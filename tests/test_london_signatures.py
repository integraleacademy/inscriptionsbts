"""London signing lifecycle with synthetic people and an in-memory Yousign API."""
import copy
from io import BytesIO
import json
import uuid
from unittest.mock import patch

import pytest
from test_london_mobility import application, auth, client, seed, london, data, post, versions
from london_mobility_signatures import SignatureError, YousignClient, signature_fields


class FakeYousign:
    def __init__(self):
        self.calls = []; self.requests = {}; self.timeout = None; self.bad_pdf = False

    def call(self, method, path, **kwargs):
        self.calls.append((method,path,copy.deepcopy(kwargs.get('json'))))
        result = self.perform(method,path,**kwargs)
        if self.timeout and self.timeout == (method,path.split('/')[-1]):
            self.timeout = None
            raise SignatureError('Yousign n’a pas confirmé l’opération.', True)
        return result

    def perform(self, method, path, **kwargs):
        if method == 'POST' and path == '/signature_requests':
            rid = str(uuid.uuid4())
            state = {**kwargs['json'],'id':rid,'status':'draft','documents':[],'signers':[]}
            self.requests[rid] = state
            return {'id':rid,'status':'draft'}
        if method == 'GET' and path == '/signature_requests':
            return {'data':[r for r in self.requests.values() if r['external_id'] == kwargs['params']['external_id[eq]']]}
        rid = path.split('/')[2]; state = self.requests[rid]
        if state['status'] == 'deleted': raise SignatureError('Absent', status_code=404)
        if path.endswith('/documents'):
            if method == 'GET': return copy.deepcopy(state['documents'])
            document = {'id':str(uuid.uuid4())}; state['documents'].append(document)
            state['content'] = kwargs['files']['file'][1]
            assert kwargs['data'] == {'nature':'signable_document'}
            return document
        if path.endswith('/signers'):
            if method == 'GET': return copy.deepcopy(state['signers'])
            person = {**copy.deepcopy(kwargs['json']),'id':str(uuid.uuid4()),'status':'initiated'}
            state['signers'].append(person); return person
        if path.endswith('/activate'):
            assert state['status'] == 'draft'
            state['status'] = 'ongoing'
            for p in state['signers']: p['status'] = 'notified'
            return {'id':rid,'status':'ongoing'}
        if path.endswith('/download'): return b'broken' if self.bad_pdf else state['content']
        if path.endswith('/send_reminder'): return {}
        if path.endswith('/cancel'): state['status'] = 'canceled'; return {'status':'canceled'}
        if method == 'DELETE': state['status'] = 'deleted'; return {}
        if method == 'GET': return {k:v for k,v in state.items() if k not in {'content','documents','signers'}}
        raise AssertionError((method,path))

    @property
    def latest(self): return list(self.requests.values())[-1]

    def complete(self):
        self.latest['status'] = 'done'
        for person in self.latest['signers']: person['status'] = 'signed'


@pytest.fixture
def signing(london, monkeypatch):
    fake = FakeYousign()
    monkeypatch.setitem(application.app.config, 'LONDON_YOUSIGN_CLIENT_FACTORY', lambda: fake)
    monkeypatch.setitem(application.app.config, 'LONDON_SIGNATURE_POLLING', False)
    return fake


def send(client, **overrides):
    vid = versions()[0]['id']
    values = data(client)
    payload = dict(csrf_token=values['csrf_token'],source_fingerprint=values['source_fingerprint'],reviewed='yes',
                   employer_first_name='Alex',employer_last_name='EXEMPLE',employer_email='alex@entreprise.example',
                   apprentice_email='camille@apprenti.example',guardian_email='parent@famille.example',employer_phone='0612345678',apprentice_phone='0676543210',guardian_phone='0712345678',**{})
    payload.update(overrides)
    return client.post(f'/admin/candidat/london/londres/conventions/{vid}/signature',data=payload,headers={'Accept':'application/json'})


def attempts():
    with application.db() as conn:
        return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM london_mobility_signatures ORDER BY created_at DESC')]


def action(client, operation, **values):
    state = attempts()[0]
    return client.post(f"/admin/candidat/london/londres/conventions/{state['version_id']}/signature/{state['id']}/{operation}",
                       data={'csrf_token':data(client)['csrf_token'],**values},headers={'Accept':'application/json'})


def test_adult_send_once_and_archive_only_when_all_signers_signed(london, signing):
    assert post(london,data(london)).status_code == 200
    version = versions()[0]
    original = london.get(f"/admin/candidat/london/londres/conventions/{version['id']}/pdf").data
    assert send(london).status_code == 200
    assert len(signing.requests) == 1 and len(signing.latest['signers']) == 2
    assert signing.latest['delivery_mode'] == 'email' and not signing.latest['ordered_signers']
    assert all(p['signature_authentication_mode']=='otp_sms' for p in signing.latest['signers'])
    assert all(len(p['fields']) == 1 and p['fields'][0]['page'] == 4 for p in signing.latest['signers'])
    assert signing.calls[-1][1].endswith('/activate')
    count = len(signing.calls)
    assert send(london).status_code == 400 and len(signing.calls) == count
    assert 'Signatures en cours' in london.get('/admin/candidat/london').text
    signing.latest['status'] = 'done'; signing.latest['signers'][0]['status'] = 'signed'
    assert action(london,'refresh').status_code == 409
    assert not versions()[0]['signed_id']
    signing.complete()
    assert action(london,'refresh').status_code == 200
    assert attempts()[0]['status'] == 'completed' and versions()[0]['signed_id']
    with application.db() as conn:
        assert conn.execute("SELECT convention FROM voyage_londres_inscriptions WHERE candidat_id='london'").fetchone()[0] == 'Signée'
    assert london.get(f"/admin/candidat/london/londres/conventions/{version['id']}/pdf").data == original
    assert london.get(f"/admin/candidat/london/londres/conventions/{version['id']}/signed").status_code == 200
    assert action(london,'refresh').status_code == 200
    with application.db() as conn: assert conn.execute('SELECT count(*) FROM voyage_londres_documents').fetchone()[0] == 3


def test_minor_requires_distinct_guardian_and_correct_third_signature(london, signing):
    with application.db() as conn: conn.execute("UPDATE candidats SET date_naissance='2010-03-12' WHERE id='london'")
    assert post(london,data(london,guardian_first_name='Charlie',guardian_last_name='EXEMPLE')).status_code == 200
    assert send(london,guardian_email='').status_code == 400 and not signing.calls
    assert send(london,guardian_email='CAMILLE@apprenti.example').status_code == 400
    assert send(london).status_code == 200
    assert len(signing.latest['signers']) == 3
    guardian = signing.latest['signers'][2]
    assert guardian['info']['first_name'] == 'Charlie'
    assert guardian['fields'][0]['y'] > signing.latest['signers'][1]['fields'][0]['y'] + 45
    assert guardian['fields'][0]['y'] + 45 < 790


@pytest.mark.parametrize('overrides', [{'reviewed':''},{'employer_email':'bad'},{'employer_first_name':''},{'csrf_token':'bad'},{'source_fingerprint':'old'}])
def test_invalid_send_does_not_contact_yousign(london, signing, overrides):
    assert post(london,data(london)).status_code == 200
    assert send(london,**overrides).status_code == 400
    assert not signing.calls and not attempts()


def test_stale_version_and_foreign_candidate_do_not_send(london, signing):
    assert post(london,data(london)).status_code == 200
    with application.db() as conn: conn.execute("UPDATE candidats SET nom='Autre' WHERE id='london'")
    assert send(london).status_code == 400 and not signing.calls
    vid = versions()[0]['id']
    assert london.post(f'/admin/candidat/other/londres/conventions/{vid}/signature',data={'csrf_token':data(london)['csrf_token'],'reviewed':'yes'}).status_code == 404


def test_creation_timeout_is_recovered_without_duplicate_request(london, signing):
    post(london,data(london)); signing.timeout=('POST','signature_requests')
    response = send(london)
    assert response.status_code == 409 and response.json['refresh_url']
    assert attempts()[0]['pending'] == 'create'
    assert action(london,'resume',reviewed='yes').status_code == 409
    assert len(signing.requests) == 1
    assert action(london,'refresh').status_code == 200
    assert action(london,'resume',reviewed='yes').status_code == 200
    assert len(signing.requests) == 1 and attempts()[0]['status'] == 'ongoing'


def test_activation_timeout_reconciles_without_second_invitation(london, signing):
    post(london,data(london)); signing.timeout=('POST','activate')
    assert send(london).status_code == 409
    assert action(london,'refresh').status_code == 200
    assert attempts()[0]['status'] == 'ongoing' and 'pending' not in attempts()[0]
    assert action(london,'resume',reviewed='yes').status_code == 409
    assert len([c for c in signing.calls if c[1].endswith('/activate')]) == 1


def test_upload_timeout_requires_cancel_and_new_request(london, signing):
    post(london,data(london)); signing.timeout=('POST','documents')
    assert send(london).status_code == 409
    assert action(london,'refresh').status_code == 200
    assert attempts()[0]['pending'] == 'document'
    assert action(london,'resume',reviewed='yes').status_code == 409
    assert action(london,'cancel',cancel_confirmed='yes').status_code == 200
    assert send(london).status_code == 200 and len(signing.requests) == 2


def test_cancel_timeout_after_delete_is_reconciled(london, signing):
    post(london,data(london)); signing.timeout=('POST','documents'); send(london)
    signing.timeout=('DELETE',signing.latest['id'])
    assert action(london,'cancel',cancel_confirmed='yes').status_code == 409
    assert action(london,'refresh').status_code == 200
    assert attempts()[0]['status'] == 'deleted'


def test_remote_signer_change_never_marks_document_signed(london, signing):
    post(london,data(london)); send(london); signing.complete()
    signing.latest['signers'][0]['info']['email'] = 'intrus@example.test'
    assert action(london,'refresh').status_code == 409 and not versions()[0]['signed_id']


def test_invalid_download_can_resume_archiving_without_resending(london, signing):
    post(london,data(london)); send(london); signing.complete(); signing.bad_pdf=True
    assert action(london,'refresh').status_code == 409 and not versions()[0]['signed_id']
    signing.bad_pdf=False
    with application.db() as conn: conn.execute("UPDATE voyage_londres_inscriptions SET convention='Transmise OPCO' WHERE candidat_id='london'")
    assert action(london,'refresh').status_code == 200
    with application.db() as conn: assert conn.execute("SELECT convention FROM voyage_londres_inscriptions WHERE candidat_id='london'").fetchone()[0] == 'Transmise OPCO'
    assert len([c for c in signing.calls if c[1].endswith('/activate')]) == 1


def test_active_request_blocks_regeneration_and_manual_upload(london, signing):
    post(london,data(london)); send(london)
    assert post(london,data(london,mobility_start='2027-11-09')).status_code == 400
    vid = versions()[0]['id']; pdf = signing.latest['content']
    response = london.post(f'/admin/candidat/london/londres/conventions/{vid}/signee',data={
        'csrf_token':data(london)['csrf_token'],'signed_confirmed':'yes','document':(BytesIO(pdf),'signed.pdf')},headers={'Accept':'application/json'})
    assert response.status_code == 400
    assert action(london,'cancel').status_code == 409
    assert action(london,'cancel',cancel_confirmed='yes').status_code == 200
    assert post(london,data(london,mobility_start='2027-11-09')).status_code == 200


def test_reminders_only_unsigned_with_cooldown(london, signing):
    post(london,data(london)); send(london)
    assert action(london,'remind',role='employer').status_code == 200
    assert action(london,'remind',role='employer').status_code == 409
    signing.latest['signers'][1]['status']='signed'
    assert action(london,'remind',role='apprentice').status_code == 409
    assert len([c for c in signing.calls if c[1].endswith('/send_reminder')]) == 1


def test_lock_and_polling_archive_without_page_open(london, signing):
    post(london,data(london))
    service=application.app.extensions['london_signatures']
    with service.lock('london'):
        assert send(london).status_code == 400 and not signing.calls
    send(london); signing.complete()
    state=attempts()[0]; state['checked_at']='2020-01-01T00:00:00+00:00'; service.save(state)
    with application.app.app_context(): service.poll()
    assert attempts()[0]['status'] == 'completed'


def test_client_handles_timeout_and_never_exposes_api_key(monkeypatch):
    monkeypatch.setenv('YOUSIGN_API_KEY','secret-not-for-errors'); monkeypatch.setenv('YOUSIGN_ENV','production')
    monkeypatch.delenv('YOUSIGN_BASE_URL',raising=False)
    import requests
    with patch('london_mobility_signatures.requests.request',side_effect=requests.Timeout('secret-not-for-errors')):
        with pytest.raises(SignatureError) as exc: YousignClient().call('POST','/signature_requests',json={})
    assert exc.value.ambiguous and 'secret-not-for-errors' not in str(exc.value)
    monkeypatch.setenv('YOUSIGN_BASE_URL','https://untrusted.example/v3')
    with pytest.raises(SignatureError): YousignClient()
