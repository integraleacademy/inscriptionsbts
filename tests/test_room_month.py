"""The monthly calendar uses real bookings and remains available without the chat."""
from test_planning import BASE, add, app, call, client, db, setup_school
from test_planning_rooms_events import linked
from test_room_calendar import block, seed
from test_room_reservations import reserve


def month(client, **extra):
    params = {'from': '2027-01-01', 'to': '2027-01-31', **extra}
    return client.get(BASE + '/rooms/disponibilites', query_string=params)


def test_month_combines_all_sources_and_only_counts_physical_active_rooms_as_free(client, linked, db):
    setup_school(client)
    add(client, start='08:00', end='10:00')
    reserve(client, room_id='r1', start='10:00', end='12:15')
    seed(client, slots=[dict(room_id='r1', date='2027-01-04', start='13:00', end='15:00')])
    block(client, room_id='r1', start='16:00', end='18:30')
    with db() as conn:
        conn.execute("INSERT INTO planning_rooms VALUES('r3','Salle inactive',0)")
        conn.execute("INSERT INTO planning_rooms VALUES('r4','Salle à définir',1)")
    data = month(client).json
    rooms = {r['id']: r for r in data['rooms']}
    assert 'r4' not in rooms
    assert '2027-01-02' not in data['dates']
    assert rooms['r1']['days']['2027-01-04'] == dict(state='partial', free=[['12:15','13:00'], ['15:00','16:00']])
    assert rooms['r2']['free_days'] == len(data['dates']) and rooms['r3']['free_days'] == 0
    narrow = {r['id']: r for r in month(client, start='10:00', end='12:00').json['rooms']}
    assert narrow['r1']['days']['2027-01-04']['state'] == 'busy' and narrow['r2']['days']['2027-01-04']['state'] == 'free'
    feb = month(client, **{'from':'2028-02-01', 'to':'2028-02-29', 'weekdays':'0,1,2,3,4,5,6'})
    assert feb.status_code == 200 and len(feb.json['dates']) == 29
    assert month(client, weekdays='7').status_code == 400
    assert month(client, start='19:00', end='09:00').status_code == 400
    assert month(client, **{'to':'9999-12-31'}).status_code == 400


def test_month_requires_admin_and_a_synchronized_ledger(client, app, monkeypatch):
    assert month(app.test_client()).status_code == 403
    monkeypatch.setenv('SHARED_ROOMS_TOKEN', 'test')
    monkeypatch.setenv('SESSION_ROOMS_URL', 'https://sessions.example.test')
    assert month(client).status_code == 503


def test_open_ended_closure_can_be_shortened_in_the_calendar(client):
    assert block(client, room_id='r1', start_date='2027-01-01', no_end=True).status_code == 200
    saved = client.get(BASE+'/rooms/schedule?start=2028-01-04&end=2028-01-04').json['reservations'][0]
    assert reserve(client, room_id='r1', date='2028-01-04').status_code == 409
    edited = call(client, '/rooms/unavailability/'+saved['id'], dict(room_id='r1', version=saved['version'],
                  start_date='2027-01-01', end_date='2027-03-10', reason='Travaux'), 'PUT')
    assert edited.status_code == 200
    assert reserve(client, room_id='r1', date='2028-01-04').status_code == 200
