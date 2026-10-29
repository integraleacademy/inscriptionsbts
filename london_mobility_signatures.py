"""Candidate-owned Yousign requests, checkpointed before each remote mutation.

Only an explicit administrator send authorizes activation. One-click requests
persist that authorization so their worker can recover after a restart.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

import requests
from flask import abort, current_app, has_app_context, jsonify, request
from pypdf import PdfReader

from london_mobility_documents import minor_at_signing

ACTIVE = {'preparing', 'draft', 'ongoing', 'uncertain', 'approval', 'paused', 'done', 'unknown'}
CLOSED = {'canceled', 'expired', 'deleted', 'declined', 'rejected'}
LABELS = {'preparing':'Préparation', 'draft':'Envoi à terminer', 'ongoing':'Signatures en cours',
          'uncertain':'Opération à vérifier', 'approval':'Validation en cours', 'paused':'En pause',
          'done':'Archivage en cours', 'completed':'Convention signée', 'unknown':'À vérifier',
          'canceled':'Demande annulée', 'expired':'Demande expirée', 'deleted':'Brouillon annulé',
          'declined':'Signature refusée', 'rejected':'Demande refusée'}
SIGNER_LABELS = {'initiated':'En attente d’envoi', 'notified':'Invitation envoyée', 'processing':'Signature en cours',
                 'signed':'Signé', 'declined':'Refusé', 'error':'À vérifier', 'aborted':'Interrompu'}
ROLES = {'employer':'Entreprise', 'apprentice':'Apprenti', 'guardian':'Représentant légal'}


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def signature_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS london_mobility_signatures (
        id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, version_id TEXT NOT NULL,
        status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS london_signatures_candidate ON london_mobility_signatures(candidate_id,created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS london_signatures_status ON london_mobility_signatures(status,updated_at)')
    conn.execute('''CREATE TABLE IF NOT EXISTS london_mobility_notifications (
        version_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
        created_at TEXT NOT NULL, read_at TEXT)''')


def active_signature(conn, cid):
    return conn.execute('SELECT id FROM london_mobility_signatures WHERE candidate_id=? AND status IN (' +
                        ','.join('?' for _ in ACTIVE) + ') LIMIT 1', (cid, *ACTIVE)).fetchone()


def configuration():
    env = (os.getenv('YOUSIGN_ENV') or os.getenv('YOUSIGN_ENVIRONMENT') or 'production').strip().lower()
    base = (os.getenv('YOUSIGN_BASE_URL') or ('https://api-sandbox.yousign.app/v3' if env == 'sandbox' else 'https://api.yousign.app/v3')).rstrip('/')
    valid = base in {'https://api.yousign.app/v3', 'https://api-sandbox.yousign.app/v3'}
    valid = valid and (('sandbox' in base) == (env == 'sandbox'))
    return bool(os.getenv('YOUSIGN_API_KEY', '').strip()) and valid, base, env


def signature_context(conn, row, versions):
    configured, _, environment = configuration()
    configured = configured or (has_app_context() and bool(current_app.config.get('LONDON_YOUSIGN_CLIENT_FACTORY')))
    attempts = [json.loads(r['payload']) for r in conn.execute(
        'SELECT payload FROM london_mobility_signatures WHERE candidate_id=? ORDER BY created_at DESC', (row['id'],))]
    previous_employer = next((p for a in attempts for p in a['recipients'] if p['role'] == 'employer'), {})
    for version in versions:
        attempt = next((a for a in attempts if a['version_id'] == version['id']), None)
        version['signature'] = public_state(attempt) if attempt else None
        version['minor'] = minor_at_signing(version['signing_snapshot'])
        version['can_send'] = not version['signed_id'] and not version['stale'] and not active_signature(conn, row['id'])
    return {'configured': configured, 'sandbox': environment == 'sandbox', 'employer': previous_employer,
            'apprentice_email': row.get('email') or '', 'guardian_email': row.get('resp_email') or '',
            'active': bool(active_signature(conn, row['id']))}


def public_state(state):
    people = []
    for person in state['recipients']:
        tracked = state.get('signers', {}).get(person['role'], {})
        people.append({**person, 'label': ROLES[person['role']], 'status': tracked.get('status', 'initiated'),
                       'status_label': SIGNER_LABELS.get(tracked.get('status', 'initiated'), 'En attente'),
                       'can_remind': state['status'] == 'ongoing' and tracked.get('status') == 'notified'})
    visible = {k: state.get(k) for k in ('id', 'version_id', 'status', 'error', 'sent_at', 'completed_at', 'checked_at', 'pending', 'automatic', 'authentication_mode')}
    visible.update(label=LABELS.get(state['status'], 'À vérifier'), recipients=people,
                   active=state['status'] in ACTIVE,
                   can_resume=state['status'] in {'preparing','draft'} and not state.get('pending'),
                   can_cancel=state['status'] in ACTIVE - {'done'},
                   needs_refresh=state['status'] in ACTIVE)
    # Ignore polling timestamps so a background check never reloads a form being edited.
    visible['etag'] = hashlib.sha256(dumps({k:v for k,v in visible.items() if k != 'checked_at'}).encode()).hexdigest()
    return visible


class SignatureError(ValueError):
    def __init__(self, message, ambiguous=False, status_code=None):
        super().__init__(message)
        self.ambiguous = ambiguous
        self.status_code = status_code


def identifier(value):
    value = str(value or '')
    if not re.fullmatch(r'[a-fA-F0-9-]{36}', value):
        raise SignatureError('Yousign a renvoyé un identifiant inattendu. Actualisez le suivi.', True)
    return value


def items(value):
    return value if isinstance(value, list) else value.get('data', []) if isinstance(value, dict) else []


class YousignClient:
    def __init__(self):
        configured, self.base, _ = configuration()
        if not configured:
            raise SignatureError('La connexion Yousign doit être configurée sur Inscriptions BTS avant l’envoi.')
        self.key = os.environ['YOUSIGN_API_KEY'].strip()

    def call(self, method, path, *, binary=False, **kwargs):
        try:
            response = requests.request(method, self.base + path, headers={
                'Authorization': 'Bearer ' + self.key, 'Accept': 'application/pdf' if binary else 'application/json'},
                timeout=(10, 40), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise SignatureError('Yousign n’a pas confirmé l’opération. Actualisez le suivi avant de réessayer.', method != 'GET') from None
        if not 200 <= response.status_code < 300:
            message = ('Yousign a refusé la connexion. Vérifiez la clé API et ses droits.' if response.status_code in {401,403}
                       else 'Yousign limite temporairement les demandes. Réessayez dans quelques minutes.' if response.status_code == 429
                       else 'Yousign a refusé la demande. Vérifiez les coordonnées et la configuration du compte.' if response.status_code < 500
                       else 'Yousign est temporairement indisponible. Actualisez le suivi avant de réessayer.')
            raise SignatureError(message, method != 'GET' and (response.status_code >= 500 or response.status_code in {408,429}), response.status_code)
        if binary: return response.content
        try:
            return response.json() if response.content else {}
        except ValueError:
            raise SignatureError('La réponse Yousign est illisible. Actualisez le suivi.', method != 'GET') from None


def recipients_for(data, raw):
    people = [dict(role='employer', first_name=raw.get('employer_first_name'), last_name=raw.get('employer_last_name'), email=raw.get('employer_email')),
              dict(role='apprentice', first_name=data['apprentice_first_name'], last_name=data['apprentice_last_name'], email=raw.get('apprentice_email'))]
    if minor_at_signing(data):
        people.append(dict(role='guardian', first_name=data['guardian_first_name'], last_name=data['guardian_last_name'], email=raw.get('guardian_email')))
    for person in people:
        from london_mobility_data import mobile
        try: person['phone_number'] = mobile(raw.get(person['role'] + '_phone'))
        except ValueError: raise SignatureError('Vérifiez le mobile du signataire « ' + ROLES[person['role']] + ' » pour le code SMS.') from None
        for key in ('first_name','last_name','email'):
            person[key] = str(person[key] or '').strip()
            if not person[key] or len(person[key]) > (254 if key == 'email' else 100):
                raise SignatureError('Complétez le prénom, le nom et l’e-mail du signataire « ' + ROLES[person['role']] + ' ».')
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', person['email']):
            raise SignatureError('Vérifiez l’e-mail du signataire « ' + ROLES[person['role']] + ' ».')
    if len({p['email'].casefold() for p in people}) != len(people):
        raise SignatureError('Chaque signataire doit utiliser une adresse e-mail distincte pour son invitation.')
    if len({p['phone_number'] for p in people}) != len(people):
        raise SignatureError('Chaque signataire doit utiliser son propre mobile pour recevoir son code SMS.')
    return people


def signature_fields(data):
    if data.get('version') == 'london-20261029-2':
        from london_mobility_documents import signature_layout
        return signature_layout(data)
    manifest = json.loads((Path(__file__).parent / 'assets/london_mobility/manifest.json').read_text())
    variant = manifest['minor' if minor_at_signing(data) else 'adult']
    names = {'company_signature':'employer', 'beneficiary_signature':'apprentice', 'guardian':'guardian'}
    return {names[f['name']]: dict(type='signature', page=f['page'] + 1, x=round(f['x']),
            y=round(f['baseline'] + (f['lines'] - 1) * f['leading'] + 8), width=180, height=45)
            for f in variant['fields'] if f['name'] in names}


class SignatureService:
    def __init__(self, app, connect, directory, store_file, log_event):
        self.app, self.connect, self.directory = app, connect, directory
        self.store_file, self.log_event = store_file, log_event

    def api(self):
        factory = self.app.config.get('LONDON_YOUSIGN_CLIENT_FACTORY', YousignClient)
        return factory()

    @contextmanager
    def lock(self, cid):
        root = Path(self.directory()) / '.signature-locks'; root.mkdir(parents=True, exist_ok=True)
        path = root / hashlib.sha256(cid.encode()).hexdigest()
        with path.open('a') as handle:
            path.chmod(0o600)
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise SignatureError('Une opération est déjà en cours. Actualisez le suivi dans quelques instants.') from None
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)

    def save(self, state):
        with closing(self.connect()) as conn:
            conn.execute('UPDATE london_mobility_signatures SET status=?,payload=?,updated_at=? WHERE id=?',
                         (state['status'], dumps(state), now(), state['id']))
            conn.commit()

    def load(self, cid, vid, aid):
        with closing(self.connect()) as conn:
            found = conn.execute('SELECT payload FROM london_mobility_signatures WHERE id=? AND candidate_id=? AND version_id=?', (aid,cid,vid)).fetchone()
        if not found: abort(404)
        return json.loads(found[0])

    def begin(self, cid, vid, raw, *, automatic=False):
        from london_mobility import current_settings, digest, snapshot, source_fingerprint
        # Instantiate first: missing configuration must not lock a version in a draft.
        self.api()
        if not automatic and raw.get('reviewed') != 'yes':
            raise SignatureError('Relisez le PDF et confirmez les destinataires avant l’envoi.')
        with closing(self.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
            version = conn.execute('SELECT * FROM london_mobility_versions WHERE id=? AND candidate_id=?', (vid,cid)).fetchone()
            if not row or not version: abort(404)
            row, version = dict(row), dict(version)
            trip = conn.execute('SELECT statut FROM voyage_londres_inscriptions WHERE candidat_id=?', (cid,)).fetchone()
            if row['mode'] != 'presentiel' or not trip or trip['statut'] != 'active':
                raise SignatureError('Le candidat doit être en présentiel et son inscription au voyage active.')
            if version['signed_id']: raise SignatureError('Cette convention est déjà signée.')
            if active_signature(conn, cid): raise SignatureError('Une demande existe déjà. Consultez son suivi avant tout nouvel envoi.')
            latest = conn.execute('SELECT id FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1', (cid,)).fetchone()
            data = json.loads(version['snapshot'])
            if automatic:
                from london_mobility_data import automatic_data
                resolved = automatic_data(conn, row, convention_date=data['convention_date'])
                if not resolved['ready']: raise SignatureError(resolved['issues'][0]['message'])
                current = digest(resolved['snapshot'])
            else:
                values, _, _, selected, _ = current_settings(conn, row)
                current = digest(snapshot(row, values, selected))
            if latest['id'] != vid or current != version['fingerprint']:
                raise SignatureError('Les informations ont changé. Générez et relisez la nouvelle version avant l’envoi.')
            if not automatic and raw.get('source_fingerprint') != source_fingerprint(conn, row):
                raise SignatureError('La fiche a changé. Rechargez-la pour vérifier les destinataires.')
            aid = secrets.token_hex(16); created = now()
            state = dict(id=aid,candidate_id=cid,version_id=vid,status='preparing',created_at=created,
                         external_id='london-' + aid,recipients=resolved['recipients'] if automatic else recipients_for(data, raw),fields=signature_fields(data),signers={},
                         automatic=automatic,authentication_mode='otp_sms',
                         pdf_hash=version['pdf_hash'], document_name='convention-londres-' + vid + '.pdf')
            if automatic:
                state.update(source_hash=resolved['fingerprint'],convention_date=data['convention_date'])
            self.original(conn, state)
            conn.execute('INSERT INTO london_mobility_signatures VALUES(?,?,?,?,?,?,?)', (aid,cid,vid,state['status'],dumps(state),created,created))
            conn.commit()
        return state

    def original(self, conn, state):
        found = conn.execute('''SELECT d.nom_stockage,v.pdf_hash FROM london_mobility_versions v
            JOIN voyage_londres_documents d ON d.id=v.pdf_id WHERE v.id=? AND v.candidate_id=?''',
                             (state['version_id'],state['candidate_id'])).fetchone()
        if not found: raise SignatureError('La convention originale est introuvable.')
        path = Path(self.directory()) / found['nom_stockage']
        if path.name != found['nom_stockage'] or not path.is_file(): raise SignatureError('La convention originale est introuvable.')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != state['pdf_hash'] or found['pdf_hash'] != state['pdf_hash']:
            raise SignatureError('La convention originale a changé. L’envoi est bloqué.')
        return content

    def mutate(self, state, api, step, method, path, **kwargs):
        state['pending'] = step
        self.save(state)
        try:
            return api.call(method, path, **kwargs)
        except SignatureError as exc:
            state['error'] = str(exc)
            if exc.ambiguous: state['status'] = 'uncertain'
            else: state.pop('pending', None)
            self.save(state)
            raise

    def checkpoint(self, state):
        state.pop('pending', None); state.pop('error', None)
        self.save(state)

    def verify(self, state, api, signed=False):
        base = '/signature_requests/' + identifier(state['request_id'])
        documents = items(api.call('GET', base + '/documents'))
        if len(documents) != 1 or documents[0].get('id') != state.get('document_id'):
            raise SignatureError('Les documents de la demande Yousign ont changé. Vérifiez la demande avant de continuer.')
        people = items(api.call('GET', base + '/signers'))
        if {p.get('id') for p in people} != {p['id'] for p in state['signers'].values()} or len(people) != len(state['recipients']):
            raise SignatureError('La liste des signataires Yousign a changé. Vérifiez la demande.')
        for expected in state['recipients']:
            tracked = state['signers'][expected['role']]
            actual = next(p for p in people if p.get('id') == tracked['id'])
            if any(str(actual.get('info', {}).get(k) or '').strip().casefold() != expected[k].casefold() for k in ('first_name','last_name','email')):
                raise SignatureError('Les coordonnées d’un signataire ont changé dans Yousign. Vérifiez la demande.')
            if state.get('authentication_mode') == 'otp_sms' and (
                actual.get('signature_authentication_mode') != 'otp_sms' or
                actual.get('info', {}).get('phone_number') != expected['phone_number']):
                raise SignatureError('Le mobile ou la validation par SMS a changé dans Yousign. Vérifiez la demande.')
            if actual.get('excluded_documents') or tracked['id'] in (documents[0].get('excluded_signers') or []):
                raise SignatureError('Un signataire n’a plus accès à la convention. Vérifiez la demande Yousign.')
            tracked['status'] = actual.get('status', 'initiated')
            if signed and tracked['status'] != 'signed':
                raise SignatureError('Yousign doit confirmer la signature de chaque destinataire avant l’archivage.')

    def validate_source(self, state):
        from london_mobility import current_settings, digest, snapshot
        with closing(self.connect()) as conn:
            row = dict(conn.execute('SELECT * FROM candidats WHERE id=?', (state['candidate_id'],)).fetchone())
            trip = conn.execute('SELECT statut FROM voyage_londres_inscriptions WHERE candidat_id=?', (state['candidate_id'],)).fetchone()
            version = conn.execute('SELECT fingerprint FROM london_mobility_versions WHERE id=?', (state['version_id'],)).fetchone()
            if state.get('automatic'):
                from london_mobility_data import automatic_data
                resolved = automatic_data(conn, row, convention_date=state['convention_date'])
                unchanged = resolved['ready'] and resolved['fingerprint'] == state['source_hash']
            else:
                values, _, _, selected, _ = current_settings(conn, row)
                unchanged = digest(snapshot(row, values, selected)) == version['fingerprint']
            if row['mode'] != 'presentiel' or not trip or trip['statut'] != 'active' or not unchanged:
                raise SignatureError('La fiche ou le séjour a changé. Annulez cette demande et préparez la convention actualisée.')

    def send(self, state):
        from london_mobility import current_settings, digest, snapshot
        if state['status'] not in {'preparing','draft'} or state.get('pending'):
            raise SignatureError('Cette demande ne peut pas être renvoyée. Actualisez son suivi pour éviter un doublon.')
        api = self.api()
        self.validate_source(state)
        with closing(self.connect()) as conn: content = self.original(conn, state)
        if not state.get('request_id'):
            person = next(p for p in state['recipients'] if p['role'] == 'apprentice')
            result = self.mutate(state, api, 'create', 'POST', '/signature_requests', json={
                'name': ('Mobilité Londres · ' + person['first_name'] + ' ' + person['last_name'])[:128],
                'delivery_mode':'email', 'ordered_signers':False, 'timezone':'Europe/Paris',
                'external_id':state['external_id'], 'audit_trail_locale':'fr'})
            state.update(request_id=identifier(result.get('id')), status='draft')
            self.checkpoint(state)
        base = '/signature_requests/' + identifier(state['request_id'])
        if not state.get('document_id'):
            result = self.mutate(state, api, 'document', 'POST', base + '/documents',
                files={'file':(state['document_name'], content, 'application/pdf')}, data={'nature':'signable_document'})
            state['document_id'] = identifier(result.get('id')); self.checkpoint(state)
        for person in state['recipients']:
            role = person['role']
            if role in state['signers']: continue
            result = self.mutate(state, api, 'signer:' + role, 'POST', base + '/signers', json={
                'info':{**{k:person[k] for k in ('first_name','last_name','email')},
                        **({'phone_number':person['phone_number']} if state.get('authentication_mode') == 'otp_sms' else {}), 'locale':'fr'},
                'signature_level':'electronic_signature', 'signature_authentication_mode':state.get('authentication_mode','otp_email'),
                'fields':[{**state['fields'][role], 'document_id':state['document_id']}]})
            state['signers'][role] = dict(id=identifier(result.get('id')), status='initiated')
            self.checkpoint(state)
        # An operator may have changed the draft directly in Yousign.
        live = api.call('GET', base)
        if live.get('external_id') != state['external_id'] or live.get('status') != 'draft':
            raise SignatureError('La demande Yousign a changé. Actualisez son suivi avant de continuer.')
        self.verify(state, api)
        self.validate_source(state)  # Recheck immediately before invitations leave the service.
        result = self.mutate(state, api, 'activate', 'POST', base + '/activate', json={})
        if result.get('status') not in {'ongoing','done'}:
            raise SignatureError('Yousign n’a pas confirmé l’envoi. Actualisez le suivi.', True)
        state.update(status=result['status'], sent_at=now())
        for person in state['signers'].values(): person['status'] = 'notified'
        self.checkpoint(state)
        self.log_event(state['candidate_id'], 'Convention Londres envoyée en signature Yousign', {'version_id':state['version_id'], 'request_id':state['request_id']})

    def refresh(self, state):
        if state['status'] == 'completed': return
        api = self.api()
        if not state.get('request_id'):
            if not state.get('pending'): return
            found = [r for r in items(api.call('GET', '/signature_requests', params={'external_id[eq]':state['external_id'], 'limit':100}))
                     if r.get('external_id') == state['external_id']]
            if len(found) != 1:
                raise SignatureError('Yousign ne permet pas encore d’identifier la demande. Aucun nouvel envoi ne sera lancé automatiquement.')
            state['request_id'] = identifier(found[0]['id']); self.save(state)
        base = '/signature_requests/' + identifier(state['request_id'])
        try:
            live = api.call('GET', base)
        except SignatureError as error:
            if error.status_code == 404 and state.get('pending') == 'cancel':
                state.update(status='deleted', canceled_at=now()); self.checkpoint(state); return
            raise
        if live.get('id') != state['request_id'] or live.get('external_id') != state['external_id']:
            raise SignatureError('La demande Yousign ne correspond pas à cette convention.')
        state['status'] = live.get('status') if live.get('status') in ACTIVE | CLOSED else 'unknown'
        state['checked_at'] = now()
        if state['status'] in CLOSED:
            self.checkpoint(state)
        elif state['status'] in {'ongoing','done'}:
            self.verify(state, api, signed=state['status'] == 'done')
            self.checkpoint(state)
            if state['status'] == 'done': self.archive(state, api)
        elif state['status'] == 'draft':
            if state.get('pending') in {'create','activate'}:
                self.checkpoint(state)
            elif state.get('pending'):
                state['error'] = 'Une opération sur ce brouillon reste incertaine. Annulez cette demande avant d’en préparer une nouvelle.'
                self.save(state)
            else: self.save(state)
        else: self.save(state)

    def archive(self, state, api):
        content = api.call('GET', '/signature_requests/' + identifier(state['request_id']) + '/documents/' + identifier(state['document_id']) + '/download', binary=True)
        try:
            with closing(self.connect()) as conn: original = self.original(conn, state)
            reader = PdfReader(BytesIO(content))
            if not content.startswith(b'%PDF-') or reader.is_encrypted or len(reader.pages) != len(PdfReader(BytesIO(original)).pages): raise ValueError
        except Exception:
            raise SignatureError('Les signatures sont terminées, mais le PDF signé reçu est invalide. Réactualisez pour reprendre l’archivage.') from None
        paths = []
        try:
            with closing(self.connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                version = conn.execute('SELECT signed_id FROM london_mobility_versions WHERE id=? AND candidate_id=?', (state['version_id'],state['candidate_id'])).fetchone()
                if not version: raise SignatureError('Version introuvable pour l’archivage.')
                if not version['signed_id']:
                    trip = conn.execute('SELECT id FROM voyage_londres_inscriptions WHERE candidat_id=?', (state['candidate_id'],)).fetchone()
                    created = now()
                    did, sha = self.store_file(conn, trip['id'], content, 'pdf', 'Convention signée', 'Convention_Londres_signee_Yousign_' + created[:10], created, paths)
                    conn.execute('UPDATE london_mobility_versions SET signed_id=?,signed_hash=?,signed_at=? WHERE id=?', (did,sha,created,state['version_id']))
                    latest = conn.execute('SELECT id FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1', (state['candidate_id'],)).fetchone()
                    if latest['id'] == state['version_id']:
                        conn.execute("UPDATE voyage_londres_inscriptions SET convention=CASE WHEN convention='Transmise OPCO' THEN convention ELSE 'Signée' END,updated_at=? WHERE candidat_id=?", (created,state['candidate_id']))
                state.update(status='completed', completed_at=now())
                conn.execute('INSERT OR IGNORE INTO london_mobility_notifications VALUES(?,?,?,NULL)',
                             (state['version_id'],state['candidate_id'],state['completed_at']))
                state.pop('error', None); state.pop('pending', None)
                conn.execute('UPDATE london_mobility_signatures SET status=?,payload=?,updated_at=? WHERE id=?', (state['status'],dumps(state),now(),state['id']))
                conn.commit()
            paths.clear()
        finally:
            for path in paths: path.unlink(missing_ok=True)
        self.log_event(state['candidate_id'], 'Convention Londres signée et archivée depuis Yousign', {'version_id':state['version_id'], 'request_id':state['request_id']})

    def cancel(self, state):
        if state['status'] not in ACTIVE - {'done'}: raise SignatureError('Cette demande ne peut plus être annulée.')
        if not state.get('request_id') and not state.get('pending'):
            state.update(status='canceled', canceled_at=now()); self.checkpoint(state); return
        self.refresh(state)
        if state['status'] in CLOSED: return
        if state['status'] == 'completed': raise SignatureError('La convention est déjà signée et archivée.')
        api = self.api(); base = '/signature_requests/' + identifier(state.get('request_id'))
        if state['status'] == 'draft':
            self.mutate(state, api, 'cancel', 'DELETE', base)
        elif state['status'] in {'ongoing','approval','paused'}:
            self.mutate(state, api, 'cancel', 'POST', base + '/cancel', json={'reason':'errors_in_document', 'custom_note':'Correction de la convention de mobilité Londres'})
        else: raise SignatureError('Actualisez le suivi avant de demander l’annulation.')
        state.update(status='canceled', canceled_at=now()); self.checkpoint(state)
        self.log_event(state['candidate_id'], 'Demande de signature Londres annulée', {'version_id':state['version_id']})

    def remind(self, state, role):
        self.refresh(state)
        person = state['signers'].get(role)
        if state['status'] != 'ongoing' or not person or person['status'] != 'notified':
            raise SignatureError('La relance est disponible seulement pour une invitation en attente de signature.')
        previous = state.get('reminders', {}).get(role, 0)
        if time.time() - previous < 1800: raise SignatureError('Une relance a déjà été demandée récemment. Patientez 30 minutes avant une autre relance.')
        state.setdefault('reminders', {})[role] = time.time(); self.save(state)
        api = self.api()
        # A timeout may mean the email was delivered: retain the cooldown in either case.
        api.call('POST', '/signature_requests/' + identifier(state['request_id']) + '/signers/' + identifier(person['id']) + '/send_reminder', json={})
        self.log_event(state['candidate_id'], 'Relance signature Londres demandée', {'version_id':state['version_id'], 'destinataire':ROLES[role]})

    def record_error(self, state, error):
        state['error'] = str(error)
        state['checked_at'] = now()
        if state.get('pending') and getattr(error, 'ambiguous', False): state['status'] = 'uncertain'
        self.save(state)

    def poll(self):
        with closing(self.connect()) as conn:
            signature_schema(conn); conn.commit()
            rows = conn.execute('SELECT candidate_id,version_id,id,payload FROM london_mobility_signatures WHERE status IN (' +
                                ','.join('?' for _ in ACTIVE) + ') ORDER BY updated_at LIMIT 20', tuple(ACTIVE)).fetchall()
        for row in rows:
            state = json.loads(row['payload'])
            auto_pending = state.get('automatic') and state['status'] in {'preparing','draft','uncertain'}
            if not auto_pending and not state.get('request_id') and not state.get('pending'): continue
            checked = datetime.fromisoformat(state.get('checked_at') or state['created_at']).timestamp()
            if time.time() - checked < 90: continue
            try:
                with self.lock(row['candidate_id']):
                    state = self.load(row['candidate_id'],row['version_id'],row['id'])
                    try:
                        self.refresh(state)
                        if state.get('automatic') and state['status'] in {'preparing','draft'} and not state.get('pending') and not state.get('error'):
                            self.send(state)
                    except SignatureError as error: self.record_error(state, error)
            except SignatureError: pass  # An administrator is already working on it.


def register_signatures(app, connect, directory, guard, answer, store_file, log_event):
    service = SignatureService(app, connect, directory, store_file, log_event)
    app.extensions['london_signatures'] = service

    @app.post('/admin/candidat/<cid>/londres/conventions/<vid>/signature')
    def london_signature_send(cid, vid):
        guard(True)
        state = None
        try:
            with service.lock(cid):
                state = service.begin(cid, vid, request.form)
                try: service.send(state)
                except SignatureError as error:
                    service.record_error(state, error)
                    # The persisted draft must be visible even if the first send failed.
                    return jsonify(ok=False,error=str(error),refresh_url=True), 409
            return answer(cid, 'Invitations Yousign envoyées aux destinataires indiqués.')
        except SignatureError as error:
            return answer(cid, str(error), 400)

    @app.post('/admin/candidat/<cid>/londres/conventions/<vid>/signature/<aid>/<action>')
    def london_signature_action(cid, vid, aid, action):
        guard(True)
        if action not in {'refresh','resume','cancel','remind'}: abort(404)
        try:
            with service.lock(cid):
                state = service.load(cid, vid, aid)
                try:
                    if action == 'refresh': service.refresh(state)
                    elif action == 'resume':
                        if request.form.get('reviewed') != 'yes': raise SignatureError('Confirmez les destinataires avant de terminer l’envoi.')
                        service.send(state)
                    elif action == 'cancel':
                        if request.form.get('cancel_confirmed') != 'yes': raise SignatureError('Confirmez l’annulation de cette demande.')
                        service.cancel(state)
                    else: service.remind(state, request.form.get('role'))
                except SignatureError as error:
                    service.record_error(state, error)
                    return answer(cid, str(error), 409)
            if action == 'refresh' and request.form.get('poll') == 'yes':
                response = jsonify(ok=True, signature=public_state(state)); response.headers['Cache-Control'] = 'private, no-store'
                return response
            return answer(cid, {'refresh':'Suivi des signatures actualisé.', 'resume':'Invitations Yousign envoyées.',
                                'cancel':'Demande de signature annulée.', 'remind':'Relance demandée à Yousign.'}[action])
        except SignatureError as error:
            return answer(cid, str(error), 409)

    starter_lock = threading.Lock()
    @app.before_request
    def start_polling():
        if app.testing or not app.config.get('LONDON_SIGNATURE_POLLING', True) or not configuration()[0]: return
        with starter_lock:
            if app.extensions.get('london_signature_thread'): return
            def worker():
                while True:
                    try:
                        with app.app_context(): service.poll()
                    except Exception:
                        # Do not log API payloads, recipient data or secrets.
                        app.logger.warning('London signature polling will retry after an unexpected error')
                    time.sleep(45)
            thread = threading.Thread(target=worker, name='london-signatures', daemon=True)
            app.extensions['london_signature_thread'] = thread
            thread.start()
