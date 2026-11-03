"""Validate the CFA key against AKTO's recette API without importing test dossiers."""
from contextlib import closing
from datetime import datetime, timezone
import hmac
import os
import re

from cryptography.fernet import InvalidToken
from flask import abort, redirect, request, session, url_for

from akto_sync import PARIS, PortalError, secret
from opco_convergence import Client, ReadError, ReadHttpError, STATE_CODES
from wedof_contract_data import STATES


HOST = 'https://cfa-ws-rec.akto.fr'
CLIENT_ID = 'AKTO_RECETTE_CLIENT_ID'
CLIENT_SECRET = 'AKTO_RECETTE_CLIENT_SECRET'


def recette_headers(key):
    ident, password = os.environ.get(CLIENT_ID), os.environ.get(CLIENT_SECRET)
    if not ident or not password:
        raise ReadError('Les accès techniques de recette AKTO doivent être configurés sur le serveur.')
    try:
        token = Client.json_request(
            'POST', HOST + '/SorApiIdentityServer/connect/token', auth=(ident, password),
            data={'grant_type': 'client_credentials', 'scope': 'api.read api.write'},
            describe_bad_request=lambda p: {
                'invalid_client': 'Les identifiants techniques ont été refusés.',
                'invalid_scope': 'Les droits API demandés ont été refusés.',
                'unauthorized_client': 'Le logiciel n’est pas autorisé pour cette authentification.',
            }.get(p.get('error'), '') if isinstance(p, dict) and isinstance(p.get('error'), str) else '',
        )
    except ReadHttpError as exc:
        detail = f'{exc.detail} ' if exc.detail else ''
        raise ReadError(f'Authentification technique refusée par AKTO (HTTP {exc.status_code}). {detail}'
                        'La recherche du dossier n’a pas été envoyée.') from None
    bearer = token.get('access_token') if isinstance(token, dict) else None
    if not isinstance(bearer, str) or not bearer:
        raise ReadError('AKTO n’a pas délivré le jeton technique de recette.')
    return {'Authorization': 'Bearer ' + bearer, 'X-API-KEY': key, 'EDITEUR': 'Integrale Academy',
            'LOGICIEL': 'Inscriptions BTS', 'VERSION': '1.0', 'Accept': 'application/json'}


def verify_key(key):
    result = Client.json_request(
        'GET', HOST + '/SorApiEchangeCFA/v2/dossiers/etats',
        headers=recette_headers(key),
        params={'numeroPage': 1, 'dateModification': datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')},
    )
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict) and 'total' in result[0]:
        result = result[0]
    if isinstance(result, dict):
        rows = result.get('etatDossierResult', result.get('EtatDossierResult'))
        if rows is None and result.get('total') == 0:
            rows = []
    else:
        rows = result
    if not isinstance(rows, list) or not all(isinstance(row, dict) and 'numeroInterne' in row for row in rows):
        raise ReadError('AKTO a renvoyé une réponse inattendue. La clé n’a pas pu être vérifiée.')


def bad_request_reason(payload, headers):
    if not isinstance(payload, dict):
        return ''
    errors = payload.get('errors')
    entries = errors[:3] if isinstance(errors, list) else []
    # ASP.NET validation errors use a field-to-messages map instead of ErrorResult.
    if isinstance(errors, dict):
        for field in ('numeroInterne', 'numeroExterne', 'numeroDeca'):
            messages = errors.get(field)
            if isinstance(messages, list) and messages and isinstance(messages[0], str):
                entries.append({'description': field + ' : ' + messages[0]})
    parts = []
    for entry in [*entries, payload]:
        if not isinstance(entry, dict):
            continue
        value = entry.get('description') or entry.get('title')
        if isinstance(value, str):
            value = ' '.join(value.split())
            for sensitive in (headers.get('X-API-KEY'), headers.get('Authorization', '').removeprefix('Bearer ')):
                if sensitive:
                    value = value.replace(sensitive, '[masqué]')
            if value and value not in parts:
                parts.append(value[:240])
        code = entry.get('code')
        if type(code) is int and code != 400 and f'Code {code}' not in parts:
            parts.append(f'Code {code}')
    return ' · '.join(parts)[:500]


def lookup_dossier(key, reference, deca, internal=''):
    if not all(re.fullmatch(r'[a-zA-Z0-9./_-]{1,80}', value) for value in (reference, deca)):
        raise ReadError('Saisissez le numéro de dossier AKTO et le numéro d’enregistrement DECA figurant sur le contrat.')
    if internal and not re.fullmatch(r'[a-zA-Z0-9./_-]{1,80}', internal):
        raise ReadError('Vérifiez le format du numéro interne AKTO.')
    headers = recette_headers(key)
    queries = [('numéro de dossier et DECA', {'numeroExterne': reference, 'numeroDeca': deca})]
    if internal:
        queries.insert(0, ('numéro interne', {'numeroInterne': internal}))
    failures = []
    for label, params in queries:
        try:
            data = Client.json_request('GET', HOST + '/SorApiEchangeCFA/v2/dossiers', headers=headers,
                                       params=params, describe_bad_request=lambda body: bad_request_reason(body, headers))
            break
        except ReadHttpError as exc:
            if exc.status_code == 403:
                raise ReadError('Accès refusé en recette (403). AKTO ne rend pas ce dossier accessible à votre CFA '
                                'avec ces références.') from None
            if exc.status_code not in (400, 404):
                raise
            if exc.status_code == 404:
                reason = 'Dossier introuvable en recette (404).'
            elif not exc.detail:
                reason = 'Requête refusée (400). AKTO n’a pas fourni de motif exploitable.'
            else:
                reason = f'Requête refusée (400). Motif AKTO : {exc.detail}'
            failures.append(f'Recherche par {label} : {reason}')
    else:
        raise ReadError(' '.join(failures))
    cerfa = data.get('cerfa') if isinstance(data, dict) else None
    if not isinstance(cerfa, dict) or cerfa.get('numeroExterne') != reference:
        raise ReadError('AKTO n’a pas retourné de dossier correspondant au numéro demandé.')
    if 'numeroInterne' in params and str(cerfa.get('numeroInterne') or '') != internal:
        raise ReadError('Le dossier retourné par AKTO ne correspond pas au numéro interne demandé.')
    contract = cerfa.get('contrat') or {}
    if not isinstance(contract, dict) or (contract.get('noContrat') and contract['noContrat'] != deca):
        raise ReadError('Le numéro d’enregistrement reçu ne correspond pas à la demande.')
    state = STATES.get(STATE_CODES.get(cerfa.get('etat')), 'Non communiqué')
    dues = data.get('echeances')
    schedule = f'{len(dues)} échéance(s) communiquée(s).' if isinstance(dues, list) else 'Échéancier non communiqué.'
    return f'Dossier retrouvé en recette. Statut : {state}. {schedule}'


def register_akto_convergence(app, connect, require_admin):
    app.logger.info('AKTO Convergence recette : accès techniques configurés=%s.',
                    bool(os.environ.get(CLIENT_ID) and os.environ.get(CLIENT_SECRET)))

    def status():
        with closing(connect()) as conn:
            row = conn.execute('SELECT credential IS NOT NULL AS configured, verified FROM akto_recette_key').fetchone()
        return dict(row, feedback=session.pop('akto_recette_feedback', None),
                    dossier_feedback=session.pop('akto_dossier_feedback', None))

    app.jinja_env.globals['akto_recette_status'] = status

    @app.post('/admin/parametres/akto/convergence')
    def akto_recette_settings():
        expected = session.get('_planning_csrf')
        if not require_admin() or not expected or not hmac.compare_digest(expected.encode(), request.form.get('csrf_token', '').encode()):
            abort(403)
        action = request.form.get('action')
        if action not in ('save', 'test', 'remove', 'lookup'):
            abort(400)
        with closing(connect()) as conn:
            row = conn.execute('SELECT credential, revision FROM akto_recette_key WHERE id=1').fetchone()
            credential, verified = None, None
            try:
                if action != 'remove':
                    cipher = secret(app)
                    if action == 'save':
                        key = request.form.get('cfa_key', '').strip()
                        if not key or len(key) > 8192 or not key.isascii() or not key.isprintable() or ' ' in key:
                            raise ReadError('Saisissez une clé CFA AKTO valide, sans espaces.')
                        credential = cipher.encrypt(key.encode())
                    else:
                        credential = row['credential']
                        if credential is None:
                            raise ReadError('Aucune clé CFA n’est enregistrée.')
                        key = cipher.decrypt(credential).decode()
                    if action == 'lookup':
                        message = lookup_dossier(key, request.form.get('reference', '').strip(), request.form.get('deca', '').strip(),
                                                 request.form.get('internal', '').strip())
                        if conn.execute('SELECT revision FROM akto_recette_key WHERE id=1').fetchone()[0] != row['revision']:
                            raise ReadError('La clé a été modifiée pendant la lecture. Relancez le test.')
                        session['akto_dossier_feedback'] = ('success', message)
                        return redirect(url_for('admin_settings', _anchor='akto-dossier'), 303)
                    verify_key(key)
                    verified = datetime.now(PARIS).strftime('%d/%m/%Y à %H:%M')
                # Never hold a SQLite write lock while waiting for AKTO.
                changed = conn.execute('''UPDATE akto_recette_key SET credential=?, verified=?, revision=revision+1
                                          WHERE id=1 AND revision=?''', (credential, verified, row['revision']))
                conn.commit()
                if not changed.rowcount:
                    raise ReadError('Un autre administrateur a modifié ce réglage. Actualisez la page avant de réessayer.')
                message = 'Clé CFA supprimée.' if action == 'remove' else 'Clé CFA acceptée par AKTO en recette.'
                feedback = ('success', message)
            except (ReadError, PortalError) as exc:
                feedback = ('error', str(exc))
            except InvalidToken:
                feedback = ('error', 'La clé enregistrée ne peut plus être déchiffrée. Saisissez-la de nouveau.')
        session['akto_dossier_feedback' if action == 'lookup' else 'akto_recette_feedback'] = feedback
        return redirect(url_for('admin_settings', _anchor='akto-dossier' if action == 'lookup' else 'akto-convergence'), 303)
