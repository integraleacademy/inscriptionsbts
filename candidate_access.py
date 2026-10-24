"""Student password access, initial DOB password and private email recovery.

Passwords use Werkzeug's salted scrypt hashes. Existing bearer links stay usable,
but never confer the authenticated session needed to change a password.
"""
from contextlib import closing
from datetime import date
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
import unicodedata

from flask import abort, redirect, render_template, request, session, url_for
from branded_email import render_branded_email
from werkzeug.security import check_password_hash, generate_password_hash

SESSION_TTL = 8 * 60 * 60
RESET_TTL = 30 * 60
RATE_WINDOW = 15 * 60
LOGIN_LIMIT = 10


def _normalized_name(value):
    value = unicodedata.normalize('NFKD', value or '')
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).casefold().replace('’', "'").split())


def _dob(value):
    try:
        parsed = date.fromisoformat((value or '')[:10])
        return parsed.strftime('%d%m%Y') if parsed < date.today() else None
    except (TypeError, ValueError):
        return None


def _schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS student_accounts (
            id TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            must_change INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS student_account_members (
            candidate_id TEXT PRIMARY KEY, account_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS student_account_members_account ON student_account_members(account_id);
        CREATE TABLE IF NOT EXISTS student_auth_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            identity_key TEXT NOT NULL, ip_key TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS student_auth_identity_time ON student_auth_requests(kind,identity_key,created_at);
        CREATE INDEX IF NOT EXISTS student_auth_ip_time ON student_auth_requests(ip_key,created_at);
        CREATE TABLE IF NOT EXISTS student_password_resets (
            token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL,
            version INTEGER NOT NULL, created_at REAL NOT NULL,
            expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
        );
    ''')


def _clear_student_session():
    for key in ('_student_auth', '_candidate_access_challenge', '_student_reset_hash', '_candidate_access_csrf'):
        session.pop(key, None)


def get_authenticated_student(app, db_connect, candidate_id=None, allow_initial=False):
    """Resolve a version-bound session; never infer authentication from a slug."""
    identity = session.get('_student_auth')
    if not isinstance(identity, dict) or not isinstance(identity.get('expires_at'), (int, float)) or identity['expires_at'] <= time.time():
        if identity:
            _clear_student_session()
        return None
    try:
        with closing(db_connect()) as conn:
            row = conn.execute('''SELECT a.id,a.version,a.must_change,c.id AS candidate_id,c.nom,c.slug_public
                FROM student_accounts a JOIN student_account_members m ON m.account_id=a.id
                JOIN candidats c ON c.id=m.candidate_id WHERE a.id=? AND c.id=?''',
                (identity.get('account_id'), candidate_id or identity.get('candidate_id'))).fetchone()
            if not row or row['version'] != identity.get('version'):
                _clear_student_session()
                return None
            if row['must_change'] and not allow_initial:
                return None
            return dict(account_id=row['id'], candidate_id=row['candidate_id'], nom=row['nom'],
                        slug_public=row['slug_public'], version=row['version'], must_change=bool(row['must_change']))
    except Exception as error:
        # Isolated test databases and startup before lazy schema creation fail closed.
        import sqlite3
        if isinstance(error, sqlite3.OperationalError):
            return None
        raise


def register_candidate_access(app, db_connect, send_mail):
    dummy_password_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    def require_configured_key():
        if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
            abort(503, 'La connexion à ton espace étudiant est temporairement indisponible. Contacte notre équipe au 04 22 47 07 68.')

    def digest(value):
        key = app.secret_key.encode('utf-8') if isinstance(app.secret_key, str) else app.secret_key
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
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def safe_redirect(endpoint, **kwargs):
        response = redirect(url_for(endpoint, **kwargs))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def limit(conn, kind, identity, maximum):
        now = time.time()
        identity_key = digest(kind + ':' + identity)
        ip = request.remote_addr or 'unknown'
        ip_key = digest('ip:' + ip)
        try:
            public_ip = ipaddress.ip_address(ip).is_global
        except ValueError:
            public_ip = False
        # Render may present a shared private reverse proxy rather than a client IP.
        ip_limit = 30 if public_ip else 300
        conn.execute('DELETE FROM student_auth_requests WHERE created_at<?', (now - 86400,))
        identity_count = conn.execute('SELECT COUNT(*) FROM student_auth_requests WHERE kind=? AND identity_key=? AND created_at>?', (kind, identity_key, now - RATE_WINDOW)).fetchone()[0]
        ip_count = conn.execute('SELECT COUNT(*) FROM student_auth_requests WHERE ip_key=? AND created_at>?', (ip_key, now - RATE_WINDOW)).fetchone()[0]
        if identity_count >= maximum or ip_count >= ip_limit:
            return False
        conn.execute('INSERT INTO student_auth_requests(kind,identity_key,ip_key,created_at) VALUES(?,?,?,?)', (kind, identity_key, ip_key, now))
        return True

    def grouped_accounts(conn, surname):
        rows = conn.execute('''SELECT id,nom,prenom,date_naissance,email,slug_public,rentree_annee,created_at
            FROM candidats ORDER BY COALESCE(rentree_annee,2026) DESC,created_at DESC''').fetchall()
        groups = {}
        for row in rows:
            if _normalized_name(row['nom']) != surname:
                continue
            person = dict(row)
            # First name matters: twins sharing surname, DOB and a parent's email are distinct.
            email = (person.get('email') or '').strip().casefold()
            identity = (surname, _normalized_name(person.get('prenom')), (person.get('date_naissance') or '')[:10], email or person['id'])
            groups.setdefault(identity, []).append(person)
        results = {}
        for people in groups.values():
            existing = []
            for person in people:
                account = conn.execute('SELECT a.* FROM student_accounts a JOIN student_account_members m ON m.account_id=a.id WHERE m.candidate_id=?', (person['id'],)).fetchone()
                if account and account['id'] not in [item['id'] for item in existing]:
                    existing.append(dict(account))
            if not existing:
                now = time.time()
                account_id = secrets.token_urlsafe(24)
                initial = _dob(people[0].get('date_naissance')) or secrets.token_urlsafe(32)
                password_hash = generate_password_hash(initial, method='scrypt')
                conn.execute('INSERT INTO student_accounts(id,password_hash,must_change,version,created_at,updated_at) VALUES(?,?,1,1,?,?)', (account_id, password_hash, now, now))
                existing = [dict(id=account_id,password_hash=password_hash,must_change=1,version=1)]
            if len(existing) == 1:
                account = existing[0]
                for person in people:
                    conn.execute('INSERT OR IGNORE INTO student_account_members(candidate_id,account_id) VALUES(?,?)', (person['id'], account['id']))
                results.setdefault(account['id'], (account, []))[1].extend(people)
            else:
                # Previously distinct accounts are never merged just because contact details changed.
                for account in existing:
                    members = []
                    for person in people:
                        member = conn.execute('SELECT account_id FROM student_account_members WHERE candidate_id=?', (person['id'],)).fetchone()
                        if member and member[0] == account['id']:
                            members.append(person)
                    results.setdefault(account['id'], (account, []))[1].extend(members)
        return list(results.values())

    def establish(account, person):
        _clear_student_session()
        session['_student_auth'] = dict(account_id=account['id'],candidate_id=person['id'],version=account['version'],expires_at=time.time()+SESSION_TTL)
        csrf()

    def password_error(password, confirmation):
        if len(password) < 12 or len(password) > 128 or password.isdecimal():
            return 'Choisis un mot de passe de 12 à 128 caractères, avec au moins une lettre. Une phrase est facile à retenir.'
        if not any(character.isalpha() for character in password):
            return 'Ajoute au moins une lettre à ton nouveau mot de passe.'
        if password != confirmation:
            return 'Les deux nouveaux mots de passe ne sont pas identiques.'
        return ''

    @app.context_processor
    def student_access_context():
        return dict(student_session=get_authenticated_student(app, db_connect), student_csrf_token=csrf())

    @app.route('/espace/connexion', methods=['GET', 'POST'])
    def candidate_login():
        require_configured_key()
        error, surname = '', ''
        if request.method == 'POST':
            check_csrf()
            _clear_student_session()
            surname = request.form.get('nom', '').strip()[:100]
            password = request.form.get('password', '')
            selected = None
            if surname and 1 <= len(password) <= 128:
                with closing(db_connect()) as conn:
                    _schema(conn)
                    conn.execute('BEGIN IMMEDIATE')
                    if limit(conn, 'login', _normalized_name(surname), LOGIN_LIMIT):
                        accounts = grouped_accounts(conn, _normalized_name(surname))
                        matches = [(account, people) for account, people in accounts if check_password_hash(account['password_hash'], password)]
                        if not accounts:
                            check_password_hash(dummy_password_hash, password)
                        # Never pick an arbitrary person when a surname/password pair is ambiguous.
                        if len(matches) == 1:
                            selected = matches[0]
                    conn.commit()
            if selected:
                account, people = selected
                establish(account, people[0])
                return safe_redirect('student_change_password' if account['must_change'] else 'student_dashboard')
            error = 'Nom ou mot de passe incorrect, ou accès temporairement limité. Vérifie tes informations ou utilise « Mot de passe oublié ». En cas de difficulté, contacte notre équipe.'
        return page('candidate_login.html', title='Espace étudiant · Intégrale Academy', error=error, surname=surname, reset_done=request.args.get('reset') == 'ok')

    @app.route('/espace/verification', methods=['GET', 'POST'])
    def candidate_verify():
        # Retired email-code login bookmarks return to the new two-field login.
        session.pop('_candidate_access_challenge', None)
        return safe_redirect('candidate_login')

    @app.get('/espace/mon-dossier')
    def student_dashboard():
        person = get_authenticated_student(app, db_connect, allow_initial=True)
        if not person:
            return safe_redirect('candidate_login')
        if person['must_change']:
            return safe_redirect('student_change_password')
        slug = person['slug_public']
        if not slug:
            slug = secrets.token_urlsafe(24)
            with closing(db_connect()) as conn:
                conn.execute('UPDATE candidats SET slug_public=? WHERE id=? AND (slug_public IS NULL OR slug_public=?)', (slug,person['candidate_id'],''))
                conn.commit()
                slug = conn.execute('SELECT slug_public FROM candidats WHERE id=?',(person['candidate_id'],)).fetchone()[0]
        return safe_redirect('espace_candidat', slug=slug)

    @app.route('/espace/mot-de-passe', methods=['GET', 'POST'])
    def student_change_password():
        require_configured_key()
        person = get_authenticated_student(app, db_connect, allow_initial=True)
        if not person:
            return safe_redirect('candidate_login')
        error = ''
        if request.method == 'POST':
            check_csrf()
            current = request.form.get('current_password', '')
            password = request.form.get('new_password', '')
            error = password_error(password, request.form.get('confirm_password', ''))
            if not error:
                with closing(db_connect()) as conn:
                    _schema(conn)
                    conn.execute('BEGIN IMMEDIATE')
                    account = conn.execute('SELECT * FROM student_accounts WHERE id=?', (person['account_id'],)).fetchone()
                    if not limit(conn,'change',person['account_id'],5) or len(current)>128 or not account or account['version'] != person['version'] or not check_password_hash(account['password_hash'],current):
                        error = 'Le mot de passe actuel est incorrect ou les tentatives sont temporairement limitées.'
                    elif check_password_hash(account['password_hash'], password):
                        error = 'Choisis un nouveau mot de passe différent du mot de passe actuel.'
                    else:
                        version = account['version'] + 1
                        conn.execute('UPDATE student_accounts SET password_hash=?,must_change=0,version=?,updated_at=? WHERE id=?', (generate_password_hash(password,method='scrypt'),version,time.time(),person['account_id']))
                        conn.execute('UPDATE student_password_resets SET consumed=1 WHERE account_id=?',(person['account_id'],))
                    conn.commit()
                if not error:
                    establish(dict(id=person['account_id'],version=version), dict(id=person['candidate_id']))
                    return safe_redirect('student_dashboard')
        return page('student_password.html', title='Mon mot de passe · Espace étudiant', error=error, initial=person['must_change'])

    @app.route('/espace/mot-de-passe-oublie', methods=['GET', 'POST'])
    def student_forgot_password():
        require_configured_key()
        sent = False
        if request.method == 'POST':
            check_csrf()
            surname = _normalized_name(request.form.get('nom','').strip()[:100])
            birth = request.form.get('date_naissance','').strip()[:10]
            matched = None
            if surname and _dob(birth):
                with closing(db_connect()) as conn:
                    _schema(conn)
                    conn.execute('BEGIN IMMEDIATE')
                    if limit(conn,'recovery',surname+':'+birth,5):
                        accounts = grouped_accounts(conn,surname)
                        matches = [(account,people) for account,people in accounts if any((p.get('date_naissance') or '')[:10]==birth for p in people)]
                        if len(matches)==1:
                            account,people=matches[0]
                            address=(people[0].get('email') or '').strip()
                            if '@' in address and not any(c.isspace() for c in address):
                                token=secrets.token_urlsafe(32)
                                token_hash=hashlib.sha256(token.encode()).hexdigest()
                                conn.execute('UPDATE student_password_resets SET consumed=1 WHERE account_id=?',(account['id'],))
                                conn.execute('DELETE FROM student_password_resets WHERE expires_at<?',(time.time()-86400,))
                                conn.execute('INSERT INTO student_password_resets(token_hash,account_id,version,created_at,expires_at) VALUES(?,?,?,?,?)',(token_hash,account['id'],account['version'],time.time(),time.time()+RESET_TTL))
                                matched=(address,token,token_hash)
                    conn.commit()
            if matched:
                address,token,token_hash=matched
                base=os.getenv('BASE_URL','https://inscriptionsbts.onrender.com').rstrip('/')
                link=base+url_for('student_reset_password',token=token)
                html=render_branded_email(
                    'Un nouveau mot de passe.',
                    '<p>Tu as demandé à réinitialiser ton mot de passe.</p>',
                    eyebrow='INTÉGRALE ACADEMY · ESPACE ÉTUDIANT',
                    accent_title='Reprenons le fil.',
                    preview_text='Retrouve l’accès à ton espace étudiant Intégrale Academy.',
                    action_url=link, action_label='Choisir mon nouveau mot de passe',
                    security_note='Ce lien personnel est valable 30 minutes et ne peut être utilisé qu’une fois. Si tu n’es pas à l’origine de cette demande, ignore ce message : ton mot de passe reste inchangé.')
                try:
                    delivered=send_mail(address,'Réinitialiser ton mot de passe · Espace étudiant',html)
                except Exception:
                    delivered=False
                if delivered is False:
                    with closing(db_connect()) as conn:
                        conn.execute('UPDATE student_password_resets SET consumed=1 WHERE token_hash=?',(token_hash,))
                        conn.commit()
                    app.logger.warning('Student password recovery email could not be delivered.')
            sent=True
        return page('student_forgot_password.html',title='Mot de passe oublié · Espace étudiant',sent=sent)

    @app.route('/espace/reinitialiser', methods=['GET', 'POST'])
    def student_reset_password():
        require_configured_key()
        # Remove the bearer token from the address bar before presenting a form.
        if request.method=='GET' and request.args.get('token'):
            token=request.args['token']
            session['_student_reset_hash']=hashlib.sha256(token.encode()).hexdigest() if 20<=len(token)<=128 else ''
            return safe_redirect('student_reset_password')
        token_hash=session.get('_student_reset_hash','')
        record=None
        with closing(db_connect()) as conn:
            _schema(conn)
            record=conn.execute('''SELECT r.*,a.version AS current_version FROM student_password_resets r
                JOIN student_accounts a ON a.id=r.account_id WHERE r.token_hash=?''',(token_hash,)).fetchone()
        valid=bool(record and not record['consumed'] and record['expires_at']>time.time() and record['version']==record['current_version'])
        error=''
        if request.method=='POST':
            check_csrf()
            password=request.form.get('new_password','')
            error=password_error(password,request.form.get('confirm_password',''))
            if valid and not error:
                with closing(db_connect()) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    # Recheck in the same write transaction: reset tokens are single-use under concurrency.
                    current=conn.execute('SELECT r.*,a.version AS current_version FROM student_password_resets r JOIN student_accounts a ON a.id=r.account_id WHERE r.token_hash=?',(token_hash,)).fetchone()
                    if current and not current['consumed'] and current['expires_at']>time.time() and current['version']==current['current_version']:
                        conn.execute('UPDATE student_accounts SET password_hash=?,must_change=0,version=version+1,updated_at=? WHERE id=?',(generate_password_hash(password,method='scrypt'),time.time(),current['account_id']))
                        conn.execute('UPDATE student_password_resets SET consumed=1 WHERE account_id=?',(current['account_id'],))
                        conn.commit()
                        _clear_student_session()
                        return safe_redirect('candidate_login',reset='ok')
                    conn.commit()
                    valid=False
        return page('student_reset_password.html',title='Nouveau mot de passe · Espace étudiant',valid=valid,error=error)

    @app.route('/espace/deconnexion', methods=['GET', 'POST'])
    def student_logout():
        if request.method != 'POST':
            abort(405)
        check_csrf()
        _clear_student_session()
        return safe_redirect('candidate_login')
