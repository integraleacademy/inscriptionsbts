"""Read-only daily programme for the screen at the training centre."""
import json
import re

from planning import _load_courses, _minutes
from planning_import_pdf import normal
from planning_room_calendar import reservation_slots
from planning_room_changes import during, periods
from planning_rooms import effective_slots, is_physical_room


PARIS_LOCATION = re.compile(r'\b(?:paris(?:ien(?:ne)?s?)?|750(?:0[0-9]|1[0-9]|20)|75116|rue poissonniere|villa de lourcine)\b')


def in_paris(value):
    return bool(PARIS_LOCATION.search(normal(value)))


def teaching_periods(slot, staff, room_ids, exam):
    """Subdivide a committed room reservation only when its teaching team changes."""
    start, end = slot['start_min'], slot['end_min']
    changes = {start, end}
    assigned = []
    for group in staff.get('days', {}).get(slot['date'], []):
        rid = room_ids.get(group['room_name'].casefold()) if group.get('room_name') else group.get('room_id')
        if rid != slot['room_id']:
            continue
        for left, right in group['spans']:
            a, b = max(start, _minutes(left)), min(end, _minutes(right, True))
            if a < b:
                assigned.append((a, b, group['names']))
                changes.update((a, b))
    fallback = staff.get('exam' if exam else 'default', [])
    periods = []
    points = sorted(changes)
    for a, b in zip(points, points[1:]):
        people = sorted({name for left, right, names in assigned if left <= a < right for name in names}, key=str.casefold)
        people = people or fallback
        if periods and periods[-1][2] == people:
            periods[-1] = (periods[-1][0], b, people)
        else:
            periods.append((a, b, people))
    return periods


def daily_programme(conn, day):
    rooms = {r['id']: r['name'] for r in during(periods(conn), day, day)}
    aliases = {r['name']: r['room_id'] for r in conn.execute('SELECT name, room_id FROM planning_room_aliases')}
    room_ids = {name.strip().casefold(): rid for rid, name in rooms.items()}
    room_ids.update(aliases)
    paris_rooms = {rid for rid, name in rooms.items() if in_paris(name)}
    paris_rooms.update(rid for name, rid in aliases.items() if in_paris(name))
    entries = []

    def add(slot, title, detail='', exam=False, trainers=()):
        if slot['room_id'] in paris_rooms:
            return
        room = rooms.get(slot['room_id'], '')
        entries.append(dict(start_min=slot['start_min'], end_min=slot['end_min'], title=title,
                            detail=detail, room=room if is_physical_room(room) else '', exam=bool(exam), trainers=list(trainers)))

    for course in _load_courses(conn, day, day):
        groups = [g for g in course['groups'] if not in_paris(g['promotion_name'])]
        if not groups:
            continue
        title = course['title']
        if not title or title.casefold().strip() == 'cours':
            title = groups[0]['subject_name'] or course['subject_name']
        promotions = dict.fromkeys(g['promotion_name'] for g in groups if g['promotion_name'])
        named = course['trainer_id'] and course['trainer_active'] is not None and course['trainer_name'] != 'Formateur à renseigner'
        add(course, title, ' · '.join(promotions), trainers=[course['trainer_name']] if named else [])

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
        for original, slot in zip(slots, effective_slots(conn, owner['owner'], slots, meta)):
            # Old director sessions may have no site or room at all. Only show
            # those after the source or a local label identifies their centre.
            has_venue = location.get('site') or location.get('venue') or (exam and location.get('exam_venue'))
            if not has_venue and (formation.upper() in ('DESP', 'DIRIGEANT') or normal(title).startswith(('desp', 'dirigeant'))):
                identifiers = normal(' '.join([title, location.get('venue', ''), rooms.get(slot['room_id'], '')]))
                if not any(v in identifiers for v in ('puget', 'cote d azur', 'aurillac', 'arpajon')):
                    continue
            detail = formation if formation.casefold() not in title.casefold() else ''
            for start, end, people in teaching_periods(original, meta.get('display_trainers', {}), room_ids, exam):
                add(dict(slot, start_min=start, end_min=end), title, detail, exam, people)

    for booking in reservation_slots(conn, day, day):
        if not in_paris(booking['title']):
            names = dict.fromkeys(n.strip() for n in re.split('[,;]', booking['trainer_names']) if n.strip())
            add(booking, booking['title'], exam=booking['exam'], trainers=names)

    return sorted(entries, key=lambda e: (e['start_min'], e['end_min'], normal(e['room']), normal(e['title'])))
