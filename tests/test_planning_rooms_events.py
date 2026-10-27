"""Events, annual limits, atomic room batches and the cross-platform ledger."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
import planning
import planning_rooms
from test_planning import db, app, client, call, BASE, setup_school, add, course, admin


def event(client, **changes):
    payload = dict(kind='event', promotion_id='p1', title='Réunion de rentrée', date='2027-01-04', start='09:00', end='10:00')
    payload.update(changes)
    return call(client, '/courses', payload)


def test_event_without_subject_trainer_calendar_or_room(client, db):
    response = event(client)
    assert response.status_code == 200, response.json
    c = response.json['course']
    assert c['kind'] == 'event' and c['subject_id'] == '' and c['trainer_id'] == ''
    assert c['subject_name'] == 'Réunion de rentrée' and not c['warnings']
    with db() as conn:
        assert all(s['scheduled_minutes'] == 0 for s in planning._subjects(conn, 'p1'))
    edited = call(client, '/courses/'+c['id'], dict(version=c['version'], title='Accueil'), 'PUT')
    assert edited.status_code == 200 and edited.json['course']['title'] == 'Accueil'
    assert call(client, '/courses/'+c['id'], dict(version=edited.json['course']['version']), 'DELETE').status_code == 200


def test_event_reserves_promotion_room_and_trainer(client):
    setup_school(client)
    assert event(client, room_id='r1', trainer_id='t1').status_code == 200
    assert event(client).status_code == 409
    assert event(client, promotion_id='p2', room_id='r1').status_code == 409
    assert event(client, promotion_id='p2', trainer_id='t1').status_code == 409
    assert event(client, promotion_id='p2', room_id='r2').status_code == 200


def test_event_bounds_and_type_cannot_bypass_subject_budget(client, db):
    setup_school(client)
    c = add(client)
    assert call(client, '/courses/'+c['id'], dict(kind='event', version=1), 'PUT').status_code == 400
    assert event(client, date='2026-12-31').status_code == 409
    assert event(client, trainer_id='unassigned', start='12:00', end='13:00').status_code == 400
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=2 WHERE id='s1'")
    assert call(client, '/courses', course(date='2027-01-05')).status_code == 409
    assert event(client, date='2027-01-05').status_code == 200
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=1 WHERE id='s1'")
        s = next(s for s in planning._subjects(conn, 'p1') if s['id']=='s1')
        assert s['remaining_minutes'] == -60 and s['over_budget']


def bulk(courses, **changes):
    payload = dict(promotion_id='p1', room_id='r2', courses=[dict(id=c['id'], version=c['version']) for c in courses])
    payload.update(changes)
    return payload


def test_bulk_updates_all_selected_once_without_touching_times(client, db):
    setup_school(client)
    a, b = add(client), add(client, date='2027-01-05')
    preview = call(client, '/rooms/bulk-preview', bulk([a,b]))
    assert preview.status_code == 200, preview.json
    assert preview.json['count'] == 2
    result = call(client, '/rooms/bulk-commit', dict(token=preview.json['token']))
    assert result.status_code == 200
    with db() as conn:
        rows = planning._load_courses(conn)
        assert {c['room_id'] for c in rows} == {'r2'}
        assert {c['version'] for c in rows} == {2}
        assert {c['start'] for c in rows} == {'09:00'}
    assert call(client, '/rooms/bulk-commit', dict(token=preview.json['token'])).status_code == 409


def test_bulk_conflict_or_stale_preview_leaves_every_course_unchanged(client, db):
    setup_school(client)
    a, b = add(client), add(client, date='2027-01-05')
    preview = call(client, '/rooms/bulk-preview', bulk([a,b])).json
    add(client, pid='p2', sid='s4', room_id='r2', date='2027-01-05')
    response = call(client, '/rooms/bulk-commit', dict(token=preview['token']))
    assert response.status_code == 409
    with db() as conn:
        assert all(c['room_id']=='r1' and c['version']==1 for c in planning._load_courses(conn, promotion_id='p1'))


def test_bulk_selected_collisions_and_csrf(client, app):
    a = event(client, room_id='r1').json['course']
    b = event(client, promotion_id='p2', room_id='r2').json['course']
    assert call(client, '/rooms/bulk-preview', bulk([a,b])).status_code == 409
    assert app.test_client().post(BASE+'/rooms/bulk-preview', json=bulk([a])).status_code == 403
    preview = call(client, '/rooms/bulk-preview', bulk([a], room_id='r1')).json
    assert call(admin(app, 'another'), '/rooms/bulk-commit', dict(token=preview['token'])).status_code == 400


def reservation(owner='session:one', revision='1', room='r1', **changes):
    item = dict(owner=owner, revision=revision*64, previous_revision='0'*64, title='APS · session',
                slots=[dict(room_id=room, date='2027-01-04', start='09:00', end='11:00')])
    item.update(changes)
    return item


def machine(client, action, data):
    return client.post('/internal/rooms/'+action, json=data, headers={'Authorization':'Bearer room-test'})


@pytest.fixture
def linked(monkeypatch, client):
    monkeypatch.setenv('SHARED_ROOMS_TOKEN', 'room-test')
    monkeypatch.setenv('SESSION_ROOMS_URL', 'https://sessions.example.test')
    assert machine(client, 'bootstrap', dict(owners=[])).status_code == 200


def test_link_initialization_and_machine_auth(monkeypatch, client):
    monkeypatch.setenv('SHARED_ROOMS_TOKEN', 'room-test')
    monkeypatch.setenv('SESSION_ROOMS_URL', 'https://sessions.example.test')
    assert event(client, room_id='r1').status_code == 409
    assert client.post('/internal/rooms/bootstrap', json={'owners':[]}).status_code == 403
    assert machine(client, 'bootstrap', dict(owners=[])).status_code == 200
    assert machine(client, 'bootstrap', dict(owners=[])).status_code == 409
    assert event(client, room_id='r1').status_code == 200


def test_bts_and_sessions_mutually_exclusive_and_adjacent_allowed(linked, client):
    prepared = machine(client, 'prepare', reservation())
    assert prepared.status_code == 200, prepared.json
    assert event(client, room_id='r1').status_code == 409
    assert event(client, room_id='r1', start='11:00', end='12:00').status_code == 200
    assert machine(client, 'prepare', reservation(owner='session:two')).status_code == 409
    assert machine(client, 'finish', dict(token=prepared.json['token'], commit=True)).status_code == 200
    assert call(client, '/rooms/r1', {}, 'DELETE').status_code == 409
    assert call(client, '/rooms/r1', dict(active=False), 'PUT').status_code == 409


def test_move_holds_both_rooms_and_reconciles_from_durable_source(linked, client, db):
    first = machine(client, 'prepare', reservation()).json['token']
    machine(client, 'finish', dict(token=first, commit=True))
    second = machine(client, 'prepare', reservation(revision='2', room='r2', previous_revision='1'*64)).json['token']
    assert event(client, room_id='r1').status_code == 409
    assert event(client, room_id='r2').status_code == 409
    # Simulate a successful source save followed by loss of the final response.
    assert machine(client, 'reconcile', dict(owners=[reservation(revision='2', room='r2')])).status_code == 200
    assert event(client, room_id='r1').status_code == 200
    with db() as conn:
        slots = planning_rooms.external_slots(conn)
        assert {s['room_id'] for s in slots} == {'r2'} and not any(s['pending'] for s in slots)
    assert machine(client, 'finish', dict(token=second, commit=True)).status_code == 200


def test_aborted_source_save_releases_only_new_holds(linked, client, db):
    first = machine(client, 'prepare', reservation()).json['token']
    machine(client, 'finish', dict(token=first, commit=True))
    machine(client, 'prepare', reservation(revision='2', room='r2', previous_revision='1'*64))
    machine(client, 'reconcile', dict(owners=[reservation()]))
    assert event(client, room_id='r1').status_code == 409
    assert event(client, room_id='r2').status_code == 200


def test_simultaneous_reservations_have_exactly_one_winner(linked, app):
    gate = Barrier(2)
    def reserve(owner):
        c = app.test_client(); gate.wait()
        return machine(c, 'prepare', reservation(owner=owner)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, ['session:a','session:b'])) == [200,409]


def test_calendar_displays_legacy_conflicts_without_erasing_bookings(client, monkeypatch):
    assert event(client, room_id='r1').status_code == 200
    monkeypatch.setenv('SHARED_ROOMS_TOKEN','room-test')
    monkeypatch.setenv('SESSION_ROOMS_URL','https://sessions.example.test')
    assert machine(client, 'bootstrap', dict(owners=[reservation()])).status_code == 200
    result = client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10')
    assert result.status_code == 200
    assert len(result.json['rooms']) == 2
    assert len(result.json['reservations']) == 2
    assert all(r['conflict'] for r in result.json['reservations'])


def test_week_duplication_keeps_one_off_events_only_in_source_week(client):
    setup_school(client)
    add(client)
    assert event(client,start='14:00',end='15:00').status_code==200
    result=call(client,'/courses/preview',dict(promotion_id='p1',mode='weeks',source_start='2027-01-04',target_weeks=['2027-01-11']))
    assert result.status_code==200,result.json
    assert len(result.json['items'])==1 and result.json['items'][0]['course']['kind']=='course'
    response=call(client,'/courses/batch',dict(preview_token=result.json['preview_token'],selected_keys=['0']))
    assert response.status_code==200,response.json


def test_bts_and_session_race_has_one_winner(linked,app):
    gate=Barrier(2)
    def writer(index):
        c=admin(app);gate.wait()
        return (event(c,room_id='r1') if index==0 else machine(c,'prepare',reservation())).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(writer,[0,1]))==[200,409]


def test_renamed_room_keeps_external_alias(linked,client):
    assert call(client,'/rooms/r1',dict(name='Salle Méditerranée'),'PUT').status_code==200
    item=reservation();item['slots'][0].pop('room_id');item['slots'][0]['room_name']='Salle r1'
    assert machine(client,'prepare',item).status_code==200
    assert event(client,room_id='r1').status_code==409


def test_deleted_source_recovers_pending_release(linked,client,db):
    first=machine(client,'prepare',reservation()).json['token']
    machine(client,'finish',dict(token=first,commit=True))
    machine(client,'prepare',reservation(revision='2',previous_revision='1'*64,slots=[]))
    assert event(client,room_id='r1').status_code==409
    machine(client,'reconcile',dict(owners=[],complete=True))
    assert event(client,room_id='r1').status_code==200


def test_request_cache_observes_other_writer_and_own_changes(linked,app,client,db):
    first=machine(client,'prepare',reservation()).json['token']
    machine(client,'finish',dict(token=first,commit=True))
    with app.test_request_context(),db() as conn:
        reads=[]
        conn.set_trace_callback(lambda sql:reads.append(sql) if sql=='SELECT * FROM planning_room_owners' else None)
        assert {s['room_id'] for s in planning_rooms.external_slots(conn)}=={'r1'}
        assert planning_rooms.external_slots(conn,room_day=('r2','2027-01-04'))==[]
        assert len(reads)==1
        with db() as other:
            row=other.execute('SELECT slots FROM planning_room_owners').fetchone()
            slots=json.loads(row['slots']);slots[0]['room_id']='r2'
            other.execute('UPDATE planning_room_owners SET slots=?',(json.dumps(slots),))
        assert planning_rooms.external_slots(conn,room_day=('r1','2027-01-04'))==[]
        assert len(planning_rooms.external_slots(conn,room_day=('r2','2027-01-04')))==1
        assert len(reads)==2
        conn.execute("UPDATE planning_room_owners SET slots='[]'")
        assert planning_rooms.external_slots(conn)==[]
        assert len(reads)==3
