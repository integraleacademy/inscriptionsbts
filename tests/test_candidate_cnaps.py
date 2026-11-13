"""Security-only CNAPS collection, confirmed mail history and safe live tracking."""
import hashlib
import hmac
import json

import pytest
import requests
from bs4 import BeautifulSoup

from test_admissions_2027 import application, auth, client, seed
from candidate_cnaps import COLLECTION_URL, TRACKING_SOURCE_URL, collection_email
from candidate_workflows import prepare_workflow
from training_programs import SECURITY


def security_candidate(client, cid='cnaps-candidate'):
    seed(2027, cid, 'preinscription')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=? WHERE id=?', (SECURITY, cid))
    auth(client)
    assert client.get('/admin/candidat/' + cid).status_code == 200
    with client.session_transaction() as state:
        return {'X-CSRF-Token': state['_candidate_message_csrf']}


def test_collection_preparation_has_no_status_change_or_sms():
    row = dict(id='c', bts=SECURITY, email='candidate@example.test', prenom='<script>bad()</script>', nom='TEST')
    with application.app.test_request_context():
        plan = prepare_workflow(row, 'cnaps', {})
    assert plan['changes'] == {} and plan['files'] == []
    mail, = plan['messages']
    assert mail['type'] == 'email' and mail['recipient'] == row['email']
    assert mail['reply_to'] == 'aurelie@integraleacademy.com'
    soup = BeautifulSoup(mail['html'], 'html.parser')
    assert soup.select_one('a[href="' + COLLECTION_URL + '"]')
    assert soup.find('script') is None
    assert 'CNAPS' in mail['subject']
    assert 'cnapsv5' not in mail['html']


@pytest.mark.parametrize('program', ['MOS', 'MCO', 'NDRC', 'PI', 'CI', 'CG', 'TP GESTIONNAIRE DE PAIE', ''])
def test_every_other_course_is_excluded_from_ui_and_routes(client, monkeypatch, program):
    seed(2027, 'other')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=? WHERE id=?', (program, 'other'))
    auth(client)
    calls = []
    monkeypatch.setattr('candidate_cnaps.requests.get', lambda *a, **kw: calls.append(a))
    page = client.get('/admin/candidat/other')
    assert page.status_code == 200
    assert 'Collecter les informations CNAPS' not in page.text
    assert 'candidate-cnaps.js' not in page.text
    assert client.get('/admin/candidat/other/cnaps-tracking').status_code == 404
    assert client.post('/admin/candidat/other/cnaps-request', json={'preview': True}).status_code == 404
    with pytest.raises(ValueError, match='parcours sécurité'):
        collection_email({'bts': program})
    assert calls == []


def test_authentication_and_csrf_required(client):
    assert client.get('/admin/candidat/any/cnaps-tracking').status_code == 403
    assert client.post('/admin/candidat/any/cnaps-request', json={}).status_code == 403
    security_candidate(client)
    assert client.post('/admin/candidat/cnaps-candidate/cnaps-request', json={'preview': True}).status_code == 400
    assert client.get('/admin/candidat/missing/cnaps-tracking').status_code == 404


def test_preview_then_confirm_sends_exact_mail_once_and_records_date(client, monkeypatch):
    headers = security_candidate(client)
    calls = []
    monkeypatch.setattr(application, 'send_mail', lambda *a, **kw: calls.append((a, kw)) or 'brevo-confirmed')
    route = '/admin/candidat/cnaps-candidate/cnaps-request'
    preview = client.post(route, json={'preview': True}, headers=headers)
    assert preview.status_code == 200
    assert calls == []
    before = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking?collection_only=1')
    assert before.json == {'ok': True, 'collection_sent_at': None}
    mail, = preview.json['dossiers'][0]['messages']
    confirmation = {'preview_token': preview.json['preview_token']}
    assert client.post(route, json=confirmation, headers=headers).json['sent'] == 1
    assert calls[0][0] == (mail['recipient'], mail['subject'], mail['html'])
    assert calls[0][1]['reply_to'] == mail['reply_to']
    assert client.post(route, json=confirmation, headers=headers).json['duplicate']
    assert len(calls) == 1
    after = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking?collection_only=1')
    assert after.json['collection_sent_at']
    assert after.headers['Cache-Control'] == 'private, no-store'
    assert 'Complète tes informations CNAPS' in client.get('/admin/candidat/cnaps-candidate/emails').text
    with application.db() as conn:
        assert conn.execute('SELECT statut FROM candidats WHERE id=?', ('cnaps-candidate',)).fetchone()[0] == 'preinscription'


def test_failed_mail_is_not_marked_as_collected_or_sent(client, monkeypatch):
    headers = security_candidate(client)
    monkeypatch.setattr(application, 'send_mail', lambda *a, **kw: False)
    route = '/admin/candidat/cnaps-candidate/cnaps-request'
    preview = client.post(route, json={'preview': True}, headers=headers)
    result = client.post(route, json={'preview_token': preview.json['preview_token']}, headers=headers)
    assert result.status_code == 502 and result.json['sent'] == 0
    assert client.get('/admin/candidat/cnaps-candidate/cnaps-tracking?collection_only=1').json['collection_sent_at'] is None


def test_changed_candidate_cannot_receive_stale_preview(client, monkeypatch):
    headers = security_candidate(client)
    calls = []
    monkeypatch.setattr(application, 'send_mail', lambda *a, **kw: calls.append(a))
    route = '/admin/candidat/cnaps-candidate/cnaps-request'
    preview = client.post(route, json={'preview': True}, headers=headers)
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=? WHERE id=?', ('MOS', 'cnaps-candidate'))
    result = client.post(route, json={'preview_token': preview.json['preview_token']}, headers=headers)
    assert result.status_code == 404 and not calls


class RemoteResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode()
        self.status_code = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.payload


def remote_setup(client, monkeypatch, payload, status=200):
    security_candidate(client)
    monkeypatch.setenv('BTS_IMPORT_API_KEY', 'test-shared-key-' * 4)
    calls = []
    def get(url, **options):
        calls.append((url, options))
        return RemoteResponse(payload, status)
    monkeypatch.setattr('candidate_cnaps.requests.get', get)
    return calls


def test_tracking_uses_candidate_id_and_derived_server_credential_with_safe_payload(client, monkeypatch):
    calls = remote_setup(client, monkeypatch, {
        'found': True, 'person': {'nub': '1234567', 'email': 'private@example.test'},
        'source_url': 'https://untrusted.invalid/collect', 'token': 'must-never-leak',
        'inscription': 'Parcours sécurité',
        'cnaps': {'cnaps_status': 'ACCEPTÉ', 'last_checked_at': '2026-11-13T12:00:00Z',
                  'nub_missing': False, 'titles': [{'type': 'AP SH', 'state': 'ACTIF', 'expires_at': '2027-05-01', 'secret': 'hidden'}]},
    })
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking?refresh=1')
    assert response.status_code == 200
    assert response.json['cnaps']['status'] == 'ACCEPTÉ'
    assert response.json['nub'] == '1234567' and response.json['source_url'] == TRACKING_SOURCE_URL
    assert response.json['cnaps']['titles'][0]['expires_at'] == '2027-05-01'
    for forbidden in ('must-never-leak', 'private@example.test', 'untrusted.invalid', 'hidden'):
        assert forbidden not in response.text
    url, options = calls[0]
    assert url.endswith('/api/integrations/bts/candidats/cnaps-candidate/cnaps-tracking')
    expected = hmac.new(('test-shared-key-' * 4).encode(), b'bts-cnaps-tracking-v1', hashlib.sha256).hexdigest()
    assert options['headers']['Authorization'] == 'Bearer ' + expected
    assert expected not in response.text
    assert options['params'] == {'refresh': '1'} and options['allow_redirects'] is False
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_missing_dossier_is_an_empty_state_not_an_integration_error(client, monkeypatch):
    remote_setup(client, monkeypatch, {'found': False})
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking')
    assert response.status_code == 200 and response.json['found'] is False and response.json['ok']


def test_cached_tracking_is_explicitly_stale_when_refresh_fails(client, monkeypatch):
    remote_setup(client, monkeypatch, {
        'found': True, 'cnaps': {'cnaps_status': 'TRANSMIS', 'last_checked_at': '2026-11-12T12:00:00Z'},
        'stale': True, 'refresh_failed': True, 'refresh_error': 'private provider error',
    })
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking?refresh=1')
    assert response.status_code == 200 and response.json['stale'] and response.json['refresh_failed']
    assert response.json['cnaps']['last_checked_at'] == '2026-11-12T12:00:00Z'
    assert 'private provider error' not in response.text


@pytest.mark.parametrize('status,expected,reason', [(401,503,'not_configured'),(403,503,'not_configured'),(409,409,'ambiguous_match'),(502,502,'unavailable'),(302,502,'unavailable')])
def test_remote_errors_are_explicit_without_exposing_provider_body(client, monkeypatch, status, expected, reason):
    remote_setup(client, monkeypatch, {'error': 'secret-provider-details'}, status)
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking')
    assert response.status_code == expected
    assert response.json['reason'] == reason and response.json['ok'] is False
    assert 'secret-provider-details' not in response.text


def test_unconfigured_tracking_does_not_call_remote(client, monkeypatch):
    security_candidate(client)
    monkeypatch.delenv('BTS_IMPORT_API_KEY', raising=False)
    calls = []
    monkeypatch.setattr('candidate_cnaps.requests.get', lambda *a, **kw: calls.append(a))
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking')
    assert response.status_code == 503 and not calls


def test_timeout_and_malformed_remote_are_safe_errors(client, monkeypatch):
    remote_setup(client, monkeypatch, {'unexpected': True})
    assert client.get('/admin/candidat/cnaps-candidate/cnaps-tracking').status_code == 502
    def timeout(*args, **kwargs):
        raise requests.Timeout('private remote details')
    monkeypatch.setattr('candidate_cnaps.requests.get', timeout)
    response = client.get('/admin/candidat/cnaps-candidate/cnaps-tracking')
    assert response.status_code == 502 and 'private remote details' not in response.text
