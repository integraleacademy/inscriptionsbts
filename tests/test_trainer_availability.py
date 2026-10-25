"""Trainer calendar declarations, ownership boundaries and cancellation consent."""
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo

from flask import Flask
from jinja2 import DictLoader
import pytest

import planning
import trainer_availability as availability
from test_planning_portal_security import portal_db

BASE = '/formateur/indisponibilites/api'


@pytest.fixture
def app(portal_db, monkeypatch):
    monkeypatch.setattr(availability, '_now_paris', lambda: datetime(2026, 10, 25, 10, tzinfo=ZoneInfo('Europe/Paris')))
    app = Flask(__name__)
    app.secret_key = 'trainer-calendar-fixture-only'
    app.config['TESTING'] = True
    app.jinja_loader = DictLoader({'trainer_availability.html': '{{ availability|tojson }}'})
    app.add_url_rule('/formateur/connexion', 'trainer_login', lambda: 'Login')
    app.add_url_rule('/formateur', 'trainer_dashboard', lambda: 'Dashboard')
    app.add_url_rule('/formateur/planning', 'trainer_planning', lambda: 'Planning')
    availability.register_trainer_availability(app, portal_db)
    return app


def logged(app, trainer='t1', csrf='fixture-csrf'):
    client = app.test_client()
    with client.session_transaction() as state:
        state['_trainer_auth'] = dict(trainer_id=trainer, version=1, expires_at=time.time() + 3600)
        state['_trainer_csrf'] = csrf
    return client


def post(client, path, data, csrf='fixture-csrf'):
    return client.post(BASE + path, json=data, headers={'X-CSRF-Token': csrf})


def preview(client, dates=None, action='unavailable', **extra):
    return post(client, '/preview', dict(dates=dates or ['2027-01-05'], action=action, **extra))


def commit(client, token, **extra):
    return post(client, '/commit', dict(preview_token=token, **extra))


def count(db, table):
    with db() as conn:
        return conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]


def test_page_and_state_are_authenticated_private_and_identity_scoped(app, portal_db):
    assert app.test_client().get('/formateur/indisponibilites').status_code == 302
    assert app.test_client().get(BASE + '/state').status_code == 401
    client = logged(app)
    page = client.get('/formateur/indisponibilites?year=2027')
    assert page.status_code == 200
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert page.headers['Referrer-Policy'] == 'no-referrer'
    state = client.get(BASE + '/state?year=2027').json
    assert len(state['days']) == 365
    assert state['csrf_token'] == 'fixture-csrf'
    by_date = {day['date']: day for day in state['days']}
    # The archived primary group still represents this trainer's reservation.
    assert by_date['2027-01-04']['course_count'] == 2
    assert by_date['2027-01-05']['course_count'] == 1
    assert by_date['2027-01-01']['public_holiday']
    assert 'example.test' not in json.dumps(state)
    assert 'secret-' not in json.dumps(state)


@pytest.mark.parametrize('query', ['year=2027&trainer_id=t2', 'year=2027&year=2028', 'year=1', 'year=2201', 'year=garbage'])
def test_state_rejects_scope_override_and_invalid_year(app, query):
    assert logged(app).get(BASE + '/state?' + query).status_code == 400


def test_preview_is_read_only_and_lists_all_shared_promotions(app, portal_db):
    before = count(portal_db, 'planning_courses')
    result = preview(logged(app)).json
    assert result['ok'] and result['requires_confirmation']
    assert result['course_count'] == 1
    assert result['courses'][0]['id'] == 'shared'
    assert result['courses'][0]['shared']
    assert set(result['courses'][0]['promotion_names']) == {'PROMOTION LOCALE', 'PROMOTION AUTRE'}
    assert count(portal_db, 'planning_courses') == before
    assert count(portal_db, 'planning_trainer_unavailability') == 0


@pytest.mark.parametrize('confirmation', [None, False, 'true', 1])
def test_course_deletion_requires_boolean_explicit_confirmation(app, portal_db, confirmation):
    client = logged(app)
    token = preview(client).json['preview_token']
    response = commit(client, token, confirm_delete=confirmation)
    assert response.status_code == 409
    assert count(portal_db, 'planning_courses') == 6
    assert count(portal_db, 'planning_trainer_unavailability') == 0


def test_confirmed_absence_deletes_once_and_releases_all_shared_subject_hours(app, portal_db):
    client = logged(app)
    token = preview(client).json['preview_token']
    with portal_db() as conn:
        previous1 = planning._subject_minutes(conn, 's1')
        previous2 = planning._subject_minutes(conn, 's2')
    response = commit(client, token, confirm_delete=True)
    assert response.status_code == 200
    assert response.json['removed_count'] == 1
    assert response.json['added_dates'] == ['2027-01-05']
    with portal_db() as conn:
        assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone() is None
        assert conn.execute("SELECT 1 FROM planning_course_groups WHERE course_id='shared'").fetchone() is None
        assert planning._subject_minutes(conn, 's1') == previous1 - 120
        assert planning._subject_minutes(conn, 's2') == previous2 - 120
        unavailable = planning._unavailability(conn, 't1')
        assert unavailable[0]['start_date'] == unavailable[0]['end_date'] == '2027-01-05'
    assert commit(client, token, confirm_delete=True).status_code == 409
    assert count(portal_db, 'planning_courses') == 5


def test_available_only_removes_personal_block_and_never_recreates_courses(app, portal_db):
    client = logged(app)
    first = preview(client).json['preview_token']
    assert commit(client, first, confirm_delete=True).status_code == 200
    with portal_db() as conn:
        conn.execute("INSERT INTO planning_trainer_unavailability VALUES('admin','t1','2027-01-05','2027-01-05','[1]','[]','Administratif')")
    state = client.get(BASE + '/state?year=2027').json
    day = next(item for item in state['days'] if item['date'] == '2027-01-05')
    assert day['own_unavailable'] and day['admin_unavailable']
    token = preview(client, action='available').json['preview_token']
    response = commit(client, token)
    assert response.status_code == 200
    assert response.json['removed_dates'] == ['2027-01-05']
    assert response.json['removed_count'] == 0
    with portal_db() as conn:
        blocks = planning._unavailability(conn, 't1')
        assert [row['id'] for row in blocks] == ['admin']
        assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone() is None


def test_partial_admin_block_and_whole_day_personal_state(app, portal_db):
    with portal_db() as conn:
        conn.execute("INSERT INTO planning_trainer_unavailability VALUES('admin','t1','2027-01-07','2027-01-07','[3]',?,'Administratif')", (json.dumps([{'start': '08:00', 'end': '10:00'}]),))
    client = logged(app)
    state = client.get(BASE + '/state?year=2027').json
    day = next(item for item in state['days'] if item['date'] == '2027-01-07')
    assert day['partial'] and day['admin_unavailable'] and not day['own_unavailable']
    token = preview(client, ['2027-01-07']).json['preview_token']
    assert commit(client, token).status_code == 200
    state = client.get(BASE + '/state?year=2027').json
    day = next(item for item in state['days'] if item['date'] == '2027-01-07')
    assert not day['partial'] and day['own_unavailable'] and day['admin_unavailable']


def test_admin_removed_personal_block_can_be_redeclared(app, portal_db):
    client = logged(app)
    token = preview(client, ['2027-01-07']).json['preview_token']
    assert commit(client, token).status_code == 200
    with portal_db() as conn:
        conn.execute("DELETE FROM planning_trainer_unavailability WHERE trainer_id='t1'")
    token = preview(client, ['2027-01-07']).json['preview_token']
    assert commit(client, token).status_code == 200
    assert count(portal_db, 'planning_trainer_owned_absences') == 1
    assert count(portal_db, 'planning_trainer_unavailability') == 1


def test_csrf_and_extra_identifiers_rejected(app):
    client = logged(app)
    assert post(client, '/preview', {'dates': ['2027-01-07'], 'action': 'unavailable'}, csrf='wrong').status_code == 403
    assert preview(client, trainer_id='t2').status_code == 400


@pytest.mark.parametrize('dates', [[], ['invalid'], ['2027-02-30'], ['2201-01-01'], ['2027-01-01'] * 741])
def test_invalid_dates_never_mutate(app, portal_db, dates):
    response = post(logged(app), '/preview', dict(dates=dates, action='unavailable'))
    assert response.status_code == 400
    assert count(portal_db, 'planning_trainer_unavailability') == 0


def test_past_and_already_started_today_cannot_delete_realized_hours(app, portal_db, monkeypatch):
    client = logged(app)
    assert preview(client, ['2026-10-24']).status_code == 400
    monkeypatch.setattr(availability, '_now_paris', lambda: datetime(2027, 1, 5, 9, tzinfo=ZoneInfo('Europe/Paris')))
    response = preview(client)
    assert response.status_code == 400
    assert 'déjà commencé' in response.json['message']
    assert count(portal_db, 'planning_courses') == 6


def test_course_starting_between_preview_and_commit_preserves_history(app, portal_db, monkeypatch):
    client = logged(app)
    monkeypatch.setattr(availability, '_now_paris', lambda: datetime(2027, 1, 5, 8, 59, tzinfo=ZoneInfo('Europe/Paris')))
    token = preview(client).json['preview_token']
    monkeypatch.setattr(availability, '_now_paris', lambda: datetime(2027, 1, 5, 9, tzinfo=ZoneInfo('Europe/Paris')))
    assert commit(client, token, confirm_delete=True).status_code == 409
    assert count(portal_db, 'planning_courses') == 6


def test_date_duplicates_normalized_and_empty_personal_removal_safe(app, portal_db):
    client = logged(app)
    result = preview(client, ['2027-01-08', '2027-01-07', '2027-01-07']).json
    assert result['dates'] == ['2027-01-07', '2027-01-08']
    assert commit(client, result['preview_token']).status_code == 200
    token = preview(client, ['2027-01-06'], action='available').json['preview_token']
    assert commit(client, token).status_code == 200
    assert count(portal_db, 'planning_trainer_unavailability') == 2

