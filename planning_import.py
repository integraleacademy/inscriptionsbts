"""Admin-only Yparéo import: signed extraction, review, atomic revalidation.

An import adds courses only after review. Existing courses and annual budgets
are never rewritten. Empty PDF weeks do not imply school/company/holiday days.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
import re

from flask import render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import planning as p
import planning_years
import planning_import_trainers as new_trainers
import planning_import_subjects as new_subjects
from trainer_records import ensure_optional_trainer_email
from planning_import_pdf import ImportPDFError, MAX_BYTES, MAX_COURSES, normal, parse_ypareo_pdf


def suggest_subject(label, subjects):
    source = normal(label)
    matches = [s['id'] for s in subjects if normal(s['name']) == source]
    if not matches and ('…' in label or '...' in label) and len(source) >= 12:
        matches = [s['id'] for s in subjects if normal(s['name']).startswith(source)]
    return matches[0] if len(matches) == 1 else ''


def suggest_trainer(label, trainers):
    source = normal(re.sub(r'^(?:M\.|Mme|Mlle)\s+', '', label))
    matches = [t['id'] for t in trainers if source in {
        normal(t['nom'] + ' ' + t['prenom']), normal(t['nom'] + ' ' + t['prenom'][:1]),
        normal(t['prenom'] + ' ' + t['nom'])}]
    return matches[0] if len(matches) == 1 else ''


def separate_subject_trainers(document):
    """Keep clipped subject labels separate when their PDF trainers differ."""
    trainers = {}
    for row in document['rows']:
        trainers.setdefault(row['subject_key'], set()).add(row['trainer'])
    for row in document['rows']:
        label = row['subject_key']
        row['subject_label'] = label
        if len(trainers[label]) > 1:
            identity = (label + '\0' + row['trainer']).encode()
            row['subject_key'] = 'pdf-group-' + hashlib.sha256(identity).hexdigest()


def _context(conn, promotion_id, period_id):
    promotion = p._promotion(conn, promotion_id, ready=True)
    if not isinstance(period_id, str) or not period_id:
        raise p.PlanningError('Sélectionnez une année du planning.')
    period = planning_years.select(conn, promotion, period_id)
    return promotion, period


def _signature(course):
    return tuple(course[k] for k in ('date', 'start_min', 'end_min', 'trainer_id'))


def _trainers(conn, promotion_id):
    return [dict(row) for row in conn.execute('''SELECT t.id,t.nom,t.prenom,
        EXISTS(SELECT 1 FROM trainer_promotions g WHERE g.trainer_id=t.id AND g.promotion_id=?) AS assigned
        FROM trainers t WHERE t.active=1 ORDER BY t.nom,t.prenom''', (promotion_id,))]


def review(conn, *args, **kwargs):
    # Temporary allocations let the normal course and budget checks run unchanged.
    # Always roll them back, even when this function is called outside a transaction.
    conn.execute('SAVEPOINT import_subject_review')
    try:
        return _review(conn, *args, **kwargs)
    finally:
        conn.execute('ROLLBACK TO import_subject_review')
        conn.execute('RELEASE import_subject_review')


def _review(conn, source, mappings, school_days, room_id, selected_keys=None, *, assign_trainers=False, allowed_assignments=None, trainer_drafts=None, subject_hours=None, allowed_preparations=None):
    promotion, period = _context(conn, source['promotion_id'], source['period_id'])
    if period['start_date'] != source['start_date'] or period['end_date'] != source['end_date']:
        raise p.PlanningError('Les dates de l’année ont changé. Analysez à nouveau le PDF.', status=409)
    if not isinstance(mappings, dict) or not isinstance(mappings.get('subjects'), dict):
        raise p.PlanningError('Vérifiez les correspondances de matières et de formateurs.')
    # Keep signed previews and pages opened before the per-subject UI usable.
    trainer_key = 'subject_trainers' if 'subject_trainers' in mappings else 'trainers'
    if not isinstance(mappings.get(trainer_key), dict):
        raise p.PlanningError('Vérifiez les correspondances de matières et de formateurs.')
    if not isinstance(school_days, bool):
        raise p.PlanningError('Confirmez le traitement des journées école.')
    if not isinstance(assign_trainers, bool):
        raise p.PlanningError('Vérifiez les affectations des formateurs.')
    subject_hours = {} if subject_hours is None else subject_hours
    if not isinstance(subject_hours, dict):
        raise p.PlanningError('Vérifiez les volumes annuels des matières à ajouter.')
    if room_id is not None and (not isinstance(room_id, str) or not conn.execute(
            'SELECT 1 FROM planning_rooms WHERE id=? AND active=1', (room_id,)).fetchone()):
        raise p.PlanningError('Choisissez une salle active ou laissez la salle à compléter.')
    rows = source['rows']
    source_trainers = {}
    for row in rows:
        source_trainers.setdefault(row['subject_key'], set()).add(row['trainer'])
    if any(len(trainers) > 1 for trainers in source_trainers.values()):
        raise p.PlanningError('Plusieurs formateurs partagent un intitulé dans ce PDF. '
                              'Rechargez la page, puis analysez-le à nouveau pour vérifier chaque correspondance séparément.', status=409)
    if selected_keys is not None:
        if (not isinstance(selected_keys, list) or not selected_keys or len(selected_keys) > MAX_COURSES or
                any(not isinstance(k, str) for k in selected_keys) or len(set(selected_keys)) != len(selected_keys) or
                not set(selected_keys) <= {r['key'] for r in rows}):
            raise p.PlanningError('Sélectionnez au moins un cours dans l’aperçu.')
        rows = [row for row in rows if row['key'] in selected_keys]
    rules, exceptions = p._calendar(conn, promotion['id'])
    existing = p._load_courses(conn, min(r['date'] for r in rows), max(r['date'] for r in rows))
    unavailable = p._unavailability(conn)
    used_ids = {mappings[trainer_key].get(r['subject_key'] if trainer_key == 'subject_trainers' else r['trainer']) for r in rows
                if isinstance(mappings[trainer_key].get(r['subject_key'] if trainer_key == 'subject_trainers' else r['trainer']), str)}
    pending_trainers = new_trainers.prepare(conn, source, trainer_drafts if trainer_drafts is not None else [], used_ids)
    trainers = {t['id']: t for t in _trainers(conn, promotion['id'])}
    trainers.update(pending_trainers)
    # Only this import can propose new grants; normal course APIs remain strict.
    pending_assignments = {(tid, promotion['id']) for tid, trainer in trainers.items()
        if assign_trainers and not trainer['assigned'] and (allowed_assignments is None or tid in allowed_assignments)}
    trainer_assignments = {}
    subject_preparations = {}
    accepted, results, changed_days, calendar_before = [], [], {}, {}
    for row in rows:
        item = dict(row, status='blocked', issues=[])
        sid = mappings['subjects'].get(row['subject_key'])
        tid = mappings[trainer_key].get(row['subject_key'] if trainer_key == 'subject_trainers' else row['trainer'])
        try:
            planning_years.require_dates(period, row['date'])
            if not isinstance(sid, str) or not sid or not isinstance(tid, str) or not tid:
                raise p.PlanningError('Associez la matière et le formateur de ce cours.')
            sid = new_subjects.resolve(conn, promotion, period, sid, tid, subject_hours, subject_preparations, allowed_preparations)
            allocation = planning_years.allocation(conn, sid)
            if not allocation or allocation['id'] != period['id']:
                raise p.PlanningError('Choisissez une matière préparée pour cette année du planning.')
            course = p._course(conn, dict(promotion_id=promotion['id'], subject_id=sid, trainer_id=tid,
                                        room_id=room_id, date=row['date'], start=row['start'], end=row['end']),
                               pending_trainer_assignments=pending_assignments, pending_trainers=pending_trainers)
            item.update(subject_name=course['groups'][0]['subject_name'], subject_id=sid, trainer_id=tid)
            duplicate = next((c for c in existing + accepted if _signature(c) == _signature(course) and
                              any(g['promotion_id'] == promotion['id'] and g['subject_id'] == sid for g in p._groups(c))), None)
            if duplicate:
                item.update(status='duplicate', existing_id=duplicate.get('id'))
            else:
                day = p._day(promotion, date.fromisoformat(row['date']), rules, exceptions)
                candidate_exceptions = exceptions
                if school_days and day['kind'] not in ('school', 'public_holiday'):
                    candidate_exceptions = [e for e in exceptions if e['date'] != row['date']] + [
                        dict(date=row['date'], kind='school', label='École · import Yparéo')]
                issues = p._conflicts(conn, course, pool=existing + accepted,
                    calendar=(rules, candidate_exceptions), unavailable=unavailable, pending=accepted)
                if issues:
                    item['issues'] = [i['message'] for i in issues]
                else:
                    item['status'] = 'ready'
                    accepted.append(course)
                    if (tid, promotion['id']) in pending_assignments:
                        trainer_assignments[tid] = trainers[tid]
                    calendar_before[row['date']] = {k: day[k] for k in ('kind', 'label')}
                    if day['kind'] != 'school':
                        changed_days[row['date']] = dict(date=row['date'], previous=day['label'], kind=day['kind'])
        except p.PlanningError as error:
            item['issues'] = [str(error)]
        results.append(item)
    summary = {status: sum(r['status'] == status for r in results) for status in ('ready', 'duplicate', 'blocked')}
    summary.update(total=len(results), minutes=sum(c['end_min']-c['start_min'] for c in accepted), school_days=len(changed_days))
    # A blocked/deselected row must not choose the preparation's default trainer.
    preparations = []
    for course in accepted:
        item = subject_preparations.pop(course['subject_id'], None)
        if item:
            preparations.append(dict(item, trainer_id=course['trainer_id']))
    return dict(items=results, summary=summary, calendar_before=calendar_before,
        subject_preparations=preparations,
        trainer_assignments=list(trainer_assignments.values()),
        trainer_creations=[t for tid, t in pending_trainers.items() if tid in {c['trainer_id'] for c in accepted}],
        calendar_changes=sorted(changed_days.values(), key=lambda d: d['date'])), accepted


def register_planning_import(app, guard, connect, csrf, result, fail, transact, persist):
    signer = URLSafeTimedSerializer(app.secret_key, salt='planning-ypareo-import-v1')

    def sign(data, action):
        return signer.dumps(dict(data, action=action, binding=hashlib.sha256(csrf().encode()).hexdigest()))

    def verify(token, action):
        if not isinstance(token, str) or len(token) > 400000:
            raise p.PlanningError('L’aperçu est invalide. Analysez à nouveau le PDF.', status=409)
        try:
            value = signer.loads(token, max_age=30 * 60)
        except (BadSignature, SignatureExpired):
            raise p.PlanningError('L’aperçu a expiré. Analysez à nouveau le PDF.', status=409) from None
        if value.get('action') != action or value.get('binding') != hashlib.sha256(csrf().encode()).hexdigest():
            raise p.PlanningError('Cet aperçu ne correspond pas à votre session.', status=409)
        return value

    @app.get('/admin/planning/import')
    def planning_import_admin():
        guard()
        try:
            with closing(connect()) as conn:
                promotion, period = _context(conn, request.args.get('promotion_id'), request.args.get('period_id'))
            response = app.make_response(render_template('planning_import.html', promotion=promotion,
                period=period, csrf_token=csrf(), title='Importer un planning · Intégrale Academy'))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except p.PlanningError as error:
            return fail(error)

    @app.post('/admin/planning/api/import/analyze')
    def planning_import_analyze():
        guard(True)
        try:
            if request.content_length and request.content_length > MAX_BYTES + 32768:
                raise p.PlanningError('Choisissez un PDF de 10 Mo maximum.', status=413)
            upload = request.files.get('file')
            if not upload:
                raise p.PlanningError('Choisissez le PDF du planning à importer.')
            with closing(connect()) as conn:
                promotion, period = _context(conn, request.form.get('promotion_id'), request.form.get('period_id'))
                subjects = new_subjects.choices(conn, promotion, period)
                trainers = _trainers(conn, promotion['id'])
                known_trainers = [dict(r) for r in conn.execute('SELECT id,nom,prenom,active FROM trainers')]
                rooms = [dict(row) for row in conn.execute('SELECT id,name FROM planning_rooms WHERE active=1 ORDER BY name')]
            try:
                document = parse_ypareo_pdf(upload.stream.read(MAX_BYTES + 1), period)
            except ImportPDFError as error:
                raise p.PlanningError(str(error), status=422) from None
            except Exception:
                app.logger.exception('Unable to read Ypareo planning PDF')
                raise p.PlanningError('Le PDF est illisible ou son format n’est pas reconnu. Exportez un planning groupe hebdomadaire depuis Yparéo.', status=422) from None
            separate_subject_trainers(document)
            source = dict(promotion_id=promotion['id'], period_id=period['id'],
                start_date=period['start_date'], end_date=period['end_date'], rows=document['rows'])
            source_groups = {r['subject_key']: (r['subject_label'], r['trainer']) for r in document['rows']}
            source_subjects = sorted(source_groups, key=source_groups.get)
            source_trainers = sorted({r['trainer'] for r in document['rows']})
            trainer_matches = {t: suggest_trainer(t, trainers) for t in source_trainers}
            drafts, proposed_matches, trainer_warnings = new_trainers.propose(source_trainers, known_trainers)
            source['trainer_drafts'] = drafts
            subject_trainers = {}
            for subject in source_subjects:
                matches = {proposed_matches.get(r['trainer'], trainer_matches[r['trainer']]) for r in document['rows'] if r['subject_key'] == subject}
                subject_trainers[subject] = next(iter(matches)) if len(matches) == 1 else ''
            return result(document=document, source_token=sign(source, 'source'), subjects=subjects, trainers=trainers,
                rooms=rooms, new_trainers=drafts, trainer_warnings=trainer_warnings,
                mappings=dict(subjects={s: suggest_subject(source_groups[s][0], subjects) for s in source_subjects},
                                          subject_trainers=subject_trainers, trainers=trainer_matches))
        except p.PlanningError as error:
            return fail(error)

    @app.post('/admin/planning/api/import/preview')
    def planning_import_preview():
        guard(True)
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise p.PlanningError('Les données de l’import sont invalides.')
            source = verify(payload.get('source_token'), 'source')
            mappings, school_days, room_id = payload.get('mappings'), payload.get('school_days'), payload.get('room_id') or None
            assign_trainers = payload.get('assign_trainers', False)
            trainer_drafts = payload.get('new_trainers', [])
            with closing(connect()) as conn:
                # Catalogue allocations are staged then rolled back by review.
                # Reserve the writer before reading to avoid a snapshot upgrade race.
                conn.execute('BEGIN IMMEDIATE')
                preview, _ = review(conn, source, mappings, school_days, room_id, assign_trainers=assign_trainers,
                                    trainer_drafts=trainer_drafts, subject_hours=payload.get('subject_hours'))
            ready = [r['key'] for r in preview['items'] if r['status'] == 'ready']
            token = sign(dict(source=source, mappings=mappings, school_days=school_days,
                              room_id=room_id, ready=ready, calendar_before=preview['calendar_before'],
                              assign_trainers=assign_trainers,
                              subject_hours={new_subjects.PREFIX + s['catalog_subject_id']: s['planned_hours']
                                             for s in preview['subject_preparations']},
                              new_trainers=trainer_drafts,
                              trainer_assignment_ids=[t['id'] for t in preview['trainer_assignments']]), 'review')
            return result(preview, preview_token=token)
        except p.PlanningError as error:
            return fail(error)

    @app.post('/admin/planning/api/import/commit')
    def planning_import_commit():
        def operation(conn, payload):
            approved = verify(payload.get('preview_token'), 'review')
            selected = payload.get('selected_keys')
            if not isinstance(selected, list) or any(not isinstance(k, str) for k in selected) or not set(selected) <= set(approved['ready']):
                raise p.PlanningError('Choisissez uniquement les cours prêts dans cet aperçu.')
            preview, courses = review(conn, approved['source'], approved['mappings'],
                                      approved['school_days'], approved['room_id'], selected,
                                      assign_trainers=approved.get('assign_trainers', False),
                                      subject_hours=approved.get('subject_hours', {}),
                                      allowed_preparations=set(approved.get('subject_hours', {})),
                                      trainer_drafts=approved.get('new_trainers', []),
                                      allowed_assignments=approved.get('trainer_assignment_ids', []))
            if any(approved['calendar_before'].get(day) != state for day, state in preview['calendar_before'].items()):
                raise p.PlanningError('L’alternance a changé depuis l’aperçu. Vérifiez à nouveau les cours avant d’importer.', status=409)
            if preview['summary']['blocked']:
                raise p.PlanningError('Le planning a changé : refaites l’aperçu. Aucun cours n’a été ajouté.',
                    [dict(date=r['date'], type='import_conflict', message=' '.join(r['issues']))
                     for r in preview['items'] if r['status'] == 'blocked'], 409)
            # BEGIN IMMEDIATE from transact serializes duplicate/conflict checks.
            promotion_id = approved['source']['promotion_id']
            created = preview['trainer_creations']
            if created:
                ensure_optional_trainer_email(conn)
                now = datetime.now(timezone.utc).isoformat()
                for trainer in created:
                    conn.execute('''INSERT INTO trainers(id,nom,prenom,email,active,version,created_at,updated_at)
                        VALUES(?,?,?,?,1,1,?,?)''', (trainer['id'], trainer['nom'], trainer['prenom'], trainer['email'], now, now))
            for trainer in preview['trainer_assignments']:
                conn.execute('INSERT INTO trainer_promotions(trainer_id,promotion_id) VALUES(?,?)', (trainer['id'], promotion_id))
                if trainer['id'] not in {t['id'] for t in created}:
                    conn.execute('UPDATE trainers SET version=version+1 WHERE id=?', (trainer['id'],))
                if p._has_table(conn, 'trainer_access_tokens'):
                    conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id=?', (trainer['id'],))
            for subject in preview['subject_preparations']:
                new_subjects.save(conn, subject)
            for change in preview['calendar_changes']:
                conn.execute('''INSERT INTO planning_day_exceptions(promotion_id,date,kind,label) VALUES(?,?,'school',?)
                    ON CONFLICT(promotion_id,date) DO UPDATE SET kind=excluded.kind,label=excluded.label''',
                    (promotion_id, change['date'], 'École · import Yparéo'))
            if preview['calendar_changes']:
                conn.execute('''INSERT INTO planning_calendar_versions VALUES(?,1)
                    ON CONFLICT(promotion_id) DO UPDATE SET version=version+1''', (approved['source']['period_id'],))
            ids = [persist(conn, course) for course in courses]
            return dict(count=len(ids), course_ids=ids, duplicates=preview['summary']['duplicate'], created_trainers=len(created),
                        prepared_subjects=len(preview['subject_preparations']),
                        message=f'{len(ids)} cours importé(s). {preview["summary"]["duplicate"]} doublon(s) ignoré(s).' +
                                (f' {len(created)} fiche(s) formateur créée(s).' if created else ''))
        return transact(operation)
