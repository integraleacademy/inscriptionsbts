"""Student authentication, initial DOB password and recovery without live mail."""
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from flask import Flask
from werkzeug.security import check_password_hash

import candidate_access

DOB_PASSWORD='02012000'
PASSWORD='Une phrase personnelle 2027'
NEW_PASSWORD='Une autre phrase personnelle 2028'


@pytest.fixture
def access(tmp_path, monkeypatch):
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
    app.secret_key='student-auth-tests-only'
    app.config['TESTING']=True
    database=tmp_path/'access.sqlite'
    def db():
        conn=sqlite3.connect(database)
        conn.row_factory=sqlite3.Row
        return conn
    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,email TEXT,date_naissance TEXT,slug_public TEXT,rentree_annee INTEGER,created_at TEXT)')
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?)',('person','DUPRÉ','Camille','camille@example.test','2000-01-02','private-existing-slug',2027,'2026-12-01'))
    deliveries=[]
    def mail(*args):
        deliveries.append(args)
        return True
    @app.get('/espace/<slug>')
    def espace_candidat(slug):
        return 'Private student page'
    candidate_access.register_candidate_access(app,db,mail)
    monkeypatch.setenv('BASE_URL','https://school.example.test')
    return app.test_client(),db,deliveries


def token(client,path='/espace/connexion'):
    response=client.get(path)
    assert response.status_code==200
    return re.search(rb'name="csrf_token" value="([^"]+)"',response.data).group(1).decode()


def login(access,password=DOB_PASSWORD,nom='Dupré',client=None):
    client=client or access[0]
    return client.post('/espace/connexion',data=dict(csrf_token=token(client),nom=nom,password=password))


def change(client,current=DOB_PASSWORD,password=PASSWORD,confirm=None):
    return client.post('/espace/mot-de-passe',data=dict(csrf_token=token(client,'/espace/mot-de-passe'),current_password=current,new_password=password,confirm_password=password if confirm is None else confirm))


def setup(access):
    client=access[0]
    assert login(access).headers['Location']=='/espace/mot-de-passe'
    assert change(client).headers['Location']=='/espace/mon-dossier'


def recovery(access,nom='Dupré',birth='2000-01-02'):
    client,_,deliveries=access
    response=client.post('/espace/mot-de-passe-oublie',data=dict(csrf_token=token(client,'/espace/mot-de-passe-oublie'),nom=nom,date_naissance=birth))
    assert response.status_code==200
    assert b'camille@example.test' not in response.data
    if deliveries:
        return re.search(r'href="([^"]+/espace/reinitialiser\?token=[^"]+)"',deliveries[-1][2]).group(1)
    return None


def open_reset(client,link):
    parsed=urlsplit(link)
    response=client.get(parsed.path+'?'+parsed.query)
    assert response.headers['Location']=='/espace/reinitialiser'
    return client.get('/espace/reinitialiser')


def reset_password(client,password=NEW_PASSWORD):
    return client.post('/espace/reinitialiser',data=dict(csrf_token=token(client,'/espace/reinitialiser'),new_password=password,confirm_password=password))


def test_login_has_only_surname_and_password_no_email_or_candidature(access):
    response=access[0].get('/espace/connexion')
    assert b'name="nom"' in response.data and b'name="password"' in response.data
    assert b'name="email"' not in response.data and b'name="date_naissance"' not in response.data
    assert b'candidature' not in response.data.lower()
    assert 'Espace étudiant'.encode() in response.data
    assert b'16091993' in response.data


def test_initial_dob_login_requires_password_setup_before_dossier(access):
    client,db,deliveries=access
    response=login(access)
    assert response.headers['Location']=='/espace/mot-de-passe'
    assert client.get('/espace/mon-dossier').headers['Location']=='/espace/mot-de-passe'
    with client.session_transaction() as state:
        assert 'private-existing-slug' not in str(dict(state))
    with db() as conn:
        account=conn.execute('SELECT * FROM student_accounts').fetchone()
        assert account['password_hash'].startswith('scrypt:')
        assert check_password_hash(account['password_hash'],DOB_PASSWORD)
    assert not deliveries
    assert change(client).headers['Location']=='/espace/mon-dossier'
    assert client.get('/espace/mon-dossier').headers['Location']=='/espace/private-existing-slug'


def test_no_initial_dob_fallback_once_changed(access):
    setup(access)
    assert login(access,DOB_PASSWORD).status_code==200
    assert login(access,PASSWORD).headers['Location']=='/espace/mon-dossier'


def test_invalid_names_passwords_and_unicode_names_are_handled_generically(access):
    client=access[0]
    wrong=login(access,'wrong-password').data
    missing=login(access,'wrong-password','UNKNOWN').data
    marker='Nom ou mot de passe incorrect'.encode()
    assert marker in wrong and marker in missing
    assert login(access,DOB_PASSWORD,' DUPRE ').status_code==302
    assert client.post('/espace/connexion',data=dict(csrf_token=token(client),nom='DUPRÉ',password='x'*129)).status_code==200


def test_current_password_required_and_weak_passwords_rejected(access):
    setup(access)
    assert change(access[0],current='incorrect',password=NEW_PASSWORD).status_code==200
    assert change(access[0],current=PASSWORD,password='short').status_code==200
    assert change(access[0],current=PASSWORD,password='111111111111').status_code==200
    assert change(access[0],current=PASSWORD,password=NEW_PASSWORD,confirm='Mismatch').status_code==200
    assert login(access,PASSWORD).status_code==302


def test_slug_bearer_alone_cannot_change_password(access):
    client=access[0]
    assert client.get('/espace/private-existing-slug').status_code==200
    assert client.get('/espace/mot-de-passe').headers['Location']=='/espace/connexion'
    assert client.post('/espace/mot-de-passe',data={'new_password':PASSWORD}).headers['Location']=='/espace/connexion'


def test_changed_password_revokes_other_sessions_but_preserves_admin(access):
    client,db,_=access
    setup(access)
    other=client.application.test_client()
    assert login(access,PASSWORD,client=other).status_code==302
    with client.session_transaction() as state:
        state['admin_ok']=True
    assert change(client,current=PASSWORD,password=NEW_PASSWORD).status_code==302
    assert other.get('/espace/mon-dossier').headers['Location']=='/espace/connexion'
    with client.session_transaction() as state:
        assert state['admin_ok'] is True
        assert state['_student_auth']['version']==3


def test_student_logout_is_post_csrf_and_preserves_admin(access):
    setup(access)
    client=access[0]
    with client.session_transaction() as state:
        state['admin_ok']=True
        csrf=state['_candidate_access_csrf']
    assert client.get('/espace/deconnexion').status_code==405
    assert client.post('/espace/deconnexion',data={}).status_code==400
    assert client.post('/espace/deconnexion',data={'csrf_token':csrf}).headers['Location']=='/espace/connexion'
    with client.session_transaction() as state:
        assert state['admin_ok'] is True
        assert '_student_auth' not in state


def test_session_expiry_is_enforced(access):
    setup(access)
    with access[0].session_transaction() as state:
        state['_student_auth']={**state['_student_auth'],'expires_at':0}
    assert access[0].get('/espace/mon-dossier').headers['Location']=='/espace/connexion'


def test_homonyms_same_surname_and_dob_never_pick_arbitrary_person(access):
    with access[1]() as conn:
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?)',('other','DUPRÉ','Alex','alex@example.test','2000-01-02','other-private-slug',2027,'2026-12-02'))
    assert login(access).status_code==200
    assert recovery(access) is None
    assert not access[2]


def test_twins_same_parent_email_are_not_merged(access):
    with access[1]() as conn:
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?)',('twin','DUPRÉ','Alex','camille@example.test','2000-01-02','twin-private-slug',2027,'2026-12-02'))
    assert login(access).status_code==200
    with access[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_accounts').fetchone()[0]==2


def test_cross_cohort_same_student_shares_password_and_latest_dossier(access):
    with access[1]() as conn:
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?)',('old','DUPRÉ','Camille','camille@example.test','2000-01-02','old-private-slug',2026,'2025-12-01'))
    setup(access)
    with access[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_accounts').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM student_account_members').fetchone()[0]==2
    assert access[0].get('/espace/mon-dossier').headers['Location']=='/espace/private-existing-slug'
    assert login(access,DOB_PASSWORD).status_code==200


def test_recovery_generic_and_sends_to_registered_address_only(access):
    assert recovery(access,nom='UNKNOWN') is None
    assert recovery(access,birth='2000-02-02') is None
    link=recovery(access)
    assert link.startswith('https://school.example.test/espace/reinitialiser?token=')
    assert access[2][0][0]=='camille@example.test'
    assert 'ESPACE ÉTUDIANT' in access[2][0][2]


def test_reset_is_one_use_and_invalidates_previous_password_and_sessions(access):
    client=access[0]
    setup(access)
    other=client.application.test_client()
    assert login(access,PASSWORD,client=other).status_code==302
    link=recovery(access)
    assert b'name="new_password"' in open_reset(client,link).data
    response=reset_password(client)
    assert response.headers['Location']=='/espace/connexion?reset=ok'
    assert other.get('/espace/mon-dossier').headers['Location']=='/espace/connexion'
    assert login(access,PASSWORD).status_code==200
    assert login(access,DOB_PASSWORD).status_code==200
    assert login(access,NEW_PASSWORD).status_code==302
    assert 'déjà été utilisé'.encode() in open_reset(client,link).data


def test_expired_reset_and_password_change_revoked_reset(access):
    setup(access)
    link=recovery(access)
    with access[1]() as conn:
        conn.execute('UPDATE student_password_resets SET expires_at=0')
    assert b'name="new_password"' not in open_reset(access[0],link).data
    link=recovery(access)
    change(access[0],current=PASSWORD,password=NEW_PASSWORD)
    assert b'name="new_password"' not in open_reset(access[0],link).data


def test_new_reset_request_invalidates_previous_reset_link(access):
    first=recovery(access)
    second=recovery(access)
    assert b'name="new_password"' not in open_reset(access[0],first).data
    assert b'name="new_password"' in open_reset(access[0],second).data


def test_no_cleartext_password_or_recovery_token_persisted(access):
    setup(access)
    link=recovery(access)
    raw=urlsplit(link).query.split('=',1)[1]
    with access[1]() as conn:
        account=conn.execute('SELECT * FROM student_accounts').fetchone()
        record=conn.execute('SELECT * FROM student_password_resets').fetchone()
        assert PASSWORD not in str(tuple(account))
        assert raw not in str(tuple(record))
    open_reset(access[0],link)
    with access[0].session_transaction() as state:
        assert raw not in str(dict(state)) and PASSWORD not in str(dict(state))


def test_rate_limits_persist_for_login_and_recovery(access):
    client,db,deliveries=access
    for _ in range(candidate_access.LOGIN_LIMIT):
        assert login(access,'wrong-password').status_code==200
    assert login(access,DOB_PASSWORD).status_code==200
    for _ in range(7):
        recovery(access)
    assert len(deliveries)==5
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_auth_requests WHERE kind=?',('login',)).fetchone()[0]==candidate_access.LOGIN_LIMIT


def test_csrf_required_including_non_ascii_and_default_secret_fails_closed(access):
    client=access[0]
    token(client)
    assert client.post('/espace/connexion',data={'csrf_token':'é'}).status_code==400
    assert client.post('/espace/mot-de-passe-oublie',data={}).status_code==400
    assert client.post('/espace/reinitialiser',data={}).status_code==400
    client.application.secret_key='change-me'
    assert client.get('/espace/connexion').status_code==503


def test_deprecated_verification_bookmark_goes_to_new_login(access):
    assert access[0].get('/espace/verification').headers['Location']=='/espace/connexion'


def test_public_ip_limit_ignores_caller_forwarded_headers(access,monkeypatch):
    client,db,_=access
    monkeypatch.setattr(candidate_access,'check_password_hash',lambda *_:False)
    for i in range(32):
        response=client.post('/espace/connexion',data=dict(csrf_token=token(client),nom=f'UNKNOWN{i}',password='wrong'),headers={'CF-Connecting-IP':f'203.0.113.{i}'},environ_overrides={'REMOTE_ADDR':'8.8.8.8'})
        assert response.status_code==200
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_auth_requests').fetchone()[0]==30


def test_shared_private_proxy_allows_distinct_students_beyond_public_limit(access,monkeypatch):
    client,db,_=access
    monkeypatch.setattr(candidate_access,'check_password_hash',lambda *_:False)
    for i in range(32):
        response=client.post('/espace/connexion',data=dict(csrf_token=token(client),nom=f'UNKNOWN{i}',password='wrong'),environ_overrides={'REMOTE_ADDR':'10.0.0.1'})
        assert response.status_code==200
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_auth_requests').fetchone()[0]==32
