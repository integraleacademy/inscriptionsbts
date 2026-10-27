"""Annual planning permissions, resource conflicts, previews and atomic writes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier
from unittest.mock import patch

from flask import Flask, session
from jinja2 import DictLoader
import pytest

import planning

BASE='/admin/planning/api'


@pytest.fixture
def db(tmp_path):
    path=tmp_path/'planning.sqlite'
    def connect():
        conn=sqlite3.connect(path,timeout=5)
        conn.row_factory=sqlite3.Row
        return conn
    with connect() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,bts TEXT,rentree_annee INTEGER,statut TEXT)')
        planning.ensure_planning_schema(conn)
        conn.execute('CREATE TABLE trainers(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,email TEXT,active INTEGER,version INTEGER)')
        for pid in ('p1','p2','undated'):
            start,end=('2027-01-01','2027-03-31') if pid!='undated' else (None,None)
            conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,'BTS MCO '+pid,'MCO',1,2026,start,end,1,'2026-10-01','2026-10-01'))
        for tid in ('t1','t2','unassigned','inactive'):
            conn.execute('INSERT INTO trainers VALUES(?,?,?,?,?,?)',(tid,'NOM '+tid,'Prénom',tid+'@example.test',int(tid!='inactive'),1))
        for tid in ('t1','t2','inactive'):
            for pid in ('p1','p2','undated'):
                conn.execute('INSERT INTO trainer_promotions(trainer_id,promotion_id) VALUES(?,?)',(tid,pid))
        for rid in ('r1','r2'):
            conn.execute('INSERT INTO planning_rooms VALUES(?,?,1)',(rid,'Salle '+rid))
        for sid,pid,tid in [('s1','p1','t1'),('s2','p2','t1'),('s3','p1','t2'),('s4','p2','t2')]:
            conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)',(sid,pid,'Matière '+sid,tid,'#626b4e',30))
    return connect


@pytest.fixture
def app(db):
    application=Flask(__name__)
    application.secret_key='planning-test-secret-not-production'
    application.config['TESTING']=True
    application.jinja_loader=DictLoader({'planning_admin.html':'{{ planning_csrf_token }}'})
    planning.register_planning(application,db,lambda:bool(session.get('admin_ok')))
    return application


def admin(app,token='csrf-test'):
    client=app.test_client()
    with client.session_transaction() as state:
        state['admin_ok']=True
        state['_planning_csrf']=token
    return client


@pytest.fixture
def client(app):return admin(app)


def call(client,path,body=None,method='POST'):
    with client.session_transaction() as state:token=state.get('_planning_csrf','')
    return client.open(path if path.startswith('/admin') else BASE+path,method=method,json=body or {},headers={'X-CSRF-Token':token})


def rule(client,pid='p1',**updates):
    data=dict(promotion_id=pid,start_date='2027-01-01',end_date='2027-03-31',weekdays=[0,1,2,3,4],kind='school',label='À l’école')
    data.update(updates)
    return call(client,'/calendar/rules',data)


def setup_school(client):
    for pid in ('p1','p2'):
        response=rule(client,pid)
        assert response.status_code==200,response.json


def course(pid='p1',sid='s1',**updates):
    data=dict(promotion_id=pid,subject_id=sid,room_id='r1',date='2027-01-04',start='09:00',end='11:00',title='Cours')
    data.update(updates)
    return data


def add(client,**updates):
    response=call(client,'/courses',course(**updates))
    assert response.status_code==200,response.json
    return response.json['course']


def count(db,table='planning_courses'):
    with db() as conn:return conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]


def types(response):return {item['type'] for item in response.json['conflicts']}


def repeat(client,**updates):
    payload=dict(promotion_id='p1',mode='repeat',start_date='2027-01-04',end_date='2027-01-25',weekdays=[0],interval_weeks=1,template=dict(subject_id='s1',room_id='r1',start='09:00',end='11:00'))
    payload.update(updates)
    return call(client,'/courses/preview',payload)


def test_permissions_csrf_json_and_admin_page(app,client,db):
    outsider=app.test_client()
    for url in ('/state?promotion_id=p1','/availability?promotion_id=p1'):
        assert outsider.get(BASE+url).status_code==403
    assert outsider.get('/admin/planning/export.pdf?promotion_id=p1').status_code==403
    assert outsider.get('/admin/formateurs/t1/indisponibilites').status_code==403
    assert call(outsider,'/courses',course()).status_code==403
    assert client.post(BASE+'/courses',json=course()).status_code==400
    assert client.post(BASE+'/rooms',json=[],headers={'X-CSRF-Token':'csrf-test'}).status_code==400
    assert client.post(BASE+'/rooms',json={},headers={'X-CSRF-Token':'é'}).status_code==400
    assert client.get('/admin/planning').status_code==200
    assert count(db)==0


def test_school_calendar_required_before_courses_and_dates_bound(client,db):
    response=call(client,'/courses',course())
    assert response.status_code==409 and 'not_school' in types(response)
    setup_school(client)
    assert add(client)['start']=='09:00'
    response=call(client,'/courses',course(date='2027-04-01'))
    assert response.status_code==409 and 'outside_promotion' in types(response)
    assert call(client,'/subjects',dict(promotion_id='undated',trainer_id='t1',name='Maths')).status_code==400
    assert count(db)==1


def test_adjacent_slots_allowed_one_minute_overlap_rejected(client,db):
    setup_school(client)
    add(client)
    add(client,start='11:00',end='12:00')
    response=call(client,'/courses',course(start='10:59',end='11:30'))
    assert response.status_code==409
    assert {'promotion_overlap','trainer_overlap','room_overlap'}<=types(response)
    assert count(db)==2


def test_conflicts_across_promotions_teacher_and_room(client,db):
    setup_school(client)
    add(client)
    response=call(client,'/courses',course('p2','s2',room_id='r2'))
    assert response.status_code==409 and types(response)=={'trainer_overlap'}
    response=call(client,'/courses',course('p2','s4'))
    assert response.status_code==409 and types(response)=={'room_overlap'}
    add(client,pid='p2',sid='s4',room_id='r2')
    assert count(db)==2


def test_resources_assignment_and_input_validation(client,db):
    setup_school(client)
    invalid=[dict(subject_id='s2'),dict(trainer_id='unassigned'),dict(trainer_id='inactive'),dict(room_id='missing'),dict(start='25:00'),dict(end='09:00'),dict(date='2027-02-30'),dict(subject_id=[]),dict(trainer_id={}),dict(promotion_id=[])]
    for updates in invalid:
        assert call(client,'/courses',course(**updates)).status_code==400,updates
    for tid in ('unassigned','inactive'):
        assert call(client,'/subjects',dict(promotion_id='p1',name='Test',trainer_id=tid)).status_code==400
    for hours in (10**400,'nan',float('inf'),-1):
        assert call(client,'/subjects',dict(promotion_id='p1',name='Test',trainer_id='t1',planned_hours=hours)).status_code==400
    assert count(db)==0


def test_move_version_and_delete_protect_lost_updates(client,db):
    setup_school(client);first=add(client)
    path='/courses/'+first['id']
    assert call(client,path,dict(start='12:00',end='13:00'),method='PUT').status_code==400
    moved=call(client,path,dict(version=1,start='12:00',end='13:00'),method='PUT')
    assert moved.status_code==200 and moved.json['course']['version']==2
    stale=call(client,path,dict(version=1,date='2027-01-05'),method='PUT')
    assert stale.status_code==409 and types(stale)=={'stale'}
    assert call(client,path,{},method='DELETE').status_code==400
    assert call(client,path,dict(version=1),method='DELETE').status_code==409
    assert call(client,path,dict(version=2),method='DELETE').status_code==200
    assert count(db)==0


def test_calendar_rules_conflicts_holidays_and_safe_edits(client,db):
    initial=rule(client).json['rule'];add(client)
    response=rule(client,kind='company')
    assert response.status_code==409 and 'calendar_overlap' in types(response)
    response=rule(client,kind='holiday',start_date='2027-01-04',end_date='2027-01-04')
    assert response.status_code==409 and 'existing_course' in types(response)
    assert call(client,'/calendar/rules/'+initial['id'],{},method='DELETE').status_code==409
    assert call(client,'/calendar/rules/'+initial['id'],dict(kind='company'),method='PUT').status_code==409
    assert call(client,'/calendar/exceptions',dict(promotion_id='p1',date='2027-01-04',kind='closed',label='Fermeture'),method='PUT').status_code==409
    assert count(db,'planning_calendar_rules')==1
    assert count(db,'planning_day_exceptions')==0


def test_holiday_precedence_school_exception_and_exception_delete_guard(client):
    rule(client)
    assert rule(client,kind='holiday',start_date='2027-01-04',end_date='2027-01-08',label='Vacances').status_code==200
    assert call(client,'/courses',course()).status_code==409
    exception=dict(promotion_id='p1',date='2027-01-04',kind='school',label='Reprise exceptionnelle')
    assert call(client,'/calendar/exceptions',exception,method='PUT').status_code==200
    add(client)
    assert call(client,'/calendar/exceptions/p1/2027-01-04',{},method='DELETE').status_code==409
    state=client.get(BASE+'/state?promotion_id=p1&start=2027-01-04&end=2027-01-05').json
    assert [item['kind'] for item in state['days']]==['school','holiday']


def test_trainer_unavailability_recurring_and_existing_courses(client,db):
    setup_school(client)
    url='/admin/formateurs/t1/indisponibilites'
    payload=dict(start_date='2027-01-01',end_date='2027-01-31',weekdays=[0],times=[dict(start='09:00',end='11:00')],reason='Autre mission')
    response=call(client,url,payload)
    assert response.status_code==200
    block=response.json['item']
    for pid,sid in [('p1','s1'),('p2','s2')]:
        conflict=call(client,'/courses',course(pid,sid))
        assert conflict.status_code==409 and 'unavailable' in types(conflict)
    add(client,start='11:00',end='12:00')
    add(client,date='2027-01-05')
    response=call(client,url,dict(start_date='2027-01-05',end_date='2027-01-05',reason='Toute la journée'))
    assert response.status_code==409 and 'unavailable' in types(response)
    assert count(db,'planning_trainer_unavailability')==1
    assert client.get(url).json['items'][0]['times']==payload['times']
    assert call(client,'/admin/formateurs/t2/indisponibilites/'+block['id'],{},method='DELETE').status_code==404
    assert call(client,url+'/'+block['id'],{},method='DELETE').status_code==200


def test_repeat_preview_has_calendar_conflicts_and_explicit_subset_commit(client,db):
    setup_school(client)
    rule(client,kind='holiday',start_date='2027-01-11',end_date='2027-01-11',label='Vacances')
    preview=repeat(client)
    assert preview.status_code==200
    assert preview.json['summary']==dict(total=4,valid=3,conflicts=1)
    assert count(db)==0
    token=preview.json['preview_token']
    assert call(client,'/courses/batch',dict(preview_token=token)).status_code==400
    assert call(client,'/courses/batch',dict(preview_token=token,selected_keys=['0','1','2','3'])).status_code==409
    assert count(db)==0
    response=call(client,'/courses/batch',dict(preview_token=token,selected_keys=['0','2','3']))
    assert response.status_code==200 and response.json['count']==3
    assert count(db)==3
    assert call(client,'/courses/batch',dict(preview_token=token,selected_keys=['0'])).status_code==409


def test_recurrence_interval_anchored_to_week_start_and_duplicates(client,db):
    setup_school(client)
    preview=repeat(client,start_date='2027-01-06',end_date='2027-01-29',weekdays=[0,2],interval_weeks=2)
    assert [item['course']['date'] for item in preview.json['items']]==['2027-01-06','2027-01-18','2027-01-20']
    source=add(client)
    duplicate=call(client,'/courses/preview',dict(promotion_id='p1',mode='duplicate',course_ids=[source['id']],target_start='2027-01-11'))
    assert duplicate.status_code==200 and duplicate.json['items'][0]['course']['date']=='2027-01-11'
    token=duplicate.json['preview_token']
    assert call(client,'/courses/batch',dict(preview_token=token,selected_keys=['0'])).status_code==200
    assert count(db)==2


def test_batch_revalidates_db_and_never_writes_partial_selection(client,db):
    setup_school(client);preview=repeat(client).json
    add(client,date='2027-01-25')
    response=call(client,'/courses/batch',dict(preview_token=preview['preview_token'],selected_keys=['0','1','2','3']))
    assert response.status_code==409 and 'promotion_overlap' in types(response)
    assert count(db)==1


def test_batch_internal_conflicts_cannot_be_bypassed_by_forged_selection(client,db):
    setup_school(client);source=add(client)
    # A migrated inconsistent source range must not be reproduced by trusting preview checkboxes.
    with db() as conn:
        conn.execute('INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,title,version,created_at,updated_at) SELECT ?,promotion_id,subject_id,trainer_id,room_id,date,start_min+30,end_min+30,title,version,created_at,updated_at FROM planning_courses WHERE id=?',('legacy-overlap',source['id']))
    preview=call(client,'/courses/preview',dict(promotion_id='p1',mode='duplicate',source_start='2027-01-04',source_end='2027-01-04',target_start='2027-01-11')).json
    assert all(not row['valid'] for row in preview['items'])
    response=call(client,'/courses/batch',dict(preview_token=preview['preview_token'],selected_keys=['0','1']))
    assert response.status_code==409 and 'promotion_overlap' in types(response)
    assert count(db)==2


def test_batch_session_expiry_tampering_and_canonical_indices(client,app,db):
    setup_school(client);token=repeat(client).json['preview_token']
    other=admin(app,'other-csrf')
    assert call(other,'/courses/batch',dict(preview_token=token,selected_keys=['0'])).status_code==409
    for bad in ('tampered',token+'garbage',None,[]):
        assert call(client,'/courses/batch',dict(preview_token=bad,selected_keys=['0'])).status_code==409
    for selected in (['²'],['٠'],['00'],['-1'],['99999'],['0','0'],[0],[{}]):
        assert call(client,'/courses/batch',dict(preview_token=token,selected_keys=selected)).status_code==400
    signer=planning.URLSafeTimedSerializer(app.secret_key,salt='bts-planning-preview-v1')
    contents=signer.loads(token)
    with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=1):expired=signer.dumps(contents)
    assert call(client,'/courses/batch',dict(preview_token=expired,selected_keys=['0'])).status_code==409
    assert count(db)==0


def test_availability_read_only_respects_resources_and_move_exclusion(client,db):
    setup_school(client);first=add(client)
    query='/availability?promotion_id=p1&subject_id=s1&room_id=r1&start=2027-01-04&end=2027-01-04&duration=120&day_start=09:00&day_end=13:00'
    slots=client.get(BASE+query).json['slots']
    assert slots[0]['available'] is False
    assert slots[-1]['available'] is True
    moved=client.get(BASE+query+'&exclude_course_id='+first['id']).json['slots']
    assert all(row['available'] for row in moved)
    assert count(db)==1
    assert client.get(BASE+query.replace('end=2027-01-04','end=2027-03-31')).status_code==400


def test_state_scheduled_hours_and_used_resource_deletion_guards(client,db):
    setup_school(client);first=add(client);add(client,date='2027-01-05',start='09:00',end='10:30')
    state=client.get(BASE+'/state?promotion_id=p1&start=2027-01-04&end=2027-01-04').json
    assert len(state['courses'])==1
    assert next(row for row in state['subjects'] if row['id']=='s1')['scheduled_hours']==3.5
    assert state['courses'][0]['trainer_name']=='Prénom NOM t1'
    assert call(client,'/subjects/s1',{},method='DELETE').status_code==409
    assert call(client,'/rooms/r1',dict(active=False),method='PUT').status_code==409
    assert call(client,'/rooms/r1',{},method='DELETE').status_code==409
    assert call(client,'/subjects/s1',dict(trainer_id='t2'),method='PUT').status_code==200
    with db() as conn:assert conn.execute('SELECT trainer_id FROM planning_courses WHERE id=?',(first['id'],)).fetchone()[0]=='t1'


@pytest.mark.parametrize('kind',[[],{},None,17])
def test_malformed_calendar_enum_is_validation_error(client,kind):
    assert rule(client,kind=kind).status_code==400
    assert call(client,'/calendar/exceptions',dict(promotion_id='p1',date='2027-01-04',kind=kind),method='PUT').status_code==400


def test_date_extremes_and_duplicate_overflow_are_handled(client,db):
    setup_school(client);source=add(client)
    response=call(client,'/courses/preview',dict(promotion_id='p1',mode='duplicate',course_ids=[source['id']],source_start='9999-12-31',target_start='0001-01-01'))
    assert response.status_code==400
    state=client.get(BASE+'/state?promotion_id=p1&start=9999-12-31&end=9999-12-31')
    assert state.status_code==200 and len(state.json['days'])==1
    assert list(planning._dates(planning.date.max,planning.date.max))==[planning.date.max]


def test_pdf_export_authorized_inline_and_unconfigured_rejected(client):
    setup_school(client);add(client)
    with patch('planning_pdf.build_planning_pdf',return_value=b'%PDF-1.4 test') as build:
        response=client.get('/admin/planning/export.pdf?promotion_id=p1&start=2027-01-04&end=2027-01-10&view=weekly')
        assert response.status_code==200 and response.mimetype=='application/pdf'
        assert response.headers['Content-Disposition'].startswith('inline;')
        assert response.headers['Cache-Control']=='private, no-store'
        assert response.headers['X-Content-Type-Options']=='nosniff'
        assert build.call_args.args[0]['id']=='p1'
        assert len(build.call_args.args[1])==1
        assert build.call_args.kwargs=={'mode':'weekly'}
    assert client.get('/admin/planning/export.pdf?promotion_id=undated').status_code==400
    assert client.get('/admin/planning/export.pdf?promotion_id=p1&view=unknown').status_code==400


def test_schema_and_parent_guards_preserve_transaction(client,db):
    setup_school(client);add(client)
    conn=db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE planning_rooms SET name=? WHERE id=?',('Not committed','r1'))
        planning.ensure_planning_schema(conn)
        issues=planning.validate_promotion_change(conn,'p1',dict(date_debut='2027-01-05'))
        assert {'outside_promotion','calendar_outside'}<={row['type'] for row in issues}
        assert planning.validate_trainer_promotions_change(conn,'t1',['p2'])
        assert not planning.validate_trainer_promotions_change(conn,'t1',['p1','p2'])
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute('SELECT name FROM planning_rooms WHERE id=?',('r1',)).fetchone()[0]=='Salle r1'
    finally:conn.close()


def test_simultaneous_course_creations_serialize_resource_validation(app,client,db):
    setup_school(client)
    barrier=Barrier(2)
    def worker(index):
        own=admin(app,'concurrent-'+str(index));barrier.wait()
        return call(own,'/courses',course()).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:statuses=list(executor.map(worker,[1,2]))
    assert sorted(statuses)==[200,409]
    assert count(db)==1


def test_concurrent_course_and_unavailability_cannot_create_inconsistent_state(app,client,db):
    setup_school(client);barrier=Barrier(2)
    def worker(kind):
        own=admin(app,'concurrent-'+kind);barrier.wait()
        if kind=='course':return call(own,'/courses',course()).status_code
        return call(own,'/admin/formateurs/t1/indisponibilites',dict(start_date='2027-01-04',end_date='2027-01-04',reason='Absent')).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:statuses=list(executor.map(worker,['course','block']))
    assert sorted(statuses)==[200,409]
    assert count(db)+count(db,'planning_trainer_unavailability')==1


def test_catalog_minutes_precision_and_fractional_minute_rejected(client,db):
    setup_school(client)
    response=call(client,'/subjects/s1',dict(planned_hours=1.1),method='PUT')
    assert response.status_code==200
    assert response.json['subject']['planned_minutes']==66
    add(client,end='10:06')
    state=client.get(BASE+'/catalog').json
    subject=next(item for item in state['subjects'] if item['id']=='s1')
    assert subject['scheduled_minutes']==66 and subject['remaining_minutes']==0
    assert subject['remaining_hours']==0 and subject['budget_configured'] is True
    assert {'p1','p2','undated'}=={row['id'] for row in state['promotions']}
    assert next(item for item in state['trainers'] if item['id']=='t1')['promotion_ids']==['p1','p2','undated']
    for value in (.001,True,None):
        assert call(client,'/subjects/s1',dict(planned_hours=value),method='PUT').status_code==400
    with db() as conn:assert conn.execute('SELECT planned_hours FROM planning_subjects WHERE id=?',('s1',)).fetchone()[0]==1.1


def test_catalog_pages_require_admin_and_do_not_cache(app,client):
    app.jinja_loader=DictLoader({'planning_subjects.html':'{{ planning_csrf_token }}','planning_rooms.html':'{{ planning_csrf_token }}'})
    visitor=app.test_client()
    for path in ('/admin/matieres','/admin/salles',BASE+'/catalog'):
        assert visitor.get(path).status_code==403
        response=client.get(path)
        assert response.status_code==200 and response.headers['Cache-Control']=='no-store'


def test_bulk_calendar_requires_revision_and_invalidates_after_rule_or_exception(client,db):
    initial=rule(client).json
    assert initial['calendar_revision']==1
    payload=dict(promotion_id='p1',days=[dict(date='2027-01-05',kind='company')])
    assert call(client,'/calendar/bulk',payload).status_code==400
    payload['expected_revision']=1
    assert call(client,'/calendar/exceptions',dict(promotion_id='p1',date='2027-01-06',kind='holiday'),method='PUT').json['calendar_revision']==2
    response=call(client,'/calendar/bulk',payload)
    assert response.status_code==409 and types(response)=={'calendar_stale'}
    assert count(db,'planning_day_exceptions')==1
    payload['expected_revision']=2
    assert call(client,'/calendar/bulk',payload).json['calendar_revision']==3
    assert client.get(BASE+'/state?promotion_id=p1').json['calendar_revision']==3


def test_shared_duplicate_from_secondary_and_independent_local_display(client,db):
    setup_school(client)
    response=call(client,'/courses',course(shared=[dict(promotion_id='p2',subject_id='s2')]))
    assert response.status_code==200
    cid=response.json['course']['id']
    state=client.get(BASE+'/state?promotion_id=p2').json
    assert len(state['courses'])==1 and state['courses'][0]['id']==cid
    assert state['courses'][0]['promotion_id']=='p1'
    assert state['courses'][0]['display_subject_name']=='Matière s2'
    assert call(client,'/subjects/s2',{},method='DELETE').status_code==409
    preview=call(client,'/courses/preview',dict(promotion_id='p2',mode='duplicate',course_ids=[cid],target_start='2027-01-11'))
    assert preview.status_code==200 and preview.json['items'][0]['course']['shared']==[dict(promotion_id='p2',subject_id='s2')]
    response=call(client,'/courses/batch',dict(preview_token=preview.json['preview_token'],selected_keys=['0']))
    assert response.status_code==200 and count(db)==2 and count(db,'planning_course_groups')==4


def test_shared_availability_checks_each_calendar_and_budget(client,db):
    import json
    from urllib.parse import urlencode
    setup_school(client)
    with db() as conn:conn.execute('UPDATE planning_subjects SET planned_hours=1 WHERE id=?',('s2',))
    query=dict(promotion_id='p1',subject_id='s1',trainer_id='t1',room_id='r1',start='2027-01-04',end='2027-01-04',duration=120,shared=json.dumps([dict(promotion_id='p2',subject_id='s2')]))
    response=client.get(BASE+'/availability?'+urlencode(query))
    assert response.status_code==200
    assert all(not row['available'] for row in response.json['slots'])
    assert all(any(issue['type']=='subject_budget' and issue['subject_id']=='s2' for issue in row['conflicts']) for row in response.json['slots'])
    query['shared']='not-json'
    assert client.get(BASE+'/availability?'+urlencode(query)).status_code==400


def test_annual_pdf_receives_entire_subject_budget_snapshot(client):
    setup_school(client);add(client)
    with patch('planning_pdf.build_planning_pdf',return_value=b'%PDF-1.4 test') as build:
        response=client.get('/admin/planning/export.pdf?promotion_id=p1&view=annual')
        assert response.status_code==200
        assert build.call_args.kwargs['mode']=='annual'
        subject=next(item for item in build.call_args.kwargs['subjects'] if item['id']=='s1')
        assert subject['planned_minutes']==1800 and subject['scheduled_minutes']==120


def test_national_holidays_follow_official_2026_2027_dates():
    # https://www.service-public.gouv.fr/particuliers/vosdroits/F2405
    from planning_holidays import french_public_holidays, public_holiday_name
    assert len(french_public_holidays(2026)) == 11
    assert len(french_public_holidays(2027)) == 11
    assert public_holiday_name('2026-04-06') == 'Lundi de Pâques'
    assert public_holiday_name('2026-05-14') == 'Ascension'
    assert public_holiday_name('2026-05-25') == 'Lundi de Pentecôte'
    assert public_holiday_name('2027-03-29') == 'Lundi de Pâques'
    assert public_holiday_name('2027-05-06') == 'Ascension'
    assert public_holiday_name('2027-05-17') == 'Lundi de Pentecôte'
    assert public_holiday_name('2027-04-01') is None


def test_missing_room_is_visible_and_flagged_without_blocking_course_creation(client):
    setup_school(client)
    added = add(client, room_id=None)
    assert added['incomplete'] is True
    assert added['warnings'] == [{'code': 'room_missing', 'message': 'Salle non affectée'}]
    assert added['warning_labels'] == ['Salle non affectée']
    fixed = call(client, '/courses/' + added['id'], {'version': added['version'], 'room_id': 'r2'}, method='PUT')
    assert fixed.status_code == 200
    assert fixed.json['course']['incomplete'] is False
    assert fixed.json['course']['warnings'] == []


def test_legacy_orphan_resources_do_not_hide_course_or_free_occupied_slot(client, db):
    setup_school(client)
    added = add(client)
    with db() as conn:
        conn.execute("DELETE FROM planning_rooms WHERE id='r1'")
        conn.execute("DELETE FROM planning_subjects WHERE id='s1'")
        conn.execute("DELETE FROM trainers WHERE id='t1'")
    state = client.get(BASE + '/state?promotion_id=p1').json
    stored = next(item for item in state['courses'] if item['id'] == added['id'])
    assert {'room_missing', 'subject_missing', 'trainer_missing'} <= {item['code'] for item in stored['warnings']}
    assert stored['display_subject_name'] == 'Matière à renseigner'
    response = call(client, '/courses', course(sid='s3', trainer_id='t2', room_id='r2'))
    assert response.status_code == 409 and 'promotion_overlap' in types(response)


def test_explicit_date_duplication_sorts_dates_and_preserves_shared_course(client, db):
    setup_school(client)
    added = add(client, shared=[{'promotion_id': 'p2', 'subject_id': 's2'}])
    preview = call(client, '/courses/preview', dict(promotion_id='p2', mode='dates', source_course_id=added['id'], source_version=1, dates=['2027-01-12', '2027-01-06']))
    assert preview.status_code == 200, preview.json
    assert [item['course']['date'] for item in preview.json['items']] == ['2027-01-06', '2027-01-12']
    assert all(item['valid'] and item['course']['shared'] == [{'promotion_id': 'p2', 'subject_id': 's2'}] for item in preview.json['items'])
    committed = call(client, '/courses/batch', dict(preview_token=preview.json['preview_token'], selected_keys=['0', '1']))
    assert committed.status_code == 200
    assert count(db) == 3
    second = client.get(BASE + '/state?promotion_id=p2').json
    assert len(second['courses']) == 3
    assert next(item for item in second['subjects'] if item['id'] == 's2')['scheduled_minutes'] == 360


def test_explicit_source_duplication_requires_fresh_version_at_preview_and_commit(client, db):
    setup_school(client)
    added = add(client)
    payload = dict(promotion_id='p1', mode='dates', source_course_id=added['id'], source_version=1, dates=['2027-01-05'])
    preview = call(client, '/courses/preview', payload)
    assert preview.status_code == 200
    assert call(client, '/courses/' + added['id'], {'version': 1, 'title': 'Mis à jour'}, method='PUT').status_code == 200
    stale = call(client, '/courses/preview', payload)
    assert stale.status_code == 409 and 'stale' in types(stale)
    commit = call(client, '/courses/batch', {'preview_token': preview.json['preview_token'], 'selected_keys': ['0']})
    assert commit.status_code == 409
    assert count(db) == 1


def test_explicit_dates_validate_duplicates_and_have_no_silent_partial_commit(client, db):
    setup_school(client)
    payload = dict(promotion_id='p1', mode='dates', dates=['2027-01-05', '2027-01-05'], template={'subject_id':'s1','room_id':'r1','start':'08:00','end':'10:00'})
    assert call(client, '/courses/preview', payload).status_code == 400
    payload['dates'] = ['2027-01-05', '2027-01-01']
    preview = call(client, '/courses/preview', payload)
    assert preview.status_code == 200
    assert [item['valid'] for item in preview.json['items']] == [False, True]
    bad = call(client, '/courses/batch', {'preview_token': preview.json['preview_token'], 'selected_keys':['0','1']})
    assert bad.status_code == 409 and count(db) == 0
    good = call(client, '/courses/batch', {'preview_token': preview.json['preview_token'], 'selected_keys':['1']})
    assert good.status_code == 200 and count(db) == 1


def test_template_duplication_does_not_accept_private_source_metadata(client, db):
    setup_school(client)
    payload = dict(promotion_id='p1', mode='dates', dates=['2027-01-05'], template={'subject_id':'s1','room_id':'r1','start':'08:00','end':'10:00','_source_course_id':['invalid'],'_source_version':{}})
    preview = call(client, '/courses/preview', payload)
    assert preview.status_code == 200
    result = call(client, '/courses/batch', {'preview_token':preview.json['preview_token'],'selected_keys':['0']})
    assert result.status_code == 200
    assert count(db) == 1


def test_course_loader_trainer_filter_intersects_promotion_scope(client, db):
    setup_school(client)
    first = add(client, shared=[{'promotion_id':'p2','subject_id':'s2'}])
    second = add(client, sid='s3', date='2027-01-05', room_id='r2')
    with db() as conn:
        assert [item['id'] for item in planning._load_courses(conn, trainer_id='t2')] == [second['id']]
        assert [item['id'] for item in planning._load_courses(conn, promotion_id='p2', trainer_id='t1')] == [first['id']]
        assert planning._load_courses(conn, promotion_id='p2', trainer_id='t2') == []


def test_zoom_belongs_to_saved_course_and_is_not_duplicated(client,db):
    setup_school(client)
    source=add(client,zoom_url='https://school.zoom.us/j/123?pwd=secret')
    assert source['zoom_url']=='https://school.zoom.us/j/123?pwd=secret'
    changed=call(client,'/courses/'+source['id'],{'version':source['version'],'title':'Nouveau titre'},method='PUT')
    assert changed.status_code==200 and changed.json['course']['zoom_url']==source['zoom_url']
    preview=call(client,'/courses/preview',dict(promotion_id='p1',mode='duplicate',source_start='2027-01-04',source_end='2027-01-04',target_start='2027-01-11')).json
    result=call(client,'/courses/batch',dict(preview_token=preview['preview_token'],selected_keys=['0']))
    assert result.status_code==200
    with db() as conn:
        assert conn.execute("SELECT zoom_url FROM planning_courses WHERE date='2027-01-11'").fetchone()[0]==''
        planning.ensure_planning_schema(conn)
        planning.ensure_planning_schema(conn)
        assert conn.execute('SELECT zoom_url FROM planning_courses WHERE id=?',(source['id'],)).fetchone()[0]==source['zoom_url']
    invalid=call(client,'/courses',course(date='2027-01-05',zoom_url='https://zoom.us.example.test/j/123'))
    assert invalid.status_code==400
