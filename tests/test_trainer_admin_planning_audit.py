"""Independent scoped admin tabs, private PDF and atomic absence mutations."""
from io import BytesIO
from datetime import datetime
import json
import re
from flask import session
import pytest
from pypdf import PdfReader

import trainer_admin_planning as panels
import trainer_access
from test_trainer_workload import workload_db, workload_client, lesson


@pytest.fixture
def admin_client(workload_client,workload_db):
    app=workload_client.application
    panels.register_admin_trainer_planning(app,workload_db,lambda:bool(session.get('admin_ok')))
    return workload_client


def absence_data(db,trainer='t1'):
    with db() as conn:return panels.get_admin_trainer_availability(conn,trainer,2027)


def save_days(client,db,dates,trainer='t1',revision=None):
    return client.post('/admin/formateurs/'+trainer+'/indisponibilites/jours',
        json=dict(dates=dates,reason='Audit fixture',expected_revision=revision or absence_data(db,trainer)['state']['revision']),
        headers={'X-CSRF-Token':'test-token'})


def test_admin_timetable_and_pdf_include_actual_teacher_once_without_colleague(admin_client,workload_db):
    with workload_db() as conn:
        lesson(conn,'shared',groups=('p1','p2','p3'))
        lesson(conn,'colleague',trainer='t2',end=720)
        snapshot=panels.get_admin_trainer_planning(conn,'t1','2027-01-04')
    assert snapshot['summary']['minutes']==120 and snapshot['summary']['courses']==1
    assert len(snapshot['courses'][0]['promotion_names'])==3
    response=admin_client.get('/admin/formateurs/t1/planning.pdf?date=2027-01-04')
    assert response.status_code==200 and response.data.startswith(b'%PDF')
    assert response.headers['Content-Disposition'].startswith('inline')
    assert response.headers['Cache-Control']=='private, no-store'
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
    assert 'Cours shared' in text and 'Cours colleague' not in text


def test_admin_availability_conflict_preserves_all_selected_dates_and_courses(admin_client,workload_db):
    with workload_db() as conn:lesson(conn)
    response=save_days(admin_client,workload_db,['2027-01-04','2027-01-05'])
    assert response.status_code==409 and response.json['conflicts']
    with workload_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM planning_trainer_unavailability').fetchone()[0]==0


def test_admin_public_holiday_rejection_rolls_back_earlier_insert(admin_client,workload_db):
    response=save_days(admin_client,workload_db,['2027-05-05','2027-05-06'])
    assert response.status_code==400
    with workload_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_trainer_unavailability').fetchone()[0]==0


def test_admin_new_absence_revision_detects_old_browser_and_block_ids_are_scoped(admin_client,workload_db):
    revision=absence_data(workload_db)['state']['revision']
    first=save_days(admin_client,workload_db,['2027-01-05'],revision=revision)
    assert first.status_code==200
    second=save_days(admin_client,workload_db,['2027-01-06'],revision=revision)
    assert second.status_code==409
    with workload_db() as conn:
        block=conn.execute('SELECT id FROM planning_trainer_unavailability').fetchone()[0]
    response=admin_client.delete('/admin/formateurs/t2/indisponibilites/bloc/'+block,
        json={'expected_revision':absence_data(workload_db,'t2')['state']['revision']},headers={'X-CSRF-Token':'test-token'})
    assert response.status_code==404
    with workload_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_trainer_unavailability').fetchone()[0]==1


def test_admin_pages_and_mutations_require_admin_and_csrf(admin_client):
    outsider=admin_client.application.test_client()
    for tab in ('accounting','planning','availability','account'):
        assert outsider.get('/admin/formateurs/t1?tab='+tab).status_code==403
    assert outsider.get('/admin/formateurs/t1/planning.pdf').status_code==403
    assert outsider.post('/admin/formateurs/t1/indisponibilites/jours',json={}).status_code==403
    assert admin_client.post('/admin/formateurs/t1/indisponibilites/jours',json={}).status_code==400


def test_week_navigation_keeps_displayed_month_and_year_when_switching_tabs(admin_client):
    page=admin_client.get('/admin/formateurs/t1?tab=planning&date=2027-03-15')
    assert page.status_code==200
    assert 'tab=accounting&amp;year=2027&amp;month=2027-03' in page.text
    assert 'tab=availability&amp;year=2027&amp;month=2027-03' in page.text
    assert 'trainer-hourly-rate-form' not in page.text
    account=admin_client.get('/admin/formateurs/t1?tab=account&year=2027')
    assert account.status_code==200 and 'trainer-profile-form' in account.text
    assert 'trainer-hourly-rate-form' not in account.text


def test_availability_panel_shows_only_blocks_overlapping_selected_year(workload_db):
    with workload_db() as conn:
        for id,start,end in [('old','2026-01-05','2026-01-05'),('current','2027-01-05','2027-01-05'),('overlap','2026-12-31','2027-01-02')]:
            conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                (id,'t1',start,end,'[0,1,2,3,4,5,6]','[]','Audit'))
        snapshot=panels.get_admin_trainer_availability(conn,'t1',2027)
    assert {block['id'] for block in snapshot['blocks']}=={'current','overlap'}


@pytest.mark.parametrize('today,year', [((2026,10,29),2026), ((2027,1,15),2026), ((2027,8,15),2026), ((2027,9,1),2027)])
def test_availability_defaults_to_current_school_year(admin_client, monkeypatch, today, year):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(*today, tzinfo=tz)
    monkeypatch.setattr(trainer_access, 'datetime', Clock)
    page = admin_client.get('/admin/formateurs/t1?tab=availability')
    config = json.loads(re.search(r'id="tap-availability-config">(.*?)</script>', page.text, re.S)[1])
    assert config['state']['start'] == f'{year}-09-01'
    assert config['state']['end'] == f'{year+1}-07-31'
    assert len(config['state']['months']) == 11
    assert 'name="school_year"' in page.text


def test_school_calendar_filters_blocks_and_course_counts_across_january(admin_client, workload_db):
    with workload_db() as conn:
        for cid, day in [('sep','2026-09-01'), ('jan','2027-01-04'), ('jul','2027-07-31'), ('aug','2027-08-01')]:
            lesson(conn, cid, day=day, groups=('p1','p2'))
            conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                (cid,'t1',day,day,'[0,1,2,3,4,5,6]','[]','Audit'))
        data = panels.get_admin_trainer_availability(conn, 't1', 2026, school_year=True)
    assert {row['id'] for row in data['blocks']} == {'sep','jan','jul'}
    assert sum(row['course_count'] for row in data['state']['days']) == 3
    page = admin_client.get('/admin/formateurs/t1?tab=availability&school_year=2026')
    assert page.status_code == 200 and '2026–2027</option>' in page.text
    assert admin_client.get('/admin/formateurs/t1?tab=availability&school_year=2026&month=2027-09').status_code == 400


def test_day_course_details_are_private_current_and_trainer_scoped(admin_client, workload_db):
    with workload_db() as conn:
        lesson(conn, 'shared', groups=('p1','p2'))
        lesson(conn, 'colleague', trainer='t2')
        conn.execute("INSERT INTO planning_rooms VALUES('room','Salle Azur',1)")
        conn.execute("UPDATE planning_courses SET room_id='room' WHERE id='shared'")
    url = '/admin/formateurs/t1/indisponibilites/cours?date=2027-01-04'
    response = admin_client.get(url)
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
    assert len(response.json['courses']) == 1
    course = response.json['courses'][0]
    assert course['room_name'] == 'Salle Azur' and course['start'] == '08:00' and course['end'] == '10:00'
    assert set(course['promotion_names']) == {'Promotion p1','Promotion p2'} and course['shared']
    with workload_db() as conn:
        conn.execute("UPDATE planning_rooms SET name='Salle Olivier' WHERE id='room'")
    assert admin_client.get(url).json['courses'][0]['room_name'] == 'Salle Olivier'
    assert admin_client.application.test_client().get(url).status_code == 403
    assert admin_client.get(url+'&trainer_id=t2').status_code == 400
    assert admin_client.get(url+'&date=2027-02-01').status_code == 400
    assert admin_client.get(url.replace('2027-01-04','2027-02-30')).status_code == 400
    assert admin_client.get(url.replace('/t1/','/missing/')).status_code == 404
