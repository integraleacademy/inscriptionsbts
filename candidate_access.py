"""Candidate return access: identity lookup plus a short-lived email challenge.

The identity fields only locate a dossier. They never grant access on their own.
Codes and rate-limit identifiers are HMACed; no credentials are kept in cookies.
"""
from contextlib import closing
from datetime import date
import hashlib
import hmac
import ipaddress
import secrets
import time
import unicodedata

from flask import abort, redirect, render_template, request, session, url_for

CODE_TTL = 10 * 60
RATE_WINDOW = 15 * 60
MAX_CODE_TRIES = 5


def _normalized_name(value):
    value = unicodedata.normalize('NFKD', value or '')
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).casefold().replace('’', "'").split())


def _schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS candidate_access_challenges (
            id TEXT PRIMARY KEY, candidate_id TEXT, code_hash TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS candidate_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email_key TEXT NOT NULL,
            ip_key TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS candidate_access_email_time
            ON candidate_access_requests(email_key, created_at);
        CREATE INDEX IF NOT EXISTS candidate_access_ip_time
            ON candidate_access_requests(ip_key, created_at);
    ''')


def register_candidate_access(app, db_connect, send_mail):
    def require_configured_key():
        if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
            abort(503, 'La connexion à ton dossier est temporairement indisponible. Contacte notre équipe au 04 22 47 07 68.')

    def digest(value):
        key = app.secret_key
        if isinstance(key, str):
            key = key.encode('utf-8')
        return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()

    def csrf():
        if '_candidate_access_csrf' not in session:
            session['_candidate_access_csrf'] = secrets.token_urlsafe(32)
        return session['_candidate_access_csrf']

    def check_csrf():
        submitted = request.form.get('csrf_token', '')
        expected = session.get('_candidate_access_csrf', '')
        if not expected or not hmac.compare_digest(submitted.encode('utf-8'), expected.encode('utf-8')):
            abort(400, 'La page a expiré. Recharge-la avant de réessayer.')

    def page(template, **kwargs):
        response = app.make_response(render_template(template, csrf_token=csrf(), **kwargs))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.route('/espace/connexion', methods=['GET', 'POST'])
    def candidate_login():
        require_configured_key()
        error = ''
        values = {'nom': '', 'date_naissance': '', 'email': ''}
        if request.method == 'POST':
            check_csrf()
            values = {key: request.form.get(key, '').strip()[:254] for key in values}
            values['nom'] = values['nom'].upper()
            values['email'] = values['email'].lower()
            try:
                dob = date.fromisoformat(values['date_naissance']).isoformat()
                valid_dob = date.fromisoformat(dob) < date.today()
            except ValueError:
                valid_dob = False
            if not values['nom'] or not valid_dob or '@' not in values['email'] or any(c.isspace() for c in values['email']):
                error = 'Vérifie ton nom, ta date de naissance et ton adresse e-mail.'
            else:
                now = time.time()
                email_key = digest('email:' + values['email'])
                # Do not let caller-controlled forwarding headers bypass rate limits.
                ip = request.remote_addr or 'unknown'
                ip_key = digest('ip:' + ip)
                try:
                    public_ip = ipaddress.ip_address(ip).is_global
                except ValueError:
                    public_ip = False
                # A private peer may be Render's shared reverse proxy. Apply a
                # generous aggregate abuse cap there, not a per-person quota.
                ip_limit = 20 if public_ip else 200
                challenge = secrets.token_urlsafe(32)
                code = f'{secrets.randbelow(1000000):06d}'
                matched = None
                with closing(db_connect()) as conn:
                    _schema(conn)
                    conn.execute('BEGIN IMMEDIATE')
                    conn.execute('DELETE FROM candidate_access_requests WHERE created_at < ?', (now - 86400,))
                    conn.execute('DELETE FROM candidate_access_challenges WHERE expires_at < ?', (now - 3600,))
                    email_count = conn.execute('SELECT COUNT(*) FROM candidate_access_requests WHERE email_key=? AND created_at>?', (email_key, now - RATE_WINDOW)).fetchone()[0]
                    ip_count = conn.execute('SELECT COUNT(*) FROM candidate_access_requests WHERE ip_key=? AND created_at>?', (ip_key, now - RATE_WINDOW)).fetchone()[0]
                    allowed = email_count < 5 and ip_count < ip_limit
                    if allowed:
                        conn.execute('INSERT INTO candidate_access_requests(email_key,ip_key,created_at) VALUES(?,?,?)', (email_key, ip_key, now))
                        rows = conn.execute('SELECT id,nom,email,date_naissance FROM candidats WHERE lower(trim(email))=? ORDER BY COALESCE(rentree_annee,2026) DESC, created_at DESC', (values['email'],)).fetchall()
                        matched = next((dict(row) for row in rows if _normalized_name(row['nom']) == _normalized_name(values['nom']) and (row['date_naissance'] or '')[:10] == dob), None)
                    previous = session.get('_candidate_access_challenge')
                    if previous:
                        conn.execute('UPDATE candidate_access_challenges SET consumed=1 WHERE id=?', (previous,))
                    conn.execute('INSERT INTO candidate_access_challenges(id,candidate_id,code_hash,created_at,expires_at) VALUES(?,?,?,?,?)', (challenge, matched['id'] if matched else None, digest(challenge + ':' + code), now, now + CODE_TTL))
                    conn.commit()
                session['_candidate_access_challenge'] = challenge
                if matched:
                    html = f'''<!doctype html><html lang="fr"><body style="margin:0;padding:32px;background:#f6f2e9;font-family:Arial,sans-serif;color:#282722"><div style="max-width:520px;margin:auto;background:white;border-radius:20px;padding:36px"><p style="font-size:12px;letter-spacing:2px">INTÉGRALE ACADEMY · ESPACE CANDIDAT</p><h1 style="font-size:27px">Retrouve ton dossier.</h1><p>Voici ton code de connexion à usage unique :</p><p style="font-size:36px;font-weight:bold;letter-spacing:8px">{code}</p><p>Ce code expire dans 10 minutes. Ne le communique à personne.</p><p style="font-size:13px;color:#6b675f">Si tu n’es pas à l’origine de cette demande, tu peux ignorer ce message. Aucun accès n’a été accordé.</p></div></body></html>'''
                    try:
                        sent = send_mail(matched['email'], 'Ton code de connexion · Intégrale Academy', html)
                    except Exception:
                        sent = False
                    if sent is False:
                        with closing(db_connect()) as conn:
                            conn.execute('UPDATE candidate_access_challenges SET consumed=1 WHERE id=?', (challenge,))
                            conn.commit()
                        app.logger.warning('Candidate access email could not be delivered.')
                return redirect(url_for('candidate_verify'))
        return page('candidate_login.html', title='Retrouver mon dossier · Intégrale Academy', error=error, values=values)

    @app.route('/espace/verification', methods=['GET', 'POST'])
    def candidate_verify():
        require_configured_key()
        challenge = session.get('_candidate_access_challenge')
        if not challenge:
            return redirect(url_for('candidate_login'))
        error = ''
        if request.method == 'POST':
            check_csrf()
            code = request.form.get('code', '').strip()[:20]
            now = time.time()
            slug = None
            with closing(db_connect()) as conn:
                _schema(conn)
                conn.execute('BEGIN IMMEDIATE')
                record = conn.execute('SELECT * FROM candidate_access_challenges WHERE id=?', (challenge,)).fetchone()
                if record and not record['consumed'] and record['expires_at'] > now and record['attempts'] < MAX_CODE_TRIES:
                    conn.execute('UPDATE candidate_access_challenges SET attempts=attempts+1 WHERE id=?', (challenge,))
                    valid = len(code) == 6 and code.isascii() and code.isdigit() and hmac.compare_digest(digest(challenge + ':' + code), record['code_hash'])
                    if valid and record['candidate_id']:
                        person = conn.execute('SELECT id,slug_public FROM candidats WHERE id=?', (record['candidate_id'],)).fetchone()
                        if person:
                            slug = person['slug_public'] or secrets.token_urlsafe(24)
                            if not person['slug_public']:
                                conn.execute('UPDATE candidats SET slug_public=? WHERE id=?', (slug, person['id']))
                            conn.execute('UPDATE candidate_access_challenges SET consumed=1 WHERE id=?', (challenge,))
                conn.commit()
            if slug:
                session.pop('_candidate_access_challenge', None)
                session.pop('_candidate_access_csrf', None)
                response = redirect(url_for('espace_candidat', slug=slug))
                response.headers['Cache-Control'] = 'no-store'
                response.headers['Referrer-Policy'] = 'same-origin'
                return response
            error = 'Ce code est incorrect ou a expiré. Vérifie-le ou demande un nouveau code.'
        return page('candidate_verify.html', title='Ton code de connexion · Intégrale Academy', error=error)
