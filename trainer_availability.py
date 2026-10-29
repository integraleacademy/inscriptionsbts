"""Trainer-owned whole-day absences with an explicit, atomic cancellation preview.

The existing planning unavailability table remains the single scheduling source.
A separate ownership table prevents a trainer from removing administrative rules.
No course disappears before the trainer confirms a short-lived preview describing
every affected reservation (including all groups of a shared course).
"""
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from zoneinfo import ZoneInfo

from flask import jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from planning import PlanningError, _clock, _iso, _load_courses, _unavailability, ensure_planning_schema
from planning_holidays import public_holiday_name
from trainer_access import get_authenticated_trainer
from trainer_notifications import (ensure_notification_schema, enqueue_availability_notification,
                                   register_notification_worker)

MAX_DATES = 740
PREVIEW_TTL = 15 * 60


def _now_paris():
    return datetime.now(ZoneInfo('Europe/Paris'))


def ensure_trainer_availability_schema(conn):
    ensure_planning_schema(conn)
    ensure_notification_schema(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_trainer_owned_absences(
        block_id TEXT PRIMARY KEY,trainer_id TEXT NOT NULL,date TEXT NOT NULL,
        UNIQUE(trainer_id,date))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_trainer_availability_versions(
        trainer_id TEXT PRIMARY KEY,version INTEGER NOT NULL DEFAULT 0)''')


def _revision(conn, trainer_id):
    row = conn.execute('SELECT version FROM planning_trainer_availability_versions WHERE trainer_id=?', (trainer_id,)).fetchone()
    return row['version'] if row else 0


def _owned(conn, trainer_id):
    return {row['date']: row['block_id'] for row in conn.execute('''
        SELECT o.date,o.block_id FROM planning_trainer_owned_absences o
        JOIN planning_trainer_unavailability u ON u.id=o.block_id AND u.trainer_id=o.trainer_id
        WHERE o.trainer_id=?''', (trainer_id,))}


def _applies(block, day):
    return block['start_date'] <= day.isoformat() <= block['end_date'] and day.weekday() in block['weekdays']


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _affected(conn, trainer_id, dates):
    selected = set(dates)
    return [course for course in _load_courses(conn, dates[0], dates[-1], trainer_id=trainer_id) if course['date'] in selected]


def _fingerprint(conn, trainer_id, dates, courses):
    """Include raw groups and every course column, not only a UI-filtered roster."""
    selected = set(dates)
    blocks = [item for item in _unavailability(conn, trainer_id)
              if any(_applies(item, date.fromisoformat(day)) for day in dates)]
    own = _owned(conn, trainer_id)
    rows = []
    for course in courses:
        raw = dict(conn.execute('SELECT * FROM planning_courses WHERE id=?', (course['id'],)).fetchone())
        raw['groups'] = [dict(row) for row in conn.execute('''
            SELECT promotion_id,subject_id FROM planning_course_groups WHERE course_id=? ORDER BY promotion_id,subject_id''', (course['id'],))]
        rows.append(raw)
    return _digest(dict(blocks=blocks, owned={day: block for day, block in own.items() if day in selected}, courses=rows))


def _course_summary(course):
    return dict(id=course['id'], date=course['date'], start=course['start'], end=course['end'],
                title=course['title'] or course['subject_name'], subject_name=course['subject_name'],
                room_name=course.get('room_name'),
                promotion_names=[group.get('promotion_name') or 'Promotion à renseigner' for group in course['groups']],
                shared=course['is_shared'])


def availability_course_date(args):
    if set(args) != {'date'} or len(args.getlist('date')) != 1:
        raise PlanningError('Choisissez une seule journée.')
    day = _iso(args.get('date'))
    if not 1900 <= day.year <= 2200:
        raise PlanningError('Choisissez une date comprise entre 1900 et 2200.')
    return day.isoformat()


def availability_day_courses(conn, trainer_id, day):
    return [_course_summary(course) for course in _load_courses(conn, day, day, trainer_id=trainer_id)]


def _check_future(dates, courses, status=400):
    now = _now_paris()
    today = now.date().isoformat()
    if any(day < today for day in dates):
        raise PlanningError('Une indisponibilité passée ne peut plus être déclarée. Contactez l’administration pour corriger votre historique.', status=status)
    if any(course['date'] == today and course['start_min'] <= now.hour * 60 + now.minute for course in courses):
        raise PlanningError('Un cours de cette journée a déjà commencé ou est terminé. Contactez l’administration : ces cours ne peuvent pas être supprimés depuis votre espace.', status=status)


def get_trainer_availability_state(conn, trainer_id, year, *, school_year=False):
    ensure_trainer_availability_schema(conn)
    begin, end = (date(year, 9, 1), date(year+1, 7, 31)) if school_year else (date(year, 1, 1), date(year, 12, 31))
    own = _owned(conn, trainer_id)
    blocks = _unavailability(conn, trainer_id)
    counts = {row['date']: row['amount'] for row in conn.execute('''SELECT date,COUNT(*) AS amount
        FROM planning_courses WHERE trainer_id=? AND date>=? AND date<=? GROUP BY date''',
        (trainer_id, begin.isoformat(), end.isoformat()))}
    days = []
    day = begin
    while day <= end:
        key = day.isoformat()
        applicable = [block for block in blocks if _applies(block, day)]
        administrators = [block for block in applicable if block['id'] != own.get(key)]
        days.append(dict(date=key, unavailable=bool(applicable), own_unavailable=key in own,
                         admin_unavailable=bool(administrators), partial=bool(applicable) and all(block['times'] for block in applicable),
                         reason=' · '.join(dict.fromkeys(block['reason'] for block in applicable)),
                         public_holiday=public_holiday_name(day), course_count=counts.get(key, 0)))
        day += timedelta(days=1)
    today = _now_paris().date().isoformat()
    months = list(dict.fromkeys(day['date'][:7] for day in days))
    return dict(year=year, school_year=school_year, label=f'{year}–{year+1}' if school_year else str(year),
                start=begin.isoformat(), end=end.isoformat(), months=months,
                today=today, min_date=today, max_date='2200-12-31',
                revision=_revision(conn, trainer_id), days=days)


def register_trainer_availability(app, db_connect, send_mail=None):
    notify = register_notification_worker(app, db_connect, send_mail)
    serializer = URLSafeTimedSerializer(app.secret_key, salt='trainer-day-availability-v1')

    def secure(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.vary.add('Cookie')
        return response

    def result(data, status=200):
        return secure(app.make_response((jsonify(data), status)))

    def fail(error):
        return result(dict(ok=False, message=str(error)), error.status)

    def csrf():
        if '_trainer_csrf' not in session:
            session['_trainer_csrf'] = secrets.token_urlsafe(32)
        return session['_trainer_csrf']

    def authenticate(mutation=False):
        trainer = get_authenticated_trainer(app, db_connect)
        if not trainer:
            raise PlanningError('Votre session a expiré. Reconnectez-vous à votre espace formateur.', status=401)
        if mutation:
            supplied = request.headers.get('X-CSRF-Token')
            expected = session.get('_trainer_csrf', '')
            if not isinstance(supplied, str) or not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
                raise PlanningError('La page a expiré. Rechargez-la avant de réessayer.', status=403)
        return trainer

    def body():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise PlanningError('Les données transmises sont invalides.')
        return payload

    def year_from_query():
        if set(request.args) - {'year', 'school_year'} or len(request.args) > 1 or any(len(v) != 1 for _, v in request.args.lists()):
            raise PlanningError('Indiquez uniquement l’année du calendrier.')
        now = _now_paris()
        # An old calendar-year link opens the school year containing January.
        # Every displayed calendar now covers September through July.
        legacy = 'year' in request.args
        default = now.year if now.month >= 9 else now.year-1
        raw = request.args.get('year' if legacy else 'school_year', str(default))
        if not isinstance(raw, str) or len(raw) != 4 or not raw.isdigit():
            raise PlanningError('Indiquez une année scolaire débutant entre 1900 et 2199.')
        year = int(raw) - int(legacy)
        if not 1900 <= year < 2200:
            raise PlanningError('Indiquez une année scolaire débutant entre 1900 et 2199.')
        return year, True

    def live_identity(conn, trainer_id):
        auth = session.get('_trainer_auth') or {}
        row = conn.execute('SELECT active,version,password_hash FROM trainers WHERE id=?', (trainer_id,)).fetchone()
        if (not row or not row['active'] or not row['password_hash'] or row['version'] != auth.get('version')
                or auth.get('trainer_id') != trainer_id or auth.get('expires_at', 0) <= time.time()):
            raise PlanningError('Votre accès a changé. Reconnectez-vous avant de modifier vos disponibilités.', status=401)

    def binding(trainer_id):
        return dict(trainer_id=trainer_id, version=(session.get('_trainer_auth') or {}).get('version'),
                    csrf=hashlib.sha256(csrf().encode()).hexdigest())

    def connect():
        conn = db_connect()
        ensure_trainer_availability_schema(conn)
        conn.commit()
        return conn

    @app.get('/formateur/indisponibilites')
    def trainer_availability():
        trainer = get_authenticated_trainer(app, db_connect)
        if not trainer:
            return secure(redirect(url_for('trainer_login')))
        try:
            year, school = year_from_query()
            with closing(connect()) as conn:
                state = get_trainer_availability_state(conn, trainer['id'], year, school_year=school)
            state['csrf_token'] = csrf()
            context = dict(csrf_token=csrf(), state_url=url_for('trainer_availability_state'),
                           preview_url=url_for('trainer_availability_preview'), commit_url=url_for('trainer_availability_commit'),
                           home_url=url_for('trainer_dashboard'), planning_url=url_for('trainer_planning'),
                           courses_url=url_for('trainer_availability_courses'), year=year, state=state)
            return secure(app.make_response(render_template('trainer_availability.html', title='Mes disponibilités · Intégrale Academy',
                                                           trainer=trainer, availability=context, csrf_token=csrf())))
        except PlanningError as error:
            return fail(error)

    @app.get('/formateur/indisponibilites/api/state')
    def trainer_availability_state():
        try:
            trainer = authenticate()
            year, school = year_from_query()
            with closing(connect()) as conn:
                snapshot = get_trainer_availability_state(conn, trainer['id'], year, school_year=school)
            return result(dict(ok=True, **snapshot, csrf_token=csrf()))
        except PlanningError as error:
            return fail(error)

    @app.get('/formateur/indisponibilites/api/courses')
    def trainer_availability_courses():
        try:
            trainer = authenticate()
            day = availability_course_date(request.args)
            with closing(connect()) as conn:
                courses = availability_day_courses(conn, trainer['id'], day)
            return result(dict(ok=True, date=day, courses=courses))
        except PlanningError as error:
            return fail(error)

    @app.post('/formateur/indisponibilites/api/preview')
    def trainer_availability_preview():
        try:
            trainer = authenticate(True)
            payload = body()
            if set(payload) - {'dates', 'action', 'reason'}:
                raise PlanningError('Les paramètres de sélection sont invalides.')
            raw = payload.get('dates')
            if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_DATES:
                raise PlanningError(f'Sélectionnez entre 1 et {MAX_DATES} journées.')
            dates = sorted({_iso(value).isoformat() for value in raw})
            if any(not 1900 <= date.fromisoformat(day).year <= 2200 for day in dates):
                raise PlanningError('Les dates doivent être comprises entre 1900 et 2200.')
            action = payload.get('action')
            if action not in ('unavailable', 'available'):
                raise PlanningError('Choisissez « Indisponible » ou « Disponible ».')
            reason = payload.get('reason', 'Indisponibilité déclarée par le formateur')
            if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240:
                raise PlanningError('Le motif doit contenir entre 1 et 240 caractères.')
            reason = reason.strip()
            with closing(connect()) as conn:
                # A single read transaction keeps rows, ownership and revision coherent.
                conn.execute('BEGIN')
                live_identity(conn, trainer['id'])
                own = _owned(conn, trainer['id'])
                courses = _affected(conn, trainer['id'], dates) if action == 'unavailable' else []
                if action == 'unavailable':
                    _check_future(dates, courses)
                added = [day for day in dates if day not in own] if action == 'unavailable' else []
                removed = [day for day in dates if day in own] if action == 'available' else []
                token = serializer.dumps(dict(binding=binding(trainer['id']), revision=_revision(conn, trainer['id']),
                    dates=dates, action=action, reason=reason, fingerprint=_fingerprint(conn, trainer['id'], dates, courses)))
            return result(dict(ok=True, preview_token=token, dates=dates, action=action,
                courses=[_course_summary(course) for course in courses], course_count=len(courses),
                requires_confirmation=bool(courses), added_dates=added, removed_dates=removed,
                message='Ces cours seront supprimés de tous les plannings après votre confirmation.' if courses
                        else 'Votre sélection est prête à être enregistrée.'))
        except PlanningError as error:
            return fail(error)

    @app.post('/formateur/indisponibilites/api/commit')
    def trainer_availability_commit():
        conn = None
        try:
            trainer = authenticate(True)
            payload = body()
            if set(payload) - {'preview_token', 'confirm_delete'}:
                raise PlanningError('Les paramètres de confirmation sont invalides.')
            token = payload.get('preview_token')
            if not isinstance(token, str):
                raise PlanningError('Générez un aperçu avant d’enregistrer.', status=409)
            try:
                preview = serializer.loads(token, max_age=PREVIEW_TTL)
            except (BadSignature, SignatureExpired):
                raise PlanningError('Cet aperçu a expiré. Vérifiez à nouveau votre sélection.', status=409)
            if preview.get('binding') != binding(trainer['id']):
                raise PlanningError('Cet aperçu appartient à une autre session. Vérifiez à nouveau votre sélection.', status=409)
            conn = connect()
            conn.execute('BEGIN IMMEDIATE')
            live_identity(conn, trainer['id'])
            dates, action = preview['dates'], preview['action']
            courses = _affected(conn, trainer['id'], dates) if action == 'unavailable' else []
            if (_revision(conn, trainer['id']) != preview['revision']
                    or _fingerprint(conn, trainer['id'], dates, courses) != preview['fingerprint']):
                raise PlanningError('Le planning ou vos disponibilités ont changé. Vérifiez le nouvel aperçu avant de confirmer.', status=409)
            if action == 'unavailable':
                _check_future(dates, courses, status=409)
            if courses and payload.get('confirm_delete') is not True:
                raise PlanningError('Confirmez explicitement la suppression des cours affichés pour enregistrer cette indisponibilité.', status=409)
            own = _owned(conn, trainer['id'])
            added, removed = [], []
            if action == 'available':
                for day in dates:
                    if day in own:
                        conn.execute('DELETE FROM planning_trainer_unavailability WHERE id=? AND trainer_id=?', (own[day], trainer['id']))
                        conn.execute('DELETE FROM planning_trainer_owned_absences WHERE block_id=? AND trainer_id=?', (own[day], trainer['id']))
                        removed.append(day)
            else:
                for course in courses:
                    conn.execute('DELETE FROM planning_course_groups WHERE course_id=?', (course['id'],))
                    conn.execute('DELETE FROM planning_courses WHERE id=? AND trainer_id=? AND version=?', (course['id'], trainer['id'], course['version']))
                for day in dates:
                    if day in own:
                        continue
                    # Remove an orphan created if an administrator removed this personal block.
                    conn.execute('DELETE FROM planning_trainer_owned_absences WHERE trainer_id=? AND date=?', (trainer['id'], day))
                    block_id = secrets.token_urlsafe(24)
                    conn.execute('''INSERT INTO planning_trainer_unavailability(id,trainer_id,start_date,end_date,weekdays,times,reason)
                        VALUES(?,?,?,?,?,?,?)''', (block_id, trainer['id'], day, day, json.dumps([date.fromisoformat(day).weekday()]), '[]', preview['reason']))
                    conn.execute('INSERT INTO planning_trainer_owned_absences VALUES(?,?,?)', (block_id, trainer['id'], day))
                    added.append(day)
            conn.execute('''INSERT INTO planning_trainer_availability_versions(trainer_id,version) VALUES(?,1)
                ON CONFLICT(trainer_id) DO UPDATE SET version=version+1''', (trainer['id'],))
            notification_id = enqueue_availability_notification(conn, trainer, action, added, removed,
                [dict(_course_summary(course), duration_minutes=course['end_min']-course['start_min'],
                      room_name=course.get('room_name') or '') for course in courses], preview['reason'], _revision(conn,trainer['id']))
            conn.commit()
            # Delivery starts only after the complete availability/course transaction.
            # A transport problem must never undo the confirmed scheduling change.
            if notification_id:
                try:
                    notify(notification_id)
                except Exception:
                    app.logger.warning('Availability saved; notification remains queued for retry.')
            return result(dict(ok=True, notification_queued=bool(notification_id), removed_count=len(courses), added_dates=added, removed_dates=removed,
                message=(f'Indisponibilités enregistrées. {len(courses)} cours supprimé(s) ; tous les plannings et volumes horaires sont mis à jour.'
                         if courses else 'Vos disponibilités ont été enregistrées.')))
        except PlanningError as error:
            if conn is not None:
                conn.rollback()
            return fail(error)
        except sqlite3.OperationalError:
            if conn is not None:
                conn.rollback()
            app.logger.exception('Trainer availability update failed')
            return result(dict(ok=False, message='La mise à jour n’a pas pu être enregistrée. Rechargez la page avant de réessayer.'), 503)
        finally:
            if conn is not None:
                conn.close()
