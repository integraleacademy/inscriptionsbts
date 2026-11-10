"""Availability across the room ledger, calculated on the requested teaching hours."""
from collections import defaultdict
from contextlib import closing
from datetime import date

from flask import request

from planning import PlanningError, _clock, _dates, _minutes, _range, _weekdays
from planning_room_calendar import reservation_slots
from planning_rooms import configured, external_slots, is_physical_room, ready

OPEN_END = date.max.isoformat()
SCHOOL_DAYS = [0, 1, 2, 3, 4]


def require_ready(conn):
    if not ready(conn):
        raise PlanningError('Les réservations des sessions sont en cours de synchronisation. Réessayez dans un instant.', status=503)


def bookings(conn, first, last):
    """One row per physical booking, including both sides of pending external writes."""
    rows = conn.execute('''SELECT c.id, c.version, c.room_id, c.date, c.start_min, c.end_min,
        c.kind, COALESCE(NULLIF(c.title,''),s.name,'Cours') AS title, p.nom AS promotion_name
        FROM planning_courses c LEFT JOIN planning_subjects s ON s.id=c.subject_id
        LEFT JOIN promotions p ON p.id=c.promotion_id
        WHERE c.date BETWEEN ? AND ? AND c.room_id IS NOT NULL''', (first, last))
    courses = [dict(row, key='course:' + row['id'], source='event' if row['kind'] == 'event' else 'bts') for row in rows]
    sessions = [s for s in external_slots(conn) if s['room_id'] and first <= s['date'] <= last]
    return courses + sessions + reservation_slots(conn, first, last)


def closures(conn, first, last):
    return [dict(row) for row in conn.execute('''SELECT * FROM planning_room_unavailability
        WHERE start_date <= ? AND end_date >= ?''', (last, first))]


def free_intervals(spans, start, end):
    free = []
    cursor = start
    for left, right in sorted(spans):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            free.append([_clock(cursor), _clock(left)])
        cursor = max(cursor, right)
        if cursor >= end:
            break
    if cursor < end:
        free.append([_clock(cursor), _clock(end)])
    return free


def availability(conn, first, last, start='08:00', end='18:00', weekdays=None):
    require_ready(conn)
    first_day, last_day = _range(first, last, max_days=365)
    days = _weekdays(weekdays, SCHOOL_DAYS)
    left, right = _minutes(start), _minutes(end, end=True)
    if left >= right:
        raise PlanningError('L’heure de fin doit suivre l’heure de début.')
    dates = [d.isoformat() for d in _dates(first_day, last_day) if d.weekday() in days]
    rooms = [dict(r) for r in conn.execute('SELECT id,name,active FROM planning_rooms ORDER BY name COLLATE NOCASE,id')
             if is_physical_room(r['name'])]
    occupied = defaultdict(list)
    for slot in bookings(conn, first, last):
        occupied[slot['room_id'], slot['date']].append((slot['start_min'], slot['end_min']))
    for block in closures(conn, first, last):
        for day in dates:
            if block['start_date'] <= day <= block['end_date']:
                occupied[block['room_id'], day].append((block['start_min'], block['end_min']))
    for room in rooms:
        cells = {}
        for day in dates:
            free = free_intervals(occupied[room['id'], day], left, right) if room['active'] else []
            cells[day] = dict(state='free' if free == [[start, end]] else 'partial' if free else 'busy', free=free)
        room.update(days=cells, free_days=sum(c['state'] == 'free' for c in cells.values()))
    return dict(rooms=rooms, dates=dates, first=first, last=last, start=start, end=end, weekdays=days, connected=configured())


def register(app, connect, guard, result, fail):
    @app.get('/admin/planning/api/rooms/disponibilites')
    def planning_room_availability():
        guard()
        try:
            with closing(connect()) as conn:
                conn.execute('BEGIN')
                weekdays = request.args.get('weekdays', '0,1,2,3,4').split(',')
                if any(n not in '0123456' or len(n) != 1 for n in weekdays):
                    raise PlanningError('Choisissez les jours à vérifier.')
                return result(availability(conn, request.args.get('from'), request.args.get('to'),
                                           request.args.get('start', '08:00'), request.args.get('end', '18:00'),
                                           [int(n) for n in weekdays]))
        except PlanningError as error:
            return fail(error)
