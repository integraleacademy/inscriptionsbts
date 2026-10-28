"""Free room bookings share the same locks and conflict rules as BTS/sessions."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

import pytest
from pypdf import PdfReader
from test_planning import db, app, client, call, BASE, admin
from test_planning_rooms_events import event, reservation, machine, linked, bulk
from test_room_calendar import seed, schedule, move, block


def reserve(client,**changes):
    data=dict(room_id='r2',date='2027-01-04',start='09:00',end='11:00',title='Examen VTC',exam=True)
    data.update(changes)
    return call(client,'/rooms/reservations',data)


def edit(client,row,**changes):
    data={k:row[k] for k in ('room_id','date','title','exam','version')}
    data.update(start='09:00',end='11:00');data.update(changes)
    return call(client,'/rooms/reservations/'+row['id'],data,'PUT')


def test_free_reservation_needs_no_promotion_and_can_be_edited_deleted(client,db):
    response=reserve(client)
    assert response.status_code==200,response.json
    row=response.json['reservation']
    assert row['source']=='reservation' and row['formation']=='OTHER' and row['exam'] is True
    assert schedule(client)[0]['title']=='Examen VTC'
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM planning_room_reservations').fetchone()[0]==1
    assert edit(client,row,title='Réunion VTC',exam=False,room_id='r1',date='2027-01-05',start='10:00',end='12:00').status_code==200
    assert edit(client,row,title='Écriture périmée').status_code==409
    saved=schedule(client)[0]
    assert (saved['room_id'],saved['date'],saved['start'],saved['end'],saved['exam'],saved['version'])==('r1','2027-01-05','10:00','12:00',False,2)
    path='/rooms/reservations/'+row['id']
    assert call(client,path,dict(version=1),'DELETE').status_code==409
    assert call(client,path,dict(version=2),'DELETE').status_code==200
    assert schedule(client)==[]
    assert call(client,path,dict(version=2),'DELETE').status_code==404


@pytest.mark.parametrize('bad',[dict(title=''),dict(title=' '*5),dict(title='x'*201),dict(title=[]),dict(exam='true'),
    dict(date='2027-02-30'),dict(start='25:00'),dict(start='11:00',end='10:00'),dict(end='09:00'),dict(room_id='missing'),dict(room_id=None)])
def test_free_reservation_validation(client,bad):
    assert reserve(client,**bad).status_code==400
    assert schedule(client)==[]


def test_all_day_and_midnight_reservations_keep_exact_minutes(client):
    assert reserve(client,start='00:00',end='24:00').status_code==200
    assert reserve(client,start='23:59',end='24:00').status_code==409
    assert reserve(client,date='2027-01-05',start='23:00',end='24:00').status_code==200
    assert [(r['start_min'],r['end_min']) for r in schedule(client)]==[(0,1440),(1380,1440)]


def test_reservations_conflict_with_courses_sessions_blocks_and_each_other(linked,client):
    seed(client,room='r1')
    assert reserve(client,room_id='r1').status_code==409
    assert event(client,room_id='r2').status_code==200
    assert reserve(client).status_code==409
    assert reserve(client,start='10:00',end='11:00').status_code==200  # adjacency is available
    assert reserve(client,start='10:59',end='12:00').status_code==409
    assert block(client,start_date='2027-01-05',end_date='2027-01-05').status_code==200
    assert reserve(client,date='2027-01-05').status_code==409


def test_booking_blocks_all_other_assignment_paths_and_room_deletion(linked,client):
    row=reserve(client).json['reservation']
    assert event(client,room_id='r2').status_code==409
    course=event(client,room_id='r1').json['course']
    assert call(client,'/rooms/courses/'+course['id']+'/assign',dict(version=1,room_id='r2')).status_code==409
    assert call(client,'/rooms/bulk-preview',bulk([course])).status_code==409
    assert move(client,[r for r in schedule(client) if r['source']=='event']).status_code==409
    assert machine(client,'prepare',reservation(room='r2')).status_code==409
    assert block(client).status_code==409
    assert call(client,'/rooms/r2',dict(active=False),'PUT').status_code==409
    assert call(client,'/rooms/r2',{},'DELETE').status_code==409
    assert call(client,'/rooms/reservations/'+row['id'],dict(version=1),'DELETE').status_code==200
    assert call(client,'/rooms/r2',dict(active=False),'PUT').status_code==200
    assert reserve(client).status_code==400


def test_mixed_drag_moves_free_booking_and_exam_with_other_sources_atomically(linked,client):
    seed(client,room='r1')
    event(client,room_id='r1',start='12:00',end='13:00')
    free=reserve(client,room_id='r1',date='2027-01-05').json['reservation']
    rows=schedule(client)
    block(client,start_date='2027-01-05',end_date='2027-01-05')
    assert move(client,rows).status_code==409
    assert {r['room_id'] for r in schedule(client) if r['source']!='unavailable'}=={'r1'}
    closure=next(r for r in schedule(client) if r['source']=='unavailable')
    call(client,'/rooms/unavailability/'+closure['id'],dict(version=1),'DELETE')
    assert move(client,rows).status_code==200
    assert {r['room_id'] for r in schedule(client)}=={'r2'}
    saved=next(r for r in schedule(client) if r['key']==free['key'])
    assert saved['exam'] and saved['version']==2 and saved['date']=='2027-01-05' and saved['start']=='09:00'
    assert edit(client,free).status_code==409


@pytest.mark.parametrize('competitor',['booking','session','course'])
def test_parallel_writers_cannot_double_book_room(linked,app,competitor):
    gate=Barrier(2)
    def write(n):
        client=admin(app);gate.wait()
        if n==0 or competitor=='booking':return reserve(client).status_code
        if competitor=='session':return machine(client,'prepare',reservation(room='r2')).status_code
        return event(client,room_id='r2').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(write,[0,1]))==[200,409]


def test_failed_edit_keeps_booking_and_free_bookings_are_in_pdf(client):
    free=reserve(client).json['reservation']
    event(client,room_id='r1')
    assert edit(client,free,room_id='r1').status_code==409
    assert next(r for r in schedule(client) if r['source']=='reservation')['room_id']=='r2'
    pdf=client.get('/admin/salles/export.pdf?start=2027-01-04&end=2027-01-04')
    assert pdf.status_code==200
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.data)).pages)
    assert all(s in text for s in ['Examen VTC','EXAMEN','04/01/2027','Autre créneau'])


def test_new_endpoints_require_admin_csrf_and_initialized_room_sync(app,client,monkeypatch):
    for path,method in [('/rooms/reservations','POST'),('/rooms/reservations/missing','PUT'),('/rooms/reservations/missing','DELETE')]:
        assert app.test_client().open(BASE+path,method=method,json={}).status_code==403
        assert client.open(BASE+path,method=method,json={}).status_code==400
    monkeypatch.setenv('SHARED_ROOMS_TOKEN','room-test');monkeypatch.setenv('SESSION_ROOMS_URL','https://sessions.example.test')
    assert reserve(client).status_code==503
