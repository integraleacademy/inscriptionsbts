"""Trainer account lifecycle and exact cohort authorization; every email is mocked."""
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from flask import Flask, session, template_rendered
from werkzeug.security import check_password_hash

import trainer_access
import promotions

PASSWORD='Une phrase formateur 2027'
NEW_PASSWORD='Une nouvelle phrase formateur 2028'


@pytest.fixture
def access(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
    app.secret_key='trainer-tests-secret'
    app.config['TESTING']=True
    app.jinja_env.filters['dmy']=lambda value:value
    path=tmp_path/'trainers.sqlite'
    def db():
        conn=sqlite3.connect(path)
        conn.row_factory=sqlite3.Row
        return conn
    with db() as conn:
        conn.execute('''CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,mode TEXT,email TEXT,tel TEXT,numero_dossier TEXT,rentree_annee INTEGER,statut TEXT,slug_public TEXT,num_secu TEXT,date_naissance TEXT,f_photo TEXT)''')
    mails=[]
    def mail(*args):
        mails.append(args)
        return False if app.config.get('TRAINER_MAIL_FAIL') else 'mock-message-id'
    trainer_access.register_trainer_access(app,db,mail,lambda:bool(session.get('admin_ok')))
    promotions.register_promotions(app,db,lambda:bool(session.get('admin_ok')))
    contexts=[]
    def capture(sender,template,context,**extra):
        contexts.append((template.name,context))
    template_rendered.connect(capture,app,weak=False)
    monkeypatch.setenv('BASE_URL','https://school.example.test')
    client=app.test_client()
    with client.session_transaction() as state:
        state['admin_ok']=True
    return client,db,mails,contexts


def csrf(client,path='/admin/formateurs'):
    response=client.get(path)
    assert response.status_code==200
    with client.session_transaction() as state:
        return state['_trainer_csrf']


def promotion_ids(access,values):
    result=[]
    with access[1]() as conn:
        trainer_access._schema(conn)
        for value in values:
            if ':' not in value:
                result.append(value)
                continue
            bts,year=value.split(':')
            row=conn.execute('SELECT id FROM promotions WHERE bts=? AND rentree_annee=? ORDER BY created_at LIMIT 1',(bts,int(year))).fetchone()
            if row:
                result.append(row[0])
            else:
                pid='promotion-'+bts+'-'+year
                conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(pid,'BTS '+bts+' 1ère année',bts,1,int(year),year+'-09-01',str(int(year)+1)+'-06-30','now','now'))
                result.append(pid)
        conn.commit()
    return result


def create(access,email='teacher@example.test',assignments=None,nom='DUPONT',prenom='Camille'):
    client,db,_,_=access
    response=client.post('/admin/formateurs',json=dict(csrf_token=csrf(client),nom=nom,prenom=prenom,email=email,assignments=promotion_ids(access,assignments if assignments is not None else ['MCO:2026','MOS:2027'])))
    assert response.status_code==201,response.data
    with db() as conn:
        return conn.execute('SELECT id FROM trainers WHERE email=?',(email.lower().strip(),)).fetchone()[0]


def admin_post(access,trainer_id,action,**fields):
    client=access[0]
    if 'assignments' in fields:fields['assignments']=promotion_ids(access,fields['assignments'])
    return client.post(f'/admin/formateurs/{trainer_id}/{action}',json=dict(csrf_token=csrf(client),**fields))


def invite(access,trainer_id):
    response=admin_post(access,trainer_id,'send-access')
    assert response.status_code==200,response.data
    return re.search(r'href="([^"]+/formateur/mot-de-passe/[^"]+)"',access[2][-1][2]).group(1)


def open_link(client,link):
    response=client.get(urlsplit(link).path)
    assert response.headers['Location']=='/formateur/mot-de-passe'
    return client.get('/formateur/mot-de-passe')


def password(client,value=PASSWORD):
    return client.post('/formateur/mot-de-passe',data=dict(csrf_token=csrf(client,'/formateur/mot-de-passe'),new_password=value,confirm_password=value))


def login(client,email='teacher@example.test',value=PASSWORD):
    return client.post('/formateur/connexion',data=dict(csrf_token=csrf(client,'/formateur/connexion'),email=email,password=value))


def active(access,assignments=None):
    tid=create(access,assignments=assignments)
    link=invite(access,tid)
    assert b'name="new_password"' in open_link(access[0],link).data
    assert password(access[0]).headers['Location']=='/formateur/connexion?reset=ok'
    assert login(access[0]).headers['Location']=='/formateur'
    return tid


def recover(access,client=None,email='teacher@example.test'):
    client=client or access[0]
    response=client.post('/formateur/mot-de-passe-oublie',data=dict(csrf_token=csrf(client,'/formateur/mot-de-passe-oublie'),email=email))
    assert response.status_code==200
    return response


def seed(db,cid,bts,year,status='confirmee'):
    with db() as conn:
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,cid.upper(),'Élève',bts,'presentiel',cid+'@example.test','0600000000',f'{year}-DOS-{cid}',year,status,'PRIVATE-SLUG-'+cid,'PRIVATE-NIR-'+cid,'PRIVATE-DOB-'+cid,'PRIVATE-DOC-'+cid))
        group=conn.execute('SELECT id FROM promotions WHERE bts=? AND rentree_annee=? ORDER BY created_at LIMIT 1',(bts.strip().upper(),year)).fetchone()
        if group:conn.execute('INSERT INTO student_promotions(candidate_id,promotion_id,assigned_at) VALUES(?,?,?)',(cid,group[0],'test-explicit-assignment'))


def test_create_update_do_not_send_emails_and_normalize_identity(access):
    tid=create(access,email='TEACHER@EXAMPLE.TEST',nom='duPont',prenom='cAMILLE')
    assert not access[2]
    with access[1]() as conn:
        row=conn.execute('SELECT * FROM trainers WHERE id=?',(tid,)).fetchone()
        assert row['nom']=='DUPONT' and row['prenom']=='Camille'
        assert row['email']=='teacher@example.test' and row['password_hash'] is None
        assert row['invited_at'] is None
    response=admin_post(access,tid,'update',nom='Dupont',prenom='Camille',email='teacher@example.test',assignments=['CI:2027'])
    assert response.status_code==200
    assert not access[2]


def test_admin_auth_csrf_and_unique_email_enforced(access):
    client=access[0]
    stranger=client.application.test_client()
    assert stranger.get('/admin/formateurs').status_code==403
    assert stranger.post('/admin/formateurs',json={}).status_code==403
    assert client.post('/admin/formateurs',json={}).status_code==400
    assert client.post('/admin/formateurs',json={'csrf_token':'é'}).status_code==400
    create(access)
    response=client.post('/admin/formateurs',json=dict(csrf_token=csrf(client),nom='AUTRE',prenom='Alex',email='TEACHER@example.test',assignments=[]))
    assert response.status_code==409
    assert not access[2]


def test_assignment_validation_and_unassigned_account_allowed(access):
    client=access[0]
    for assignments in [['OTHER:2027'],['MCO:garbage'],['MCO:1900'],['MCO'],['MCO:2027']*61]:
        response=client.post('/admin/formateurs',json=dict(csrf_token=csrf(client),nom='TEST',prenom='Alex',email='test@example.test',assignments=assignments))
        assert response.status_code==400
    tid=create(access,assignments=[])
    with access[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainer_promotions WHERE trainer_id=?',(tid,)).fetchone()[0]==0


def test_explicit_invitation_activation_hashes_password_and_token_single_use(access):
    tid=create(access)
    link=invite(access,tid)
    raw=urlsplit(link).path.rsplit('/',1)[1]
    assert access[2][0][0]=='teacher@example.test'
    assert '72 heures' in access[2][0][2]
    with access[1]() as conn:
        token=conn.execute('SELECT * FROM trainer_access_tokens').fetchone()
        assert token['token_hash']!=raw and raw not in str(tuple(token))
        assert 72*3600-5<=token['expires_at']-time.time()<=72*3600
        assert conn.execute('SELECT invited_at FROM trainers WHERE id=?',(tid,)).fetchone()[0]
    assert login(access[0],value='16091993').status_code==200
    open_link(access[0],link)
    assert password(access[0]).status_code==302
    with access[1]() as conn:
        account=conn.execute('SELECT password_hash FROM trainers WHERE id=?',(tid,)).fetchone()
        assert account[0].startswith('scrypt:') and check_password_hash(account[0],PASSWORD)
    assert b'name="new_password"' not in open_link(access[0],link).data


def test_expired_activation_and_invalid_token_fail_closed(access):
    tid=create(access)
    link=invite(access,tid)
    with access[1]() as conn:
        conn.execute('UPDATE trainer_access_tokens SET expires_at=0')
    assert b'name="new_password"' not in open_link(access[0],link).data
    assert b'name="new_password"' not in open_link(access[0],'https://school.example.test/formateur/mot-de-passe/invalid-token').data
    assert access[0].post('/formateur/mot-de-passe',data={}).status_code==400


def test_only_exact_assigned_pairs_and_confirmed_statuses_reach_template(access):
    active(access)
    for cid,bts,year,status in [('allowed','MCO',2026,'confirmee'),('reconfirmed','MOS',2027,'reconfirmee'),('cross-one','MCO',2027,'confirmee'),('cross-two','MOS',2026,'confirmee'),('pending','MCO',2026,'preinscription'),('validated','MCO',2026,'validee'),('reconfirming','MCO',2026,'reconf_en_cours'),('cancelled','MCO',2026,'annulee'),('other','CI',2026,'confirmee')]:
        seed(access[1],cid,bts,year,status)
    response=access[0].get('/formateur?bts=MCO&rentree=2026')
    assert response.status_code==200
    context=access[3][-1][1]
    assert {row['nom'] for row in context['students']}=={'ALLOWED','RECONFIRMED'}
    expected={'nom','prenom','bts','mode','email','tel','numero_dossier','rentree_annee','statut','promotion_id','promotion_name','promotion_niveau','promotion_date_debut','promotion_date_fin','promotion_needs_setup'}
    assert all(set(row)==expected for row in context['students'])
    for forbidden in [b'PRIVATE-',b'cross-one@example',b'cross-two@example',b'pending@example',b'validated@example',b'reconfirming@example',b'cancelled@example',b'other@example',b'/admin/candidat/']:
        assert forbidden not in response.data
    # The shared header may link to the public sign-in page, never a student's private dossier.
    from bs4 import BeautifulSoup
    student_links = BeautifulSoup(response.text, 'html.parser').select('a[href^="/espace/"]')
    assert all(link['href'] == '/espace/connexion' for link in student_links)
    assert context['selected_bts']=='MCO' and context['selected_year']==2026


def test_unassigned_dashboard_empty_and_other_accounts_assignments_cannot_leak(access):
    active(access,assignments=[])
    create(access,email='other@example.test',assignments=['MCO:2026'])
    seed(access[1],'not-mine','MCO',2026)
    response=access[0].get('/formateur?bts=MCO&rentree=2026')
    assert response.status_code==200 and access[3][-1][1]['students']==[]
    assert b'not-mine@example' not in response.data


def test_assignments_change_invalidates_existing_sessions_and_old_links(access):
    tid=active(access)
    other=access[0].application.test_client()
    assert login(other).status_code==302
    link=invite(access,tid)
    response=admin_post(access,tid,'update',nom='DUPONT',prenom='Camille',email='teacher@example.test',assignments=['CI:2027'])
    assert response.status_code==200
    assert other.get('/formateur').headers['Location']=='/formateur/connexion'
    assert b'name="new_password"' not in open_link(access[0],link).data
    assert login(other).status_code==302
    seed(access[1],'new-group','CI',2027)
    seed(access[1],'old-group','MCO',2026)
    assert b'new-group@example' in other.get('/formateur').data
    assert b'old-group@example' not in other.get('/formateur').data


def test_email_change_requires_new_activation_and_clears_old_invited_date(access):
    tid=active(access)
    assert admin_post(access,tid,'update',nom='DUPONT',prenom='Camille',email='new@example.test',assignments=['MCO:2026']).status_code==200
    assert login(access[0],email='teacher@example.test').status_code==200
    assert login(access[0],email='new@example.test').status_code==200
    with access[1]() as conn:
        row=conn.execute('SELECT password_hash,invited_at FROM trainers WHERE id=?',(tid,)).fetchone()
        assert row[0] is None and row[1] is None
    count=len(access[2])
    link=invite(access,tid)
    assert len(access[2])==count+1 and access[2][-1][0]=='new@example.test'
    open_link(access[0],link)
    password(access[0])
    assert login(access[0],email='new@example.test').status_code==302


def test_disable_reactivate_revokes_sessions_links_and_recovery_delivery(access):
    tid=active(access)
    other=access[0].application.test_client()
    assert login(other).status_code==302
    link=invite(access,tid)
    assert admin_post(access,tid,'status',active='0').status_code==200
    assert other.get('/formateur').headers['Location']=='/formateur/connexion'
    assert login(other).status_code==200
    assert b'name="new_password"' not in open_link(other,link).data
    count=len(access[2])
    recover(access,client=other)
    assert len(access[2])==count
    assert admin_post(access,tid,'send-access').status_code==400
    assert admin_post(access,tid,'status',active='1').status_code==200
    assert other.get('/formateur').headers['Location']=='/formateur/connexion'
    assert login(other).status_code==302


def test_recovery_generic_single_use_thirty_minutes_and_revokes_all_sessions(access):
    active(access)
    other=access[0].application.test_client()
    assert login(other).status_code==302
    count=len(access[2])
    unknown=recover(access,email='unknown@example.test')
    assert len(access[2])==count
    known=recover(access)
    assert len(access[2])==count+1
    # User-supplied email remains in the input context only; the account existence message is identical.
    phrase='Si cette adresse'.encode()
    assert phrase in unknown.data and phrase in known.data
    link=re.search(r'href="([^"]+/formateur/mot-de-passe/[^"]+)"',access[2][-1][2]).group(1)
    assert '30 minutes' in access[2][-1][2]
    with access[1]() as conn:
        record=conn.execute('SELECT * FROM trainer_access_tokens WHERE consumed=0').fetchone()
        assert 30*60-5<=record['expires_at']-time.time()<=30*60
    open_link(access[0],link)
    assert password(access[0],NEW_PASSWORD).status_code==302
    assert other.get('/formateur').headers['Location']=='/formateur/connexion'
    assert login(other).status_code==200
    assert login(other,value=NEW_PASSWORD).status_code==302
    assert b'name="new_password"' not in open_link(access[0],link).data


def test_sessions_are_separate_and_logout_preserves_admin_and_student(access):
    active(access)
    client=access[0]
    with client.session_transaction() as state:
        state['admin_ok']=True
        state['_student_auth']={'marker':'independent-student'}
        token=state['_trainer_csrf']
    assert client.get('/formateur/deconnexion').status_code==405
    assert client.post('/formateur/deconnexion').status_code==400
    assert client.post('/formateur/deconnexion',data={'csrf_token':token}).status_code==302
    with client.session_transaction() as state:
        assert state['admin_ok'] is True
        assert state['_student_auth']=={'marker':'independent-student'}
        assert '_trainer_auth' not in state
    assert client.get('/formateur').headers['Location']=='/formateur/connexion'


def test_session_expiry_and_trainer_session_does_not_grant_admin(access):
    active(access)
    client=access[0]
    with client.session_transaction() as state:
        state.pop('admin_ok')
    assert client.get('/admin/formateurs').status_code==403
    assert client.post('/admin/formateurs',json={}).status_code==403
    with client.session_transaction() as state:
        state['_trainer_auth']={**state['_trainer_auth'],'expires_at':0}
    assert client.get('/formateur').headers['Location']=='/formateur/connexion'


def test_rate_limits_login_and_recovery_and_invitation(access):
    tid=create(access)
    for _ in range(5):
        invite(access,tid)
    assert admin_post(access,tid,'send-access').status_code==429
    for _ in range(7):
        recover(access)
    assert len(access[2])==10
    for _ in range(11):
        assert login(access[0],value='wrong-password').status_code==200
    with access[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainer_access_requests WHERE kind=?',('login',)).fetchone()[0]==10


def test_activation_rejects_weak_password_and_new_invite_invalidates_old(access):
    tid=create(access)
    first=invite(access,tid)
    second=invite(access,tid)
    assert b'name="new_password"' not in open_link(access[0],first).data
    open_link(access[0],second)
    assert password(access[0],'short').status_code==200
    assert password(access[0],'123456789012').status_code==200
    assert password(access[0],PASSWORD).status_code==302


def test_default_secret_fails_closed_and_auth_views_have_no_analytics(access):
    response=access[0].get('/formateur/connexion')
    assert b'googletagmanager' not in response.data and b'cdn.brevo.com' not in response.data
    access[0].application.secret_key='change-me'
    assert access[0].get('/formateur/connexion').status_code==503
    assert access[0].get('/formateur/mot-de-passe-oublie').status_code==503


def test_browser_multipart_create_and_update_preserve_multiple_assignments(access):
    client,db,mails,_=access
    response=client.post('/admin/formateurs',data=dict(csrf_token=csrf(client),nom='DUPONT',prenom='Camille',email='browser@example.test',assignments=promotion_ids(access,['MCO:2026','MOS:2027'])),content_type='multipart/form-data',headers={'Accept':'application/json'})
    assert response.status_code==201,response.data
    with db() as conn:
        tid=conn.execute('SELECT id FROM trainers WHERE email=?',('browser@example.test',)).fetchone()[0]
        assert {tuple(row) for row in conn.execute('SELECT p.bts,p.rentree_annee FROM trainer_promotions a JOIN promotions p ON p.id=a.promotion_id WHERE a.trainer_id=?',(tid,))}=={('MCO',2026),('MOS',2027)}
    response=client.post('/admin/formateurs/'+tid+'/update',data=dict(csrf_token=csrf(client),nom='DUPONT',prenom='Camille',email='browser@example.test',assignments=promotion_ids(access,['CI:2027','PI:2028'])),content_type='multipart/form-data',headers={'Accept':'application/json'})
    assert response.status_code==200,response.data
    with db() as conn:
        assert {tuple(row) for row in conn.execute('SELECT p.bts,p.rentree_annee FROM trainer_promotions a JOIN promotions p ON p.id=a.promotion_id WHERE a.trainer_id=?',(tid,))}=={('CI',2027),('PI',2028)}
    assert not mails


def test_legacy_bts_spelling_is_normalized_for_roster_filters(access):
    active(access,assignments=['MCO:2026'])
    seed(access[1],'legacy-spelling',' Mco ',2026)
    assert access[0].get('/formateur').status_code==200
    assert access[3][-1][1]['students'][0]['bts']=='MCO'


def test_roster_rechecks_changed_student_status_on_every_visit(access):
    active(access,assignments=['MCO:2026'])
    seed(access[1],'previously-confirmed','MCO',2026,'confirmee')
    seed(access[1],'newly-confirmed','MCO',2026,'preinscription')
    assert access[0].get('/formateur').status_code==200
    assert {row['nom'] for row in access[3][-1][1]['students']}=={'PREVIOUSLY-CONFIRMED'}
    with access[1]() as conn:
        conn.execute('UPDATE candidats SET statut=? WHERE id=?',('annulee','previously-confirmed'))
        conn.execute('UPDATE candidats SET statut=? WHERE id=?',('confirmee','newly-confirmed'))
    assert access[0].get('/formateur').status_code==200
    assert {row['nom'] for row in access[3][-1][1]['students']}=={'NEWLY-CONFIRMED'}


def test_failed_mail_does_not_report_sent_and_consumes_undelivered_token(access):
    tid=create(access)
    access[0].application.config['TRAINER_MAIL_FAIL']=True
    response=admin_post(access,tid,'send-access')
    assert response.status_code==502 and response.json['ok'] is False
    with access[1]() as conn:
        assert conn.execute('SELECT invited_at FROM trainers WHERE id=?',(tid,)).fetchone()[0] is None
        assert conn.execute('SELECT consumed FROM trainer_access_tokens WHERE trainer_id=?',(tid,)).fetchone()[0]==1


def test_new_reset_link_works_when_browser_has_stale_trainer_session(access):
    tid=active(access)
    other=access[0].application.test_client()
    assert login(other).status_code==302
    # An admin edit invalidates the teacher's browser session before a new link is issued.
    assert admin_post(access,tid,'update',nom='DUPONT',prenom='Camille',email='teacher@example.test',assignments=['CI:2027']).status_code==200
    link=invite(access,tid)
    assert b'name="new_password"' in open_link(other,link).data
    response=password(other,NEW_PASSWORD)
    assert response.status_code==302
    assert login(other,value=NEW_PASSWORD).status_code==302


def test_admin_form_csrf_remains_current_when_trainer_session_is_invalidated(access):
    tid=active(access)
    assert admin_post(access,tid,'status',active='0').status_code==200
    response=access[0].get('/admin/formateurs')
    rendered=re.search(rb'data-csrf="([^"]+)"',response.data).group(1).decode()
    with access[0].session_transaction() as state:
        assert rendered==state['_trainer_csrf']
        assert '_trainer_auth' not in state
        assert state['admin_ok'] is True
