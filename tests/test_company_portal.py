"""Employer lifecycle, tenant isolation, exports and attendance corrections."""
from datetime import date
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

from flask import Flask, session
import pytest
from werkzeug.security import generate_password_hash
import company_portal as portal
from trainer_access import _schema as trainer_schema

PASSWORD = 'Une phrase entreprise 2026'


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root/'templates'), static_folder=str(root/'static'))
    app.secret_key = 'company-test-key-unique'
    app.config['TESTING'] = True
    path = tmp_path/'companies.sqlite'
    def db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    with db() as conn:
        conn.execute('''CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,rentree_annee INTEGER,statut TEXT,
            email TEXT,num_secu TEXT,slug_public TEXT)''')
        trainer_schema(conn)
        portal.ensure_company_schema(conn)
        for pid in ('p1','p2'):
            conn.execute("INSERT INTO promotions VALUES(?,?,'MOS',1,2026,'2026-09-01','2027-08-31',1,0,'now','now')", (pid,'Promotion '+pid))
            conn.execute("INSERT INTO planning_calendar_rules VALUES(?,?,'2026-09-01','2027-08-31','[0,1]','school','À l’école')", (pid+'school',pid))
            conn.execute("INSERT INTO planning_calendar_rules VALUES(?,?,'2026-09-01','2027-08-31','[2,3,4]','company','En entreprise')", (pid+'company',pid))
        conn.execute("INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES('t1','PROF','Alex','teacher@example.test','now','now')")
        for i,status in ((1,'confirmee'),(2,'rentree'),(3,'annulee'),(4,'preinscription')):
            cid = 's'+str(i)
            conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?,?)', (cid,'NOM'+str(i),'Prénom'+str(i),'MOS',2026,status,'secret-email-'+cid,'secret-nir-'+cid,'secret-bearer-'+cid))
            conn.execute('INSERT INTO student_promotions VALUES(?,?,?)', (cid,'p1' if i==1 else 'p2','now'))
        for n in (1,2):
            cid = 'e'+str(n)
            conn.execute('INSERT INTO companies(id,name,contact,email,password_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                         (cid,'Entreprise '+str(n),'Contact '+str(n),'contact'+str(n)+'@example.test',generate_password_hash(PASSWORD),'now','now'))
            conn.execute('INSERT INTO company_students VALUES(?,?,?,?,?,?)', ('s'+str(n),cid,'2026-10-01','2027-06-30','Tuteur '+str(n),'link-v1'))
            conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)', ('subject'+str(n),'p'+str(n),'Matière '+str(n),'t1','#1255aa',20))
            conn.execute('INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,title,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', ('course'+str(n),'p'+str(n),'subject'+str(n),'t1',None,'2026-10-19',510,750,'Cours '+str(n),1,'now','now'))
            conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)', ('course'+str(n),'p'+str(n),'subject'+str(n)))
            conn.execute('INSERT INTO student_attendance(id,candidate_id,date,start_min,end_min,kind,justification,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         ('a'+str(n),'s'+str(n),'2026-10-20',510,600,'absence','pending','now','now'))
        conn.execute("ALTER TABLE candidats ADD COLUMN mode TEXT NOT NULL DEFAULT 'presentiel'")
    mails = []
    def send(*args):
        mails.append(args)
        return not app.config.get('MAIL_FAIL',False)
    from daily_login import register_daily_login
    register_daily_login(app)
    portal.register_company_portal(app, db, send, lambda: bool(session.get('admin_ok')))
    monkeypatch.setattr(portal, 'today', lambda:date(2026,10,25))
    monkeypatch.setenv('BASE_URL','https://school.example.test')
    return app, db, mails


def admin(env):
    client = env[0].test_client()
    with client.session_transaction() as state:
        state['admin_ok'] = True
        state['_company_csrf'] = 'admin-csrf'
    return client


def logged(env, company='e1', **extra):
    client = env[0].test_client()
    with client.session_transaction() as state:
        state['_company_auth'] = dict(company_id=company,version=1,expires_at=time.time()+3600,**extra)
        state['_company_csrf'] = 'employer-csrf'
    return client


def post(client, path, **data):
    with client.session_transaction() as state:
        token = state.get('_company_csrf')
    return client.post(path,data=dict(csrf_token=token,**data))


def test_real_templates_render_for_all_roles_and_no_tracking(env):
    for path in ['/entreprise/connexion','/entreprise/mot-de-passe-oublie','/entreprise/mot-de-passe']:
        response = env[0].test_client().get(path)
        assert response.status_code==200
        assert 'googletagmanager' not in response.text and 'cdn.brevo' not in response.text
    for path in ['/admin/entreprises','/admin/entreprises/e1','/admin/assiduite','/admin/assiduite?month=2026-10&edit=a1']:
        response=admin(env).get(path)
        assert response.status_code==200
        assert 'googletagmanager' not in response.text
    for tab in ['students','planning','attendance']:
        response=logged(env).get('/entreprise',query_string={'tab':tab,'date':'2026-10-19'})
        assert response.status_code==200
        assert 'NOM2' not in response.text
        for secret in ['secret-email','secret-nir','secret-bearer','password_hash','company_tokens']:
            assert secret not in response.text
        assert response.headers['Cache-Control']=='private, no-store'
        assert response.headers['Referrer-Policy']=='no-referrer'
        assert 'Cookie' in response.headers['Vary']
    assert not env[2]


@pytest.mark.parametrize('path',['/entreprise','/entreprise/planning.pdf','/entreprise/absences.csv'])
def test_every_portal_route_requires_company_session(env,path):
    client=env[0].test_client()
    with client.session_transaction() as state:
        state['admin_ok']=True
        state['_trainer_auth']={'trainer_id':'t1','expires_at':time.time()+3600,'version':1}
    response=client.get(path+'?student=s1')
    assert response.status_code==302 and response.headers['Location']=='/entreprise/connexion'
    assert 'no-store' in response.headers['Cache-Control']


@pytest.mark.parametrize('path',['/admin/entreprises','/admin/entreprises/e1','/admin/assiduite'])
def test_company_has_no_admin_access(env,path):
    assert logged(env).get(path).status_code==403
    assert logged(env).post(path).status_code==403


@pytest.mark.parametrize('path',['/entreprise?tab=planning&student=s2','/entreprise?tab=attendance&student=s2','/entreprise/planning.pdf?student=s2','/entreprise/absences.csv?student=s2'])
def test_foreign_student_is_denied_in_pages_and_exports(env,path):
    assert logged(env).get(path).status_code==404


def test_account_version_expiry_and_disable_revoke_access(env):
    for mutation in ["UPDATE companies SET active=0 WHERE id='e1'", "UPDATE companies SET version=2 WHERE id='e1'", "UPDATE companies SET password_hash=NULL WHERE id='e1'"]:
        with env[1]() as conn:
            conn.execute("UPDATE companies SET active=1,version=1,password_hash='fixture' WHERE id='e1'")
            conn.execute(mutation)
        assert logged(env).get('/entreprise').status_code==302
    client=logged(env)
    with client.session_transaction() as state:
        state['_company_auth']['expires_at']=time.time()-1
        state.modified=True
    assert client.get('/entreprise').status_code==302


def test_removed_expired_and_cancelled_grants_immediately_hide_student(env):
    client=logged(env)
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET end_date='2026-10-24' WHERE candidate_id='s1'")
    assert 'NOM1' not in client.get('/entreprise').text
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET end_date=NULL WHERE candidate_id='s1'")
        conn.execute("UPDATE candidats SET statut='annulee' WHERE id='s1'")
    assert client.get('/entreprise/absences.csv?student=s1').status_code==404
    with env[1]() as conn:
        conn.execute("UPDATE candidats SET statut='confirmee' WHERE id='s1'")
        conn.execute("DELETE FROM company_students WHERE candidate_id='s1'")
    assert client.get('/entreprise/planning.pdf?student=s1').status_code==404


def test_planning_reuses_live_promotions_and_clips_contract_dates(env):
    client=logged(env)
    response=client.get('/entreprise?tab=planning&student=s1&date=2026-10-19')
    assert 'Matière 1' in response.text and 'Matière 2' not in response.text
    assert 'En entreprise' in response.text
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET start_date='2026-10-20' WHERE candidate_id='s1'")
    response=client.get('/entreprise?tab=planning&student=s1&date=2026-10-19')
    assert 'Matière 1' not in response.text and 'Hors période' in response.text
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET start_date='2026-10-01' WHERE candidate_id='s1'")
        conn.execute("UPDATE student_promotions SET promotion_id='p2' WHERE candidate_id='s1'")
    response=client.get('/entreprise?tab=planning&student=s1&date=2026-10-19')
    assert 'Matière 1' not in response.text and 'Matière 2' in response.text


def test_pdf_and_csv_are_scoped_and_csv_neutralizes_formulas(env):
    client=logged(env)
    response=client.get('/entreprise/planning.pdf?student=s1&date=2026-10-19')
    assert response.status_code==200 and response.data.startswith(b'%PDF')
    assert 'attachment' in response.headers['Content-Disposition']
    with env[1]() as conn:
        conn.execute("UPDATE candidats SET nom='=FORMULA()' WHERE id='s1'")
    response=client.get('/entreprise/absences.csv?month=2026-10')
    assert response.status_code==200 and response.data.startswith(b'\xef\xbb\xbf')
    assert "'=FORMULA()" in response.data.decode('utf-8-sig')
    assert 'NOM2' not in response.text
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET start_date='2026-10-21' WHERE candidate_id='s1'")
    assert 'FORMULA' not in client.get('/entreprise/absences.csv?month=2026-10').text


@pytest.mark.parametrize('query',['date=bad','date=9999-01-01','month=2026-99','date=2026-10-19&date=2026-10-20','student=s1&student=s2','promotion_id=p2','tab=admin'])
def test_invalid_and_ambiguous_filters_return_400(env,query):
    assert logged(env).get('/entreprise?'+query).status_code==400


def test_create_company_validate_unique_email_and_no_automatic_invites(env):
    client=admin(env)
    fields=dict(name='Entreprise test',contact='Camille DUPONT',email=' CONTACT@EXAMPLE.TEST ',phone='',siret='')
    assert client.post('/admin/entreprises',data=fields).status_code==400
    response=post(client,'/admin/entreprises',**fields)
    assert response.status_code==303
    assert not env[2]
    with env[1]() as conn:
        company=conn.execute("SELECT * FROM companies WHERE email='contact@example.test'").fetchone()
        assert company and not company['password_hash']
    assert post(client,'/admin/entreprises',**fields).status_code==400


def test_invitation_activation_login_reset_and_token_replay(env):
    client=admin(env)
    with env[1]() as conn:
        conn.execute("UPDATE companies SET password_hash=NULL WHERE id='e1'")
    assert post(client,'/admin/entreprises/e1/invitation').status_code==303
    assert len(env[2])==1 and env[2][0][0]=='contact1@example.test'
    link=re.search(r'https://school.example.test/entreprise/mot-de-passe/[^"\s<]+',env[2][0][2]).group()
    visitor=env[0].test_client()
    visitor.get(urlsplit(link).path)
    visitor.get('/entreprise/mot-de-passe')
    assert post(visitor,'/entreprise/mot-de-passe',new_password='short',confirm_password='short').status_code==200
    response=post(visitor,'/entreprise/mot-de-passe',new_password=PASSWORD,confirm_password=PASSWORD)
    assert response.status_code==303
    visitor.get('/entreprise/connexion')
    response=post(visitor,'/entreprise/connexion',email='CONTACT1@example.test',password=PASSWORD)
    assert response.status_code==303 and response.headers['Location']=='/entreprise'
    assert visitor.get('/entreprise').status_code==200
    replay=env[0].test_client()
    replay.get(urlsplit(link).path)
    assert 'expiré' in replay.get('/entreprise/mot-de-passe').text
    replay.get('/entreprise/mot-de-passe-oublie')
    assert post(replay,'/entreprise/mot-de-passe-oublie',email='contact1@example.test').status_code==200
    assert len(env[2])==2
    reset_link=re.search(r'https://school.example.test/entreprise/mot-de-passe/[^"\s<]+',env[2][-1][2]).group()
    replay.get(urlsplit(reset_link).path)
    assert post(replay,'/entreprise/mot-de-passe',new_password=PASSWORD+' new',confirm_password=PASSWORD+' new').status_code==303
    assert visitor.get('/entreprise').status_code==302


def test_email_change_invalidates_password_sessions_and_invites(env):
    admin_client=admin(env)
    company_client=logged(env)
    assert post(admin_client,'/admin/entreprises/e1',version='1',name='Enterprise',contact='Contact',email='new@example.test',phone='',siret='').status_code==303
    assert company_client.get('/entreprise').status_code==302
    with env[1]() as conn:
        row=conn.execute("SELECT password_hash,version FROM companies WHERE id='e1'").fetchone()
        assert row['password_hash'] is None and row['version']==2
    assert post(admin_client,'/admin/entreprises/e1/statut',version='1').status_code==409


def test_failed_email_revokes_token_and_forgot_does_not_enumerate(env):
    client=admin(env)
    env[0].config['MAIL_FAIL']=True
    post(client,'/admin/entreprises/e1/invitation')
    with env[1]() as conn:
        assert conn.execute('SELECT consumed FROM company_tokens').fetchone()[0]==1
    visitor=env[0].test_client()
    visitor.get('/entreprise/mot-de-passe-oublie')
    a=post(visitor,'/entreprise/mot-de-passe-oublie',email='contact1@example.test')
    b=post(visitor,'/entreprise/mot-de-passe-oublie',email='missing@example.test')
    assert a.text==b.text and a.status_code==200


def test_login_rate_limit_and_post_only_logout(env):
    client=env[0].test_client()
    client.get('/entreprise/connexion')
    for _ in range(10):
        assert post(client,'/entreprise/connexion',email='contact1@example.test',password='wrong').status_code==200
    assert post(client,'/entreprise/connexion',email='contact1@example.test',password=PASSWORD).status_code==200
    company=logged(env)
    assert company.get('/entreprise/deconnexion').status_code==405
    assert company.post('/entreprise/deconnexion').status_code==400
    assert post(company,'/entreprise/deconnexion').status_code==303
    assert company.get('/entreprise').status_code==302


def test_link_assignment_conflicts_dates_removal_and_revocation(env):
    client=admin(env)
    fields=dict(candidate_id='s2',start_date='2026-10-01',end_date='',tutor='Tuteur')
    assert post(client,'/admin/entreprises/e1/alternants',**fields).status_code==409
    fields['candidate_id']='s3'
    assert post(client,'/admin/entreprises/e1/alternants',**fields).status_code==400
    with env[1]() as conn:
        conn.execute("UPDATE candidats SET statut='confirmee' WHERE id='s3'")
    fields['end_date']='2026-09-01'
    assert post(client,'/admin/entreprises/e1/alternants',**fields).status_code==400
    fields['end_date']=''
    assert post(client,'/admin/entreprises/e1/alternants',**fields).status_code==303
    assert 'NOM3' in logged(env).get('/entreprise').text
    with env[1]() as conn:
        stamp=conn.execute("SELECT updated_at FROM company_students WHERE candidate_id='s3'").fetchone()[0]
    assert post(client,'/admin/entreprises/e1/alternants/s3/retirer',expected_updated_at='wrong').status_code==409
    assert post(client,'/admin/entreprises/e1/alternants/s3/retirer',expected_updated_at=stamp).status_code==303
    assert 'NOM3' not in logged(env).get('/entreprise').text


def test_attendance_write_correct_delete_and_overlap_protection(env):
    client=admin(env)
    values=dict(candidate_id='s1',date='2026-10-21',start='08:30',end='08:45',kind='late',justification='pending')
    assert client.post('/admin/assiduite',data=values).status_code==400
    assert post(client,'/admin/assiduite',**values).status_code==303
    with env[1]() as conn:
        record=conn.execute("SELECT * FROM student_attendance WHERE date='2026-10-21'").fetchone()
        record_id=record['id']
    page=logged(env).get('/entreprise?tab=attendance&month=2026-10')
    assert '15 min' in page.text and 'Retard' in page.text
    assert post(client,'/admin/assiduite',**values).status_code==400
    values.update(record_id=record_id,version='1',justification='justified',end='09:00')
    assert post(client,'/admin/assiduite',**values).status_code==303
    assert post(client,'/admin/assiduite',**values).status_code==409
    page=logged(env).get('/entreprise?tab=attendance&month=2026-10')
    assert '30 min' in page.text and 'Justifié' in page.text
    assert post(client,f'/admin/assiduite/{record_id}/supprimer',version='2').status_code==303
    assert 'Retard</span>' not in logged(env).get('/entreprise?tab=attendance&month=2026-10').text
    with env[1]() as conn:
        assert conn.execute('SELECT deleted FROM student_attendance WHERE id=?',(record_id,)).fetchone()[0]==1
        assert conn.execute("SELECT COUNT(*) FROM company_audit WHERE target_id=?",(record_id,)).fetchone()[0]==3


@pytest.mark.parametrize('change',[{'date':'2026-10-26'},{'date':'2026-02-30'},{'start':'25:00'},{'end':'08:00'},{'kind':'present'},{'justification':'medical detail'},{'candidate_id':'missing'}])
def test_attendance_invalid_events_do_not_persist(env,change):
    values=dict(candidate_id='s1',date='2026-10-21',start='08:30',end='09:00',kind='absence',justification='pending')
    values.update(change)
    assert post(admin(env),'/admin/assiduite',**values).status_code==400
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_attendance').fetchone()[0]==2


def test_default_secret_disables_employer_auth(env):
    env[0].secret_key='change-me'
    assert env[0].test_client().get('/entreprise/connexion').status_code==503
