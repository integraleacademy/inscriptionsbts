"""Room choices use the same reservations as course writes, at exact times."""
import json

import pytest

from test_planning import db, app, client, BASE, setup_school, add, call, course
from test_planning_rooms_events import bulk, event


def available(client, **changes):
    return client.get(BASE + '/rooms/available', query_string=dict(
        dict(date='2027-01-04', start='09:00', end='11:00'), **changes))


def room_ids(response):
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'no-store'
    return [room['id'] for room in response.json['rooms']]


def test_only_free_active_rooms_across_promotions(client, db):
    setup_school(client)
    add(client, pid='p2', sid='s4', trainer_id='t2', room_id='r1')
    with db() as conn:
        conn.execute("INSERT INTO planning_rooms VALUES('inactive','Ancienne salle',0)")
    assert room_ids(available(client)) == ['r2']
    assert room_ids(available(client, date='2027-01-05')) == ['r1', 'r2']


def test_shared_course_does_not_reserve_its_room_against_itself(client):
    setup_school(client)
    existing = add(client, shared=[dict(promotion_id='p2', subject_id='s2')])
    assert room_ids(available(client)) == ['r2']
    assert room_ids(available(client, exclude_course_id=existing['id'])) == ['r1', 'r2']
    assert room_ids(available(client, exclude_course_id=existing['id'], start='10:00', end='12:00')) == ['r1', 'r2']


@pytest.mark.parametrize('start,end,occupied', [
    ('08:00','09:00',False), ('11:00','12:00',False),
    ('08:00','09:01',True), ('10:59','12:00',True), ('09:30','10:00',True),
])
def test_exact_overlaps_and_adjacent_slots(client, start, end, occupied):
    setup_school(client)
    add(client)
    ids = room_ids(available(client, start=start, end=end))
    assert ('r1' not in ids) == occupied


@pytest.mark.parametrize('source', ['session', 'pending_session', 'reservation', 'closure'])
def test_all_room_reservation_sources_are_respected(client, db, source):
    with db() as conn:
        if source in ('session', 'pending_session'):
            slots = json.dumps([dict(room_id='r1', date='2027-01-04', start_min=540, end_min=660)])
            conn.execute('''INSERT INTO planning_room_owners(owner,revision,slots,pending_slots,title,url)
                VALUES('session:example','1',?,?,'Session','')''',
                         (slots if source == 'session' else '[]', slots if source == 'pending_session' else None))
        if source == 'reservation':
            conn.execute("INSERT INTO planning_room_reservations VALUES('exam','r1','2027-01-04',540,660,'Examen',1,1,'now','now')")
        if source == 'closure':
            conn.execute("INSERT INTO planning_room_unavailability VALUES('closed','r1','2027-01-04','2027-01-05',540,660,'Travaux',1)")
    assert room_ids(available(client)) == ['r2']
    assert room_ids(available(client, start='11:00', end='12:00')) == ['r1', 'r2']


def test_room_choices_do_not_require_a_prepared_subject_or_school_day(client, db):
    with db() as conn:
        conn.execute('UPDATE planning_subjects SET planned_hours=0')
    assert room_ids(available(client)) == ['r1', 'r2']


def test_end_at_midnight_and_all_rooms_busy(client, db):
    with db() as conn:
        for rid in ('r1', 'r2'):
            conn.execute('INSERT INTO planning_room_reservations VALUES(?,?,?,?,?,?,0,1,?,?)',
                         (rid, rid, '2027-01-04', 23*60, 1440, 'Réservation', 'now', 'now'))
    assert room_ids(available(client, start='22:00', end='24:00')) == []
    assert room_ids(available(client, start='22:00', end='23:00')) == ['r1', 'r2']


def test_selected_room_is_revalidated_when_saving(client):
    setup_school(client)
    assert room_ids(available(client)) == ['r1', 'r2']
    add(client, pid='p2', sid='s4', trainer_id='t2', room_id='r1')
    response = call(client, '/courses', course(room_id='r1'))
    assert response.status_code == 409
    assert any(c['type'] == 'room_overlap' for c in response.json['conflicts'])


@pytest.mark.parametrize('query', [dict(date='2027-02-30'), dict(start='24:00'), dict(end='25:00'),
                                   dict(start='11:00',end='09:00'), dict(start=''), dict(end='09:00')])
def test_invalid_slots_do_not_return_room_choices(client, query):
    assert available(client, **query).status_code == 400


def test_permissions_deleted_courses_and_uninitialized_sync(app, client, monkeypatch):
    assert available(app.test_client()).status_code == 403
    assert available(client, exclude_course_id='deleted').status_code == 404
    monkeypatch.setenv('SHARED_ROOMS_TOKEN', 'room-test')
    monkeypatch.setenv('SESSION_ROOMS_URL', 'https://sessions.example.test')
    response = available(client)
    assert response.status_code == 503 and 'rooms' not in response.json


def batch_choices(client, courses, **changes):
    return call(client, '/rooms/bulk-available', bulk(courses, **changes))


def test_bulk_choices_intersect_every_selected_date_and_do_not_change_courses(client, db):
    setup_school(client)
    first = add(client, room_id=None)
    second = add(client, room_id=None, date='2027-01-05')
    add(client, pid='p2', sid='s4', room_id='r1', date='2027-01-05')
    with db() as conn:
        conn.execute("INSERT INTO planning_rooms VALUES('inactive','Ancienne salle',0)")
    assert room_ids(batch_choices(client, [first, second])) == ['r2']
    assert room_ids(batch_choices(client, [first])) == ['r1', 'r2']
    assert room_ids(batch_choices(client, [second])) == ['r2']
    with db() as conn:
        assert [tuple(c) for c in conn.execute("SELECT room_id,version FROM planning_courses WHERE promotion_id='p1'")] == [(None,1),(None,1)]


def test_bulk_choices_can_be_empty_even_when_each_slot_has_a_free_room(client):
    setup_school(client)
    first = add(client, room_id=None)
    second = add(client, room_id=None, date='2027-01-05')
    add(client, pid='p2', sid='s4', room_id='r1')
    add(client, pid='p2', sid='s4', room_id='r2', date='2027-01-05')
    assert room_ids(batch_choices(client, [first, second])) == []
    assert room_ids(batch_choices(client, [first])) == ['r2']
    assert room_ids(batch_choices(client, [second])) == ['r1']


def test_bulk_shared_course_excludes_one_physical_booking_from_secondary_promotion(client):
    setup_school(client)
    shared = add(client, shared=[dict(promotion_id='p2',subject_id='s2')])
    assert room_ids(batch_choices(client, [shared], promotion_id='p2', period_id='p2:1')) == ['r1','r2']
    preview = call(client, '/rooms/bulk-preview', bulk([shared], promotion_id='p2', period_id='p2:1', room_id='r1'))
    assert preview.status_code == 200 and preview.json['shared'] == 1


def test_bulk_overlapping_selected_events_cannot_share_any_room(client, db):
    first = event(client, room_id='r1').json['course']
    second = event(client, start='11:00', end='12:00', room_id='r2').json['course']
    assert room_ids(batch_choices(client, [first, second])) == ['r1','r2']
    with db() as conn:
        conn.execute('UPDATE planning_courses SET start_min=599 WHERE id=?', (second['id'],))
    assert room_ids(batch_choices(client, [first, second])) == []
    assert call(client, '/rooms/bulk-preview', bulk([first,second])).status_code == 409


@pytest.mark.parametrize('source', ['session', 'pending_session', 'reservation', 'closure'])
def test_bulk_choices_check_external_bookings_on_later_selected_dates(client, db, source):
    first = event(client).json['course']
    second = event(client, date='2027-01-05').json['course']
    with db() as conn:
        if source in ('session', 'pending_session'):
            slots = json.dumps([dict(room_id='r1', date='2027-01-05', start_min=540, end_min=660)])
            conn.execute('''INSERT INTO planning_room_owners(owner,revision,slots,pending_slots,title,url)
                VALUES('session:example','1',?,?,'Session','')''',
                         (slots if source == 'session' else '[]', slots if source == 'pending_session' else None))
        if source == 'reservation':
            conn.execute("INSERT INTO planning_room_reservations VALUES('exam','r1','2027-01-05',540,660,'Examen',1,1,'now','now')")
        if source == 'closure':
            conn.execute("INSERT INTO planning_room_unavailability VALUES('closed','r1','2027-01-05','2027-01-06',540,660,'Travaux',1)")
    assert room_ids(batch_choices(client, [first, second])) == ['r2']
    assert room_ids(batch_choices(client, [first])) == ['r1','r2']


def test_bulk_choices_cannot_authorize_a_newly_occupied_room(client, db):
    setup_school(client)
    first = add(client, room_id=None)
    second = add(client, room_id=None, date='2027-01-05')
    assert room_ids(batch_choices(client, [first,second])) == ['r1','r2']
    preview = call(client, '/rooms/bulk-preview', bulk([first,second], room_id='r1')).json
    add(client, pid='p2', sid='s4', room_id='r1', date='2027-01-05')
    saved = call(client, '/rooms/bulk-commit', dict(token=preview['token']))
    assert saved.status_code == 409
    assert room_ids(batch_choices(client, [first,second])) == ['r2']
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM planning_courses WHERE promotion_id='p1' AND room_id IS NOT NULL").fetchone()[0] == 0


def test_bulk_choices_validate_selection_scope_versions_and_permissions(client, app, db, monkeypatch):
    current = event(client).json['course']
    assert batch_choices(client, []).status_code == 400
    assert batch_choices(client, [current,current]).status_code == 400
    assert batch_choices(client, [dict(current,version=99)]).status_code == 409
    assert batch_choices(client, [current], promotion_id='p2').status_code == 409
    assert batch_choices(app.test_client(), [current]).status_code == 403
    assert client.post(BASE+'/rooms/bulk-available', json=bulk([current])).status_code == 400
    with db() as conn:
        conn.execute("UPDATE promotions SET date_fin='2028-03-31' WHERE id='p1'")
    assert batch_choices(client, [current], period_id='p1:2').status_code == 400
    monkeypatch.setenv('SHARED_ROOMS_TOKEN','room-test')
    monkeypatch.setenv('SESSION_ROOMS_URL','https://sessions.example.test')
    assert batch_choices(client, [current]).status_code == 503
