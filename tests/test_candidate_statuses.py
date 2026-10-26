"""Employment presentation uses real links, dates and current contract states."""
from datetime import date
import json
import sqlite3

import pytest
from candidate_statuses import annotate_candidate_statuses
from test_admissions_2027 import application, auth, client, seed
from wedof_contracts import ensure_schema as ensure_wedof, billing

TODAY = date(2026, 10, 26)


@pytest.fixture
def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE student_wedof_contracts(candidate_id TEXT,payload TEXT)')
    conn.execute('CREATE TABLE companies(id TEXT PRIMARY KEY,active INTEGER)')
    conn.execute('CREATE TABLE company_students(candidate_id TEXT,company_id TEXT,start_date TEXT,end_date TEXT)')
    yield conn
    conn.close()


def add_contract(conn, cid='student', **changes):
    item = dict(state='accepted', employer_name='Entreprise Exemple', contract_start='2026-09-01', contract_end='2028-08-31')
    item.update(changes)
    conn.execute('INSERT INTO student_wedof_contracts VALUES(?,?)', (cid, json.dumps(item)))


def test_active_contract_changes_only_display_status(db):
    row = dict(id='student', statut='confirmee')
    add_contract(db)
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == 'en_entreprise' and row['display_status_label'] == 'En entreprise'
    assert row['statut'] == 'confirmee'
    db.execute('DELETE FROM student_wedof_contracts')
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == 'confirmee' and row['display_status_label'] == ''


@pytest.mark.parametrize('changes', [dict(state='draft'), dict(state='broken'), dict(state='cancelled'),
    dict(state='completed'), dict(contract_start='2026-12-01'), dict(contract_end='2026-10-25'),
    dict(contract_start=''), dict(contract_start='invalid'), dict(contract_break_date='2026-10-26'),
    dict(employer_name='',employer_siret='')])
def test_unconfirmed_ended_future_and_invalid_contracts_do_not_claim_employment(db, changes):
    row = dict(id='student', statut='confirmee')
    add_contract(db, **changes)
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == 'confirmee'


@pytest.mark.parametrize('status', ['annulee', 'docs_non_conformes', 'preinscription'])
def test_admission_alerts_and_unreviewed_applications_keep_their_status(db, status):
    add_contract(db)
    row = dict(id='student', statut=status)
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == status


def test_real_company_assignment_works_without_wedof_or_portal_access(db):
    db.execute("INSERT INTO companies VALUES('company',0)")
    db.execute("INSERT INTO company_students VALUES('student','company','2026-10-01','2026-10-26')")
    row = dict(id='student', statut='reconfirmee')
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == 'en_entreprise'
    annotate_candidate_statuses(db, [row], date(2026,10,27))
    assert row['display_status'] == 'reconfirmee'


def test_self_declaration_and_invalid_payloads_are_not_company_assignments(db):
    db.execute("INSERT INTO student_wedof_contracts VALUES('student','invalid-json')")
    row = dict(id='student', statut='confirmee', entreprise_trouvee='oui')
    annotate_candidate_statuses(db, [row], TODAY)
    assert row['display_status'] == 'confirmee'


def test_directory_kpi_and_api_use_display_status_while_campaign_keeps_admission(client, monkeypatch):
    import candidate_statuses
    original = candidate_statuses.annotate_candidate_statuses
    monkeypatch.setattr(application, 'annotate_candidate_statuses', lambda conn, rows: original(conn, rows, TODAY))
    seed(2026,'employed'); seed(2026,'confirmed'); auth(client)
    with application.db() as conn:
        ensure_wedof(conn)
        payload = dict(state='accepted',employer_name='Entreprise Exemple',contract_start='2026-09-01',contract_end='2028-08-31')
        conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)', ('101','employed',json.dumps(payload),0,'now'))
        conn.commit()
    employed = client.get('/admin?rentree=2026&statut=en_entreprise')
    assert employed.status_code == 200
    assert 'data-id="employed"' in employed.text and 'data-id="confirmed"' not in employed.text
    confirmed = client.get('/admin?rentree=2026&statut=confirmee')
    assert 'data-id="confirmed"' in confirmed.text and 'data-id="employed"' not in confirmed.text
    counts = client.get('/api/kpi?rentree=2026').json
    assert counts['en_entreprise'] == 1 and counts['confirmee'] == 1
    row = client.get('/admin/row/employed').json['row']
    assert row['display_status'] == 'en_entreprise' and row['statut'] == 'confirmee'
    with application.app.test_request_context('/?rentree=2026'):
        assert {r['id'] for r in application.campaign_rows('confirmee')} == {'employed','confirmed'}
    with application.db() as conn:
        assert conn.execute("SELECT statut FROM candidats WHERE id='employed'").fetchone()[0] == 'confirmee'


def test_schedule_states_and_progress_do_not_turn_missing_data_into_paid(db):
    source = {'schedules':[
        dict(montantTotal=100,montantRegle=100,montantEnCoursInstruction=0,dateOuverture='2020-01-01'),
        dict(montantTotal=100,montantRegle=0,montantEnCoursInstruction=0,dateOuverture='2090-01-01'),
        dict(montantTotal=100,montantRegle=0,montantEnCoursInstruction=0,dateOuverture='2020-01-01'),
        dict(montantTotal=100,montantRegle=0,montantEnCoursInstruction=20,dateOuverture='2020-01-01')]}
    result = billing(source)
    assert [r['status_code'] for r in result['schedules']] == ['paid','upcoming','open','pending']
    assert result['paid_percent'] == 25 and result['counts']['paid'] == 1
    assert result['next_due']['status_code'] == 'open'
    source['schedules'][1]['montantRegle'] = None
    assert billing(source)['paid_percent'] is None
    source['raw_stale'] = True
    result = billing(source)
    assert result['paid_percent'] is None and result['next_due'] is None
    assert all(r['status_code']=='stale' for r in result['schedules'])
