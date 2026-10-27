"""Shared subject definitions, with a separate curriculum for each diploma.

planning_subjects remains the timetable allocation (teacher and annual budget).
Its identifiers and existing courses are preserved by the catalogue migration.
"""
from contextlib import closing
import json
import re
import secrets

from flask import request

from promotions import BTS_LABELS
import subject_references as references

ANNUAL_FIELDS = {1: 'annual_hours_first', 2: 'annual_hours_second'}


def study_year(promotion, period):
    return (promotion.get('niveau') or 1) + ((period or {}).get('number', 1) - 1)


def annual_hours(conn, subject_id, promotion, period):
    field = ANNUAL_FIELDS.get(study_year(promotion, period))
    return diploma_details(conn, subject_id, promotion['bts']).get(field) if field else None


def validate_details(changes, previous):
    from planning import _annual_hours
    result = references.validate_details(changes, previous)
    for field in ANNUAL_FIELDS.values():
        if field in changes:
            value = changes[field]
            result[field] = None if value is None or value == '' else _annual_hours(value)
    return result


def save_allocations(conn, subject_id, changes):
    """Explicit edits only; a catalogue default never overwrites a promotion."""
    from planning import PlanningError, _annual_hours, _budget_minutes, _subject_minutes
    if not isinstance(changes, list) or len(changes) > 1000:
        raise PlanningError('Les volumes des plannings sont invalides.')
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get('id'), str) or change['id'] in seen:
            raise PlanningError('Choisissez chaque planning une seule fois.')
        seen.add(change['id'])
        row = conn.execute('''SELECT s.*,p.nom AS promotion_name,p.active FROM planning_subjects s
            JOIN planning_subject_catalog_links l ON l.planning_subject_id=s.id
            JOIN promotions p ON p.id=s.promotion_id WHERE s.id=? AND l.subject_id=?''',
            (change['id'], subject_id)).fetchone()
        if not row:
            raise PlanningError('Ce planning ne correspond plus à la matière. Rechargez le catalogue.', status=409)
        if not row['active']:
            raise PlanningError('Le planning « '+row['promotion_name']+' » est archivé.', status=409)
        previous = change.get('previous_planned_hours')
        if ('previous_planned_hours' not in change or
                (previous is not None and type(previous) not in (int, float)) or previous != row['planned_hours']):
            raise PlanningError('Le volume du planning « '+row['promotion_name']+' » a changé. Rechargez le catalogue.', status=409)
        hours = _annual_hours(change.get('planned_hours'))
        used = _subject_minutes(conn, row['id'])
        if used > _budget_minutes(hours):
            raise PlanningError('Le volume du planning « '+row['promotion_name']+' » ne peut pas être inférieur aux '+
                format(used / 60, '.2f').rstrip('0').rstrip('.').replace('.', ',')+' h déjà planifiées.',
                [dict(type='subject_budget', subject_id=row['id'], planned_minutes=_budget_minutes(hours), scheduled_minutes=used)], 409)
        conn.execute('UPDATE planning_subjects SET planned_hours=? WHERE id=?', (hours, row['id']))


def diploma_codes(value):
    from planning import PlanningError
    if (not isinstance(value, list) or not value or len(value) > len(BTS_LABELS)
            or any(not isinstance(code, str) or code not in BTS_LABELS for code in value)
            or len(set(value)) != len(value)):
        raise PlanningError('Cochez au moins un diplôme valide pour cette matière.')
    return sorted(value)


def schema(conn):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS planning_subject_catalog (
            id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1)''',
        '''CREATE TABLE IF NOT EXISTS planning_subject_diplomas (
            subject_id TEXT NOT NULL,diploma_code TEXT NOT NULL,data TEXT NOT NULL,
            PRIMARY KEY(subject_id,diploma_code))''',
        '''CREATE TABLE IF NOT EXISTS planning_subject_catalog_links (
            planning_subject_id TEXT PRIMARY KEY,subject_id TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS subject_diplomas_code ON planning_subject_diplomas(diploma_code,subject_id)',
        'CREATE INDEX IF NOT EXISTS subject_catalog_links_subject ON planning_subject_catalog_links(subject_id)',
    ):
        conn.execute(sql)
    # Also catches allocations created by an older worker during a rolling deploy.
    # Original rows, budgets, course IDs and reference JSON are never rewritten.
    legacy = conn.execute('''SELECT s.*,p.bts,d.data FROM planning_subjects s
        JOIN promotions p ON p.id=s.promotion_id
        LEFT JOIN planning_subject_details d ON d.subject_id=s.id
        LEFT JOIN planning_subject_catalog_links l ON l.planning_subject_id=s.id
        WHERE l.planning_subject_id IS NULL ORDER BY d.updated_at DESC,s.id''').fetchall()
    for row in legacy:
        if row['bts'] not in BTS_LABELS:
            continue
        key = references.normal(row['name'])
        subject = conn.execute('SELECT id FROM planning_subject_catalog WHERE name_key=?', (key,)).fetchone()
        sid = subject['id'] if subject else row['id']
        if not subject:
            conn.execute('INSERT INTO planning_subject_catalog(id,name,name_key,color) VALUES(?,?,?,?)',
                (sid, row['name'], key, row['color']))
        metadata = row['data'] or '{}'
        conn.execute('INSERT OR IGNORE INTO planning_subject_diplomas VALUES(?,?,?)', (sid, row['bts'], metadata))
        if metadata != '{}':
            conn.execute("UPDATE planning_subject_diplomas SET data=? WHERE subject_id=? AND diploma_code=? AND data='{}'",
                (metadata, sid, row['bts']))
        conn.execute('INSERT INTO planning_subject_catalog_links VALUES(?,?)', (row['id'], sid))


def diploma_details(conn, subject_id, code):
    row = conn.execute('SELECT data FROM planning_subject_diplomas WHERE subject_id=? AND diploma_code=?', (subject_id, code)).fetchone()
    return json.loads(row['data']) if row else {}


def linked_subject(conn, planning_subject_id):
    row = conn.execute('SELECT subject_id FROM planning_subject_catalog_links WHERE planning_subject_id=?', (planning_subject_id,)).fetchone()
    return row['subject_id'] if row else None


def subjects(conn, diploma=None):
    items = []
    query = 'SELECT * FROM planning_subject_catalog'
    args = ()
    if diploma:
        query += ' WHERE id IN (SELECT subject_id FROM planning_subject_diplomas WHERE diploma_code=?)'
        args = (diploma,)
    for row in conn.execute(query+' ORDER BY name_key,id', args):
        item = dict(row)
        item.pop('name_key')
        item['diploma_details'] = {r['diploma_code']: json.loads(r['data']) for r in conn.execute(
            'SELECT diploma_code,data FROM planning_subject_diplomas WHERE subject_id=? ORDER BY diploma_code', (item['id'],))}
        item['diploma_codes'] = list(item['diploma_details'])
        item['diploma_labels'] = [BTS_LABELS.get(code, code) for code in item['diploma_codes']]
        item['planning_count'] = conn.execute('''SELECT COUNT(*) FROM planning_subject_catalog_links l
            JOIN planning_subjects s ON s.id=l.planning_subject_id WHERE l.subject_id=?''', (item['id'],)).fetchone()[0]
        items.append(item)
    return items


def find(conn, subject_id):
    from planning import PlanningError
    if not isinstance(subject_id, str) or not subject_id or len(subject_id) > 128:
        raise PlanningError('Choisissez une matière du catalogue.')
    row = conn.execute('SELECT * FROM planning_subject_catalog WHERE id=?', (subject_id,)).fetchone()
    if not row:
        raise PlanningError('Matière introuvable dans le catalogue.', status=404)
    return dict(row)


def available(conn, subject_id, code):
    from planning import PlanningError
    item = find(conn, subject_id)
    if not conn.execute('SELECT 1 FROM planning_subject_diplomas WHERE subject_id=? AND diploma_code=?', (subject_id, code)).fetchone():
        raise PlanningError('Cette matière n’est pas rattachée au BTS de cette promotion. Modifiez ses diplômes dans Matières.')
    return item


def save(conn, payload, subject_id=None):
    from planning import PlanningError, _text
    old = find(conn, subject_id) if subject_id else None
    if old and 'version' in payload and (type(payload['version']) is not int or payload['version'] != old['version']):
        raise PlanningError('Cette matière a été modifiée entre-temps. Rechargez le catalogue avant de réessayer.', status=409)
    name = _text(payload.get('name', old['name'] if old else ''), 'le nom de la matière', 120, True)
    key = references.normal(name)
    other = conn.execute('SELECT id FROM planning_subject_catalog WHERE name_key=? AND id!=?', (key, subject_id or '')).fetchone()
    if other:
        raise PlanningError('Cette matière existe déjà dans le catalogue. Ouvrez sa fiche pour lui ajouter un diplôme.', status=409)
    previous = {row['diploma_code']: json.loads(row['data']) for row in conn.execute(
        'SELECT diploma_code,data FROM planning_subject_diplomas WHERE subject_id=?', (subject_id,))} if old else {}
    codes = diploma_codes(payload.get('diploma_codes', list(previous)))
    color = payload.get('color', old['color'] if old else '#2563eb')
    if not isinstance(color, str) or not re.fullmatch('#[0-9a-fA-F]{6}', color):
        raise PlanningError('La couleur de la matière doit être au format #RRGGBB.')
    changes = payload.get('diploma_details', {})
    if not isinstance(changes, dict) or any(code not in codes or not isinstance(value, dict) for code, value in changes.items()):
        raise PlanningError('Les informations pédagogiques doivent correspondre aux diplômes cochés.')
    for removed in set(previous) - set(codes):
        used = conn.execute('''SELECT p.nom FROM planning_subject_catalog_links l
            JOIN planning_subjects s ON s.id=l.planning_subject_id JOIN promotions p ON p.id=s.promotion_id
            WHERE l.subject_id=? AND p.bts=? LIMIT 1''', (subject_id, removed)).fetchone()
        if used:
            raise PlanningError('Le BTS '+removed+' est utilisé dans le planning « '+used['nom']+' ». Retirez d’abord cette matière de ce planning pour détacher le diplôme.', status=409)
    details = {code: validate_details(changes.get(code, {}), previous.get(code, {})) for code in codes}
    save_allocations(conn, subject_id, payload.get('planning_allocations', []))
    sid = subject_id or secrets.token_urlsafe(24)
    if old:
        conn.execute('UPDATE planning_subject_catalog SET name=?,name_key=?,color=?,version=version+1 WHERE id=?', (name, key, color, sid))
        if name != old['name'] or color != old['color']:
            conn.execute('''UPDATE planning_subjects SET name=?,color=? WHERE id IN
                (SELECT planning_subject_id FROM planning_subject_catalog_links WHERE subject_id=?)''', (name, color, sid))
    else:
        conn.execute('INSERT INTO planning_subject_catalog(id,name,name_key,color) VALUES(?,?,?,?)', (sid, name, key, color))
    conn.execute('DELETE FROM planning_subject_diplomas WHERE subject_id=?', (sid,))
    conn.executemany('INSERT INTO planning_subject_diplomas VALUES(?,?,?)',
        [(sid, code, json.dumps(details[code], ensure_ascii=False)) for code in codes])
    return sid


def import_subject(conn, name, code, metadata, color='#2563eb'):
    """Extend an existing subject to another diploma, never overwrite its programme."""
    from planning import PlanningError
    diploma_codes([code])
    existing = conn.execute('SELECT id FROM planning_subject_catalog WHERE name_key=?', (references.normal(name),)).fetchone()
    if existing:
        sid = existing['id']
        if conn.execute('SELECT 1 FROM planning_subject_diplomas WHERE subject_id=? AND diploma_code=?', (sid, code)).fetchone():
            raise PlanningError('« '+name+' » existe déjà pour le BTS '+code+'. Décochez-la ou modifiez son nom. Aucune matière n’a été importée.', status=409)
        conn.execute('UPDATE planning_subject_catalog SET version=version+1 WHERE id=?', (sid,))
    else:
        sid = secrets.token_urlsafe(24)
        conn.execute('INSERT INTO planning_subject_catalog(id,name,name_key,color) VALUES(?,?,?,?)', (sid, name, references.normal(name), color))
    conn.execute('INSERT INTO planning_subject_diplomas VALUES(?,?,?)', (sid, code, json.dumps(metadata, ensure_ascii=False)))
    return sid


def link_allocation(conn, allocation_id, subject_id):
    conn.execute('INSERT INTO planning_subject_catalog_links VALUES(?,?)', (allocation_id, subject_id))


def delete(conn, subject_id, payload):
    """Remove unused preparations with the catalogue entry, never actual lessons."""
    from planning import PlanningError, _has_table
    item = find(conn, subject_id)
    if 'version' in payload and (type(payload['version']) is not int or payload['version'] != item['version']):
        raise PlanningError('Cette matière a été modifiée entre-temps. Rechargez le catalogue avant de la supprimer.', status=409)
    if _has_table(conn, 'teaching_homework_groups') and conn.execute(
            'SELECT 1 FROM teaching_homework_groups WHERE subject_id=? LIMIT 1', (subject_id,)).fetchone():
        raise PlanningError('Cette matière contient des devoirs ou des évaluations. Elle doit être conservée pour préserver les notes.', status=409)
    used = conn.execute('''WITH linked AS (
            SELECT planning_subject_id FROM planning_subject_catalog_links WHERE subject_id=?
        ), lessons AS (
            SELECT c.id,c.promotion_id,c.subject_id FROM planning_courses c
            JOIN linked l ON l.planning_subject_id=c.subject_id
            UNION
            SELECT c.id,g.promotion_id,g.subject_id FROM planning_course_groups g
            JOIN planning_courses c ON c.id=g.course_id JOIN linked l ON l.planning_subject_id=g.subject_id
        ) SELECT l.subject_id,l.promotion_id,p.nom AS promotion_name,y.period_id,
            COALESCE(p.niveau,1)+COALESCE(a.number,1)-1 AS study_year,COUNT(DISTINCT l.id) AS course_count
        FROM lessons l LEFT JOIN promotions p ON p.id=l.promotion_id
        LEFT JOIN planning_subject_periods y ON y.subject_id=l.subject_id
        LEFT JOIN planning_periods a ON a.id=y.period_id
        GROUP BY l.subject_id,l.promotion_id ORDER BY p.nom,a.number,l.subject_id''', (subject_id,)).fetchall()
    if used:
        raise PlanningError('Cette matière comporte encore des cours. Supprimez-les ou réaffectez-les dans les plannings ci-dessous avant de supprimer la matière.',
            [dict(row, type='subject_used') for row in used], 409)
    # Keep links until every dependent row has been removed. The caller owns the
    # transaction, so a failure or a concurrent course creation cannot orphan data.
    for table, key in [('planning_subject_details', 'subject_id'), ('planning_subject_periods', 'subject_id'),
                       ('planning_course_groups', 'subject_id'), ('planning_subjects', 'id')]:
        conn.execute('DELETE FROM '+table+' WHERE '+key+' IN (SELECT planning_subject_id FROM planning_subject_catalog_links WHERE subject_id=?)', (subject_id,))
    conn.execute('DELETE FROM planning_subject_diplomas WHERE subject_id=?', (subject_id,))
    conn.execute('DELETE FROM planning_subject_catalog_links WHERE subject_id=?', (subject_id,))
    conn.execute('DELETE FROM planning_subject_catalog WHERE id=?', (subject_id,))


def register(app, connect, guard, result, fail, transact):
    from planning import PlanningError

    @app.get('/admin/planning/api/subject-catalog')
    def subject_catalog_list():
        guard()
        try:
            code = request.args.get('diploma') or None
            if code:
                diploma_codes([code])
            with closing(connect()) as conn:
                return result(subjects=subjects(conn, code), diplomas=BTS_LABELS)
        except PlanningError as error:
            return fail(error)

    @app.post('/admin/planning/api/subject-catalog')
    @app.route('/admin/planning/api/subject-catalog/<subject_id>', methods=['PUT', 'DELETE'])
    def subject_catalog_edit(subject_id=None):
        def operation(conn, payload):
            if request.method == 'DELETE':
                delete(conn, subject_id, payload)
                return dict(message='Matière supprimée du catalogue et retirée des plannings sans cours.')
            sid = save(conn, payload, subject_id)
            return dict(subject=next(row for row in subjects(conn) if row['id'] == sid), message='Matière, diplômes et volumes annuels enregistrés.')
        return transact(operation)
