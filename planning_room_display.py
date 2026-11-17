"""Read-only daily programme for the screen at the training centre."""
import json
import re

from planning import _load_courses
from planning_import_pdf import normal
from planning_room_calendar import reservation_slots
from planning_rooms import effective_slots, is_physical_room


PARIS_LOCATION = re.compile(r'\b(?:paris(?:ien(?:ne)?s?)?|750(?:0[0-9]|1[0-9]|20)|75116|rue poissonniere|villa de lourcine)\b')


def in_paris(value):
    return bool(PARIS_LOCATION.search(normal(value)))


def daily_programme(conn, day):
    rooms = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM planning_rooms')}
    paris_rooms = {rid for rid, name in rooms.items() if in_paris(name)}
    paris_rooms.update(r['room_id'] for r in conn.execute('SELECT name, room_id FROM planning_room_aliases') if in_paris(r['name']))
    entries = []

    def add(slot, title, detail='', exam=False):
        if slot['room_id'] in paris_rooms:
            return
        room = rooms.get(slot['room_id'], '')
        entries.append(dict(start_min=slot['start_min'], end_min=slot['end_min'], title=title,
                            detail=detail, room=room if is_physical_room(room) else '', exam=bool(exam)))

    for course in _load_courses(conn, day, day):
        groups = [g for g in course['groups'] if not in_paris(g['promotion_name'])]
        if not groups:
            continue
        title = course['title']
        if not title or title.casefold().strip() == 'cours':
            title = groups[0]['subject_name'] or course['subject_name']
        names = [g['promotion_name'] for g in groups if g['promotion_name']]
        if course['trainer_id'] and course['trainer_active'] is not None:
            names.append(course['trainer_name'])
        add(course, title, ' · '.join(dict.fromkeys(names)))

    # The administrative calendar holds both sides of a pending write. Students
    # must see only the committed timetable, using its current per-slot overrides.
    owners = conn.execute("""SELECT owner, title, slots, metadata FROM planning_room_owners
        WHERE owner LIKE 'session:%' AND instr(slots, ?) > 0""", (day,))
    for owner in owners:
        meta = json.loads(owner['metadata'] or '{}')
        location = meta.get('location') or {}
        title = meta.get('name') or owner['title']
        exam = day in meta.get('exam_dates', [])
        if (meta.get('deleted') or in_paris(location.get('site')) or in_paris(location.get('venue'))
                or (exam and in_paris(location.get('exam_venue'))) or in_paris(title)):
            continue
        formation = meta.get('formation') or ''
        slots = [s for s in json.loads(owner['slots']) if s['date'] == day]
        for slot in effective_slots(conn, owner['owner'], slots, meta):
            # Old director sessions may have no site or room at all. Only show
            # those after the source or a local label identifies their centre.
            has_venue = location.get('site') or location.get('venue') or (exam and location.get('exam_venue'))
            if not has_venue and (formation.upper() in ('DESP', 'DIRIGEANT') or normal(title).startswith(('desp', 'dirigeant'))):
                identifiers = normal(' '.join([title, location.get('venue', ''), rooms.get(slot['room_id'], '')]))
                if not any(v in identifiers for v in ('puget', 'cote d azur', 'aurillac', 'arpajon')):
                    continue
            detail = formation if formation.casefold() not in title.casefold() else ''
            add(slot, title, detail, exam)

    for booking in reservation_slots(conn, day, day):
        if not in_paris(booking['title']):
            add(booking, booking['title'], exam=booking['exam'])

    return sorted(entries, key=lambda e: (e['start_min'], e['end_min'], normal(e['room']), normal(e['title'])))
