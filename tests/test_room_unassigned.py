"""Actual sessions without rooms remain visible and can be assigned atomically."""
from copy import deepcopy
from io import BytesIO

from pypdf import PdfReader
import pytest
from test_planning import db, app, client, call, BASE
from test_planning_rooms_events import linked, machine, event, reservation
from test_room_calendar import seed, schedule, move


def projection(**changes):
    item=reservation(schema=3,revision='3',compat_revision='1'*64,legacy_revision='0'*64,
        slots=[dict(room_id=None,date=d,start='09:00',end='11:00') for d in ('2027-01-04','2027-01-05')],
        metadata=dict(name='APS JANVIER 2027',formation='APS',start='2027-01-04',needs_schedule=False,exam_dates=['2027-01-05']))
    item.update(changes)
    return item


def sync(client,items):
    result=machine(client,'reconcile',dict(owners=items,complete=True))
    assert result.status_code==200,result.json
    return result.json


def calendar(client):
    return client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10').json


def test_unassigned_sessions_and_bts_are_first_without_reserving_physical_rooms(linked,client):
    p=projection();sync(client,[p])
    event(client,room_id=None,date='2027-01-06')
    data=calendar(client)
    assert data['rooms'][0]==dict(id=None,name='À affecter',active=True,unassigned=True)
    assert data['unassigned_count']==3
    assert data['unassigned_sessions']==[dict(owner=p['owner'],name='APS JANVIER 2027',start='2027-01-04',needs_schedule=False,count=2)]
    rows=[r for r in data['reservations'] if r['source']=='session']
    assert len(rows)==2 and all(r['title']=='APS JANVIER 2027' and r['formation']=='APS' and not r.get('conflict') for r in rows)
    assert next(r for r in rows if r['date']=='2027-01-05')['exam']
    assert event(client,room_id='r1').status_code==200
    assert event(client,promotion_id='p2',room_id='r2').status_code==200


def test_assign_unassigned_group_updates_effective_counts_and_keeps_dates(linked,client):
    p=projection();sync(client,[p]);before=schedule(client)
    expected={r['key']:(r['date'],r['start'],r['end'],r['exam']) for r in before}
    assert move(client,before,'r1').status_code==200
    assert sync(client,[p])['assignments'][p['owner']]==dict(total=2,unassigned=0)
    after=schedule(client)
    assert len(after)==2 and all(r['room_id']=='r1' for r in after)
    assert {r['key']:(r['date'],r['start'],r['end'],r['exam']) for r in after}==expected
    assert not calendar(client)['unassigned_sessions']
    assert all(r['id'] for r in calendar(client)['rooms'])
    assert move(client,before,'r2').status_code==409
    assert event(client,room_id='r1').status_code==409


def test_partial_assignment_stays_visible_and_batch_conflict_leaves_every_slot(linked,client):
    p=projection();sync(client,[p]);rows=schedule(client)
    assert event(client,room_id='r1',date='2027-01-05').status_code==200
    assert move(client,rows,'r1').status_code==409
    assert all(not r['room_id'] for r in schedule(client) if r['source']=='session')
    assert move(client,[rows[0]],'r2').status_code==200
    assert sync(client,[p])['assignments'][p['owner']]==dict(total=2,unassigned=1)
    assert calendar(client)['unassigned_sessions'][0]['count']==1


def test_exact_v2_upgrade_keeps_existing_overrides_and_is_idempotent(linked,client):
    old=seed(client,metadata=dict(name='APS JANVIER 2027',formation='APS',start='2027-01-04'))
    assert move(client,schedule(client),'r2').status_code==200
    p=projection(slots=old['slots']+[dict(room_id=None,date='2027-01-05',start='09:00',end='11:00')])
    mismatch=deepcopy(p);mismatch['compat_revision']='a'*64
    sync(client,[mismatch]);assert len(schedule(client))==1
    sync(client,[p]);rows=schedule(client)
    assert len(rows)==2
    assert {r['date']:r['room_id'] for r in rows}=={'2027-01-04':'r2','2027-01-05':None}
    assert sync(client,[p])['assignments'][p['owner']]==dict(total=2,unassigned=1)
    assert schedule(client)==rows


def test_saved_v2_pending_revision_can_upgrade_without_losing_held_room(linked,client):
    seed(client)
    pending=reservation(revision='2',room='r2',previous_revision='1'*64)
    assert machine(client,'prepare',pending).status_code==200
    p=projection(compat_revision='2'*64,slots=pending['slots']+[dict(room_id=None,date='2027-01-05',start='09:00',end='11:00')])
    sync(client,[p]);rows=schedule(client)
    assert len(rows)==2 and not any(r['pending'] for r in rows)
    assert {r['date']:r['room_id'] for r in rows}=={'2027-01-04':'r2','2027-01-05':None}


@pytest.mark.parametrize('fields',[{},dict(room_id='missing'),dict(room_id=''),dict(room_name='Unknown room')])
def test_only_explicit_null_schema3_is_unassigned(linked,client,fields):
    p=projection(slots=[dict(date='2027-01-04',start='09:00',end='11:00',**fields)])
    assert machine(client,'prepare',p).status_code==400
    p['slots'][0]={'date':'2027-01-04','start':'09:00','end':'11:00','room_id':None}
    p['schema']=2
    assert machine(client,'prepare',p).status_code==400
    p['schema']=3
    assert machine(client,'prepare',p).status_code==200


def test_missing_timetable_is_listed_but_never_invents_slots_and_deleted_is_excluded(linked,client,monkeypatch):
    items=[projection(owner='session:'+key,slots=[],metadata=dict(name=key,start=start,needs_schedule=True,deleted=deleted))
           for key,start,deleted in [('future','2027-02-01',False),('old','2026-10-25',False),('deleted','2027-02-01',True),('undated',None,False)]]
    sync(client,items);data=calendar(client)
    assert not data['reservations']
    assert {s['owner'] for s in data['unassigned_sessions']}=={'session:future','session:undated'}
    import planning_rooms
    monkeypatch.setattr(planning_rooms,'remote',lambda *a:dict(sessions=[dict(owner='session:undated',needs_schedule=True)]))
    assert client.get(BASE+'/rooms/sessions').json['sessions']==[dict(owner='session:undated',needs_schedule=True)]


def test_unassigned_override_survives_source_edit_but_global_assignment_resets(linked,client):
    p=projection();sync(client,[p]);move(client,schedule(client),'r1')
    update=deepcopy(p);update.update(revision='4'*64,previous_revision=p['revision']);update['metadata']['name']='APS nouveau nom'
    token=machine(client,'prepare',update).json['token'];machine(client,'finish',dict(token=token,commit=True))
    assert all(r['room_id']=='r1' and r['title']=='APS nouveau nom' for r in schedule(client))
    update.update(revision='5'*64,previous_revision='4'*64);update['metadata']['assignment']='new-global-assignment'
    for slot in update['slots']:slot['room_id']='r2'
    token=machine(client,'prepare',update).json['token'];machine(client,'finish',dict(token=token,commit=True))
    assert all(r['room_id']=='r2' for r in schedule(client))


def test_pdf_includes_unassigned_row_and_exams(linked,client):
    sync(client,[projection()])
    result=client.get('/admin/salles/export.pdf?start=2027-01-04&end=2027-01-10')
    assert result.status_code==200
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(result.data)).pages)
    assert all(s in text for s in ('À affecter','À AFFECTER','APS JANVIER 2027','EXAMEN','05/01/2027'))
