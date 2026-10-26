"""WEDOF reads use synthetic payloads. Never call a real OPCO or send messages."""
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import Mock

from flask import Flask, session
import pytest
import requests

import wedof_contracts as wc
from wedof_contract_data import FINANCERS, WedofError, normalize_summary, raw_fields


def contract(key=101, **changes):
    return {'id': key, 'financer': 'opcoCfaAkto', 'state': 'accepted', 'amount': 12000,
        'externalIdTrainingOrganism': f'AK-{key}', 'externalIdDeca': f'DECA-{key}',
        'startDate': '2026-09-01', 'endDate': '2028-08-31',
        '_links': {'registrationFolder': {'externalId': f'OPCO-{key}', 'href': 'https://evil.invalid'},
                   'employer': {'name': 'Entreprise Exemple', 'siret': '12345678901234'}}, **changes}


def folder(key=101, **changes):
    return {'externalId': f'OPCO-{key}', 'type': 'opcoCfa',
        'attendee': {'firstName': 'Camille', 'lastName': 'Exemple', 'dateOfBirth': '2006-03-04', 'email': 'camille@example.test', 'nir': 'SECRET-NIR'},
        'trainingActionInfo': {'title': 'BTS MOS', 'sessionStartDate': '2026-09-01', 'sessionEndDate': '2028-08-31', 'hoursInCenter': 1350}, **changes}


def raw(key=101):
    return {'cerfa': {'numeroInterne': f'AK-{key}',
        'apprenti': {'prenom': 'Camille', 'nom': 'Exemple', 'nir': 'SECRET-NIR'},
        'contrat': {'noContrat': f'DECA-{key}', 'salaireEmbauche': 1081.23},
        'employeur': {'denomination': 'Entreprise Exemple'},
        'maitre1': {'prenom': 'Alex', 'nom': 'Tutor', 'courriel': 'alex@example.test'},
        'formation': {'dureeFormation': 1350, 'nombreHeuresEnDistanciel': 0}},
        'echeances': [{'numero': 1, 'montantTotal': 6000, 'montantRegle': 3000, 'montantEnCoursInstruction': 0, 'dateOuverture': '2026-09-01'},
                     {'numero': 2, 'montantTotal': 6000, 'montantRegle': 0, 'montantEnCoursInstruction': 1000, 'dateOuverture': '2027-03-01'}],
        'engagementsFraisAnnexe': [{'natureFrais': 'Premierequipement', 'quantite': 1, 'prixUnitaire': 500, 'montantTotal': 500}],
        'iban': 'SECRET-IBAN'}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv('WEDOF_API_KEY', raising=False)
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.secret_key = 'test-secret-key-with-enough-entropy-for-tests'
    app.config['TESTING'] = True
    def db():
        conn = sqlite3.connect(tmp_path / 'test.db')
        conn.row_factory = sqlite3.Row
        return conn
    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,date_naissance TEXT,email TEXT)')
        conn.executemany('INSERT INTO candidats VALUES(?,?,?,?,?)', [('alice','Exemple','Camille','2006-03-04','camille@example.test'),('bob','Autre','Louis','2005-06-01','bob@example.test')])
    wc.register_wedof_contracts(app, db, lambda: session.get('admin_ok'))
    @app.get('/init')
    def init():
        session['_wedof_csrf'] = 'test-csrf'
        return 'ok'
    client = app.test_client()
    client.get('/init')
    with client.session_transaction() as state:
        state['admin_ok'] = True
    headers = {'X-CSRF-Token': 'test-csrf'}
    assert client.put('/admin/api/wedof/settings', json={'api_key': 'secret-wedof-test-key'}, headers=headers).status_code == 200
    http = Mock()
    def reply(url, **kwargs):
        endpoint = url.removeprefix(wc.BASE_URL)
        if endpoint == '/workingContracts': data = [contract()]
        elif endpoint.startswith('/workingContracts/') and endpoint.endswith('/raw'): data = raw(int(endpoint.split('/')[2]))
        elif endpoint.startswith('/workingContracts/'): data = contract(int(endpoint.rsplit('/',1)[1]))
        elif endpoint.startswith('/registrationFolders/'): data = folder(int(endpoint.rsplit('-',1)[1]))
        else: raise AssertionError(endpoint)
        return Mock(status_code=200, json=Mock(return_value=data), headers={}, content=b'{}')
    http.side_effect = reply
    monkeypatch.setattr(wc.requests, 'get', http)
    return client, db, headers, http, app


def post(env, path, data=None, cid='alice'):
    client, _, headers, *_ = env
    return client.post(f'/admin/candidat/{cid}/contrats-apprentissage' + path, json=data or {}, headers=headers)


def inspect(env, key=101, cid='alice'):
    search = post(env, '/rechercher', {'kind':'wedof','reference':str(key)}, cid)
    assert search.status_code == 200, search.json
    result = post(env, '/apercu', {'token':search.json['token'],'contract_id':str(key)}, cid)
    assert result.status_code == 200, result.json
    return result.json


def link(env, key=101):
    preview = inspect(env, key)
    result = post(env, '/rattacher', {'token':preview['token']})
    assert result.status_code == 200, result.json
    return result


def stale(env):
    with env[1]() as conn:
        conn.execute('UPDATE student_wedof_contracts SET checked_at=0,last_attempt=0')


def test_settings_are_encrypted_never_disclosed_and_admin_csrf_protected(setup):
    client, db, headers, http, _ = setup
    data = client.get('/admin/api/wedof/settings')
    assert data.json['configured'] and 'secret-wedof' not in data.text
    with db() as conn:
        saved = conn.execute('SELECT value FROM student_wedof_settings').fetchone()[0]
        assert 'secret-wedof' not in saved
    assert client.put('/admin/api/wedof/settings',json={'api_key':'x'}).status_code == 400
    assert client.post('/admin/candidat/alice/contrats-apprentissage/rechercher',json={}).status_code == 400
    with client.session_transaction() as state: state['admin_ok'] = False
    assert client.get('/admin/api/wedof/settings').status_code == 403
    assert client.get('/admin/candidat/alice/contrats-apprentissage').status_code == 403
    assert post(setup,'/rattacher').status_code == 403
    http.assert_not_called()


def test_environment_key_cannot_be_removed_or_returned(setup, monkeypatch):
    monkeypatch.setenv('WEDOF_API_KEY','server-secret-key')
    client = setup[0]
    response = client.get('/admin/api/wedof/settings')
    assert response.json['managed_by_server'] and 'server-secret-key' not in response.text
    assert client.delete('/admin/api/wedof/settings',headers=setup[2]).status_code == 409


def test_preview_and_link_never_write_remote_or_expose_sensitive_fields(setup):
    preview = inspect(setup)
    assert preview['identity']['status'] == 'matched'
    assert 'Camille Exemple' in preview['html']
    setup[3].reset_mock()
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 200
    setup[3].assert_not_called()
    response = setup[0].get('/admin/candidat/alice/contrats-apprentissage')
    assert response.status_code == 200
    assert 'Alex Tutor' in response.json['html']
    assert 'Ouverte à facturation' in response.json['html']
    assert '9\u202f000,00' in response.json['html']
    assert 'SECRET-' not in response.text and 'evil.invalid' not in response.text
    assert response.headers['Cache-Control'] == 'private, no-store'
    with setup[1]() as conn:
        payload = conn.execute('SELECT payload FROM student_wedof_contracts').fetchone()[0]
        assert 'SECRET-' not in payload and 'href' not in payload


def test_mismatching_identity_blocks_link_even_with_confirmation(setup):
    preview = inspect(setup,cid='bob')
    assert preview['identity']['status'] == 'mismatch'
    assert post(setup,'/rattacher',{'token':preview['token'],'identity_confirmed':True},cid='bob').status_code == 409


def test_unknown_identity_requires_explicit_manual_verification(setup, monkeypatch):
    monkeypatch.setattr(wc.Client, 'details', lambda self, item: {**item,'raw_stale':True})
    preview = inspect(setup)
    assert preview['identity']['status'] == 'unverified'
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 409
    assert post(setup,'/rattacher',{'token':preview['token'],'identity_confirmed':True}).status_code == 200


def test_candidate_changed_after_preview_is_rechecked(setup):
    preview = inspect(setup)
    with setup[1]() as conn: conn.execute("UPDATE candidats SET date_naissance='2001-01-01' WHERE id='alice'")
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 409


def test_preview_bound_to_candidate_session_expiry_and_configuration(setup):
    preview = inspect(setup)
    assert post(setup,'/rattacher',{'token':preview['token']},cid='bob').status_code == 410
    with setup[0].session_transaction() as state: state['_wedof_csrf'] = 'other-session'
    response = setup[0].post('/admin/candidat/alice/contrats-apprentissage/rattacher',json={'token':preview['token']},headers={'X-CSRF-Token':'other-session'})
    assert response.status_code == 410
    with setup[0].session_transaction() as state: state['_wedof_csrf'] = 'test-csrf'
    with setup[1]() as conn: conn.execute('UPDATE student_wedof_previews SET created_at=0')
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 410


def test_duplicate_previews_and_parallel_links_cannot_duplicate_a_contract(setup):
    preview = inspect(setup)
    calls = setup[3].call_count
    repeated = inspect(setup)
    assert repeated['token'] == preview['token'] and setup[3].call_count == calls
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 200
    assert post(setup,'/rattacher',{'token':preview['token']}).status_code == 410
    with setup[1]() as conn: assert conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0] == 1


def test_multiple_contracts_and_unlink_are_local_only(setup):
    link(setup); link(setup,102)
    setup[3].reset_mock()
    assert post(setup,'/101/detacher').status_code == 200
    with setup[1]() as conn:
        rows = conn.execute('SELECT contract_id FROM student_wedof_contracts').fetchall()
        assert [r[0] for r in rows] == ['102']
    setup[3].assert_not_called()


def test_number_search_is_explicit_exact_and_one_page_at_a_time(setup, monkeypatch):
    page = Mock(return_value=([normalize_summary(contract()),normalize_summary(contract(102))],True))
    monkeypatch.setattr(wc.Client,'page',page)
    result = post(setup,'/rechercher',{'kind':'number','reference':' AK-101 ','financer':'opcoCfaAkto'})
    assert [r['working_contract_id'] for r in result.json['items']] == ['101']
    assert page.call_count == 1 and result.json['next_token']
    again = post(setup,'/rechercher',{'kind':'number','reference':' AK-101 ','financer':'opcoCfaAkto'})
    assert again.json['cached'] and page.call_count == 1
    assert post(setup,'/rechercher',{'next_token':result.json['next_token']}).status_code == 200
    assert page.call_count == 2 and page.call_args.kwargs['page'] == 2
    with setup[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0] == 0
        assert 'AK-102' not in ''.join(r[0] for r in conn.execute('SELECT payload FROM student_wedof_previews'))


def test_invalid_or_empty_queries_make_no_api_call(setup):
    for payload in ({'reference':''},{'kind':'all','reference':'101'},{'kind':'wedof','reference':'../organisms'}, {'kind':'folder','reference':'https://evil.invalid'}, {'kind':'number','reference':'AK-101'}):
        assert post(setup,'/rechercher',payload).status_code == 400
    setup[3].assert_not_called()


def test_foreign_result_cannot_be_selected(setup):
    data = post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).json
    setup[3].reset_mock()
    assert post(setup,'/apercu',{'token':data['token'],'contract_id':'102'}).status_code == 403
    setup[3].assert_not_called()


def test_refresh_within_30_minutes_reads_only_cache(setup):
    link(setup); setup[3].reset_mock()
    assert post(setup,'/101/actualiser').json['cached']
    setup[0].get('/admin/candidat/alice/contrats-apprentissage')
    setup[3].assert_not_called()


def test_outage_retains_old_data_marks_stale_and_throttles_failures(setup):
    link(setup); stale(setup)
    setup[3].side_effect = requests.Timeout('secret provider message')
    response = post(setup,'/101/actualiser')
    assert response.status_code == 502 and 'secret provider message' not in response.text
    with setup[1]() as conn:
        row = conn.execute('SELECT * FROM student_wedof_contracts').fetchone()
        assert json.loads(row['payload'])['schedules'][0]['montantTotal'] == 6000
        assert json.loads(row['payload'])['raw_stale'] and row['error']
    assert 'À vérifier' in setup[0].get('/admin/candidat/alice/contrats-apprentissage').json['html']
    setup[3].reset_mock()
    assert post(setup,'/101/actualiser').json['cached']
    setup[3].assert_not_called()


def test_partial_refresh_does_not_remove_previous_schedules(setup, monkeypatch):
    link(setup); stale(setup)
    monkeypatch.setattr(wc.Client,'details',lambda self,item:{**item,'raw_stale':True,'raw_error':'Échéancier indisponible'})
    assert post(setup,'/101/actualiser').status_code == 200
    with setup[1]() as conn:
        item=json.loads(conn.execute('SELECT payload FROM student_wedof_contracts').fetchone()[0])
        assert item['schedules'] and item['raw_stale']


def test_changed_registration_or_student_cannot_overwrite_existing_contract(setup, monkeypatch):
    link(setup); stale(setup)
    monkeypatch.setattr(wc.Client,'contract',lambda self,key:{**normalize_summary(contract()),'registration_id':'OTHER'})
    assert post(setup,'/101/actualiser').status_code == 400
    with setup[1]() as conn: assert json.loads(conn.execute('SELECT payload FROM student_wedof_contracts').fetchone()[0])['registration_id'] == 'OPCO-101'


def test_quota_and_shared_lock_stop_calls_before_network(setup):
    with setup[1]() as conn:
        conn.execute('INSERT INTO student_wedof_lock VALUES(1,?,?)',('busy',time.time()+90))
    assert post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).status_code == 409
    setup[3].assert_not_called()
    with setup[1]() as conn:
        conn.execute('DELETE FROM student_wedof_lock')
        conn.executemany('INSERT INTO student_wedof_calls VALUES(?)',[(time.time(),)]*100)
    assert post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).status_code == 429
    setup[3].assert_not_called()


def test_http_read_uses_fixed_host_no_redirect_and_no_retry(setup):
    setup[3].side_effect = None
    setup[3].return_value = Mock(status_code=429,content=b'{"token":"secret"}',headers={})
    response=post(setup,'/rechercher',{'kind':'wedof','reference':'101'})
    assert response.status_code == 502 and setup[3].call_count == 1
    args=setup[3].call_args
    assert args.args[0] == 'https://www.wedof.fr/api/workingContracts/101'
    assert args.kwargs['allow_redirects'] is False and args.kwargs['timeout'] == (3,5)
    assert 'secret' not in response.text


def test_financial_unknowns_zero_and_cent_rounding():
    data=raw_fields(raw(),normalize_summary(contract()))
    result=wc.billing(data)
    assert result['total']==12000 and result['paid']==3000 and result['remaining']==9000
    assert data['remote_hours'] == 0 and 'SECRET' not in json.dumps(data)
    data['schedules'][0].pop('montantRegle')
    assert wc.billing(data)['paid'] is None and wc.billing(data)['remaining'] is None
    assert wc.billing({'schedules':[]})['total'] is None
    assert wc.billing({'schedules':[{'montantTotal':0.1,'montantRegle':0},{'montantTotal':0.2,'montantRegle':0}]})['remaining']==0.3


def test_stored_untrusted_text_is_escaped_and_missing_values_are_visible(setup, monkeypatch):
    monkeypatch.setattr(wc.Client,'details',lambda self,item:{**item,'employer_name':'<script>alert(1)</script>', 'apprentice_first_name':'Camille','apprentice_last_name':'Exemple'})
    link(setup)
    html=setup[0].get('/admin/candidat/alice/contrats-apprentissage').json['html']
    assert '<script>' not in html and '&lt;script&gt;' in html and 'Non communiqué' in html


def test_raw_and_folder_must_describe_the_same_person(setup):
    original=setup[3].side_effect
    def changed(url,**kwargs):
        response=original(url,**kwargs)
        if url.endswith('/raw'):
            payload=raw();payload['cerfa']['apprenti']['nom']='Autre'
            response.json.return_value=payload
        return response
    setup[3].side_effect=changed
    search=post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).json
    assert post(setup,'/apercu',{'token':search['token'],'contract_id':'101'}).status_code == 400


def test_all_current_financers_are_accepted():
    assert len(FINANCERS)==11
    for financer in FINANCERS: assert normalize_summary(contract(financer=financer))['financer']==financer


def test_deleted_candidate_does_not_leave_contract_data_or_stale_links(setup):
    link(setup)
    with setup[1]() as conn:
        conn.execute("DELETE FROM candidats WHERE id='alice'")
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_contracts').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM student_wedof_previews').fetchone()[0] == 0


def test_missing_candidate_cannot_be_searched_or_read(setup):
    assert post(setup,'/rechercher',{'kind':'wedof','reference':'101'},cid='missing').status_code==404
    assert setup[0].get('/admin/candidat/missing/contrats-apprentissage').status_code==404
    setup[3].assert_not_called()


def test_changed_summary_invalidates_cached_search_for_immediate_retry(setup, monkeypatch):
    search=post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).json
    monkeypatch.setattr(wc.Client,'contract',lambda self,key:normalize_summary(contract(amount=14000)))
    assert post(setup,'/apercu',{'token':search['token'],'contract_id':'101'}).status_code==409
    refreshed=post(setup,'/rechercher',{'kind':'wedof','reference':'101'}).json
    assert refreshed['token']!=search['token']
    assert post(setup,'/apercu',{'token':refreshed['token'],'contract_id':'101'}).status_code==200


def test_unexpected_optional_state_is_not_a_server_error():
    assert normalize_summary(contract(state=[]))['state_label']=='État non communiqué'
