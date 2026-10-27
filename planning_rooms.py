"""The room ledger is the authority for BTS and session reservations.

External writers prepare while holding their source-store lock, save durably,
then finish. Both the previous and proposed slots remain occupied until finish.
A crashed writer reconciles against the durable source before its next change.
"""
from contextlib import closing
from datetime import datetime, timezone
import hmac
import json
import os
import secrets
from urllib.parse import quote

import requests
from flask import request, session, abort, g, has_request_context
from itsdangerous import BadSignature, SignatureExpired


def schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_room_owners(
        owner TEXT PRIMARY KEY, revision TEXT NOT NULL, slots TEXT NOT NULL,
        pending_revision TEXT, pending_slots TEXT, pending_token TEXT,
        title TEXT NOT NULL, url TEXT NOT NULL)''')
    conn.execute('CREATE TABLE IF NOT EXISTS planning_room_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS planning_room_aliases(name TEXT PRIMARY KEY,room_id TEXT NOT NULL)')


def configured():
    return bool(os.environ.get('SHARED_ROOMS_TOKEN') and os.environ.get('SESSION_ROOMS_URL'))


def ready(conn):
    return not configured() or bool(conn.execute("SELECT 1 FROM planning_room_meta WHERE key='ready' AND value='1'").fetchone())


def external_slots(conn, exclude_owner=None, room_day=None):
    # Reuse the parsed ledger during one availability request, but invalidate
    # after either this connection or another writer changes the database.
    ledger_key=(conn.total_changes,conn.execute('PRAGMA data_version').fetchone()[0])
    cached=getattr(g,'_room_ledger',None) if has_request_context() else None
    if cached and cached[0] is conn and cached[1]==ledger_key:
        rows=cached[3].get(room_day,[]) if room_day else cached[2]
        return [row for row in rows if row['owner']!=exclude_owner]
    result = []
    for row in conn.execute('SELECT * FROM planning_room_owners'):
        seen = set()
        for field in ('slots', 'pending_slots'):
            for slot in json.loads(row[field] or '[]'):
                key = (slot['room_id'], slot['date'], slot['start_min'], slot['end_min'])
                if key not in seen:
                    result.append(dict(slot, owner=row['owner'], title=row['title'], url=row['url'],
                                       source='session', pending=bool(row['pending_token'])))
                    seen.add(key)
    index={}
    for row in result:index.setdefault((row['room_id'],row['date']),[]).append(row)
    if has_request_context():g._room_ledger=(conn,ledger_key,result,index)
    rows=index.get(room_day,[]) if room_day else result
    return [row for row in rows if row['owner']!=exclude_owner]


def overlap(a, b):
    return (a.get('room_id') and a['room_id'] == b.get('room_id') and a['date'] == b['date']
            and a['start_min'] < b['end_min'] and a['end_min'] > b['start_min'])


def room_conflicts(conn, course, exclude_owner=None, include_courses=False, exclude_ids=()):
    from planning import _clock, _load_courses
    if not course.get('room_id'):
        return []
    if not ready(conn):
        return [dict(type='room_sync', message='La liaison des salles est en cours d’initialisation. Réessayez après la synchronisation des sessions.')]
    rows = external_slots(conn, exclude_owner, (course['room_id'],course['date']))
    if include_courses:
        rows += [dict(c, source='bts') for c in _load_courses(conn, course['date'], course['date']) if c['id'] not in exclude_ids]
    return [dict(type='room', date=c['date'], room_id=c['room_id'], owner=c.get('owner'), course_id=c.get('id'),
                 message='Salle déjà réservée : ' + (c.get('title') or c.get('subject_name') or 'Session') +
                         ' · ' + _clock(c['start_min']) + '–' + _clock(c['end_min'])) for c in rows if overlap(course, c)]


def room_used(conn, room_id):
    return any(s['room_id'] == room_id for s in external_slots(conn))


def normalize(conn, raw, bootstrap=False):
    from planning import PlanningError, _iso, _minutes
    if not isinstance(raw, list) or len(raw) > 5000:
        raise PlanningError('Liste des réservations invalide.')
    rooms = {r['id']: dict(r) for r in conn.execute('SELECT * FROM planning_rooms')}
    names = {r['name'].strip().casefold(): r['id'] for r in rooms.values()}
    names.update({r['name']:r['room_id'] for r in conn.execute('SELECT * FROM planning_room_aliases')})
    groups = {}
    for item in raw:
        if not isinstance(item, dict):
            raise PlanningError('Créneau de salle invalide.')
        rid = item.get('room_id')
        name = str(item.get('room_name') or '').strip()
        if not rid and name:
            rid = names.get(name.casefold())
            if not rid and bootstrap:
                rid = secrets.token_urlsafe(24)
                conn.execute('INSERT INTO planning_rooms(id,name) VALUES(?,?)', (rid, name[:100]))
                rooms[rid] = dict(id=rid, active=1); names[name.casefold()] = rid
            if rid and bootstrap:
                conn.execute('INSERT OR IGNORE INTO planning_room_aliases(name,room_id) VALUES(?,?)',(name.casefold(),rid))
        if not isinstance(rid,str) or not rid or rid not in rooms or not rooms[rid]['active']:
            raise PlanningError('Salle inconnue ou inactive : ' + name + '. Choisissez-la dans le planning commun.')
        day = _iso(item.get('date')).isoformat()
        start, end = _minutes(item.get('start')), _minutes(item.get('end'), True)
        if start >= end:
            raise PlanningError('Les horaires de réservation sont invalides.')
        groups.setdefault((rid, day), []).append((start, end))
    result = []
    for (rid, day), spans in sorted(groups.items()):
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        result.extend(dict(room_id=rid, date=day, start_min=a, end_min=b) for a, b in merged)
    return result


def owner_data(data):
    from planning import PlanningError
    owner, revision = data.get('owner'), data.get('revision')
    if not isinstance(owner, str) or not owner.startswith(('session:', 'formation:')) or len(owner) > 180:
        raise PlanningError('Référence de session invalide.')
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
        raise PlanningError('Version de session invalide.')
    title = str(data.get('title') or 'Session')[:200]
    base = os.environ.get('SESSION_ROOMS_URL', '').rstrip('/')
    route = '/sessions/' if owner.startswith('session:') else '/formation/'
    suffix = '' if owner.startswith('session:') else '/modifier'
    return owner, revision, title, base + route + quote(owner.split(':', 1)[1], safe='') + suffix


def prepare(conn, data):
    from planning import PlanningError
    if not ready(conn):
        raise PlanningError('La première synchronisation des salles doit être terminée avant de modifier les sessions.',status=503)
    owner, revision, title, url = owner_data(data)
    row = conn.execute('SELECT * FROM planning_room_owners WHERE owner=?', (owner,)).fetchone()
    previous = data.get('previous_revision')
    # The caller holds its source lock. Its previous revision is durable truth.
    if row and row['pending_token']:
        if previous == row['pending_revision']:
            conn.execute('UPDATE planning_room_owners SET revision=pending_revision,slots=pending_slots,pending_revision=NULL,pending_slots=NULL,pending_token=NULL WHERE owner=?', (owner,))
        elif previous == row['revision']:
            conn.execute('UPDATE planning_room_owners SET pending_revision=NULL,pending_slots=NULL,pending_token=NULL WHERE owner=?', (owner,))
        else:
            raise PlanningError('La réservation attend une réconciliation de la session.', status=409)
        row = conn.execute('SELECT * FROM planning_room_owners WHERE owner=?', (owner,)).fetchone()
    if row and row['revision'] != previous:
        raise PlanningError('Cette session a changé. Rechargez ses réservations.', status=409)
    if row and revision == row['revision']:
        return dict(token=None)
    slots = normalize(conn, data.get('slots'))
    issues = []
    for slot in slots:
        issues.extend(room_conflicts(conn, slot, exclude_owner=owner, include_courses=True))
    if issues:
        raise PlanningError('Salle indisponible. La session n’a pas été modifiée.', issues[:80], 409)
    token = secrets.token_urlsafe(32)
    if not row:
        conn.execute('INSERT INTO planning_room_owners(owner,revision,slots,title,url) VALUES(?,?,?,?,?)',
                     (owner, previous or '0' * 64, '[]', title, url))
    conn.execute('UPDATE planning_room_owners SET pending_revision=?,pending_slots=?,pending_token=?,title=?,url=? WHERE owner=?',
                 (revision, json.dumps(slots), token, title, url, owner))
    return dict(token=token)


def reconcile(conn, owners, complete=False):
    from planning import PlanningError
    if not isinstance(owners, list) or len(owners) > 10000:
        raise PlanningError('Liste de sessions invalide.')
    seen=set()
    for item in owners:
        owner, revision, _, _ = owner_data(item)
        seen.add(owner)
        row = conn.execute('SELECT * FROM planning_room_owners WHERE owner=?', (owner,)).fetchone()
        if not row or not row['pending_token']:
            continue
        if revision == row['pending_revision']:
            finish(conn, dict(token=row['pending_token'], commit=True))
        elif revision == row['revision']:
            finish(conn, dict(token=row['pending_token'], commit=False))
        else:
            raise PlanningError('Une réservation nécessite une réconciliation manuelle.',status=409)
    if complete:
        for row in conn.execute('SELECT * FROM planning_room_owners WHERE pending_token IS NOT NULL').fetchall():
            if row['owner'] not in seen:
                if json.loads(row['pending_slots']) == []:
                    finish(conn,dict(token=row['pending_token'],commit=True))
                elif json.loads(row['slots']) == []:
                    finish(conn,dict(token=row['pending_token'],commit=False))
    return {}


def finish(conn, data):
    from planning import PlanningError
    token = data.get('token')
    if not isinstance(token, str) or len(token) < 20 or not isinstance(data.get('commit'), bool):
        raise PlanningError('Confirmation de réservation invalide.')
    row = conn.execute('SELECT * FROM planning_room_owners WHERE pending_token=?', (token,)).fetchone()
    if row:
        if data['commit']:
            conn.execute('UPDATE planning_room_owners SET revision=pending_revision,slots=pending_slots WHERE owner=?', (row['owner'],))
        conn.execute('UPDATE planning_room_owners SET pending_revision=NULL,pending_slots=NULL,pending_token=NULL WHERE owner=?', (row['owner'],))
    return {}


def remote(path, method='GET', data=None):
    from planning import PlanningError
    if not configured():
        raise PlanningError('La liaison des salles avec les sessions n’est pas configurée.', status=503)
    try:
        response = requests.request(method, os.environ['SESSION_ROOMS_URL'].rstrip('/') + '/api/shared-rooms' + path,
                                    json=data, headers={'Authorization': 'Bearer ' + os.environ['SHARED_ROOMS_TOKEN']},
                                    timeout=(5, 40), allow_redirects=False)
        value = response.json()
    except (requests.RequestException, ValueError):
        raise PlanningError('La plateforme des sessions est indisponible. Réessayez sans modifier les réservations.', status=503)
    if not response.ok or value.get('ok') is False:
        raise PlanningError(value.get('message', 'La réservation a été refusée.'), value.get('conflicts', []), 409 if response.status_code == 409 else 503)
    return value


def register(app, connect, guard, result, fail, transact, serializer):
    from planning import PlanningError, _iso, _load_courses, _clock, _promotion, _planning_period

    @app.route('/internal/rooms/<action>', methods=['POST'])
    def shared_room_machine(action):
        token = os.environ.get('SHARED_ROOMS_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + token):
            abort(403)
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise PlanningError('Objet JSON requis.')
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                if action == 'prepare':
                    answer = prepare(conn, payload)
                elif action == 'finish':
                    answer = finish(conn, payload)
                elif action == 'reconcile':
                    answer = reconcile(conn, payload.get('owners'),payload.get('complete') is True)
                elif action == 'bootstrap':
                    if conn.execute("SELECT 1 FROM planning_room_meta WHERE key='ready'").fetchone():
                        raise PlanningError('Les salles ont déjà été synchronisées.', status=409)
                    owners = payload.get('owners')
                    if not isinstance(owners, list) or len(owners) > 10000:
                        raise PlanningError('Liste de sessions invalide.')
                    room_names=payload.get('room_names',[])
                    if not isinstance(room_names,list) or len(room_names)>300 or any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in room_names):
                        raise PlanningError('Liste des salles invalide.')
                    for name in room_names:
                        normalize(conn,[dict(room_name=name,date='2000-01-01',start='00:00',end='00:01')],bootstrap=True)
                    for item in owners:
                        owner, revision, title, url = owner_data(item)
                        slots = normalize(conn, item['slots'], bootstrap=True)
                        conn.execute('INSERT INTO planning_room_owners(owner,revision,slots,title,url) VALUES(?,?,?,?,?)',
                                     (owner, revision, json.dumps(slots), title, url))
                    conn.execute("INSERT INTO planning_room_meta(key,value) VALUES('ready','1')")
                    answer = dict(count=len(owners))
                else:
                    abort(404)
                conn.commit()
            return result(answer)
        except PlanningError as exc:
            return fail(exc)

    @app.get('/admin/planning/api/rooms/schedule')
    def room_schedule():
        guard()
        try:
            start, end = _iso(request.args.get('start')), _iso(request.args.get('end'))
            if not 0 <= (end - start).days <= 31:
                raise PlanningError('Affichez au maximum 31 jours.')
            with closing(connect()) as conn:
                rows = [dict(c, source='event' if c.get('kind') == 'event' else 'bts',
                             title=c['title'] or c['subject_name'], url='/admin/planning?promotion_id=' + quote(c['promotion_id']))
                        for c in _load_courses(conn, start.isoformat(), end.isoformat()) if c['room_id']]
                rows += [c for c in external_slots(conn) if start.isoformat() <= c['date'] <= end.isoformat()]
                for index, row in enumerate(rows):
                    row.update(start=_clock(row['start_min']), end=_clock(row['end_min']),
                               conflict=any(overlap(row, other) and row.get('owner', row.get('id')) != other.get('owner', other.get('id'))
                                            for i, other in enumerate(rows) if i != index))
                return result(rooms=[dict(r) for r in conn.execute('SELECT * FROM planning_rooms ORDER BY name')],
                              reservations=rows, connected=configured(), ready=ready(conn))
        except PlanningError as exc:
            return fail(exc)

    @app.route('/admin/planning/api/rooms/sessions', methods=['GET', 'POST'])
    def room_sessions():
        guard(request.method == 'POST')
        try:
            # No ledger transaction here: the remote writer calls back into it.
            return result(remote('/sessions', request.method, request.get_json(silent=True) if request.method == 'POST' else None))
        except PlanningError as exc:
            return fail(exc)

    @app.post('/admin/planning/api/rooms/bootstrap')
    def room_bootstrap():
        guard(True)
        try:
            return result(remote('/bootstrap', 'POST', {}))
        except PlanningError as exc:
            return fail(exc)

    @app.get('/admin/planning/api/rooms/courses')
    def bulk_candidates():
        guard()
        try:
            with closing(connect()) as conn:
                pid = request.args.get('promotion_id'); _promotion(conn, pid)
                start, end = _iso(request.args.get('start')), _iso(request.args.get('end'))
                if not 0 <= (end-start).days <= 400:
                    raise PlanningError('Choisissez une période de 400 jours au maximum.')
                return result(courses=_load_courses(conn, start.isoformat(), end.isoformat(), pid))
        except PlanningError as exc:
            return fail(exc)

    def selection(conn, payload):
        pid = payload.get('promotion_id'); _promotion(conn, pid, ready=True)
        period = _planning_period(conn, pid, period_id=payload.get('period_id'))
        items = payload.get('courses'); rid = payload.get('room_id')
        if not isinstance(rid,str) or not conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1', (rid,)).fetchone():
            raise PlanningError('Choisissez une salle active.')
        if not isinstance(items, list) or not 1 <= len(items) <= 1000 or any(not isinstance(c, dict) for c in items):
            raise PlanningError('Sélectionnez entre 1 et 1 000 cours.')
        if any(not isinstance(c.get('id'),str) or len(c['id'])>100 for c in items):
            raise PlanningError('Sélection de cours invalide.')
        ids = {c.get('id'): c.get('version') for c in items}
        if len(ids) != len(items):
            raise PlanningError('Un cours apparaît plusieurs fois.')
        courses = {c['id']: c for c in _load_courses(conn, promotion_id=pid)}
        selected = []
        for cid, version in ids.items():
            c = courses.get(cid)
            if not c or type(version) is not int or c['version'] != version:
                raise PlanningError('Un cours a changé. Rechargez la sélection.', status=409)
            if period and not period['start_date'] <= c['date'] <= period['end_date']:
                raise PlanningError('Sélectionnez des cours de l’année affichée.')
            selected.append(dict(c, room_id=rid))
        issues = []
        for i, c in enumerate(selected):
            issues.extend(room_conflicts(conn, c, include_courses=True, exclude_ids=ids))
            if any(overlap(c, other) for other in selected[:i]):
                issues.append(dict(type='room', date=c['date'], message='Plusieurs cours sélectionnés se chevauchent dans la même salle.'))
        if issues:
            raise PlanningError('Aucune affectation effectuée : la salle est indisponible.', issues[:80], 409)
        return selected

    @app.post('/admin/planning/api/rooms/bulk-preview')
    def bulk_preview():
        def operation(conn, payload):
            courses = selection(conn, payload)
            token = serializer.dumps(dict(kind='rooms', csrf=session.get('_planning_csrf'), payload=payload))
            return dict(token=token, count=len(courses), shared=sum(c['is_shared'] for c in courses))
        return transact(operation)

    @app.post('/admin/planning/api/rooms/bulk-commit')
    def bulk_commit():
        def operation(conn, payload):
            try:
                signed = serializer.loads(payload.get('token', ''), max_age=1800)
            except (BadSignature, SignatureExpired, TypeError):
                raise PlanningError('Vérifiez à nouveau la sélection : l’aperçu a expiré.')
            if signed.get('kind') != 'rooms' or signed.get('csrf') != session.get('_planning_csrf'):
                raise PlanningError('Cet aperçu appartient à une autre session.')
            courses = selection(conn, signed['payload'])
            now = datetime.now(timezone.utc).isoformat()
            for c in courses:
                conn.execute('UPDATE planning_courses SET room_id=?,version=version+1,updated_at=? WHERE id=?', (c['room_id'], now, c['id']))
            return dict(count=len(courses), message='Salle affectée à tous les cours sélectionnés.')
        return transact(operation)
