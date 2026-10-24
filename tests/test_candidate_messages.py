"""Personal messaging tests: every transport is an in-memory stub."""
import io
import sqlite3
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image

from candidate_messages import register_candidate_messages


@pytest.fixture
def messaging(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'))
    app.secret_key = 'test-messaging-only'
    app.testing = True
    database = tmp_path / 'messages.sqlite'

    def db():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY, nom TEXT, email TEXT, tel TEXT, numero_dossier TEXT)')
        conn.executemany('INSERT INTO candidats VALUES(?,?,?,?,?)', [
            ('one', 'TEST', 'student@example.test', '06 12 34 56 78', '2027TEST'),
            ('two', 'OTHER', 'other@example.test', '+33687654321', '2027OTHER')])
    deliveries, logs = [], []
    transport = {'success': True, 'raises': False}

    def mail(to, subject, html, attachments=None):
        deliveries.append({'type': 'email', 'to': to, 'subject': subject, 'html': html,
                           'attachments': [(Path(path).name, Path(path).read_bytes()) for path in attachments or []]})
        if transport['raises']:
            raise RuntimeError('Fake provider outage')
        return 'test-mail-id' if transport['success'] else False

    def sms(to, body):
        deliveries.append({'type': 'sms', 'to': to, 'body': body})
        return 'test-sms-id' if transport['success'] else False

    register_candidate_messages(app, db, mail, sms, lambda *args: logs.append(args))
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin_ok'] = True
        state['_candidate_message_csrf'] = 'test-csrf'
    return client, db, deliveries, logs, transport


def fields(**extra):
    result = {'type': 'email', 'subject': 'Votre formation', 'body': 'Bonjour,\n\nVotre prochain cours approche.', 'csrf_token': 'test-csrf'}
    result.update(extra)
    return result


def preview(client, **extra):
    return client.post('/admin/candidat/one/message-preview', data=fields(**extra))


def send(client, token, **extra):
    return client.post('/admin/candidat/one/message', data=fields(preview_token=token, **extra))


def test_preview_never_sends_and_html_is_escaped(messaging):
    client, _, deliveries, _, _ = messaging
    response = preview(client, body='<script>alert(1)</script>\nBonjour & bienvenue')
    assert response.status_code == 200
    assert not deliveries
    assert response.json['recipient'] == 'student@example.test'
    assert '<script>' not in response.json['html']
    assert '&lt;script&gt;' in response.json['html']
    assert 'background:#202a26' in response.json['html']
    assert 'width="240"' in response.json['html']
    assert 'width:240px;' in response.json['html']
    assert 'color:#ffffff;' in response.json['html']
    assert response.headers['Cache-Control'] == 'no-store'


def test_only_authenticated_admin_with_csrf_can_preview_or_send(messaging):
    client, _, deliveries, _, _ = messaging
    assert preview(client, csrf_token='invalid').status_code == 400
    assert preview(client, csrf_token='é').status_code == 400
    with client.session_transaction() as state:
        state['admin_ok'] = False
    assert preview(client).status_code == 403
    assert send(client, 'x' * 43).status_code == 403
    assert not deliveries


def test_send_binds_recipient_to_dossier_and_is_idempotent(messaging):
    client, db, deliveries, logs, _ = messaging
    token = preview(client, recipient='attacker@example.test').json['preview_token']
    result = send(client, token, recipient='attacker@example.test')
    assert result.status_code == 200 and result.json['ok']
    assert deliveries[0]['to'] == 'student@example.test'
    assert logs[0][1] == 'MAIL_ENVOYE'
    assert logs[0][2]['message_id'] == 'test-mail-id'
    assert send(client, token).json['duplicate']
    assert len(deliveries) == 1
    with db() as conn:
        assert conn.execute('SELECT status FROM candidate_message_previews').fetchone()[0] == 'sent'


def test_sms_uses_normalized_phone_and_logs_message(messaging):
    client, _, deliveries, logs, _ = messaging
    token = preview(client, type='sms', body='À demain !').json['preview_token']
    assert send(client, token, type='sms', body='À demain !').status_code == 200
    assert deliveries == [{'type': 'sms', 'to': '+33612345678', 'body': 'À demain !'}]
    assert logs[0][1] == 'SMS_ENVOYE'


def test_send_requires_unmodified_current_preview(messaging):
    client, db, deliveries, _, _ = messaging
    assert send(client, '').status_code == 400
    token = preview(client).json['preview_token']
    assert send(client, token, body='changed').status_code == 400
    assert client.post('/admin/candidat/two/message', data=fields(preview_token=token)).status_code == 400
    with db() as conn:
        conn.execute("UPDATE candidats SET email='new@example.test' WHERE id='one'")
    assert send(client, token).status_code == 400
    assert not deliveries


def test_preview_is_session_bound_and_expires(messaging):
    client, db, deliveries, _, _ = messaging
    token = preview(client).json['preview_token']
    with client.session_transaction() as state:
        state['_candidate_message_csrf'] = 'new-csrf'
    assert send(client, token, csrf_token='new-csrf').status_code == 400
    with client.session_transaction() as state:
        state['_candidate_message_csrf'] = 'test-csrf'
    with db() as conn:
        conn.execute('UPDATE candidate_message_previews SET expires_at=0')
    assert send(client, token).status_code == 400
    assert not deliveries


def test_failed_delivery_never_reports_success_and_same_token_is_not_retried(messaging):
    client, _, deliveries, logs, transport = messaging
    transport['success'] = False
    token = preview(client).json['preview_token']
    assert send(client, token).status_code == 502
    assert logs[0][1] == 'MESSAGE_ECHEC'
    assert send(client, token).status_code == 409
    assert len(deliveries) == 1


def test_transport_exception_has_same_failure_semantics(messaging):
    client, _, deliveries, logs, transport = messaging
    transport['raises'] = True
    token = preview(client).json['preview_token']
    assert send(client, token).status_code == 502
    assert logs[0][1] == 'MESSAGE_ECHEC'
    assert len(deliveries) == 1


def test_attachments_checked_in_preview_bound_to_send_and_cleaned(messaging):
    client, _, deliveries, _, _ = messaging
    pdf = b'%PDF-1.4\ncontent\n%%EOF'
    token = preview(client, attachment=(io.BytesIO(pdf), 'cours.pdf')).json['preview_token']
    assert send(client, token, attachment=(io.BytesIO(pdf + b'changed'), 'cours.pdf')).status_code == 400
    assert send(client, token, attachment=(io.BytesIO(pdf), 'cours.pdf')).status_code == 200
    assert deliveries[0]['attachments'] == [('cours.pdf', pdf)]


def test_reject_disguised_files_excess_size_count_and_sms_attachments(messaging):
    client, _, deliveries, _, _ = messaging
    assert preview(client, attachment=(io.BytesIO(b'<html>bad</html>'), 'bad.pdf')).status_code == 400
    assert preview(client, attachment=(io.BytesIO(b'fake image'), 'bad.png')).status_code == 400
    assert preview(client, attachment=(io.BytesIO(b'<svg/>'), 'bad.svg')).status_code == 400
    assert preview(client, attachment=(io.BytesIO(b'%PDF-' + b'x' * (10 * 1024 * 1024) + b'%%EOF'), 'big.pdf')).status_code == 400
    assert preview(client, attachment=[(io.BytesIO(b'%PDF-1.4\n%%EOF'), f'{i}.pdf') for i in range(6)]).status_code == 400
    assert preview(client, type='sms', attachment=(io.BytesIO(b'%PDF-1.4\n%%EOF'), 'note.pdf')).status_code == 400
    assert not deliveries


def test_valid_image_attachment_and_invalid_fields(messaging):
    client, _, deliveries, _, _ = messaging
    photo = io.BytesIO()
    Image.new('RGB', (2, 2)).save(photo, format='PNG')
    photo.seek(0)
    assert preview(client, attachment=(photo, 'image.png')).status_code == 200
    assert preview(client, type='fax').status_code == 400
    assert preview(client, body='').status_code == 400
    assert preview(client, subject='Bad\nHeader').status_code == 400
    assert preview(client, type='sms', body='x' * 1601).status_code == 400
    assert not deliveries


def test_json_preview_supported_and_missing_contact_is_explicit(messaging):
    client, db, deliveries, _, _ = messaging
    assert client.post('/admin/candidat/one/message-preview', json=fields()).status_code == 200
    with db() as conn:
        conn.execute("UPDATE candidats SET email='',tel='' WHERE id='one'")
    assert preview(client).status_code == 400
    assert preview(client, type='sms').status_code == 400
    assert not deliveries
