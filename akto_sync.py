"""Server-side AKTO synchronization for BTS MOS, on the persistent BTS disk."""
import base64
import fcntl
import hashlib
import hmac
import json
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from flask import abort, flash, redirect, request, session, url_for

from akto_portal import PortalError, read_portal
from akto_pilot import contract_for

PARIS = ZoneInfo('Europe/Paris')


def schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS akto_connection (
          id INTEGER PRIMARY KEY CHECK(id=1), credential BLOB, requested INTEGER DEFAULT 0,
          day TEXT DEFAULT '', state TEXT DEFAULT 'unconfigured', message TEXT DEFAULT '',
          attempted TEXT DEFAULT '', succeeded TEXT DEFAULT '');
        INSERT OR IGNORE INTO akto_connection(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS akto_students (
          candidate_id TEXT PRIMARY KEY, records TEXT, message TEXT NOT NULL, seen TEXT NOT NULL);
    ''')


def secret(app):
    key = app.secret_key
    if not key or len(key)<20:
        raise PortalError('La clé de chiffrement de la plateforme doit être configurée.')
    raw = key.encode() if isinstance(key,str) else key
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b'bts-akto-v1\0'+raw).digest()))


def get_records(conn,cid):
    result=conn.execute('SELECT records,message FROM akto_students WHERE candidate_id=?',(cid,)).fetchone()
    if result and result['records'] is not None:
        return json.loads(result['records']),result['message']
    pilot=contract_for(cid)
    return ([pilot] if pilot else []), (result['message'] if result else 'En attente de la première lecture AKTO.')


def run_due(app,connect,directory,now=None,reader=read_portal):
    clock=now or datetime.now(PARIS)
    day=clock.date().isoformat()
    stamp=clock.strftime('%d/%m/%Y à %H:%M')
    with (Path(directory)/'akto-sync.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM akto_connection WHERE id=1').fetchone()
            if not row['credential']:
                return
            daily=clock.hour>=5 and row['day']!=day
            if not (row['requested'] or daily or row['state']=='running'):
                return
            conn.execute("""UPDATE akto_connection SET requested=0,state='running',attempted=?,day=?,message='Lecture du portail en cours.' WHERE id=1""",
                         (stamp,day if daily else row['day']))
            people=[dict(p) for p in conn.execute("SELECT id,prenom,nom,date_naissance FROM candidats WHERE upper(trim(bts))='MOS'")]
            conn.commit()
        def save(person,records,message):
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                current=conn.execute("SELECT 1 FROM candidats WHERE id=? AND upper(trim(bts))='MOS' AND nom=? AND prenom=? AND COALESCE(date_naissance,'')=COALESCE(?,'')",
                                     (person['id'],person['nom'],person['prenom'],person['date_naissance'])).fetchone()
                if not current or conn.execute('SELECT credential FROM akto_connection WHERE id=1').fetchone()[0]!=row['credential']:
                    return
                # Do not replace a verified agreement with a partial portal response.
                if records is not None:
                    previous,_=get_records(conn,person['id'])
                    old={r['reference']:r for r in previous}
                    for record in records:
                        saved=old.get(record['reference'],{})
                        if saved.get('schedules') and not record.get('schedules'):
                            raise PortalError('Courrier déjà connu indisponible.')
                data=None if records is None else json.dumps(records,ensure_ascii=False)
                conn.execute('''INSERT INTO akto_students VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET
                    records=COALESCE(excluded.records,akto_students.records),message=excluded.message,seen=excluded.seen''',
                             (person['id'],data,message,stamp))
                conn.commit()
        try:
            email,password=json.loads(secret(app).decrypt(row['credential']))
            errors=reader(email,password,people,save)
            state='partial' if errors else 'ok'
            message=f'{len(people)} fiche(s) MOS examinée(s). {errors} lecture(s) à vérifier.'
        except PortalError as exc:
            state,message='error',str(exc)
        except Exception:
            state,message='error','Lecture AKTO interrompue. Vérifiez le compte prestataire et relancez la synchronisation.'
        with closing(connect()) as conn:
            conn.execute('''UPDATE akto_connection SET state=?,message=?,succeeded=CASE WHEN ?='ok' THEN ? ELSE succeeded END
                            WHERE id=1 AND credential=?''',(state,message,state,stamp,row['credential']))
            conn.commit()
        app.logger.info('AKTO MOS : %s (%s)',state,stamp)


def register_akto(app,connect,require_admin,directory):
    with closing(connect()) as conn:
        schema(conn)
    wake,guard=threading.Event(),threading.Lock()
    thread=None
    def worker():
        while True:
            try:
                run_due(app,connect,directory)
            except Exception:
                app.logger.warning('AKTO MOS : passage à reprendre.')
            wake.wait(20)
            wake.clear()
    def start():
        nonlocal thread
        if app.testing:
            return
        with guard:
            if thread is None or not thread.is_alive():
                thread=threading.Thread(target=worker,name='akto-mos',daemon=True)
                thread.start()
    app.extensions['akto_start']=start
    app.before_request(start)
    def status():
        with closing(connect()) as conn:
            return dict(conn.execute('SELECT credential IS NOT NULL AS configured,state,message,attempted,succeeded,requested FROM akto_connection WHERE id=1').fetchone())
    app.jinja_env.globals['akto_status']=status

    @app.post('/admin/parametres/akto')
    def akto_settings():
        expected=session.get('_planning_csrf','')
        if not require_admin() or not expected or not hmac.compare_digest(expected,request.form.get('csrf_token','')):
            abort(403)
        action=request.form.get('action')
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if action=='connect':
                email=request.form.get('email','').strip()
                password=request.form.get('password','')
                if '@' not in email or len(email)>254 or not password or len(password)>512:
                    abort(400)
                try:
                    encrypted=secret(app).encrypt(json.dumps([email,password]).encode())
                except PortalError as exc:
                    flash(str(exc),'error')
                    return redirect(url_for('admin_settings',_anchor='akto'),303)
                conn.execute("UPDATE akto_connection SET credential=?,requested=1,state='pending',message='Connexion à vérifier.',succeeded='' WHERE id=1",(encrypted,))
            elif action=='sync':
                conn.execute("UPDATE akto_connection SET requested=1 WHERE id=1 AND credential IS NOT NULL AND state!='running'")
            elif action=='disconnect':
                conn.execute("UPDATE akto_connection SET credential=NULL,requested=0,state='unconfigured',message='',succeeded='' WHERE id=1")
            else:
                abort(400)
            conn.commit()
        start()
        wake.set()
        return redirect(url_for('admin_settings',_anchor='akto'),303)
