"""Independent assignments and evaluations, scoped to teacher, class and subject.

Existing course homework keeps its ID and grades. Its class/subject scope is
copied once, so deleting or moving a timetable lesson cannot delete a grade.
"""
from contextlib import closing
from datetime import date

from flask import render_template, request

from planning import PlanningError
from planning_portal import _identity_scope
import subject_catalog


def ensure_gradebook_schema(conn):
    # Serialize first-run ALTERs and the one-time scope copy across workers.
    # The caller owns commit/rollback, including when already in a transaction.
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(teaching_homework)')}
    for name, definition in [('kind', "TEXT NOT NULL DEFAULT 'homework'"),
                             ('evaluation_date', "TEXT NOT NULL DEFAULT ''"),
                             ('scope_migrated', 'INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:
            conn.execute('ALTER TABLE teaching_homework ADD COLUMN '+name+' '+definition)
    conn.execute('''CREATE TABLE IF NOT EXISTS teaching_homework_groups(
        homework_id TEXT NOT NULL,promotion_id TEXT NOT NULL,subject_id TEXT NOT NULL,
        PRIMARY KEY(homework_id,promotion_id,subject_id))''')
    conn.execute('CREATE INDEX IF NOT EXISTS teaching_homework_groups_promotion ON teaching_homework_groups(promotion_id,homework_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS teaching_homework_trainer ON teaching_homework(trainer_id,evaluation_date)')
    for row in conn.execute('SELECT id FROM teaching_homework WHERE scope_migrated=0').fetchall():
        migrate_homework_scope(conn, row['id'])


def migrate_homework_scope(conn, homework_id):
    row = conn.execute('SELECT course_id,scope_migrated,due_date FROM teaching_homework WHERE id=?', (homework_id,)).fetchone()
    if not row or row['scope_migrated'] or not row['course_id']:
        return
    conn.execute('''INSERT OR IGNORE INTO teaching_homework_groups(homework_id,promotion_id,subject_id)
        SELECT ?,g.promotion_id,l.subject_id FROM planning_course_groups g
        JOIN planning_subject_catalog_links l ON l.planning_subject_id=g.subject_id WHERE g.course_id=?''',
        (homework_id, row['course_id']))
    course = conn.execute('SELECT date FROM planning_courses WHERE id=?', (row['course_id'],)).fetchone()
    conn.execute('UPDATE teaching_homework SET scope_migrated=1,evaluation_date=? WHERE id=?',
                 (course['date'] if course else row['due_date'], homework_id))


def groups_for(conn, homework_id, role, identity_id):
    allowed = {p['id'] for p in _identity_scope(conn, role, identity_id)['promotions']}
    return [dict(row) for row in conn.execute('''SELECT g.promotion_id,g.subject_id,p.nom,p.bts,s.name
        FROM teaching_homework_groups g JOIN promotions p ON p.id=g.promotion_id
        JOIN planning_subject_catalog s ON s.id=g.subject_id WHERE g.homework_id=? ORDER BY p.nom,s.name''',
        (homework_id,)) if row['promotion_id'] in allowed]


def access(conn, homework_id, role, identity_id):
    row = conn.execute('SELECT * FROM teaching_homework WHERE id=?', (homework_id,)).fetchone()
    if not row or (role == 'trainer' and row['trainer_id'] != identity_id) or (role == 'student' and not row['published']):
        raise PlanningError('Évaluation introuvable dans votre espace.', status=404)
    groups = groups_for(conn, homework_id, role, identity_id)
    if not groups:
        raise PlanningError('Évaluation introuvable dans votre espace.', status=404)
    return dict(row, groups=groups, subject_name=' · '.join(dict.fromkeys(g['name'] for g in groups)),
                promotion_names=' · '.join(dict.fromkeys(g['nom'] for g in groups)))


def snapshot(conn, item, role, identity_id, include_roster=False):
    import teaching as t
    students = t.roster(conn, item)
    allowed = {s['id'] for s in students} if role == 'trainer' else {identity_id}
    item['grades'] = [dict(row) for row in conn.execute('''SELECT candidate_id,score,status,comment
        FROM teaching_grades WHERE homework_id=?''', (item['id'],)) if row['candidate_id'] in allowed]
    item['graded_count'] = sum(g['status'] == 'graded' for g in item['grades'])
    if include_roster and role == 'trainer':
        item['students'] = students
    return item


def selection(conn, trainer_id, promotion_id, subject_id):
    if not isinstance(promotion_id, str) or not isinstance(subject_id, str):
        raise PlanningError('Choisissez une promotion et une matière.')
    promotions = _identity_scope(conn, 'trainer', trainer_id)['promotions']
    promotion = next((p for p in promotions if p['id'] == promotion_id), None)
    if not promotion:
        raise PlanningError('Promotion introuvable dans votre espace.', status=404)
    subject = subject_catalog.available(conn, subject_id, promotion['bts'])
    return dict(promotion_id=promotion_id, subject_id=subject_id, nom=promotion['nom'], bts=promotion['bts'], name=subject['name'])


def save(conn, trainer_id, data):
    import teaching as t
    homework_id = data.get('id')
    if homework_id is not None and not isinstance(homework_id, str):
        raise PlanningError('Évaluation invalide.')
    old = access(conn, homework_id, 'trainer', trainer_id) if homework_id else None
    # Existing scope is immutable, including shared classes inherited from a lesson.
    # This keeps historical grades attached to the right class and subject.
    groups = old['groups'] if old else [selection(conn, trainer_id, data.get('promotion_id'), data.get('subject_id'))]
    kind = data.get('kind', old['kind'] if old else 'homework')
    if kind not in ('homework', 'evaluation'):
        raise PlanningError('Choisissez Devoir ou Évaluation.')
    try:
        evaluation_date = date.fromisoformat(data.get('evaluation_date', '')).isoformat()
        if not '1900-01-01' <= evaluation_date <= '2200-12-31':
            raise ValueError()
    except (TypeError, ValueError):
        raise PlanningError('Choisissez une date valide pour le devoir ou l’évaluation.') from None
    metadata = dict(data, due_date=evaluation_date if kind == 'evaluation' else data.get('due_date'))
    course = dict(id=old['course_id'] if old else '', date='1900-01-01', groups=groups)
    homework_id = t.save_homework(conn, course, trainer_id, metadata)
    if not old:
        conn.executemany('INSERT INTO teaching_homework_groups VALUES(?,?,?)',
            [(homework_id, g['promotion_id'], g['subject_id']) for g in groups])
    conn.execute('UPDATE teaching_homework SET kind=?,evaluation_date=?,scope_migrated=1 WHERE id=?',
                 (kind, evaluation_date, homework_id))
    return homework_id


def register_gradebook(app, *, connect, person, guard, check_csrf, csrf, secure, result, payload):
    @app.get('/formateur/devoirs-notes')
    @app.get('/espace/devoirs-notes')
    @guard
    def gradebook_index():
        import teaching as t
        role = 'trainer' if request.path.startswith('/formateur') else 'student'
        who, identity_id = person(role)
        with closing(connect()) as conn:
            scope = _identity_scope(conn, role, identity_id)
            subjects = subject_catalog.subjects(conn) if role == 'trainer' else []
            codes = {p['bts'] for p in scope['promotions']}
            subjects = [dict(id=s['id'], name=s['name'], diploma_codes=s['diploma_codes']) for s in subjects if codes.intersection(s['diploma_codes'])]
            rows = conn.execute('SELECT id FROM teaching_homework WHERE trainer_id=? ORDER BY evaluation_date DESC,created_at DESC', (identity_id,)) if role == 'trainer' else conn.execute('SELECT id FROM teaching_homework WHERE published=1 ORDER BY evaluation_date DESC,created_at DESC')
            items = []
            for row in rows.fetchall():
                try:
                    items.append(snapshot(conn, access(conn, row['id'], role, identity_id), role, identity_id))
                except PlanningError:
                    continue
            state = dict(role=role, items=items, promotions=scope['promotions'], subjects=subjects, today=t.now_paris().date().isoformat())
        return secure(app.make_response(render_template('gradebook.html', state=state, trainer=who,
            csrf_token=csrf(), title='Devoirs et notes · Intégrale Academy')))

    @app.get('/formateur/devoirs-notes/<homework_id>/state')
    @guard
    def gradebook_state(homework_id):
        _, trainer_id = person('trainer')
        with closing(connect()) as conn:
            return result(dict(ok=True, item=snapshot(conn, access(conn, homework_id, 'trainer', trainer_id), 'trainer', trainer_id, True)))

    @app.post('/formateur/devoirs-notes/enregistrer')
    @guard
    def gradebook_save():
        import teaching as t
        _, trainer_id = person('trainer')
        check_csrf()
        data = payload()
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Recheck the version-bound account and its permissions inside the transaction.
            t.assert_trainer_session(conn, trainer_id)
            homework_id = save(conn, trainer_id, data)
            item = snapshot(conn, access(conn, homework_id, 'trainer', trainer_id), 'trainer', trainer_id, True)
            conn.commit()
        return result(dict(ok=True, item=item))

    @app.post('/formateur/devoirs-notes/<homework_id>/notes')
    @guard
    def gradebook_grades(homework_id):
        import teaching as t
        _, trainer_id = person('trainer')
        check_csrf()
        data = payload()
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            t.assert_trainer_session(conn, trainer_id)
            item = access(conn, homework_id, 'trainer', trainer_id)
            t.save_grades(conn, dict(id=item['course_id'], groups=item['groups']), trainer_id, dict(data, id=homework_id))
            item = snapshot(conn, access(conn, homework_id, 'trainer', trainer_id), 'trainer', trainer_id, True)
            conn.commit()
        return result(dict(ok=True, item=item))
