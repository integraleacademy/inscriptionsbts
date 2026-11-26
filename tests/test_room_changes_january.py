"""The room change is based on the booking date, including partial sessions."""
import json

from planning import ensure_planning_schema
from planning_rooms import slot_key
from test_planning import db, app, client, call, BASE, course, setup_school


def legacy(conn):
    conn.execute("UPDATE promotions SET bts='MOS',nom='BTS MOS' WHERE id='p1'")
    conn.execute("UPDATE planning_rooms SET name='Annexe Vernèdes' WHERE id='r1'")
    conn.execute("UPDATE planning_rooms SET name='Salle 1B' WHERE id='r2'")
    conn.executemany('INSERT INTO planning_rooms VALUES(?,?,1)', [('paris','Atelier Modulable Paris'),('other','Salle 3B')])
    for cid, pid, rid, day in [
            ('dec-mos','p1','r1','2026-12-31'), ('jan-mos','p1','r1','2027-01-01'),
            ('shared','p2','other','2027-01-05'), ('pi','p2','r2','2027-01-01'),
            ('other','p2','other','2027-01-06'), ('already','p1','r2','2027-02-01'),
            ('dec-paris','p2','paris','2026-12-30'), ('jan-paris','p2','paris','2027-01-02')]:
        conn.execute("""INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,
            title,created_at,updated_at) VALUES(?,?,?,'t1',?,?,540,600,'Cours','old','old')""",
            (cid,pid,'s1' if pid=='p1' else 's2',rid,day))
    conn.execute("INSERT INTO planning_course_groups VALUES('shared','p1','s1')")
    for day in ('2026-12-31','2027-01-01'):
        conn.execute("""INSERT INTO planning_room_reservations(id,room_id,date,start_min,end_min,title,exam,created_at,updated_at)
            VALUES(?,'r2',?,720,780,'Examen VTC',1,'old','old')""", (day,day))
    slots = [dict(room_id=rid,date=day,start_min=600,end_min=720) for rid,day in
             [('r2','2026-12-31'),('r2','2027-01-01'),('r2','2027-01-02'),('other','2027-01-03')]]
    meta = json.dumps(dict(start='2026-12-31',formation='APS'))
    conn.execute("""INSERT INTO planning_room_owners(owner,revision,slots,title,url,metadata)
        VALUES('session:winter',?,?,'Session hiver','',?)""", ('a'*64,json.dumps(slots),meta))
    # Respect the effective assignment in both directions.
    conn.executemany("INSERT INTO planning_room_overrides VALUES('session:winter',?,?)",
                     [(slot_key(slots[2]),'other'),(slot_key(slots[3]),'r2')])


def calendar(client, first, last):
    res=client.get(BASE+'/rooms/schedule',query_string=dict(start=first,end=last))
    assert res.status_code==200
    return res.json


def test_dated_change_keeps_history_and_real_slots_and_allows_later_reassignment(db,client):
    with db() as conn:
        legacy(conn)
    dec=calendar(client,'2026-12-30','2026-12-31')
    jan=calendar(client,'2027-01-01','2027-01-06')
    assert {r['name'] for r in dec['rooms']}=={'Salle 1B','Annexe Vernèdes','Atelier Modulable Paris','Salle 3B'}
    assert {r['name'] for r in jan['rooms']}=={'Salle 1B','34 rue Poissonnière','Salle 3B'}
    assert {r['date']:r['room_id'] for r in jan['reservations'] if r['source']=='session'}=={
        '2027-01-01':None,'2027-01-02':'other','2027-01-03':None}
    assert jan['unassigned_sessions'][0]['count']==2
    individual=jan['unassigned_session_slots']
    assert {s['date'] for s in individual}=={'2027-01-01','2027-01-03'}
    assert call(client,'/rooms/calendar-move',dict(slots=[individual[0]],room_id='other')).status_code==200
    rows={r['id']:r for r in dec['reservations']+jan['reservations'] if r['source']!='session'}
    assert [(rows[c]['room_id'],rows[c]['version']) for c in ('dec-mos','jan-mos','shared','pi','other')] == [
        ('r1',1),('r2',2),('r2',2),(None,2),('other',1)]
    assert rows['2026-12-31']['room_id']=='r2' and not rows['2027-01-01']['room_id'] and rows['2027-01-01']['exam']
    assert rows['dec-paris']['room_name']=='Atelier Modulable Paris'
    assert rows['jan-paris']['room_name']=='34 rue Poissonnière'
    assert len([r for r in calendar(client,'2026-12-31','2027-01-01')['rooms'] if r['id']=='paris'])==2
    released={r['key']:r for r in jan['unassigned_local']}
    assert set(released)=={'course:pi','reservation:2027-01-01'}
    for key in released:
        slot=released[key]
        res=call(client,'/rooms/calendar-move',dict(slots=[slot],room_id='other'))
        assert res.status_code==200,res.json
    assert not calendar(client,'2027-01-01','2027-01-06')['unassigned_local']
    with db() as conn:
        ensure_planning_schema(conn)
        assert tuple(conn.execute("SELECT room_id,version FROM planning_courses WHERE id='pi'").fetchone())==('other',3)
        assert tuple(conn.execute("SELECT room_id,version FROM planning_courses WHERE id='already'").fetchone())==('r2',1)
        assert conn.execute("SELECT room_id FROM planning_room_aliases WHERE name='atelier modulable paris'").fetchone()[0]=='paris'


def test_closure_applies_to_new_bookings_and_mos_defaults_and_shared_availability(db,client):
    with db() as conn:
        legacy(conn)
    setup_school(client)
    res=call(client,'/courses',course(room_id=None,date='2027-01-07'))
    assert res.status_code==200 and res.json['course']['room_id']=='r2'
    res=call(client,'/rooms/reservations',dict(room_id='r1',date='2027-01-01',start='09:00',end='10:00',title='Réunion'))
    assert res.status_code==409
    res=call(client,'/rooms/reservations',dict(room_id='r1',date='2026-12-30',start='09:00',end='10:00',title='Réunion'))
    assert res.status_code==200
    after=client.get(BASE+'/rooms/available?date=2027-01-01&start=14:00&end=15:00').json['rooms']
    assert 'r1' not in {r['id'] for r in after}
    assert next(r['name'] for r in after if r['id']=='paris')=='34 rue Poissonnière'
    local=next(r for r in calendar(client,'2027-01-01','2027-01-01')['unassigned_local'] if r['key']=='course:pi')
    assert call(client,'/rooms/calendar-move',dict(slots=[local],room_id='r1')).status_code==409
    mixed=client.get(BASE+'/rooms/disponibilites?from=2026-12-31&to=2027-01-01').json['rooms']
    assert next(r for r in mixed if r['id']=='r1')['days']['2027-01-01']['free']==[]


def test_waits_for_source_confirmation_and_preserves_closures(db,client):
    with db() as conn:
        legacy(conn)
        conn.execute("UPDATE planning_room_owners SET pending_token='in-flight'")
        ensure_planning_schema(conn)
        assert conn.execute('SELECT count(*) FROM planning_room_changes').fetchone()[0]==0
        conn.execute('UPDATE planning_room_owners SET pending_token=NULL')
        conn.execute("""INSERT INTO planning_room_unavailability VALUES(
            'closure','r2','2027-01-05','2027-01-05',540,700,'Travaux',1)""")
    data=calendar(client,'2027-01-05','2027-01-05')
    assert {b['key'] for b in data['unassigned_local']} >= {'course:shared'}
    assert not any(r['conflict'] for r in data['reservations'])
