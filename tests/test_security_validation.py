"""Security validation invites candidates to an interview; no real sends."""
from html import unescape
import base64
import hashlib
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from test_admissions_2027 import application, auth, client, seed
from branded_email import BRAND_MARKER, email_plain_text
from candidate_workflows import prepare_workflow
from mail_templates import mail_html
from security_admission import ADVISER, BROCHURE_NAME, BROCHURE_PATH
from training_programs import SECURITY


def candidate(**values):
    return dict(id='security', nom='EXEMPLE', prenom='Camille', email='camille@example.test',
                tel='0600000000', bts=SECURITY, statut='preinscription', slug_public='security',
                rentree_annee=2027, **values)


def test_validation_has_real_clickable_contacts_and_safe_personalization():
    html = mail_html('candidature_validee', program_code=SECURITY, prenom='Camille &lt;img src=x onerror=alert(1)&gt;')
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.h1.get_text(' ', strip=True) == 'Parcours sécurité en alternance'
    assert 'Ta candidature est validée.' in soup.select_one('.mail-title').text
    assert soup.select_one('a[href="tel:+33487830615"]').text == '04 87 83 06 15'
    assert soup.select_one('a[href="tel:+33769390457"]').text == '07 69 39 04 57'
    assert soup.select_one('a[href="mailto:aurelie@integraleacademy.com"]')
    assert soup.select_one('a[href^="mailto:aurelie@integraleacademy.com?subject="]')
    assert 'Chargée des relations clients' in soup.text and 'BAYARD-CHAUSSEZ' in soup.text
    assert html.count(BRAND_MARKER) == 1 and not soup.select('[onerror]')
    assert not soup.select('img[src=x]')
    assert 'entretien' in email_plain_text(html)
    assert ADVISER['email'] in email_plain_text(html)
    assert 'Confirmer mon inscription' not in html and '/confirm-inscription' not in html
    assert 'Fais le premier pas vers ton futur métier' in soup.text
    assert 'Votre parcours, notre engagement.' not in soup.text
    for detail in ('Ton projet et tes motivations', 'Ton organisation et tes disponibilités',
                   'Les prochaines démarches', 'APS', 'A3P', 'SSIAP 1', 'TA BROCHURE EN PIÈCE JOINTE'):
        assert detail in soup.text


@pytest.mark.parametrize('kind,data', [
    ('status', {'value': 'validee'}),
    ('resend', {'action': 'candidature_validee'}),
    ('remind', {'action': 'candidature_validee'}),
])
def test_security_validation_and_reminders_use_same_interview_step(kind, data):
    with application.app.test_request_context():
        planned = prepare_workflow(candidate(), kind, data)
    email, sms = planned['messages']
    assert email['reply_to'] == ADVISER['email']
    assert email['cc'] == [ADVISER['email']]
    assert email['copy'] == 'gestion@integraleacademy.com, aurelie@integraleacademy.com'
    assert 'entretien' in email['html'] and 'entretien' in sms['body']
    assert 'Confirmez votre inscription' not in email['subject']
    assert 'BTS' not in email['subject'] and 'BTS' not in sms['body']
    assert '/confirm-inscription' not in email['html'] + sms['body']
    assert 'token_confirm' not in planned['changes']
    assert ('programmer ton entretien' in email['subject']) == (kind == 'remind')
    assert len(planned['files']) == 1
    assert planned['files'][0]['name'] == BROCHURE_NAME
    assert base64.b64decode(planned['files'][0]['content']) == BROCHURE_PATH.read_bytes()


@pytest.mark.parametrize('program', ['MOS', 'MCO', 'NDRC', 'PI', 'CI', 'CG', 'TP GESTIONNAIRE DE PAIE'])
def test_other_courses_keep_their_confirmation_workflow(program):
    row = candidate()
    row['bts'] = program
    with application.app.test_request_context():
        planned = prepare_workflow(row, 'status', {'value': 'validee'})
    email, sms = planned['messages']
    assert '/confirm-inscription?' in unescape(email['html'])
    assert '/confirm-inscription?' in sms['body']
    assert planned['changes']['token_confirm']
    assert 'reply_to' not in email
    assert 'cc' not in email
    assert 'Écrire à Aurélie pour mon entretien' not in email['html']
    assert not planned['files']


def test_status_sends_exact_preview_once_and_keeps_history(client, monkeypatch):
    seed(2027, 'security', 'preinscription')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=?,tel=? WHERE id=?', (SECURITY, '0600000000', 'security'))
    auth(client)
    client.get('/admin/candidat/security')
    with client.session_transaction() as session:
        headers = {'X-CSRF-Token': session['_candidate_message_csrf']}
    deliveries = []
    def mail(*args, **kwargs):
        kwargs['attachment_bytes'] = [Path(path).read_bytes() for path in kwargs.get('attachments', [])]
        deliveries.append(('email', args, kwargs))
        return 'email-id'
    monkeypatch.setattr(application, 'send_mail', mail)
    monkeypatch.setattr(application, 'send_sms_brevo', lambda *args: deliveries.append(('sms', args, {})) or 'sms-id')
    data = {'id': 'security', 'value': 'validee'}
    preview = client.post('/admin/update-status', json={**data, 'preview': True}, headers=headers)
    assert preview.status_code == 200, preview.json
    assert not deliveries
    file, = preview.json['dossiers'][0]['files']
    assert file['name'] == BROCHURE_NAME
    attachment = client.get(file['url'])
    assert attachment.mimetype == 'application/pdf'
    assert attachment.data == BROCHURE_PATH.read_bytes()
    assert application.app.test_client().get(file['url']).status_code == 403
    with application.db() as conn:
        assert conn.execute('SELECT statut FROM candidats WHERE id=?', ('security',)).fetchone()[0] == 'preinscription'
    confirmation = {**data, 'preview_token': preview.json['preview_token']}
    response = client.post('/admin/update-status', json=confirmation, headers=headers)
    assert response.status_code == 200 and response.json['sent'] == 2
    expected = preview.json['dossiers'][0]['messages'][0]
    assert expected['cc'] == [ADVISER['email']]
    assert ADVISER['email'] in expected['copy']
    assert deliveries[0][1] == (expected['recipient'], expected['subject'], expected['html'])
    assert deliveries[0][2]['reply_to'] == ADVISER['email']
    assert deliveries[0][2]['cc'] == expected['cc']
    assert deliveries[0][2]['attachment_bytes'] == [attachment.data]
    with application.db() as conn:
        saved = dict(conn.execute('SELECT * FROM candidats WHERE id=?', ('security',)).fetchone())
    assert saved['statut'] == 'validee' and not saved['token_confirm']
    assert client.post('/admin/update-status', json=confirmation, headers=headers).json['duplicate']
    assert len(deliveries) == 2
    assert prepare_workflow(saved, 'status', data)['messages'] == []
    logs = client.get('/admin/logs/security').json
    assert sum(event['type'] == 'MAIL_ENVOYE' for event in logs) == 1
    assert any('entretien' in str(event) for event in logs)
    assert any(BROCHURE_NAME in str(event) for event in logs)
    assert any(event['type'] == 'MAIL_ENVOYE' and 'copie' in str(event) and ADVISER['email'] in str(event) for event in logs)


def test_brochure_is_exact_provided_sixteen_page_pdf():
    from pypdf import PdfReader
    assert hashlib.sha256(BROCHURE_PATH.read_bytes()).hexdigest() == 'a9a497274634ff82d9b0a9eddc2e016ab4ee482b40dccdc7bc8e3f9694a1bced'
    assert len(PdfReader(BROCHURE_PATH).pages) == 16


def test_missing_brochure_stops_preview_without_changing_status(client, monkeypatch, tmp_path):
    import security_admission
    monkeypatch.setattr(security_admission, 'BROCHURE_PATH', tmp_path / 'missing.pdf')
    seed(2027, 'security', 'preinscription')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=? WHERE id=?', (SECURITY, 'security'))
    auth(client)
    client.get('/admin/candidat/security')
    with client.session_transaction() as session:
        headers = {'X-CSRF-Token': session['_candidate_message_csrf']}
    deliveries = []
    monkeypatch.setattr(application, 'send_mail', lambda *a, **k: deliveries.append(a))
    response = client.post('/admin/update-status', json={'id':'security', 'value':'validee', 'preview':True}, headers=headers)
    assert response.status_code == 400 and 'brochure' in response.json['error']
    with application.db() as conn:
        assert conn.execute('SELECT statut FROM candidats WHERE id=?', ('security',)).fetchone()[0] == 'preinscription'
    assert not deliveries
