"""Explicit promotions, safe legacy backfill and trainer scope boundaries."""
import sqlite3
import time
from pathlib import Path

import pytest
from flask import Flask, session, template_rendered
from werkzeug.security import generate_password_hash

import promotions
import trainer_access


@pytest.fixture
def db(tmp_path):
    path=tmp_path/'promotions.sqlite'
    def connect():
        conn=sqlite3.connect(path)
        conn.row_factory=sqlite3.Row
        return conn
    with connect() as conn:
        conn.execute('''CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,mode TEXT,email TEXT,tel TEXT,numero_dossier TEXT,rentree_annee INTEGER,statut TEXT,fichiers_photo TEXT)''')
    return connect


def student(conn,cid='student',bts='MCO',year=2026,status='confirmee'):
    conn.execute('INSERT INTO candidats(id,nom,prenom,bts,mode,email,tel,numero_dossier,rentree_annee,statut) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,cid.upper(),'Camille',bts,'presentiel',cid+'@example.test','0600000000',cid+'-DOS',year,status))


def group(conn,pid='group-one',bts='MCO',year=2026,level=1,active=1):
    promotions.ensure_promotion_schema(conn)
    conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,'BTS '+bts+' année '+str(level),bts,level,year,f'{year+level-1}-09-01',f'{year+level}-06-30',active,'2026-01-01','2026-01-01'))
    return pid


@pytest.fixture
def legacy_db(db):
    with db() as conn:
        conn.executescript('''CREATE TABLE trainers(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,email TEXT,password_hash TEXT,active INTEGER,version INTEGER,created_at TEXT,updated_at TEXT,invited_at TEXT);
            CREATE TABLE trainer_assignments(trainer_id TEXT,bts TEXT,rentree_annee INTEGER,PRIMARY KEY(trainer_id,bts,rentree_annee));
            CREATE TABLE trainer_access_tokens(token_hash TEXT PRIMARY KEY,trainer_id TEXT,purpose TEXT,version INTEGER,expires_at REAL,consumed INTEGER);''')
        for tid in ('teacher-a','teacher-b'):
            conn.execute('INSERT INTO trainers VALUES(?,?,?,?,?,?,?,?,?,?)',(tid,'NOM','Prénom',tid+'@example.test','KEEP-PASSWORD-HASH',1,7,'old-created','old-updated','old-invited'))
            conn.execute('INSERT INTO trainer_assignments VALUES(?,?,?)',(tid,'MCO',2026))
            conn.execute('INSERT INTO trainer_access_tokens VALUES(?,?,?,?,?,?)',('oldtoken-'+tid,tid,'activation',7,time.time()+10000,0))
        conn.execute('INSERT INTO trainer_assignments VALUES(?,?,?)',('teacher-a','MOS',2027))
        student(conn,'old-mco','MCO',2026)
        student(conn,'old-mos','MOS',2027)
        student(conn,'ungranted-cohort','MCO',2027)
    return db


def test_legacy_migration_creates_shared_technical_groups_without_invented_dates(legacy_db):
    with legacy_db() as conn:
        promotions.ensure_promotion_schema(conn)
        groups=conn.execute('SELECT * FROM promotions').fetchall()
        assert len(groups)==2
        assert all(row['niveau'] is None and row['date_debut'] is None and row['date_fin'] is None and row['needs_setup']==1 for row in groups)
        mco=next(row for row in groups if row['bts']=='MCO')
        assert mco['nom']=='BTS MCO · rentrée 2026 · À compléter'
        assert conn.execute('SELECT COUNT(*) FROM trainer_promotions WHERE promotion_id=?',(mco['id'],)).fetchone()[0]==2
        assert {r[0] for r in conn.execute('SELECT candidate_id FROM student_promotions')}=={'old-mco','old-mos'}
        assert conn.execute('SELECT COUNT(*) FROM trainer_assignments').fetchone()[0]==3
        assert conn.execute('SELECT COUNT(*) FROM candidats').fetchone()[0]==3
        for row in conn.execute('SELECT * FROM trainers'):
            assert row['password_hash']=='KEEP-PASSWORD-HASH' and row['version']==8
            assert row['email']==row['id']+'@example.test' and row['invited_at']=='old-invited'
        assert all(row[0]==1 for row in conn.execute('SELECT consumed FROM trainer_access_tokens'))


def test_legacy_backfill_runs_once_and_never_regrants_removed_or_future_students(legacy_db):
    with legacy_db() as conn:
        promotions.ensure_promotion_schema(conn)
        current=promotions.get_candidate_promotion(conn,'old-mco')
        conn.execute('DELETE FROM student_promotions WHERE candidate_id=?',('old-mco',))
        conn.execute('DELETE FROM trainer_promotions WHERE trainer_id=? AND promotion_id=?',('teacher-b',current['id']))
        student(conn,'future-mco','MCO',2026)
        group(conn,'future-group','MCO',2026,2)
        promotions.ensure_promotion_schema(conn)
        assert promotions.get_candidate_promotion(conn,'old-mco') is None
        assert promotions.get_candidate_promotion(conn,'future-mco') is None
        assert conn.execute('SELECT COUNT(*) FROM trainer_promotions WHERE promotion_id=?',('future-group',)).fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM trainer_promotions WHERE trainer_id=?',('teacher-b',)).fetchone()[0]==0
        assert all(row[0]==8 for row in conn.execute('SELECT version FROM trainers'))
        assert conn.execute('SELECT COUNT(*) FROM promotions').fetchone()[0]==3


def test_migration_preserves_existing_explicit_placement(legacy_db):
    with legacy_db() as conn:
        promotions.ensure_promotion_schema(conn)
        group(conn,'explicit-placement','MCO',2026,2)
        promotions.assign_candidate_promotion(conn,'old-mco','explicit-placement')
        # Simulates a partially prepared schema before its migration marker is recorded.
        conn.execute('DELETE FROM promotion_migrations')
        promotions.ensure_promotion_schema(conn)
        assert promotions.get_candidate_promotion(conn,'old-mco')['id']=='explicit-placement'


def test_schema_migration_is_atomic_and_does_not_commit_callers_transaction(legacy_db):
    conn=legacy_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        promotions.ensure_promotion_schema(conn)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='promotions'").fetchone()[0]==0
        assert all(row[0]==7 for row in conn.execute('SELECT version FROM trainers'))
        assert all(row[0]==0 for row in conn.execute('SELECT consumed FROM trainer_access_tokens'))
    finally:
        conn.close()


def test_empty_install_does_not_invent_legacy_promotions(db):
    with db() as conn:
        student(conn)
        promotions.ensure_promotion_schema(conn)
        assert conn.execute('SELECT COUNT(*) FROM promotions').fetchone()[0]==0
        assert promotions.get_candidate_promotion(conn,'student') is None


def test_student_transfer_keeps_original_intake_and_audits_history(db):
    with db() as conn:
        student(conn)
        group(conn,'year-one','MCO',2026,1)
        group(conn,'year-two','MCO',2026,2)
        promotions.assign_candidate_promotion(conn,'student','year-one')
        result=promotions.assign_candidate_promotion(conn,'student','year-two')
        assert result['niveau']==2 and result['rentree_annee']==2026 and result['date_debut']=='2027-09-01'
        assert conn.execute('SELECT rentree_annee FROM candidats WHERE id=?',('student',)).fetchone()[0]==2026
        history=conn.execute('SELECT previous_promotion_id,promotion_id FROM student_promotion_history ORDER BY id').fetchall()
        assert [tuple(row) for row in history]==[(None,'year-one'),('year-one','year-two')]
        promotions.assign_candidate_promotion(conn,'student','')
        assert promotions.get_candidate_promotion(conn,'student') is None


def test_incompatible_promotion_and_new_archived_assignment_are_rejected_without_mutation(db):
    with db() as conn:
        student(conn)
        group(conn,'allowed')
        group(conn,'other-bts','MOS')
        group(conn,'other-intake','MCO',2027)
        group(conn,'archived',active=0)
        promotions.assign_candidate_promotion(conn,'student','allowed')
        for pid in ('other-bts','other-intake','archived','missing'):
            with pytest.raises(ValueError):promotions.assign_candidate_promotion(conn,'student',pid)
            assert promotions.get_candidate_promotion(conn,'student')['id']=='allowed'
        conn.execute('UPDATE promotions SET active=0 WHERE id=?',('allowed',))
        assert promotions.assign_candidate_promotion(conn,'student','allowed')['id']=='allowed'


@pytest.fixture
def web(db):
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
    app.secret_key='promotion-tests-secret';app.config['TESTING']=True
    app.jinja_env.filters['dmy']=lambda value:value
    trainer_access.register_trainer_access(app,db,lambda *_:False,lambda:bool(session.get('admin_ok')))
    promotions.register_promotions(app,db,lambda:bool(session.get('admin_ok')))
    contexts=[]
    def capture(sender,template,context,**kwargs):contexts.append(context)
    template_rendered.connect(capture,app,weak=False)
    client=app.test_client()
    with client.session_transaction() as state:state['admin_ok']=True
    return client,app,contexts


def csrf(client):
    client.get('/admin/promotions')
    with client.session_transaction() as state:return state['_promotion_csrf']


def form(**updates):
    data=dict(nom='BTS MCO · 2e année',bts='MCO',niveau=2,rentree_annee=2026,date_debut='2027-09-01',date_fin='2028-06-30')
    data.update(updates);return data


def test_create_complete_promotion_and_invalid_dates_levels_csrf(web,db):
    client,app,_=web
    unknown=app.test_client()
    assert unknown.post('/admin/promotions',json=form()).status_code==403
    assert client.post('/admin/promotions',json=form()).status_code==400
    for updates in [dict(niveau=3),dict(bts='OTHER'),dict(date_debut='2028-07-01'),dict(date_fin='not-date'),dict(date_debut=''),dict(niveau='')]:
        assert client.post('/admin/promotions',json=dict(csrf_token=csrf(client),**form(**updates))).status_code==400
    response=client.post('/admin/promotions',json=dict(csrf_token=csrf(client),**form()))
    assert response.status_code==201
    with db() as conn:
        row=conn.execute('SELECT * FROM promotions WHERE id=?',(response.json['promotion_id'],)).fetchone()
        assert row['niveau']==2 and row['rentree_annee']==2026 and row['date_debut']=='2027-09-01' and row['needs_setup']==0


def test_candidate_assignment_route_requires_admin_csrf_and_matching_bts_intake(web,db):
    client,app,_=web
    with db() as conn:
        student(conn);group(conn);group(conn,'wrong','MOS')
    endpoint='/admin/candidat/student/promotion'
    assert app.test_client().post(endpoint,json={'promotion_id':'group-one'}).status_code==403
    assert client.post(endpoint,json={'promotion_id':'group-one'}).status_code==400
    assert client.post(endpoint,json=dict(csrf_token=csrf(client),promotion_id='wrong')).status_code==400
    response=client.post(endpoint,json=dict(csrf_token=csrf(client),promotion_id='group-one'))
    assert response.status_code==200 and response.json['promotion']['id']=='group-one'
    assert client.post(endpoint,json=dict(csrf_token=csrf(client),promotion_id='')).json['promotion'] is None


def setup_teacher(web,db,groups):
    with db() as conn:
        trainer_access._schema(conn)
        conn.execute('INSERT INTO trainers(id,nom,prenom,email,password_hash,active,version,created_at,updated_at) VALUES(?,?,?,?,?,1,1,?,?)',('teacher','DUPONT','Camille','teacher@example.test',generate_password_hash('Teacher password long',method='scrypt'),'now','now'))
        promotions.replace_trainer_promotions(conn,'teacher',groups)
    client=web[1].test_client()
    with client.session_transaction() as state:state['_trainer_auth']=dict(trainer_id='teacher',version=1,expires_at=time.time()+10000)
    return client


def test_same_bts_intake_different_promotions_are_strictly_isolated(web,db):
    with db() as conn:
        group(conn,'first');group(conn,'second',level=2)
        student(conn,'first-student');student(conn,'second-student');student(conn,'unassigned')
        promotions.assign_candidate_promotion(conn,'first-student','first')
        promotions.assign_candidate_promotion(conn,'second-student','second')
    teacher=setup_teacher(web,db,['first'])
    assert teacher.get('/formateur?promotion=second').status_code==200
    assert [row['nom'] for row in web[2][-1]['students']]==['FIRST-STUDENT']
    with db() as conn:
        promotions.assign_candidate_promotion(conn,'first-student','second')
    assert teacher.get('/formateur').status_code==200
    assert web[2][-1]['students']==[]


def test_roster_defense_in_depth_rechecks_bts_intake_and_status(web,db):
    with db() as conn:
        group(conn);student(conn)
        promotions.assign_candidate_promotion(conn,'student','group-one')
    teacher=setup_teacher(web,db,['group-one'])
    assert teacher.get('/formateur').status_code==200 and len(web[2][-1]['students'])==1
    for column,value in [('bts','MOS'),('rentree_annee',2027),('statut','annulee')]:
        with db() as conn:conn.execute(f'UPDATE candidats SET {column}=? WHERE id=?',(value,'student'))
        assert teacher.get('/formateur').status_code==200 and web[2][-1]['students']==[]
        with db() as conn:conn.execute('UPDATE candidats SET bts=?,rentree_annee=?,statut=? WHERE id=?',('MCO',2026,'confirmee','student'))


def test_promotion_archive_revokes_sessions_preserves_relations_and_excludes_roster(web,db):
    with db() as conn:
        group(conn);student(conn);promotions.assign_candidate_promotion(conn,'student','group-one')
    teacher=setup_teacher(web,db,['group-one'])
    admin=web[0]
    assert admin.post('/admin/promotions/group-one/status',json=dict(csrf_token=csrf(admin),active=0)).status_code==200
    assert teacher.get('/formateur').headers['Location']=='/formateur/connexion'
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_promotions').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM trainer_promotions').fetchone()[0]==1
        version=conn.execute('SELECT version FROM trainers').fetchone()[0]
        # Existing archived grants remain editable, new archived grants are forbidden.
        promotions.replace_trainer_promotions(conn,'teacher',['group-one'])
        with pytest.raises(ValueError):promotions.replace_trainer_promotions(conn,'new-teacher',['group-one'])
    with teacher.session_transaction() as state:state['_trainer_auth']=dict(trainer_id='teacher',version=version,expires_at=time.time()+10000)
    assert teacher.get('/formateur').status_code==200 and web[2][-1]['students']==[]


def test_promotion_update_cannot_change_bts_or_cohort_against_members(web,db):
    with db() as conn:
        group(conn);student(conn);promotions.assign_candidate_promotion(conn,'student','group-one')
    client=web[0]
    for updates in [dict(bts='MOS'),dict(rentree_annee=2027)]:
        response=client.post('/admin/promotions/group-one/update',json=dict(csrf_token=csrf(client),**form(**updates)))
        assert response.status_code==409
    assert client.post('/admin/promotions/group-one/update',json=dict(csrf_token=csrf(client),**form())).status_code==200
    with db() as conn:assert promotions.get_candidate_promotion(conn,'student')['niveau']==2


def test_technical_group_can_be_completed_only_with_real_level_dates(web,db):
    with db() as conn:
        group(conn)
        conn.execute('UPDATE promotions SET niveau=NULL,date_debut=NULL,date_fin=NULL,needs_setup=1')
    client=web[0]
    assert client.post('/admin/promotions/group-one/update',json=dict(csrf_token=csrf(client),**form(date_debut='',niveau=''))).status_code==400
    assert client.post('/admin/promotions/group-one/update',json=dict(csrf_token=csrf(client),**form())).status_code==200
    with db() as conn:assert conn.execute('SELECT needs_setup FROM promotions WHERE id=?',('group-one',)).fetchone()[0]==0
