"""Read-only portal rendering and Paris-local homepage schedules."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

from flask import Flask
import pytest

import planning_portal
from candidate_access import _schema as student_schema
from trainer_access import _schema as trainer_schema
from planning import ensure_planning_schema


@pytest.fixture
def portal_db(tmp_path):
    path = tmp_path / 'portal.sqlite'
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    with closing(connect()) as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,rentree_annee INTEGER,statut TEXT,slug_public TEXT)')
        trainer_schema(conn)
        student_schema(conn)
        ensure_planning_schema(conn)
        for pid in ('p1', 'p2'):
            conn.execute("INSERT INTO promotions VALUES(?,?, 'MOS',1,2026,'2026-09-01','2027-08-31',1,0,'now','now')", (pid, 'Promotion ' + pid))
            conn.execute("INSERT INTO planning_calendar_rules VALUES(?,?, '2026-09-01','2027-08-31','[0,1,2,3,4]','school','À l’école')", ('rule'+pid,pid))
        for tid in ('t1','t2'):
            conn.execute("INSERT INTO trainers(id,nom,prenom,email,password_hash,active,version,created_at,updated_at) VALUES(?,?,?,?,'fixture-unused',1,1,'now','now')", (tid,'NOM '+tid,'Prénom',tid+'@example.test'))
            for pid in ('p1','p2'):
                conn.execute('INSERT INTO trainer_promotions VALUES(?,?)',(tid,pid))
        for sid,pid,tid in [('s1','p1','t1'),('s2','p2','t1'),('s3','p1','t2')]:
            conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,60)',(sid,pid,'Matière '+sid,tid,'#626b4e'))
        conn.execute("INSERT INTO planning_rooms VALUES('r1','Salle Olivier',1)")
        for cid,pid in [('student1','p1'),('student2','p2')]:
            conn.execute("INSERT INTO candidats VALUES(?,?,?,'MOS',2026,'confirmee',?)",(cid,'ÉTUDIANT','Test',cid+'-slug'))
            conn.execute('INSERT INTO student_promotions VALUES(?,?,?)',(cid,pid,'now'))
            conn.execute("INSERT INTO student_accounts VALUES(?,'fixture-unused',0,1,0,0)",(cid,))
            conn.execute('INSERT INTO student_account_members VALUES(?,?)',(cid,cid))
        def course(cid,pid,sid,tid,day,start=480,end=600,room='r1'):
            conn.execute("INSERT INTO planning_courses VALUES(?,?,?,?,?,?,?,?,?,1,'now','now')",(cid,pid,sid,tid,room,day,start,end,''))
            conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)',(cid,pid,sid))
        course('common','p1','s1','t1','2026-10-26')
        conn.execute("INSERT INTO planning_course_groups VALUES('common','p2','s2')")
        course('other-teacher','p1','s3','t2','2026-10-26',780,900)
        course('next','p1','s1','t1','2026-11-02',room=None)
        course('next-year','p1','s1','t1','2027-01-04')
        conn.commit()
    return connect


@pytest.fixture
def portal_app(portal_db):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root/'templates'), static_folder=str(root/'static'))
    app.secret_key = 'portal-test-secret-only'
    app.config['TESTING'] = True
    app.add_url_rule('/espace/connexion',endpoint='candidate_login',view_func=lambda:'login')
    app.add_url_rule('/espace/mot-de-passe',endpoint='student_change_password',view_func=lambda:'password')
    app.add_url_rule('/formateur/connexion',endpoint='trainer_login',view_func=lambda:'login')
    planning_portal.register_planning_portal(app,portal_db)
    return app


def login(app,role='student',person='student1'):
    client=app.test_client()
    with client.session_transaction() as state:
        if role=='student':
            state['_student_auth']=dict(account_id=person,candidate_id=person,version=1,expires_at=time.time()+3600)
        else:
            state['_trainer_auth']=dict(trainer_id=person,version=1,expires_at=time.time()+3600)
    return client


def test_today_uses_paris_midnight_and_finds_next_year_courses(portal_db):
    instant=datetime(2026,10,25,23,30,tzinfo=timezone.utc).astimezone(planning_portal.PARIS)
    with closing(portal_db()) as conn,patch.object(planning_portal,'_now_paris',return_value=instant):
        today=planning_portal.get_portal_today(conn,'student','student1')
    assert today['today']=='2026-10-26'
    assert {row['id'] for row in today['courses']}=={'common','other-teacher'}
    assert [row['id'] for row in today['next_courses']]==['next','next-year']
    assert 'janvier 2027' in today['next_courses'][1]['date_label']
    assert today['next_courses'][0]['incomplete']
    assert today['next_courses'][0]['warning_labels']==['Salle à confirmer.']


def test_student_secondary_promotion_gets_local_subject_only(portal_db):
    with closing(portal_db()) as conn:
        week=planning_portal.get_portal_week(conn,'student','student2','2026-10-26')
    assert [course['id'] for course in week['courses']]==['common']
    course=week['courses'][0]
    assert course['subject_name']=='Matière s2'
    assert course['promotion_names']==['Promotion p2']
    assert course['is_shared']
    assert week['summary']==dict(courses=1,hours=2,minutes=120)
    assert 'Promotion p1' not in str(week)


def test_trainer_schedule_only_contains_actual_teaching_assignments(portal_db):
    with closing(portal_db()) as conn:
        week=planning_portal.get_portal_week(conn,'trainer','t1','2026-10-26')
    assert [course['id'] for course in week['courses']]==['common']
    assert week['courses'][0]['promotion_names']==['Promotion p1','Promotion p2']
    assert 'email' not in week['courses'][0] and 'planned_hours' not in week['courses'][0]


def test_holiday_header_is_explicit_even_without_a_course(portal_db):
    with closing(portal_db()) as conn,patch.object(planning_portal,'_now_paris',return_value=datetime(2026,11,11,10,tzinfo=planning_portal.PARIS)):
        today=planning_portal.get_portal_today(conn,'student','student1')
    assert today['public_holiday'] and today['day_kind']=='public_holiday'
    assert 'Armistice' in today['day_label']
    assert today['courses']==[]


@pytest.mark.parametrize('role,person,path', [('student','student2','/espace/planning'),('trainer','t1','/formateur/planning')])
def test_schedule_real_template_and_pdf_use_scoped_context(portal_app,role,person,path):
    client=login(portal_app,role,person)
    page=client.get(path+'?date=2026-10-26')
    assert page.status_code==200,page.text
    assert 'Salle Olivier' in page.text
    assert 'Matière s3' not in page.text
    assert page.headers['Cache-Control']=='private, no-store'
    assert 'Cookie' in page.headers['Vary']
    pdf=client.get(path+'.pdf?date=2026-10-26')
    assert pdf.status_code==200,pdf.text[:400] if pdf.status_code!=200 else ''
    assert pdf.data.startswith(b'%PDF')
    assert pdf.headers['Content-Disposition'].startswith('inline;')
    assert pdf.headers['Cache-Control']=='private, no-store'


def test_readonly_timetable_never_accepts_course_mutations(portal_app):
    client=login(portal_app)
    assert client.post('/espace/planning',json={'promotion_id':'p2'}).status_code==405
    assert client.put('/espace/planning.pdf',json={}).status_code==405


def test_initial_password_redirects_before_schedule_or_pdf(portal_app,portal_db):
    client=login(portal_app)
    with closing(portal_db()) as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='student1'");conn.commit()
    for route in ('/espace/planning','/espace/planning.pdf'):
        result=client.get(route)
        assert result.status_code==302
        assert result.location=='/espace/mot-de-passe'


def test_invalid_promotion_date_does_not_break_homepage(portal_db):
    with closing(portal_db()) as conn:
        conn.execute("UPDATE promotions SET date_fin='2027-02-30' WHERE id='p1'")
        with patch.object(planning_portal,'_now_paris',return_value=datetime(2026,10,26,10,tzinfo=planning_portal.PARIS)):
            assert planning_portal.get_portal_today(conn,'student','student1')['courses']


@pytest.mark.parametrize('hour,minute,expected',[(7,59,'upcoming'),(8,0,'ongoing'),(9,59,'ongoing'),(10,0,'')])
def test_today_live_status_starts_inclusive_and_ends_exclusive(portal_db,hour,minute,expected):
    with closing(portal_db()) as conn,patch.object(planning_portal,'_now_paris',return_value=datetime(2026,10,26,hour,minute,tzinfo=planning_portal.PARIS)):
        today=planning_portal.get_portal_today(conn,'trainer','t1')
    lesson=next(item for item in today['courses'] if item['id']=='common')
    assert lesson['live_state']==expected
    assert lesson['live_label']=={'upcoming':'À venir','ongoing':'En cours','':''}[expected]


def test_course_finishing_at_midnight_is_live_until_next_paris_day(portal_db):
    with closing(portal_db()) as conn:
        conn.execute("UPDATE planning_courses SET start_min=1380,end_min=1440 WHERE id='common'")
        with patch.object(planning_portal,'_now_paris',return_value=datetime(2026,10,26,23,59,tzinfo=planning_portal.PARIS)):
            lesson=planning_portal.get_portal_today(conn,'trainer','t1')['courses'][0]
            assert lesson['end']=='24:00' and lesson['live_state']=='ongoing'
        with patch.object(planning_portal,'_now_paris',return_value=datetime(2026,10,27,0,0,tzinfo=planning_portal.PARIS)):
            assert planning_portal.get_portal_today(conn,'trainer','t1')['courses']==[]
