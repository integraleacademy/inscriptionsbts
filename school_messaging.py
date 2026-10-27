"""Previewed school communications with frozen recipients and durable delivery claims."""
from person_names import person_name
from contextlib import closing
import json
import secrets
import time
from urllib.parse import urlsplit

from flask import abort, jsonify, render_template, request, session
from school_email import SENDERS, LAYOUTS, DEFAULT_ACCENT, render_school_email
from candidate_messages import _equal, _recipient
from campus_admin import ENROLLED, csrf
from promotions import list_promotions


def schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS school_messages(
        id TEXT PRIMARY KEY,channel TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,
        html TEXT NOT NULL,created_at REAL NOT NULL,started_at REAL,owner TEXT NOT NULL,
        sender_json TEXT NOT NULL DEFAULT '{}')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS school_message_recipients(
        message_id TEXT NOT NULL,recipient TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',provider_id TEXT,updated_at REAL NOT NULL,mode TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(message_id,recipient))''')
    if 'mode' not in {r[1] for r in conn.execute('PRAGMA table_info(school_message_recipients)')}:
        conn.execute("ALTER TABLE school_message_recipients ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
    if 'sender_json' not in {r[1] for r in conn.execute('PRAGMA table_info(school_messages)')}:
        conn.execute("ALTER TABLE school_messages ADD COLUMN sender_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()


def audience(conn, data):
    if not isinstance(data,dict): raise ValueError('Requête invalide.')
    channel = data.get('channel','email')
    if channel not in ('email','sms'): raise ValueError('Choisissez un e-mail ou un SMS.')
    groups=data.get('groups',[])
    promotions=data.get('promotions',[])
    if not isinstance(groups,list) or not groups or any(g not in ('students','trainers','companies') for g in groups):
        raise ValueError('Choisissez au moins un groupe de destinataires.')
    if not isinstance(promotions,list) or len(promotions)>500 or not all(isinstance(p,str) for p in promotions):
        raise ValueError('Vérifiez les promotions choisies.')
    mode=data.get('mode','')
    if mode not in ('','presentiel','distanciel'): raise ValueError('Choisissez une modalité valide.')
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    people=[]
    if 'students' in groups:
        for r in conn.execute('''SELECT c.id,c.prenom,c.nom,c.email,c.tel,c.mode,s.promotion_id FROM candidats c
            LEFT JOIN student_promotions s ON s.candidate_id=c.id WHERE c.statut IN (?,?) ORDER BY c.nom,c.prenom''',ENROLLED):
            if promotions and r['promotion_id'] not in promotions: continue
            if mode and r['mode']!=mode: continue
            people.append(dict(r,kind='Étudiant',name=person_name(r['nom'],r['prenom'])))
    if 'trainers' in groups and 'trainers' in tables:
        phones={r['trainer_id']:r['phone'] for r in conn.execute('SELECT * FROM teaching_contacts')} if 'teaching_contacts' in tables else {}
        for r in conn.execute('SELECT id,nom,prenom,email FROM trainers WHERE active=1 ORDER BY nom,prenom'):
            people.append(dict(r,tel=phones.get(r['id'],''),kind='Formateur',name=person_name(r['nom'],r['prenom'])))
    if 'companies' in groups and 'companies' in tables:
        people += [dict(r,tel=r['phone'],kind='Entreprise') for r in conn.execute('SELECT name,email,phone FROM companies ORDER BY name')]
    recipients, invalid, duplicate = {}, [], 0
    for person in people:
        try: contact=_recipient(person,channel)
        except ValueError:
            invalid.append(dict(name=person['name'],kind=person['kind']))
            continue
        normalized=contact.casefold() if channel=='email' else contact
        if normalized in recipients:
            duplicate+=1
            continue
        recipients[normalized]=dict(recipient=contact,name=person['name'],kind=person['kind'],mode=person.get('mode',''))
    return list(recipients.values()),invalid,duplicate


def content(data):
    if not isinstance(data,dict): raise ValueError('Requête invalide.')
    channel=data.get('channel','email')
    subject=str(data.get('subject') or '').strip()
    body=str(data.get('body') or '').strip()
    if channel not in ('email','sms') or not body or len(body)>(20000 if channel=='email' else 1600) or '\x00' in body:
        raise ValueError('Saisissez un message valide (20 000 caractères par e-mail, 1 600 par SMS).')
    if channel=='email' and (not subject or len(subject)>200 or '\n' in subject or '\r' in subject):
        raise ValueError('Saisissez un objet de 200 caractères maximum sur une ligne.')
    action_url=str(data.get('action_url') or '').strip() if channel=='email' else ''
    action_label=str(data.get('action_label') or '').strip() if action_url else ''
    if action_url:
        parsed=urlsplit(action_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or len(action_url)>2000 or any(ord(c)<33 for c in action_url):
            raise ValueError('Le bouton doit mener vers une adresse https:// valide.')
        if not action_label or len(action_label)>80: raise ValueError('Nommez le bouton (80 caractères maximum).')
    html, sender = '', {}
    if channel == 'email':
        html, sender = render_school_email(subject, body, data.get('sender_id', 'clement'),
            data.get('layout', 'crm'), action_url=action_url, action_label=action_label,
            accent_title=data.get('accent_title', DEFAULT_ACCENT))
    return dict(channel=channel,subject=subject if channel=='email' else '',body=body,html=html,sender=sender)


def register_school_messaging(app, db_connect, require_admin, send_mail, send_sms):
    def guard(write=False):
        if not require_admin(): abort(403)
        if write and not _equal(request.headers.get('X-CSRF-Token'),session.get('_campus_csrf')):
            abort(400,'La page a expiré. Rechargez-la.')

    def state(conn, mid):
        row=conn.execute('SELECT * FROM school_messages WHERE id=?',(mid,)).fetchone()
        if not row: abort(404)
        recipients=[dict(r) for r in conn.execute('SELECT recipient,name,kind,status,updated_at,mode FROM school_message_recipients WHERE message_id=? ORDER BY name',(mid,))]
        counts={name:sum(r['status']==name for r in recipients) for name in ('pending','sending','sent','failed')}
        return dict(id=mid,channel=row['channel'],subject=row['subject'],body=row['body'],html=row['html'],
                    sender=json.loads(row['sender_json']),
                    started=bool(row['started_at']),recipients=recipients,counts=counts,total=len(recipients),
                    can_send=_equal(row['owner'],csrf()) and (bool(row['started_at']) or time.time()-row['created_at']<900),
                    done=not counts['pending'])

    @app.get('/admin/messagerie')
    def admin_school_messages():
        guard()
        with closing(db_connect()) as conn:
            schema(conn)
            promotions=list_promotions(conn,active_only=True)
            history=[dict(r) for r in conn.execute('''SELECT m.id,m.subject,m.channel,m.created_at,m.started_at,
                COUNT(r.recipient) AS total,SUM(r.status='sent') AS sent,SUM(r.status='failed') AS failed,
                SUM(r.status='pending') AS pending,SUM(r.status='sending') AS sending
                FROM school_messages m JOIN school_message_recipients r ON r.message_id=m.id
                GROUP BY m.id ORDER BY m.created_at DESC LIMIT 30''')]
        return render_template('school_messages.html',title='Messagerie · Intégrale Academy',
                               promotions=promotions,history=history,senders=SENDERS.values(),layouts=LAYOUTS,
                               default_accent=DEFAULT_ACCENT)

    @app.post('/admin/messagerie/destinataires')
    def school_message_audience():
        guard(True)
        try:
            with closing(db_connect()) as conn:
                list_promotions(conn)
                recipients,invalid,duplicate=audience(conn,request.get_json(silent=True) or {})
            return jsonify(ok=True,recipients=recipients,invalid=invalid,duplicate=duplicate)
        except ValueError as error: return jsonify(ok=False,error=str(error)),400

    @app.post('/admin/messagerie/apercu')
    def school_message_preview():
        guard(True)
        data=request.get_json(silent=True) or {}
        try:
            message=content(data)
            with closing(db_connect()) as conn:
                schema(conn)
                list_promotions(conn)
                recipients,invalid,duplicate=audience(conn,data)
                if not recipients: raise ValueError('Aucun destinataire joignable dans cette sélection.')
                mid,now=secrets.token_urlsafe(24),time.time()
                conn.execute('INSERT INTO school_messages(id,channel,subject,body,html,created_at,owner,sender_json) VALUES(?,?,?,?,?,?,?,?)',
                             (mid,message['channel'],message['subject'],message['body'],message['html'],now,csrf(),json.dumps(message['sender'])))
                conn.executemany('INSERT INTO school_message_recipients(message_id,recipient,name,kind,updated_at,mode) VALUES(?,?,?,?,?,?)',
                                 [(mid,p['recipient'],p['name'],p['kind'],now,p.get('mode','')) for p in recipients])
                conn.commit()
                snapshot=state(conn,mid)
            return jsonify(ok=True,**snapshot,invalid=invalid,duplicate=duplicate)
        except ValueError as error: return jsonify(ok=False,error=str(error)),400

    @app.get('/admin/messagerie/<mid>')
    def school_message_state(mid):
        guard()
        with closing(db_connect()) as conn:
            schema(conn)
            return jsonify(ok=True,**state(conn,mid))

    @app.post('/admin/messagerie/<mid>/envoyer')
    def school_message_send(mid):
        guard(True)
        with closing(db_connect()) as conn:
            schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            message=conn.execute('SELECT * FROM school_messages WHERE id=?',(mid,)).fetchone()
            if not message: abort(404)
            if not _equal(message['owner'],csrf()): abort(403)
            if not message['started_at']:
                if time.time()-message['created_at']>=900:
                    return jsonify(ok=False,error='L’aperçu a expiré. Prévisualisez à nouveau.'),400
                if (request.get_json(silent=True) or {}).get('confirm') is not True:
                    return jsonify(ok=False,error='Confirmez l’envoi après avoir relu l’aperçu.'),400
                conn.execute('UPDATE school_messages SET started_at=? WHERE id=?',(time.time(),mid))
            recipient=conn.execute("SELECT * FROM school_message_recipients WHERE message_id=? AND status='pending' ORDER BY name LIMIT 1",(mid,)).fetchone()
            if not recipient:
                conn.commit()
                return jsonify(ok=True,**state(conn,mid))
            conn.execute("UPDATE school_message_recipients SET status='sending',updated_at=? WHERE message_id=? AND recipient=?",(time.time(),mid,recipient['recipient']))
            conn.commit()
        provider=None
        try:
            if message['channel']=='email':
                sender=json.loads(message['sender_json'])
                # Send the identity frozen with the preview, never a new client value.
                # Historical previews retain the school's original sender.
                options=dict(sender_email=sender['email'],sender_name=sender['name']+' · Intégrale Academy',
                             reply_to=sender['email']) if sender else {}
                provider=send_mail(recipient['recipient'],message['subject'],message['html'],**options)
            else:
                provider=send_sms(recipient['recipient'],message['body'])
        except Exception:
            app.logger.warning('School message delivery unconfirmed; no automatic retry (%s)',message['channel'])
        with closing(db_connect()) as conn:
            conn.execute('UPDATE school_message_recipients SET status=?,provider_id=?,updated_at=? WHERE message_id=? AND recipient=?',
                         ('sent' if provider else 'failed',str(provider) if provider else None,time.time(),mid,recipient['recipient']))
            conn.commit()
            return jsonify(ok=True,**state(conn,mid))

    @app.after_request
    def private_messages(response):
        if request.path.startswith('/admin/messagerie'):
            response.headers['Cache-Control']='private, no-store'
        return response
