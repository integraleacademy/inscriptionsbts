"""Room-grid actions remove one local course or release one linked room slot."""
import json

import pytest
from planning import _load_courses
from test_planning import db, app, client, call, BASE, setup_school, add
from test_planning_rooms_events import linked, event, machine, reservation
from test_room_calendar import seed, schedule, move


def release(client, row, **changes):
    payload={key:row[key] for key in ('key','date','revision','room_version')}
    payload.update(confirm_release=True, **changes)
    return call(client,'/rooms/calendar-release',payload)


def test_room_grid_shared_course_delete_updates_all_plannings_and_only_one_slot(client,db):
    setup_school(client)
    shared=add(client,shared=[dict(promotion_id='p2',subject_id='s2')])
    kept=add(client,date='2027-01-05')
    row=next(r for r in schedule(client) if r['id']==shared['id'])
    assert row['source']=='bts' and row['is_shared'] and len(row['groups'])==2
    assert call(client,'/courses/'+row['id'],dict(version=row['version']),'DELETE').status_code==200
    assert [r['id'] for r in schedule(client)]==[kept['id']]
    with db() as conn:
        assert [c['id'] for c in _load_courses(conn,promotion_id='p1')]==[kept['id']]
        assert not _load_courses(conn,promotion_id='p2')
        assert not conn.execute('SELECT 1 FROM planning_course_groups WHERE course_id=?',(row['id'],)).fetchone()


def test_room_grid_stale_course_cannot_be_deleted(client):
    item=event(client,room_id='r1').json['course']
    row=schedule(client)[0]
    assert move(client,[row],'r2').status_code==200
    assert call(client,'/courses/'+row['id'],dict(version=row['version']),'DELETE').status_code==409
    current=schedule(client)[0]
    assert current['id']==item['id'] and current['room_id']=='r2'
    assert call(client,'/courses/'+current['id'],dict(version=current['version']),'DELETE').status_code==200
    assert not schedule(client)


def test_release_only_one_session_slot_and_survives_sync_then_can_be_reassigned(linked,client,db):
    source=seed(client,slots=[dict(room_id='r1',date=d,start='09:00',end='11:00') for d in ('2027-01-04','2027-01-05')],
        metadata=dict(name='APS JANVIER',formation='APS',start='2027-01-04',exam_dates=['2027-01-04'],assignment='initial'))
    row=schedule(client)[0]
    response=release(client,row)
    assert response.status_code==200,response.json
    assert response.headers['Cache-Control']=='no-store'
    after=schedule(client)
    assert len(after)==2 and after[0]['room_id'] is None and after[1]['room_id']=='r1'
    assert after[0]['exam'] and after[0]['date']==row['date'] and after[0]['start']==row['start']
    assert all(r['room_version']==row['room_version']+1 for r in after)
    with db() as conn:
        saved=conn.execute('SELECT slots FROM planning_room_owners WHERE owner=?',(source['owner'],)).fetchone()
        assert len(json.loads(saved['slots']))==2
    # A routine sync cannot recreate the room booking just removed.
    assert machine(client,'reconcile',dict(owners=[source],complete=True)).status_code==200
    assert schedule(client)==after
    data=client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10').json
    assert data['unassigned_sessions'][0]['count']==1
    assert release(client,row).status_code==409
    assert move(client,[after[0]],'r2').status_code==200
    assert [r['room_id'] for r in schedule(client)]==['r2','r1']


def test_released_room_is_free_for_other_bookings_but_other_session_slots_stay_reserved(linked,client):
    seed(client,slots=[dict(room_id='r1',date=d,start='09:00',end='11:00') for d in ('2027-01-04','2027-01-05')])
    assert release(client,schedule(client)[0]).status_code==200
    assert event(client,room_id='r1').status_code==200
    assert event(client,room_id='r1',date='2027-01-05').status_code==409


@pytest.mark.parametrize('changes,status',[(dict(confirm_release=False),400),(dict(confirm_release='true'),400),
    (dict(room_version=0),409),(dict(room_version=True),409),(dict(revision='stale'),409),
    (dict(key='missing'),409),(dict(date='2027-01-05'),409),(dict(date='invalid'),400),
    (dict(room_id='r2'),400)])
def test_release_rejects_invalid_or_stale_selection_without_changes(linked,client,changes,status):
    seed(client)
    before=schedule(client)
    row=before[0]
    payload={key:row[key] for key in ('key','date','revision','room_version')}
    payload.update(confirm_release=True);payload.update(changes)
    assert call(client,'/rooms/calendar-release',payload).status_code==status
    assert schedule(client)==before


def test_release_requires_admin_csrf_confirmation_ready_and_finished_session(linked,client,app,db):
    source=seed(client)
    row=schedule(client)[0]
    payload={key:row[key] for key in ('key','date','revision','room_version')}
    assert call(client,'/rooms/calendar-release',payload).status_code==400
    payload['confirm_release']=True
    path=BASE+'/rooms/calendar-release'
    assert app.test_client().post(path,json=payload).status_code==403
    assert client.post(path,json=payload).status_code==400
    with db() as conn:conn.execute("UPDATE planning_room_meta SET value='0' WHERE key='ready'")
    assert release(client,row).status_code==503
    with db() as conn:conn.execute("UPDATE planning_room_meta SET value='1' WHERE key='ready'")
    pending=dict(source,revision='2'*64,previous_revision=source['revision'])
    assert machine(client,'prepare',pending).status_code==200
    before=schedule(client)
    assert release(client,before[0]).status_code==409
    assert schedule(client)==before


def test_release_cannot_be_used_to_remove_a_local_course(client):
    event(client,room_id='r1')
    before=schedule(client)
    assert call(client,'/rooms/calendar-release',dict(key=before[0]['key'],date=before[0]['date'],revision='x',room_version=1,confirm_release=True)).status_code==409
    assert schedule(client)==before
