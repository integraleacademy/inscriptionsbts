"""Independent regression checks for shared lessons and annual-hour limits.

Every database is temporary. No application transport or real account is used.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import pytest

import planning
from test_planning import app, client, db, admin, call, course, count, setup_school, types


def budget(db, sid, hours):
    with db() as conn:
        conn.execute('UPDATE planning_subjects SET planned_hours=? WHERE id=?', (hours, sid))


def shared_course(**updates):
    return course(shared=[dict(promotion_id='p2', subject_id='s2')], **updates)


def create(client, payload=None):
    response = call(client, '/courses', payload or course())
    assert response.status_code == 200, response.json
    return response.json['course']


def snapshot(client, pid='p1'):
    response = client.get('/admin/planning/api/state?promotion_id=' + pid)
    assert response.status_code == 200, response.json
    return response.json


def scheduled(client, pid, sid):
    return next(item['scheduled_hours'] for item in snapshot(client, pid)['subjects'] if item['id'] == sid)


def paint(client, pid, days, revision=None):
    if revision is None:
        revision = snapshot(client, pid)['calendar_revision']
    return call(client, '/calendar/bulk', dict(promotion_id=pid, days=days, expected_revision=revision))


def preview(client, **updates):
    data = dict(promotion_id='p1', mode='repeat', start_date='2027-01-04',
                end_date='2027-01-25', weekdays=[0], interval_weeks=1,
                template=dict(subject_id='s1', room_id='r1', start='09:00', end='11:00'))
    data.update(updates)
    response = call(client, '/courses/preview', data)
    assert response.status_code == 200, response.json
    return response.json


def test_shared_course_is_one_event_visible_in_both_promotions_and_charges_each_budget(client, db):
    setup_school(client)
    lesson = create(client, shared_course())
    assert count(db) == 1
    assert {item['promotion_id'] for item in lesson['groups']} == {'p1', 'p2'}
    for pid, sid in [('p1', 's1'), ('p2', 's2')]:
        state = snapshot(client, pid)
        assert [item['id'] for item in state['courses']] == [lesson['id']]
        assert scheduled(client, pid, sid) == 2


def test_secondary_promotion_collision_is_checked_in_both_directions(client, db):
    setup_school(client)
    create(client, course(pid='p2', sid='s4', room_id='r2'))
    response = call(client, '/courses', shared_course())
    assert response.status_code == 409
    assert 'promotion_overlap' in types(response)
    assert count(db) == 1
    with db() as conn:
        conn.execute('DELETE FROM planning_courses')
        conn.execute('DELETE FROM planning_course_groups')
    create(client, shared_course())
    response = call(client, '/courses', course(pid='p2', sid='s4', room_id='r2'))
    assert response.status_code == 409
    assert 'promotion_overlap' in types(response)


def test_shared_course_requires_teacher_grant_and_school_day_for_every_group(client, db):
    setup_school(client)
    with db() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p2'")
    response = call(client, '/courses', shared_course())
    assert response.status_code == 400
    assert count(db) == 0
    with db() as conn:
        conn.execute("INSERT INTO trainer_promotions VALUES('t1','p2')")
    response = call(client, '/calendar/exceptions', dict(promotion_id='p2', date='2027-01-04', kind='company'), 'PUT')
    assert response.status_code == 200
    response = call(client, '/courses', shared_course())
    assert response.status_code == 409
    assert 'not_school' in types(response)
    assert count(db) == 0


def test_shared_course_checks_secondary_promotion_dates_and_subject_ownership(client, db):
    setup_school(client)
    response = call(client, '/courses', course(shared=[dict(promotion_id='p2', subject_id='s1')]))
    assert response.status_code == 400
    with db() as conn:
        conn.execute("UPDATE promotions SET date_fin='2027-01-03' WHERE id='p2'")
    response = call(client, '/courses', shared_course())
    assert response.status_code == 409
    assert 'outside_promotion' in types(response)
    assert count(db) == 0


def test_exact_budget_allowed_and_next_minute_refused(client, db):
    setup_school(client)
    budget(db, 's1', 2)
    create(client)
    response = call(client, '/courses', course(date='2027-01-05', start='09:00', end='09:01'))
    assert response.status_code == 409
    assert 'subject_budget' in types(response)
    assert count(db) == 1
    assert scheduled(client, 'p1', 's1') == 2


def test_secondary_subject_budget_blocks_entire_shared_event(client, db):
    setup_school(client)
    budget(db, 's2', 1)
    response = call(client, '/courses', shared_course())
    assert response.status_code == 409
    assert 'subject_budget' in types(response)
    assert count(db) == count(db, 'planning_course_groups') == 0


def test_edit_excludes_old_duration_and_shortening_releases_budget(client, db):
    setup_school(client)
    budget(db, 's1', 2)
    lesson = create(client)
    response = call(client, '/courses/' + lesson['id'], dict(version=lesson['version'], title='Nouveau titre'), 'PUT')
    assert response.status_code == 200, response.json
    lesson = response.json['course']
    response = call(client, '/courses/' + lesson['id'], dict(version=lesson['version'], end='12:00'), 'PUT')
    assert response.status_code == 409 and 'subject_budget' in types(response)
    response = call(client, '/courses/' + lesson['id'], dict(version=lesson['version'], end='10:00'), 'PUT')
    assert response.status_code == 200, response.json
    create(client, course(date='2027-01-05', end='10:00'))
    assert scheduled(client, 'p1', 's1') == 2


def test_deletion_releases_all_shared_budgets(client, db):
    setup_school(client)
    for sid in ('s1', 's2'):
        budget(db, sid, 2)
    lesson = create(client, shared_course())
    response = call(client, '/courses/' + lesson['id'], dict(version=lesson['version']), 'DELETE')
    assert response.status_code == 200
    assert count(db) == count(db, 'planning_course_groups') == 0
    assert scheduled(client, 'p1', 's1') == scheduled(client, 'p2', 's2') == 0
    create(client, shared_course(date='2027-01-05'))


def test_removing_shared_group_releases_its_budget_and_migration_never_restores_it(client, db):
    setup_school(client)
    lesson = create(client, shared_course())
    response = call(client, '/courses/' + lesson['id'], dict(version=lesson['version'], shared=[]), 'PUT')
    assert response.status_code == 200, response.json
    for _ in range(2):
        with db() as conn:
            planning.ensure_planning_schema(conn)
        assert snapshot(client, 'p2')['courses'] == []
    assert scheduled(client, 'p2', 's2') == 0
    assert count(db) == count(db, 'planning_course_groups') == 1


@pytest.mark.parametrize('hours', [None, '', 0, -1, True, [], {}, float('inf'), '1e-1000100'])
def test_subject_budget_is_required_and_strictly_numeric(client, hours):
    response = call(client, '/subjects', dict(promotion_id='p1', name='Nouvelle matière', trainer_id='t1', planned_hours=hours))
    assert response.status_code == 400, response.json


def test_lowering_subject_budget_below_scheduled_time_is_atomic(client, db):
    setup_school(client)
    create(client, shared_course())
    response = call(client, '/subjects/s2', dict(planned_hours=1), 'PUT')
    assert response.status_code == 409
    with db() as conn:
        assert conn.execute("SELECT planned_hours FROM planning_subjects WHERE id='s2'").fetchone()[0] == 30
    assert scheduled(client, 'p2', 's2') == 2


def test_legacy_missing_budget_remains_visible_and_blocks_new_hours_until_completed(client, db):
    setup_school(client)
    create(client)
    budget(db, 's1', None)
    state = snapshot(client)
    subject = next(item for item in state['subjects'] if item['id'] == 's1')
    assert subject['planned_hours'] is None and subject['scheduled_hours'] == 2
    response = call(client, '/courses', course(date='2027-01-05'))
    assert response.status_code == 409 and 'subject_budget_missing' in types(response)
    response = call(client, '/subjects/s1', dict(planned_hours=4), 'PUT')
    assert response.status_code == 200, response.json
    create(client, course(date='2027-01-05'))
    assert scheduled(client, 'p1', 's1') == 4


def test_repeat_preview_and_selected_batch_use_cumulative_budget(client, db):
    setup_school(client)
    budget(db, 's1', 3)
    plan = preview(client)
    assert any(issue['type'] == 'subject_budget' for item in plan['items'] for issue in item['conflicts'])
    response = call(client, '/courses/batch', dict(preview_token=plan['preview_token'], selected_keys=['0', '1']))
    assert response.status_code == 409 and 'subject_budget' in types(response)
    assert count(db) == 0
    # A different single occurrence still fits even if the full series does not.
    response = call(client, '/courses/batch', dict(preview_token=plan['preview_token'], selected_keys=['2']))
    assert response.status_code == 200, response.json
    assert count(db) == 1 and scheduled(client, 'p1', 's1') == 2


def test_shared_recurrence_counts_secondary_budget_cumulatively(client, db):
    setup_school(client)
    budget(db, 's2', 3)
    plan = preview(client, template=dict(subject_id='s1', trainer_id='t1', room_id='r1', start='09:00', end='11:00', shared=[dict(promotion_id='p2', subject_id='s2')]))
    response = call(client, '/courses/batch', dict(preview_token=plan['preview_token'], selected_keys=['0', '1']))
    assert response.status_code == 409 and 'subject_budget' in types(response)
    assert count(db) == count(db, 'planning_course_groups') == 0


def test_preview_does_not_reserve_hours_and_commit_rechecks_current_total(client, db):
    setup_school(client)
    budget(db, 's1', 3)
    plan = preview(client, end_date='2027-01-04')
    create(client, course(date='2027-01-05'))
    response = call(client, '/courses/batch', dict(preview_token=plan['preview_token'], selected_keys=['0']))
    assert response.status_code == 409 and 'subject_budget' in types(response)
    assert count(db) == 1


def test_nonoverlapping_concurrent_lessons_cannot_exceed_annual_hours(app, client, db):
    setup_school(client)
    budget(db, 's1', 3)
    barrier = Barrier(2)
    def worker(index):
        own = admin(app, 'budget-worker-' + str(index))
        barrier.wait()
        return call(own, '/courses', course(date='2027-01-0' + str(4 + index))).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(worker, [0, 1]))
    assert sorted(statuses) == [200, 409]
    assert count(db) == 1 and scheduled(client, 'p1', 's1') == 2


def test_availability_budget_blocks_new_course_but_excludes_the_edited_course(client, db):
    setup_school(client)
    budget(db, 's1', 2)
    lesson = create(client)
    query = '/admin/planning/api/availability?promotion_id=p1&subject_id=s1&trainer_id=t1&room_id=r1&start=2027-01-05&end=2027-01-05&duration=120'
    response = client.get(query)
    assert response.status_code == 200
    assert response.json['slots'] and all(not slot['available'] for slot in response.json['slots'])
    assert any(issue['type'] == 'subject_budget' for slot in response.json['slots'] for issue in slot['conflicts'])
    response = client.get(query + '&exclude_course_id=' + lesson['id'])
    assert response.status_code == 200
    assert any(slot['available'] for slot in response.json['slots'])


def test_annual_paint_is_atomic_on_course_conflict_and_validates_all_days(client, db):
    setup_school(client)
    create(client, shared_course())
    response = paint(client, 'p2', [dict(date='2027-01-05', kind='company'), dict(date='2027-01-04', kind='company')])
    assert response.status_code == 409
    assert count(db, 'planning_day_exceptions') == 0
    response = paint(client, 'p1', [dict(date='2027-01-05', kind='company'), dict(date='2027-01-06', kind=[])])
    assert response.status_code == 400
    assert count(db, 'planning_day_exceptions') == 0
    response = paint(client, 'p2', [dict(date='2027-01-05', kind='company'), dict(date='2027-01-06', kind='holiday')])
    assert response.status_code == 200, response.json
    assert count(db, 'planning_day_exceptions') == 2


def test_annual_paint_rejects_stale_revision_without_partially_overwriting(client, db):
    setup_school(client)
    revision = snapshot(client)['calendar_revision']
    response = paint(client, 'p1', [dict(date='2027-01-05', kind='company')], revision)
    assert response.status_code == 200, response.json
    response = paint(client, 'p1', [dict(date='2027-01-05', kind='school'), dict(date='2027-01-06', kind='holiday')], revision)
    assert response.status_code == 409
    assert 'calendar_stale' in types(response)
    with db() as conn:
        rows = conn.execute('SELECT date,kind FROM planning_day_exceptions').fetchall()
        assert [tuple(row) for row in rows] == [('2027-01-05', 'company')]


def test_secondary_groups_protect_parent_promotion_and_teacher_changes(client, db):
    setup_school(client)
    lesson = create(client, shared_course())
    with db() as conn:
        issues = planning.validate_promotion_change(conn, 'p2', dict(date_fin='2027-01-03'))
        assert any(issue.get('course_id') == lesson['id'] for issue in issues)
        issues = planning.validate_trainer_promotions_change(conn, 't1', ['p1'])
        assert any(issue.get('course_id') == lesson['id'] and issue.get('promotion_id') == 'p2' for issue in issues)


@pytest.mark.parametrize('shared', [{}, 'p2', [None], [dict(promotion_id=[], subject_id='s2')], [dict(promotion_id='p2', subject_id={})]])
def test_malformed_shared_groups_are_validation_errors(client, shared):
    setup_school(client)
    response = call(client, '/courses', course(shared=shared))
    assert response.status_code == 400, response.json


def test_annual_paint_requires_admin_and_csrf(app, client):
    data = dict(promotion_id='p1', days=[dict(date='2027-01-05', kind='company')])
    assert client.post('/admin/planning/api/calendar/bulk', json=data).status_code == 400
    visitor = app.test_client()
    with visitor.session_transaction() as state:
        state['_trainer_auth'] = {'trainer_id': 't1'}
        state['_planning_csrf'] = 'teacher-only'
    assert visitor.post('/admin/planning/api/calendar/bulk', json=data, headers={'X-CSRF-Token': 'teacher-only'}).status_code == 403


@pytest.fixture
def legacy_planning(tmp_path):
    """Existing production shape before shared-course schema initialization."""
    path = tmp_path / 'legacy-planning.sqlite'
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    with connect() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,bts TEXT,rentree_annee INTEGER)')
        planning.ensure_promotion_schema(conn)
        conn.executescript('''
            CREATE TABLE trainers(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,email TEXT,active INTEGER,version INTEGER);
            CREATE TABLE planning_rooms(id TEXT PRIMARY KEY,name TEXT,active INTEGER);
            CREATE TABLE planning_subjects(id TEXT PRIMARY KEY,promotion_id TEXT,name TEXT,trainer_id TEXT,color TEXT,planned_hours REAL);
            CREATE TABLE planning_calendar_rules(id TEXT PRIMARY KEY,promotion_id TEXT,start_date TEXT,end_date TEXT,weekdays TEXT,kind TEXT,label TEXT);
            CREATE TABLE planning_day_exceptions(promotion_id TEXT,date TEXT,kind TEXT,label TEXT,PRIMARY KEY(promotion_id,date));
            CREATE TABLE planning_courses(id TEXT PRIMARY KEY,promotion_id TEXT,subject_id TEXT,trainer_id TEXT,room_id TEXT,date TEXT,start_min INTEGER,end_min INTEGER,title TEXT,version INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT);
            INSERT INTO trainers VALUES('default-teacher','DEFAULT','Alex','default@example.test',1,1),('actual-teacher','ACTUAL','Sam','actual@example.test',1,1);
            INSERT INTO planning_rooms VALUES('legacy-room','Salle historique',1);
            INSERT INTO planning_subjects VALUES('legacy-subject','legacy-promotion','Matière historique','default-teacher','#445566',NULL);
            INSERT INTO planning_calendar_rules VALUES('legacy-rule','legacy-promotion','2027-01-01','2027-03-31','[0,1,2,3,4]','school','École');
            INSERT INTO planning_courses VALUES('legacy-course','legacy-promotion','legacy-subject','actual-teacher','legacy-room','2027-01-04',540,660,'Cours historique',5,'old-created','old-updated');
        ''')
        conn.execute("INSERT INTO promotions VALUES('legacy-promotion','Promotion historique','MCO',1,2026,'2027-01-01','2027-03-31',1,0,'old-created','old-updated')")
        for tid in ('default-teacher', 'actual-teacher'):
            conn.execute('INSERT INTO trainer_promotions VALUES(?,?)', (tid, 'legacy-promotion'))
    return connect


def test_parent_edit_guards_work_before_shared_schema_migration_without_committing(legacy_planning):
    conn = legacy_planning()
    try:
        assert not planning._has_table(conn, 'planning_course_groups')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE planning_rooms SET name='Uncommitted' WHERE id='legacy-room'")
        issues = planning.validate_promotion_change(conn, 'legacy-promotion', dict(date_fin='2027-01-03'))
        assert any(item.get('course_id') == 'legacy-course' for item in issues)
        issues = planning.validate_trainer_promotions_change(conn, 'actual-teacher', [])
        assert any(item.get('course_id') == 'legacy-course' for item in issues)
        assert conn.in_transaction
        assert not planning._has_table(conn, 'planning_course_groups')
        conn.rollback()
        assert conn.execute("SELECT name FROM planning_rooms WHERE id='legacy-room'").fetchone()[0] == 'Salle historique'
    finally:
        conn.close()


def test_shared_schema_migration_preserves_legacy_course_and_unconfigured_budget(legacy_planning):
    with legacy_planning() as conn:
        planning.ensure_planning_schema(conn)
        planning.ensure_planning_schema(conn)
        row = conn.execute("SELECT * FROM planning_courses WHERE id='legacy-course'").fetchone()
        assert row['version'] == 5 and row['trainer_id'] == 'actual-teacher'
        assert row['created_at'] == 'old-created' and row['updated_at'] == 'old-updated'
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM planning_course_groups').fetchone()[0] == 1
        state = planning.get_planning_snapshot(conn, 'legacy-promotion')
        assert state['subjects'][0]['planned_hours'] is None
        assert state['subjects'][0]['scheduled_hours'] == 2
        assert state['courses'][0]['id'] == 'legacy-course'
        assert {item['promotion_id'] for item in state['courses'][0]['groups']} == {'legacy-promotion'}


def test_actual_override_teacher_cannot_lose_secondary_shared_promotion(client, db):
    setup_school(client)
    lesson = create(client, shared_course(trainer_id='t2'))
    with db() as conn:
        # The subjects belong to t1; the actual session is taught by t2.
        assert conn.execute("SELECT trainer_id FROM planning_subjects WHERE id='s2'").fetchone()[0] == 't1'
        issues = planning.validate_trainer_promotions_change(conn, 't2', ['p1'])
        assert any(item.get('course_id') == lesson['id'] and item.get('promotion_id') == 'p2' for item in issues)


def test_duplication_from_secondary_promotion_keeps_shared_identity_and_charges_both(client, db):
    setup_school(client)
    lesson = create(client, shared_course())
    response = call(client, '/courses/preview', dict(promotion_id='p2', mode='duplicate',
        course_ids=[lesson['id']], target_start='2027-01-11'))
    assert response.status_code == 200, response.json
    plan = response.json
    assert {group['promotion_id'] for group in plan['items'][0]['course']['groups']} == {'p1', 'p2'}
    response = call(client, '/courses/batch', dict(preview_token=plan['preview_token'], selected_keys=['0']))
    assert response.status_code == 200, response.json
    assert count(db) == 2
    assert scheduled(client, 'p1', 's1') == scheduled(client, 'p2', 's2') == 4


def test_shared_availability_checks_secondary_budget_calendar_and_self_exclusion(client, db):
    setup_school(client)
    budget(db, 's2', 2)
    lesson = create(client, shared_course())
    query = dict(promotion_id='p1', subject_id='s1', trainer_id='t1', room_id='r1',
                 start='2027-01-05', end='2027-01-05', duration=120,
                 shared=json.dumps([dict(promotion_id='p2', subject_id='s2')]))
    response = client.get('/admin/planning/api/availability', query_string=query)
    assert response.status_code == 200
    assert all(not slot['available'] for slot in response.json['slots'])
    assert any(issue['type'] == 'subject_budget' and issue['promotion_id'] == 'p2'
               for slot in response.json['slots'] for issue in slot['conflicts'])
    query['exclude_course_id'] = lesson['id']
    response = client.get('/admin/planning/api/availability', query_string=query)
    assert response.status_code == 200 and any(slot['available'] for slot in response.json['slots'])
    assert paint(client, 'p2', [dict(date='2027-01-05', kind='company')]).status_code == 200
    response = client.get('/admin/planning/api/availability', query_string=query)
    assert response.status_code == 200
    assert all(not slot['available'] for slot in response.json['slots'])
    assert any(issue['type'] == 'not_school' and issue['promotion_id'] == 'p2'
               for slot in response.json['slots'] for issue in slot['conflicts'])


def test_concurrent_annual_paints_do_not_overwrite_the_same_revision(app, client, db):
    setup_school(client)
    revision = snapshot(client)['calendar_revision']
    barrier = Barrier(2)
    def worker(index):
        own = admin(app, 'paint-worker-' + str(index))
        barrier.wait()
        return paint(own, 'p1', [dict(date='2027-01-0' + str(5 + index), kind='company')], revision).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(worker, [0, 1]))
    assert sorted(statuses) == [200, 409]
    assert count(db, 'planning_day_exceptions') == 1
