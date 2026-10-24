"""Academy mail presentation and transport regressions; no real delivery."""
from html import unescape
from unittest.mock import Mock

import pytest

from branded_email import (BRAND_MARKER, brand_existing_email, email_plain_text,
                           render_branded_email, style_email_content)


def test_access_email_brand_is_inline_readable_and_safe(monkeypatch):
    monkeypatch.setenv('BASE_URL', 'https://school.example.test')
    link='https://school.example.test/formateur/mot-de-passe/secret-token?x=1&signature=abc'
    html=render_branded_email('Bienvenue <script>bad</script>', '<p>Votre accès est prêt.</p>',
        eyebrow='ESPACE FORMATEUR', accent_title='À vous de jouer.',
        action_url=link, action_label='Activer <mon espace>', security_note='Valable 72 heures & une seule fois.')
    assert html.count(BRAND_MARKER)==1
    assert 'https://school.example.test/static/academy-official-logo.png' in html
    assert 'width="240" height="72"' in html
    assert 'background:#202a26' in html
    assert 'Georgia' in html and 'font-style:italic' in html
    assert 'role="presentation"' in html and 'width="600"' in html
    assert 'mso-padding-alt:16px 25px' in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'Activer &lt;mon espace&gt;' in html
    assert link in unescape(html)
    assert 'Valable 72 heures &amp; une seule fois.' in html


def test_wrapper_is_idempotent_and_preserves_existing_signed_links():
    original='<p>Bonjour Camille.</p><p><a class="btn" href="https://school.example.test/confirm?token=abc&amp;sig=123">Confirmer</a></p>'
    once=brand_existing_email('Confirmation',original)
    assert brand_existing_email('Confirmation',once)==once
    assert once.count(BRAND_MARKER)==1
    assert 'https://school.example.test/confirm?token=abc&sig=123' in unescape(once)
    assert 'mso-padding-alt:15px 23px' in once


def test_legacy_document_does_not_nest_html_or_duplicate_old_logo():
    legacy='<!DOCTYPE html><html><head><style>badcss</style><title>Old</title></head><body><div class="header"><img src="old-logo.png">OLD BRAND</div><div><p>Votre dossier reste disponible.</p><a href="https://school.example.test/espace/secret">Ouvrir</a></div><div class="footer">OLD FOOTER</div></body></html>'
    result=brand_existing_email('Message',legacy)
    assert result.lower().count('<html ')==1
    assert result.count('<body ')==1
    assert 'old-logo.png' not in result and 'OLD BRAND' not in result
    assert 'badcss' not in result and 'OLD FOOTER' not in result
    assert 'Votre dossier reste disponible.' in result
    assert 'https://school.example.test/espace/secret' in result


def test_safe_fragment_removes_scripts_and_handlers_preserving_rich_content():
    result=style_email_content('<p onclick="bad()">Bonjour <strong>Camille</strong></p><script>secret()</script><a href="javascript:bad()">Non</a><a href="https://example.test/?x=1&amp;y=2">Oui</a>')
    assert '<strong>Camille</strong>' in result
    assert 'onclick' not in result and '<script>' not in result and 'secret()' not in result
    assert 'javascript:' not in result
    assert 'https://example.test/?x=1&y=2' in unescape(result)


def test_plain_text_keeps_action_link_and_has_no_html_or_css():
    link='https://school.example.test/espace/reinitialiser?token=secret'
    html=render_branded_email('Un nouveau mot de passe.', '<p>Tu as demandé à réinitialiser ton mot de passe.</p>',
        action_url=link, action_label='Choisir mon mot de passe', security_note='Ce lien est valable 30 minutes.')
    text=email_plain_text(html)
    assert 'Choisir mon mot de passe ('+link+')' in text
    assert '30 minutes' in text
    assert '<html' not in text and 'font-size:' not in text and '@media' not in text


@pytest.mark.parametrize('url',['javascript:alert(1)','//evil.test','file:///tmp/x','https://name:password@example.test/x'])
def test_action_urls_require_absolute_http_url_without_credentials(url):
    with pytest.raises(ValueError):
        render_branded_email('Test','<p>Texte</p>',action_url=url,action_label='Ouvrir')


def test_brevo_transport_brands_raw_mail_and_retains_attachment_and_copy_settings(monkeypatch,tmp_path):
    import utils
    monkeypatch.setattr(utils,'BREVO_KEY','fake-key-no-real-request')
    response=Mock(ok=True,text='{}')
    response.json.return_value={'messageId':'test-id'}
    post=Mock(return_value=response)
    monkeypatch.setattr(utils.requests,'post',post)
    path=tmp_path/'document.pdf';path.write_bytes(b'%PDF-1.4\n%%EOF')
    assert utils.send_mail('student@example.test','Bienvenue','<p>Message.</p>',attachments=[str(path)],copy_admin=False)=='test-id'
    data=post.call_args.kwargs['json']
    assert data['to']==[{'email':'student@example.test'}]
    assert BRAND_MARKER in data['htmlContent']
    assert '<p>' not in data['textContent'] and 'Message.' in data['textContent']
    assert data['attachment'][0]['name']=='document.pdf'
    assert data['attachment'][0]['content']
    utils.send_mail('student@example.test','Message','<p>Texte.</p>')
    assert {'email':'gestion@integraleacademy.com'} in post.call_args.kwargs['json']['to']


def test_smtp_has_html_and_plain_alternatives(monkeypatch):
    import utils
    server=Mock()
    monkeypatch.setattr(utils.smtplib,'SMTP',Mock(return_value=server))
    monkeypatch.setenv('MAIL_FROM','school@example.test')
    monkeypatch.setenv('MAIL_PASS','fake-local-test-value')
    assert utils.send_mail_gmail('admin@example.test','Alerte','<p>Vérifier le service.</p>') is True
    message=server.send_message.call_args.args[0]
    assert message.get_content_type()=='multipart/alternative'
    parts=message.get_payload()
    assert [part.get_content_type() for part in parts]==['text/plain','text/html']
    assert 'Vérifier le service.' in parts[0].get_payload(decode=True).decode()
    assert BRAND_MARKER in parts[1].get_payload(decode=True).decode()
