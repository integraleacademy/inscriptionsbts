"""Annual migration, isolation and atomic reviewed course removal."""
import json
from unittest.mock import patch

import pytest

import planning
from test_planning import db, app, client, call, BASE


def raw_course(conn, cid, sid, day, pid='p1', shared=False):
    conn.execute('''INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,
        date,start_min,end_min,title,created_at,updated_at) VALUES(?,?,?,'t1',?,540,660,'','now','now')''',
        (cid,pid,sid,day))
    conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)',(cid,pid,sid))
    if shared:conn.execute("INSERT INTO planning_course_groups VALUES(?,'p2','s2')",(cid,))


@pytest.fixture
def annual(db):
    # Legacy promotion and allocations, before the first annual migration.
    with db() as conn:
        conn.execute("UPDATE promotions SET date_debut='2026-09-01',date_fin='2028-07-01' WHERE id IN ('p1','p2')")
        for pid in ('p1','p2'):
            conn.execute('INSERT INTO planning_calendar_rules VALUES(?,?,?,?,?,?,?)',
                ('legacy-'+pid,pid,'2026-09-01','2028-07-01',json.dumps([0,1,2,3,4]),'school','Rythme existant'))
        raw_course(conn,'first','s1','2026-11-04',shared=True)
        raw_course(conn,'second','s1','2027-11-04',shared=True)
        raw_course(conn,'first-other','s3','2027-01-11')
        raw_course(conn,'summer','s1','2027-08-23')
    return db


def snapshot(client, year=1, pid='p1'):
    response=client.get(BASE+f'/state?promotion_id={pid}&period_id={pid}:{year}')
    assert response.status_code==200,response.json
    return response.json


def mutate(client,path,data=None,year=1,pid='p1',method='POST'):
    return client.open(BASE+path,method=method,json=data or {},headers={
        'X-CSRF-Token':'csrf-test','X-Planning-Promotion':pid,'X-Planning-Period':f'{pid}:{year}'})


def allocation(state, name='Matière s1'):
    return next(s for s in state['subjects'] if s['name']==name)


def preview(client,year=1,mode='subject',**values):
    return mutate(client,'/courses/delete-preview',dict(promotion_id='p1',period_id=f'p1:{year}',mode=mode,**values),year)


def test_migration_preserves_courses_and_splits_each_year(annual,client):
    first,second=snapshot(client),snapshot(client,2)
    assert [(p['start_date'],p['end_date']) for p in first['periods']]==[
        ('2026-09-01','2027-07-01'),('2027-09-01','2028-07-01')]
    assert first['cohort']['date_fin']=='2028-07-01'
    assert first['promotion']['date_fin']=='2027-07-01'
    assert {c['id'] for c in first['courses']}=={'first','first-other'}
    assert {c['id'] for c in second['courses']}=={'second'}
    assert [c['id'] for c in first['outside_courses']]==['summer']
    assert allocation(first)['id']!=allocation(second)['id']
    assert allocation(first)['planned_hours']==allocation(second)['planned_hours']==30
    assert allocation(first)['scheduled_minutes']==allocation(second)['scheduled_minutes']==120
    assert [d['date'] for d in second['scheduled_days']]==['2027-11-04']
    assert all('2026-09-01'<=r['start_date']<=r['end_date']<='2027-07-01' for r in first['rules'])
    assert all('2027-09-01'<=r['start_date']<=r['end_date']<='2028-07-01' for r in second['rules'])
    with annual() as conn:
        before={table:[tuple(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in
                ('planning_subjects','planning_courses','planning_course_groups','planning_calendar_rules')}
        planning.ensure_planning_schema(conn)
        after={table:[tuple(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in before}
        assert before==after
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0]==4
        assert conn.execute("SELECT COUNT(*) FROM planning_calendar_rules WHERE start_date='2027-07-02' AND end_date='2027-08-31'").fetchone()[0]==2
    shared=snapshot(client,2,'p2')
    assert shared['courses'][0]['display_subject_id']==allocation(shared,'Matière s2')['id']


def test_budgets_teachers_and_subject_removal_are_independent(annual,client):
    first,second=snapshot(client),snapshot(client,2)
    sid=allocation(second)['id']
    response=mutate(client,'/subjects/'+sid,dict(planned_hours=2,trainer_id='t2'),2,method='PUT')
    assert response.status_code==200,response.json
    assert allocation(snapshot(client))['planned_hours']==30
    assert allocation(snapshot(client))['trainer_id']=='t1'
    assert allocation(snapshot(client,2))['remaining_minutes']==0
    assert mutate(client,'/subjects/'+sid,dict(planned_hours=10),1,method='PUT').status_code==409
    unused=allocation(second,'Matière s3')['id']
    assert mutate(client,'/subjects/'+unused,{},2,method='DELETE').status_code==200
    assert allocation(snapshot(client),'Matière s3')
    assert not any(s['id']==unused for s in snapshot(client,2)['subjects'])
    # Adding the same catalogue subject back only affects the selected year.
    source=allocation(first,'Matière s3')
    response=mutate(client,'/subjects',dict(promotion_id='p1',catalog_subject_id=source['catalog_subject_id'],trainer_id='t2',planned_hours=12),2)
    assert response.status_code==200,response.json
    assert allocation(snapshot(client,2),'Matière s3')['planned_hours']==12
    assert allocation(snapshot(client),'Matière s3')['planned_hours']==30


def test_rhythm_and_revision_are_scoped_to_year(annual,client):
    first,second=snapshot(client),snapshot(client,2)
    response=mutate(client,'/calendar/bulk',dict(promotion_id='p1',expected_revision=first['calendar_revision'],days=[dict(date='2026-11-05',kind='company')]))
    assert response.status_code==200,response.json
    assert snapshot(client)['calendar_revision']==1
    assert snapshot(client,2)['calendar_revision']==second['calendar_revision']
    assert not snapshot(client,2)['exceptions']
    assert mutate(client,'/calendar/rules/'+second['rules'][0]['id'],method='DELETE').status_code==409
    assert mutate(client,'/calendar/rules',dict(promotion_id='p1',start_date='2026-09-01',end_date='2028-07-01',weekdays=[0],kind='company')).status_code==409
    assert mutate(client,'/calendar/bulk',dict(promotion_id='p1',expected_revision=1,days=[dict(date='2027-11-05',kind='company')])).status_code==409
    assert mutate(client,'/calendar/exceptions',dict(promotion_id='p1',date='2027-11-05',kind='company'),method='PUT').status_code==409
    assert mutate(client,'/calendar/exceptions/p1/2027-11-05',method='DELETE').status_code==409
    assert len(snapshot(client,2)['rules'])==len(second['rules'])


def test_courses_and_duplication_cannot_cross_year(annual,client):
    first,second=snapshot(client),snapshot(client,2)
    data=dict(promotion_id='p1',subject_id='s1',date='2027-11-08',start='09:00',end='10:00')
    assert mutate(client,'/courses',data).status_code==409
    second_course=second['courses'][0]
    assert mutate(client,'/courses/second',dict(version=second_course['version']),method='DELETE').status_code==409
    assert mutate(client,'/courses/first',dict(version=first['courses'][0]['version'],subject_id=allocation(second)['id'],date='2027-11-08'),method='PUT').status_code==409
    response=mutate(client,'/courses/preview',dict(promotion_id='p1',mode='dates',source_course_id='first',source_version=first['courses'][0]['version'],dates=['2027-11-08']))
    assert response.status_code==200,response.json
    assert response.json['items'][0]['conflicts']
    assert len(snapshot(client,2)['courses'])==1


def test_delete_all_subject_is_annual_and_keeps_other_promotions(annual,client):
    before=snapshot(client,2)
    response=preview(client,subject_id=allocation(snapshot(client))['id'])
    assert response.status_code==200,response.json
    assert response.json['count']==1 and response.json['shared_count']==1
    assert [c['id'] for c in response.json['courses']]==['first']
    token=response.json['preview_token']
    assert len(snapshot(client)['courses'])==2  # preview is read-only
    deleted=mutate(client,'/courses/delete-batch',dict(preview_token=token))
    assert deleted.status_code==200,deleted.json
    assert deleted.json['detached_count']==1
    assert [c['id'] for c in snapshot(client)['courses']]==['first-other']
    assert snapshot(client,2)['courses']==before['courses']
    assert 'first' in {c['id'] for c in snapshot(client,1,'p2')['courses']}
    with annual() as conn:
        assert conn.execute("SELECT promotion_id FROM planning_courses WHERE id='first'").fetchone()[0]=='p2'
        assert conn.execute("SELECT COUNT(*) FROM planning_courses WHERE id='summer'").fetchone()[0]==1
    assert mutate(client,'/courses/delete-batch',dict(preview_token=token)).status_code==409


def test_selected_deletion_rejects_foreign_year_and_is_atomic(annual,client):
    snapshot(client)
    for ids in (['first','second'],['first','summer'],['first','missing']):
        assert preview(client,mode='selected',course_ids=ids).status_code==409
    response=preview(client,mode='selected',course_ids=['first','first-other'])
    assert response.status_code==200,response.json
    token=response.json['preview_token']
    with annual() as conn:conn.execute("UPDATE planning_courses SET version=version+1 WHERE id='first-other'")
    assert mutate(client,'/courses/delete-batch',dict(preview_token=token)).status_code==409
    assert len(snapshot(client)['courses'])==2
    token=preview(client,mode='selected',course_ids=['first','first-other']).json['preview_token']
    assert mutate(client,'/courses/delete-batch',dict(preview_token=token)).status_code==200
    assert not snapshot(client)['courses']
    assert len(snapshot(client,2)['courses'])==1


def test_delete_preview_guards_new_courses_session_year_and_csrf(annual,client,app):
    snapshot(client)
    token=preview(client,subject_id='s1').json['preview_token']
    with annual() as conn:raw_course(conn,'new','s1','2026-11-06')
    assert mutate(client,'/courses/delete-batch',dict(preview_token=token)).status_code==409
    assert mutate(client,'/courses/delete-batch',dict(preview_token=token),2).status_code==409
    other=app.test_client()
    with other.session_transaction() as session:session.update(admin_ok=True,_planning_csrf='another')
    assert call(other,'/courses/delete-batch',dict(preview_token=token)).status_code==409
    assert client.post(BASE+'/courses/delete-batch',json=dict(preview_token=token)).status_code==400
    assert app.test_client().post(BASE+'/courses/delete-preview',json={}).status_code==403
    assert mutate(client,'/courses/batch',dict(preview_token=token,selected_keys=['0'])).status_code==409
    assert mutate(client,'/courses/delete-batch',dict(preview_token='tampered')).status_code==409
    assert len(snapshot(client)['courses'])==3


def test_pdf_only_contains_the_selected_year(annual,client):
    with patch('planning_pdf.build_planning_pdf',return_value=b'%PDF test') as build:
        response=client.get('/admin/planning/export.pdf?promotion_id=p1&period_id=p1:2&view=annual')
        assert response.status_code==200,response.json
        assert build.call_args.args[0]['date_debut']=='2027-09-01'
        assert [c['id'] for c in build.call_args.args[1]]==['second']
        assert all(s['period_id']=='p1:2' for s in build.call_args.kwargs['subjects'])
    assert client.get('/admin/planning/export.pdf?promotion_id=p1&period_id=p1:1&start=2026-09-01&end=2028-07-01').status_code==409


def test_summer_courses_can_be_repaired_without_entering_bulk_selection(annual,client):
    state=snapshot(client,2);outside=state['outside_courses'][0]
    response=mutate(client,'/courses/summer',dict(version=outside['version'],date='2027-11-08',subject_id=allocation(state)['id']),2,method='PUT')
    assert response.status_code==200,response.json
    assert not snapshot(client)['outside_courses']
    assert {c['id'] for c in snapshot(client,2)['courses']}=={'second','summer'}
