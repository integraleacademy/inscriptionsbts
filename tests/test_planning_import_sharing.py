"""Common CI/PI sessions stay single bookings; busy rooms defer only their room."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

import planning
import subject_catalog
from test_planning import db, app, client, admin, rule, add
from test_planning_import import analyze, preview, commit, count, pdf_bytes, two_weeks


def configure(db, bts='PI', names=('Langue vivante étrangère anglaise', 'Langue vivante étrangère')):
    with db() as conn:
        for pid, diploma in [('p1', bts), ('p2', 'CI' if bts == 'PI' else 'PI')]:
            conn.execute('UPDATE promotions SET bts=?,nom=? WHERE id=?', (diploma, 'BTS ' + diploma, pid))
        for sid, name in zip(('s1', 's2'), names):
            conn.execute('UPDATE planning_subjects SET name=? WHERE id=?', (name, sid))


def existing_session(client, **changes):
    assert rule(client, 'p2').status_code == 200
    return add(client, pid='p2', sid='s2', trainer_id='t1', title='Séance déjà préparée',
               zoom_url='https://zoom.us/j/123456789', **changes)


def imported_preview(client, content=None, **changes):
    extraction = analyze(client, content or pdf_bytes(subject='ANGLAIS'))
    assert extraction.status_code == 200, extraction.json
    mappings = dict(subjects={r['subject_key']: 's1' for r in extraction.json['document']['rows']},
                    subject_trainers={r['subject_key']: 't1' for r in extraction.json['document']['rows']})
    response = preview(client, extraction.json['source_token'], mappings=mappings, **changes)
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize('bts', ['CI', 'PI'])
@pytest.mark.parametrize('names', [
    ('Langue vivante étrangère anglaise', 'Langue vivante étrangère'),
    ('Culture générale et expression', 'Culture générale et expression'),
])
def test_shared_import_joins_single_session_and_preserves_details(client, db, bts, names):
    configure(db, bts, names)
    old = existing_session(client)
    reviewed = imported_preview(client, room_id='r2')
    item, = reviewed['items']
    assert item['status'] == 'ready' and item['shared_course']['id'] == old['id']
    assert item['room_id'] == 'r1' and any('Séance commune' in n for n in item['notices'])
    assert count(db) == 1
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM planning_course_groups WHERE promotion_id='p1'").fetchone()[0] == 0
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['shared_courses'] == 1, saved.json
    assert saved.json['course_ids'] == [old['id']] and count(db) == 1
    with db() as conn:
        course, = planning._load_courses(conn)
        assert {(g['promotion_id'], g['subject_id']) for g in course['groups']} == {('p1','s1'),('p2','s2')}
        for key in ('promotion_id', 'subject_id', 'trainer_id', 'room_id', 'date', 'start_min', 'end_min', 'title', 'zoom_url', 'created_at'):
            assert course[key] == old[key]
        assert course['version'] == old['version'] + 1
        assert planning._subject_minutes(conn, 's1') == planning._subject_minutes(conn, 's2') == 120
        assert conn.execute("SELECT kind FROM planning_day_exceptions WHERE promotion_id='p1'").fetchone()[0] == 'school'
    repeated = commit(client, reviewed['preview_token'])
    assert repeated.status_code == 200 and repeated.json['duplicates'] == 1 and repeated.json['count'] == 0
    assert count(db) == 1


@pytest.mark.parametrize('change', ['second_year', 'other_cohort', 'other_bts', 'other_subject', 'rci', 'different_hours'])
def test_unconfirmed_teacher_overlap_stays_blocked(client, db, change):
    names = ('Relation commerciale interculturelle en anglais',) * 2 if change == 'rci' else ('Anglais', 'Anglais')
    configure(db, names=names)
    with db() as conn:
        if change == 'second_year': conn.execute("UPDATE promotions SET niveau=2 WHERE id='p2'")
        if change == 'other_cohort': conn.execute("UPDATE promotions SET rentree_annee=2025 WHERE id='p2'")
        if change == 'other_bts': conn.execute("UPDATE promotions SET bts='MCO' WHERE id='p2'")
        if change == 'other_subject': conn.execute("UPDATE planning_subjects SET name='Commerce' WHERE id='s2'")
    existing_session(client, **({'end': '10:00'} if change == 'different_hours' else {}))
    reviewed = imported_preview(client)
    assert reviewed['summary']['blocked'] == 1
    assert any('formateur intervient déjà' in i for i in reviewed['items'][0]['issues'])
    assert count(db) == 1


def test_other_teacher_is_a_distinct_course(client, db):
    configure(db)
    assert rule(client, 'p2').status_code == 200
    add(client, pid='p2', sid='s2', trainer_id='t2')
    reviewed = imported_preview(client)
    assert reviewed['summary']['ready'] == 1 and 'shared_course' not in reviewed['items'][0]
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['shared_courses'] == 0 and count(db) == 2


def test_shared_courses_consume_budget_once_per_group(client, db):
    configure(db)
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=4 WHERE id IN ('s1','s2')")
    existing_session(client)
    add(client, pid='p2', sid='s2', trainer_id='t1', date='2027-01-11')
    reviewed = imported_preview(client, two_weeks())
    assert reviewed['summary']['ready'] == 2, reviewed
    saved = commit(client, reviewed['preview_token'], ['0', '1'])
    assert saved.status_code == 200 and saved.json['shared_courses'] == 2, saved.json
    with db() as conn:
        assert planning._subject_minutes(conn, 's1') == planning._subject_minutes(conn, 's2') == 240
    assert count(db) == 2


def test_only_selected_shared_session_is_joined(client, db):
    configure(db)
    existing_session(client)
    selected = add(client, pid='p2', sid='s2', trainer_id='t1', date='2027-01-11')
    reviewed = imported_preview(client, two_weeks())
    saved = commit(client, reviewed['preview_token'], ['1'])
    assert saved.status_code == 200 and saved.json['course_ids'] == [selected['id']]
    with db() as conn:
        assert [c['date'] for c in planning._load_courses(conn, promotion_id='p1')] == ['2027-01-11']
        assert planning._subject_minutes(conn, 's1') == 120
        assert planning._subject_minutes(conn, 's2') == 240


@pytest.mark.parametrize('period_number', [1, 2])
def test_two_year_promotions_use_the_actual_annual_period(client, db, period_number):
    configure(db)
    with db() as conn:
        start = '2026-09-01' if period_number == 1 else '2025-09-01'
        end = '2028-07-01' if period_number == 1 else '2027-07-01'
        conn.execute("UPDATE promotions SET date_debut=?,date_fin=?,niveau=2 WHERE id IN ('p1','p2')", (start, end))
        planning.ensure_planning_schema(conn)
        ids = {pid: conn.execute('''SELECT s.id FROM planning_subjects s JOIN planning_subject_periods y ON y.subject_id=s.id
            WHERE s.promotion_id=? AND y.period_id=? AND s.name LIKE 'Langue%' ''', (pid, f'{pid}:{period_number}')).fetchone()[0]
            for pid in ('p1','p2')}
    assert rule(client, 'p2').status_code == 200
    add(client, pid='p2', sid=ids['p2'], trainer_id='t1')
    extracted = analyze(client, pdf_bytes(subject='ANGLAIS'), period=f'p1:{period_number}').json
    reviewed = preview(client, extracted['source_token'], mappings=dict(
        subjects={'ANGLAIS': ids['p1']}, subject_trainers={'ANGLAIS': 't1'})).json
    assert reviewed['summary']['ready'] == (1 if period_number == 1 else 0), reviewed
    assert reviewed['summary']['blocked'] == (0 if period_number == 1 else 1), reviewed


def test_ambiguous_existing_sessions_are_not_joined(client, db):
    configure(db)
    old = existing_session(client)
    with db() as conn:
        # Represent a legacy double booking; normal course creation rejects it.
        conn.execute('''INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,title,created_at,updated_at)
            SELECT 'legacy',promotion_id,subject_id,trainer_id,NULL,date,start_min,end_min,title,created_at,updated_at
            FROM planning_courses WHERE id=?''', (old['id'],))
        conn.execute("INSERT INTO planning_course_groups VALUES('legacy','p2','s2')")
    reviewed = imported_preview(client)
    assert reviewed['summary']['blocked'] == 1 and 'shared_course' not in reviewed['items'][0]


@pytest.mark.parametrize('reason', ['budget', 'calendar', 'unavailable'])
def test_shared_courses_keep_other_import_checks(client, db, reason):
    configure(db)
    existing_session(client)
    with db() as conn:
        if reason == 'budget': conn.execute("UPDATE planning_subjects SET planned_hours=1 WHERE id='s1'")
        if reason == 'unavailable':
            conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                         ('u','t1','2027-01-04','2027-01-04','[0]','[]','Absent'))
    reviewed = imported_preview(client, school_days=reason != 'calendar')
    assert reviewed['summary']['blocked'] == 1
    assert not reviewed['calendar_changes'] and count(db) == 1


def test_shared_import_prepares_catalogue_subject_and_grants_teacher(client, db):
    configure(db, names=('Autre matière', 'Anglais'))
    with db() as conn:
        planning.ensure_planning_schema(conn)
        catalog_id = subject_catalog.import_subject(conn, 'Anglais', 'PI', dict(annual_hours_first=40))
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    existing_session(client)
    extracted = analyze(client, pdf_bytes(subject='ANGLAIS')).json
    reviewed = preview(client, extracted['source_token'], mappings=extracted['mappings'], assign_trainers=True).json
    assert reviewed['summary']['ready'] == 1 and len(reviewed['subject_preparations']) == 1, reviewed
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['shared_courses'] == saved.json['prepared_subjects'] == 1, saved.json
    with db() as conn:
        sid = conn.execute('SELECT planning_subject_id FROM planning_subject_catalog_links WHERE subject_id=?', (catalog_id,)).fetchone()[0]
        assert planning._subject_minutes(conn, sid) == 120
        assert conn.execute("SELECT 1 FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'").fetchone()


@pytest.mark.parametrize('change', ['edited', 'deleted'])
def test_changed_shared_target_aborts_all_rows(client, db, change):
    configure(db)
    old = existing_session(client)
    reviewed = imported_preview(client, two_weeks())
    assert reviewed['summary']['ready'] == 2
    with db() as conn:
        if change == 'edited':
            conn.execute('UPDATE planning_courses SET title=?,version=version+1 WHERE id=?', ('Titre modifié', old['id']))
        else:
            conn.execute('DELETE FROM planning_course_groups WHERE course_id=?', (old['id'],))
            conn.execute('DELETE FROM planning_courses WHERE id=?', (old['id'],))
    saved = commit(client, reviewed['preview_token'], ['0', '1'])
    assert saved.status_code == 409, saved.json
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM planning_course_groups WHERE promotion_id='p1'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM planning_day_exceptions WHERE promotion_id='p1'").fetchone()[0] == 0


def test_new_shared_target_requires_a_fresh_preview(client, db):
    configure(db)
    reviewed = imported_preview(client)
    existing_session(client)
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 409 and count(db) == 1


def test_parallel_shared_commits_are_idempotent(app, client, db):
    configure(db)
    existing_session(client)
    reviewed = imported_preview(client)
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: commit(admin(app), reviewed['preview_token']), range(2)))
    assert all(r.status_code == 200 for r in responses), [r.json for r in responses]
    assert sorted(r.json['count'] for r in responses) == [0, 1] and count(db) == 1


@pytest.mark.parametrize('source', ['course', 'reservation', 'unavailability', 'session', 'sync'])
def test_busy_rooms_allow_import_without_claiming_the_room(client, db, monkeypatch, source):
    extracted = analyze(client).json
    with db() as conn:
        if source == 'reservation':
            conn.execute("INSERT INTO planning_room_reservations VALUES('r','r1','2027-01-04',540,660,'Examen',1,1,'now','now')")
        if source == 'unavailability':
            conn.execute("INSERT INTO planning_room_unavailability VALUES('u','r1','2027-01-04','2027-01-04',540,660,'Travaux',1)")
        if source == 'session':
            slots = json.dumps([dict(room_id='r1', date='2027-01-04', start_min=540, end_min=660)])
            conn.execute("INSERT INTO planning_room_owners(owner,revision,slots,title,url) VALUES('session:test','1',?,'Formation','')", (slots,))
    if source == 'course':
        assert rule(client, 'p2').status_code == 200
        add(client, pid='p2', sid='s4', trainer_id='t2')
    if source == 'sync':
        monkeypatch.setattr('planning_rooms.ready', lambda conn: False)
    reviewed = preview(client, extracted['source_token'], room_id='r1').json
    item, = reviewed['items']
    assert item['status'] == 'ready' and item['room_id'] is None and item['room_warning'], reviewed
    assert any('Salle à compléter' in n for n in item['notices'])
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['rooms_to_review'] == 1, saved.json
    with db() as conn:
        course = conn.execute("SELECT * FROM planning_courses WHERE promotion_id='p1'").fetchone()
        assert course['room_id'] is None


def test_room_taken_after_preview_defers_only_the_affected_day(client, db):
    extracted = analyze(client, two_weeks()).json
    reviewed = preview(client, extracted['source_token'], room_id='r1').json
    assert rule(client, 'p2').status_code == 200
    add(client, pid='p2', sid='s4', trainer_id='t2')
    saved = commit(client, reviewed['preview_token'], ['0', '1'])
    assert saved.status_code == 200 and saved.json['rooms_to_review'] == 1, saved.json
    with db() as conn:
        assert [tuple(r) for r in conn.execute("SELECT date,room_id FROM planning_courses WHERE promotion_id='p1' ORDER BY date")] == [
            ('2027-01-04',None), ('2027-01-11','r1')]


def test_room_fallback_does_not_bypass_teacher_conflicts(client, db):
    existing_session(client)
    extracted = analyze(client).json
    reviewed = preview(client, extracted['source_token'], room_id='r1').json
    assert reviewed['summary']['blocked'] == 1
    assert any('formateur intervient déjà' in i for i in reviewed['items'][0]['issues'])
    assert count(db) == 1


def test_shared_session_keeps_its_room_and_reports_preexisting_room_conflict(client, db):
    configure(db)
    old = existing_session(client)
    with db() as conn:
        conn.execute("INSERT INTO planning_room_reservations VALUES('r','r1','2027-01-04',540,660,'Examen',1,1,'now','now')")
    reviewed = imported_preview(client, room_id='r2')
    item, = reviewed['items']
    assert item['status'] == 'ready' and item['room_id'] == 'r1' and item['room_warning']
    assert any('Salle de la séance commune à vérifier' in n for n in item['notices'])
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['shared_courses'] == saved.json['rooms_to_review'] == 1
    with db() as conn:
        assert conn.execute('SELECT room_id FROM planning_courses WHERE id=?', (old['id'],)).fetchone()[0] == 'r1'
