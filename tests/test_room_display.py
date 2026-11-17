from datetime import datetime, timezone
from unittest.mock import patch

from planning_room_display import daily_programme
from test_planning import BASE, add, app, call, client, db, setup_school
from test_planning_rooms_events import event, linked, machine, reservation
from test_room_calendar import block, move, schedule, seed


DAY = '2027-01-04'
FEED = BASE + '/rooms/affichage-tv'


def test_television_uses_the_school_day_and_only_display_fields(app, client, db):
    setup_school(client)
    add(client, title='Cours', zoom_url='https://zoom.us/j/12345678', shared=[dict(promotion_id='p2', subject_id='s2')])
    event(client, title='Demain', date='2027-01-05')
    assert block(client, start_date=DAY, end_date=DAY).status_code == 200
    assert app.test_client().get(FEED).status_code == 403
    assert app.test_client().get('/admin/salles/affichage-tv').status_code == 403
    # It is already Monday in France while the UTC server is still on Sunday.
    instant = datetime(2027, 1, 3, 23, 30, tzinfo=timezone.utc)
    with patch('planning_room_calendar.datetime') as now:
        now.now.side_effect = instant.astimezone
        response = client.get(FEED + '?date=2027-01-05')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert response.json['date'] == DAY and response.json['now'].endswith('+01:00')
    entry, = response.json['entries']
    assert set(entry) == {'start_min', 'end_min', 'title', 'detail', 'room', 'exam'}
    assert entry['title'] == 'Matière s1' and entry['room'] == 'Salle r1'
    assert 'BTS MCO p1' in entry['detail'] and 'BTS MCO p2' in entry['detail']
    with db() as conn:
        assert daily_programme(conn, '2027-01-06') == []


def test_paris_rooms_aliases_promotions_and_source_venues_are_excluded(linked, client, db):
    with db() as conn:
        conn.execute("UPDATE planning_rooms SET name='Salle 75002' WHERE id='r1'")
        conn.execute("INSERT INTO planning_rooms VALUES('renamed','Salle A',1)")
        conn.execute("INSERT INTO planning_room_aliases VALUES('salle paris','renamed')")
        conn.execute("UPDATE promotions SET nom='BTS MOS Paris' WHERE id='p2'")
    event(client, title='Cours en salle parisienne', room_id='r1')
    event(client, title='Ancienne salle parisienne', room_id='renamed', start='13:00', end='14:00')
    event(client, title='Promotion parisienne', promotion_id='p2', room_id=None)
    seed(client, owner='session:paris', room='r2', metadata=dict(name='Dirigeant', formation='DESP', location={'site': 'PARIS'}))
    seed(client, owner='session:address', schema=3, room=None, metadata=dict(name='Accueil', location={'venue': '34 rue Poissonnière'}))
    seed(client, owner='session:exam', schema=3, room=None, metadata=dict(name='Examen externe', exam_dates=[DAY], location={'exam_venue': '75014'}))
    seed(client, owner='session:local', schema=3, room=None, metadata=dict(name='Dirigeant local', formation='DESP', location={'site': 'PUGET'}))
    call(client, '/rooms/reservations', dict(room_id='r2', date=DAY, title='Examen SSIAP', exam=True, start='15:00', end='16:00'))
    with db() as conn:
        entries = daily_programme(conn, DAY)
    assert [e['title'] for e in entries] == ['Dirigeant local', 'Examen SSIAP']
    assert entries[0]['room'] == '' and entries[1]['exam'] is True
    assert len(schedule(client)) == 8


def test_existing_source_gains_site_without_losing_override_or_publishing_pending_room(linked, client, db):
    old = seed(client, metadata=dict(name='Dirigeant', formation='DESP'))
    assert move(client, schedule(client), 'r2').status_code == 200
    site = dict(old, schema=3, revision='2'*64, pre_location_revision=old['revision'],
                metadata=dict(old['metadata'], location={'site': 'PUGET'}))
    assert machine(client, 'reconcile', dict(owners=[site], complete=True)).status_code == 200
    with db() as conn:
        item, = daily_programme(conn, DAY)
        assert item['room'] == 'Salle r2'
    change = reservation(revision='3', previous_revision=site['revision'], room='r1',
                         metadata=dict(site['metadata'], assignment='new', location={'site': 'PARIS'}))
    prepared = machine(client, 'prepare', change)
    assert prepared.status_code == 200
    with db() as conn:
        assert daily_programme(conn, DAY) == [item]
    assert machine(client, 'finish', dict(token=prepared.json['token'], commit=True)).status_code == 200
    with db() as conn:
        assert daily_programme(conn, DAY) == []
