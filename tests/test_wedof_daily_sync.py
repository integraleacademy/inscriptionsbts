"""Daily scheduling uses synthetic WEDOF responses and a controlled Paris clock."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest
import requests

from test_wedof_contracts import setup, discover, directory_state, post
import wedof_contracts as wc
from wedof_daily_sync import initialize, next_morning, tick, PARIS


@pytest.fixture
def daily(setup, monkeypatch):
    clock = [datetime.now(PARIS).replace(hour=7, minute=59, second=0, microsecond=0)]
    monkeypatch.setattr(wc.time, 'time', lambda: clock[0].timestamp())
    with setup[0].session_transaction() as state:
        state['admin_ok'] = True
        state['_wedof_csrf'] = 'test-csrf'
    with setup[1]() as conn:
        conn.execute("ALTER TABLE candidats ADD COLUMN statut TEXT DEFAULT 'confirmee'")
        conn.execute("UPDATE candidats SET statut='preinscription' WHERE id='bob'")
    initialize(setup[1], clock[0])
    return setup, clock


def step(daily, sync=None):
    env, clock = daily
    with env[4].app_context():
        return tick(env[1], sync or env[4].extensions['wedof_sync_item'],
                    lambda conn: bool(wc.get_key(env[4], conn)), now=clock[0])


def finish(daily, limit=10):
    for _ in range(limit):
        delay = step(daily)
        if delay > 3600:
            return
        daily[1][0] += timedelta(seconds=delay)
    raise AssertionError('Daily batch did not finish in bounded steps')


def test_no_read_before_8_and_one_batch_despite_restarts_and_page_visits(daily):
    env, clock = daily
    assert step(daily) == 60
    env[3].assert_not_called()
    clock[0] += timedelta(minutes=1)
    finish(daily)
    assert env[3].call_count == 5
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0] == 1
        assert conn.execute('SELECT status FROM student_wedof_daily_runs').fetchone()[0] == 'completed'
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_daily_items').fetchone()[0] == 1
    for _ in range(3):
        initialize(env[1], clock[0])
        step(daily)
        env[0].get('/admin/candidat/alice/contrats-apprentissage')
        # Older open tabs cannot trigger automatic reads with their old script.
        response = env[0].post('/admin/candidat/alice/contrats-apprentissage/detecter', json={}, headers=env[2])
        assert response.status_code == 200 and not response.json['pending']
    assert env[3].call_count == 5


def test_next_morning_refreshes_existing_contract_and_its_schedules_once(daily):
    env, clock = daily
    clock[0] += timedelta(minutes=1)
    finish(daily)
    env[3].reset_mock()
    clock[0] = next_morning(clock[0])
    finish(daily)
    assert env[3].call_count == 3
    assert not any(c.args[0].endswith('/registrationFolders') for c in env[3].call_args_list)
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_daily_runs').fetchone()[0] == 2
        item = json.loads(conn.execute('SELECT payload FROM student_wedof_contracts').fetchone()[0])
        assert len(item['schedules']) == 2
    step(daily)
    assert env[3].call_count == 3


def test_8am_refresh_is_not_skipped_by_an_earlier_manual_cache(daily):
    env, clock = daily
    assert discover(env)['linked']
    env[3].reset_mock()
    clock[0] += timedelta(minutes=1)
    finish(daily)
    assert env[3].call_count == 3


def test_voluntary_unlink_remains_suppressed_in_daily_batch(daily):
    env, clock = daily
    assert discover(env)['linked']
    assert post(env, '/101/detacher').status_code == 200
    env[3].reset_mock()
    clock[0] += timedelta(minutes=1)
    finish(daily)
    env[3].assert_not_called()
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0] == 0


def test_manual_refresh_just_before_8_pauses_without_cancelling_the_daily_batch(daily):
    env, clock = daily
    assert discover(env)['linked']
    clock[0] = next_morning(clock[0]) + timedelta(days=1, seconds=-10)
    assert post(env, '/101/actualiser').status_code == 200
    env[3].reset_mock()
    clock[0] += timedelta(seconds=10)
    assert step(daily) == 50
    env[3].assert_not_called()
    clock[0] += timedelta(seconds=50)
    finish(daily)
    assert env[3].call_count == 3


@pytest.mark.parametrize('date,utc_hour', [
    ('2026-01-15', 7), ('2026-07-15', 6), ('2026-03-29', 6), ('2026-10-25', 7),
])
def test_8am_is_paris_time_in_winter_summer_and_dst_changes(date, utc_hour):
    local = datetime.fromisoformat(date+'T07:59:00').replace(tzinfo=PARIS)
    due = next_morning(local)
    assert due.hour == 8 and due.minute == 0
    assert due.astimezone(timezone.utc).hour == utc_hour
    following = next_morning(due)
    assert following.date() == due.date()+timedelta(days=1) and following.hour == 8


def test_late_first_install_waits_until_next_8am_and_clock_survives_restart(daily):
    env, clock = daily
    with env[1]() as conn:
        conn.execute('DELETE FROM student_wedof_daily_clock')
        conn.commit()
    clock[0] = clock[0].replace(hour=14)
    initialize(env[1], clock[0])
    step(daily)
    env[3].assert_not_called()
    clock[0] = next_morning(clock[0])
    initialize(env[1], clock[0])
    finish(daily)
    assert env[3].call_count == 5


def test_missed_8am_is_caught_up_once_after_a_restart(daily):
    env, clock = daily
    clock[0] = clock[0].replace(hour=9)
    initialize(env[1], clock[0])
    finish(daily)
    assert env[3].call_count == 5
    initialize(env[1], clock[0])
    step(daily)
    assert env[3].call_count == 5


def test_shared_lease_prevents_two_workers_from_reading_same_phase(daily):
    env, clock = daily
    clock[0] += timedelta(minutes=1)
    sync = env[4].extensions['wedof_sync_item']
    called = []
    def concurrent(cid, key, since):
        called.append(cid)
        assert step(daily, lambda *a: pytest.fail('Second worker acquired the live lease')) == 120
        return sync(cid, key, since)
    step(daily, concurrent)
    assert called == ['alice'] and env[3].call_count == 1
    clock[0] += timedelta(seconds=2)
    finish(daily)
    assert env[3].call_count == 5


def test_provider_pause_resumes_same_batch_without_restarting_successful_phases(daily):
    env, clock = daily
    clock[0] += timedelta(minutes=1)
    reply = env[3].side_effect
    def exhausted(url, **kwargs):
        response = reply(url, **kwargs)
        response.headers = {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '20'}
        return response
    env[3].side_effect = exhausted
    step(daily)
    env[3].side_effect = reply
    clock[0] += timedelta(seconds=1)
    assert step(daily) == 19
    assert env[3].call_count == 1
    clock[0] += timedelta(seconds=20)
    finish(daily)
    assert env[3].call_count == 5
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_daily_runs').fetchone()[0] == 1


def test_outage_stops_the_day_and_retains_contract_before_next_morning(daily):
    env, clock = daily
    clock[0] += timedelta(minutes=1)
    finish(daily)
    clock[0] = next_morning(clock[0])
    reply = env[3].side_effect
    env[3].side_effect = requests.Timeout()
    env[3].reset_mock()
    step(daily)
    assert env[3].call_count == 1
    for _ in range(3):
        clock[0] += timedelta(minutes=5)
        step(daily)
    assert env[3].call_count == 1
    with env[1]() as conn:
        item = json.loads(conn.execute('SELECT payload FROM student_wedof_contracts').fetchone()[0])
        assert len(item['schedules']) == 2 and item['raw_stale']
    clock[0] = next_morning(clock[0])
    env[3].side_effect = reply
    finish(daily)
    assert env[3].call_count == 4


def test_no_contract_result_remains_visible_between_daily_runs(daily):
    env, clock = daily
    env[3].side_effect = lambda *a, **kw: Mock(status_code=200, headers={}, content=b'[]', json=lambda: [])
    clock[0] += timedelta(minutes=1)
    finish(daily)
    assert env[3].call_count == 2
    clock[0] += timedelta(hours=12)
    assert directory_state(env)['contract'] == 'no'
    step(daily)
    assert env[3].call_count == 2


def test_expired_lease_resumes_and_completed_items_are_not_repeated(daily):
    env, clock = daily
    clock[0] += timedelta(minutes=1)
    step(daily)
    with env[1]() as conn:
        conn.execute('UPDATE student_wedof_daily_runs SET owner=?,lease_until=?', ('crashed', clock[0].timestamp()+120))
    assert step(daily) == 120
    assert env[3].call_count == 1
    clock[0] += timedelta(seconds=121)
    finish(daily)
    assert env[3].call_count == 5
