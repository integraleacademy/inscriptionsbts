"""One durable WEDOF batch each day at 08:00 Europe/Paris, on the web disk.

No browser session, external writes or messages. A lease serializes steps across
workers; completed queue entries survive deploys. Provider pauses resume the same
batch, never start a second sweep. Other failures wait for the next daily batch.
"""
from contextlib import closing
from datetime import datetime, timedelta
import os
import secrets
import threading
import time
from zoneinfo import ZoneInfo

from werkzeug.exceptions import NotFound
from wedof_contract_data import WedofError

PARIS = ZoneInfo('Europe/Paris')
LEASE_SECONDS = 120


def next_morning(now):
    local = now.astimezone(PARIS)
    morning = local.replace(hour=8, minute=0, second=0, microsecond=0)
    return morning if local < morning else morning + timedelta(days=1)


def schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS student_wedof_daily_clock (
            id INTEGER PRIMARY KEY CHECK(id=1), first_due REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS student_wedof_daily_runs (
            day TEXT PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL,
            status TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
            lease_until REAL NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS student_wedof_daily_items (
            day TEXT NOT NULL, candidate_id TEXT NOT NULL, contract_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '', PRIMARY KEY(day,candidate_id,contract_id));
    ''')


def initialize(connect, now=None):
    now = now or datetime.now(PARIS)
    with closing(connect()) as conn:
        schema(conn)
        conn.execute('INSERT OR IGNORE INTO student_wedof_daily_clock VALUES(1,?)',
                     (next_morning(now).timestamp(),))
        conn.commit()


def tick(connect, sync_item, configured, *, now=None):
    """Process at most one bounded phase; return seconds until more work is due."""
    fixed_clock = now is not None
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    ts, day = now.timestamp(), now.date().isoformat()
    tomorrow = next_morning(now).timestamp()
    token = secrets.token_hex(16)
    with closing(connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        first = conn.execute('SELECT first_due FROM student_wedof_daily_clock WHERE id=1').fetchone()
        if not first or ts < first['first_due']:
            return max(1, first['first_due']-ts) if first else 30
        if now.hour < 8:
            return max(1, tomorrow-ts)
        run = conn.execute('SELECT * FROM student_wedof_daily_runs WHERE day=?', (day,)).fetchone()
        new_run = not run
        if not run:
            # Snapshot the local students once. No global WEDOF catalogue import.
            conn.execute('INSERT INTO student_wedof_daily_runs(day,started_at,status) VALUES(?,?,?)',
                         (day, ts, 'running'))
            conn.execute('''INSERT INTO student_wedof_daily_items(day,candidate_id,contract_id)
                SELECT ?,c.id,COALESCE(w.contract_id,'') FROM candidats c
                LEFT JOIN student_wedof_contracts w ON w.candidate_id=c.id
                WHERE c.statut IN ('confirmee','reconfirmee') OR w.contract_id IS NOT NULL''', (day,))
            run = conn.execute('SELECT * FROM student_wedof_daily_runs WHERE day=?', (day,)).fetchone()
        if run['status'] != 'running':
            return max(1, tomorrow-ts)
        if run['lease_until'] > ts or run['next_attempt'] > ts:
            return max(1, max(run['lease_until'], run['next_attempt'])-ts)
        item = conn.execute("SELECT * FROM student_wedof_daily_items WHERE day=? AND status='pending' ORDER BY candidate_id,contract_id LIMIT 1", (day,)).fetchone()
        if not item:
            errors = conn.execute("SELECT COUNT(*) FROM student_wedof_daily_items WHERE day=? AND status='error'", (day,)).fetchone()[0]
            conn.execute('UPDATE student_wedof_daily_runs SET status=?,finished_at=? WHERE day=?',
                         ('completed_with_errors' if errors else 'completed', ts, day))
            conn.commit()
            print(f'WEDOF quotidien {day} : passage terminé ({errors} erreur(s)).', flush=True)
            return max(1, tomorrow-ts)
        try:
            ready = configured(conn)
        except WedofError:
            ready = False
        if not ready:
            conn.execute("UPDATE student_wedof_daily_runs SET status='blocked',finished_at=?,error=? WHERE day=?",
                         (ts, 'La connexion WEDOF est à configurer.', day))
            conn.commit()
            return max(1, tomorrow-ts)
        conn.execute('UPDATE student_wedof_daily_runs SET owner=?,lease_until=? WHERE day=?',
                     (token, ts+LEASE_SECONDS, day))
        conn.commit()

    if new_run:
        print(f'WEDOF quotidien {day} : début du passage de 08:00 Europe/Paris.', flush=True)

    try:
        result = sync_item(item['candidate_id'], item['contract_id'], run['started_at'])
    except NotFound:
        result = {'skipped': True}
    except WedofError as error:
        result = {'error_status': error.status, 'error_code': error.code,
                  'retry_at': error.retry_at or 0, 'message': str(error)}
    except Exception:
        result = {'error_status': 500, 'message': 'Vérification interrompue ; les données précédentes sont conservées.'}

    # Network reads finish before this checkpoint. A restart can resume the phase;
    # a successfully refreshed/linked contract is detected by the service cache.
    finished = ts if fixed_clock else time.time()
    retry_at = result.get('retry_at', 0)
    delay = max(1, retry_at-finished) if retry_at else 1
    status = 'pending' if result.get('pending') else 'error' if result.get('error_status') else 'done'
    message = result.get('message', '') if result.get('error_status') else ''
    waiting = result.get('error_status') in {429, 409} or result.get('error_code') == 'refresh_pending'
    if waiting:
        status, delay = 'pending', max(delay, 5)
    with closing(connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned = conn.execute('SELECT 1 FROM student_wedof_daily_runs WHERE day=? AND owner=?', (day, token)).fetchone()
        if not owned:
            return 30
        conn.execute('''UPDATE student_wedof_daily_items SET status=?,attempts=attempts+1,error=?
            WHERE day=? AND candidate_id=? AND contract_id=?''',
                     (status, message, day, item['candidate_id'], item['contract_id']))
        blocked = not waiting and (result.get('error_code') in {'http_401', 'http_403'} or result.get('error_status') in {500, 502, 503})
        if blocked:
            conn.execute("UPDATE student_wedof_daily_runs SET status='blocked',finished_at=?,error=? WHERE day=?",
                         (finished, message, day))
        conn.execute('UPDATE student_wedof_daily_runs SET owner=?,lease_until=0,next_attempt=? WHERE day=?',
                     ('', finished+delay, day))
        conn.commit()
    if blocked:
        print(f'WEDOF quotidien {day} : passage interrompu ; prochaine vérification demain à 08:00.', flush=True)
    return delay


def register_daily_sync(app, connect, sync_item, configured):
    with closing(connect()) as conn:
        schema(conn)
    guard, wake = threading.Lock(), threading.Event()
    state = {'thread': None}

    def worker():
        while True:
            try:
                with app.app_context():
                    delay = tick(connect, sync_item, configured)
            except Exception:
                app.logger.warning('Le contrôle du passage quotidien WEDOF sera repris.')
                delay = 30
            wake.wait(max(1, min(delay, 60)))

    def start():
        if app.config.get('TESTING') or os.getenv('WEDOF_DAILY_SYNC_DISABLED') == '1':
            return
        with guard:
            if state['thread'] is None or not state['thread'].is_alive():
                initialize(connect)
                state['thread'] = threading.Thread(target=worker, name='wedof-daily-sync', daemon=True)
                state['thread'].start()
                print('WEDOF : vérification quotidienne à 08:00 Europe/Paris activée.', flush=True)

    # Render starts the worker at boot. This is only a recovery hook for WSGI.
    app.before_request(start)
    app.extensions['wedof_start_daily_sync'] = start
    app.extensions['wedof_sync_item'] = sync_item
