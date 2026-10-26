"""Durable one-hour roll-call reminders, driven by the running web service.

SQLite serializes claims across workers. An ambiguous provider timeout is never
automatically resent: avoiding duplicate SMS is preferable to guessing delivery.
The worker rechecks the live course, account, roster, phone and call before send.
"""
from contextlib import closing
from datetime import datetime, timedelta
import os
import threading
import time
from urllib.parse import quote

import requests


def send_reminder(phone, content):
    key = os.getenv('BREVO_API_KEY', '').strip()
    if not key:
        return 'blocked', None, 'La clé Brevo n’est pas configurée.'
    try:
        response = requests.post('https://api.brevo.com/v3/transactionalSMS/send',
            headers={'api-key': key, 'Content-Type': 'application/json'},
            json=dict(sender='INTACADEMY', recipient=phone, content=content,
                      type='transactional', unicodeEnabled=True, tag='rappel-appel'),
            timeout=(3, 10), allow_redirects=False)
    except requests.RequestException:
        return 'unknown', None, 'Envoi non confirmé ; aucune relance automatique pour éviter un doublon.'
    if 200 <= response.status_code < 300:
        try:
            provider_id = response.json().get('messageId')
        except (ValueError, AttributeError):
            provider_id = None
        return ('sent', str(provider_id), '') if provider_id is not None else ('unknown', None, 'Envoi accepté sans identifiant.')
    if response.status_code == 429:
        return 'retry', None, 'Limite temporaire Brevo ; nouvelle tentative prévue.'
    if response.status_code >= 500:
        return 'unknown', None, 'Réponse incertaine du service SMS ; aucune relance automatique.'
    return 'blocked', None, 'Envoi refusé par Brevo. Vérifiez la configuration et le crédit SMS.'


def dispatch_reminders(app, db_connect, *, now=None, sender=None):
    from teaching import schema, now_paris, course_access, course_window, roster, PlanningError
    fixed_clock = now is not None
    now = now or now_paris()
    sender = sender or send_reminder
    with closing(db_connect()) as conn:
        schema(conn)
        conn.commit()
        ids = [r['id'] for r in conn.execute('SELECT id FROM planning_courses WHERE date=?', (now.date().isoformat(),))]
    processed = 0
    for course_id in ids:
        with closing(db_connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('''SELECT c.*,t.active,t.password_hash,tc.phone FROM planning_courses c
                JOIN trainers t ON t.id=c.trainer_id LEFT JOIN teaching_contacts tc ON tc.trainer_id=t.id
                WHERE c.id=?''', (course_id,)).fetchone()
            if not row or not row['active'] or not row['password_hash']:
                continue
            window = course_window(row, now)
            due = datetime.fromisoformat(window['start_at'])+timedelta(hours=1)
            if not window['open'] or now < due:
                continue
            if conn.execute('SELECT 1 FROM teaching_rollcalls WHERE course_id=? AND completed_at IS NOT NULL', (course_id,)).fetchone():
                continue
            try:
                course = course_access(conn, course_id, 'trainer', row['trainer_id'])
            except PlanningError:
                continue
            if not roster(conn, course):
                continue
            previous = conn.execute('SELECT * FROM teaching_reminders WHERE course_id=?', (course_id,)).fetchone()
            if previous and (previous['status'] in ('sent', 'sending', 'unknown') or previous['next_attempt'] > now.timestamp()):
                continue
            if not row['phone']:
                status, error = 'blocked', 'Aucun numéro de mobile renseigné pour le formateur.'
            else:
                status, error = 'sending', None
            attempts = (previous['attempts'] if previous else 0)+int(status == 'sending')
            conn.execute('''INSERT INTO teaching_reminders(course_id,trainer_id,scheduled_for,status,attempts,next_attempt,updated_at,error)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(course_id) DO UPDATE SET trainer_id=excluded.trainer_id,
                scheduled_for=excluded.scheduled_for,status=excluded.status,attempts=excluded.attempts,
                next_attempt=excluded.next_attempt,updated_at=excluded.updated_at,error=excluded.error''',
                (course_id, row['trainer_id'], due.isoformat(), status, attempts, now.timestamp()+60, now.isoformat(), error))
            conn.commit()
            phone, trainer_id = row['phone'], row['trainer_id']
        if status != 'sending':
            continue
        # A call or a timetable/account change between discovery and claim cancels delivery.
        with closing(db_connect()) as conn:
            current = conn.execute('''SELECT c.*,t.active,t.password_hash,tc.phone FROM planning_courses c
                JOIN trainers t ON t.id=c.trainer_id LEFT JOIN teaching_contacts tc ON tc.trainer_id=t.id WHERE c.id=?''', (course_id,)).fetchone()
            called = conn.execute('SELECT 1 FROM teaching_rollcalls WHERE course_id=? AND completed_at IS NOT NULL', (course_id,)).fetchone()
            if (not current or not current['active'] or not current['password_hash'] or called
                    or current['trainer_id'] != trainer_id or current['phone'] != phone
                    or not course_window(current, now if fixed_clock else now_paris())['open'] or current['start_min'] != row['start_min']):
                conn.execute("UPDATE teaching_reminders SET status='cancelled',updated_at=? WHERE course_id=?", (now.isoformat(), course_id))
                conn.commit()
                continue
        base = os.getenv('BASE_URL', 'https://inscriptionsbts.onrender.com').rstrip('/')
        message = ('Intégrale Academy : pensez à valider l’appel de votre cours commencé à '
                   +course['start']+'. '+base+'/formateur/cours/'+quote(course_id, safe='')+'#appel')
        try:
            status, provider_id, error = sender(phone, message)
        except Exception:
            status, provider_id, error = 'unknown', None, 'Envoi non confirmé ; vérification nécessaire.'
        with closing(db_connect()) as conn:
            conn.execute('''UPDATE teaching_reminders SET status=?,provider_id=?,error=?,next_attempt=?,updated_at=?
                WHERE course_id=? AND status='sending' ''',
                (status, provider_id, error, now.timestamp()+60, now.isoformat(), course_id))
            conn.commit()
        processed += 1
    return processed


def register_reminder_worker(app, db_connect):
    guard = threading.Lock()
    state = {'thread': None}
    wake = threading.Event()

    def worker():
        while True:
            try:
                with app.app_context():
                    dispatch_reminders(app, db_connect)
            except Exception:
                app.logger.warning('Le contrôle des rappels d’appel sera réessayé.')
            wake.wait(30)

    @app.before_request
    def start_rollcall_worker():
        if app.config.get('TESTING') or os.getenv('TEACHING_REMINDER_WORKER_DISABLED') == '1':
            return
        with guard:
            if state['thread'] is None or not state['thread'].is_alive():
                state['thread'] = threading.Thread(target=worker, name='rollcall-reminders', daemon=True)
                state['thread'].start()

    app.extensions['teaching_start_reminders'] = start_rollcall_worker
