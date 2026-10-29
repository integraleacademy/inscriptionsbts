"""Trainer file edits, exports, scoped consultation and directory search."""
from datetime import date
from io import BytesIO
import time
import re

import pytest
from flask import session
from pypdf import PdfReader
from werkzeug.datastructures import MultiDict

from test_trainer_workload import workload_db, workload_client, lesson
from test_trainer_admin_planning_audit import admin_client
from test_planning_integration import connected
from test_campus_workspace import campus, client, application
from trainer_admin_planning import trainer_export_bounds, get_admin_trainer_planning
from trainer_availability import get_trainer_availability_state
from trainer_workload import get_trainer_workload, ensure_workload_schema
from planning import _load_courses
from planning_portal import get_portal_week


def test_plain_trainer_file_opens_planning_and_orders_tabs(admin_client):
    page = admin_client.get('/admin/formateurs/t1')
    assert page.status_code == 200
    tabs = re.findall(r'<a class="tw-tab[^>]*>.*?<span>(.*?)</span></a>',page.text,re.S)
    assert tabs == ['Planning','Indisponibilités','Compte &amp; accès','Comptabilité']
    assert 'tw-tab is-active' in page.text
    assert 'Espace du formateur' in page.text
    assert 'data-admin-trainer-planning' in page.text


def test_export_period_bounds():
    for period, start, end in [('week','2027-01-25','2027-01-31'),('month','2027-01-01','2027-01-31'),('school_year','2026-09-01','2027-07-31')]:
        assert trainer_export_bounds(MultiDict(dict(date='2027-01-28',period=period))) == (date.fromisoformat(start),date.fromisoformat(end))
    assert trainer_export_bounds(MultiDict(dict(date='2028-02-15',period='month')))[1] == date(2028,2,29)


@pytest.mark.parametrize('query', ['period=no','period=custom&start=2027-02-02&end=2027-02-01','period=custom&start=2026-01-01&end=2028-01-01','period=month&period=week','trainer_id=t2','period=school_year&date=1900-01-01'])
def test_pdf_rejects_invalid_or_unscoped_periods(admin_client,query):
    assert admin_client.get('/admin/formateurs/t1/planning.pdf?'+query).status_code == 400


def test_pdf_month_year_custom_scope_and_shared_groups(admin_client,workload_db):
    with workload_db() as conn:
        lesson(conn,'JAN_UNIQUE',groups=('p1','p2','p3'))
        lesson(conn,'FEB_UNIQUE',day='2027-02-01')
        lesson(conn,'OUTSIDE_UNIQUE',day='2027-08-02')
        lesson(conn,'COLLEAGUE_UNIQUE',trainer='t2')
    for query, included, excluded in [
        ('date=2027-01-04&period=month',['JAN_UNIQUE'],['FEB_UNIQUE','OUTSIDE_UNIQUE']),
        ('date=2027-01-04&period=school_year',['JAN_UNIQUE','FEB_UNIQUE'],['OUTSIDE_UNIQUE']),
        ('period=custom&start=2027-02-01&end=2027-02-01',['FEB_UNIQUE'],['JAN_UNIQUE','OUTSIDE_UNIQUE'])]:
        response = admin_client.get('/admin/formateurs/t1/planning.pdf?'+query)
        assert response.status_code == 200
        reader = PdfReader(BytesIO(response.data))
        text = ' '.join(page.extract_text() for page in reader.pages)
        assert all(title in text for title in included)
        assert all(title not in text for title in excluded+['COLLEAGUE_UNIQUE'])
        assert 'private, no-store' == response.headers['Cache-Control']


def test_course_edit_delete_updates_every_projection_and_rejects_stale_version(connected):
    c, db, _, _ = connected
    with db() as conn:
        ensure_workload_schema(conn)
        row = conn.execute('SELECT id FROM planning_courses').fetchone()
        conn.execute("INSERT INTO promotions VALUES('other','BTS MOS groupe B','MOS',1,2026,'2026-09-01','2027-08-31',1,0,'now','now')")
        conn.execute("INSERT INTO trainer_promotions VALUES('trainer','other')")
        conn.execute("INSERT INTO planning_subjects VALUES('second','other','Culture générale','trainer','#123456',50)")
        conn.execute("INSERT INTO planning_course_groups VALUES(?,'other','second')",(row['id'],))
    with c.session_transaction() as state: headers = {'X-CSRF-Token':state['_planning_csrf']}
    assert c.post('/admin/planning/api/calendar/rules',headers=headers,json=dict(promotion_id='other',start_date='2026-09-01',end_date='2027-08-31',weekdays=[0,1,2,3,4],kind='school',label='École')).status_code == 200
    path = '/admin/planning/api/courses/'+row['id']
    snapshot = c.get(path).json['course']
    assert len(snapshot['groups']) == 2
    changed = c.put(path,headers=headers,json=dict(version=snapshot['version'],date='2027-01-05',start='10:00',end='13:00'))
    assert changed.status_code == 200,changed.json
    assert c.put(path,headers=headers,json=dict(version=snapshot['version'],title='stale')).status_code == 409
    with db() as conn:
        assert all(_load_courses(conn,promotion_id=pid)[0]['date']=='2027-01-05' for pid in ('demo','other'))
        assert get_admin_trainer_planning(conn,'trainer','2027-01-04')['summary']['minutes'] == 180
        assert get_trainer_workload(conn,'trainer','2027-01')['total_minutes'] == 180
        assert get_portal_week(conn,'trainer','trainer','2027-01-04')['courses'][0]['end'] == '13:00'
        counts = {r['date']:r['course_count'] for r in get_trainer_availability_state(conn,'trainer',2027)['days']}
        assert counts['2027-01-04'] == 0 and counts['2027-01-05'] == 1
    assert c.delete(path,headers=headers,json=dict(version=changed.json['course']['version'])).status_code == 200
    with db() as conn:
        assert not _load_courses(conn)
        assert not conn.execute('SELECT 1 FROM planning_course_groups').fetchone()
        assert get_trainer_workload(conn,'trainer','2027-01')['total_minutes'] == 0
        assert not get_portal_week(conn,'trainer','trainer','2027-01-04')['courses']
    assert c.application.test_client().get(path).status_code == 403


def test_admin_preview_without_activation_stays_private_and_read_only(campus,monkeypatch):
    c,_,sent = campus
    monkeypatch.setattr(application.app,'secret_key','preview-fixture-secret')
    with c.session_transaction() as state: state['admin_ok'] = True
    c.get('/admin/formateurs/t1')
    with c.session_transaction() as state:
        token = state['_trainer_csrf']
        previous = dict(trainer_id='another',version=1,expires_at=time.time()+3600)
        state['_trainer_auth'] = previous
    endpoint = '/admin/formateurs/t1/espace'
    assert c.post(endpoint).status_code == 400
    assert application.app.test_client().post(endpoint,data={'csrf_token':token}).status_code == 403
    response = c.post(endpoint,data={'csrf_token':token},follow_redirects=True)
    assert response.status_code == 200 and 'Consultation administrateur' in response.text
    for path in ['/formateur/planning?date=2026-10-26','/formateur/indisponibilites','/formateur/cours/course','/formateur/pedagogie','/formateur/devoirs-notes']:
        response = c.get(path)
        assert response.status_code == 200,(path,response.text)
    assert c.post('/formateur/indisponibilites/api/preview',json={}).status_code == 403
    assert not sent
    with c.session_transaction() as state: assert state['_trainer_auth'] == previous
    response = c.post('/admin/formateurs/espace/fermer',data={'csrf_token':token})
    assert response.status_code == 303 and response.location == '/admin/formateurs/t1'
    c.post(endpoint,data={'csrf_token':token})
    with c.session_transaction() as state: state.pop('admin_ok')
    assert c.get('/formateur').status_code == 302
    with c.session_transaction() as state: assert '_trainer_preview' not in state


def test_search_people_companies_promotions_and_functions(campus):
    c,_,_ = campus
    for query,kind,path in [('prof','Formateur','/admin/formateurs/t1'),('exemple','Entreprise','/admin/entreprises/co'),('mos','Promotion','/admin/planning?promotion_id=p2'),('zoom','Fonction','/admin/planning')]:
        matches = c.get('/admin/recherche',query_string={'q':query}).json['results']
        assert any(r['kind']==kind and r['url']==path for r in matches),matches
    with application.db() as conn:
        conn.execute("UPDATE trainers SET nom='DUPRÉ',active=0 WHERE id='t1'")
    assert any(r['kind']=='Formateur' for r in c.get('/admin/recherche?q=dupre').json['results'])
