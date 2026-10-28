"""Admin-only personal messages with preview, CSRF and one-time delivery claims."""
import hashlib
import hmac
import io
import json
import re
import secrets
import tempfile
import time
from contextlib import closing
from pathlib import Path

from flask import jsonify, render_template, request, session
from PIL import Image
from werkzeug.utils import secure_filename
from school_email import SENDERS, LAYOUTS, DEFAULT_ACCENT, email_options, render_school_email


MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
PREVIEW_TTL = 15 * 60


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _csrf_token():
    if not session.get('_candidate_message_csrf'):
        session['_candidate_message_csrf'] = secrets.token_urlsafe(32)
    return session['_candidate_message_csrf']


def _equal(left, right):
    return isinstance(left, str) and isinstance(right, str) and hmac.compare_digest(left.encode(), right.encode())


def _schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS candidate_message_previews (
        token_hash TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
        session_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL, status TEXT NOT NULL,
        provider_id TEXT, created_at INTEGER NOT NULL
    )''')
    # A completed claim is retained beyond its preview lifetime to stop retries.
    conn.execute('DELETE FROM candidate_message_previews WHERE created_at < ?', (int(time.time()) - 7 * 86400,))
    conn.commit()


def _recipient(row, kind):
    if kind == 'email':
        recipient = str(row.get('email') or '').strip()
        if len(recipient) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', recipient):
            raise ValueError('Le dossier ne contient pas d’adresse e-mail valide.')
        return recipient
    recipient = re.sub(r'[\s().-]', '', str(row.get('tel') or ''))
    if recipient.startswith('00'):
        recipient = '+' + recipient[2:]
    elif re.fullmatch(r'0\d{9}', recipient):
        recipient = '+33' + recipient[1:]
    if not re.fullmatch(r'\+[1-9]\d{7,14}', recipient):
        raise ValueError('Le dossier ne contient pas de numéro de téléphone valide.')
    return recipient


def _attachments():
    uploads = [f for f in request.files.getlist('attachment') if f.filename]
    if len(uploads) > MAX_ATTACHMENTS:
        raise ValueError('Ajoutez au maximum 5 pièces jointes.')
    results, total, names = [], 0, set()
    for upload in uploads:
        name = secure_filename(upload.filename)
        ext = Path(name).suffix.lower()
        if not name or ext not in {'.pdf', '.jpg', '.jpeg', '.png'}:
            raise ValueError('Les pièces jointes doivent être des PDF, JPG ou PNG.')
        if name.lower() in names:
            raise ValueError('Chaque pièce jointe doit avoir un nom différent.')
        names.add(name.lower())
        content = upload.stream.read(MAX_ATTACHMENT_BYTES - total + 1)
        total += len(content)
        if total > MAX_ATTACHMENT_BYTES:
            raise ValueError('La taille totale des pièces jointes ne doit pas dépasser 10 Mo.')
        if ext == '.pdf':
            valid = content.startswith(b'%PDF-') and b'%%EOF' in content[-2048:]
        else:
            try:
                with Image.open(io.BytesIO(content)) as picture:
                    expected = {'PNG'} if ext == '.png' else {'JPEG', 'MPO'}
                    valid = picture.format in expected and picture.width * picture.height <= 40_000_000
                    picture.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                valid = False
        if not valid:
            raise ValueError('Le contenu d’une pièce jointe ne correspond pas à son format.')
        results.append((name, content))
    return results


def _payload(row, data):
    kind = data.get('type')
    if not isinstance(kind, str) or kind not in {'email', 'sms'}:
        raise ValueError('Choisissez un e-mail ou un SMS.')
    subject = str(data.get('subject') or '').strip() if kind == 'email' else ''
    body = str(data.get('body') or '').strip().replace('\r\n', '\n').replace('\r', '\n')
    if kind == 'email' and (not subject or len(subject) > 200 or '\n' in subject or '\r' in subject):
        raise ValueError('Renseignez un objet de 200 caractères maximum, sur une seule ligne.')
    maximum = 20000 if kind == 'email' else 1600
    if not body or len(body) > maximum or '\x00' in body:
        raise ValueError(f'Renseignez un message de {maximum} caractères maximum.')
    attachments = _attachments()
    if kind == 'sms' and attachments:
        raise ValueError('Un SMS ne peut pas contenir de pièce jointe.')
    recipient = _recipient(row, kind)
    envelope = dict(type=kind, recipient=recipient, subject=subject, body=body,
                    attachments=[(name, hashlib.sha256(content).hexdigest()) for name, content in attachments])
    if kind == 'email':
        envelope['email_options'] = email_options(data)
        envelope['sender'] = dict(SENDERS[envelope['email_options']['sender_id']])
    if data.get('template') == 'student_access' and kind == 'email':
        from branded_email import DEFAULT_BASE
        import os
        envelope['template'] = 'student_access'
        envelope['email_options']['action_url'] = os.getenv('BASE_URL', DEFAULT_BASE).rstrip('/') + '/espace/connexion'
        envelope['email_options']['action_label'] = 'Accéder à mon espace étudiant'
    digest = _hash(json.dumps(envelope, sort_keys=True, ensure_ascii=False))
    return envelope, attachments, digest


def _email_html(envelope):
    access = envelope.get('template') == 'student_access'
    return render_school_email(envelope['subject'], envelope['body'], **envelope['email_options'],
        security_note='Votre mot de passe personnel reste inchangé. Ne partagez jamais vos identifiants.' if access else '')[0]



def register_candidate_messages(app, db_connect, send_mail, send_sms, log_event):
    """Register without capturing app helpers, so callers may inject test transports."""
    @app.context_processor
    def _message_context():
        return {'candidate_message_csrf': _csrf_token, 'message_senders': SENDERS.values(),
                'message_layouts': LAYOUTS, 'message_default_accent': DEFAULT_ACCENT}

    def prepare(cid):
        if not session.get('admin_ok'):
            return None, None, (jsonify(ok=False, error='Veuillez vous connecter à l’administration.'), 403)
        data = request.get_json(silent=True) if request.is_json else request.form
        if not isinstance(data, dict) and not hasattr(data, 'get'):
            return None, None, (jsonify(ok=False, error='Requête invalide.'), 400)
        token = request.headers.get('X-CSRF-Token') or data.get('csrf_token')
        if not _equal(token, session.get('_candidate_message_csrf')):
            return None, None, (jsonify(ok=False, error='La session a expiré. Rechargez la fiche.'), 400)
        with closing(db_connect()) as conn:
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not row:
            return None, None, (jsonify(ok=False, error='Dossier introuvable.'), 404)
        return dict(row), data, None

    @app.post('/admin/candidat/<cid>/message-assistant')
    def admin_candidate_message_assistant(cid):
        row, data, error = prepare(cid)
        if error:
            return error
        from message_assistant import draft_response
        # Contact details, history, attachments and sensitive dossier fields stay out.
        context = {key: str(row.get(key) or '')[:120] for key in ('prenom', 'bts', 'mode')}
        return draft_response(app, db_connect, data, dict(type='individuel', etudiant=context))

    @app.post('/admin/candidat/<cid>/message-preview')
    def admin_candidate_message_preview(cid):
        row, data, error = prepare(cid)
        if error:
            return error
        try:
            envelope, attachments, digest = _payload(row, data)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        token, now = secrets.token_urlsafe(32), int(time.time())
        with closing(db_connect()) as conn:
            _schema(conn)
            # Bound pending previews per browser while leaving delivery claims intact.
            conn.execute("DELETE FROM candidate_message_previews WHERE session_hash=? AND status='ready' AND expires_at<?",
                         (_hash(_csrf_token()), now))
            conn.execute('INSERT INTO candidate_message_previews VALUES(?,?,?,?,?,?,?,?)',
                         (_hash(token), cid, _hash(_csrf_token()), digest, now + PREVIEW_TTL, 'ready', None, now))
            conn.commit()
        return jsonify(ok=True, recipient=envelope['recipient'], subject=envelope['subject'],
                       body=envelope['body'], html=_email_html(envelope) if envelope['type'] == 'email' else '',
                       attachments=[name for name, _ in attachments], sender=envelope.get('sender', {}), preview_token=token)

    @app.post('/admin/candidat/<cid>/message')
    def admin_candidate_message_send(cid):
        row, data, error = prepare(cid)
        if error:
            return error
        try:
            envelope, attachments, digest = _payload(row, data)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        token = data.get('preview_token')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,60}', token):
            return jsonify(ok=False, error='Prévisualisez le message avant de l’envoyer.'), 400
        with closing(db_connect()) as conn:
            _schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            record = conn.execute('SELECT * FROM candidate_message_previews WHERE token_hash=?', (_hash(token),)).fetchone()
            if (not record or record['candidate_id'] != cid or record['session_hash'] != _hash(_csrf_token())
                    or record['payload_hash'] != digest):
                return jsonify(ok=False, error='Le message a changé. Prévisualisez-le à nouveau.'), 400
            if record['status'] == 'sent':
                return jsonify(ok=True, message='Ce message a déjà été envoyé.', duplicate=True)
            if record['status'] != 'ready':
                return jsonify(ok=False, error='Cet envoi a déjà été lancé. Consultez l’historique avant de recommencer.'), 409
            if record['expires_at'] <= int(time.time()):
                return jsonify(ok=False, error='L’aperçu a expiré. Prévisualisez à nouveau le message.'), 400
            conn.execute("UPDATE candidate_message_previews SET status='sending' WHERE token_hash=?", (_hash(token),))
            conn.commit()
        provider_id = None
        try:
            if envelope['type'] == 'email':
                with tempfile.TemporaryDirectory(prefix='bts-message-') as folder:
                    paths = []
                    for name, content in attachments:
                        path = Path(folder) / name
                        path.write_bytes(content)
                        paths.append(str(path))
                    sender = envelope['sender']
                    provider_id = send_mail(envelope['recipient'], envelope['subject'], _email_html(envelope), attachments=paths,
                        sender_email=sender['email'], sender_name=sender['name']+' · Intégrale Academy', reply_to=sender['email'])
            else:
                provider_id = send_sms(envelope['recipient'], envelope['body'])
        except Exception:
            app.logger.exception('Candidate personal message delivery failed (%s)', envelope['type'])
        status = 'sent' if provider_id else 'failed'
        with closing(db_connect()) as conn:
            conn.execute('UPDATE candidate_message_previews SET status=?,provider_id=? WHERE token_hash=?',
                         (status, str(provider_id) if provider_id else None, _hash(token)))
            conn.commit()
        payload = {'destinataire': envelope['recipient'], 'objet': envelope['subject'],
                   'message': envelope['body'], 'pieces_jointes': [name for name, _ in attachments],
                   'message_id': str(provider_id) if provider_id else '', 'canal': envelope['type']}
        log_event(row, ('MAIL_ENVOYE' if envelope['type'] == 'email' else 'SMS_ENVOYE') if provider_id else 'MESSAGE_ECHEC', payload)
        if not provider_id:
            return jsonify(ok=False, error='L’envoi n’a pas été confirmé par le service de messagerie. Vérifiez l’historique avant de réessayer.'), 502
        return jsonify(ok=True, message='E-mail envoyé.' if envelope['type'] == 'email' else 'SMS envoyé.')

    @app.after_request
    def private_message_responses(response):
        if request.endpoint in {'admin_candidate_message_preview', 'admin_candidate_message_send', 'admin_candidate_message_assistant'}:
            response.headers['Cache-Control'] = 'no-store'
        return response
