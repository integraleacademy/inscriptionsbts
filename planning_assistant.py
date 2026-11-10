"""Session-bound, reviewable admin operations on the authoritative planning data."""
from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta
import hashlib
import os
import secrets
import time

from itsdangerous import BadData
import planning_assistant_language as language
import planning_room_availability as room_view
import planning_years
import subject_references
from planning import (PlanningError, _budget_minutes, _clock, _conflicts, _course, _iso, _load_courses,
                      _minutes, _promotion, _subject_minutes, remove_promotion_courses)
from planning_room_calendar import apply_room_moves
from planning_rooms import available_rooms, configured, is_physical_room
from planning_import_pdf import normal
from planning_assistant_replies import Answer, at_location, availability_answer, joined, room_options

DAY_NAMES = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']


def french(day):
    return date.fromisoformat(day).strftime('%d/%m/%Y')


def date_slot(slot):
    day = date.fromisoformat(slot['date'])
    return f"{DAY_NAMES[day.weekday()]} {french(slot['date'])} · {_clock(slot['start_min'])}–{_clock(slot['end_min'])}"


def interval(first, last):
    return french(first) if first == last else f'du {french(first)} au {french(last)}'


def room(conn, rid, label):
    row = conn.execute('SELECT * FROM planning_rooms WHERE id=?', (rid,)).fetchone()
    if not row:
        raise PlanningError('Précisez ' + label + ' avec son nom dans le répertoire.')
    if not is_physical_room(row['name']):
        raise PlanningError(f"« {row['name']} » indique une affectation en attente. Choisissez une salle du répertoire.")
    if not row['active']:
        raise PlanningError(f"{row['name']} est inactive. Choisissez une salle active.")
    return dict(row)


def slots_count(count):
    return f"{count} créneau" if count == 1 else f"{count} créneaux"


def booking_stamp(row):
    return [row['key'], row.get('version'), row.get('revision'), row.get('room_version'), row['room_id'],
            row['date'], row['start_min'], row['end_min']]


def replace_room(conn, intent):
    room_view.require_ready(conn)
    source = room(conn, intent['source_room_id'], 'la salle à remplacer ou à fermer')
    target = room(conn, intent['room_id'], 'la salle de remplacement') if intent['room_id'] else None
    close = intent['close_source']
    if not target and not close:
        raise PlanningError('Dans quelle salle souhaitez-vous déplacer les réservations ?')
    if target and target['id'] == source['id']:
        raise PlanningError('Choisissez deux salles différentes.')
    if not intent['from_date']:
        raise PlanningError('À partir de quelle date ce changement doit-il s’appliquer ?')
    first = _iso(intent['from_date']).isoformat()
    last = _iso(intent['to_date']).isoformat() if intent['to_date'] else room_view.OPEN_END
    if last < first:
        raise PlanningError('La fin de la période doit suivre son début.')
    label = 'à partir du ' + french(first) if last == room_view.OPEN_END else interval(first, last)
    blocks = room_view.closures(conn, first, last)
    covered = any(b['room_id'] == source['id'] and b['start_date'] <= first and b['end_date'] >= last
                  and b['start_min'] == 0 and b['end_min'] == 1440 for b in blocks)
    need_closure = close and not covered
    rows = room_view.bookings(conn, first, last)
    selected = sorted((r for r in rows if r['room_id'] == source['id']),
                      key=lambda r: (r['date'], r['start_min'], r['key']))
    if any(r.get('pending') for r in selected):
        raise PlanningError('Une session de cette salle est en cours de synchronisation. Réessayez dans un instant.', status=409)
    if selected and not target:
        return Answer(f"{source['name']} compte {slots_count(len(selected))} à déplacer {label}. Quelle salle doit les accueillir ?",
                      [f"{date_slot(r)} · {r['title']}" for r in selected])
    if not selected and not need_closure:
        return Answer(f"{source['name']} est déjà indisponible {label}." if close else
                      f"Aucune réservation à déplacer dans {source['name']} {label}.")
    details = []
    if selected:
        occupied = defaultdict(list)
        for r in rows:
            if r['room_id'] == target['id']:
                occupied[r['date']].append(r)
        target_blocks = [b for b in blocks if b['room_id'] == target['id']]
        collisions = []
        for slot in selected:
            day = slot['date']
            others = occupied[day] + [b for b in target_blocks if b['start_date'] <= day <= b['end_date']]
            for other in others:
                if slot['start_min'] < other['end_min'] and slot['end_min'] > other['start_min']:
                    collisions.append(f"{date_slot(slot)} · {slot['title']} / {other.get('title') or other.get('reason')}")
            occupied[day].append(slot)
            details.append(f"{date_slot(slot)} · {slot['title']}" +
                           (f" · {slot['promotion_name']}" if slot.get('promotion_name') else ''))
        if collisions:
            return Answer(f"Le remplacement par {target['name']} est bloqué. Choisissez une autre salle ou libérez les créneaux suivants.", collisions)
    parts = []
    if selected:
        parts.append(f"Déplacer {slots_count(len(selected))} de {source['name']} vers {target['name']} {label}.")
    if need_closure:
        parts.append(f"Rendre {source['name']} indisponible toute la journée {label}.")

    def apply(conn):
        if selected:
            apply_room_moves(conn, selected, target['id'])
        if need_closure:
            conn.execute('''INSERT INTO planning_room_unavailability
                (id,room_id,start_date,end_date,start_min,end_min,reason) VALUES(?,?,?,?,0,1440,?)''',
                (secrets.token_urlsafe(24), source['id'], first, last, 'Salle indisponible' +
                 (f" · remplacement par {target['name']}" if target else '')))
        result = [f"Affectation enregistrée pour {slots_count(len(selected))} dans {target['name']}."] if selected else []
        if close:
            result.append(f"{source['name']} est indisponible {label}.")
        return ' '.join(result)

    return Answer(' '.join(parts), details, [booking_stamp(r) for r in selected], 'Appliquer le changement de salle', apply)


def check_availability(conn, intent):
    if not intent['from_date'] or not intent['to_date']:
        raise PlanningError('Quels jours ou quelle période souhaitez-vous vérifier ?')
    data = room_view.availability(conn, intent['from_date'], intent['to_date'], intent['start'] or '08:00',
                                  intent['end'] or '18:00', intent['weekdays'] or room_view.SCHOOL_DAYS)
    dates = data['dates']
    if not dates:
        return Answer('Aucun des jours demandés ne figure dans cette période. Précisez les jours à vérifier.')
    rooms = [r for r in data['rooms'] if r['active']]
    if intent['room_id']:
        chosen = room(conn, intent['room_id'], 'la salle à vérifier')
        rooms = [r for r in rooms if r['id'] == chosen['id']]
    return availability_answer(data, at_location(rooms, intent.get('location')), intent.get('location'))


def resolve_course_filter(courses, value, id_key, name_key, label):
    needle = normal(value)
    if not needle:
        raise PlanningError('Précisez ' + label + '.')
    names = {c[id_key]: c[name_key] for c in courses if c.get(id_key)}
    exact = [k for k, v in names.items() if normal(v) == needle]
    matches = exact or [k for k, v in names.items() if set(needle.split()) <= set(normal(v).split()) or
                        (needle == 'cejm' and {'culture', 'economique', 'juridique', 'manageriale'} <= set(normal(v).split()))]
    if len(matches) > 1:
        raise PlanningError(f"Plusieurs correspondances pour « {value} ». Précisez {label} : " +
                            ', '.join(names[k] for k in matches) + '.')
    if not matches:
        raise PlanningError(f"Aucun cours ne correspond à « {value} » dans cette année du planning. Vérifiez {label}.")
    return matches[0]


def planning_selection(conn, intent, context):
    pid = intent['promotion_id'] or context['promotion_id']
    if not pid:
        raise PlanningError('Pour quelle promotion et quelle année scolaire ?')
    promotion = _promotion(conn, pid, ready=True)
    period_id = intent['period_id'] or (context['period_id'] if pid == context['promotion_id'] else None)
    choices = planning_years.periods(promotion)
    if not period_id and len(choices) != 1:
        raise PlanningError(f"Précisez l’année de {promotion['nom']} : " + ', '.join(p['label'] for p in choices) + '.')
    period = planning_years.select(conn, promotion, period_id)
    if not period:
        raise PlanningError('Les dates de cette année de formation doivent être renseignées.')
    start, end = period['start_date'], period['end_date']
    first = _iso(intent['from_date']).isoformat() if intent['from_date'] else max(start, language.today())
    if not intent['from_date'] and intent['whole_period']:
        first = start
    last = _iso(intent['to_date']).isoformat() if intent['to_date'] else end
    first, last = max(first, start), min(last, end)
    if last < first:
        raise PlanningError(f"La période demandée ne recoupe pas {promotion['nom']} — {period['label']} ({interval(start, end)}).")
    rows = [c for c in _load_courses(conn, start, end, pid) if c['kind'] == 'course']
    for key, id_key, name_key, label in [('subject', 'display_subject_id', 'display_subject_name', 'la matière'),
                                          ('trainer', 'trainer_id', 'trainer_name', 'le formateur')]:
        if intent[key]:
            match = resolve_course_filter(rows, intent[key], id_key, name_key, label)
            rows = [c for c in rows if c[id_key] == match]
    days = intent['weekdays']
    for key in ('start', 'end'):
        if intent[key]:
            _minutes(intent[key], end=key == 'end')
            rows = [c for c in rows if c[key] == intent[key]]
    selected = [c for c in rows if first <= c['date'] <= last and
                (not days or date.fromisoformat(c['date']).weekday() in days)]
    scope = f"{promotion['nom']} · {period['label']} · {interval(first, last)}"
    return period, selected, scope


def course_label(c):
    shared = ' · cours commun à ' + ', '.join(g['promotion_name'] for g in c['groups']) if c['is_shared'] else ''
    return f"{date_slot(c)} · {c['display_subject_name']} · {c['trainer_name']} · {c['room_name'] or 'sans salle'}{shared}"


def move_courses(conn, intent, period, rows, scope, persist):
    if not any(intent[k] is not None for k in ('new_date', 'new_weekday', 'new_start', 'new_end')):
        raise PlanningError('À quel jour ou à quels horaires souhaitez-vous déplacer le cours ?')
    proposals = []
    for current in rows:
        day = date.fromisoformat(current['date'])
        if intent['new_date']:
            day = _iso(intent['new_date'])
        elif intent['new_weekday'] is not None:
            day += timedelta(days=intent['new_weekday'] - day.weekday())
        planning_years.require_dates(period, day.isoformat())
        change = dict(date=day.isoformat(), start=intent['new_start'] or current['start'], end=intent['new_end'] or current['end'])
        if any(current[k] != v for k, v in change.items()):
            proposals.append((current, _course(conn, change, current)))
    if not proposals:
        return Answer(scope + '\nLes cours correspondent déjà à ces horaires.')

    # Compare the final positions together, even when one course vacates another's destination.
    ids = {old['id'] for old, _ in proposals}
    target_days = {new['date'] for _, new in proposals}
    pool = defaultdict(list)
    for other in _load_courses(conn, min(target_days), max(target_days)):
        if other['id'] not in ids:
            pool[other['date']].append(other)
    deltas = defaultdict(int)
    errors = []
    for old, new in proposals:
        issues = _conflicts(conn, new, pool=pool[new['date']], include_budget=False)
        errors.extend(f"{date_slot(new)} · {issue['message']}" for issue in issues)
        pool[new['date']].append(new)
        for group in new['groups']:
            deltas[group['subject_id']] += new['end_min'] - new['start_min'] - old['duration_minutes']
    for sid, delta in deltas.items():
        subject = conn.execute('SELECT name,planned_hours FROM planning_subjects WHERE id=?', (sid,)).fetchone()
        limit = _budget_minutes(subject['planned_hours'])
        if limit is None or _subject_minutes(conn, sid) + delta > limit:
            errors.append(f"{subject['name']} · vérifiez le volume horaire annuel disponible.")
    if errors:
        return Answer(scope + '\nDéplacement impossible aux horaires demandés.', list(dict.fromkeys(errors)))
    details = [f"{course_label(old)} → {date_slot(new)}" for old, new in proposals]

    def apply(conn):
        for old, new in proposals:
            persist(conn, new, old['id'])
        return f"Déplacement enregistré pour {len(proposals)} cours."

    return Answer(f"Je peux déplacer {len(proposals)} cours. Voici les séances à vérifier avant de confirmer.\n{scope}", details, [[c['id'], c['version']] for c in rows],
                  'Confirmer le déplacement', apply)


def course_action(conn, intent, context, persist):
    action = intent['action']
    if action == 'remove_courses':
        if not (intent['subject'] or intent['trainer'] or intent['all_courses'] or
                (intent['from_date'] and intent['from_date'] == intent['to_date'] and intent['start'])):
            raise PlanningError('Quel cours souhaitez-vous retirer ? Précisez la matière, le formateur ou « tous les cours » de la période.')
        if not intent['from_date'] and not intent['whole_period']:
            raise PlanningError('À quelle date ou sur quelle période faut-il retirer ces cours ?')
    if action == 'move_courses' and not (intent['subject'] or intent['trainer'] or intent['all_courses'] or
                                        (intent['from_date'] and intent['start'])):
        raise PlanningError('Précisez la matière, le formateur ou le créneau à déplacer.')
    period, rows, scope = planning_selection(conn, intent, context)
    if not rows:
        return Answer(scope + '\nAucun cours programmé ne correspond à ces critères.')
    if action == 'list_courses':
        details = [course_label(c) for c in rows]
        title = f"J’ai trouvé {len(rows)} cours pour cette sélection."
        fragments = dict(groupe=_promotion(conn, period['promotion_id'])['nom'], nombre=f'{len(rows)} cours',
                         periode=scope.rsplit(' · ', 1)[-1])
        for i, line in enumerate(details[:5], 1):
            fragments[f'cours{i}'] = line
        return Answer(title + '\n' + scope, details, evidence=dict(resultat='Cours confirmés du planning dans l’ordre chronologique.',
                      fragments=fragments, obligatoires=[['groupe'], ['nombre'], ['periode']]))
    if (action in ('remove_courses', 'move_courses') and len(rows) > 1 and intent['from_date']
            and intent['from_date'] == intent['to_date'] and not intent['all_courses']):
        return Answer(f"{scope}\nPlusieurs cours correspondent ce jour-là. Précisez l’horaire ou indiquez que la demande concerne tous ces cours.",
                      [course_label(c) for c in rows])
    if action == 'move_courses':
        return move_courses(conn, intent, period, rows, scope, persist)
    stamps = [[c['id'], c['version'], c['promotion_ids']] for c in rows]
    if action == 'remove_courses':
        def apply(conn):
            shared = remove_promotion_courses(conn, rows, period['promotion_id'])
            return f"Suppression enregistrée pour {len(rows)} cours de cette promotion." + (f" Les autres promotions gardent leurs cours en commun ({shared})." if shared else '')
        shared = sum(c['is_shared'] for c in rows)
        message = f"Je peux retirer {len(rows)} cours du planning de cette promotion.\n{scope}."
        if shared:
            message += f" Les autres promotions garderont leurs cours partagés ({shared})."
        return Answer(message, [course_label(c) for c in rows], stamps, 'Confirmer la suppression', apply)

    choices = room_options(at_location(available_rooms(conn, rows), intent.get('location')))
    names = ', '.join(r['name'] for r in choices) or 'Aucune salle commune à ces créneaux'
    if action == 'promotion_rooms' and intent['room_id']:
        chosen = room(conn, intent['room_id'], 'la salle à vérifier')
        if not at_location([chosen], intent.get('location')):
            return Answer(f"Le nom de {chosen['name']} ne précise pas le site demandé. Voulez-vous vérifier cette salle sur les créneaux de la promotion ?")
        possible = chosen['id'] in {r['id'] for r in choices}
        message = (f"{chosen['name']} peut accueillir les {len(rows)} cours." if possible else
                   f"{chosen['name']} ne peut pas accueillir tous les cours. Autres possibilités : {names}.")
        return Answer(scope + '\n' + message, [course_label(c) for c in rows])
    if action == 'promotion_rooms':
        if not choices:
            suffix = f" dont le nom indique « {intent['location']} »" if intent.get('location') else ''
            return Answer(f"Je ne trouve aucune salle{suffix} qui soit libre pour tous les cours de cette promotion. "
                          "Tu peux préciser une période plus courte.", [course_label(c) for c in rows])
        fragments = {'groupe': _promotion(conn, period['promotion_id'])['nom'], 'cours': f"{len(rows)} cours"}
        for i, choice in enumerate(choices[:8], 1):
            fragments[f'salle{i}'] = f"**{choice['name']}**"
        refs = [k for k in fragments if k.startswith('salle')]
        facts = dict(resultat='Les salles indiquées sont libres sur tous les cours de la sélection.', fragments=fragments,
                     obligatoires=[['groupe'], ['cours'], refs])
        names = joined([r['name'] for r in choices])
        return Answer(f"Pour les {len(rows)} cours de {fragments['groupe']}, tu peux choisir {names}.",
                      [course_label(c) for c in rows], evidence=facts)
    target = room(conn, intent['room_id'], 'la salle à affecter')
    if target['id'] not in {r['id'] for r in choices}:
        return Answer(f"{scope}\n{target['name']} ne peut pas accueillir tous les cours. Autres possibilités : {names}.")
    selected = [dict(c, source='bts') for c in rows if c['room_id'] != target['id']]
    if not selected:
        return Answer(f"{scope}\nTous les cours sont déjà dans {target['name']}.")
    def apply(conn):
        apply_room_moves(conn, selected, target['id'])
        return f"{target['name']} affectée à {len(selected)} cours."
    return Answer(f"{scope}\nAffecter {target['name']} à {len(selected)} cours.", [course_label(c) for c in selected],
                  stamps, 'Confirmer l’affectation', apply)


def build(conn, intent, context, persist):
    action = intent['action']
    if action == 'clarify':
        return Answer(intent['question'] or 'Pouvez-vous préciser la promotion, les dates ou la salle concernée ?')
    # Do not silently ignore a narrower filter suggested by the interpreter.
    allowed = {'from_date', 'to_date'}
    if action == 'replace_room':
        allowed.update(('source_room_id', 'room_id', 'close_source'))
    elif action == 'availability':
        allowed.update(('room_id', 'location', 'start', 'end', 'weekdays'))
    else:
        allowed.update(('subject', 'trainer', 'start', 'end', 'weekdays', 'whole_period', 'all_courses'))
        if action == 'move_courses':
            allowed.update(('new_start', 'new_end', 'new_date', 'new_weekday'))
        if action in ('assign_room', 'promotion_rooms'):
            allowed.add('room_id')
        if action == 'promotion_rooms':
            allowed.add('location')
    if action not in ('availability', 'replace_room'):
        allowed.update(('promotion_id', 'period_id'))
    fields = set(intent) - allowed - {'action', 'question'}
    if any(intent[k] is not None and intent[k] is not False and intent[k] != [] for k in fields):
        raise PlanningError('La sélection combine des critères incompatibles. Précisez la modification ou la recherche souhaitée.')
    if action == 'replace_room':
        return replace_room(conn, intent)
    if action == 'availability':
        return check_availability(conn, intent)
    return course_action(conn, intent, context, persist)


def page_context(data):
    context = data.get('context')
    if not isinstance(context, dict) or context.get('page') not in ('salles', 'planning'):
        raise PlanningError('Rechargez la page pour retrouver le contexte du planning.')
    result = {'page': context['page']}
    for key in ('promotion_id', 'period_id'):
        value = context.get(key) or None
        if value is not None and (not isinstance(value, str) or len(value) > 180):
            raise PlanningError('Promotion ou année invalide.')
        result[key] = value
    return result


def resolve_relative_week(intent, previous):
    shift = intent.get('week_shift')
    if shift is None:
        return intent
    if intent['action'] != 'availability' or not previous or previous.get('action') != 'availability':
        raise PlanningError('De quelle semaine souhaitez-vous partir ? Indiquez une date pour vérifier les salles.')
    ref = _iso(previous['to_date'] if shift > 0 else previous['from_date'])
    try:
        monday = ref + timedelta(days=7*shift - ref.weekday())
        sunday = monday + timedelta(days=6)
    except OverflowError:
        raise PlanningError('Cette semaine dépasse les dates prises en charge.') from None
    return dict(intent, from_date=monday.isoformat(), to_date=sunday.isoformat(), week_shift=None)


def register(app, connect, guard, body, result, fail, transact, csrf, serializer, persist):
    revision = os.getenv('RENDER_GIT_COMMIT')
    if revision and revision == os.getenv('PLANNING_CHAT_VERIFY_COMMIT'):
        from scripts.check_planning_chat import start_release_check
        start_release_check(app, connect, revision)

    def binding():
        return hashlib.sha256(csrf().encode()).hexdigest()

    def previous_search(data, context):
        token = data.get('conversation_token')
        if not isinstance(token, str) or len(token) > 12000:
            return None
        try:
            state = serializer.loads(token, max_age=4*3600)
        except BadData:
            return None
        if (isinstance(state, dict) and state.get('action') == 'planning_conversation'
                and state.get('binding') == binding() and state.get('context') == context):
            return state.get('search')
        return None

    @app.context_processor
    def planning_chat_model():
        return dict(planning_chat_model=language.model_name())

    @app.post('/admin/planning/api/assistant')
    def ask_planning_assistant():
        guard(True)
        try:
            data = body()
            context = page_context(data)
            message = data.get('message')
            history = data.get('history', [])
            if not isinstance(message, str) or not message.strip() or len(message) > 3000:
                raise PlanningError('Écrivez une demande de 1 à 3 000 caractères.')
            if not isinstance(history, list) or len(history) > 10 or any(
                not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') or
                not isinstance(item.get('text'), str) or len(item['text']) > 3000 for item in history):
                raise PlanningError('La conversation est trop longue. Commencez une nouvelle demande.')
            history = [{'role': item['role'], 'text': item['text']} for item in history]
            previous = previous_search(data, context)
            with closing(connect()) as conn:
                if not subject_references.key_configured(conn):
                    raise PlanningError('Pour activer le tchat, ajoutez la clé OpenAI dans Paramètres → OpenAI.', status=503)
                key = subject_references.api_key(app, conn)
                inventory = language.catalog(conn)
                # The provider call must never hold the SQLite writer lock.
                conn.execute('BEGIN IMMEDIATE')
                now = time.time()
                conn.execute('CREATE TABLE IF NOT EXISTS planning_assistant_usage(owner TEXT NOT NULL,created_at REAL NOT NULL)')
                conn.execute('DELETE FROM planning_assistant_usage WHERE created_at < ?', (now-600,))
                if conn.execute('SELECT count(*) FROM planning_assistant_usage WHERE owner=?', (binding(),)).fetchone()[0] >= 40:
                    raise PlanningError('Vous avez atteint 40 demandes en 10 minutes. Réessayez dans quelques instants.', status=429)
                conn.execute('INSERT INTO planning_assistant_usage VALUES(?,?)', (binding(), now))
                conn.commit()
            intent = language.interpret(key, message.strip(), history, inventory, context, previous)
            intent = resolve_relative_week(intent, previous)
            with closing(connect()) as conn:
                conn.execute('BEGIN')
                answer = build(conn, intent, context, persist)
                warning = ('La liaison avec les sessions externes est inactive. Seules les réservations enregistrées sont prises en compte.'
                           if intent['action'] in ('availability', 'promotion_rooms', 'assign_room', 'replace_room') and not configured() else '')
            token = None
            if answer.apply:
                token = serializer.dumps(dict(action='planning_assistant', binding=binding(), intent=intent,
                                              context=context, digest=answer.digest()))
            # The editorial pass uses a finished read-only snapshot and cannot influence any mutation.
            reply = language.compose(key, message, history, answer.evidence, answer.message) if answer.evidence else answer.message
            search = previous if intent['action'] == 'clarify' else None
            if intent['action'] in ('availability', 'promotion_rooms', 'list_courses'):
                search = {k: v for k, v in intent.items() if v and k != 'question'}
                search['derniere_reponse'] = reply[:1400]
                if intent['action'] == 'availability':
                    search.update(weekdays=intent['weekdays'] or room_view.SCHOOL_DAYS,
                                  start=intent['start'] or '08:00', end=intent['end'] or '18:00')
            conversation_token = (serializer.dumps(dict(action='planning_conversation', binding=binding(),
                                  context=context, search=search)) if search else None)
            return result(message=reply, details=answer.details, detail_label=answer.detail_label, warning=warning,
                          preview_token=token, confirm_label=answer.confirm_label, conversation_token=conversation_token)
        except PlanningError as error:
            return fail(error)

    @app.post('/admin/planning/api/assistant/confirmer')
    def confirm_planning_assistant():
        def operation(conn, data):
            token = data.get('preview_token')
            if not isinstance(token, str) or len(token) > 16000:
                raise PlanningError('Vérifiez la proposition avant de confirmer.', status=409)
            try:
                preview = serializer.loads(token, max_age=15*60)
            except BadData:
                raise PlanningError('Cette proposition a expiré. Relancez la demande.', status=409) from None
            if (not isinstance(preview, dict) or preview.get('action') != 'planning_assistant' or
                    preview.get('binding') != binding() or page_context(data) != preview['context']):
                raise PlanningError('Cette proposition appartient à un autre planning ou à une autre session.', status=409)
            try:
                answer = build(conn, preview['intent'], preview['context'], persist)
            except PlanningError as error:
                raise PlanningError(f"Le planning a changé. {error} Relancez la demande.", status=409) from None
            if not answer.apply or answer.digest() != preview['digest']:
                raise PlanningError('Le planning a changé depuis l’aperçu. Relancez la demande pour vérifier les nouveaux créneaux.', status=409)
            return dict(message=answer.apply(conn))
        return transact(operation)
