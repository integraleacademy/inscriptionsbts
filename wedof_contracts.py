"""Admin-only WEDOF contract linking, with explicit previews and cached reads.

No remote writes, polling, retries or bulk imports. Each search page is requested
explicitly; only exact reference matches are returned. Credentials and previews
remain server-side. The API contract is documented in docs/wedof-contracts.md.
"""
import base64
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, jsonify, render_template, request, session
import requests

from wedof_contract_data import (FINANCERS, WedofError, date as source_date,
    financer_filter, folder_fields, identifier, normalize_summary, raw_fields, stamp)

CACHE_SECONDS = 1800
PREVIEW_SECONDS = 1800
BASE_URL = "https://www.wedof.fr/api"


def ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS student_wedof_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS student_wedof_contracts (
            contract_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, payload TEXT NOT NULL,
            checked_at REAL NOT NULL, linked_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
            last_attempt REAL NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS student_wedof_candidate ON student_wedof_contracts(candidate_id);
        CREATE TABLE IF NOT EXISTS student_wedof_previews (
            token TEXT PRIMARY KEY, binding TEXT NOT NULL, candidate_id TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS student_wedof_lock (id INTEGER PRIMARY KEY CHECK(id=1), token TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS student_wedof_calls (created_at REAL NOT NULL);
        CREATE TRIGGER IF NOT EXISTS student_wedof_candidate_deleted AFTER DELETE ON candidats
        BEGIN
            DELETE FROM student_wedof_contracts WHERE candidate_id=OLD.id;
            DELETE FROM student_wedof_previews WHERE candidate_id=OLD.id;
        END;
    """)


def cipher(app):
    secret = app.secret_key
    if not secret or len(secret) < 20 or secret == 'change-me':
        raise WedofError('La configuration sécurisée du serveur doit être complétée avant d’enregistrer la clé.', status=503)
    raw = secret.encode() if isinstance(secret, str) else secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b'bts-wedof-key-v1\0' + raw).digest()))


def get_key(app, conn):
    key = os.environ.get('WEDOF_API_KEY', '').strip()
    if key:
        return key
    row = conn.execute("SELECT value FROM student_wedof_settings WHERE name='api_key'").fetchone()
    if not row:
        return ''
    try:
        return cipher(app).decrypt(row['value'].encode()).decode()
    except (InvalidToken, UnicodeError):
        raise WedofError('La clé WEDOF enregistrée n’est plus lisible. Remplacez-la dans Paramètres.', status=503) from None


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')).casefold() if c.isalnum())


def reference(value):
    value = str(value or '').strip()
    if not 3 <= len(value) <= 120 or not re.fullmatch(r'[\w\s./-]+', value) or not any(c.isdigit() for c in value):
        raise WedofError('Saisissez le numéro complet du contrat OPCO ou le numéro DECA.')
    return ''.join(unicodedata.normalize('NFKC', value).split()).casefold()


def matches(item, number):
    for field in ('external_number', 'deca_number'):
        try:
            if reference(item.get(field)) == number:
                return True
        except WedofError:
            pass
    return False


def identity(candidate, item):
    """A known mismatch cannot be overridden by a checkbox."""
    pairs = [('prenom', 'apprentice_first_name'), ('nom', 'apprentice_last_name')]
    conflicts = [a for a, b in pairs if norm(candidate.get(a)) and norm(item.get(b)) and norm(candidate[a]) != norm(item[b])]
    local_birth, remote_birth = source_date(candidate.get('date_naissance')), item.get('apprentice_birth_date')
    if local_birth and remote_birth and local_birth != remote_birth:
        conflicts.append('date_naissance')
    if conflicts:
        return {'status': 'mismatch', 'message': 'L’identité ou la date de naissance ne correspond pas à cet étudiant. Vérifiez la référence ou corrigez la fiche avant de rattacher le contrat.'}
    complete = all(norm(candidate.get(a)) and norm(item.get(b)) for a, b in pairs)
    if complete:
        return {'status': 'matched', 'message': 'Le nom et le prénom correspondent à la fiche étudiante.'}
    return {'status': 'unverified', 'message': 'WEDOF ne restitue pas une identité complète. Vérifiez personnellement que ce contrat appartient à cet étudiant.'}


def euros(value):
    if value is None:
        return 'Non communiqué'
    return f'{Decimal(str(value)):,.2f}'.replace(',', '\u202f').replace('.', ',') + ' €'


def display_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return 'Non communiquée'


def display_stamp(value):
    from zoneinfo import ZoneInfo
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M')
    except (ValueError, TypeError):
        return 'Non communiquée'


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if value is not None else None


def billing(item):
    today = datetime.now(timezone.utc).date().isoformat()
    schedules = []
    for source in item.get('schedules', []):
        row = dict(source)
        total, paid, pending = (cents(row.get(k)) for k in ('montantTotal', 'montantRegle', 'montantEnCoursInstruction'))
        row['remaining'] = max(0, total-paid)/100 if total is not None and paid is not None else None
        if item.get('raw_stale'):
            row['status'] = 'À vérifier'
        elif total is not None and paid is not None and paid >= total:
            row['status'] = 'Réglée'
        elif pending is not None and pending > 0:
            row['status'] = 'En instruction'
        elif row.get('dateOuverture') and row['dateOuverture'] <= today:
            row['status'] = 'Ouverte à facturation'
        elif row.get('dateOuverture'):
            row['status'] = 'À venir'
        else:
            row['status'] = 'Non communiqué'
        schedules.append(row)
    def total(key):
        values = [cents(r.get(key)) for r in schedules]
        return sum(values)/100 if values and all(v is not None for v in values) else None
    amount, paid = total('montantTotal'), total('montantRegle')
    return {'schedules': schedules, 'total': amount, 'paid': paid, 'pending': total('montantEnCoursInstruction'),
            'remaining': max(0, cents(amount)-cents(paid))/100 if amount is not None and paid is not None else None}


class Client:
    def __init__(self, key, reserve):
        self.key, self.reserve = key, reserve

    def read(self, path, params=None):
        self.reserve()
        try:
            response = requests.get(BASE_URL + path, params=params,
                headers={'X-Api-Key': self.key, 'Accept': 'application/json', 'User-Agent': 'IntegraleAcademy-BTS/2026.10'},
                timeout=(3, 5), allow_redirects=False)
        except requests.RequestException:
            raise WedofError('WEDOF est momentanément injoignable. Les informations enregistrées sont conservées.', status=502) from None
        errors = {401: 'La clé WEDOF est invalide. Vérifiez-la dans Paramètres.',
                  403: 'La connexion WEDOF n’autorise pas la lecture de ces données.',
                  404: 'Ce contrat ou dossier est introuvable dans WEDOF.',
                  429: 'WEDOF reçoit trop de demandes. Réessayez plus tard.'}
        if not 200 <= response.status_code < 300:
            raise WedofError(errors.get(response.status_code, 'WEDOF n’a pas pu fournir les informations. Réessayez plus tard.'),
                             code='http_' + str(response.status_code), status=502)
        if len(response.content) > 4_000_000:
            raise WedofError('La réponse WEDOF est trop volumineuse.', status=502)
        try:
            return response.json(), response.headers
        except ValueError:
            raise WedofError('La réponse WEDOF est illisible.', status=502) from None

    def contract(self, key):
        key = identifier(key)
        raw, _ = self.read('/workingContracts/' + key)
        item = normalize_summary(raw)
        if item['working_contract_id'] != key:
            raise WedofError('Le contrat reçu ne correspond pas à la référence demandée.')
        return item

    def page(self, *, page=1, financer='', folder=''):
        params = {'state': 'all', 'financer': financer_filter(financer), 'page': page, 'limit': 100}
        if folder:
            params['registrationFolderExternalId'] = folder
        raw, headers = self.read('/workingContracts', params)
        if not isinstance(raw, list) or len(raw) > 100:
            raise WedofError('La liste WEDOF reçue est inattendue.')
        items = [normalize_summary(x) for x in raw]
        if len({x['working_contract_id'] for x in items}) != len(items):
            raise WedofError('La liste WEDOF contient des doublons. Relancez la recherche.')
        if any((financer and x['financer'] != financer) or (folder and x['registration_id'] != folder) for x in items):
            raise WedofError('WEDOF n’a pas respecté le dossier ou l’OPCO demandé.')
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            total = int(headers['x-total-count']) if 'x-total-count' in headers else None
            if (total is not None and (total < 0 or (not items and page*100 < total))) or int(headers.get('x-current-page', page)) != page:
                raise ValueError
        except (ValueError, TypeError):
            raise WedofError('La pagination WEDOF est incohérente.') from None
        return items, page*100 < total if total is not None else len(items) == 100

    def details(self, item):
        data = dict(item)
        errors = []
        folder = item.get('registration_id', '')
        if folder and len(folder) <= 250 and not any(c in folder for c in '/\\?#\r\n'):
            try:
                raw, _ = self.read('/registrationFolders/' + quote(folder, safe=''))
                data.update(folder_fields(raw, folder))
            except WedofError as error:
                errors.append(str(error))
                if error.code in {'http_401', 'http_403', 'http_429'}:
                    data.update(raw_stale=True, raw_error=str(error), details_error=str(error))
                    return data
        try:
            raw, _ = self.read('/workingContracts/' + item['working_contract_id'] + '/raw')
            fields = raw_fields(raw, item)
            # Two upstream identities must agree before either can be linked.
            for k in ('apprentice_first_name', 'apprentice_last_name', 'apprentice_birth_date'):
                if data.get(k) and fields.get(k) and norm(data[k]) != norm(fields[k]):
                    raise WedofError('Les identités du dossier et du contrat OPCO sont différentes.', code='identity_conflict')
            data.update(fields)
        except WedofError as error:
            if error.code == 'identity_conflict':
                raise
            data.update(raw_stale=True, raw_error=str(error))
        data['details_error'] = ' '.join(errors)
        return data


def register_wedof_contracts(app, connect, require_admin):
    bp = Blueprint('wedof_contracts', __name__)
    with closing(connect()) as conn:
        ensure_schema(conn)
    app.jinja_env.filters.update(wedof_money=euros, wedof_date=display_date, wedof_stamp=display_stamp)

    def csrf():
        if not session.get('_wedof_csrf'):
            session['_wedof_csrf'] = secrets.token_urlsafe(32)
        return session['_wedof_csrf']

    app.context_processor(lambda: {'wedof_csrf': csrf, 'wedof_financers': FINANCERS})

    def guarded(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not require_admin():
                abort(403)
            if request.method != 'GET' and (not session.get('_wedof_csrf') or not hmac.compare_digest(
                    request.headers.get('X-CSRF-Token', ''), session['_wedof_csrf'])):
                return jsonify(ok=False, message='La session a expiré. Rechargez la page.'), 400
            try:
                return fn(*args, **kwargs)
            except WedofError as error:
                return jsonify(ok=False, message=str(error)), error.status
        return wrapped

    @bp.after_request
    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def connection():
        conn = connect()
        ensure_schema(conn)
        return conn

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise WedofError('La demande est invalide.')
        return data

    def candidate(cid):
        with closing(connection()) as conn:
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not row:
            abort(404)
        return dict(row)

    def binding():
        return hashlib.sha256(csrf().encode()).hexdigest()

    def config_id(key):
        return hashlib.sha256(key.encode()).hexdigest()

    def save_preview(conn, cid, kind, data):
        token = secrets.token_urlsafe(32)
        conn.execute('DELETE FROM student_wedof_previews WHERE created_at<?', (time.time()-PREVIEW_SECONDS,))
        conn.execute('INSERT INTO student_wedof_previews VALUES(?,?,?,?,?,?)',
                     (token, binding(), cid, kind, json.dumps(data, ensure_ascii=False), time.time()))
        conn.commit()
        return token

    def preview(conn, cid, token, kind):
        row = conn.execute('SELECT payload FROM student_wedof_previews WHERE token=? AND binding=? AND candidate_id=? AND kind=? AND created_at>?',
            (str(token or ''), binding(), cid, kind, time.time()-PREVIEW_SECONDS)).fetchone()
        if not row:
            raise WedofError('Cet aperçu a expiré. Relancez la recherche.', status=410)
        data = json.loads(row['payload'])
        if data['config'] != config_id(get_key(app, conn)):
            raise WedofError('La connexion WEDOF a changé. Relancez la recherche.', status=409)
        return data

    @contextmanager
    def api_client():
        token = secrets.token_hex(16)
        with closing(connection()) as conn:
            key = get_key(app, conn)
            if not key:
                raise WedofError('Ajoutez votre clé WEDOF dans Paramètres avant de rechercher un contrat.', status=503)
            conn.execute('BEGIN IMMEDIATE')
            locked = conn.execute('SELECT expires FROM student_wedof_lock WHERE id=1').fetchone()
            if locked and locked['expires'] > time.time():
                raise WedofError('Une lecture WEDOF est déjà en cours. Réessayez dans quelques instants.', status=409)
            conn.execute('INSERT INTO student_wedof_lock VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET token=excluded.token,expires=excluded.expires', (token, time.time()+90))
            conn.commit()
        def reserve():
            with closing(connection()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                now = time.time()
                conn.execute('DELETE FROM student_wedof_calls WHERE created_at<?', (now-86400,))
                count = conn.execute('SELECT COUNT(*),SUM(created_at>?) FROM student_wedof_calls', (now-3600,)).fetchone()
                if count[0] >= 500 or (count[1] or 0) >= 100:
                    raise WedofError('Le plafond interne de lectures WEDOF est atteint. Réessayez plus tard.', status=429)
                conn.execute('INSERT INTO student_wedof_calls VALUES(?)', (now,))
                conn.commit()
        try:
            yield Client(key, reserve)
        finally:
            with closing(connection()) as conn:
                conn.execute('DELETE FROM student_wedof_lock WHERE id=1 AND token=?', (token,))
                conn.commit()

    def cards(cid):
        with closing(connection()) as conn:
            rows = conn.execute('SELECT * FROM student_wedof_contracts WHERE candidate_id=? ORDER BY linked_at DESC', (cid,)).fetchall()
        return [{'item': json.loads(r['payload']), 'error': r['error'], 'checked_at': datetime.fromtimestamp(r['checked_at'], timezone.utc).isoformat(),
                 'billing': billing(json.loads(r['payload']))} for r in rows]

    @bp.route('/admin/api/wedof/settings', methods=['GET', 'PUT', 'DELETE'])
    @guarded
    def settings():
        with closing(connection()) as conn:
            managed = bool(os.environ.get('WEDOF_API_KEY', '').strip())
            if request.method != 'GET' and managed:
                raise WedofError('La clé WEDOF est gérée sur le serveur.', status=409)
            if request.method == 'PUT':
                key = str(body().get('api_key', '')).strip()
                if not 16 <= len(key) <= 512 or not re.fullmatch(r'[!-~]+', key):
                    raise WedofError('Saisissez une clé API WEDOF valide, sans espaces.')
                conn.execute("INSERT INTO student_wedof_settings VALUES('api_key',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (cipher(app).encrypt(key.encode()).decode(),))
                conn.execute('DELETE FROM student_wedof_previews')
                conn.commit()
            elif request.method == 'DELETE':
                conn.execute("DELETE FROM student_wedof_settings WHERE name='api_key'")
                conn.execute('DELETE FROM student_wedof_previews')
                conn.commit()
            warning = ''
            try:
                configured = bool(get_key(app, conn))
            except WedofError as error:
                configured, warning = False, str(error)
            return jsonify(ok=True, configured=configured, managed_by_server=managed, warning=warning)

    @bp.get('/admin/candidat/<cid>/contrats-apprentissage')
    @guarded
    def index(cid):
        row = candidate(cid)
        with closing(connection()) as conn:
            try:
                configured = bool(get_key(app, conn))
            except WedofError:
                configured = False
        return jsonify(ok=True, html=render_template('_wedof_contracts_list.html', contracts=cards(cid), row=row, configured=configured))

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/rechercher')
    @guarded
    def search(cid):
        candidate(cid)
        data = body()
        with closing(connection()) as conn:
            if data.get('next_token'):
                params = preview(conn, cid, data['next_token'], 'page')
            else:
                kind = data.get('kind', 'number')
                number = str(data.get('reference', '')).strip()
                financer = str(data.get('financer', ''))
                financer_filter(financer)
                if kind == 'wedof':
                    number = identifier(number)
                elif kind == 'number':
                    number = reference(number)
                    if not financer:
                        raise WedofError('Choisissez l’OPCO pour rechercher un numéro de contrat ou DECA.')
                elif kind == 'folder':
                    if not re.fullmatch(r'[\w.-]{1,120}', number):
                        raise WedofError('Saisissez la référence exacte du dossier de formation WEDOF.')
                else:
                    raise WedofError('Choisissez un type de référence valide.')
                params = {'kind': kind, 'number': number, 'financer': financer, 'page': 1}
            config = config_id(get_key(app, conn))
            request_hash = hashlib.sha256(json.dumps({k: v for k, v in params.items() if k != 'config'}, sort_keys=True).encode()).hexdigest()
            cached_rows = conn.execute("SELECT token,payload FROM student_wedof_previews WHERE binding=? AND candidate_id=? AND kind='search' AND created_at>? ORDER BY created_at DESC", (binding(), cid, time.time()-CACHE_SECONDS)).fetchall()
            cached = next(((r['token'], json.loads(r['payload'])) for r in cached_rows
                           if json.loads(r['payload']).get('request_hash') == request_hash and json.loads(r['payload']).get('config') == config), None)
        if cached:
            return jsonify(ok=True, token=cached[0], next_token=cached[1].get('next_token'), items=cached[1]['public_items'], message=cached[1]['message'], cached=True)
        with api_client() as client:
            if params['kind'] == 'wedof':
                items, more = [client.contract(params['number'])], False
                if params['financer'] and items[0]['financer'] != params['financer']:
                    raise WedofError('Ce contrat appartient à un autre OPCO que celui sélectionné.')
            else:
                items, more = client.page(page=params['page'], financer=params['financer'], folder=params['number'] if params['kind'] == 'folder' else '')
                if params['kind'] == 'number':
                    items = [i for i in items if matches(i, params['number'])]
            config = config_id(client.key)
        with closing(connection()) as conn:
            next_token = save_preview(conn, cid, 'page', {**params, 'page': params['page']+1, 'config': config}) if more and params['page'] < 100 else None
            message = 'Contrat(s) correspondant à votre référence.' if items else 'Aucun contrat trouvé dans cette page de résultats.' if next_token else 'Aucun contrat ne correspond à cette référence. Vérifiez le numéro et la connexion de l’OPCO dans WEDOF.'
            public_items = [{k: i.get(k) for k in ('working_contract_id', 'external_number', 'deca_number', 'employer_name', 'contract_start', 'contract_end', 'state_label')} for i in items]
            token = save_preview(conn, cid, 'search', {'config': config, 'items': items, 'request_hash': request_hash, 'next_token': next_token, 'public_items': public_items, 'message': message})
        return jsonify(ok=True, token=token, next_token=next_token, message=message, items=public_items)

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/apercu')
    @guarded
    def inspect(cid):
        row, data = candidate(cid), body()
        key = identifier(data.get('contract_id'))
        with closing(connection()) as conn:
            result = preview(conn, cid, data.get('token'), 'search')
            selected = next((i for i in result['items'] if i['working_contract_id'] == key), None)
            if not selected:
                raise WedofError('Ce contrat ne fait pas partie de votre recherche.', status=403)
            linked = conn.execute('SELECT candidate_id FROM student_wedof_contracts WHERE contract_id=?', (key,)).fetchone()
            if linked:
                raise WedofError('Ce contrat est déjà rattaché à cette fiche.' if linked['candidate_id'] == cid else 'Ce contrat est déjà rattaché à un autre étudiant.', status=409)
            cached_rows = conn.execute("SELECT token,payload FROM student_wedof_previews WHERE binding=? AND candidate_id=? AND kind='contract' AND created_at>? ORDER BY created_at DESC", (binding(), cid, time.time()-CACHE_SECONDS)).fetchall()
            cached = next(((r['token'], json.loads(r['payload'])) for r in cached_rows
                           if json.loads(r['payload']).get('config') == result['config'] and json.loads(r['payload'])['item']['summary_hash'] == selected['summary_hash']), None)
        if cached:
            item = cached[1]['item']
            check = identity(row, item)
            return jsonify(ok=True, token=cached[0], identity=check, html=render_template('_wedof_contract_preview.html', item=item, identity=check, row=row), cached=True)
        with api_client() as client:
            current = client.contract(key)
            if current['summary_hash'] != selected['summary_hash']:
                with closing(connection()) as conn:
                    conn.execute("DELETE FROM student_wedof_previews WHERE binding=? AND candidate_id=? AND kind IN ('search','page')", (binding(), cid))
                    conn.commit()
                raise WedofError('Le contrat a changé. Relancez la recherche avant de le rattacher.', status=409)
            item = client.details(current)
            config = config_id(client.key)
        check = identity(row, item)
        with closing(connection()) as conn:
            token = save_preview(conn, cid, 'contract', {'config': config, 'item': item, 'checked_at': time.time()})
        return jsonify(ok=True, token=token, identity=check, html=render_template('_wedof_contract_preview.html', item=item, identity=check, row=row))

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/rattacher')
    @guarded
    def link(cid):
        row, data = candidate(cid), body()
        with closing(connection()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = preview(conn, cid, data.get('token'), 'contract')
            current_candidate = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
            if not current_candidate:
                abort(404)
            row = dict(current_candidate)
            item = result['item']
            check = identity(row, item)
            if check['status'] == 'mismatch' or (check['status'] == 'unverified' and data.get('identity_confirmed') is not True):
                raise WedofError(check['message'], status=409)
            try:
                conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)',
                             (item['working_contract_id'], cid, json.dumps(item, ensure_ascii=False), result['checked_at'], stamp()))
            except sqlite3.IntegrityError:
                raise WedofError('Ce contrat a déjà été rattaché. Actualisez la fiche.', status=409) from None
            conn.execute('DELETE FROM student_wedof_previews WHERE token=?', (data['token'],))
            conn.commit()
        return jsonify(ok=True, message='Le contrat est rattaché à la fiche étudiante.')

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/<key>/actualiser')
    @guarded
    def refresh(cid, key):
        row, key = candidate(cid), identifier(key)
        with closing(connection()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            stored = conn.execute('SELECT * FROM student_wedof_contracts WHERE candidate_id=? AND contract_id=?', (cid, key)).fetchone()
            if not stored:
                abort(404)
            if time.time()-max(stored['checked_at'], stored['last_attempt']) < CACHE_SECONDS:
                return jsonify(ok=True, message='Les dernières données sont conservées. Une nouvelle lecture sera possible 30 minutes après la précédente.', cached=True)
            conn.execute('UPDATE student_wedof_contracts SET last_attempt=? WHERE contract_id=?', (time.time(), key))
            conn.commit()
        old = json.loads(stored['payload'])
        try:
            with api_client() as client:
                current = client.contract(key)
                if current['financer'] != old['financer'] or current['registration_id'] != old['registration_id']:
                    raise WedofError('Le dossier lié a changé dans WEDOF. Les anciennes informations sont conservées pour vérification.')
                fresh = client.details(current)
                if identity(row, fresh)['status'] == 'mismatch':
                    raise WedofError('L’identité reçue ne correspond plus à cet étudiant. Les informations précédentes sont conservées.')
            merged = {**old, **fresh}
            if fresh.get('raw_stale'):
                merged['raw_stale'] = True
            with closing(connection()) as conn:
                conn.execute('UPDATE student_wedof_contracts SET payload=?,checked_at=?,error=? WHERE candidate_id=? AND contract_id=?',
                             (json.dumps(merged, ensure_ascii=False), time.time(), '', cid, key))
                conn.commit()
        except WedofError as error:
            with closing(connection()) as conn:
                old['raw_stale'] = True
                conn.execute('UPDATE student_wedof_contracts SET error=?,payload=? WHERE candidate_id=? AND contract_id=?',
                             (str(error), json.dumps(old, ensure_ascii=False), cid, key))
                conn.commit()
            raise
        return jsonify(ok=True, message='Les informations disponibles ont été actualisées depuis WEDOF.')

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/<key>/detacher')
    @guarded
    def unlink(cid, key):
        candidate(cid)
        with closing(connection()) as conn:
            conn.execute('DELETE FROM student_wedof_contracts WHERE candidate_id=? AND contract_id=?', (cid, identifier(key)))
            conn.commit()
        return jsonify(ok=True, message='Le lien avec cette fiche a été retiré. Le contrat reste dans WEDOF.')

    app.register_blueprint(bp)
