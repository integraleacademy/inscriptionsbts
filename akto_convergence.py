"""Validate the CFA key against AKTO's recette API without importing test dossiers."""
from contextlib import closing
from datetime import datetime, timezone
import hmac
import os

from cryptography.fernet import InvalidToken
from flask import abort, redirect, request, session, url_for

from akto_sync import PARIS, PortalError, secret
from opco_convergence import Client, ReadError


HOST = 'https://cfa-ws-rec.akto.fr'
CLIENT_ID = 'AKTO_RECETTE_CLIENT_ID'
CLIENT_SECRET = 'AKTO_RECETTE_CLIENT_SECRET'


def verify_key(key):
    ident, password = os.environ.get(CLIENT_ID), os.environ.get(CLIENT_SECRET)
    if not ident or not password:
        raise ReadError('Les accès techniques de recette AKTO doivent être configurés sur le serveur.')
    token = Client.json_request(
        'POST', HOST + '/SorApiIdentityServer/connect/token', auth=(ident, password),
        data={'grant_type': 'client_credentials', 'scope': 'api.read api.write'},
    )
    bearer = token.get('access_token') if isinstance(token, dict) else None
    if not isinstance(bearer, str) or not bearer:
        raise ReadError('AKTO n’a pas délivré le jeton technique de recette.')
    # Probe a protected route. The CFA key only travels in a header.
    result = Client.json_request(
        'GET', HOST + '/SorApiEchangeCFA/v2/dossiers/etats',
        headers={'Authorization': 'Bearer ' + bearer, 'X-API-KEY': key,
                 'EDITEUR': 'Integrale Academy', 'LOGICIEL': 'Inscriptions BTS', 'VERSION': '1.0',
                 'Accept': 'application/json'},
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


def register_akto_convergence(app, connect, require_admin):
    app.logger.info('AKTO Convergence recette : accès techniques configurés=%s.',
                    bool(os.environ.get(CLIENT_ID) and os.environ.get(CLIENT_SECRET)))

    def status():
        with closing(connect()) as conn:
            row = conn.execute('SELECT credential IS NOT NULL AS configured, verified FROM akto_recette_key').fetchone()
        return dict(row, feedback=session.pop('akto_recette_feedback', None))

    app.jinja_env.globals['akto_recette_status'] = status

    @app.post('/admin/parametres/akto/convergence')
    def akto_recette_settings():
        expected = session.get('_planning_csrf')
        if not require_admin() or not expected or not hmac.compare_digest(expected.encode(), request.form.get('csrf_token', '').encode()):
            abort(403)
        action = request.form.get('action')
        if action not in ('save', 'test', 'remove'):
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
        session['akto_recette_feedback'] = feedback
        return redirect(url_for('admin_settings', _anchor='akto-convergence'), 303)
