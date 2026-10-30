"""Placement counts use enrolled students and distinguish absence from unknown."""
from datetime import date
import hashlib
import json

import pytest

from promotion_metrics import annotate_promotion_metrics
from promotions import assign_candidate_promotion, list_promotions
from test_promotions import db, web, group, student
from wedof_contracts import discovery_fingerprint, ensure_schema

TODAY = date(2026, 10, 30)


@pytest.fixture
def metrics_db(db, monkeypatch):
    monkeypatch.delenv('WEDOF_API_KEY', raising=False)
    monkeypatch.setattr('wedof_contracts.requests.get', lambda *a, **k: pytest.fail('Promotions must never call WEDOF'))
    with db() as conn:
        conn.execute('ALTER TABLE candidats ADD COLUMN entreprise_trouvee TEXT')
        conn.execute('ALTER TABLE candidats ADD COLUMN date_naissance TEXT')
        conn.execute('CREATE TABLE companies(id TEXT PRIMARY KEY,active INTEGER)')
        conn.execute('CREATE TABLE company_students(candidate_id TEXT,company_id TEXT,start_date TEXT,end_date TEXT)')
        ensure_schema(conn)
        group(conn)
        group(conn, 'other')
        group(conn, 'empty', active=0)
    return db


def member(conn, cid, declared=None, status='confirmee', pid='group-one'):
    student(conn, cid, status=status)
    conn.execute('UPDATE candidats SET entreprise_trouvee=? WHERE id=?', (declared, cid))
    if pid:
        assign_candidate_promotion(conn, cid, pid)


def contract(conn, cid, **changes):
    item = dict(state='accepted', employer_name='Entreprise exemple',
                contract_start='2026-09-01', contract_end='2028-08-31')
    item.update(changes)
    index = conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0]
    conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)',
                 (str(index + 1), cid, json.dumps(item), 1, 'now'))


def metrics(conn, app):
    groups = list_promotions(conn)
    annotate_promotion_metrics(app, conn, groups, TODAY)
    return {p['id']: p['placement'] for p in groups}


def test_counts_deduplicate_contracts_and_exclude_non_enrolled_or_other_groups(metrics_db, web):
    with metrics_db() as conn:
        member(conn, 'declared', ' OUI ')
        contract(conn, 'declared')
        contract(conn, 'declared', state='broken')
        member(conn, 'searching', 'non')
        member(conn, 'not-found')
        row = dict(conn.execute("SELECT * FROM candidats WHERE id='not-found'").fetchone())
        fingerprint = discovery_fingerprint(row, hashlib.sha256(b'').hexdigest())
        conn.execute('INSERT INTO student_wedof_discovery VALUES(?,?,?,?)',
                     ('not-found', fingerprint, json.dumps(dict(step='done', not_found=True, items=[], incomplete=False)), 1))
        member(conn, 'future-company')
        conn.execute("INSERT INTO companies VALUES('company',0)")
        conn.execute("INSERT INTO company_students VALUES('future-company','company','2026-11-01','2028-08-31')")
        member(conn, 'draft', 'non')
        contract(conn, 'draft', state='draft')
        member(conn, 'invalid')
        contract(conn, 'invalid')
        conn.execute("UPDATE student_wedof_contracts SET payload='not-json' WHERE candidate_id='invalid'")
        member(conn, 'expired', status='reconfirmee')
        contract(conn, 'expired', contract_end='2026-10-29')
        member(conn, 'cancelled', 'oui', status='annulee')
        contract(conn, 'cancelled')
        member(conn, 'applicant', 'oui', status='validee')
        member(conn, 'unassigned', 'oui', pid=None)
        member(conn, 'another', 'oui', pid='other')
        result = metrics(conn, web[1])
        first = result['group-one']
        assert first['total'] == 7
        expected = dict(company_found=2, company_searching=2, company_unknown=3,
                        contract_linked=3, contract_missing=1, contract_unknown=3)
        assert {key: first[key]['count'] for key in expected} == expected
        assert first['company_found']['percent'] == 28.6
        assert first['contract_missing']['percent'] == 14.3
        assert result['other']['total'] == 1 and result['other']['company_found']['percent'] == 100
        assert result['empty']['total'] == 0 and result['empty']['contract_linked']['percent'] is None


@pytest.mark.parametrize('changes,found', [
    ({}, 1), ({'state': 'pendingAcceptation'}, 1), ({'state': 'sent'}, 1),
    ({'contract_start': '2026-12-01'}, 1), ({'contract_end': '2026-10-30'}, 1),
    ({'state': 'broken'}, 0), ({'state': 'cancelled'}, 0), ({'state': 'refused'}, 0),
    ({'state': 'completed'}, 0), ({'state': 'draft'}, 0),
    ({'employer_name': '', 'employer_siret': ''}, 0),
    ({'contract_end': '2026-10-29'}, 0), ({'contract_end': 'invalid'}, 0),
    ({'contract_break_date': '2026-10-30'}, 0), ({'contract_break_date': '2026-10-29'}, 0),
])
def test_historical_contracts_are_attached_but_do_not_claim_a_current_company(metrics_db, web, changes, found):
    with metrics_db() as conn:
        member(conn, 'one')
        contract(conn, 'one', **changes)
        result = metrics(conn, web[1])['group-one']
        assert result['company_found']['count'] == found
        assert result['company_unknown']['count'] == 1 - found
        assert result['contract_linked']['count'] == 1


def test_company_assignment_overrides_old_no_and_refreshes_after_transfer(metrics_db, web):
    with metrics_db() as conn:
        member(conn, 'one', 'non')
        member(conn, 'two')
        conn.execute("INSERT INTO companies VALUES('company',1)")
        conn.execute("INSERT INTO company_students VALUES('one','company','2026-09-01','2028-08-31')")
        conn.execute("INSERT INTO company_students VALUES('two','company','2025-09-01','2026-10-29')")
        result = metrics(conn, web[1])['group-one']
        assert result['company_found']['count'] == 1
        assert result['company_searching']['count'] == 0
        assert result['company_unknown']['count'] == 1
        assign_candidate_promotion(conn, 'one', 'other')
        result = metrics(conn, web[1])
        assert result['group-one']['total'] == 1 and result['group-one']['company_found']['count'] == 0
        assert result['other']['company_found']['percent'] == 100


def test_page_is_admin_only_shows_denominator_and_real_contract_filter_links(metrics_db, web):
    with metrics_db() as conn:
        for cid in ('one', 'two', 'three'):
            member(conn, cid)
        contract(conn, 'one')
        member(conn, 'cancelled', 'oui', status='annulee')
    client, app, contexts = web
    response = client.get('/admin/promotions')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert '3 inscriptions confirmées · base des pourcentages' in response.text
    assert '33,3 %' in response.text and '66,7 %' in response.text
    assert 'Aucune inscription confirmée pour le moment' in response.text
    assert 'promotion=group-one&amp;contract=yes' in response.text
    assert 'promotion=group-one&amp;contract=no' in response.text
    assert 'promotion=group-one&amp;contract=linked' in response.text
    assert next(p for p in contexts[-1]['promotions'] if p['id'] == 'group-one')['placement']['total'] == 3
    assert app.test_client().get('/admin/promotions').status_code == 403


def test_legacy_schema_without_wedof_or_company_fields_remains_unknown(db, web):
    with db() as conn:
        group(conn)
        student(conn)
        assign_candidate_promotion(conn, 'student', 'group-one')
        result = metrics(conn, web[1])['group-one']
        assert result['company_unknown'] == dict(count=1, percent=100)
        assert result['contract_unknown'] == dict(count=1, percent=100)
        assert result['contract_missing']['count'] == 0
