"""Independent, cross-feature regressions for duplication and trainer changes.

Only isolated SQLite fixtures and Flask clients are used; no live accounts,
notifications or business records are touched.
"""
from datetime import datetime
import json
import time
from unittest.mock import patch

from flask import Flask, session
from jinja2 import DictLoader
import pytest

import planning
import planning_portal
from test_planning_portal_security import portal_db


@pytest.fixture
def audit_db(portal_db):
    with portal_db() as conn:
        conn.execute('DELETE FROM planning_course_groups')
        conn.execute('DELETE FROM planning_courses')
        # Both groups can receive shared sessions throughout the school year.
        for pid in ('p1', 'p2'):
            conn.execute('''INSERT INTO planning_calendar_rules VALUES(
                ?,?,'2026-09-01','2027-08-31','[0,1,2,3,4]','school','École')''', ('rule-' + pid, pid))
        conn.execute("UPDATE planning_subjects SET trainer_id='t1' WHERE id='s2'")
    return portal_db


@pytest.fixture
def audit_app(audit_db):
    app = Flask(__name__)
    app.secret_key = 'cross-feature-independent-test-only'
    app.config['TESTING'] = True
    app.jinja_loader = DictLoader({'planning_admin.html': 'planning', 'portal_planning.html': '{{ portal_planning|tojson }}'})
    app.add_url_rule('/formateur/connexion', 'trainer_login', lambda: 'login')
    app.add_url_rule('/espace/connexion', 'candidate_login', lambda: 'login')
    app.add_url_rule('/espace/mot-de-passe', 'student_change_password', lambda: 'password')
    planning.register_planning(app, audit_db, lambda: bool(session.get('audit_admin')))
    planning_portal.register_planning_portal(app, audit_db)
    return app


@pytest.fixture
def audit_admin(audit_app):
    client = audit_app.test_client()
    with client.session_transaction() as auth:
        auth['audit_admin'] = True
        auth['_planning_csrf'] = 'audit-admin-csrf'
    return client


def admin_post(client, path, data, method='POST'):
    return client.open('/admin/planning/api' + path, method=method, json=data,
                       headers={'X-CSRF-Token': 'audit-admin-csrf'})


def add_course(client, **changes):
    data = dict(promotion_id='p1', subject_id='s1', room_id='r1',
                date='2027-01-04', start='09:00', end='11:00', title='Séance test')
    data.update(changes)
    response = admin_post(client, '/courses', data)
    assert response.status_code == 200, response.json
    return response.json['course']


def weeks(client, **changes):
    data = dict(promotion_id='p1', mode='weeks', source_start='2027-01-04', target_weeks=['2027-01-11'])
    data.update(changes)
    response = admin_post(client, '/courses/preview', data)
    assert response.status_code == 200, response.json
    return response.json


def commit_weeks(client, preview):
    return admin_post(client, '/courses/batch', dict(preview_token=preview['preview_token'],
        selected_keys=[item['key'] for item in preview['items']]))


def table_count(db, table='planning_courses'):
    with db() as conn:
        return conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]


def portal(db, role='student', person='c1', day='2027-01-04'):
    with db() as conn:
        return planning_portal.get_portal_week(conn, role, person, day)


def test_week_commit_skips_new_trainer_conflict_and_updates_all_shared_portals(audit_admin, audit_db):
    source = add_course(audit_admin, shared=[dict(promotion_id='p2', subject_id='s2')])
    add_course(audit_admin, subject_id='s3', date='2027-01-05')
    preview = weeks(audit_admin)
    assert preview['summary']['valid'] == 2
    # A different administrator adds a trainer conflict after the preview.
    with audit_db() as conn:
        conn.execute('''INSERT INTO planning_trainer_unavailability VALUES(
            'new-block','t2','2027-01-12','2027-01-12','[1]','[]','Mission externe')''')
    result = commit_weeks(audit_admin, preview)
    assert result.status_code == 200, result.json
    assert result.json['count'] == result.json['skipped_count'] == 1
    assert {reason['type'] for reason in result.json['skipped'][0]['conflicts']} == {'unavailable'}
    assert table_count(audit_db) == 3
    created_id = result.json['course_ids'][0]
    for role, identity in [('student', 'c1'), ('student', 'c2'), ('trainer', 't1')]:
        snapshot = portal(audit_db, role, identity, '2027-01-11')
        assert {item['id'] for item in snapshot['courses']} == {created_id}
        assert snapshot['summary']['minutes'] == 120
    assert source['id'] != created_id


def test_week_commit_rechecks_whole_source_set_before_any_partial_insert(audit_admin, audit_db):
    add_course(audit_admin)
    preview = weeks(audit_admin)
    add_course(audit_admin, date='2027-01-05')
    result = commit_weeks(audit_admin, preview)
    assert result.status_code == 409
    assert table_count(audit_db) == 2
    assert not portal(audit_db, day='2027-01-11')['courses']


def test_week_holiday_is_skipped_but_other_weekday_preserves_exact_minutes(audit_admin, audit_db):
    add_course(audit_admin, date='2027-03-15', start='08:17', end='09:46')
    add_course(audit_admin, date='2027-03-16', start='08:17', end='09:46')
    preview = weeks(audit_admin, source_start='2027-03-15', target_weeks=['2027-03-29'])
    assert preview['summary'] == dict(total=2, valid=1, conflicts=1)
    result = commit_weeks(audit_admin, preview)
    assert result.status_code == 200
    assert result.json['count'] == result.json['skipped_count'] == 1
    snapshot = portal(audit_db, day='2027-03-29')
    assert snapshot['summary']['minutes'] == 89
    assert snapshot['courses'][0]['date'] == '2027-03-30'
    assert snapshot['days'][0]['public_holiday'] is True


def test_week_preview_token_cannot_be_used_from_another_admin_session(audit_app, audit_admin, audit_db):
    add_course(audit_admin)
    preview = weeks(audit_admin)
    other = audit_app.test_client()
    with other.session_transaction() as auth:
        auth['audit_admin'] = True
        auth['_planning_csrf'] = 'other-session'
    response = other.post('/admin/planning/api/courses/batch', json={
        'preview_token': preview['preview_token'], 'selected_keys': ['0']},
        headers={'X-CSRF-Token': 'other-session'})
    assert response.status_code == 409
    assert table_count(audit_db) == 1


def test_week_duplicate_replay_does_not_double_hours(audit_admin, audit_db):
    add_course(audit_admin, shared=[dict(promotion_id='p2', subject_id='s2')])
    preview = weeks(audit_admin)
    first = commit_weeks(audit_admin, preview)
    assert first.status_code == 200 and first.json['count'] == 1
    repeated = commit_weeks(audit_admin, preview)
    assert repeated.status_code == 200 and repeated.json['count'] == 0
    assert repeated.json['skipped_count'] == 1
    assert table_count(audit_db) == 2
    assert table_count(audit_db, 'planning_course_groups') == 4


@pytest.fixture
def availability_app(audit_app, audit_db, monkeypatch):
    import trainer_availability
    monkeypatch.setattr(trainer_availability, '_now_paris',
        lambda: datetime(2026, 10, 25, 10, 0, tzinfo=planning_portal.PARIS))
    trainer_availability.register_trainer_availability(audit_app, audit_db)
    return audit_app


def trainer_client(app, identity='t1', csrf='audit-trainer-csrf'):
    client = app.test_client()
    with client.session_transaction() as auth:
        auth['_trainer_auth'] = dict(trainer_id=identity, version=1, expires_at=time.time() + 3600)
        auth['_trainer_csrf'] = csrf
    return client


def trainer_post(client, path, payload):
    with client.session_transaction() as auth:
        token = auth.get('_trainer_csrf', '')
    return client.post('/formateur/indisponibilites/api/' + path, json=payload,
        headers={'X-CSRF-Token': token})


def absence_preview(client, days=None, action='unavailable'):
    response = trainer_post(client, 'preview', dict(dates=days or ['2027-01-04'], action=action))
    assert response.status_code == 200, response.json
    return response.json


def workload(db, identity='t1', month='2027-01'):
    import trainer_workload
    with db() as conn:
        trainer_workload.ensure_workload_schema(conn)
        return trainer_workload.get_trainer_workload(conn, identity, month)


def test_absence_confirmation_removes_shared_course_once_and_releases_every_budget(
        availability_app, audit_admin, audit_db):
    shared = add_course(audit_admin, shared=[dict(promotion_id='p2', subject_id='s2')])
    colleague = add_course(audit_admin, subject_id='s3', start='13:00', end='14:00')
    client = trainer_client(availability_app)
    before = workload(audit_db)
    assert before['total_minutes'] == 120
    assert [row['minutes'] for row in before['by_promotion']] == [120, 120]
    preview = absence_preview(client)
    assert preview['course_count'] == 1 and preview['requires_confirmation']
    assert set(preview['courses'][0]['promotion_names']) == {'PROMOTION LOCALE', 'PROMOTION AUTRE'}
    assert table_count(audit_db) == 2
    rejected = trainer_post(client, 'commit', dict(preview_token=preview['preview_token'], confirm_delete=False))
    assert rejected.status_code == 409 and table_count(audit_db) == 2
    saved = trainer_post(client, 'commit', dict(preview_token=preview['preview_token'], confirm_delete=True))
    assert saved.status_code == 200 and saved.json['removed_count'] == 1
    assert table_count(audit_db) == table_count(audit_db, 'planning_course_groups') == 1
    assert {row['id'] for row in portal(audit_db)['courses']} == {colleague['id']}
    assert portal(audit_db, person='c2')['courses'] == []
    assert portal(audit_db, role='trainer', person='t1')['courses'] == []
    assert workload(audit_db)['total_minutes'] == 0
    with audit_db() as conn:
        assert planning._subject_minutes(conn, 's1') == planning._subject_minutes(conn, 's2') == 0
    # Mutation reaches the same core conflict checker used by admin drag/drop.
    blocked = admin_post(audit_admin, '/courses', dict(promotion_id='p1', subject_id='s1',
        date='2027-01-04', start='15:00', end='16:00'))
    assert blocked.status_code == 409
    assert 'unavailable' in {row['type'] for row in blocked.json['conflicts']}
    replay = trainer_post(client, 'commit', dict(preview_token=preview['preview_token'], confirm_delete=True))
    assert replay.status_code == 409
    assert table_count(audit_db) == 1
    assert shared['id'] != colleague['id']


@pytest.mark.parametrize('change', ['new_course', 'edited_course', 'shared_group'])
def test_new_or_changed_course_requires_new_absence_confirmation(
        availability_app, audit_admin, audit_db, change):
    source = add_course(audit_admin)
    client = trainer_client(availability_app)
    preview = absence_preview(client)
    if change == 'new_course':
        add_course(audit_admin, start='13:00', end='14:00')
    elif change == 'edited_course':
        response = admin_post(audit_admin, '/courses/' + source['id'],
            dict(version=source['version'], title='Nouveau contenu'), 'PUT')
        assert response.status_code == 200
    else:
        # Even a direct data correction without a version bump changes the
        # affected groups shown in the confirmation, so it must invalidate it.
        with audit_db() as conn:
            conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)', (source['id'], 'p2', 's2'))
    expected = table_count(audit_db)
    result = trainer_post(client, 'commit', dict(preview_token=preview['preview_token'], confirm_delete=True))
    assert result.status_code == 409
    assert table_count(audit_db) == expected
    assert table_count(audit_db, 'planning_trainer_unavailability') == 0


def test_self_service_available_does_not_erase_admin_block_or_other_trainer_courses(
        availability_app, audit_admin, audit_db):
    client = trainer_client(availability_app)
    with audit_db() as conn:
        conn.execute('''INSERT INTO planning_trainer_unavailability VALUES(
            'admin-block','t1','2027-01-04','2027-01-04','[0]','[]','Mission décidée par administration')''')
    colleague = add_course(audit_admin, subject_id='s3')
    unavailable = absence_preview(client)
    result = trainer_post(client, 'commit', dict(preview_token=unavailable['preview_token']))
    assert result.status_code == 200
    available = absence_preview(client, action='available')
    result = trainer_post(client, 'commit', dict(preview_token=available['preview_token']))
    assert result.status_code == 200
    with audit_db() as conn:
        rows = list(conn.execute('SELECT id FROM planning_trainer_unavailability'))
        assert [row['id'] for row in rows] == ['admin-block']
    assert {row['id'] for row in portal(audit_db)['courses']} == {colleague['id']}
    state = client.get('/formateur/indisponibilites/api/state?year=2027').json
    day = next(row for row in state['days'] if row['date'] == '2027-01-04')
    assert day['admin_unavailable'] and not day['own_unavailable'] and day['unavailable']


@pytest.mark.parametrize('kind', ['other_trainer', 'different_session', 'account_revoked'])
def test_absence_confirmation_cannot_cross_account_or_session(
        availability_app, audit_admin, audit_db, kind):
    add_course(audit_admin)
    client = trainer_client(availability_app)
    preview = absence_preview(client)
    if kind == 'other_trainer':
        actor = trainer_client(availability_app, identity='t2')
    elif kind == 'different_session':
        actor = trainer_client(availability_app, csrf='second-session-token')
    else:
        actor = client
        with audit_db() as conn:
            conn.execute("UPDATE trainers SET version=version+1 WHERE id='t1'")
    response = trainer_post(actor, 'commit', dict(preview_token=preview['preview_token'], confirm_delete=True))
    assert response.status_code in (401, 409)
    assert table_count(audit_db) == 1
    assert table_count(audit_db, 'planning_trainer_unavailability') == 0


def test_workload_rate_history_and_planning_edits_recompute_month_without_shared_double_count(
        audit_admin, audit_db):
    import trainer_workload
    first = add_course(audit_admin, shared=[dict(promotion_id='p2', subject_id='s2')], start='08:00', end='09:30')
    add_course(audit_admin, date='2027-02-01', start='08:00', end='09:30')
    with audit_db() as conn:
        trainer_workload.ensure_workload_schema(conn)
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        revision = trainer_workload.save_hourly_rate(conn, 't1', '2027-01-01', '40,20', 0)
        trainer_workload.save_hourly_rate(conn, 't1', '2027-02-01', '50', revision)
    january = workload(audit_db)
    february = workload(audit_db, month='2027-02')
    assert january['total_minutes'] == 90 and january['estimated_cents'] == 6030
    assert february['total_minutes'] == 90 and february['estimated_cents'] == 7500
    assert sum(row['minutes'] for row in january['by_promotion']) == 180
    assert sum(row['minutes'] for row in january['by_bts']) == 90
    changed = admin_post(audit_admin, '/courses/' + first['id'], dict(version=first['version'], end='09:00'), 'PUT')
    assert changed.status_code == 200
    assert workload(audit_db)['estimated_cents'] == 4020
    for person in ('c1', 'c2'):
        snapshot = portal(audit_db, person=person)
        assert snapshot['summary']['minutes'] == 60
        text = json.dumps(snapshot)
        assert 'rate_cents' not in text and 'estimated_cents' not in text

