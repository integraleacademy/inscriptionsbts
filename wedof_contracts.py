"""Admin-only WEDOF contract discovery, linking and cached reads.

No remote writes or bulk imports. Daily scheduled discovery is bounded
to one student's folders; reference searches paginate explicitly. Credentials and previews
remain server-side. The API contract is documented in docs/wedof-contracts.md.
"""
import base64
from collections.abc import Mapping
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from email.utils import parsedate_to_datetime
from functools import wraps
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from urllib.parse import quote
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, jsonify, render_template, request, session
import requests

from wedof_contract_data import (FINANCERS, STATES, WedofError, date as source_date,
    financer_filter, folder_fields, identifier, normalize_summary, raw_fields, stamp)

CACHE_SECONDS = 1800
ERROR_CACHE_SECONDS = 60
READ_WINDOW_SECONDS = 60
READ_WINDOW_LIMIT = 100
PREVIEW_SECONDS = 1800
BASE_URL = "https://www.wedof.fr/api"


def retry_time(headers, now):
    """Respect WEDOF's reset headers, including standard HTTP Retry-After."""
    deadlines = []
    for name, relative in (('retry-after', True), ('x-ratelimit-reset', True), ('x-ratelimit-retry-at', False)):
        value = headers.get(name)
        try:
            number = float(value)
            deadline = now + number if relative else number
        except (ValueError, TypeError):
            if name != 'retry-after' or not isinstance(value, str):
                continue
            try:
                deadline = parsedate_to_datetime(value).timestamp()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(deadline) and deadline > now:
            deadlines.append(deadline)
    return max(deadlines) if deadlines else now + READ_WINDOW_SECONDS


def rate_limit_error(retry_at):
    seconds = max(1, math.ceil(retry_at - time.time()))
    return WedofError(f'Les lectures WEDOF sont momentanément en pause. Réessayez dans {seconds} secondes.',
                      code='rate_limited', status=429, retry_at=retry_at)


def discovery_cache_valid(state, updated_at, manual=False):
    if state.get('error_code') or state.get('error_status'):
        # Invalidate errors persisted by the removed hourly/daily local quota.
        if state.get('error_status') == 429 and state.get('error_code') == 'wedof_error':
            return False
        if state.get('retry_at'):
            return state['retry_at'] > time.time()
        return not manual and updated_at > time.time() - ERROR_CACHE_SECONDS
    return updated_at > time.time() - CACHE_SECONDS


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
        CREATE TABLE IF NOT EXISTS student_wedof_discovery (
            candidate_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
            payload TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE TRIGGER IF NOT EXISTS student_wedof_discovery_deleted AFTER DELETE ON candidats
        BEGIN
            DELETE FROM student_wedof_discovery WHERE candidate_id=OLD.id;
        END;
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


def email(value):
    value = str(value or '').strip().casefold()
    return value if len(value) <= 254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) else ''


def automatic_identity(candidate, item):
    """Names alone never authorize an automatic link, even for a unique result."""
    if identity(candidate, item)['status'] != 'matched':
        return False
    local_email = email(candidate.get('email'))
    birth = source_date(candidate.get('date_naissance'))
    return bool((local_email and local_email == email(item.get('apprentice_email')))
                or (birth and birth == item.get('apprentice_birth_date')))


def discovery_fingerprint(candidate, config):
    fields = {k: candidate.get(k) for k in ('id', 'nom', 'prenom', 'date_naissance', 'email')}
    return hashlib.sha256(json.dumps([fields, config], sort_keys=True).encode()).hexdigest()


def directory_contracts(app, conn, rows):
    """Read the same links as the student sheet, without making remote calls.

    A missing local link is unknown until a complete, successful discovery. Keep
    ambiguous, failed and deliberately detached results out of the no-contract KPI.
    """
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    api_key = ''
    if 'student_wedof_settings' in tables:
        try:
            api_key = get_key(app, conn)
        except WedofError:
            pass
    config = hashlib.sha256(api_key.encode()).hexdigest()
    contracts, discoveries = {}, {}
    ids = [r['id'] for r in rows]
    for offset in range(0, len(ids), 400):
        batch = ids[offset:offset+400]
        marks = ','.join('?' for _ in batch)
        if 'student_wedof_contracts' in tables:
            for saved in conn.execute(f'SELECT candidate_id,payload FROM student_wedof_contracts WHERE candidate_id IN ({marks}) ORDER BY checked_at DESC', batch):
                try:
                    item = json.loads(saved['payload'])
                except (ValueError, TypeError):
                    item = None
                contracts.setdefault(saved['candidate_id'], []).append(item)
        if 'student_wedof_discovery' in tables:
            discoveries.update({r['candidate_id']: dict(r) for r in conn.execute(
                f'SELECT * FROM student_wedof_discovery WHERE candidate_id IN ({marks})', batch)})
    for row in rows:
        row.update(contract='linked', contract_label='À vérifier', contract_detail='Recherche WEDOF à effectuer', contract_needs_check=bool(api_key))
        linked = contracts.get(row['id'], [])
        if linked:
            row['contract_needs_check'] = False
            items = [i for i in linked if isinstance(i, dict) and i]
            if items:
                row.update(contract='yes', contract_label='Contrat d’apprentissage',
                           contract_detail=' · '.join(dict.fromkeys(STATES.get(i.get('state'), 'État à vérifier') for i in items)))
            else:
                row['contract_detail'] = 'Le contrat rattaché doit être vérifié dans la fiche.'
            continue
        saved = discoveries.get(row['id'])
        if not saved or saved['fingerprint'] != discovery_fingerprint(row, config):
            continue
        try:
            state = json.loads(saved['payload'])
        except (TypeError, ValueError):
            continue
        if not isinstance(state, dict):
            continue
        if state.get('suppressed'):
            row.update(contract_needs_check=False, contract_detail='Rattachement automatique suspendu dans la fiche.')
        elif state.get('step') == 'done' and (not state.get('error_code') or discovery_cache_valid(state, saved['updated_at'])):
            row.update(contract_needs_check=False, contract_detail=state.get('message', 'Vérifiez le contrat dans la fiche.'))
            if state.get('not_found') is True and not state.get('incomplete') and not state.get('error_code') and not state.get('items'):
                row.update(contract='no', contract_label='Aucun contrat identifié', contract_detail='Aucun contrat trouvé lors de la dernière recherche WEDOF.')
    return bool(api_key)


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
    today = datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    schedules = []
    for source in item.get('schedules', []):
        row = dict(source)
        total, paid, pending = (cents(row.get(k)) for k in ('montantTotal', 'montantRegle', 'montantEnCoursInstruction'))
        row['remaining'] = max(0, total-paid)/100 if total is not None and paid is not None else None
        if item.get('raw_stale'):
            row['status'], row['status_code'] = 'À vérifier', 'stale'
        elif total is not None and paid is not None and paid >= total:
            row['status'], row['status_code'] = 'Réglée', 'paid'
        elif pending is not None and pending > 0:
            row['status'], row['status_code'] = 'En instruction', 'pending'
        elif row.get('dateOuverture') and row['dateOuverture'] <= today:
            row['status'], row['status_code'] = 'Ouverte à facturation', 'open'
        elif row.get('dateOuverture'):
            row['status'], row['status_code'] = 'À venir', 'upcoming'
        else:
            row['status'], row['status_code'] = 'Non communiqué', 'unknown'
        row['paid_percent'] = min(100, max(0, round(paid/total*100))) if total and paid is not None else None
        schedules.append(row)
    def total(key):
        values = [cents(r.get(key)) for r in schedules]
        return sum(values)/100 if values and all(v is not None for v in values) else None
    amount, paid = total('montantTotal'), total('montantRegle')
    counts = {code: sum(r['status_code'] == code for r in schedules) for code in ('paid', 'pending', 'open', 'upcoming', 'stale', 'unknown')}
    next_due = next(iter(sorted((r for r in schedules if r['status_code'] in {'open', 'upcoming', 'pending'} and r.get('dateOuverture')),
                               key=lambda r: r['dateOuverture'])), None)
    return {'schedules': schedules, 'total': amount, 'paid': paid, 'pending': total('montantEnCoursInstruction'),
            'counts': counts, 'next_due': next_due,
            'paid_percent': min(100, max(0, round(cents(paid)/cents(amount)*100))) if amount and paid is not None and not item.get('raw_stale') else None,
            'remaining': max(0, cents(amount)-cents(paid))/100 if amount is not None and paid is not None else None}


class Client:
    def __init__(self, key, reserve, remember_limit):
        self.key, self.reserve, self.remember_limit = key, reserve, remember_limit

    def read(self, path, params=None):
        self.reserve()
        try:
            response = requests.get(BASE_URL + path, params=params,
                headers={'X-Api-Key': self.key, 'Accept': 'application/json', 'User-Agent': 'IntegraleAcademy-BTS/2026.10'},
                timeout=(3, 5), allow_redirects=False)
        except requests.RequestException:
            raise WedofError('WEDOF est momentanément injoignable. Les informations enregistrées sont conservées.', status=502) from None
        headers = {k.lower(): v for k, v in response.headers.items()} if isinstance(response.headers, Mapping) else {}
        if response.status_code == 429 or str(headers.get('x-ratelimit-remaining')) == '0':
            retry_at = retry_time(headers, time.time())
            self.remember_limit(retry_at)
            if response.status_code == 429:
                raise rate_limit_error(retry_at)
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

    def folders(self, candidate, *, by_name=False):
        params = {'state': 'all', 'limit': 100, 'page': 1}
        if by_name:
            name = str(candidate.get('nom') or '').strip()
            if len(norm(name)) < 2:
                return [], False
            params['query'] = name
        else:
            address = email(candidate.get('email'))
            if not address:
                return [], False
            params['findOtherFoldersOfAttendee'] = address
        raw, headers = self.read('/registrationFolders', params)
        if not isinstance(raw, list) or len(raw) > 100 or any(not isinstance(x, dict) for x in raw):
            raise WedofError('La liste des dossiers WEDOF est inattendue.')
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            total = int(headers.get('x-total-count', len(raw)))
            if total < len(raw) or int(headers.get('x-current-page', 1)) != 1:
                raise ValueError
        except (ValueError, TypeError):
            raise WedofError('La pagination WEDOF est incohérente.') from None
        found = {}
        seen = set()
        for folder in raw:
            key = folder.get('externalId')
            if folder.get('type') not in {'opcoCfa', 'opco'} or not isinstance(key, str) or not re.fullmatch(r'[\w.-]{1,120}', key):
                continue
            if key in seen:
                raise WedofError('La liste des dossiers WEDOF contient des doublons. Vérifiez la référence manuellement.')
            seen.add(key)
            fields = folder_fields(folder, key)
            check = identity(candidate, fields)['status']
            same_email = bool(email(candidate.get('email')) and email(candidate.get('email')) == email(fields.get('apprentice_email')))
            if check != 'mismatch' and (check == 'matched' if by_name else same_email):
                found[key] = {'registration_id': key, 'strong': automatic_identity(candidate, fields)}
        return list(found.values()), total > len(raw) or len(raw) == 100

    def details(self, item):
        data = dict(item)
        errors = []
        folder = item.get('registration_id', '')
        if folder and len(folder) <= 250 and not any(c in folder for c in '/\\?#\r\n'):
            try:
                raw, _ = self.read('/registrationFolders/' + quote(folder, safe=''))
                data.update(folder_fields(raw, folder))
            except WedofError as error:
                if error.code == 'rate_limited':
                    raise
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
            # Empty CERFA fields must not erase the verified folder identity.
            data.update({k: v for k, v in fields.items() if v not in ('', None) or not data.get(k)})
        except WedofError as error:
            if error.code in {'identity_conflict', 'rate_limited'}:
                raise
            data.update(raw_stale=True, raw_error=str(error), raw_identity_conflict=error.code == 'raw_identity_mismatch')
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
                response = jsonify(ok=False, message=str(error), code=error.code,
                                   retry_after=max(0, math.ceil(error.retry_at-time.time())) if error.retry_at else None)
                response.status_code = error.status
                if error.retry_at:
                    response.headers['Retry-After'] = str(max(1, math.ceil(error.retry_at-time.time())))
                return response
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
                cooldown = conn.execute('SELECT value FROM student_wedof_settings WHERE name=?', (limit_key,)).fetchone()
                if cooldown and float(cooldown['value']) > now:
                    raise rate_limit_error(float(cooldown['value']))
                conn.execute('DELETE FROM student_wedof_calls WHERE created_at<=?', (now-READ_WINDOW_SECONDS,))
                boundary = conn.execute('SELECT created_at FROM student_wedof_calls ORDER BY created_at DESC LIMIT 1 OFFSET ?',
                                        (READ_WINDOW_LIMIT-1,)).fetchone()
                if boundary:
                    raise rate_limit_error(boundary['created_at'] + READ_WINDOW_SECONDS)
                conn.execute('INSERT INTO student_wedof_calls VALUES(?)', (now,))
                conn.commit()
        limit_key = 'rate_limit:' + config_id(key)
        def remember_limit(retry_at):
            with closing(connection()) as conn:
                conn.execute('INSERT INTO student_wedof_settings VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                             (limit_key, str(retry_at)))
                conn.commit()
        try:
            yield Client(key, reserve, remember_limit)
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
        contracts = cards(cid)
        return jsonify(ok=True, configured=configured, has_contracts=bool(contracts),
                       html=render_template('_wedof_contracts_list.html', contracts=contracts, row=row, configured=configured))

    def discovery_state(conn, cid, fingerprint, manual, since=None):
        stored = conn.execute('SELECT * FROM student_wedof_discovery WHERE candidate_id=?', (cid,)).fetchone()
        if stored and stored['fingerprint'] == fingerprint:
            state = json.loads(stored['payload'])
            if state.get('suppressed') and not manual:
                return state, stored['updated_at']
            if since is not None and stored['updated_at'] < since:
                return {'step': 'email', 'items': [], 'folders': [], 'incomplete': False}, stored['updated_at']
            if not state.get('suppressed') and discovery_cache_valid(state, stored['updated_at'], manual):
                return state, stored['updated_at']
            if state.get('resume') and stored['updated_at'] > time.time()-CACHE_SECONDS:
                return state['resume'], stored['updated_at']
        return {'step': 'email', 'items': [], 'folders': [], 'incomplete': False}, stored['updated_at'] if stored else None

    def discovery_reply(cid, state, config, cached=False):
        items = state.get('items', []) if state['step'] == 'done' and not state.get('linked') else []
        token = None
        if items:
            with closing(connection()) as conn:
                token = save_preview(conn, cid, 'search', {'config': config, 'items': items})
        public_items = [{k: i.get(k) for k in ('working_contract_id', 'external_number', 'deca_number', 'employer_name', 'state_label')} for i in items]
        error = bool(state.get('error_code') or state.get('error_status'))
        message = str(rate_limit_error(state['retry_at'])) if state.get('retry_at', 0) > time.time() else state.get('message', 'Recherche des contrats WEDOF de cet étudiant…')
        return jsonify(ok=True, pending=state['step'] != 'done', linked=bool(state.get('linked')),
                       message=message + (' Résultat de la dernière vérification enregistrée.' if cached and not error and not state.get('suppressed') else ''),
                       retry_after=max(0, math.ceil(state.get('retry_at', 0)-time.time())),
                       token=token, items=public_items, cached=cached,
                       stop_sync=state.get('error_code') in {'http_401', 'http_403', 'http_429'} or state.get('error_status') in {429, 502, 503})

    def discover_step(cid, manual=False, since=None):
        row = candidate(cid)
        with closing(connection()) as conn:
            if conn.execute('SELECT 1 FROM student_wedof_contracts WHERE candidate_id=?', (cid,)).fetchone():
                return {'step': 'done', 'linked': True, 'items': [], 'message': 'Le contrat est déjà rattaché à cette fiche.'}, '', True
            config = config_id(get_key(app, conn))
            fingerprint = discovery_fingerprint(row, config)
            state, revision = discovery_state(conn, cid, fingerprint, manual, since)
        if state['step'] == 'done':
            return state, config, True
        # One bounded phase per request; never paginate the organism's catalogue.
        # The shared lease also prevents two tabs from advancing the same phase.
        with api_client() as client:
            with closing(connection()) as conn:
                state, revision = discovery_state(conn, cid, fingerprint, manual, since)
            if state['step'] == 'done':
                return state, config, True
            item_to_link = None
            resume = dict(state)
            try:
                if state['step'] in {'email', 'name'}:
                    folders, more = client.folders(row, by_name=state['step'] == 'name')
                    state['incomplete'] = state['incomplete'] or more or len(folders) > 5
                    if folders:
                        state.update(step='contracts', folders=folders[:5], message='Dossier étudiant trouvé. Recherche de ses contrats…')
                    elif state['step'] == 'email':
                        state.update(step='name', message='Aucun dossier trouvé par e-mail. Vérification de l’identité dans WEDOF…')
                    else:
                        state.update(step='done', not_found=not state['incomplete'], message='Aucun dossier d’apprentissage correspondant trouvé dans WEDOF. Vérifiez l’identité et l’e-mail de la fiche, ou recherchez une référence manuellement.')
                elif state['step'] == 'contracts':
                    folder = state['folders'][0]
                    items, more = client.page(folder=folder['registration_id'])
                    state['incomplete'] = state['incomplete'] or more
                    state['folders'] = state['folders'][1:]
                    by_id = {i['working_contract_id']: i for i in state['items']}
                    by_id.update({i['working_contract_id']: {**i, 'discovery_strong': folder['strong']} for i in items})
                    state['items'] = list(by_id.values())
                    if not state['folders']:
                        if len(state['items']) == 1 and not state['incomplete'] and state['items'][0]['discovery_strong']:
                            state.update(step='verify', message='Contrat trouvé. Vérification de l’identité et récupération des échéances…')
                        else:
                            state.update(step='done', not_found=not state['items'] and not state['incomplete'], message='Plusieurs contrats ou une identité à vérifier : sélectionnez le contrat à rattacher.' if state['items'] else 'Le dossier étudiant a été retrouvé, mais aucun contrat d’apprentissage n’y est disponible dans WEDOF.')
                        if state['incomplete']:
                            state['message'] = 'La recherche ne permet pas de choisir un contrat avec certitude. Vérifiez les propositions ou utilisez sa référence exacte.'
                elif state['step'] == 'verify':
                    selected = state['items'][0]
                    current = client.contract(selected['working_contract_id'])
                    if current['summary_hash'] != selected['summary_hash']:
                        raise WedofError('Le contrat a changé pendant la recherche. Vérifiez-le manuellement avant de le rattacher.')
                    item = client.details(current)
                    state.update(step='done', message='Contrat trouvé : vérifiez son identité avant de le rattacher.')
                    if automatic_identity(row, item) and not item.get('details_error') and not item.get('raw_identity_conflict'):
                        item_to_link = item
            except WedofError as error:
                state.update(step='done', items=[], not_found=False, error_code=error.code, error_status=error.status,
                             message=str(error), retry_at=error.retry_at or 0, resume=resume)
            with closing(connection()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                current_row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
                if not current_row:
                    abort(404)
                if discovery_fingerprint(dict(current_row), config_id(get_key(app, conn))) != fingerprint:
                    raise WedofError('La fiche ou la connexion WEDOF a changé. Relancez la recherche.', status=409)
                current_state = conn.execute('SELECT updated_at FROM student_wedof_discovery WHERE candidate_id=?', (cid,)).fetchone()
                if (current_state['updated_at'] if current_state else None) != revision:
                    raise WedofError('La recherche a été modifiée dans une autre fenêtre. Rechargez les contrats.', status=409)
                linked = conn.execute('SELECT 1 FROM student_wedof_contracts WHERE candidate_id=?', (cid,)).fetchone()
                if linked:
                    state.update(step='done', linked=True, items=[], message='Le contrat est déjà rattaché à cette fiche.')
                elif item_to_link:
                    try:
                        conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)',
                                     (item_to_link['working_contract_id'], cid, json.dumps(item_to_link, ensure_ascii=False), time.time(), stamp()))
                        state.update(linked=True, items=[], message='Contrat retrouvé et rattaché automatiquement après vérification de l’identité.')
                    except sqlite3.IntegrityError:
                        state.update(items=[], message='Ce contrat est déjà rattaché à un autre étudiant. Vérifiez les fiches avant de poursuivre.')
                conn.execute('INSERT INTO student_wedof_discovery VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,updated_at=excluded.updated_at',
                             (cid, fingerprint, json.dumps(state, ensure_ascii=False), time.time()))
                conn.commit()
        return state, config, False

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/detecter')
    @guarded
    def discover(cid):
        data = body()
        if data.get('origin') != 'interactive':
            candidate(cid)
            return jsonify(ok=True, pending=False, linked=bool(cards(cid)), items=[], cached=True,
                           message='La vérification automatique est programmée chaque jour à 8 h (heure de Paris).')
        state, config, cached = discover_step(cid, manual=data.get('manual') is True)
        return discovery_reply(cid, state, config, cached)

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

    def refresh_contract(cid, key, since=None):
        row, key = candidate(cid), identifier(key)
        with closing(connection()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            stored = conn.execute('SELECT * FROM student_wedof_contracts WHERE candidate_id=? AND contract_id=?', (cid, key)).fetchone()
            if not stored:
                abort(404)
            fresh_enough = stored['checked_at'] >= since if since is not None else time.time()-stored['checked_at'] < CACHE_SECONDS
            if not stored['error'] and fresh_enough:
                return dict(ok=True, message='Les dernières données sont conservées.', cached=True)
            if (not stored['error'].startswith('Le plafond interne de lectures WEDOF')
                    and time.time()-stored['last_attempt'] < ERROR_CACHE_SECONDS):
                raise WedofError('Une actualisation est en cours ou vient d’échouer. Réessayez dans quelques instants ; les données précédentes sont conservées.',
                                 code='refresh_pending', status=503, retry_at=stored['last_attempt']+ERROR_CACHE_SECONDS)
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
                conn.execute('UPDATE student_wedof_contracts SET error=?,payload=?,last_attempt=? WHERE candidate_id=? AND contract_id=?',
                             (str(error), json.dumps(old, ensure_ascii=False),
                              0 if error.code == 'rate_limited' else time.time(), cid, key))
                conn.commit()
            raise
        return dict(ok=True, message='Les informations disponibles ont été actualisées depuis WEDOF.')

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/<key>/actualiser')
    @guarded
    def refresh(cid, key):
        return jsonify(refresh_contract(cid, key))

    def sync_item(cid, key, since):
        if key:
            return refresh_contract(cid, key, since)
        state, _, _ = discover_step(cid, since=since)
        return {**state, 'pending': state['step'] != 'done'}

    from wedof_daily_sync import register_daily_sync
    register_daily_sync(app, connect, sync_item, lambda conn: bool(get_key(app, conn)))

    @bp.post('/admin/candidat/<cid>/contrats-apprentissage/<key>/detacher')
    @guarded
    def unlink(cid, key):
        row = candidate(cid)
        with closing(connection()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM student_wedof_contracts WHERE candidate_id=? AND contract_id=?', (cid, identifier(key)))
            # A deliberate unlink must survive a reload and the cache expiry.
            state = {'step': 'done', 'suppressed': True, 'items': [], 'message': 'Rattachement automatique suspendu après le retrait du lien. Utilisez « Rechercher automatiquement » pour le relancer.'}
            try:
                config = config_id(get_key(app, conn))
            except WedofError:
                config = config_id('')
            conn.execute('INSERT INTO student_wedof_discovery VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,updated_at=excluded.updated_at',
                         (cid, discovery_fingerprint(row, config), json.dumps(state), time.time()))
            conn.commit()
        return jsonify(ok=True, message='Le lien avec cette fiche a été retiré. Le contrat reste dans WEDOF.')

    app.register_blueprint(bp)
