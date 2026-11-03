from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest
from flask import Flask, session

from akto_convergence import CLIENT_ID, CLIENT_SECRET, HOST, lookup_dossier, register_akto_convergence, verify_key
from akto_sync import register_akto, secret
from opco_convergence import Client, ReadError, ReadHttpError
from planning import register_planning


@pytest.fixture
def settings(tmp_path):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.secret_key = 'test-only-long-platform-key'
    app.testing = True

    def db():
        conn = sqlite3.connect(tmp_path / 'test.db')
        conn.row_factory = sqlite3.Row
        return conn

    def admin():
        return session.get('admin_ok', False)

    register_planning(app, db, admin)
    register_akto(app, db, admin, tmp_path)
    register_akto_convergence(app, db, admin)
    return app, db


def test_real_settings_route_and_encrypted_key(settings, monkeypatch):
    app, db = settings
    client = app.test_client()
    url = '/admin/parametres/akto/convergence'
    key = 'test-cfa-placeholder'
    checked = []

    def verify(value):
        checked.append(value)
        if value != key:
            raise ReadError('Lecture refusée.')

    monkeypatch.setattr('akto_convergence.verify_key', verify)
    assert client.post(url, data={'action': 'save', 'cfa_key': key}).status_code == 403
    with client.session_transaction() as state:
        state['admin_ok'] = True
    page = client.get('/admin/parametres')
    assert page.status_code == 200 and b'id="akto-cfa-key" name="cfa_key" type="password"' in page.data
    assert client.post(url, data={'action': 'save', 'cfa_key': key}).status_code == 403
    with client.session_transaction() as state:
        csrf = state['_planning_csrf']

    def submit(action, value=''):
        response = client.post(url, data={'csrf_token': csrf, 'action': action, 'cfa_key': value})
        assert response.status_code == 303 and response.location.endswith('/admin/parametres#akto-convergence')
        html = client.get('/admin/parametres').get_data(as_text=True)
        assert key not in html
        return html

    assert 'Aucune clé CFA enregistrée' in submit('save', 'two words')
    assert 'Dernière vérification réussie' in submit('save', key)
    with closing(db()) as conn:
        credential = conn.execute('SELECT credential FROM akto_recette_key').fetchone()[0]
        assert key.encode() not in credential and secret(app).decrypt(credential) == key.encode()
    assert 'Lecture refusée.' in submit('save', 'invalid')
    assert 'Dernière vérification réussie' in submit('test')
    assert checked == [key, 'invalid', key]
    assert 'Aucune clé CFA enregistrée' in submit('remove')
    assert 'Aucune clé CFA n’est enregistrée' in submit('test')
    with closing(db()) as conn:
        assert conn.execute('SELECT credential FROM akto_connection').fetchone()[0] is None


@pytest.mark.parametrize('page', [[], [{'numeroInterne': 'TEST'}], {'total': 0, 'etatDossierResult': []}])
def test_recette_reads_only_protected_endpoint(monkeypatch, page):
    monkeypatch.setenv(CLIENT_ID, 'test-client')
    monkeypatch.setenv(CLIENT_SECRET, 'test-software-secret')
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {'access_token': 'test-bearer'} if method == 'POST' else page

    monkeypatch.setattr(Client, 'json_request', request)
    verify_key('test-cfa-key')
    assert [(method, url) for method, url, _ in calls] == [
        ('POST', HOST + '/SorApiIdentityServer/connect/token'),
        ('GET', HOST + '/SorApiEchangeCFA/v2/dossiers/etats')]
    assert calls[0][2]['auth'] == ('test-client', 'test-software-secret')
    assert calls[0][2]['data'] == {'grant_type': 'client_credentials', 'scope': 'api.read api.write'}
    headers = calls[1][2]['headers']
    assert headers['Authorization'] == 'Bearer test-bearer' and headers['X-API-KEY'] == 'test-cfa-key'
    assert 'test-cfa-key' not in str(calls[1][2]['params']) and 'test-software-secret' not in str(calls[1])


def test_missing_software_access_and_unexpected_reply(monkeypatch):
    monkeypatch.delenv(CLIENT_SECRET, raising=False)
    with pytest.raises(ReadError, match='accès techniques'):
        verify_key('test')
    monkeypatch.setenv(CLIENT_SECRET, 'test-software-secret')
    monkeypatch.setenv(CLIENT_ID, 'test-client')
    monkeypatch.setattr(Client, 'json_request', lambda method, *a, **kw: {'access_token': 'test'} if method == 'POST' else {'unexpected': True})
    with pytest.raises(ReadError, match='réponse inattendue'):
        verify_key('test')


def test_lookup_from_settings_reads_one_dossier_without_import(settings, monkeypatch):
    app, db = settings
    client = app.test_client()
    fields = {'action': 'lookup', 'csrf_token': 'csrf', 'reference': 'TEST-REF', 'deca': '00042'}
    url = '/admin/parametres/akto/convergence'
    assert client.post(url, data=fields).status_code == 403
    with client.session_transaction() as state:
        state.update(admin_ok=True, _planning_csrf='csrf')
    assert client.post(url, data=dict(fields, csrf_token='wrong')).status_code == 403
    assert 'Aucune clé CFA' in client.post(url, data=fields, follow_redirects=True).get_data(as_text=True)
    monkeypatch.setenv(CLIENT_ID, 'test-software')
    monkeypatch.setenv(CLIENT_SECRET, 'test-software-secret')
    with closing(db()) as conn:
        credential = secret(app).encrypt(b'test-cfa')
        conn.execute('UPDATE akto_recette_key SET credential=?', (credential,))
        conn.commit()
    calls = []

    def api(method, path, **kwargs):
        calls.append((method, path))
        if method == 'POST':
            return {'access_token': 'test-bearer'}
        assert kwargs['params'] == {'numeroExterne': 'TEST-REF', 'numeroDeca': '00042'}
        assert kwargs['headers']['X-API-KEY'] == 'test-cfa'
        return {'cerfa': {'numeroExterne': 'TEST-REF', 'etat': 'ENGAGE', 'contrat': {'noContrat': '00042'},
                         'apprenti': {'nom': 'RAW-PRIVATE-TEST'}}, 'echeances': [{'numero': 1}, {'numero': 2}]}

    monkeypatch.setattr(Client, 'json_request', api)
    response = client.post(url, data=fields)
    assert response.location.endswith('#akto-dossier') and response.status_code == 303
    html = client.get('/admin/parametres').get_data(as_text=True)
    assert 'Dossier retrouvé en recette' in html and '2 échéance(s)' in html and 'RAW-PRIVATE-TEST' not in html
    assert calls == [('POST', HOST + '/SorApiIdentityServer/connect/token'), ('GET', HOST + '/SorApiEchangeCFA/v2/dossiers')]
    with closing(db()) as conn:
        assert tuple(conn.execute('SELECT credential,revision FROM akto_recette_key').fetchone()) == (credential, 0)
        assert conn.execute('SELECT count(*) FROM akto_students').fetchone()[0] == 0


@pytest.mark.parametrize(('code', 'message'), [(404, 'introuvable en recette'), (403, 'Accès refusé'), (503, '503')])
def test_lookup_http_outcomes(monkeypatch, code, message):
    monkeypatch.setattr('akto_convergence.recette_headers', lambda key: {})

    def unavailable(*args, **kwargs):
        raise ReadHttpError(code, f'HTTP {code}')

    monkeypatch.setattr(Client, 'json_request', unavailable)
    with pytest.raises(ReadError, match=message):
        lookup_dossier('test', 'TEST-REF', '00042')


@pytest.mark.parametrize('data', [None, {'cerfa': {'numeroExterne': 'DIFFERENT'}},
                                  {'cerfa': {'numeroExterne': 'TEST-REF', 'contrat': {'noContrat': '00043'}}}])
def test_lookup_rejects_mismatched_results(monkeypatch, data):
    monkeypatch.setattr('akto_convergence.recette_headers', lambda key: {})
    monkeypatch.setattr(Client, 'json_request', lambda *args, **kwargs: data)
    with pytest.raises(ReadError):
        lookup_dossier('test', 'TEST-REF', '00042')


def test_bad_request_preserves_safe_reason_including_chunked_json(monkeypatch):
    from akto_convergence import bad_request_reason
    from requests import Response
    response = Response()
    response.status_code = 400
    payload = {'description': 'Vérifiez les références.', 'errors': [
        {'code': 41, 'description': 'Numéro rejeté. test-secret-key test-token'}]}
    body = json.dumps(payload).encode()
    response.iter_content = lambda _: iter([body[:22], body[22:]])
    response.close = lambda: None
    monkeypatch.setattr('opco_convergence.requests.request', lambda *a, **kw: response)
    headers = {'X-API-KEY': 'test-secret-key', 'Authorization': 'Bearer test-token'}
    with pytest.raises(ReadHttpError) as err:
        Client.json_request('GET', HOST, describe_bad_request=lambda p: bad_request_reason(p, headers))
    assert err.value.status_code == 400
    assert 'Numéro rejeté' in err.value.detail and 'Code 41' in err.value.detail and 'test-' not in err.value.detail


def test_lookup_uses_internal_number_alone_and_checks_identity(monkeypatch):
    monkeypatch.setattr('akto_convergence.recette_headers', lambda key: {})
    def read(method, url, **kwargs):
        assert method == 'GET' and kwargs['params'] == {'numeroInterne': '007'}
        return {'cerfa': {'numeroExterne': 'CASE', 'numeroInterne': '007', 'contrat': {'noContrat': '00042'}}}
    monkeypatch.setattr(Client, 'json_request', read)
    assert 'Dossier retrouvé' in lookup_dossier('key', 'CASE', '00042', '007')
    with pytest.raises(ReadError, match='enregistrement'):
        lookup_dossier('key', 'CASE', '00043', '007')


def test_two_refusals_keep_their_respective_causes(monkeypatch):
    monkeypatch.setattr('akto_convergence.recette_headers', lambda key: {})
    calls = []
    def refused(method, url, **kwargs):
        calls.append(kwargs['params'])
        if 'numeroInterne' in kwargs['params']:
            raise ReadHttpError(404, 'not found')
        raise ReadHttpError(400, 'bad request', 'Numéro DECA invalide.')
    monkeypatch.setattr(Client, 'json_request', refused)
    with pytest.raises(ReadError) as err:
        lookup_dossier('key', 'CASE', '00042', '007')
    assert calls == [{'numeroInterne': '007'}, {'numeroExterne': 'CASE', 'numeroDeca': '00042'}]
    assert 'introuvable en recette (404)' in str(err.value) and 'Numéro DECA invalide' in str(err.value)


def test_technical_token_400_is_not_a_dossier_error(monkeypatch):
    monkeypatch.setenv(CLIENT_ID, 'test-id')
    monkeypatch.setenv(CLIENT_SECRET, 'test-secret')
    def refused(method, url, **kwargs):
        assert method == 'POST'
        raise ReadHttpError(400, 'bad request')
    monkeypatch.setattr(Client, 'json_request', refused)
    with pytest.raises(ReadError, match='recherche du dossier n’a pas été envoyée'):
        lookup_dossier('key', 'CASE', '00042', '007')
