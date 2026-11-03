"""Persistent read-only contract synchronization for the school accounts."""
from contextlib import closing
from datetime import datetime, timedelta
import fcntl
import hashlib
import hmac
import json
from pathlib import Path
import threading

from flask import abort, flash, redirect, request, session, url_for

from akto_portal import PortalError, START_DATE
from akto_sync import PARIS, secret
from opco_convergence import PROVIDERS, ReadError, endpoint, identity, read_contracts
from filiz_portal import HOME as FILIZ_HOME, read_filiz
from training_programs import BTS_LABELS
from wedof_contract_data import FINANCERS

ACCOUNTS = {'filiz': ('FILIZ', FILIZ_HOME+'/school'), **{k:(FINANCERS[code],portal) for k,(code,_,portal) in PROVIDERS.items()}}
BTS_MARKS = ','.join('?' for _ in BTS_LABELS)


def schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS opco_accounts (
          provider TEXT PRIMARY KEY, credential BLOB, requested INTEGER NOT NULL DEFAULT 0,
          day TEXT DEFAULT '', state TEXT DEFAULT 'unconfigured', message TEXT DEFAULT '',
          attempted TEXT DEFAULT '', succeeded TEXT DEFAULT '', cursor TEXT DEFAULT '', roster TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS opco_contracts (
          provider TEXT NOT NULL, ref TEXT NOT NULL, candidate_id TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(provider,ref));
        CREATE TABLE IF NOT EXISTS filiz_session (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL);
        CREATE INDEX IF NOT EXISTS opco_student ON opco_contracts(candidate_id);
    ''')
    conn.executemany('INSERT OR IGNORE INTO opco_accounts(provider) VALUES (?)', [(k,) for k in ACCOUNTS])
    conn.commit()


def same_contract(left, right):
    if left.get('financer') != right.get('financer'):
        return False
    return any(left.get(key) and left[key] == right.get(key)
               for key in ('deca_number','internal_number','external_number'))


def student_records(conn, person):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opco_contracts'").fetchone():
        return []
    if (person.get('bts') or '').strip().upper() not in BTS_LABELS:
        return []
    if 'date_naissance' not in person:
        current = conn.execute('SELECT nom,prenom,date_naissance FROM candidats WHERE id=?', (person['id'],)).fetchone()
        if not current:
            return []
        person = {**person, **dict(current)}
    key = identity(person.get('nom'), person.get('prenom'), person.get('date_naissance'))
    result = []
    for row in conn.execute('''SELECT c.payload,a.provider,a.state FROM opco_contracts c JOIN opco_accounts a
          ON a.provider=c.provider WHERE c.candidate_id=? AND a.credential IS NOT NULL ORDER BY c.provider,c.ref''', (person['id'],)):
        item = json.loads(row['payload'])
        if (item.get('contract_start', '') >= START_DATE and all(key) and
                key == identity(item.get('apprentice_last_name'), item.get('apprentice_first_name'), item.get('apprentice_birth_date'))):
            if row['state'] == 'error':
                item['read_warning'] = 'Dernière synchronisation en échec. Le relevé précédent est affiché.'
            result.append(item)
    return result


def coverage(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opco_accounts'").fetchone():
        return '', False
    labels = {'unconfigured':'à connecter', 'running':'lecture en cours', 'pending':'en attente',
              'error':'lecture en échec', 'partial':'lecture partielle', 'ok':'lecture effectuée'}
    rows = conn.execute('SELECT provider,state FROM opco_accounts ORDER BY provider').fetchall()
    summary = ' · '.join(ACCOUNTS[r['provider']][0]+' ('+labels.get(r['state'], 'à vérifier')+')' for r in rows)
    filiz_ok = any(r['provider']=='filiz' and r['state']=='ok' for r in rows)
    return summary, not filiz_ok and any(r['state'] != 'ok' for r in rows)


def bts_students(conn):
    return [dict(r) for r in conn.execute(
        f"SELECT id,nom,prenom,date_naissance,bts FROM candidats WHERE upper(trim(bts)) IN ({BTS_MARKS}) ORDER BY id", tuple(BTS_LABELS))]


def tick(app, connect, directory, provider, now=None, reader=read_contracts):
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
            if not account['credential'] or not (daily or account['requested'] or account['state'] == 'running'):
                return
            people = bts_students(conn)
            roster = hashlib.sha256(json.dumps(people, sort_keys=True).encode()).hexdigest()
            since = account['cursor'] if account['roster'] == roster else ''
            previous = {r['ref']: (r['candidate_id'], json.loads(r['payload'])) for r in conn.execute(
                'SELECT * FROM opco_contracts WHERE provider=?', (provider,))}
            # Existing local references also cover eligible contracts created in the OPCO
            # system before the discovery window. Verify them again directly with the OPCO.
            known = set(previous)
            if provider != 'filiz' and not since and conn.execute("SELECT 1 FROM sqlite_master WHERE name='student_wedof_contracts'").fetchone():
                for saved in conn.execute(f"""SELECT w.payload FROM student_wedof_contracts w JOIN candidats c
                        ON c.id=w.candidate_id WHERE upper(trim(c.bts)) IN ({BTS_MARKS})""",tuple(BTS_LABELS)):
                    try:
                        archive = json.loads(saved[0])
                    except (ValueError, TypeError):
                        continue
                    if (isinstance(archive, dict) and archive.get('financer') == PROVIDERS[provider][0] and
                            (archive.get('contract_start') or '') >= START_DATE and archive.get('internal_number')):
                        known.add(str(archive['internal_number']))
            conn.execute("""UPDATE opco_accounts SET state='running',message='Lecture en cours.',attempted=?,requested=0,day=?
                WHERE provider=?""", (stamp, day if daily else account['day'], provider))
            conn.commit()
        try:
            config = json.loads(secret(app).decrypt(account['credential']))
            if provider == 'filiz' and reader is read_contracts and people:
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
                since = ''  # Each FILIZ scan covers the complete school catalogue.
                results, failed, active = read_filiz(config, people, session_data, save_session)
            else:
                results, failed, active = reader(provider, config, people, since, known) if people else ({}, set(), set())
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('SELECT credential FROM opco_accounts WHERE provider=?', (provider,)).fetchone()[0] != account['credential']:
                    return
                if bts_students(conn) != people:
                    conn.execute("UPDATE opco_accounts SET requested=1,state='pending' WHERE provider=?", (provider,))
                    conn.commit()
                    return
                for ref, (cid, item) in results.items():
                    old_cid, old = previous.get(ref, (None, {}))
                    if cid == old_cid:
                        if item.get('raw_stale') and 'schedules' in old:
                            item['schedules'] = old['schedules']
                            item['raw_checked_at'] = old.get('raw_checked_at')
                            if provider=='filiz':
                                for field in ('invoices','filiz_paid','filiz_pending','engagement','filiz_updated',
                                              'extra_costs_available','extra_costs'):
                                    if field in old:
                                        item[field]=old[field]
                        if item.get('invoice_error') and 'invoices' in old:
                            item['invoices'] = old['invoices']
                    conn.execute('INSERT OR REPLACE INTO opco_contracts VALUES (?,?,?,?)',
                                 (provider, ref, cid, json.dumps(item, ensure_ascii=False)))
                for ref in previous.keys() - results.keys():
                    if ref in failed:
                        cid, item = previous[ref]
                        item['read_warning'] = 'Dossier non revérifié lors de la dernière lecture. Relevé précédent conservé.'
                        conn.execute('UPDATE opco_contracts SET payload=? WHERE provider=? AND ref=?',
                                     (json.dumps(item, ensure_ascii=False), provider, ref))
                    elif ref in active or not since:
                        conn.execute('DELETE FROM opco_contracts WHERE provider=? AND ref=?', (provider, ref))
                count = conn.execute('SELECT count(*) FROM opco_contracts WHERE provider=?', (provider,)).fetchone()[0]
                state = 'partial' if failed else 'ok'
                message = f'{count} contrat(s) rattaché(s) aux fiches BTS.'
                if failed:
                    message += f' {len(failed)} dossier(s) à vérifier.'
                app.logger.info('OPCO %s : %s',provider,message)
                cursor = (clock.date() - timedelta(days=1)).isoformat()
                conn.execute('''UPDATE opco_accounts SET state=?,message=?,succeeded=CASE WHEN ? THEN ? ELSE succeeded END,
                    cursor=CASE WHEN ? THEN ? ELSE cursor END,roster=CASE WHEN ? THEN ? ELSE roster END WHERE provider=?''',
                    (state, message, not failed, stamp, not failed, cursor, not failed, roster, provider))
                conn.commit()
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ReadError, PortalError)) else 'Lecture interrompue. Vérifiez les accès puis relancez.'
            with closing(connect()) as conn:
                conn.execute("UPDATE opco_accounts SET state='error',message=? WHERE provider=? AND credential=?",
                             (message, provider, account['credential']))
                conn.commit()
            app.logger.warning('Convergence %s : lecture interrompue (%s)', provider, type(exc).__name__)


def register_opcos(app, connect, require_admin, directory):
    with closing(connect()) as conn:
        schema(conn)
    wake, guard = threading.Event(), threading.Lock()
    thread = None

    def worker():
        while True:
            for provider in ACCOUNTS:
                try:
                    tick(app, connect, directory, provider)
                except Exception as exc:
                    app.logger.warning('Convergence %s : reprise nécessaire (%s)', provider, type(exc).__name__)
            wake.wait(20)
            wake.clear()

    def start():
        nonlocal thread
        if not app.testing:
            with guard:
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(target=worker, name='opco-bts', daemon=True)
                    thread.start()

    def statuses():
        with closing(connect()) as conn:
            rows = {r['provider']: dict(r) for r in conn.execute('''SELECT provider,credential IS NOT NULL AS configured,
                    state,message,attempted,succeeded,requested FROM opco_accounts''')}
        return [dict(rows[k], label=label, portal=portal) for k, (label, portal) in ACCOUNTS.items()]

    app.extensions['opco_start'] = start
    app.before_request(start)
    app.jinja_env.globals['opco_statuses'] = statuses

    @app.post('/admin/parametres/opco/<provider>')
    def opco_settings(provider):
        if provider not in ACCOUNTS:
            abort(404)
        expected = session.get('_planning_csrf', '')
        if not require_admin() or not expected or not hmac.compare_digest(expected, request.form.get('csrf_token', '')):
            abort(403)
        action = request.form.get('action')
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if action == 'connect':
                fields = {k: request.form.get(k, '').strip() for k in ('api','token','scope','client_id','client_secret','key')}
                try:
                    if provider=='filiz':
                        fields={'email':request.form.get('email','').strip(), 'password':request.form.get('password','')}
                        if '@' not in fields['email'] or len(fields['email'])>254 or not 1<=len(fields['password'])<=1024:
                            raise ReadError('Renseignez votre adresse e-mail et votre mot de passe FILIZ.')
                    elif any(not fields[k] for k in ('client_id','client_secret','key')) or any(len(v)>8192 for v in fields.values()):
                        raise ReadError('Renseignez les identifiants techniques et la clé CFA.')
                    if provider!='filiz':
                        for k in ('api', 'token'):
                            fields[k] = endpoint(provider, k, fields[k])
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
            if provider=='filiz' and action in ('connect','disconnect'):
                conn.execute('DELETE FROM filiz_session')
            conn.commit()
        start()
        wake.set()
        return redirect(url_for('admin_settings', _anchor='opco-' + provider), 303)
