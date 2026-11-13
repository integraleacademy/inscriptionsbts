"""CNAPS collection and read-only tracking for security apprentices only.

The shared BTS key stays on the servers. A purpose-specific derived credential
authenticates the narrow tracking route; no CNAPS or CRM credential reaches the
browser. The central service resolves the candidate itself before looking up a
CNAPS dossier. Merely consulting a dossier never sends a message.
"""
import hashlib
import hmac
import json
import os
import re
from contextlib import closing

import requests
from flask import abort, jsonify, request, session

from branded_email import _environment, academy_logo_url
from security_admission import ADVISER
from training_programs import SECURITY


COLLECTION_URL = 'https://cnapsv3.onrender.com/public-form'
TRACKING_ORIGIN = 'https://gestionstagiaires-r5no.onrender.com'
TRACKING_SOURCE_URL = TRACKING_ORIGIN + '/admin/sessions/suivi-cnaps'
TRACKING_KEY_CONTEXT = b'bts-cnaps-tracking-v1'
MAX_RESPONSE_BYTES = 128 * 1024


class TrackingUnavailable(Exception):
    def __init__(self, message, *, status=502, reason='unavailable'):
        super().__init__(message)
        self.status = status
        self.reason = reason


def collection_email(row):
    """Prepare a branded message without contacting a service or changing data."""
    if row.get('bts') != SECURITY:
        raise ValueError('Cette collecte est réservée au parcours sécurité en alternance.')
    first = str(row.get('prenom') or '').strip()
    subject = 'Ton autorisation d’entrée en formation · Ministère de l’intérieur (CNAPS)'
    logo = academy_logo_url()
    return subject, _environment.get_template('emails/security_cnaps_collection.html').render(
        first=first, subject=subject, adviser=ADVISER,
        logo_url=logo, avatar_url=logo.rsplit('/', 1)[0] + '/' + ADVISER['avatar'],
        collection_url=COLLECTION_URL,
        official_information_url=(
            'https://www.cnaps.interieur.gouv.fr/Demarches-en-ligne/'
            'Vous-etes-un-particulier/Se-former-aux-metiers-de-la-securite-privee/'
            'Se-former-aux-metiers-de-la-securite-privee'
        ),
    )


def collection_sent_at(conn, cid):
    """Only confirmed deliveries count; a preview or a failed send never does."""
    for event in conn.execute(
        "SELECT payload,created_at FROM logs WHERE (candidat_id=? OR cid=?) "
        "AND type='MAIL_ENVOYE' ORDER BY created_at DESC", (cid, cid)
    ):
        try:
            payload = json.loads(event['payload'] or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get('type') == 'cnaps' and payload.get('message_id'):
            return payload.get('sent_at') or event['created_at']
    return None


def _text(value, length=240):
    return str(value)[:length] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def _public_tracking(payload):
    """Allowlist the small display contract, rather than forwarding remote data."""
    if not isinstance(payload, dict) or not isinstance(payload.get('found'), bool):
        raise TrackingUnavailable('Le suivi du dossier a renvoyé une réponse inattendue.')
    freshness = {}
    if payload.get('stale') is True or payload.get('refresh_failed') is True:
        freshness = {
            'stale': True, 'refresh_failed': True,
            'refresh_error': 'Le suivi du dossier est momentanément indisponible.',
        }
    if payload['found'] is False:
        return {'found': False, **freshness}
    source = payload.get('cnaps')
    if not isinstance(source, dict):
        raise TrackingUnavailable('Le suivi du dossier a renvoyé une réponse inattendue.')
    person = payload.get('person') if isinstance(payload.get('person'), dict) else {}
    nub = _text(payload.get('nub') or source.get('nub') or person.get('nub'), 30)
    titles = []
    for item in (source.get('titles') if isinstance(source.get('titles'), list) else [])[:100]:
        if not isinstance(item, dict):
            continue
        titles.append({
            'type': _text(item.get('type')) or 'Titre ou autorisation',
            'state': _text(item.get('state'), 100) or 'INCONNU',
            'expires_at': _text(item.get('expires_at'), 40) or None,
            'expires_before_training': item.get('expires_before_training') is True,
        })
    return {
        'found': True,
        **freshness,
        'nub': nub,
        'inscription': _text(payload.get('inscription')),
        'source_url': TRACKING_SOURCE_URL,
        'cnaps': {
            'status': _text(source.get('cnaps_status') or source.get('status'), 120) or 'INCONNU',
            'nub': nub,
            'nub_missing': not bool(nub),
            'nub_present': bool(nub),
            'last_checked_at': _text(source.get('last_checked_at'), 50) or None,
            'cnaps_unavailable': source.get('cnaps_unavailable') is True,
            'titles': titles,
        },
    }


def fetch_tracking(cid, *, refresh=False):
    secret = os.getenv('BTS_IMPORT_API_KEY', '').strip()
    if len(secret) < 32:
        raise TrackingUnavailable('La connexion au suivi du dossier n’est pas configurée.',
                                  status=503, reason='not_configured')
    credential = hmac.new(secret.encode(), TRACKING_KEY_CONTEXT, hashlib.sha256).hexdigest()
    try:
        with requests.get(
            TRACKING_ORIGIN + '/api/integrations/bts/candidats/' + cid + '/cnaps-tracking',
            headers={'Authorization': 'Bearer ' + credential, 'Accept': 'application/json'},
            params={'refresh': '1'} if refresh else {}, timeout=(5, 45),
            allow_redirects=False, stream=True,
        ) as response:
            if response.status_code in (401, 403, 503):
                raise TrackingUnavailable('La connexion au suivi du dossier doit être vérifiée.',
                                          status=503, reason='not_configured')
            if response.status_code == 409:
                raise TrackingUnavailable(
                    'Le dossier ne peut pas être rattaché avec certitude à ce candidat. '
                    'Vérifiez son identité dans le suivi partagé.',
                    status=409, reason='ambiguous_match')
            if response.status_code != 200:
                raise TrackingUnavailable('Le suivi du dossier est momentanément indisponible. Réessayez dans quelques instants.')
            content = bytearray()
            for chunk in response.iter_content(16384):
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise TrackingUnavailable('La réponse du suivi du dossier est trop volumineuse.')
            payload = json.loads(content)
    except (requests.RequestException, ValueError, UnicodeError):
        # Never expose a URL, a credential or raw provider errors to the client.
        raise TrackingUnavailable('Le suivi du dossier est momentanément indisponible. Réessayez dans quelques instants.') from None
    return _public_tracking(payload)


def register_candidate_cnaps(app, db_connect, workflow_response):
    def candidate(cid):
        if not session.get('admin_ok'):
            abort(403)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', cid):
            abort(404)
        with closing(db_connect()) as conn:
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
            if not row:
                abort(404)
            row = dict(row)
            if row.get('bts') != SECURITY:
                abort(404)
            sent_at = collection_sent_at(conn, cid)
        return row, sent_at

    @app.get('/admin/candidat/<cid>/cnaps-tracking')
    def admin_candidate_cnaps_tracking(cid):
        _, sent_at = candidate(cid)
        # Used after a confirmed delivery; updating the send date needs no remote lookup.
        if request.args.get('collection_only') == '1':
            return jsonify(ok=True, collection_sent_at=sent_at)
        try:
            payload = fetch_tracking(cid, refresh=request.args.get('refresh') == '1')
        except TrackingUnavailable as exc:
            return jsonify(ok=False, error=str(exc), reason=exc.reason, collection_sent_at=sent_at), exc.status
        return jsonify(ok=True, **payload, collection_sent_at=sent_at)

    @app.post('/admin/candidat/<cid>/cnaps-request')
    def admin_candidate_cnaps_request(cid):
        candidate(cid)
        return workflow_response('cnaps', cid)

    @app.after_request
    def private_candidate_cnaps(response):
        if request.endpoint in {'admin_candidate_cnaps_tracking', 'admin_candidate_cnaps_request'}:
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
