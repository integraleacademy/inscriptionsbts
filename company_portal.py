"""Employer accounts, explicit student grants and a factual attendance register.

Companies only receive a projection of their linked students, within the link's
period. No application documents, personal notes or medical reasons are exposed.
Every route/export rechecks grants and account version. Admin writes are atomic.
"""
from calendar import monthrange
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from zoneinfo import ZoneInfo

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from branded_email import render_branded_email
from planning import ensure_planning_schema
from planning_portal import get_portal_week, _requested_day
from company_registry import (EDITABLE_FIELDS, RegistryError, lookup_company,
                              normalize_siret, preview_token, read_preview, saved_registry)

PARIS = ZoneInfo('Europe/Paris')
STATUSES = ('confirmee', 'reconfirmee', 'rentree')
KINDS = {'absence': 'Absence', 'late': 'Retard'}
JUSTIFICATIONS = {'pending': 'En attente', 'justified': 'Justifié', 'unjustified': 'Non justifié'}
COMPANY_TABS = ('overview', 'information', 'registry', 'students', 'access')


def company_presentation(company):
    """Display-only metadata shared by the directory and company file."""
    if not company['active']:
        state, label = 'disabled', 'Désactivé'
    elif company.get('activated'):
        state, label = 'active', 'Activé'
    elif company.get('invited_at'):
        state, label = 'invited', 'Invitation envoyée'
    else:
        state, label = 'pending', 'À inviter'
    words = re.findall(r'\w+', company['name'], flags=re.UNICODE)
    company.update(access_state=state, access_label=label,
                   initials=''.join(word[0] for word in words[:2]).upper() or 'E')
    return company


def search_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def today():
    return datetime.now(PARIS).date()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_company_schema(conn):
    ensure_planning_schema(conn)
    # execute (not executescript) preserves the caller's transaction.
    for sql in (
        '''CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, phone TEXT NOT NULL DEFAULT '', siret TEXT NOT NULL DEFAULT '',
            password_hash TEXT, active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, invited_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS company_students (
            candidate_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT, tutor TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS company_students_company ON company_students(company_id)',
        '''CREATE TABLE IF NOT EXISTS company_tokens (
            token_hash TEXT PRIMARY KEY, company_id TEXT NOT NULL, version INTEGER NOT NULL,
            expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS company_requests (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity_key TEXT NOT NULL,
            ip_key TEXT NOT NULL, created_at REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS company_requests_time ON company_requests(created_at)',
        '''CREATE TABLE IF NOT EXISTS student_attendance (
            id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, date TEXT NOT NULL,
            start_min INTEGER NOT NULL, end_min INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('absence','late')),
            justification TEXT NOT NULL CHECK(justification IN ('pending','justified','unjustified')),
            version INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            CHECK(start_min>=0 AND end_min>start_min AND end_min<=1440))''',
        'CREATE INDEX IF NOT EXISTS student_attendance_student_date ON student_attendance(candidate_id,date)',
        '''CREATE TABLE IF NOT EXISTS company_audit (
            id INTEGER PRIMARY KEY, action TEXT NOT NULL, target_id TEXT NOT NULL,
            actor TEXT NOT NULL, created_at TEXT NOT NULL)''',
    ):
        conn.execute(sql)
    # Additive migration: existing accounts, passwords and grants are untouched.
    columns = {row[1] for row in conn.execute('PRAGMA table_info(companies)')}
    for name in [field[0] for field in EDITABLE_FIELDS] + ['registry_data']:
        if name not in columns:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def linked_students(conn, company_id):
    # A cancelled student is never exposed, even if a stale link remains.
    return [dict(row) for row in conn.execute('''SELECT c.id,c.nom,c.prenom,c.bts,c.rentree_annee,
        s.start_date,s.end_date,s.tutor,p.nom AS promotion_name
        FROM company_students s JOIN candidats c ON c.id=s.candidate_id
        LEFT JOIN student_promotions sp ON sp.candidate_id=c.id
        LEFT JOIN promotions p ON p.id=sp.promotion_id AND p.active=1
            AND p.bts=upper(trim(c.bts)) AND p.rentree_annee=COALESCE(c.rentree_annee,2026)
        WHERE s.company_id=? AND lower(trim(c.statut)) IN (?,?,?)
        AND (s.end_date IS NULL OR s.end_date>=?) ORDER BY c.nom,c.prenom''',
        (company_id, *STATUSES, today().isoformat()))]


def scoped_week(conn, student, day):
    week = get_portal_week(conn, 'student', student['id'], day)
    def allowed(day):
        return day >= student['start_date'] and (not student['end_date'] or day <= student['end_date'])
    week['courses'] = [c for c in week['courses'] if allowed(c['date'])]
    for day in week['days']:
        if not allowed(day['date']):
            day.update(courses=[], kind='unconfigured', day_label='Hors période de rattachement', public_holiday=False)
    minutes = sum(c['duration_minutes'] for c in week['courses'])
    week['summary'] = dict(courses=len(week['courses']), hours=minutes/60, minutes=minutes)
    week['heading'] = 'Planning de ' + student['prenom'] + ' ' + student['nom']
    return week


def attendance_rows(conn, start, end, students=None):
    query = '''SELECT a.id,a.candidate_id,a.date,a.start_min,a.end_min,a.kind,a.justification,a.version,
        c.nom,c.prenom,c.bts FROM student_attendance a JOIN candidats c ON c.id=a.candidate_id
        WHERE a.deleted=0 AND a.date BETWEEN ? AND ?'''
    args = [start, end]
    if students is not None:
        if not students:
            return []
        # SQL scopes first, then each record is clipped to its own grant period.
        query += ' AND a.candidate_id IN (' + ','.join('?' for _ in students) + ')'
        args.extend(s['id'] for s in students)
    query += ' ORDER BY a.date DESC,a.start_min,c.nom,c.prenom'
    grants = {s['id']: s for s in students or []}
    rows = []
    for row in conn.execute(query, args):
        item = dict(row)
        if students is not None:
            grant = grants[item['candidate_id']]
            if item['date'] < grant['start_date'] or (grant['end_date'] and item['date'] > grant['end_date']):
                continue
        item.update(start=f"{item['start_min']//60:02}:{item['start_min']%60:02}",
                    end=f"{item['end_min']//60:02}:{item['end_min']%60:02}",
                    minutes=item['end_min']-item['start_min'], kind_label=KINDS[item['kind']],
                    justification_label=JUSTIFICATIONS[item['justification']])
        rows.append(item)
    return rows


def month_bounds(value):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', value or ''):
        raise ValueError('Choisissez un mois valide.')
    start = _requested_day(value+'-01')
    return start.isoformat(), date(start.year, start.month, monthrange(start.year, start.month)[1]).isoformat()


def register_company_portal(app, db_connect, send_mail, require_admin):
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    def configured():
        if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
            abort(503, 'L’espace entreprise est temporairement indisponible.')

    def csrf():
        if '_company_csrf' not in session:
            session['_company_csrf'] = secrets.token_urlsafe(32)
        return session['_company_csrf']

    def check_csrf():
        value, expected = request.form.get('csrf_token', ''), session.get('_company_csrf', '')
        if not expected or not hmac.compare_digest(value.encode(), expected.encode()):
            abort(400, 'La page a expiré. Rechargez-la avant de réessayer.')

    @app.after_request
    def company_headers(response):
        if request.path.startswith(('/entreprise', '/admin/entreprises', '/admin/assiduite')):
            response.headers.update({'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
            response.vary.add('Cookie')
        return response

    def page(template, **context):
        return render_template(template, csrf_token=csrf(), registry_fields=EDITABLE_FIELDS, **context)

    def audit(conn, action, target):
        conn.execute('INSERT INTO company_audit(action,target_id,actor,created_at) VALUES(?,?,?,?)',
                     (action, target, 'admin', now_iso()))

    def admin_guard():
        configured()
        if not require_admin():
            abort(403)
        if request.method == 'POST':
            check_csrf()

    def identity(conn):
        configured()
        auth = session.get('_company_auth')
        if not isinstance(auth, dict) or not isinstance(auth.get('expires_at'), (int, float)) or auth['expires_at'] <= time.time():
            session.pop('_company_auth', None)
            return None
        row = conn.execute('SELECT id,name,contact,email,phone,version,active,password_hash FROM companies WHERE id=?', (auth.get('company_id'),)).fetchone()
        if not row or not row['active'] or not row['password_hash'] or row['version'] != auth.get('version'):
            session.pop('_company_auth', None)
            return None
        return {k: row[k] for k in ('id', 'name', 'contact', 'email', 'phone')}

    def limit(conn, kind, value, maximum):
        key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
        digest = lambda text: hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
        identity_key, ip_key = digest(kind+':'+value), digest(request.remote_addr or 'unknown')
        now = time.time()
        conn.execute('DELETE FROM company_requests WHERE created_at<?', (now-86400,))
        count = conn.execute('SELECT COUNT(*) FROM company_requests WHERE kind=? AND identity_key=? AND created_at>?', (kind, identity_key, now-900)).fetchone()[0]
        ip_count = conn.execute('SELECT COUNT(*) FROM company_requests WHERE ip_key=? AND created_at>?', (ip_key, now-900)).fetchone()[0]
        if count >= maximum or ip_count >= 100:
            return False
        conn.execute('INSERT INTO company_requests(kind,identity_key,ip_key,created_at) VALUES(?,?,?,?)', (kind, identity_key, ip_key, now))
        return True

    def access_token(conn, company):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        conn.execute('UPDATE company_tokens SET consumed=1 WHERE company_id=?', (company['id'],))
        ttl = 1800 if company['password_hash'] else 72*3600
        conn.execute('INSERT INTO company_tokens(token_hash,company_id,version,expires_at) VALUES(?,?,?,?)', (digest, company['id'], company['version'], time.time()+ttl))
        return token, digest, ttl

    def deliver(company, token, digest, ttl):
        base = os.getenv('BASE_URL', 'https://inscriptionsbts.onrender.com').rstrip('/')
        link = base + url_for('company_accept_token', token=token)
        html = render_branded_email('Votre espace entreprise.',
            '<p>Choisissez votre mot de passe pour retrouver vos alternants, leur planning de formation et le suivi des absences et retards renseignés par l’école.</p>',
            eyebrow='INTÉGRALE ACADEMY · ENTREPRISES', action_url=link, action_label='Choisir mon mot de passe',
            security_note='Ce lien est personnel, à usage unique et valable '+('30 minutes.' if ttl == 1800 else '72 heures.'))
        try:
            sent = send_mail(company['email'], 'Votre accès entreprise · Intégrale Academy', html)
        except Exception:
            sent = False
        with closing(db_connect()) as conn:
            if sent:
                conn.execute('UPDATE companies SET invited_at=? WHERE id=?', (now_iso(), company['id']))
            else:
                conn.execute('UPDATE company_tokens SET consumed=1 WHERE token_hash=?', (digest,))
            conn.commit()
        return bool(sent)

    def company_fields(current=None):
        values = {key: request.form.get(key, '').strip() for key in ('name', 'contact', 'email', 'phone', 'siret')}
        values['email'] = values['email'].lower()
        values['siret'] = normalize_siret(values['siret']) if values['siret'] else ''
        if not values['name'] or not values['contact'] or max(len(values['name']), len(values['contact'])) > 150:
            raise ValueError('Indiquez le nom de l’entreprise et le contact (150 caractères maximum).')
        if len(values['email']) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', values['email']):
            raise ValueError('Indiquez une adresse e-mail valide.')
        if len(values['phone']) > 40 or (values['siret'] and not re.fullmatch(r'\d{14}', values['siret'])):
            raise ValueError('Vérifiez le téléphone et le SIRET (14 chiffres, facultatif).')
        if any(ord(c) < 32 for value in values.values() for c in value):
            raise ValueError('Les coordonnées contiennent un caractère invalide.')
        for name, label, maximum in EDITABLE_FIELDS:
            value = request.form.get(name, current.get(name, '') if current else '').strip()
            if len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError(f'Vérifiez le champ « {label} » ({maximum} caractères maximum).')
            values[name] = value
        token = request.form.get('registry_token', '').strip()
        if token:
            registry = read_preview(app.secret_key, token, values['siret'])
            values['registry_data'] = json.dumps(registry, ensure_ascii=False)
        elif current and current['siret'] == values['siret']:
            values['registry_data'] = current['registry_data']
        else:
            values['registry_data'] = ''
        return values

    def admin_company(conn, company_id):
        row = conn.execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone()
        if not row:
            abort(404)
        company = dict(row)
        company['activated'] = bool(company.pop('password_hash'))
        company['registry'] = saved_registry(company['registry_data'])
        return company_presentation(company)

    def version_check(current):
        if request.form.get('version') != str(current['version']):
            abort(409, 'Cette fiche a été modifiée. Rechargez-la avant de réessayer.')

    @app.get('/admin/entreprises/recherche-siret')
    def admin_company_registry():
        admin_guard()
        try:
            if len(request.args.getlist('siret')) != 1:
                raise RegistryError('Saisissez un seul SIRET composé de 14 chiffres.', 400)
            siret = normalize_siret(request.args['siret'])
            data = lookup_company(siret)
            return jsonify(**data, token=preview_token(app.secret_key, data))
        except RegistryError as exc:
            response = jsonify(error=str(exc))
            if exc.status == 429:
                response.headers['Retry-After'] = '60'
            return response, exc.status

    @app.route('/admin/entreprises', methods=['GET', 'POST'])
    def admin_companies():
        if request.method == 'GET' and not require_admin() and 'login' in app.view_functions:
            return redirect(url_for('login'))
        admin_guard()
        error = ''
        creating = request.args.get('view') == 'create' or request.method == 'POST'
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            if request.method == 'POST':
                try:
                    values = company_fields()
                    cid = secrets.token_urlsafe(24)
                    conn.execute('INSERT INTO companies(id,'+','.join(values)+',created_at,updated_at) VALUES('+','.join('?' for _ in range(len(values)+3))+')',
                                 (cid, *values.values(), now_iso(), now_iso()))
                    audit(conn, 'company_created', cid)
                    conn.commit()
                    flash('Entreprise créée. Rattachez ses alternants puis envoyez son invitation.', 'success')
                    return redirect(url_for('admin_company_detail', company_id=cid), code=303)
                except ValueError as exc:
                    error = str(exc)
                except sqlite3.IntegrityError:
                    conn.rollback()
                    error = 'Cette adresse e-mail possède déjà un espace entreprise.'
            companies = [company_presentation(dict(row)) for row in conn.execute('''SELECT e.id,e.name,e.contact,e.email,e.phone,e.siret,e.city,e.active,e.invited_at,
                (e.password_hash IS NOT NULL) AS activated,(SELECT COUNT(*) FROM company_students s
                  JOIN candidats c ON c.id=s.candidate_id WHERE s.company_id=e.id
                  AND lower(trim(c.statut)) IN (?,?,?) AND (s.end_date IS NULL OR s.end_date>=?)) AS student_count
                FROM companies e ORDER BY e.name''', (*STATUSES, today().isoformat()))]
        if creating:
            return page('company_create.html', title='Nouvelle entreprise · Intégrale Academy', error=error), 400 if error else 200
        stats = dict(total=len(companies), students=sum(c['student_count'] for c in companies),
                     pending=sum(c['access_state'] in ('pending', 'invited') for c in companies))
        query = request.args.get('q', '').strip()[:200]
        access = request.args.get('access', 'all')
        order = request.args.get('order', 'name')
        if access not in ('all', 'active', 'invited', 'pending', 'awaiting', 'disabled') or order not in ('name', 'name_desc', 'students'):
            abort(400, 'Choisissez un filtre valide.')
        if query:
            terms = search_key(query).split()
            companies = [c for c in companies if all(term in search_key(' '.join(c.get(key) or '' for key in ('name','contact','email','phone','siret','city'))) for term in terms)]
        if access == 'awaiting':
            companies = [c for c in companies if c['access_state'] in ('pending', 'invited')]
        elif access != 'all':
            companies = [c for c in companies if c['access_state'] == access]
        companies.sort(key=lambda c: (-c['student_count'], search_key(c['name'])) if order == 'students' else search_key(c['name']), reverse=order == 'name_desc')
        total = len(companies)
        pages = max(1, (total+19)//20)
        requested_page = request.args.get('page', '1')
        if not re.fullmatch(r'[0-9]{1,6}', requested_page):
            abort(400, 'Numéro de page invalide.')
        current_page = min(pages, max(1, int(requested_page)))
        start = (current_page-1)*20
        return page('company_admin.html', title='Entreprises · Intégrale Academy', companies=companies[start:start+20],
                    stats=stats, query=query, access=access, order=order, result_count=total,
                    current_page=current_page, page_count=pages, first_result=start+1 if total else 0,
                    last_result=min(start+20,total))

    @app.route('/admin/entreprises/<company_id>', methods=['GET', 'POST'])
    def admin_company_detail(company_id):
        admin_guard()
        error = ''
        selected_tab = request.args.get('tab', 'overview')
        if selected_tab not in COMPANY_TABS:
            abort(400, 'Cet onglet n’existe pas.')
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            if request.method == 'POST':
                conn.execute('BEGIN IMMEDIATE')
                company = admin_company(conn, company_id)
                version_check(company)
                try:
                    values = company_fields(company)
                    changed_email = values['email'] != company['email']
                    conn.execute('UPDATE companies SET '+','.join(key+'=?' for key in values)+',version=version+1,updated_at=? WHERE id=?',
                                 (*values.values(), now_iso(), company_id))
                    if changed_email:
                        conn.execute('UPDATE companies SET password_hash=NULL,invited_at=NULL WHERE id=?', (company_id,))
                    conn.execute('UPDATE company_tokens SET consumed=1 WHERE company_id=?', (company_id,))
                    audit(conn, 'company_updated', company_id)
                    conn.commit()
                    flash('Coordonnées enregistrées.' + (' Envoyez une nouvelle invitation à la nouvelle adresse.' if changed_email else ''), 'success')
                    return redirect(url_for('admin_company_detail', company_id=company_id, tab='information'), code=303)
                except ValueError as exc:
                    error = str(exc)
                    conn.rollback()
                except sqlite3.IntegrityError:
                    error = 'Cette adresse e-mail possède déjà un espace entreprise.'
                    conn.rollback()
            company = admin_company(conn, company_id)
            students = [dict(row) for row in conn.execute('''SELECT c.id,c.nom,c.prenom,c.bts,c.statut,c.rentree_annee,s.start_date,s.end_date,s.tutor,s.updated_at
                FROM company_students s JOIN candidats c ON c.id=s.candidate_id WHERE s.company_id=? ORDER BY c.nom,c.prenom''', (company_id,))]
            available = [dict(row) for row in conn.execute('''SELECT c.id,c.nom,c.prenom,c.bts,c.rentree_annee FROM candidats c
                WHERE lower(trim(c.statut)) IN (?,?,?) AND NOT EXISTS (SELECT 1 FROM company_students s WHERE s.candidate_id=c.id)
                ORDER BY c.nom,c.prenom''', STATUSES)]
        day = today().isoformat()
        for student in students:
            if (student['statut'] or '').strip().lower() not in STATUSES:
                student['link_state'], student['link_label'] = 'ended', 'Inscription non confirmée'
            elif student['end_date'] and student['end_date'] < day:
                student['link_state'], student['link_label'] = 'ended', 'Terminé'
            elif student['start_date'] > day:
                student['link_state'], student['link_label'] = 'future', 'À venir'
            else:
                student['link_state'], student['link_label'] = 'current', 'En cours'
        edit_id, remove_id = request.args.get('edit', ''), request.args.get('remove', '')
        if any(value and value not in {s['id'] for s in students} for value in (edit_id, remove_id)):
            abort(404)
        return page('company_detail.html', title=company['name']+' · Entreprise', company=company,
                    students=students, available=available, error=error, today=day,
                    selected_tab='information' if error else selected_tab, edit_id=edit_id, remove_id=remove_id,
                    show_link_form=request.args.get('add') == '1' or not students,
                    confirm_status=request.args.get('confirm') == 'status',
                    current_students=[s for s in students if s['link_state'] != 'ended']), 400 if error else 200

    @app.post('/admin/entreprises/<company_id>/statut')
    def admin_company_status(company_id):
        admin_guard()
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            company = admin_company(conn, company_id)
            version_check(company)
            conn.execute('UPDATE companies SET active=?,version=version+1,updated_at=? WHERE id=?', (0 if company['active'] else 1, now_iso(), company_id))
            conn.execute('UPDATE company_tokens SET consumed=1 WHERE company_id=?', (company_id,))
            audit(conn, 'company_status_changed', company_id)
            conn.commit()
        flash('Statut du compte modifié. Les anciennes sessions et invitations sont révoquées.', 'success')
        return redirect(url_for('admin_company_detail', company_id=company_id, tab='access'), code=303)

    @app.post('/admin/entreprises/<company_id>/invitation')
    def admin_company_invite(company_id):
        admin_guard()
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            company = conn.execute('SELECT * FROM companies WHERE id=? AND active=1', (company_id,)).fetchone()
            if not company:
                abort(404)
            if not limit(conn, 'invite', company_id, 5):
                abort(429, 'Réessayez dans 15 minutes.')
            token, digest, ttl = access_token(conn, company)
            audit(conn, 'company_invited', company_id)
            conn.commit()
        sent = deliver(company, token, digest, ttl)
        flash('Invitation envoyée à '+company['email']+'.' if sent else 'L’e-mail n’a pas pu être envoyé. Réessayez plus tard.', 'success' if sent else 'error')
        return redirect(url_for('admin_company_detail', company_id=company_id, tab='access'), code=303)

    @app.post('/admin/entreprises/<company_id>/alternants')
    def admin_company_link(company_id):
        admin_guard()
        candidate_id = request.form.get('candidate_id', '')
        try:
            start = _requested_day(request.form.get('start_date')).isoformat()
            end = _requested_day(request.form['end_date']).isoformat() if request.form.get('end_date') else None
            if end and end < start:
                raise ValueError('La fin du rattachement doit suivre son début.')
            tutor = request.form.get('tutor', '').strip()
            if len(tutor) > 150:
                raise ValueError('Le nom du tuteur est limité à 150 caractères.')
        except ValueError as exc:
            abort(400, str(exc))
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            admin_company(conn, company_id)
            student = conn.execute('SELECT statut FROM candidats WHERE id=?', (candidate_id,)).fetchone()
            if not student or (student['statut'] or '').strip().lower() not in STATUSES:
                abort(400, 'Sélectionnez un étudiant dont l’inscription est confirmée.')
            previous = conn.execute('SELECT * FROM company_students WHERE candidate_id=?', (candidate_id,)).fetchone()
            if previous and previous['company_id'] != company_id:
                abort(409, 'Cet alternant est déjà rattaché à une autre entreprise. Retirez d’abord son ancien rattachement.')
            if previous and request.form.get('expected_updated_at') != previous['updated_at']:
                abort(409, 'Ce rattachement a changé. Rechargez la page.')
            conn.execute('INSERT INTO company_students(candidate_id,company_id,start_date,end_date,tutor,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date,tutor=excluded.tutor,updated_at=excluded.updated_at',
                         (candidate_id, company_id, start, end, tutor, now_iso()))
            audit(conn, 'student_linked:'+company_id, candidate_id)
            conn.commit()
        flash('Rattachement enregistré. Le planning et les absences sont visibles sur cette période.', 'success')
        return redirect(url_for('admin_company_detail', company_id=company_id, tab='students'), code=303)

    @app.post('/admin/entreprises/<company_id>/alternants/<candidate_id>/retirer')
    def admin_company_unlink(company_id, candidate_id):
        admin_guard()
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            count = conn.execute('DELETE FROM company_students WHERE company_id=? AND candidate_id=? AND updated_at=?',
                                 (company_id, candidate_id, request.form.get('expected_updated_at', ''))).rowcount
            if not count:
                abort(409, 'Ce rattachement a changé. Rechargez la page.')
            audit(conn, 'student_unlinked:'+company_id, candidate_id)
            conn.commit()
        flash('Rattachement retiré. L’entreprise n’a plus accès à cet alternant.', 'success')
        return redirect(url_for('admin_company_detail', company_id=company_id, tab='students'), code=303)

    @app.route('/entreprise/connexion', methods=['GET', 'POST'])
    def company_login():
        configured()
        error, email = '', ''
        if request.method == 'POST':
            check_csrf()
            session.pop('_company_auth', None)
            email = request.form.get('email', '').strip().lower()[:254]
            password = request.form.get('password', '')
            authenticated = None
            with closing(db_connect()) as conn:
                ensure_company_schema(conn)
                conn.commit()
                conn.execute('BEGIN IMMEDIATE')
                if limit(conn, 'login', email, 10) and 1 <= len(password) <= 128:
                    company = conn.execute('SELECT * FROM companies WHERE email=?', (email,)).fetchone()
                    valid = check_password_hash(company['password_hash'] if company and company['active'] and company['password_hash'] else dummy_hash, password)
                    if valid and company and company['active'] and company['password_hash']:
                        authenticated = dict(company)
                conn.commit()
            if authenticated:
                session['_company_auth'] = dict(company_id=authenticated['id'], version=authenticated['version'], expires_at=time.time()+8*3600)
                session['_company_csrf'] = secrets.token_urlsafe(32)
                return redirect(url_for('company_dashboard'), code=303)
            error = 'Adresse e-mail ou mot de passe incorrect, ou accès temporairement limité.'
        return page('company_auth.html', title='Espace entreprise · Intégrale Academy', mode='login', email=email, error=error, reset_done=request.args.get('reset')=='ok')

    @app.route('/entreprise/mot-de-passe-oublie', methods=['GET', 'POST'])
    def company_forgot_password():
        configured()
        if request.method == 'POST':
            check_csrf()
            email = request.form.get('email', '').strip().lower()[:254]
            matched = None
            with closing(db_connect()) as conn:
                ensure_company_schema(conn)
                conn.commit()
                conn.execute('BEGIN IMMEDIATE')
                if limit(conn, 'recovery', email, 5):
                    company = conn.execute('SELECT * FROM companies WHERE email=? AND active=1', (email,)).fetchone()
                    if company:
                        matched = (dict(company), *access_token(conn, company))
                conn.commit()
            if matched:
                deliver(*matched)
        return page('company_auth.html', title='Retrouver mon accès · Entreprise', mode='forgot', sent=request.method=='POST')

    @app.get('/entreprise/mot-de-passe/<token>')
    def company_accept_token(token):
        configured()
        session['_company_reset_hash'] = hashlib.sha256(token.encode()).hexdigest() if 20 <= len(token) <= 128 else ''
        return redirect(url_for('company_password'))

    @app.route('/entreprise/mot-de-passe', methods=['GET', 'POST'])
    def company_password():
        configured()
        error = ''
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            if request.method == 'POST':
                check_csrf()
                conn.execute('BEGIN IMMEDIATE')
            record = conn.execute('''SELECT t.*,e.version AS current_version,e.active FROM company_tokens t
                JOIN companies e ON e.id=t.company_id WHERE t.token_hash=?''', (session.get('_company_reset_hash', ''),)).fetchone()
            valid = bool(record and record['active'] and not record['consumed'] and record['expires_at'] > time.time() and record['version'] == record['current_version'])
            if request.method == 'POST' and valid:
                password = request.form.get('new_password', '')
                if not 12 <= len(password) <= 128 or not any(c.isalpha() for c in password):
                    error = 'Choisissez un mot de passe de 12 à 128 caractères contenant au moins une lettre.'
                elif password != request.form.get('confirm_password'):
                    error = 'Les deux mots de passe ne sont pas identiques.'
                else:
                    conn.execute('UPDATE companies SET password_hash=?,version=version+1,updated_at=? WHERE id=?',
                                 (generate_password_hash(password, method='scrypt'), now_iso(), record['company_id']))
                    conn.execute('UPDATE company_tokens SET consumed=1 WHERE company_id=?', (record['company_id'],))
                    conn.commit()
                    for key in ('_company_auth', '_company_reset_hash', '_company_csrf'):
                        session.pop(key, None)
                    return redirect(url_for('company_login', reset='ok'), code=303)
        return page('company_auth.html', title='Choisir mon mot de passe · Entreprise', mode='password', valid=valid, error=error)

    @app.post('/entreprise/deconnexion')
    def company_logout():
        check_csrf()
        for key in ('_company_auth', '_company_reset_hash', '_company_csrf'):
            session.pop(key, None)
        return redirect(url_for('company_login'), code=303)

    @app.get('/entreprise')
    @app.get('/entreprise/planning.pdf', endpoint='company_planning_pdf')
    @app.get('/entreprise/absences.csv', endpoint='company_attendance_csv')
    def company_dashboard():
        if set(request.args) - {'tab','student','date','month'} or any(len(v)!=1 for _,v in request.args.lists()):
            abort(400, 'Vérifiez les filtres sélectionnés.')
        tab = request.args.get('tab', 'students')
        if tab not in ('students','planning','attendance'):
            abort(400)
        try:
            month = request.args.get('month', today().strftime('%Y-%m'))
            start, end = month_bounds(month)
            selected_day = _requested_day(request.args.get('date'))
        except ValueError as exc:
            abort(400, str(exc))
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            company = identity(conn)
            if not company:
                return redirect(url_for('company_login'))
            students = linked_students(conn, company['id'])
            selected = request.args.get('student', '')
            if selected and selected not in {s['id'] for s in students}:
                abort(404)
            selected_student = next((s for s in students if s['id']==selected), None)
            if not selected_student and students and (tab=='planning' or request.path.endswith('.pdf')):
                selected_student = students[0]
                selected = selected_student['id']
            rows = attendance_rows(conn, start, end, [selected_student] if selected_student else students)
            week = scoped_week(conn, selected_student, selected_day) if selected_student and (tab=='planning' or request.path.endswith('.pdf')) else None
        if request.path.endswith('.pdf'):
            if not week:
                abort(404)
            from planning_pdf import build_portal_planning_pdf
            return send_file(BytesIO(build_portal_planning_pdf(week)), mimetype='application/pdf', as_attachment=True, download_name='planning-alternant-'+week['week_start']+'.pdf')
        if request.path.endswith('.csv'):
            buffer = StringIO()
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow(['Nom','Prénom','BTS','Date','Début','Fin','Type','Durée (minutes)','Justificatif'])
            def safe(value):
                value = str(value)
                return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
            for row in rows:
                writer.writerow([safe(row[k]) for k in ('nom','prenom','bts','date','start','end','kind_label','minutes','justification_label')])
            return send_file(BytesIO(buffer.getvalue().encode('utf-8-sig')), mimetype='text/csv; charset=utf-8', as_attachment=True, download_name='absences-alternants-'+month+'.csv')
        summary = dict(absences=sum(r['kind']=='absence' for r in rows), absent_minutes=sum(r['minutes'] for r in rows if r['kind']=='absence'),
                       late_minutes=sum(r['minutes'] for r in rows if r['kind']=='late'), pending=sum(r['justification']=='pending' for r in rows))
        return page('company_dashboard.html', title='Mes alternants · Espace entreprise', company=company, students=students, selected=selected,
                    selected_student=selected_student, active_tab=tab, week=week, rows=rows, summary=summary, month=month,
                    previous=(selected_day-timedelta(days=7)).isoformat(), following=(selected_day+timedelta(days=7)).isoformat())

    @app.route('/admin/assiduite', methods=['GET', 'POST'])
    def admin_attendance():
        admin_guard()
        error = ''
        try:
            month = request.args.get('month', today().strftime('%Y-%m'))
            start, end = month_bounds(month)
        except ValueError as exc:
            abort(400, str(exc))
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            if request.method == 'POST':
                conn.execute('BEGIN IMMEDIATE')
                try:
                    cid = request.form.get('candidate_id', '')
                    candidate = conn.execute('SELECT statut FROM candidats WHERE id=?', (cid,)).fetchone()
                    if not candidate or (candidate['statut'] or '').strip().lower() not in STATUSES:
                        raise ValueError('Sélectionnez un étudiant confirmé.')
                    day = _requested_day(request.form.get('date')).isoformat()
                    if day > today().isoformat():
                        raise ValueError('Une absence constatée ne peut pas être saisie dans le futur.')
                    def minute(key):
                        value = request.form.get(key, '')
                        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
                            raise ValueError('Indiquez des horaires valides.')
                        return int(value[:2])*60+int(value[3:])
                    begin, finish = minute('start'), minute('end')
                    kind, justification = request.form.get('kind'), request.form.get('justification')
                    if finish <= begin or kind not in KINDS or justification not in JUSTIFICATIONS:
                        raise ValueError('Vérifiez les horaires, le type et le statut du justificatif.')
                    record_id = request.form.get('record_id') or secrets.token_urlsafe(24)
                    current = conn.execute('SELECT * FROM student_attendance WHERE id=? AND deleted=0', (record_id,)).fetchone()
                    if request.form.get('record_id'):
                        if not current:
                            abort(404)
                        version_check(current)
                    overlap = conn.execute('SELECT id FROM student_attendance WHERE candidate_id=? AND date=? AND deleted=0 AND id<>? AND start_min<? AND end_min>?', (cid, day, record_id, finish, begin)).fetchone()
                    if overlap:
                        raise ValueError('Un événement existe déjà sur ce créneau pour cet étudiant. Corrigez la ligne existante.')
                    if current:
                        conn.execute('UPDATE student_attendance SET candidate_id=?,date=?,start_min=?,end_min=?,kind=?,justification=?,version=version+1,updated_at=? WHERE id=?', (cid, day, begin, finish, kind, justification, now_iso(), record_id))
                    else:
                        conn.execute('INSERT INTO student_attendance(id,candidate_id,date,start_min,end_min,kind,justification,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)', (record_id, cid, day, begin, finish, kind, justification, now_iso(), now_iso()))
                    audit(conn, 'attendance_updated' if current else 'attendance_created', record_id)
                    conn.commit()
                    flash('Événement enregistré. Le suivi entreprise est à jour.', 'success')
                    return redirect(url_for('admin_attendance', month=day[:7], student=cid), code=303)
                except ValueError as exc:
                    error = str(exc)
                    conn.rollback()
            students = [dict(r) for r in conn.execute('SELECT id,nom,prenom,bts FROM candidats WHERE lower(trim(statut)) IN (?,?,?) ORDER BY nom,prenom', STATUSES)]
            rows = attendance_rows(conn, start, end)
            selected = request.args.get('student', '')
            if selected:
                rows = [r for r in rows if r['candidate_id']==selected]
            edit = None
            if request.args.get('edit'):
                edit = next((r for r in rows if r['id']==request.args['edit']), None)
                if not edit:
                    abort(404)
        return page('company_attendance.html', title='Absences et retards · Administration', students=students, rows=rows, month=month, selected=selected,
                    edit=edit, error=error, today=today().isoformat(), kinds=KINDS, justifications=JUSTIFICATIONS), 400 if error else 200

    @app.post('/admin/assiduite/<record_id>/supprimer')
    def admin_attendance_delete(record_id):
        admin_guard()
        with closing(db_connect()) as conn:
            ensure_company_schema(conn)
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM student_attendance WHERE id=? AND deleted=0', (record_id,)).fetchone()
            if not row:
                abort(404)
            version_check(row)
            conn.execute('UPDATE student_attendance SET deleted=1,version=version+1,updated_at=? WHERE id=?', (now_iso(), record_id))
            audit(conn, 'attendance_deleted', record_id)
            conn.commit()
        flash('Événement retiré du suivi. La trace de correction est conservée.', 'success')
        return redirect(url_for('admin_attendance', month=row['date'][:7]), code=303)
