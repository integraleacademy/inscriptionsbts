"""Trainer accounts and narrowly scoped confirmed-student rosters.

This module never exposes candidate bearer links, uploads, identity documents,
health/identity numbers, birth dates or administrative record actions.
"""
from person_names import person_name
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import sqlite3
import time

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from branded_email import render_branded_email
from trainer_records import ensure_optional_trainer_email
from werkzeug.security import check_password_hash, generate_password_hash

from promotions import (BTS_LABELS, ensure_promotion_schema, list_promotions,
                        get_trainer_promotions, replace_trainer_promotions)
from trainer_workload import (WorkloadError, ensure_workload_schema,
                              get_trainer_workload, get_trainer_annual_workload, save_hourly_rate, MONTHS, _month_bounds)

SESSION_TTL = 8 * 60 * 60
ACTIVATION_TTL = 72 * 60 * 60
RESET_TTL = 30 * 60
RATE_WINDOW = 15 * 60


def _schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS trainers (
            id TEXT PRIMARY KEY, nom TEXT NOT NULL, prenom TEXT NOT NULL,
            email TEXT UNIQUE, password_hash TEXT,
            active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, invited_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trainer_assignments (
            trainer_id TEXT NOT NULL, bts TEXT NOT NULL, rentree_annee INTEGER NOT NULL,
            PRIMARY KEY(trainer_id,bts,rentree_annee)
        );
        CREATE TABLE IF NOT EXISTS trainer_access_tokens (
            token_hash TEXT PRIMARY KEY, trainer_id TEXT NOT NULL,
            purpose TEXT NOT NULL, version INTEGER NOT NULL,
            expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS trainer_access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            identity_key TEXT NOT NULL, ip_key TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS trainer_access_identity_time
            ON trainer_access_requests(kind,identity_key,created_at);
        CREATE INDEX IF NOT EXISTS trainer_access_ip_time
            ON trainer_access_requests(ip_key,created_at);
    ''')
    ensure_optional_trainer_email(conn)
    ensure_promotion_schema(conn)


def _clear_trainer_session():
    for key in ('_trainer_auth', '_trainer_csrf', '_trainer_reset_hash', '_trainer_preview'):
        session.pop(key, None)


def admin_trainer_preview():
    """A preview is an admin grant, never a replacement trainer login."""
    identity = session.get('_trainer_preview')
    guard = current_app.extensions.get('trainer_preview_admin_guard')
    if (isinstance(identity, dict) and guard and guard()
            and isinstance(identity.get('expires_at'), (int, float))
            and identity['expires_at'] > time.time()):
        return identity
    session.pop('_trainer_preview', None)
    return None


def get_authenticated_trainer(app, db_connect):
    preview = admin_trainer_preview()
    identity = preview or session.get('_trainer_auth')
    if not isinstance(identity, dict) or not isinstance(identity.get('expires_at'), (int, float)) or identity['expires_at'] <= time.time():
        if identity:
            session.pop('_trainer_auth', None)
        return None
    if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
        session.pop('_trainer_auth', None)
        return None
    try:
        with closing(db_connect()) as conn:
            _schema(conn)
            row = conn.execute('SELECT id,nom,prenom,email,active,version,password_hash FROM trainers WHERE id=?', (identity.get('trainer_id'),)).fetchone()
            if not row or (not preview and (not row['active'] or not row['password_hash'])) or row['version'] != identity.get('version'):
                session.pop('_trainer_preview' if preview else '_trainer_auth', None)
                return None
            return {key: row[key] for key in ('id','nom','prenom','email','version')}
    except sqlite3.OperationalError:
        return None


def register_trainer_access(app, db_connect, send_mail, require_admin):
    app.extensions['trainer_preview_admin_guard'] = require_admin
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    @app.before_request
    def protect_trainer_preview():
        if request.path.startswith('/formateur') and admin_trainer_preview() and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return jsonify(ok=False, message='Cet espace est ouvert en consultation. Modifiez les informations depuis l’administration.'), 403

    @app.context_processor
    def trainer_preview_context():
        return dict(trainer_admin_preview=admin_trainer_preview() if request.path.startswith('/formateur') else None)

    def require_configured_key():
        if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
            abort(503, 'La connexion à l’espace formateur est temporairement indisponible.')

    def digest(value):
        key = app.secret_key.encode('utf-8') if isinstance(app.secret_key, str) else app.secret_key
        return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()

    def csrf():
        if '_trainer_csrf' not in session:
            session['_trainer_csrf'] = secrets.token_urlsafe(32)
        return session['_trainer_csrf']

    def check_csrf():
        payload = request.get_json(silent=True) if request.is_json else request.form
        supplied = request.headers.get('X-CSRF-Token') or (payload.get('csrf_token','') if isinstance(payload,dict) or hasattr(payload,'get') else '')
        expected = session.get('_trainer_csrf','')
        if not isinstance(supplied,str) or not expected or not hmac.compare_digest(supplied.encode('utf-8'),expected.encode('utf-8')):
            abort(400, 'La page a expiré. Rechargez-la avant de réessayer.')

    def secure(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def page(template, **context):
        return secure(app.make_response(render_template(template,csrf_token=csrf(),**context)))

    def go(endpoint, **values):
        return secure(redirect(url_for(endpoint,**values)))

    def admin_guard():
        if not require_admin():
            abort(403)
        require_configured_key()

    def admin_reply(ok,message,status=200):
        if request.is_json or 'application/json' in request.headers.get('Accept',''):
            return secure(app.make_response((jsonify(ok=ok,message=message),status)))
        flash(message,'success' if ok else 'error')
        return secure(redirect(url_for('admin_trainers'),code=303))

    def payload():
        value=request.get_json(silent=True) if request.is_json else request.form
        return value if isinstance(value,dict) or hasattr(value,'getlist') else {}

    def assignments_from(data):
        if hasattr(data,'getlist'):
            raw=data.getlist('assignments') or data.getlist('assignments[]') or data.getlist('promotion_ids') or data.getlist('promotion_ids[]')
        else:
            raw=data.get('assignments',data.get('promotion_ids',[]))
        if not isinstance(raw,list) or len(raw)>60 or any(not isinstance(value,str) or not 1<=len(value)<=128 or ':' in value for value in raw):
            raise ValueError('Sélectionnez les promotions à attribuer à ce formateur.')
        return sorted(set(raw))

    def fields_from(data, allow_missing_email=False):
        if any(not isinstance(data.get(key,''),str) for key in ('nom','prenom','email')):
            raise ValueError('Vérifiez le nom, le prénom et l’adresse e-mail.')
        nom=data.get('nom','').strip().upper()
        prenom=data.get('prenom','').strip().title()
        email=data.get('email','').strip().lower()
        if not nom or not prenom or max(len(nom),len(prenom))>100 or any(ord(c)<32 for c in nom+prenom):
            raise ValueError('Indiquez un nom et un prénom valides (100 caractères maximum).')
        if (not email and not allow_missing_email) or (email and (len(email)>254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email))):
            raise ValueError('Indiquez une adresse e-mail valide.')
        return nom,prenom,email or None,assignments_from(data)

    def get_assignments(conn,trainer_id):
        return get_trainer_promotions(conn,trainer_id)

    def replace_assignments(conn,trainer_id,assignments):
        replace_trainer_promotions(conn,trainer_id,assignments)

    def limit(conn,kind,identity,maximum):
        now=time.time()
        identity_key=digest(kind+':'+identity)
        ip=request.remote_addr or 'unknown'
        ip_key=digest('ip:'+ip)
        try:
            public_ip=ipaddress.ip_address(ip).is_global
        except ValueError:
            public_ip=False
        ip_maximum=30 if public_ip else 300
        conn.execute('DELETE FROM trainer_access_requests WHERE created_at<?',(now-86400,))
        identity_count=conn.execute('SELECT COUNT(*) FROM trainer_access_requests WHERE kind=? AND identity_key=? AND created_at>?',(kind,identity_key,now-RATE_WINDOW)).fetchone()[0]
        ip_count=conn.execute('SELECT COUNT(*) FROM trainer_access_requests WHERE ip_key=? AND created_at>?',(ip_key,now-RATE_WINDOW)).fetchone()[0]
        if identity_count>=maximum or ip_count>=ip_maximum:
            return False
        conn.execute('INSERT INTO trainer_access_requests(kind,identity_key,ip_key,created_at) VALUES(?,?,?,?)',(kind,identity_key,ip_key,now))
        return True

    def create_access_token(conn,trainer,purpose):
        token=secrets.token_urlsafe(32)
        token_hash=hashlib.sha256(token.encode()).hexdigest()
        conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id=?',(trainer['id'],))
        conn.execute('DELETE FROM trainer_access_tokens WHERE expires_at<?',(time.time()-86400,))
        ttl=ACTIVATION_TTL if purpose=='activation' else RESET_TTL
        conn.execute('INSERT INTO trainer_access_tokens(token_hash,trainer_id,purpose,version,expires_at) VALUES(?,?,?,?,?)',(token_hash,trainer['id'],purpose,trainer['version'],time.time()+ttl))
        return token,token_hash

    def deliver_access(email,token,token_hash,purpose):
        base=os.getenv('BASE_URL','https://inscriptionsbts.onrender.com').rstrip('/')
        link=base+url_for('trainer_accept_token',token=token)
        activation=purpose=='activation'
        heading='Bienvenue dans votre espace formateur.' if activation else 'Un nouveau mot de passe.'
        intro='Votre compte formateur Intégrale Academy est prêt. Choisissez votre mot de passe pour consulter les étudiants des promotions qui vous sont affectées.' if activation else 'Vous avez demandé à réinitialiser votre mot de passe formateur.'
        button='Activer mon espace formateur' if activation else 'Choisir mon nouveau mot de passe'
        validity='72 heures' if activation else '30 minutes'
        html=render_branded_email(
            heading,
            '<p>' + intro + '</p>',
            eyebrow='INTÉGRALE ACADEMY · ESPACE FORMATEUR',
            accent_title='À vous de jouer.' if activation else 'Reprenons le fil.',
            preview_text='Votre accès personnel à Intégrale Academy est prêt.' if activation else 'Choisissez un nouveau mot de passe pour votre espace formateur.',
            action_url=link, action_label=button,
            security_note=f'Ce lien personnel est valable {validity} et ne peut être utilisé qu’une fois. Si vous n’êtes pas concerné par ce message, ignorez-le ou contactez notre équipe au 04 22 47 07 68.')
        try:
            sent=send_mail(email, 'Activez votre espace formateur · Intégrale Academy' if activation else 'Réinitialisation du mot de passe formateur · Intégrale Academy',html)
        except Exception:
            sent=False
        if not sent:
            with closing(db_connect()) as conn:
                conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE token_hash=?',(token_hash,))
                conn.commit()
            app.logger.warning('Trainer access email could not be delivered.')
            return False
        return True

    def password_error(password,confirmation):
        if not isinstance(password,str) or not 12<=len(password)<=128 or not any(c.isalpha() for c in password):
            return 'Choisissez un mot de passe de 12 à 128 caractères contenant au moins une lettre.'
        if password!=confirmation:
            return 'Les deux mots de passe ne sont pas identiques.'
        return ''

    @app.context_processor
    def trainer_context():
        return dict(trainer_session=get_authenticated_trainer(app,db_connect),trainer_csrf_token=csrf())

    @app.route('/admin/formateurs',methods=['GET','POST'])
    def admin_trainers():
        if request.method=='GET' and not require_admin() and 'login' in app.view_functions:
            return go('login',next=request.full_path.rstrip('?'))
        admin_guard()
        if request.method=='POST':
            check_csrf()
            try:
                nom,prenom,email,assignments=fields_from(payload())
            except ValueError as error:
                return admin_reply(False,str(error),400)
            try:
                with closing(db_connect()) as conn:
                    _schema(conn)
                    trainer_id=secrets.token_urlsafe(24)
                    now=datetime.now(timezone.utc).isoformat()
                    conn.execute('INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES(?,?,?,?,?,?)',(trainer_id,nom,prenom,email,now,now))
                    replace_assignments(conn,trainer_id,assignments)
                    conn.commit()
            except ValueError as error:
                return admin_reply(False,str(error),400)
            except sqlite3.IntegrityError:
                return admin_reply(False,'Cette adresse e-mail est déjà associée à un compte formateur.',409)
            return admin_reply(True,'Compte créé. Vous pouvez maintenant envoyer l’invitation au formateur.',201)
        with closing(db_connect()) as conn:
            _schema(conn)
            rows=conn.execute('SELECT id,nom,prenom,email,active,created_at,invited_at,password_hash FROM trainers ORDER BY nom,prenom').fetchall()
            trainers=[]
            for row in rows:
                trainer={key:row[key] for key in ('id','nom','prenom','email','created_at','invited_at')}
                trainer.update(active=bool(row['active']),activated=bool(row['password_hash']),assignments=get_assignments(conn,row['id']),legacy_assignments=[dict(bts=a['bts'],rentree_annee=a['rentree_annee']) for a in conn.execute('SELECT bts,rentree_annee FROM trainer_assignments WHERE trainer_id=?',(row['id'],))])
                trainers.append(trainer)
            available_promotions=list_promotions(conn)
        selected_bts=request.args.get('bts','').upper()
        if selected_bts not in BTS_LABELS:
            selected_bts=''
        try:
            selected_year=int(request.args.get('rentree',datetime.now().year+1))
        except ValueError:
            selected_year=datetime.now().year+1
        years=sorted(set([2026,2027,*range(datetime.now().year,datetime.now().year+3),*[a['rentree_annee'] for t in trainers for a in t['assignments']]]))
        if selected_year not in years:
            selected_year=datetime.now().year+1
        return page('trainer_admin.html',title='Formateurs · Plateforme de gestion des BTS',trainers=trainers,promotions=available_promotions,bts_labels=BTS_LABELS,years=years,selected_bts=selected_bts,selected_year=selected_year,selected_promotion=request.args.get('promotion',''))

    @app.post('/admin/formateurs/<trainer_id>/update')
    def admin_trainer_update(trainer_id):
        admin_guard()
        check_csrf()
        try:
            nom,prenom,email,assignments=fields_from(payload(), allow_missing_email=True)
        except ValueError as error:
            return admin_reply(False,str(error),400)
        try:
            with closing(db_connect()) as conn:
                _schema(conn)
                conn.execute('BEGIN IMMEDIATE')
                trainer=conn.execute('SELECT * FROM trainers WHERE id=?',(trainer_id,)).fetchone()
                if not trainer:
                    abort(404)
                if trainer['email'] and not email:
                    return admin_reply(False,'Indiquez une adresse e-mail valide.',400)
                previous=sorted(a['id'] for a in get_assignments(conn,trainer_id))
                from planning import validate_trainer_promotions_change
                planning_conflicts=validate_trainer_promotions_change(conn,trainer_id,assignments)
                if planning_conflicts:
                    return admin_reply(False,'Cette affectation est encore utilisée dans le planning. Réattribuez d’abord les matières et les cours concernés avant de retirer la promotion.',409)
                changed=(nom,prenom,email,assignments)!=(trainer['nom'],trainer['prenom'],trainer['email'],previous)
                email_changed=email!=trainer['email']
                if changed:
                    conn.execute('UPDATE trainers SET nom=?,prenom=?,email=?,password_hash=?,invited_at=?,version=version+1,updated_at=? WHERE id=?',(nom,prenom,email,None if email_changed else trainer['password_hash'],None if email_changed else trainer['invited_at'],datetime.now(timezone.utc).isoformat(),trainer_id))
                    replace_assignments(conn,trainer_id,assignments)
                    conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id=?',(trainer_id,))
                conn.commit()
        except ValueError as error:
            return admin_reply(False,str(error),400)
        except sqlite3.IntegrityError:
            return admin_reply(False,'Cette adresse e-mail est déjà associée à un compte formateur.',409)
        return admin_reply(True,'Informations enregistrées. Envoyez une nouvelle invitation à la nouvelle adresse e-mail.' if email_changed else 'Informations et affectations enregistrées.')

    @app.get('/admin/formateurs/<trainer_id>')
    def admin_trainer_detail(trainer_id):
        if not require_admin() and 'login' in app.view_functions:
            return go('login', next=request.full_path.rstrip('?'))
        admin_guard()
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('Europe/Paris'))
        allowed = {'tab', 'month', 'month_number', 'year', 'school_year', 'date'}
        if set(request.args) - allowed or any(len(values) != 1 for _, values in request.args.lists()):
            abort(400, 'Sélectionnez une seule période.')
        # Preserve older bookmarked accounting periods; a plain trainer file
        # now opens its planning, as do date-based links.
        legacy_period = 'date' not in request.args and any(key in request.args for key in ('month','month_number','year','school_year'))
        tab = request.args.get('tab', 'accounting' if legacy_period else 'planning')
        if tab not in ('accounting', 'planning', 'availability', 'account'):
            abort(400, 'Choisissez un onglet de la fiche.')
        default_month = 7 if tab == 'accounting' and now.month == 8 else now.month
        raw_month = request.args.get('month')
        if raw_month is None and tab == 'planning' and re.fullmatch(r'\d{4}-\d{2}-\d{2}', request.args.get('date', '')):
            raw_month = request.args['date'][:7]
        raw_school_year = request.args.get('school_year')
        raw_number = request.args.get('month_number')
        if raw_school_year is not None:
            if tab != 'accounting' or 'year' in request.args:
                abort(400, 'Sélectionnez une seule année BTS pour la comptabilité.')
            if not re.fullmatch(r'\d{4}', raw_school_year) or not 1900 <= int(raw_school_year) < 2200:
                abort(400, 'Sélectionnez une année BTS débutant entre 1900 et 2199.')
            school_year = int(raw_school_year)
            if raw_month is None:
                if raw_number is None:
                    current_school_year = now.year if now.month >= 9 else now.year - 1
                    raw_number = f'{default_month:02d}' if school_year == current_school_year else '09'
                if not re.fullmatch(r'0?[1-9]|1[0-2]', raw_number):
                    abort(400, 'Sélectionnez un mois valide.')
                raw_year = str(school_year + (int(raw_number) < 9))
            else:
                raw_year = raw_month[:4]
        else:
            # Legacy year/month links retain their calendar-date meaning.
            raw_year = request.args.get('year', raw_month[:4] if raw_month else str(now.year))
        if not re.fullmatch(r'\d{4}', raw_year) or not 1900 <= int(raw_year) <= 2200:
            abort(400, 'Sélectionnez une année comprise entre 1900 et 2200.')
        year = int(raw_year)
        if raw_number is not None:
            if raw_month is not None or not re.fullmatch(r'0?[1-9]|1[0-2]', raw_number):
                abort(400, 'Sélectionnez un seul mois valide.')
            month = f'{year:04d}-{int(raw_number):02d}'
        else:
            month = raw_month or f'{year:04d}-{default_month:02d}'
        try:
            selected_month, _ = _month_bounds(month)
        except WorkloadError as error:
            abort(error.status, str(error))
        if selected_month.year != year:
            abort(400, 'Le mois sélectionné doit appartenir à cette année.')
        if tab == 'accounting':
            school_year = selected_month.year if selected_month.month >= 9 else selected_month.year - 1
            if not 1900 <= school_year < 2200:
                abort(400, 'Sélectionnez une année BTS débutant entre 1900 et 2199.')
            if raw_school_year is not None and school_year != int(raw_school_year):
                abort(400, 'Le mois sélectionné doit appartenir à cette année BTS.')
        selected_date = request.args.get('date')
        if selected_date is not None:
            from datetime import date
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', selected_date):
                    raise ValueError
                day = date.fromisoformat(selected_date)
                if not 1900 <= day.year <= 2200:
                    raise ValueError
            except ValueError:
                abort(400, 'Sélectionnez une date valide.')
        with closing(db_connect()) as conn:
            _schema(conn)
            ensure_workload_schema(conn)
            if tab == 'availability':
                from trainer_availability import ensure_trainer_availability_schema
                from trainer_notifications import ensure_notification_schema
                ensure_trainer_availability_schema(conn)
                ensure_notification_schema(conn)
            conn.commit()
            conn.execute('BEGIN')
            row = conn.execute('SELECT id,nom,prenom,email,active,password_hash,invited_at FROM trainers WHERE id=?', (trainer_id,)).fetchone()
            if not row:
                abort(404)
            trainer = {key: row[key] for key in ('id', 'nom', 'prenom', 'email', 'active', 'invited_at')}
            trainer.update(activated=bool(row['password_hash']), assignments=get_assignments(conn, trainer_id))
            years = set(range(now.year-3,now.year+5)) | set(range(year-2,year+3))
            for item in trainer['assignments']:
                for key in ('date_debut','date_fin'):
                    value = item.get(key) or ''
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                        years.add(int(value[:4]))
            for item in conn.execute('SELECT substr(date,1,4) AS year FROM planning_courses WHERE trainer_id=? UNION SELECT substr(effective_date,1,4) AS year FROM trainer_hourly_rates WHERE trainer_id=?',(trainer_id,trainer_id)):
                if str(item['year']).isdigit(): years.add(int(item['year']))
            context = dict(trainer=trainer, active_tab=tab, selected_year=year, selected_month=month,
                           selected_month_number=selected_month.month, selected_date=selected_date,
                           month_options=[dict(number=number, name=name) for number,name in enumerate(MONTHS,1)],
                           year_options=sorted(value for value in years if 1900<=value<=2200))
            if tab == 'accounting':
                workload = get_trainer_workload(conn, trainer_id, month)
                # Move straight between teaching years; explicit August links
                # remain accessible but are clearly outside the BTS totals.
                if selected_month.month == 9:
                    workload['previous_month'] = f'{year:04d}-07' if school_year > 1900 else None
                if selected_month.month == 7:
                    workload['next_month'] = f'{year:04d}-09' if school_year < 2199 else None
                if selected_month.month == 8 and year == 2200:
                    workload['next_month'] = None
                annual_workload = get_trainer_annual_workload(conn, trainer_id, school_year)
                context.update(workload=workload, annual_workload=annual_workload,
                               selected_school_year=school_year, outside_bts_year=selected_month.month == 8,
                               month_options=annual_workload['months'],
                               school_year_options=sorted({school_year} | {value-offset for value in years for offset in (0,1) if 1900 <= value-offset < 2200}))
            elif tab == 'planning':
                from trainer_admin_planning import get_admin_trainer_planning
                context['trainer_planning'] = get_admin_trainer_planning(conn, trainer_id, selected_date or (selected_month.isoformat() if any(key in request.args for key in ('month','month_number','year')) else now.date().isoformat()))
            elif tab == 'availability':
                from trainer_admin_planning import get_admin_trainer_availability
                context['trainer_availability'] = get_admin_trainer_availability(conn, trainer_id, year)
            else:
                current = {item['id'] for item in trainer['assignments']}
                context['account_promotions'] = [item for item in list_promotions(conn) if item['active'] or item['id'] in current]
                context['account_promotion_ids'] = current
            conn.commit()
        return page('trainer_detail.html', title=person_name(trainer['nom'],trainer['prenom'])+' · Fiche formateur', **context)

    @app.post('/admin/formateurs/<trainer_id>/espace')
    def admin_trainer_open_portal(trainer_id):
        admin_guard()
        check_csrf()
        with closing(db_connect()) as conn:
            row = conn.execute('SELECT id,nom,prenom,version FROM trainers WHERE id=?', (trainer_id,)).fetchone()
            if not row:
                abort(404)
        session['_trainer_preview'] = dict(trainer_id=row['id'], version=row['version'],
            name=person_name(row['nom'], row['prenom']), expires_at=time.time()+3600)
        return secure(redirect(url_for('trainer_dashboard'), code=303))

    @app.post('/admin/formateurs/espace/fermer')
    def admin_trainer_close_portal():
        admin_guard()
        check_csrf()
        identity = session.pop('_trainer_preview', {})
        target = url_for('admin_trainer_detail', trainer_id=identity['trainer_id']) if identity.get('trainer_id') else url_for('admin_trainers')
        return secure(redirect(target, code=303))

    @app.post('/admin/formateurs/<trainer_id>/tarif')
    def admin_trainer_hourly_rate(trainer_id):
        admin_guard()
        check_csrf()
        data = payload()
        revision = data.get('expected_revision')
        if isinstance(revision, str) and re.fullmatch(r'\d{1,10}', revision):
            revision = int(revision)
        try:
            with closing(db_connect()) as conn:
                _schema(conn)
                ensure_workload_schema(conn)
                conn.commit()
                conn.execute('BEGIN IMMEDIATE')
                save_hourly_rate(conn, trainer_id, data.get('effective_date'), data.get('hourly_rate'), revision)
                conn.commit()
        except WorkloadError as error:
            return secure(app.make_response((jsonify(ok=False, message=str(error)), error.status)))
        return secure(app.make_response(jsonify(ok=True, message='Tarif enregistré. Les estimations ont été recalculées à partir de sa date d’effet.')))

    @app.post('/admin/formateurs/<trainer_id>/status')
    def admin_trainer_status(trainer_id):
        admin_guard()
        check_csrf()
        value=payload().get('active')
        if value not in (0,1,'0','1',False,True):
            return admin_reply(False,'Choisissez un état valide pour ce compte.',400)
        active=1 if value in (1,'1',True) else 0
        with closing(db_connect()) as conn:
            _schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            trainer=conn.execute('SELECT active FROM trainers WHERE id=?',(trainer_id,)).fetchone()
            if not trainer:
                abort(404)
            if trainer['active']!=active:
                conn.execute('UPDATE trainers SET active=?,version=version+1,updated_at=? WHERE id=?',(active,datetime.now(timezone.utc).isoformat(),trainer_id))
                conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id=?',(trainer_id,))
            conn.commit()
        return admin_reply(True,'Compte réactivé.' if active else 'Compte désactivé. Les sessions et les liens précédents ne donnent plus accès à cet espace.')

    @app.post('/admin/formateurs/<trainer_id>/send-access')
    def admin_trainer_send_access(trainer_id):
        admin_guard()
        check_csrf()
        with closing(db_connect()) as conn:
            _schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            trainer=conn.execute('SELECT id,email,active,version,password_hash FROM trainers WHERE id=?',(trainer_id,)).fetchone()
            if not trainer:
                abort(404)
            if not trainer['active']:
                return admin_reply(False,'Réactivez le compte avant d’envoyer un accès.',400)
            if not trainer['email']:
                return admin_reply(False,'Renseignez l’adresse e-mail du formateur avant d’envoyer ses accès.',400)
            if not limit(conn,'invitation',trainer_id,5):
                return admin_reply(False,'Trop de demandes récentes. Réessayez dans 15 minutes.',429)
            purpose='reset' if trainer['password_hash'] else 'activation'
            token,token_hash=create_access_token(conn,trainer,purpose)
            conn.commit()
        if not deliver_access(trainer['email'],token,token_hash,purpose):
            return admin_reply(False,'L’e-mail n’a pas pu être envoyé. Réessayez plus tard.',502)
        with closing(db_connect()) as conn:
            conn.execute('UPDATE trainers SET invited_at=? WHERE id=?',(datetime.now(timezone.utc).isoformat(),trainer_id))
            conn.commit()
        return admin_reply(True,'Lien de réinitialisation envoyé au formateur.' if purpose=='reset' else 'Invitation envoyée au formateur.')

    @app.route('/formateur/connexion',methods=['GET','POST'])
    def trainer_login():
        require_configured_key()
        email,error='',''
        if request.method=='POST':
            check_csrf()
            _clear_trainer_session()
            email=request.form.get('email','').strip().lower()[:254]
            password=request.form.get('password','')
            authenticated=None
            if email and 1<=len(password)<=128:
                with closing(db_connect()) as conn:
                    _schema(conn)
                    conn.execute('BEGIN IMMEDIATE')
                    if limit(conn,'login',email,10):
                        trainer=conn.execute('SELECT id,active,version,password_hash FROM trainers WHERE email=?',(email,)).fetchone()
                        valid=check_password_hash(trainer['password_hash'] if trainer and trainer['active'] and trainer['password_hash'] else dummy_hash,password)
                        if valid and trainer and trainer['active'] and trainer['password_hash']:
                            authenticated=dict(trainer)
                    conn.commit()
            if authenticated:
                session['_trainer_auth']=dict(trainer_id=authenticated['id'],version=authenticated['version'],expires_at=time.time()+SESSION_TTL)
                csrf()
                return go('trainer_dashboard')
            error='Adresse e-mail ou mot de passe incorrect, ou accès temporairement limité. Vérifiez vos informations ou utilisez « Mot de passe oublié ».'
        return page('trainer_login.html',title='Espace formateur · Intégrale Academy',email=email,error=error,reset_done=request.args.get('reset')=='ok')

    @app.route('/formateur/mot-de-passe-oublie',methods=['GET','POST'])
    def trainer_forgot_password():
        require_configured_key()
        sent=False
        email=''
        if request.method=='POST':
            check_csrf()
            email=request.form.get('email','').strip().lower()[:254]
            matched=None
            with closing(db_connect()) as conn:
                _schema(conn)
                conn.execute('BEGIN IMMEDIATE')
                if limit(conn,'recovery',email,5):
                    trainer=conn.execute('SELECT id,email,active,version FROM trainers WHERE email=?',(email,)).fetchone()
                    if trainer and trainer['active']:
                        token,token_hash=create_access_token(conn,trainer,'reset')
                        matched=(trainer['email'],token,token_hash)
                conn.commit()
            if matched:
                deliver_access(*matched,'reset')
            sent=True
        return page('trainer_forgot_password.html',title='Mot de passe oublié · Espace formateur',email=email,sent=sent)

    @app.get('/formateur/mot-de-passe/<token>')
    def trainer_accept_token(token):
        require_configured_key()
        session['_trainer_reset_hash']=hashlib.sha256(token.encode()).hexdigest() if 20<=len(token)<=128 else ''
        return go('trainer_password')

    @app.route('/formateur/mot-de-passe',methods=['GET','POST'])
    def trainer_password():
        require_configured_key()
        token_hash=session.get('_trainer_reset_hash','')
        with closing(db_connect()) as conn:
            _schema(conn)
            record=conn.execute('''SELECT k.*,t.active,t.version AS current_version FROM trainer_access_tokens k
                JOIN trainers t ON t.id=k.trainer_id WHERE k.token_hash=?''',(token_hash,)).fetchone()
        valid=bool(record and record['active'] and not record['consumed'] and record['expires_at']>time.time() and record['version']==record['current_version'])
        purpose=record['purpose'] if valid else 'reset'
        error=''
        if request.method=='POST':
            check_csrf()
            password=request.form.get('new_password','')
            error=password_error(password,request.form.get('confirm_password',''))
            if valid and not error:
                with closing(db_connect()) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    current=conn.execute('''SELECT k.*,t.active,t.version AS current_version FROM trainer_access_tokens k
                        JOIN trainers t ON t.id=k.trainer_id WHERE k.token_hash=?''',(token_hash,)).fetchone()
                    if current and current['active'] and not current['consumed'] and current['expires_at']>time.time() and current['version']==current['current_version']:
                        conn.execute('UPDATE trainers SET password_hash=?,version=version+1,updated_at=? WHERE id=?',(generate_password_hash(password,method='scrypt'),datetime.now(timezone.utc).isoformat(),current['trainer_id']))
                        conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id=?',(current['trainer_id'],))
                        conn.commit()
                        _clear_trainer_session()
                        return go('trainer_login',reset='ok')
                    conn.commit()
                    valid=False
        return page('trainer_password.html',title='Mon mot de passe · Espace formateur',valid=valid,purpose=purpose,error=error)

    @app.get('/formateur')
    def trainer_dashboard():
        trainer=get_authenticated_trainer(app,db_connect)
        if not trainer:
            return go('trainer_login')
        selected_bts=request.args.get('bts','').strip().upper()
        if selected_bts and selected_bts not in BTS_LABELS:
            abort(400)
        selected_year=''
        if request.args.get('rentree'):
            try:
                selected_year=int(request.args['rentree'])
            except ValueError:
                abort(400)
        with closing(db_connect()) as conn:
            assignments=get_assignments(conn,trainer['id'])
            # Promotion IDs are the sole grant. BTS/cohort compatibility is a
            # second guard against later administrative edits leaving stale placements.
            sql='''SELECT c.nom,c.prenom,p.bts AS bts,c.mode,c.email,c.tel,c.numero_dossier,
                    c.rentree_annee,c.statut,p.id AS promotion_id,p.nom AS promotion_name,
                    p.niveau AS promotion_niveau,p.date_debut AS promotion_date_debut,
                    p.date_fin AS promotion_date_fin,p.needs_setup AS promotion_needs_setup
                FROM candidats c JOIN student_promotions s ON s.candidate_id=c.id
                JOIN promotions p ON p.id=s.promotion_id
                JOIN trainer_promotions a ON a.promotion_id=p.id
                JOIN trainers t ON t.id=a.trainer_id
                WHERE a.trainer_id=? AND t.active=1 AND t.version=? AND p.active=1
                    AND upper(trim(c.bts))=p.bts AND COALESCE(c.rentree_annee,2026)=p.rentree_annee
                    AND c.statut IN ('confirmee','reconfirmee')
                ORDER BY p.rentree_annee DESC,p.bts,COALESCE(p.niveau,0),p.nom,c.nom,c.prenom'''
            students=[dict(row) for row in conn.execute(sql,(trainer['id'],trainer['version']))]
            from planning_portal import get_portal_today
            portal_today=get_portal_today(conn,'trainer',trainer['id'])
        return page('trainer_dashboard.html',title='Mes étudiants · Espace formateur',trainer=trainer,students=students,
                    assignments=assignments,promotions=assignments,bts_labels=BTS_LABELS,selected_bts=selected_bts,
                    selected_year=selected_year,selected_promotion=request.args.get('promotion',''),total_students=len(students),portal_today=portal_today)

    @app.route('/formateur/deconnexion',methods=['GET','POST'])
    def trainer_logout():
        if request.method!='POST':
            abort(405)
        check_csrf()
        _clear_trainer_session()
        return go('trainer_login')
