"""Confirmed admin absences delete exactly the previewed courses, atomically."""
import sqlite3

import pytest

import trainer_admin_planning as panels
from trainer_workload import get_trainer_workload
from trainer_availability import get_trainer_availability_state
from test_trainer_workload import workload_db, workload_client, lesson
from test_trainer_admin_planning_audit import admin_client, absence_data


def selection(db):
    return dict(dates=['2027-01-04', '2027-01-05'], reason='Déplacement',
                expected_revision=absence_data(db)['state']['revision'])


def save(client, payload, trainer='t1', csrf='test-token'):
    return client.post(f'/admin/formateurs/{trainer}/indisponibilites/jours',
                       json=payload, headers={'X-CSRF-Token': csrf})


def prepare(client, db):
    payload = selection(db)
    response = save(client, payload)
    assert response.status_code == 409
    assert response.json['preview_token']
    return payload, response.json


def confirm(client, payload, preview, **kwargs):
    return save(client, dict(payload, preview_token=preview['preview_token'], confirm_delete=True), **kwargs)


def state(db):
    with db() as conn:
        return tuple([tuple(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY 1')]
                     for table in ('planning_courses', 'planning_course_groups', 'planning_trainer_unavailability'))


def test_preview_then_confirmation_updates_only_selected_trainers_dates_and_all_shared_groups(admin_client, workload_db):
    with workload_db() as conn:
        lesson(conn, 'shared', groups=('p1', 'p2', 'p3'))
        lesson(conn, 'second', day='2027-01-05')
        lesson(conn, 'outside', day='2027-01-06')
        lesson(conn, 'colleague', trainer='t2')
    before = state(workload_db)
    payload, preview = prepare(admin_client, workload_db)
    assert state(workload_db) == before
    assert len(preview['conflicts']) == 2
    assert preview['conflicts'][0]['shared']
    assert set(preview['conflicts'][0]['promotion_names']) == {'Promotion p1', 'Promotion p2', 'Promotion p3'}
    response = confirm(admin_client, payload, preview)
    assert response.status_code == 200 and response.json['removed_count'] == 2
    assert response.headers['Cache-Control'] == 'private, no-store'
    with workload_db() as conn:
        assert {row['id'] for row in conn.execute('SELECT id FROM planning_courses')} == {'outside', 'colleague'}
        assert {row['course_id'] for row in conn.execute('SELECT course_id FROM planning_course_groups')} == {'outside', 'colleague'}
        blocks = [dict(row) for row in conn.execute('SELECT * FROM planning_trainer_unavailability')]
        assert len(blocks) == 2 and all(row['trainer_id'] == 't1' and row['reason'] == 'Déplacement' for row in blocks)
        assert get_trainer_workload(conn, 't1', '2027-01')['total_minutes'] == 120
        days = {day['date']: day for day in get_trainer_availability_state(conn, 't1', 2027)['days']}
        assert all(days[day]['unavailable'] and not days[day]['course_count'] for day in payload['dates'])
    after = state(workload_db)
    assert confirm(admin_client, payload, preview).status_code == 409
    assert state(workload_db) == after


@pytest.mark.parametrize('change', ['added', 'removed', 'moved', 'time', 'trainer', 'group', 'absence'])
def test_changed_preview_never_deletes_or_blocks_anything(admin_client, workload_db, change):
    with workload_db() as conn:
        lesson(conn, groups=('p1', 'p2'))
    payload, preview = prepare(admin_client, workload_db)
    with workload_db() as conn:
        if change == 'added':
            lesson(conn, 'new', day='2027-01-05')
        elif change == 'removed':
            conn.execute("DELETE FROM planning_course_groups WHERE course_id='c1'")
            conn.execute("DELETE FROM planning_courses WHERE id='c1'")
        elif change == 'moved':
            conn.execute("UPDATE planning_courses SET date='2027-01-06' WHERE id='c1'")
        elif change == 'time':
            conn.execute("UPDATE planning_courses SET start_min=500 WHERE id='c1'")
        elif change == 'trainer':
            conn.execute("UPDATE planning_courses SET trainer_id='t2' WHERE id='c1'")
        elif change == 'group':
            conn.execute("INSERT INTO planning_course_groups VALUES('c1','p3','sp3')")
        else:
            conn.execute("INSERT INTO planning_trainer_unavailability VALUES('new','t1','2027-01-05','2027-01-05','[0,1,2,3,4,5,6]','[]','Autre')")
    before = state(workload_db)
    assert confirm(admin_client, payload, preview).status_code == 409
    assert state(workload_db) == before


@pytest.mark.parametrize('change', ['dates', 'reason', 'token', 'missing_token', 'no_confirmation', 'truthy_confirmation', 'trainer', 'session', 'expired'])
def test_confirmation_is_explicit_signed_and_scoped(admin_client, workload_db, monkeypatch, change):
    with workload_db() as conn:
        lesson(conn)
    payload, preview = prepare(admin_client, workload_db)
    payload.update(preview_token=preview['preview_token'], confirm_delete=True)
    kwargs = {}
    if change == 'dates':
        payload['dates'] = ['2027-01-04']
    elif change == 'reason':
        payload['reason'] = 'Autre motif'
    elif change == 'token':
        payload['preview_token'] = 'invalid'
    elif change == 'missing_token':
        payload.pop('preview_token')
    elif change == 'no_confirmation':
        payload.pop('confirm_delete')
    elif change == 'truthy_confirmation':
        payload['confirm_delete'] = 'true'
    elif change == 'trainer':
        kwargs['trainer'] = 't2'
    elif change == 'session':
        with admin_client.session_transaction() as session:
            session['_trainer_csrf'] = 'another-session'
        kwargs['csrf'] = 'another-session'
    else:
        monkeypatch.setattr(panels, 'PREVIEW_TTL', -1)
    before = state(workload_db)
    assert save(admin_client, payload, **kwargs).status_code == 409
    assert state(workload_db) == before


def test_holiday_and_missing_admin_or_csrf_cannot_delete(admin_client, workload_db):
    with workload_db() as conn:
        lesson(conn)
    payload, preview = prepare(admin_client, workload_db)
    before = state(workload_db)
    confirmed = dict(payload, preview_token=preview['preview_token'], confirm_delete=True)
    assert save(admin_client.application.test_client(), confirmed).status_code == 403
    assert save(admin_client, confirmed, csrf='incorrect').status_code == 400
    confirmed['dates'].append('2027-05-06')
    assert save(admin_client, confirmed).status_code == 400
    assert state(workload_db) == before


def test_failed_absence_insert_rolls_back_course_and_group_deletions(admin_client, workload_db):
    with workload_db() as conn:
        lesson(conn, groups=('p1', 'p2'))
    payload, preview = prepare(admin_client, workload_db)
    with workload_db() as conn:
        conn.execute("""CREATE TRIGGER fail_second_absence BEFORE INSERT ON planning_trainer_unavailability
            WHEN NEW.start_date='2027-01-05' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    before = state(workload_db)
    with pytest.raises(sqlite3.IntegrityError, match='test failure'):
        confirm(admin_client, payload, preview)
    assert state(workload_db) == before
