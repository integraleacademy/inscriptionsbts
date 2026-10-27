"""Candidate editing regressions; all notifications use in-memory transports."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from test_admissions_2027 import application, auth, client, seed


@pytest.fixture
def editor(client, monkeypatch):
    seed(2027, 'editor', 'preinscription')
    seed(2026, 'other', 'confirmee')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET tel='0600000000',bts='MOS' WHERE id='editor'")
        conn.execute('UPDATE candidats SET verif_docs=? WHERE id=?', (json.dumps({'identity.pdf': {'etat':'non_conforme', 'label':'Identité'}}), 'editor'))
    auth(client)
    client.get('/admin/candidat/editor')
    with client.session_transaction() as state:
        headers = {'X-CSRF-Token':state['_candidate_message_csrf']}
    deliveries = []
    def mail(to, subject, html, attachments=None):
        deliveries.append({'type':'email', 'to':to, 'subject':subject, 'html':html,
                           'files':[Path(path).read_bytes() for path in attachments or []]})
        return 'mail-test-id'
    def sms(to, body):
        deliveries.append({'type':'sms', 'to':to, 'body':body})
        return 'sms-test-id'
    monkeypatch.setattr(application, 'send_mail', mail)
    monkeypatch.setattr(application, 'send_sms_brevo', sms)
    return client, headers, deliveries


def row(cid='editor'):
    with application.db() as conn:
        return dict(conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone())


@pytest.mark.parametrize('path,data', [
    ('/admin/reconfirm/editor', {}),
    ('/admin/resend_mail_sms/editor', {'action':'candidature_validee'}),
    ('/admin/resend_mail_sms/editor', {'action':'inscription_confirmee'}),
    ('/admin/resend_mail_sms/editor', {'action':'reconfirmation'}),
    ('/admin/resend_mail_sms/editor', {'action':'reconfirmee'}),
    ('/admin/resend_mail_sms/editor', {'action':'docs_non_conformes'}),
    ('/admin/relance/editor', {'action':'candidature_validee'}),
    ('/admin/relance/editor', {'action':'reconfirmation'}),
    ('/admin/relance/editor', {'action':'docs_non_conformes'}),
    ('/admin/files/notify', {'id':'editor', 'commentaire':'Remplacez ce document, merci.'}),
    ('/admin/send_mail_aps/editor', {}),
    ('/admin/update-status', {'id':'editor', 'value':'validee'}),
    ('/admin/update-status', {'id':'editor', 'value':'confirmee'}),
    ('/admin/update-status', {'id':'editor', 'value':'reconfirmee'}),
    ('/admin/send_certificat/editor', {}),
    ('/admin/send_certificat_presentiel/editor', {}),
])
def test_every_manual_send_needs_preview_and_sends_exact_preview_once(editor, path, data):
    client, headers, deliveries = editor
    before = row()
    assert client.post(path, json=data, headers=headers).status_code == 400
    response = client.post(path, json={**data, 'preview':True}, headers=headers)
    assert response.status_code == 200, response.json
    assert row() == before and not deliveries
    result = response.json
    messages = result['dossiers'][0]['messages']
    token = result['preview_token']
    response = client.post(path, json={**data, 'preview_token':token}, headers=headers)
    assert response.status_code == 200, response.json
    assert len(deliveries) == len(messages)
    for expected, actual in zip(messages, deliveries):
        assert expected['recipient'] == actual['to']
        key = 'html' if expected['type'] == 'email' else 'body'
        assert expected[key] == actual[key]
    assert client.post(path, json={**data, 'preview_token':token}, headers=headers).json['duplicate']
    assert len(deliveries) == len(messages)


def test_certificate_tracks_mode_and_sends_exact_previewed_pdf(editor):
    client, headers, deliveries = editor
    for mode, expected, excluded in [('presentiel','UAI 0831774C','UAI 0756548K'), ('distanciel','UAI 0756548K','UAI 0831774C')]:
        assert client.post('/admin/candidat/editor/parcours',json={'mode':mode},headers=headers).json['ok']
        data = client.post('/admin/send_certificat/editor',json={'preview':True},headers=headers).json
        preview_url = data['dossiers'][0]['files'][0]['url']
        pdf = client.get(preview_url)
        assert pdf.mimetype == 'application/pdf'
        reader = PdfReader(io.BytesIO(pdf.data)); assert len(reader.pages) == 3
        content = reader.pages[0].extract_text()
        assert expected in content and excluded not in content and '{{' not in content
        assert '2027-2029' in content and '01/09/2027' in content
        assert client.post('/admin/send_certificat/editor',json={'preview_token':data['preview_token']},headers=headers).json['ok']
        assert deliveries[-1]['files'] == [pdf.data]
        page = client.get('/admin/candidat/editor').text
        assert ('Certificat présentiel' if mode == 'presentiel' else 'Certificat distanciel') in page
        assert ('Certificat distanciel' if mode == 'presentiel' else 'Certificat présentiel') not in page
    assert client.get('/admin/send_certificat/editor').status_code == 405
    assert client.get('/admin/send_certificat_presentiel/editor').status_code == 405


@pytest.mark.parametrize('mode,uai', [('presentiel','0831774C'), ('distanciel','0756548K')])
def test_certificate_word_and_long_name_pdf_use_current_mode(editor, mode, uai):
    from docx import Document
    client, headers, deliveries = editor
    with application.db() as conn:
        conn.execute("UPDATE candidats SET prenom=?,nom=?,bts='NDRC',mode=? WHERE id='editor'",
                     ('Alexandre Jean-François', 'DE LA ROCHE SAINT-PIERRE', mode))
    pdf = PdfReader(io.BytesIO(client.get('/admin/candidat/editor/certificat.pdf').data))
    assert len(pdf.pages) == 3
    content = pdf.pages[0].extract_text()
    assert uai in content and 'SAINT-PIERRE' in content and '2027-2029' in content
    for route in ('generate_certificat', 'generate_certificat_presentiel'):
        response = client.get(f'/admin/{route}/editor')
        assert response.mimetype == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        content = '\n'.join(p.text for p in Document(io.BytesIO(response.data)).paragraphs)
        assert uai in content and 'SAINT-PIERRE' in content and '{{' not in content
        assert '2027' in content and '2029' in content
    assert not deliveries


def test_changed_dossier_or_action_invalidates_old_preview(editor):
    client, headers, deliveries = editor
    data = client.post('/admin/send_certificat/editor',json={'preview':True},headers=headers).json
    client.post('/admin/candidat/editor/parcours',json={'mode':'distanciel'},headers=headers)
    assert client.post('/admin/send_certificat/editor',json={'preview_token':data['preview_token']},headers=headers).status_code == 409
    token = client.post('/admin/resend_mail_sms/editor',json={'preview':True,'action':'candidature_validee'},headers=headers).json['preview_token']
    assert client.post('/admin/resend_mail_sms/editor',json={'preview_token':token,'action':'reconfirmee'},headers=headers).status_code == 400
    assert not deliveries


def test_preview_is_authenticated_session_bound_and_expiring(editor):
    client, headers, deliveries = editor
    assert client.post('/admin/reconfirm/editor',json={'preview':True}).status_code == 400
    token = client.post('/admin/send_certificat/editor',json={'preview':True},headers=headers).json['preview_token']
    other = application.app.test_client()
    auth(other)
    assert other.get(f'/admin/message-preview/{token}/document/0').status_code == 404
    with application.db() as conn:
        conn.execute('UPDATE candidate_workflow_previews SET expires_at=0')
    assert client.post('/admin/send_certificat/editor',json={'preview_token':token},headers=headers).status_code == 400
    with client.session_transaction() as state: state.clear()
    assert client.post('/admin/reconfirm/editor',json={'preview':True},headers=headers).status_code == 403
    assert client.get('/admin/candidat/editor/certificat.pdf').status_code == 403
    assert not deliveries


def test_failed_delivery_is_reported_and_cannot_be_retried(editor, monkeypatch):
    client, headers, deliveries = editor
    monkeypatch.setattr(application,'send_sms_brevo',lambda *a,**k:False)
    preview = client.post('/admin/reconfirm/editor',json={'preview':True},headers=headers).json
    data = {'preview_token':preview['preview_token']}
    response = client.post('/admin/reconfirm/editor',json=data,headers=headers)
    assert response.status_code == 502 and response.json['sent'] == 1
    assert client.post('/admin/reconfirm/editor',json=data,headers=headers).status_code == 409
    assert len(deliveries) == 1
    assert any(event['type'] == 'MESSAGE_ECHEC' for event in client.get('/admin/logs/editor').json)


@pytest.mark.parametrize('route,status', [('relance_all_validated','validee'),('reconfirm_all','confirmee')])
def test_bulk_preview_is_cohort_scoped_and_does_not_write(editor, route, status):
    client, headers, deliveries = editor
    with application.db() as conn:
        conn.execute('UPDATE candidats SET statut=?', (status,))
    before = row()
    path = f'/admin/{route}?rentree=2027'
    preview = client.post(path,json={'preview':True},headers=headers).json
    assert len(preview['dossiers']) == 1 and row() == before and not deliveries
    assert client.post(path,json={'preview_token':preview['preview_token']},headers=headers).status_code == 200
    assert all(message['to'] != 'other@example.test' for message in deliveries)
    assert row('other')['statut'] == status


def test_mode_change_does_not_require_correcting_unrelated_legacy_fields(editor):
    client, headers, deliveries = editor
    with application.db() as conn:
        conn.execute("UPDATE candidats SET tel='unknown',num_secu='old value' WHERE id='editor'")
    assert client.post('/admin/candidat/editor/parcours',json={'mode':'distanciel'},headers=headers).status_code == 200
    assert row()['mode'] == 'distanciel' and row()['num_secu'] == 'old value' and not deliveries
    assert client.post('/admin/candidat/editor/parcours',json={'mode':'invalid'},headers=headers).status_code == 400


def make_photo(cid='editor'):
    directory = Path(application.UPLOAD_DIR)/cid
    directory.mkdir(parents=True,exist_ok=True)
    path = directory/'photo.png'
    image = Image.new('RGB',(1000,1000),'blue')
    image.paste('red',(0,0,400,500))
    image.save(path)
    with application.db() as conn:
        conn.execute('UPDATE candidats SET fichiers_photo=? WHERE id=?',(json.dumps([str(path)]),cid))
    return path


def test_photo_crop_is_non_destructive_shared_and_resettable(editor):
    client, headers, _ = editor
    path = make_photo(); original = path.read_bytes()
    response = client.get('/admin/candidat/editor/photo?original=1')
    crop = dict(source_hash=response.headers['X-Photo-Source'],x=0,y=0,width=.4,height=.5,rotation=0)
    assert client.post('/admin/candidat/editor/photo-crop',json=crop,headers=headers).status_code == 200
    saved = json.loads(client.get('/admin/candidat/editor/photo?original=1').headers['X-Photo-Crop'])
    assert saved == {k:v for k,v in crop.items() if k != 'source_hash'}
    for url in ['/admin/candidat/editor/photo','/espace/editor/photo']:
        image = Image.open(io.BytesIO(client.get(url).data))
        assert image.size == (400,500)
        assert image.getpixel((200,250))[0] > 240 and image.getpixel((200,250))[2] < 10
    assert path.read_bytes() == original
    assert client.post('/admin/candidat/editor/photo-crop',json={'reset':True,'source_hash':crop['source_hash']},headers=headers).status_code == 200
    assert Image.open(io.BytesIO(client.get('/admin/candidat/editor/photo').data)).size == (600,600)


def test_photo_rotation_stale_source_invalid_crop_and_auth(editor):
    client, headers, _ = editor
    path = make_photo()
    source_hash = client.get('/admin/candidat/editor/photo?original=1').headers['X-Photo-Source']
    crop = dict(source_hash=source_hash,x=.5,y=0,width=.4,height=.5,rotation=90)
    assert client.post('/admin/candidat/editor/photo-crop',json=crop,headers=headers).status_code == 200
    image = Image.open(io.BytesIO(client.get('/admin/candidat/editor/photo').data))
    assert image.getpixel((200,100))[0] > 240
    for change in [dict(x=-.1),dict(width=2),dict(rotation=45),dict(height=0),dict(x=True),dict(x='0')]:
        assert client.post('/admin/candidat/editor/photo-crop',json={**crop,**change},headers=headers).status_code == 400
    assert client.post('/admin/candidat/editor/photo-crop',json=crop).status_code == 400
    Image.new('RGB',(1000,1000),'green').save(path)
    assert client.post('/admin/candidat/editor/photo-crop',json=crop,headers=headers).status_code == 409
    assert Image.open(io.BytesIO(client.get('/admin/candidat/editor/photo').data)).size == (600,600)
    with client.session_transaction() as state: state.clear()
    assert client.post('/admin/candidat/editor/photo-crop',json=crop,headers=headers).status_code == 403


def test_precise_straightening_matches_saved_portrait_and_rejects_empty_corners(editor):
    from PIL import ImageDraw
    client, headers, _ = editor
    path = make_photo()
    source = Image.new('RGB', (1000, 1000), 'blue')
    ImageDraw.Draw(source).rectangle((450,100,550,900), fill='red')
    source.rotate(-27, resample=Image.Resampling.BICUBIC, fillcolor='blue').save(path)
    original = path.read_bytes()
    source_hash = client.get('/admin/candidat/editor/photo?original=1').headers['X-Photo-Source']
    crop = dict(version=2, rotation=0, straighten=-27, cx=.5, cy=.5, width=.4, height=.5, source_hash=source_hash)
    assert client.post('/admin/candidat/editor/photo-crop',json=crop,headers=headers).status_code == 200
    result = Image.open(io.BytesIO(client.get('/admin/candidat/editor/photo').data))
    assert result.size == (400,500)
    for position in ((200,60),(200,440)):
        assert result.getpixel(position)[0] > 240
        assert result.getpixel((60,position[1]))[2] > 240
    restored = json.loads(client.get('/admin/candidat/editor/photo?original=1').headers['X-Photo-Crop'])
    assert restored['straighten'] == -27 and restored['version'] == 2
    assert path.read_bytes() == original
    for bad in ({'straighten':46}, {'straighten':True}, {'cx':.02}, {'width':1,'height':1.25}, {'cx':float('inf')}):
        assert client.post('/admin/candidat/editor/photo-crop',json={**crop,**bad},headers=headers).status_code == 400


@pytest.mark.parametrize('mode', ['presentiel', 'distanciel'])
@pytest.mark.parametrize('bts', ['MOS','MCO','NDRC','PI','CI','CG'])
def test_original_certificate_model_all_courses_annexes_and_future_cohort(mode, bts):
    import hashlib
    from certificates import certificate_pdf
    root = Path(application.__file__).parent
    for year in (2026,2027,2028):
        data = certificate_pdf(dict(mode=mode,bts=bts,prenom='Élodie',nom='DUPONT',rentree_annee=year))
        reader = PdfReader(io.BytesIO(data))
        assert len(reader.pages) == 3
        text = '\n'.join(page.extract_text() for page in reader.pages)
        assert 'DUPONT Élodie' in text and '{{' not in text and '00/00/0000' not in text
        assert f'{year}-{year+2}' in text and 'Confirmation d’inscription' in text and 'Contrat d’apprentissage' in text
        assert 'SERVICE SCOLARITÉ' not in text
        if year >= 2027: assert '6000€' not in text and 'septembre 2026' not in text
        base_year = 2026 if year == 2026 else 2027
        manifest = json.loads((root/'assets/certificates/manifest.json').read_text())
        template = manifest['templates'][f'{mode}-{bts}-{base_year}']
        model = PdfReader(root/'assets/certificates'/template['file'])
        # Original header, footer QR, stamps and signatures survive every overlay.
        for page, original in zip(reader.pages, model.pages[template['start']:template['start']+3]):
            original_images = {hashlib.sha256(image.data).hexdigest() for image in original.images}
            assert original_images <= {hashlib.sha256(image.data).hexdigest() for image in page.images}
