"""Dated room names, closures and the January 2027 timetable change."""
from collections import defaultdict
from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo

from planning_import_pdf import normal

JANUARY = '2027-01-01'
MIGRATION = 'room_changes_2027_01'
PARIS_ROOM = '34 rue Poissonnière'


def paris_today():
    return datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()


def periods(conn):
    rows = conn.execute('''SELECT r.id, r.name, r.active, c.previous_name, c.effective_from, c.retired
        FROM planning_rooms r LEFT JOIN planning_room_changes c ON c.room_id=r.id''')
    result = []
    for row in rows:
        room = dict(id=row['id'], name=row['name'], active=row['active'])
        if row['effective_from']:
            previous = dict(room, name=row['previous_name'], valid_before=row['effective_from'])
            if not row['retired']:
                previous['next_name'] = room['name']
            result.append(previous)
            if row['retired']:
                continue
            room['valid_from'] = row['effective_from']
        result.append(room)
    return sorted(result, key=lambda r: (r['name'].casefold(), r['id']))


def during(rooms, first, last):
    return [r for r in rooms if (not r.get('valid_from') or r['valid_from'] <= last)
            and (not r.get('valid_before') or first < r['valid_before'])]


def retired_on(conn, room_id, day):
    return conn.execute('''SELECT 1 FROM planning_room_changes
        WHERE room_id=? AND retired=1 AND effective_from<=?''', (room_id, day)).fetchone() is not None


def default_mos_room(conn, day, groups, room_id):
    # New lessons and weeks copied from Vernèdes start in 1B. An explicit choice
    # of another available room is still editable through the usual controls.
    if day < JANUARY or (room_id and not retired_on(conn, room_id, day)):
        return room_id
    config = conn.execute('SELECT value FROM planning_room_meta WHERE key=?', (MIGRATION,)).fetchone()
    if config and any(conn.execute("SELECT 1 FROM promotions WHERE id=? AND upper(trim(bts))='MOS'",
                                   (g['promotion_id'],)).fetchone() for g in groups):
        target = json.loads(config[0])['target']
        if conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1', (target,)).fetchone():
            return target
    return room_id


def released_local_slots(conn):
    rows = conn.execute('''SELECT q.source, c.id, c.date, c.start_min, c.end_min, c.version, c.kind,
            COALESCE(NULLIF(s.name,''), NULLIF(c.title,''), 'Cours') AS title, p.nom AS promotion_name,
            EXISTS(SELECT 1 FROM planning_course_groups g WHERE g.course_id=c.id AND g.promotion_id<>c.promotion_id) AS shared
        FROM planning_room_releases q JOIN planning_courses c ON c.id=q.slot_id
        LEFT JOIN planning_subjects s ON s.id=c.subject_id LEFT JOIN promotions p ON p.id=c.promotion_id
        WHERE q.source='course' AND c.room_id IS NULL
        UNION ALL SELECT q.source, r.id, r.date, r.start_min, r.end_min, r.version, '', r.title, '', 0
        FROM planning_room_releases q JOIN planning_room_reservations r ON r.id=q.slot_id
        WHERE q.source='reservation' AND r.room_id=''
        ORDER BY date, start_min, title''')
    from planning import _clock
    return [dict(key=r['source'] + ':' + r['id'], id=r['id'], date=r['date'], version=r['version'],
                 source=('event' if r['kind']=='event' else 'bts') if r['source']=='course' else 'reservation',
                 title=r['title'], promotion_name=r['promotion_name'], is_shared=bool(r['shared']), start=_clock(r['start_min']), end=_clock(r['end_min']))
            for r in rows]


def released_session_slots(conn, sessions):
    keys = {r[0] for r in conn.execute("SELECT slot_id FROM planning_room_releases WHERE source='session'")}
    if not keys:
        return []
    from planning import _clock
    return [dict(key=s['key'], date=s['date'], title=s['title'], source='session', owner=s['owner'],
                 revision=s['revision'], room_version=s['room_version'], start=_clock(s['start_min']), end=_clock(s['end_min']))
            for s in sessions if s['key'] in keys and not s['room_id'] and not s['pending']]


def schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_room_changes(
        room_id TEXT PRIMARY KEY, effective_from TEXT NOT NULL, previous_name TEXT NOT NULL, retired INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_room_releases(
        source TEXT NOT NULL, slot_id TEXT NOT NULL, PRIMARY KEY(source,slot_id))''')
    if conn.execute('SELECT 1 FROM planning_room_meta WHERE key=?', (MIGRATION,)).fetchone():
        return
    rooms = {normal(r['name']): r for r in conn.execute('SELECT id,name,active FROM planning_rooms')}
    annex = rooms.get('annexe vernedes')
    atelier = rooms.get('atelier modulable paris') or rooms.get('atelier modulable')
    target = rooms.get('salle 1b')
    if not (annex and atelier and target and target['active']):
        return
    # The caller holds the planning schema savepoint. Finish in-flight remote
    # assignments before writing overrides, so an older finish cannot clear them.
    from planning_rooms import effective_slots
    for owner in conn.execute("SELECT * FROM planning_room_owners WHERE pending_token IS NOT NULL"):
        current = json.loads(owner['metadata'] or '{}')
        for slots, meta in [('slots','metadata'), ('pending_slots','pending_metadata')]:
            held = effective_slots(conn, owner['owner'], json.loads(owner[slots] or '[]'), json.loads(owner[meta] or '{}'), current)
            if any(s['date'] >= JANUARY and s['room_id'] in (annex['id'], target['id']) for s in held):
                return
    apply_january_change(conn, annex, atelier, target)


def apply_january_change(conn, annex, atelier, target):
    from planning_rooms import effective_slots

    now = datetime.now(timezone.utc).isoformat()
    displaced = (annex['id'], target['id'])
    counts = dict(target=target['id'], mos=0, mos_conflicts=0, courses_released=0, reservations_released=0,
                  sessions_released=0, session_slots_released=0)

    # Identify the physical course once, including MOS as a secondary group.
    mos = {r[0] for r in conn.execute('''SELECT c.id FROM planning_courses c JOIN promotions p ON p.id=c.promotion_id
        WHERE c.date>=? AND upper(trim(p.bts))='MOS'
        UNION SELECT c.id FROM planning_courses c JOIN planning_course_groups g ON g.course_id=c.id
        JOIN promotions p ON p.id=g.promotion_id WHERE c.date>=? AND upper(trim(p.bts))='MOS' ''', (JANUARY, JANUARY))}
    closures = conn.execute("""SELECT start_date,end_date,start_min,end_min FROM planning_room_unavailability
        WHERE room_id=? AND end_date>=?""", (target['id'], JANUARY)).fetchall()
    occupied = defaultdict(list)
    courses = conn.execute("""SELECT id,room_id,date,start_min,end_min FROM planning_courses WHERE date>=?
        ORDER BY (room_id IS ?) DESC, date, start_min, id""", (JANUARY, target['id'])).fetchall()
    for course in courses:
        if course['id'] in mos:
            day = course['date']
            blocks = [(c['start_min'], c['end_min']) for c in closures if c['start_date'] <= day <= c['end_date']]
            if any(a < course['end_min'] and course['start_min'] < b for a,b in occupied[day] + blocks):
                room_id = None
                counts['mos_conflicts'] += 1
            else:
                occupied[day].append((course['start_min'], course['end_min']))
                room_id = target['id']
                if course['room_id'] == room_id:
                    continue
                counts['mos'] += 1
        elif course['room_id'] in displaced:
            room_id = None
        else:
            continue
        if room_id is None:
            counts['courses_released'] += 1
            conn.execute("INSERT INTO planning_room_releases VALUES('course',?)", (course['id'],))
        conn.execute('UPDATE planning_courses SET room_id=?,version=version+1,updated_at=? WHERE id=?',
                     (room_id, now, course['id']))

    conn.execute("""INSERT INTO planning_room_releases SELECT 'reservation',id FROM planning_room_reservations
        WHERE date>=? AND room_id IN (?,?)""", (JANUARY, *displaced))
    counts['reservations_released'] = conn.execute("""UPDATE planning_room_reservations SET
        room_id='',version=version+1,updated_at=? WHERE date>=? AND room_id IN (?,?)""", (now, JANUARY, *displaced)).rowcount
    for owner in conn.execute("SELECT owner,slots,metadata FROM planning_room_owners WHERE owner LIKE 'session:%'"):
        slots = effective_slots(conn, owner['owner'], json.loads(owner['slots']), json.loads(owner['metadata'] or '{}'))
        keys = [(owner['owner'], s['slot_key']) for s in slots if s['date'] >= JANUARY and s['room_id'] in displaced]
        if keys:
            conn.executemany("""INSERT INTO planning_room_overrides(owner,slot_key,room_id) VALUES(?,?,'')
                ON CONFLICT(owner,slot_key) DO UPDATE SET room_id=''""", keys)
            conn.executemany("INSERT INTO planning_room_releases VALUES('session',?)",
                             [('session:' + who + ':' + key,) for who, key in keys])
            conn.execute('UPDATE planning_room_owners SET room_version=room_version+1 WHERE owner=?', (owner['owner'],))
            counts['sessions_released'] += 1
            counts['session_slots_released'] += len(keys)

    conn.executemany('INSERT INTO planning_room_changes VALUES(?,?,?,?)',
                     [(annex['id'], JANUARY, annex['name'], 1), (atelier['id'], JANUARY, atelier['name'], 0)])
    conn.execute('INSERT OR IGNORE INTO planning_room_aliases VALUES(?,?)', (atelier['name'].strip().casefold(), atelier['id']))
    conn.execute('UPDATE planning_rooms SET name=? WHERE id=?', (PARIS_ROOM, atelier['id']))
    conn.execute('INSERT INTO planning_room_meta(key,value) VALUES(?,?)', (MIGRATION, json.dumps(counts)))
    print('Planning des salles au 01/01/2027 : ' + json.dumps({k:v for k,v in counts.items() if k!='target'}), flush=True)
