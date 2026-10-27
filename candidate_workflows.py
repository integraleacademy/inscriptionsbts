"""Preview and confirm manual candidate notifications, including their effects.

    Previews never update a dossier or contact a transport. Confirmation sends
    the stored HTML/SMS/PDF bytes once, after checking the dossier is unchanged.
"""
from person_names import person_name
import base64
import io
import json
import secrets
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from flask import abort, jsonify, request, send_file, session, url_for

from branded_email import brand_existing_email
from campaign import candidate_year
from candidate_messages import _csrf_token, _equal, _hash, _recipient
from certificates import certificate_pdf
from mail_templates import mail_html
from sms_templates import sms_text
from utils import get_mail_context, make_signed_link, new_token


STATUSES = {'preinscription', 'validee', 'confirmee', 'reconf_en_cours', 'reconfirmee', 'annulee', 'docs_non_conformes'}
MAIL_TEMPLATES = {'candidature_validee': 'candidature_validee', 'inscription_confirmee': 'inscription_confirmee',
                  'reconfirmation': 'reconfirmation', 'reconfirmee': 'reconfirmation_validee', 'docs_non_conformes': 'docs_non_conformes'}
SMS_TEMPLATES = {**MAIL_TEMPLATES, 'reconfirmation': 'reconfirmation_demandee'}
REMIND_SUBJECTS = {'candidature_validee': 'Relance – Confirmez votre inscription BTS en alternance',
                   'reconfirmation': 'Relance – Reconfirmez votre inscription', 'docs_non_conformes': 'Relance – Documents à compléter'}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS candidate_workflow_previews (
        token_hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL, request_hash TEXT NOT NULL,
        payload TEXT NOT NULL, expires_at INTEGER NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL
    )''')
    conn.execute('DELETE FROM candidate_workflow_previews WHERE created_at<? OR (status=? AND expires_at<?)',
                 (int(time.time()) - 7*86400, 'ready', int(time.time())))
    conn.commit()


def prepare_workflow(row, kind, data):
    """Pure preparation: planned database changes are applied only on confirmation."""
    row = dict(row)
    item = dict(cid=row['id'], name=person_name(row.get('nom'),row.get('prenom')),
                snapshot=_hash(_json(row)), changes={}, messages=[], files=[], warnings=[])
    changes = item['changes']
    now = datetime.now()
    action = data.get('action', '')
    sms_template = None
    template = None
    subject = ''
    if kind == 'status':
        value = data.get('value')
        if value not in STATUSES:
            raise ValueError('Statut invalide.')
        if row.get('statut') == value:
            return item
        changes['statut'] = value
        if value in ('validee', 'confirmee', 'reconfirmee'):
            changes['date_' + value] = now.isoformat()
            changes['last_relance'] = None
        action = {'validee': 'candidature_validee', 'confirmee': 'inscription_confirmee', 'reconfirmee': 'reconfirmee'}.get(value)
        if not action:
            return item
        template, sms_template = MAIL_TEMPLATES[action], SMS_TEMPLATES[action]
        if value == 'reconfirmee':
            sms_template = None
        subject = {'validee': 'Votre candidature est validée – Confirmez votre inscription',
                   'confirmee': 'Inscription confirmée – Intégrale Academy', 'reconfirmee': 'Bienvenue à Intégrale Academy'}[value]
    elif kind == 'reconfirm':
        action = 'reconfirmation'
        template, sms_template = 'reconfirmation', 'reconfirmation_demandee'
        subject = 'Reconfirmation de votre inscription – Intégrale Academy'
        changes['statut'] = 'reconf_en_cours'
    elif kind in ('resend', 'remind'):
        if action not in (REMIND_SUBJECTS if kind == 'remind' else MAIL_TEMPLATES):
            raise ValueError('Message non reconnu.')
        template = 'relance_' + action if kind == 'remind' else MAIL_TEMPLATES[action]
        sms_template = template if kind == 'remind' else SMS_TEMPLATES[action]
        subject = REMIND_SUBJECTS[action] if kind == 'remind' else 'Intégrale Academy – ' + template.replace('_', ' ').capitalize()
        if kind == 'remind':
            changes['last_relance'] = now.isoformat()
    elif kind == 'notify':
        action, template, sms_template = 'docs_non_conformes', 'docs_non_conformes', 'docs_non_conformes'
        subject = 'Documents non conformes – Intégrale Academy'
        changes['statut'] = 'docs_non_conformes'
    elif kind == 'aps':
        if row.get('bts') != 'MOS':
            raise ValueError('Ce message concerne le BTS MOS.')
        template, subject = 'demande_aps', 'Formation APS – Documents CNAPS à envoyer'
    elif kind == 'certificate':
        presentiel = row.get('mode') == 'presentiel'
        template = 'certificat_presentiel' if presentiel else 'certificat'
        mode = 'Présentiel' if presentiel else 'Distanciel'
        year = candidate_year(row)
        subject = f"Votre certificat de scolarité – BTS {row.get('bts')} · {mode} · {year}-{year+2}"
        pdf = certificate_pdf(row)
        item['files'] = [{'name': f'Certificat_scolarite_{row["id"]}_{row["mode"]}.pdf',
                          'content': base64.b64encode(pdf).decode('ascii')}]
    else:
        raise ValueError('Action non reconnue.')

    ctx = get_mail_context(row)
    if action in ('candidature_validee', 'reconfirmation', 'docs_non_conformes'):
        field, route, days = {
            'candidature_validee': ('token_confirm', '/confirm-inscription', 30),
            'reconfirmation': ('token_reconfirm', '/reconfirm-page', 15),
            'docs_non_conformes': ('replace_token', '/replace-files', 15),
        }[action]
        token = row.get(field)
        expiry = row.get(field + '_exp')
        try:
            valid = bool(token and expiry and datetime.fromisoformat(expiry) > now)
        except (ValueError, TypeError):
            valid = False
        if not valid or kind in ('notify', 'reconfirm'):
            token = new_token()
            changes.update({field: token, field + '_exp': (now + timedelta(days=days)).isoformat()})
        link = make_signed_link(route, token)
        if action == 'candidature_validee':
            ctx['lien_confirmation'] = link
        if kind == 'remind' or action != 'candidature_validee':
            ctx['lien_espace'] = link
        if action == 'docs_non_conformes':
            try:
                verif = json.loads(row.get('verif_docs') or '{}')
            except (ValueError, TypeError):
                verif = {}
            pieces = [f"{value.get('label') or 'Pièce justificative'} – {name}" for name, value in verif.items()
                      if isinstance(value, dict) and value.get('etat') == 'non_conforme']
            if not pieces:
                raise ValueError('Aucune pièce non conforme à demander.')
            comment = str(data.get('commentaire') or '').strip()
            if len(comment) > 5000:
                raise ValueError('Limitez les précisions à 5 000 caractères.')
            changes['replace_meta'] = _json({'pieces': pieces, 'commentaire': comment})
    if kind == 'aps':
        ctx.update(aps_session=row.get('aps_session') or '', lien_espace='https://cnapsv5-1.onrender.com/')
    safe_ctx = {key: escape(value, quote=True) if isinstance(value, str) else value for key, value in ctx.items()}
    html = mail_html(template, **safe_ctx)
    if action == 'docs_non_conformes':
        # Include the actual requested documents and administrator's explanation.
        details = '<h3>Pièces à remplacer</h3><ul>' + ''.join('<li>' + escape(p) + '</li>' for p in pieces) + '</ul>'
        if comment:
            details += '<p>' + escape(comment).replace('\n', '<br>') + '</p>'
        html = html.replace('</body>', details + '</body>')
    item['messages'].append(dict(type='email', recipient=_recipient(row, 'email'), subject=subject,
                                 html=brand_existing_email(subject, html), copy='gestion@integraleacademy.com'))
    if sms_template:
        if not str(row.get('tel') or '').strip():
            item['warnings'].append('Téléphone absent : seul l’e-mail sera envoyé.')
        else:
            body = sms_text(sms_template, prenom=ctx['prenom'], bts_label=ctx['bts_label'],
                            lien_espace=ctx['lien_espace'], lien_confirmation=ctx['lien_confirmation'])
            item['messages'].append(dict(type='sms', recipient=_recipient(row, 'sms'), body=body))
    return item


def register_candidate_workflows(app, db_connect, send_mail, send_sms, log_event, campaign_rows):
    def guard():
        if not session.get('admin_ok'):
            abort(403)

    @app.get('/admin/message-preview/<token>/document/<int:index>')
    def admin_workflow_document(token, index):
        guard()
        with closing(db_connect()) as conn:
            _schema(conn)
            record = conn.execute('SELECT * FROM candidate_workflow_previews WHERE token_hash=?', (_hash(token),)).fetchone()
        if not record or record['expires_at'] <= int(time.time()) or record['session_hash'] != _hash(_csrf_token()):
            abort(404)
        payload = json.loads(record['payload'])
        files = [file for item in payload for file in item['files']]
        if index < 0 or index >= len(files):
            abort(404)
        file = files[index]
        response = send_file(io.BytesIO(base64.b64decode(file['content'])), mimetype='application/pdf',
                             download_name=file['name'], as_attachment=request.args.get('download') == '1')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def response(kind, cid=None):
        guard()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(ok=False, error='Prévisualisez le message avant de confirmer son envoi.'), 400
        if not _equal(request.headers.get('X-CSRF-Token') or data.get('csrf_token'), session.get('_candidate_message_csrf')):
            return jsonify(ok=False, error='La session a expiré. Rechargez la page.'), 400
        input_data = {key: value for key, value in data.items() if key not in ('preview', 'preview_token', 'csrf_token')}
        request_key = [kind, cid, input_data, request.args.get('rentree')]
        if kind == 'certificate':
            request_key.append('original-word-model-v1')
        request_hash = _hash(_json(request_key))
        owner = _hash(_csrf_token())
        if data.get('preview') is True:
            try:
                if kind in ('bulk-remind', 'bulk-reconfirm'):
                    rows = campaign_rows('validee' if kind == 'bulk-remind' else 'confirmee')
                    action_kind = 'remind' if kind == 'bulk-remind' else 'reconfirm'
                    action_data = {'action': 'candidature_validee'} if kind == 'bulk-remind' else {}
                else:
                    with closing(db_connect()) as conn:
                        row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid or data.get('id'),)).fetchone()
                    rows = [dict(row)] if row else []
                    action_kind, action_data = kind, data
                if not rows:
                    return jsonify(ok=False, error='Aucun dossier concerné.'), 404
                payload = [prepare_workflow(row, action_kind, action_data) for row in rows]
            except ValueError as exc:
                return jsonify(ok=False, error=str(exc)), 400
            token, now = secrets.token_urlsafe(32), int(time.time())
            with closing(db_connect()) as conn:
                _schema(conn)
                conn.execute('INSERT INTO candidate_workflow_previews VALUES(?,?,?,?,?,?,?)',
                             (_hash(token), owner, request_hash, _json(payload), now+900, 'ready', now))
                conn.commit()
            public, index = [], 0
            for item in payload:
                files = []
                for file in item['files']:
                    files.append({'name': file['name'], 'url': url_for('admin_workflow_document', token=token, index=index)})
                    index += 1
                public.append({'name': item['name'], 'messages': item['messages'], 'files': files,
                               'warnings': item['warnings'], 'statut': item['changes'].get('statut')})
            return jsonify(ok=True, preview_token=token, dossiers=public)
        token = data.get('preview_token')
        if not isinstance(token, str) or len(token) > 100:
            return jsonify(ok=False, error='Prévisualisez les messages avant de confirmer.'), 400
        with closing(db_connect()) as conn:
            _schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            record = conn.execute('SELECT * FROM candidate_workflow_previews WHERE token_hash=?', (_hash(token),)).fetchone()
            if not record or record['session_hash'] != owner or record['request_hash'] != request_hash:
                return jsonify(ok=False, error='L’action a changé. Prévisualisez à nouveau.'), 400
            if record['status'] == 'sent':
                return jsonify(ok=True, duplicate=True, message='Cet envoi a déjà été effectué.')
            if record['status'] != 'ready':
                return jsonify(ok=False, error='Cet envoi a déjà été lancé. Consultez l’historique avant de recommencer.'), 409
            if record['expires_at'] <= int(time.time()):
                return jsonify(ok=False, error='L’aperçu a expiré. Prévisualisez à nouveau.'), 400
            payload = json.loads(record['payload'])
            for item in payload:
                current = conn.execute('SELECT * FROM candidats WHERE id=?', (item['cid'],)).fetchone()
                if not current or item['snapshot'] != _hash(_json(dict(current))):
                    return jsonify(ok=False, error='Un dossier a changé depuis l’aperçu. Prévisualisez à nouveau.'), 409
            conn.execute("UPDATE candidate_workflow_previews SET status='sending' WHERE token_hash=?", (_hash(token),))
            for item in payload:
                changes = item['changes']
                if changes:
                    conn.execute('UPDATE candidats SET ' + ','.join(key+'=?' for key in changes) + ',updated_at=? WHERE id=?',
                                 [*changes.values(), datetime.now().isoformat(), item['cid']])
            conn.commit()
        errors, sent = [], 0
        for item in payload:
            row = {'id': item['cid']}
            if 'statut' in item['changes']:
                log_event(row, 'STATUT_CHANGE', {'statut': item['changes']['statut']})
            for message in item['messages']:
                provider_id = None
                try:
                    if message['type'] == 'email':
                        with tempfile.TemporaryDirectory(prefix='bts-certificate-') as folder:
                            paths = []
                            for file in item['files']:
                                path = Path(folder) / Path(file['name']).name
                                path.write_bytes(base64.b64decode(file['content']))
                                paths.append(str(path))
                            provider_id = send_mail(message['recipient'], message['subject'], message['html'], attachments=paths)
                    else:
                        provider_id = send_sms(message['recipient'], message['body'])
                except Exception:
                    app.logger.exception('Manual candidate notification failed (%s)', message['type'])
                event = ('MAIL_ENVOYE' if message['type'] == 'email' else 'SMS_ENVOYE') if provider_id else 'MESSAGE_ECHEC'
                log_event(row, event, {'type': kind, 'destinataire': message['recipient'], 'objet': message.get('subject', ''),
                                       'message': message.get('body', ''), 'message_id': str(provider_id or ''),
                                       'pieces_jointes': [file['name'] for file in item['files']]})
                if not provider_id:
                    errors.append(f"{item['name']} : {message['type']}")
                else:
                    sent += 1
            if kind in ('remind', 'bulk-remind'):
                log_event(row, 'RELANCE_ENVOYEE', {'envois_confirmes': sent, 'echecs': errors})
        with closing(db_connect()) as conn:
            conn.execute('UPDATE candidate_workflow_previews SET status=? WHERE token_hash=?', ('failed' if errors else 'sent', _hash(token)))
            conn.commit()
        if errors:
            return jsonify(ok=False, error=f"{sent} envoi(s) confirmé(s). Échec : " + ', '.join(errors) + '. Consultez l’historique avant de réessayer.', sent=sent), 502
        return jsonify(ok=True, sent=sent, statut=data.get('value'), message='Action effectuée.' if not sent else 'Envoi confirmé.')

    @app.after_request
    def private_workflows(result):
        if request.endpoint == 'admin_workflow_document' or (request.is_json and isinstance(request.get_json(silent=True), dict) and ('preview' in request.json or 'preview_token' in request.json)):
            result.headers['Cache-Control'] = 'private, no-store'
        return result

    return response
