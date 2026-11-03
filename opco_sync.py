"""Persistent read-only contract synchronization for the school accounts."""
from contextlib import closing
from datetime import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading

from playwright.sync_api import Error as BrowserError
from flask import abort, flash, redirect, request, session, url_for

from akto_portal import PortalError, START_DATE
from akto_sync import PARIS, secret
from opco_convergence import ReadError, identity
from filiz_portal import HOME as FILIZ_HOME, read_filiz
from training_programs import BTS_LABELS

FILIZ_LOGIN_VERSION = 5
BTS_MARKS = ','.join('?' for _ in BTS_LABELS)


def schema(conn):
    upgrading = not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='filiz_scan_progress'").fetchone()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS opco_accounts (
          provider TEXT PRIMARY KEY, credential BLOB, requested INTEGER NOT NULL DEFAULT 0,
          day TEXT DEFAULT '', state TEXT DEFAULT 'unconfigured', message TEXT DEFAULT '',
          attempted TEXT DEFAULT '', succeeded TEXT DEFAULT '', cursor TEXT DEFAULT '', roster TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS opco_contracts (
          provider TEXT NOT NULL, ref TEXT NOT NULL, candidate_id TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(provider,ref));
        CREATE TABLE IF NOT EXISTS filiz_session (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS filiz_retry_budget (id INTEGER PRIMARY KEY CHECK(id=1), day TEXT NOT NULL, used INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS filiz_scan_progress (ref TEXT PRIMARY KEY, outcome TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS opco_student ON opco_contracts(candidate_id);
    ''')
    if 'flow' not in {r[1] for r in conn.execute("PRAGMA table_info(filiz_retry_budget)")}:
        conn.execute("ALTER TABLE filiz_retry_budget ADD COLUMN flow INTEGER DEFAULT 1")
    conn.execute("INSERT OR IGNORE INTO opco_accounts(provider) VALUES ('filiz')")
    conn.execute("DELETE FROM opco_accounts WHERE provider!='filiz'")
    if upgrading:
        conn.execute("""UPDATE opco_accounts SET requested=1 WHERE provider='filiz' AND credential IS NOT NULL
            AND state IN ('error','partial')""")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'akto_connection' in tables:
        conn.execute("UPDATE akto_connection SET credential=NULL,requested=0,state='unconfigured' WHERE id=1")
    if 'student_wedof_settings' in tables:
        conn.execute("DELETE FROM student_wedof_settings WHERE name='api_key'")
    conn.commit()


def same_contract(left, right):
    if left.get('financer') != right.get('financer'):
        return False
    return any(left.get(key) and left[key] == right.get(key)
               for key in ('deca_number','internal_number','external_number'))


def account_status(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opco_accounts'").fetchone():
        row = conn.execute("""SELECT credential IS NOT NULL AS configured,state,message,attempted,succeeded,requested,roster
            FROM opco_accounts WHERE provider='filiz'""").fetchone()
        if row:
            status = dict(row)
            if status['state'] == 'error' and status['configured']:
                processed = conn.execute('SELECT count(*) FROM filiz_scan_progress').fetchone()[0]
                if processed:
                    attached = conn.execute("SELECT count(*) FROM opco_contracts WHERE provider='filiz'").fetchone()[0]
                    status['message'] += f' Progression conservée. Dossiers examinés : {processed}. Contrats rattachés : {attached}.'
            return status
    return dict(configured=False,state='unconfigured',message='',attempted='',succeeded='',requested=0,roster='')


def records_by_student(conn, people):
    result = {}
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opco_contracts'").fetchone():
        return result
    keys = {p['id']:identity(p.get('nom'),p.get('prenom'),p.get('date_naissance')) for p in people
            if (p.get('bts') or '').strip().upper() in BTS_LABELS}
    ids = list(keys)
    for start in range(0,len(ids),400):
        batch = ids[start:start+400]
        marks = ','.join('?' for _ in batch)
        for row in conn.execute(f"""SELECT c.candidate_id,c.payload,a.state FROM opco_contracts c
                JOIN opco_accounts a ON a.provider=c.provider WHERE c.provider='filiz' AND a.credential IS NOT NULL
                AND c.candidate_id IN ({marks}) ORDER BY c.ref""",batch):
            try:
                item = json.loads(row['payload'])
            except (ValueError,TypeError):
                continue
            key = keys[row['candidate_id']]
            if (not isinstance(item,dict) or item.get('source')!='filiz' or not all(key) or
                    (item.get('contract_start') or '') < START_DATE or
                    key != identity(item.get('apprentice_last_name'),item.get('apprentice_first_name'),item.get('apprentice_birth_date'))):
                continue
            if row['state']=='error':
                item['read_warning'] = 'Dernière lecture FILIZ en échec. Le relevé précédent est affiché.'
            result.setdefault(row['candidate_id'],[]).append(item)
    return result


def student_records(conn, person):
    return records_by_student(conn,[person]).get(person['id'],[])


def coverage(conn):
    status = account_status(conn)
    return status['message'], status['state'] != 'ok'


def roster_key(people):
    return hashlib.sha256(json.dumps(people, sort_keys=True).encode()).hexdigest()


def bts_students(conn):
    return [dict(r) for r in conn.execute(
        f"SELECT id,nom,prenom,date_naissance,bts FROM candidats WHERE upper(trim(bts)) IN ({BTS_MARKS}) ORDER BY id", tuple(BTS_LABELS))]


def store_contract(conn, ref, cid, item):
    old_row = conn.execute("SELECT payload FROM opco_contracts WHERE provider='filiz' AND ref=? AND candidate_id=?",
                           (ref, cid)).fetchone()
    if old_row:
        old = json.loads(old_row[0])
        if item.get('schedule_notice') and old.get('schedules'):
            item.update(raw_stale=True, raw_error=item['schedule_notice'])
        if item.get('raw_stale') and 'schedules' in old:
            for field in ('schedules','raw_checked_at','invoices','filiz_paid','filiz_pending','engagement',
                          'filiz_updated','extra_costs_available','extra_costs'):
                if field in old:
                    item[field] = old[field]
        if item.get('invoice_error') and 'invoices' in old:
            item['invoices'] = old['invoices']
    conn.execute("INSERT OR REPLACE INTO opco_contracts VALUES ('filiz',?,?,?)",
                 (ref, cid, json.dumps(item, ensure_ascii=False)))


class ScanSuperseded(Exception):
    pass


def tick(app, connect, directory, now=None):
    provider = 'filiz'
    clock = now or datetime.now(PARIS)
    day = clock.date().isoformat()
    stamp = clock.strftime('%d/%m/%Y à %H:%M')
    with (Path(directory) / f'opco-{provider}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            account = conn.execute('SELECT * FROM opco_accounts WHERE provider=?', (provider,)).fetchone()
            daily = clock.hour >= 5 and account['day'] != day
            retry_text = 'Navigation FILIZ interrompue. La progression est enregistrée.'
            old_timeout = 'Lecture interrompue. Vérifiez les accès puis relancez.'
            legacy_login_error = 'FILIZ n’a pas ouvert l’espace école. Vérifiez vos accès ou une validation demandée par FILIZ.'
            legacy_disabled = 'FILIZ laisse le bouton « Continuer » désactivé sur son formulaire de connexion.'
            previous_redirect = 'Après identification, FILIZ renvoie à la page de connexion sans ouvrir l’espace école.'
            retryable = (account['state'] == 'error' and account['message'] in
                         (retry_text, old_timeout, legacy_login_error, legacy_disabled, previous_redirect)
                         and account['cursor'] and account['day'] == day)
            used = conn.execute('SELECT used FROM filiz_retry_budget WHERE day=? AND flow=?', (day, FILIZ_LOGIN_VERSION)).fetchone()
            automatic_retry = retryable and (not used or used[0] < 2)
            if not account['credential'] or not (daily or account['requested'] or account['state'] == 'running' or automatic_retry):
                return
            if automatic_retry and not account['requested']:
                conn.execute('INSERT OR REPLACE INTO filiz_retry_budget(id,day,used,flow) VALUES(1,?,?,?)',
                             (day, 1 + (used[0] if used else 0), FILIZ_LOGIN_VERSION))
            people = bts_students(conn)
            roster = roster_key(people)
            resume_requested = account['requested'] and account['state'] == 'error' and account['day'] == day
            resuming = account['state'] == 'running' or retryable or resume_requested
            if not resuming or account['cursor'] != roster:
                conn.execute('DELETE FROM filiz_scan_progress')
            revisit_failures = retryable and account['message'] == old_timeout
            completed = {ref for ref, outcome in conn.execute("SELECT ref,outcome FROM filiz_scan_progress")
                         if not revisit_failures or outcome in ('linked','ignored')}
            conn.execute("""UPDATE opco_accounts SET state='running',message='Lecture en cours.',attempted=?,requested=0,
                day=?,cursor=? WHERE provider=?""", (stamp, day if daily else account['day'], roster, provider))
            conn.commit()
        try:
            config = json.loads(secret(app).decrypt(account['credential']))
            with closing(connect()) as conn:
                saved = conn.execute('SELECT payload FROM filiz_session WHERE id=1').fetchone()
            cipher = secret(app)
            session_data = json.loads(cipher.decrypt(saved[0])) if saved else None
            def save_session(data):
                encrypted = cipher.encrypt(json.dumps(data).encode())
                with closing(connect()) as conn:
                    conn.execute("""INSERT OR REPLACE INTO filiz_session SELECT 1,? WHERE EXISTS
                        (SELECT 1 FROM opco_accounts WHERE provider='filiz' AND credential=?)""",
                        (encrypted,account['credential']))
                    conn.commit()
            def validate_run(conn):
                if conn.execute('SELECT credential FROM opco_accounts WHERE provider=?', (provider,)).fetchone()[0] != account['credential']:
                    raise ScanSuperseded
                if bts_students(conn) != people:
                    conn.execute("UPDATE opco_accounts SET requested=1,state='pending' WHERE provider=?", (provider,))
                    conn.commit()
                    raise ScanSuperseded

            def save_batch(group, results, failed, done, total):
                with closing(connect()) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    validate_run(conn)
                    for ref in group:
                        if ref in results:
                            store_contract(conn, ref, *results[ref])
                            outcome = 'partial' if ref in failed or results[ref][1].get('raw_stale') else 'linked'
                        else:
                            outcome = 'error' if ref in failed else 'ignored'
                        conn.execute('INSERT OR REPLACE INTO filiz_scan_progress VALUES (?,?)', (ref, outcome))
                    linked = conn.execute("SELECT count(*) FROM filiz_scan_progress WHERE outcome IN ('linked','partial')").fetchone()[0]
                    message = f'{done}/{total} dossiers examinés. {linked} contrat(s) rattaché(s).'
                    conn.execute("UPDATE opco_accounts SET message=? WHERE provider=?", (message, provider))
                    conn.commit()

            eligible = read_filiz(config, people, session_data, save_session, completed, save_batch)
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                validate_run(conn)
                progress = dict(conn.execute('SELECT ref,outcome FROM filiz_scan_progress'))
                if eligible - progress.keys():
                    raise ReadError('Lecture FILIZ incomplète. Les dossiers déjà lus sont conservés.')
                failed = {ref for ref in eligible if progress[ref] in ('error','partial')}
                previous = conn.execute("SELECT ref,payload FROM opco_contracts WHERE provider=?", (provider,)).fetchall()
                for ref, payload in previous:
                    outcome = progress.get(ref) if ref in eligible else None
                    if outcome == 'error':
                        item = json.loads(payload)
                        item['read_warning'] = 'Dossier non revérifié lors de la dernière lecture. Relevé précédent conservé.'
                        conn.execute('UPDATE opco_contracts SET payload=? WHERE provider=? AND ref=?',
                                     (json.dumps(item, ensure_ascii=False), provider, ref))
                    elif outcome not in ('linked','partial'):
                        conn.execute('DELETE FROM opco_contracts WHERE provider=? AND ref=?', (provider, ref))
                records = [json.loads(row[0]) for row in conn.execute(
                    'SELECT payload FROM opco_contracts WHERE provider=?', (provider,))]
                count = len(records)
                schedules = sum(bool(item.get('schedules')) and not item.get('raw_stale') for item in records)
                state = 'partial' if failed else 'ok'
                message = f'{count} contrat(s) rattaché(s) aux fiches BTS, dont {schedules} avec échéancier lu.'
                if failed:
                    message += f' {len(failed)} dossier(s) à vérifier.'
                conn.execute("""UPDATE opco_accounts SET state=?,message=?,succeeded=CASE WHEN ? THEN ? ELSE succeeded END,
                    roster=CASE WHEN ? THEN ? ELSE roster END WHERE provider='filiz'""",
                    (state,message,not failed,stamp,not failed,roster))
                conn.commit()
                app.logger.warning('FILIZ : lecture terminée (%s). %s',state,message)
        except ScanSuperseded:
            return
        except Exception as exc:
            if isinstance(exc, BrowserError):
                message = retry_text
            elif isinstance(exc, (ReadError, PortalError)):
                message = str(exc)
            else:
                message = 'Erreur de lecture FILIZ. Les dossiers enregistrés sont conservés.'
            with closing(connect()) as conn:
                conn.execute("UPDATE opco_accounts SET state='error',message=? WHERE provider=? AND credential=?",
                             (message, provider, account['credential']))
                conn.commit()
            app.logger.warning('FILIZ : lecture interrompue (%s). %s', type(exc).__name__, message)


def register_opcos(app, connect, require_admin, directory):
    with closing(connect()) as conn:
        schema(conn)
        # Resume a read that failed with the obsolete temporary browser cache.
        conn.execute("""UPDATE opco_accounts SET state='pending',requested=1,
            message='Reprise de la lecture FILIZ après correction de la lecture du portail.'
            WHERE provider='filiz' AND credential IS NOT NULL AND state='error'
            AND message IN ('Le serveur ne peut pas démarrer Chromium pour la lecture du portail.',
                            'Installation de Chromium indisponible sur le serveur.',
                            'Pagination FILIZ incohérente. Dernier relevé conservé.', 'Liste FILIZ incomplète.',
                            'Le nombre de dossiers lus diffère du compteur FILIZ. Relancez la synchronisation.')""")
        conn.commit()
        account = account_status(conn)
        app.logger.warning('FILIZ : compte configuré=%s, état=%s, dernière lecture complète=%s.',
                           bool(account['configured']), account['state'], account['succeeded'] or 'aucune')
        if account['configured'] and account['state'] in ('running','error'):
            processed = conn.execute('SELECT count(*) FROM filiz_scan_progress').fetchone()[0]
            saved = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM opco_contracts WHERE provider='filiz'")]
            financed = sum(bool(item.get('schedules')) and not item.get('raw_stale') for item in saved)
            app.logger.warning('FILIZ : progression enregistrée : %d dossiers examinés, %d contrats, %d échéanciers lus.',
                               processed, len(saved), financed)
    wake, guard = threading.Event(), threading.Lock()
    thread = None

    def worker():
        while True:
            try:
                tick(app, connect, directory)
            except Exception as exc:
                app.logger.warning('FILIZ : reprise nécessaire (%s)',type(exc).__name__)
            wake.wait(20)
            wake.clear()

    def start():
        nonlocal thread
        if not app.testing and os.environ.get('FILIZ_SYNC_DISABLED') != '1':
            with guard:
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(target=worker, name='opco-bts', daemon=True)
                    thread.start()

    def statuses():
        with closing(connect()) as conn:
            return dict(account_status(conn), portal=FILIZ_HOME+'/school')

    app.extensions['opco_start'] = start
    app.before_request(start)
    app.jinja_env.globals['filiz_status'] = statuses

    @app.post('/admin/parametres/opco/filiz')
    def filiz_settings():
        provider = 'filiz'
        expected = session.get('_planning_csrf', '')
        if not require_admin() or not expected or not hmac.compare_digest(expected, request.form.get('csrf_token', '')):
            abort(403)
        action = request.form.get('action')
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if action == 'connect':
                fields={'email':request.form.get('email','').strip(), 'password':request.form.get('password','')}
                try:
                    if '@' not in fields['email'] or len(fields['email'])>254 or not 1<=len(fields['password'])<=1024:
                        raise ReadError('Renseignez votre adresse e-mail et votre mot de passe FILIZ.')
                    credential = secret(app).encrypt(json.dumps(fields).encode())
                except (ReadError, PortalError) as exc:
                    flash(str(exc), 'error')
                    return redirect(url_for('admin_settings', _anchor='opco-' + provider), 303)
                conn.execute("""UPDATE opco_accounts SET credential=?,requested=1,state='pending',message='Accès à vérifier.',
                    day='',cursor='',roster='',attempted='',succeeded='' WHERE provider=?""", (credential, provider))
                # A replaced key can belong to a different CFA. Do not expose old account records.
                conn.execute('DELETE FROM opco_contracts WHERE provider=?', (provider,))
            elif action == 'sync':
                conn.execute("UPDATE opco_accounts SET requested=1 WHERE provider=? AND credential IS NOT NULL AND state!='running'", (provider,))
            elif action == 'disconnect':
                conn.execute("""UPDATE opco_accounts SET credential=NULL,requested=0,state='unconfigured',message='',
                    day='',cursor='',roster='',attempted='',succeeded='' WHERE provider=?""", (provider,))
                conn.execute('DELETE FROM opco_contracts WHERE provider=?', (provider,))
            else:
                abort(400)
            if action in ('connect','disconnect'):
                conn.execute('DELETE FROM filiz_session')
                conn.execute('DELETE FROM filiz_scan_progress')
                conn.execute('DELETE FROM filiz_retry_budget')
            conn.commit()
        start()
        wake.set()
        return redirect(url_for('admin_settings', _anchor='opco-' + provider), 303)
