"""Durable notifications for trainer-declared availability changes.

The mutation and two recipient jobs are committed together. Delivery only runs
outside that transaction; each recipient has its own claim and retry state.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import secrets
import sqlite3
import threading
import time
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from branded_email import DEFAULT_BASE, _absolute_url, render_branded_email

RECIPIENTS = ('ecole@integraleacademy.com', 'clement@integraleacademy.com')
LEASE_SECONDS = 300
_environment = Environment(loader=FileSystemLoader(str(Path(__file__).with_name('templates'))),
                           autoescape=select_autoescape(('html', 'xml')))


def ensure_notification_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS trainer_availability_notifications(
        id TEXT PRIMARY KEY,trainer_id TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trainer_availability_deliveries(
        notification_id TEXT NOT NULL,recipient TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
        lease_until REAL NOT NULL DEFAULT 0,claim_token TEXT,provider_id TEXT,last_error TEXT,
        sent_at TEXT,PRIMARY KEY(notification_id,recipient))''')
    conn.execute('CREATE INDEX IF NOT EXISTS trainer_availability_delivery_due ON trainer_availability_deliveries(status,next_attempt,lease_until)')


def enqueue_availability_notification(conn, trainer, action, added, removed, courses, reason, revision):
    """Caller owns the availability write transaction. No transport occurs here."""
    if not added and not removed and not courses:
        return None
    ensure_notification_schema(conn)
    changed_dates = sorted(set([*added, *removed, *(course['date'] for course in courses)]))
    created = datetime.now(timezone.utc).isoformat()
    snapshot = dict(trainer_id=trainer['id'], nom=trainer.get('nom') or '', prenom=trainer.get('prenom') or '',
                    email=trainer.get('email') or '', action=action, dates=changed_dates,
                    added_dates=added, removed_dates=removed, courses=courses, reason=reason,
                    created_at=created, revision=revision)
    notification_id = secrets.token_urlsafe(24)
    conn.execute('INSERT INTO trainer_availability_notifications VALUES(?,?,?,?)',
                 (notification_id, trainer['id'], json.dumps(snapshot, ensure_ascii=False), created))
    for recipient in RECIPIENTS:
        conn.execute('INSERT INTO trainer_availability_deliveries(notification_id,recipient) VALUES(?,?)', (notification_id, recipient))
    return notification_id


def _date_label(value):
    months = ('janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre')
    weekdays = ('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')
    day = datetime.strptime(value, '%Y-%m-%d')
    return f'{weekdays[day.weekday()]} {day.day} {months[day.month-1]} {day.year}'


def render_availability_notification(snapshot):
    full_name = ' '.join((str(snapshot['prenom']) + ' ' + str(snapshot['nom'])).split())
    unavailable = snapshot['action'] == 'unavailable'
    courses = [dict(course, date_label=_date_label(course['date'])) for course in snapshot['courses']]
    total_minutes = sum(int(course.get('duration_minutes') or 0) for course in courses)
    hours, minutes = divmod(total_minutes, 60)
    duration = (f'{hours} h' + (f' {minutes:02d}' if minutes else '')) if hours else f'{minutes} min'
    created = datetime.fromisoformat(snapshot['created_at']).astimezone(ZoneInfo('Europe/Paris'))
    context = dict(snapshot=snapshot, full_name=full_name, unavailable=unavailable, courses=courses,
                   dates=[_date_label(day) for day in snapshot['dates']], duration=duration,
                   created_label=created.strftime('%d/%m/%Y à %H:%M'), course_count=len(courses))
    body = _environment.get_template('email_trainer_availability.html').render(**context)
    try:
        base = _absolute_url(os.getenv('BASE_URL', DEFAULT_BASE)).rstrip('/')
    except ValueError:
        base = DEFAULT_BASE
    url = base + '/admin/formateurs/' + quote(snapshot['trainer_id'], safe='') + '?' + urlencode(dict(tab='availability', year=snapshot['dates'][0][:4]))
    subject = ('Indisponibilités déclarées' if unavailable else 'Disponibilités rétablies') + ' · ' + full_name
    title = 'Le planning évolue.' if unavailable else 'De nouveau disponible.'
    html = render_branded_email(title, body, eyebrow='INTÉGRALE ACADEMY · ÉQUIPE PÉDAGOGIQUE',
        accent_title='Gardons une longueur d’avance.',
        preview_text=f'{full_name} · {len(snapshot["dates"])} date(s) modifiée(s) · {len(courses)} cours supprimé(s).',
        action_url=url, action_label='Ouvrir la fiche du formateur',
        security_note='Notification interne destinée à l’école. Le lien ouvre une fiche protégée par votre connexion administrateur.')
    return subject, html


def _claim(db_connect, notification_id=None, now=None):
    now = time.time() if now is None else now
    with closing(db_connect()) as conn:
        ensure_notification_schema(conn)
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        args = [now, now]
        where = "((d.status='pending' AND d.next_attempt<=?) OR (d.status='sending' AND d.lease_until<=?))"
        if notification_id:
            where += ' AND d.notification_id=?'
            args.append(notification_id)
        row = conn.execute('''SELECT d.notification_id,d.recipient,d.attempts,n.payload_json
            FROM trainer_availability_deliveries d JOIN trainer_availability_notifications n ON n.id=d.notification_id
            WHERE '''+where+' ORDER BY n.created_at,d.recipient LIMIT 1', args).fetchone()
        if not row:
            return None
        claim = secrets.token_urlsafe(24)
        conn.execute('''UPDATE trainer_availability_deliveries SET status='sending',claim_token=?,lease_until=?,attempts=attempts+1
            WHERE notification_id=? AND recipient=?''', (claim, now+LEASE_SECONDS, row['notification_id'], row['recipient']))
        conn.commit()
        return dict(row, claim_token=claim, attempts=row['attempts']+1)


def dispatch_pending_notifications(app, db_connect, send_mail, *, notification_id=None, limit=10, now=None):
    """Bounded worker pass; false/exception delivery remains durable for retry."""
    if send_mail is None:
        return 0
    processed = 0
    for _ in range(limit):
        job = _claim(db_connect, notification_id, now)
        if not job:
            break
        provider_id = None
        try:
            if job['recipient'] not in RECIPIENTS:
                raise ValueError('Unexpected notification recipient')
            subject, html = render_availability_notification(json.loads(job['payload_json']))
            provider_id = send_mail(job['recipient'], subject, html)
        except Exception:
            # Never persist provider errors containing credentials or message bodies.
            app.logger.warning('Trainer availability notification delivery failed; queued for retry.')
        clock = time.time() if now is None else now
        with closing(db_connect()) as conn:
            if provider_id:
                conn.execute('''UPDATE trainer_availability_deliveries SET status='sent',provider_id=?,sent_at=?,
                    last_error=NULL,lease_until=0,claim_token=NULL WHERE notification_id=? AND recipient=? AND claim_token=?''',
                    (str(provider_id), datetime.now(timezone.utc).isoformat(), job['notification_id'],job['recipient'],job['claim_token']))
            else:
                delay = min(3600, 30 * 2 ** min(job['attempts']-1, 7))
                conn.execute('''UPDATE trainer_availability_deliveries SET status='pending',next_attempt=?,
                    last_error='Envoi non confirmé. Nouvelle tentative automatique prévue.',lease_until=0,claim_token=NULL
                    WHERE notification_id=? AND recipient=? AND claim_token=?''',
                    (clock+delay,job['notification_id'],job['recipient'],job['claim_token']))
            conn.commit()
        processed += 1
    return processed


def notification_status(conn, trainer_id, limit=10):
    """Admin-only display helper; no provider IDs, tokens, or secret details."""
    ensure_notification_schema(conn)
    events = conn.execute('''SELECT id,payload_json,created_at FROM trainer_availability_notifications
        WHERE trainer_id=? ORDER BY created_at DESC LIMIT ?''', (trainer_id, min(max(int(limit),1),50))).fetchall()
    result=[]
    for event in events:
        payload=json.loads(event['payload_json'])
        deliveries=[dict(row) for row in conn.execute('''SELECT recipient,status,attempts,last_error,sent_at
            FROM trainer_availability_deliveries WHERE notification_id=? ORDER BY recipient''',(event['id'],))]
        result.append(dict(id=event['id'],created_at=event['created_at'],action=payload['action'],
                           dates=payload['dates'],course_count=len(payload['courses']),deliveries=deliveries,
                           complete=bool(deliveries) and all(row['status']=='sent' for row in deliveries)))
    return result


def register_notification_worker(app, db_connect, send_mail):
    """One daemon per serving process, with database leases across processes.

    Starts on the first served request, not import, so the Flask reloader parent
    never launches an extra worker. TESTING never creates a background thread.
    """
    guard=threading.Lock()
    wake=threading.Event()
    state={'thread':None}

    def worker():
        while True:
            try:
                with app.app_context():
                    dispatch_pending_notifications(app,db_connect,send_mail)
            except Exception:
                app.logger.warning('Trainer notification queue temporarily unavailable; retry scheduled.')
            wake.wait(30)
            wake.clear()

    def notify(notification_id=None):
        if send_mail is None:
            return
        if app.config.get('TESTING'):
            if app.config.get('TRAINER_NOTIFICATIONS_SYNC'):
                dispatch_pending_notifications(app,db_connect,send_mail,notification_id=notification_id,limit=2)
            return
        if os.getenv('TRAINER_NOTIFICATION_WORKER_DISABLED') == '1':
            return
        with guard:
            if state['thread'] is None or not state['thread'].is_alive():
                state['thread']=threading.Thread(target=worker,name='trainer-availability-mail',daemon=True)
                state['thread'].start()
        if notification_id is not None:
            wake.set()

    @app.before_request
    def resume_notification_delivery():
        notify()

    app.extensions['trainer_notifications_notify']=notify
    return notify
