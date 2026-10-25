"""Monthly workload always reflects saved lessons; rates never reach the portal."""
from datetime import date
from pathlib import Path
import sqlite3

import pytest
from flask import Flask, session

import trainer_access
from trainer_workload import (WorkloadError, ensure_workload_schema, get_trainer_workload,
                              save_hourly_rate)


@pytest.fixture
def workload_db(tmp_path):
    path = tmp_path / 'workload.sqlite'
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    with connect() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,bts TEXT,rentree_annee INTEGER,statut TEXT)')
        trainer_access._schema(conn)
        ensure_workload_schema(conn)
        for tid in ('t1', 't2'):
            conn.execute('INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (tid, 'NOM '+tid, 'Camille', tid+'@example.test', 'now', 'now'))
        for pid, bts in [('p1', 'MCO'), ('p2', 'MCO'), ('p3', 'MOS')]:
            conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (pid, 'Promotion '+pid, bts, 1, 2026, '2027-01-01', '2027-12-31', 'now', 'now'))
            conn.execute('INSERT INTO trainer_promotions VALUES(?,?)', ('t1', pid))
            conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)', ('s'+pid, pid, 'Matière '+pid, 't1', '#555555', 100))
        conn.commit()
    return connect


def lesson(conn, cid='c1', day='2027-01-04', start=480, end=600, trainer='t1', groups=('p1',)):
    conn.execute('INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,date,start_min,end_min,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (cid, groups[0], 's'+groups[0], trainer, day, start, end, 'Cours '+cid, 'now', 'now'))
    conn.executemany('INSERT INTO planning_course_groups VALUES(?,?,?)', [(cid, pid, 's'+pid) for pid in groups])


def snapshot(db, month='2027-01', tid='t1'):
    with db() as conn:
        return get_trainer_workload(conn, tid, month, date(2027, 1, 15))


def rate(db, amount='45', day='2027-01-01', revision=0, tid='t1'):
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        return save_hourly_rate(conn, tid, day, amount, revision)


def test_shared_sessions_once_total_once_per_bts(workload_db):
    with workload_db() as conn:
        lesson(conn, groups=('p1', 'p2', 'p3'))
        lesson(conn, 'other', trainer='t2')
    rate(workload_db)
    data = snapshot(workload_db)
    assert data['total_minutes'] == data['shared_minutes'] == 120
    assert data['course_count'] == 1
    assert data['estimated_cents'] == 9000
    assert sum(row['minutes'] for row in data['by_promotion']) == 360
    assert {row['name']: row['minutes'] for row in data['by_bts']} == {'MCO': 120, 'MOS': 120}


def test_all_session_changes_recalculate_without_cache(workload_db):
    with workload_db() as conn:
        lesson(conn)
    rate(workload_db)
    assert snapshot(workload_db)['estimated_cents'] == 9000
    with workload_db() as conn:
        conn.execute("UPDATE planning_courses SET end_min=540 WHERE id='c1'")
    assert snapshot(workload_db)['total_minutes'] == 60
    assert snapshot(workload_db)['estimated_cents'] == 4500
    with workload_db() as conn:
        conn.execute("UPDATE planning_courses SET date='2027-02-01' WHERE id='c1'")
    assert snapshot(workload_db)['total_minutes'] == 0
    assert snapshot(workload_db, '2027-02')['total_minutes'] == 60
    with workload_db() as conn:
        conn.execute("DELETE FROM planning_courses WHERE id='c1'")
    assert snapshot(workload_db, '2027-02')['total_minutes'] == 0


def test_missing_rates_are_explicit_not_silently_zero(workload_db):
    with workload_db() as conn:
        lesson(conn)
        lesson(conn, 'later', day='2027-01-18', end=570)
    rate(workload_db, day='2027-01-10')
    data = snapshot(workload_db)
    assert data['all_priced'] is False and data['unpriced_minutes'] == 120
    assert data['estimated_cents'] == 6750
    assert data['courses'][0]['amount_cents'] is None
    assert data['elapsed_minutes'] == 120 and data['future_minutes'] == 90


def test_effective_rates_preserve_previous_period_and_daily_boundary(workload_db):
    with workload_db() as conn:
        lesson(conn)
        lesson(conn, 'later', day='2027-01-18')
        lesson(conn, 'feb', day='2027-02-01')
    rate(workload_db, amount='40')
    rate(workload_db, amount='50', day='2027-01-18', revision=1)
    rate(workload_db, amount='60', day='2027-02-01', revision=2)
    assert snapshot(workload_db)['estimated_cents'] == 18000
    assert snapshot(workload_db, '2027-02')['estimated_cents'] == 12000
    assert snapshot(workload_db)['current_rate_cents'] == 4000


def test_round_total_after_summing_exact_minutes(workload_db):
    with workload_db() as conn:
        for i in range(3):
            lesson(conn, f'c{i}', start=480+i, end=481+i)
    rate(workload_db, amount='1,00')
    data = snapshot(workload_db)
    assert data['estimated_cents'] == 5
    assert [row['amount_cents'] for row in data['courses']] == [2, 2, 2]
    assert data['total_label'] == '0 h 03'


def test_rate_change_same_effective_date_replaces_without_duplicate(workload_db):
    rate(workload_db, amount='0')
    rate(workload_db, amount='55.20', revision=1)
    data = snapshot(workload_db)
    assert len(data['rates']) == 1 and data['current_rate_cents'] == 5520
    assert data['rate_revision'] == 2


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '1.001', '10001', '1e2', True, 45, '', '1 000'])
def test_invalid_rate_inputs_rejected(workload_db, amount):
    with pytest.raises(WorkloadError):
        rate(workload_db, amount=amount)
    assert snapshot(workload_db)['rates'] == []


@pytest.mark.parametrize('month', ['2027-13', '2027-00', '2027-1', '0001-01', '2201-01', ['2027-01'], 'junk'])
def test_invalid_month_rejected(workload_db, month):
    with pytest.raises(WorkloadError):
        snapshot(workload_db, month)


def test_rate_revision_prevents_silent_concurrent_overwrite(workload_db):
    rate(workload_db)
    with pytest.raises(WorkloadError) as error:
        rate(workload_db, amount='50', revision=0)
    assert error.value.status == 409
    assert snapshot(workload_db)['current_rate_cents'] == 4500


def test_same_bts_groups_missing_primary_mapping_still_count_once(workload_db):
    with workload_db() as conn:
        lesson(conn, groups=('p1', 'p2'))
        conn.execute("DELETE FROM planning_course_groups WHERE promotion_id='p1'")
    data = snapshot(workload_db)
    assert data['total_minutes'] == 120
    assert len(data['by_promotion']) == 2 and len(data['by_bts']) == 1


@pytest.fixture
def workload_client(workload_db):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root/'templates'), static_folder=str(root/'static'))
    app.secret_key = 'test-workload-only'
    app.config['TESTING'] = True
    app.jinja_env.filters['dmy'] = lambda value: value
    trainer_access.register_trainer_access(app, workload_db, lambda *args: False, lambda: bool(session.get('admin_ok')))
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin_ok'] = True
        state['_trainer_csrf'] = 'test-token'
    return client


def test_fiche_real_template_has_hours_rates_and_existing_account_actions(workload_client, workload_db):
    with workload_db() as conn:
        lesson(conn)
    response = workload_client.get('/admin/formateurs/t1?month=2027-01')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'Volume mensuel total' in text and 'Montant partiellement chiffré' in text
    assert 'Compte &amp; indisponibilités' in text
    assert '/admin/formateurs?edit=t1' in text
    assert 'ne s’additionnent pas' in text
    assert 'ne constituent pas une validation de présence' in text
    assert 'no-store' in response.headers['Cache-Control']


def test_admin_only_and_csrf_rates(workload_client):
    stranger = workload_client.application.test_client()
    assert stranger.get('/admin/formateurs/t1').status_code == 403
    payload = dict(hourly_rate='50', effective_date='2027-01-01', expected_revision=0, csrf_token='test-token')
    assert stranger.post('/admin/formateurs/t1/tarif', json=payload).status_code == 403
    assert workload_client.post('/admin/formateurs/t1/tarif', json={k:v for k,v in payload.items() if k!='csrf_token'}).status_code == 400
    response = workload_client.post('/admin/formateurs/t1/tarif', json=payload)
    assert response.status_code == 200 and response.json['ok']
    assert 'no-store' in response.headers['Cache-Control']
    assert workload_client.post('/admin/formateurs/t1/tarif', json=payload).status_code == 409


def test_fiche_unknown_and_bad_month(workload_client):
    assert workload_client.get('/admin/formateurs/missing').status_code == 404
    assert workload_client.get('/admin/formateurs/t1?month=2027-02&month=2027-03').status_code == 400
    assert workload_client.get('/admin/formateurs/t1?month=invalid').status_code == 400


def test_fiche_escapes_untrusted_subject_and_names(workload_client, workload_db):
    with workload_db() as conn:
        lesson(conn)
        conn.execute('UPDATE planning_courses SET title=?', ('<script>alert(1)</script>',))
    response = workload_client.get('/admin/formateurs/t1?month=2027-01')
    assert b'<script>alert(1)</script>' not in response.data
    assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in response.data
