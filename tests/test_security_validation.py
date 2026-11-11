"""Security validation invites candidates to an interview; no real sends."""
from html import unescape

import pytest
from bs4 import BeautifulSoup

from test_admissions_2027 import application, auth, client, seed
from branded_email import BRAND_MARKER, email_plain_text
from candidate_workflows import prepare_workflow
from mail_templates import mail_html
from security_admission import ADVISER
from training_programs import SECURITY


def candidate(**values):
    return dict(id='security', nom='EXEMPLE', prenom='Camille', email='camille@example.test',
                tel='0600000000', bts=SECURITY, statut='preinscription', slug_public='security',
                rentree_annee=2027, **values)


def test_validation_has_real_clickable_contacts_and_safe_personalization():
    html = mail_html('candidature_validee', program_code=SECURITY, prenom='Camille &lt;img src=x onerror=alert(1)&gt;')
    soup = BeautifulSoup(html, 'html.parser')
    assert 'Votre candidature est validée.' in soup.h1.text
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
    assert 'entretien' in email['html'] and 'entretien' in sms['body']
    assert 'Confirmez votre inscription' not in email['subject']
    assert 'BTS' not in email['subject'] and 'BTS' not in sms['body']
    assert '/confirm-inscription' not in email['html'] + sms['body']
    assert 'token_confirm' not in planned['changes']
    assert ('programmer votre entretien' in email['subject']) == (kind == 'remind')


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
    assert 'Écrire à Aurélie pour mon entretien' not in email['html']


def test_status_sends_exact_preview_once_and_keeps_history(client, monkeypatch):
    seed(2027, 'security', 'preinscription')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET bts=?,tel=? WHERE id=?', (SECURITY, '0600000000', 'security'))
    auth(client)
    client.get('/admin/candidat/security')
    with client.session_transaction() as session:
        headers = {'X-CSRF-Token': session['_candidate_message_csrf']}
    deliveries = []
    monkeypatch.setattr(application, 'send_mail', lambda *args, **kwargs: deliveries.append(('email', args, kwargs)) or 'email-id')
    monkeypatch.setattr(application, 'send_sms_brevo', lambda *args: deliveries.append(('sms', args, {})) or 'sms-id')
    data = {'id': 'security', 'value': 'validee'}
    preview = client.post('/admin/update-status', json={**data, 'preview': True}, headers=headers)
    assert preview.status_code == 200, preview.json
    assert not deliveries
    with application.db() as conn:
        assert conn.execute('SELECT statut FROM candidats WHERE id=?', ('security',)).fetchone()[0] == 'preinscription'
    confirmation = {**data, 'preview_token': preview.json['preview_token']}
    response = client.post('/admin/update-status', json=confirmation, headers=headers)
    assert response.status_code == 200 and response.json['sent'] == 2
    expected = preview.json['dossiers'][0]['messages'][0]
    assert deliveries[0][1] == (expected['recipient'], expected['subject'], expected['html'])
    assert deliveries[0][2]['reply_to'] == ADVISER['email']
    with application.db() as conn:
        saved = dict(conn.execute('SELECT * FROM candidats WHERE id=?', ('security',)).fetchone())
    assert saved['statut'] == 'validee' and not saved['token_confirm']
    assert client.post('/admin/update-status', json=confirmation, headers=headers).json['duplicate']
    assert len(deliveries) == 2
    assert prepare_workflow(saved, 'status', data)['messages'] == []
    logs = client.get('/admin/logs/security').json
    assert sum(event['type'] == 'MAIL_ENVOYE' for event in logs) == 1
    assert any('entretien' in str(event) for event in logs)
