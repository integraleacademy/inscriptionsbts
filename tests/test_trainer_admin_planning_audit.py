"""Independent scoped admin tabs, private PDF and atomic absence mutations."""
from io import BytesIO
from flask import session
import pytest
from pypdf import PdfReader

import trainer_admin_planning as panels
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
