from contextlib import closing
from pathlib import Path
import sqlite3

import pytest
from flask import Flask, session

from akto_convergence import CLIENT_ID, CLIENT_SECRET, HOST, register_akto_convergence, verify_key
from akto_sync import register_akto, secret
from opco_convergence import Client, ReadError
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
