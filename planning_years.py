"""Independent annual planning allocations inside a single student promotion.

Migration preserves physical courses and their identifiers. Existing preparation
is copied once into each year; subsequent edits never propagate between years.
Calendar rules are split without discarding their dates, including summer gaps.
"""
from calendar import monthrange
from datetime import date, timedelta
import secrets


def _anniversary(day, year):
    return date(year, day.month, min(day.day, monthrange(year, day.month)[1]))


def periods(promotion):
    if not promotion.get('date_debut') or not promotion.get('date_fin'):
        return []
    try:
        start, end = map(date.fromisoformat, (promotion['date_debut'], promotion['date_fin']))
    except (ValueError, TypeError):
        return []  # Malformed legacy dates must not break student/trainer portals.
    if end < start:
        return []
    ranges = []
    if (end - start).days <= 366:
        ranges.append((start, end))
    else:
        current = start
        while current <= end:
            if current.year == 9999:
                ranges.append((current, end))
                break
            following = _anniversary(start, current.year + 1)
            # September–July cohorts keep the same teaching dates each year.
            finish = (_anniversary(end, current.year + 1)
                      if (end.month, end.day) < (start.month, start.day)
                      else following - timedelta(days=1))
            ranges.append((current, min(end, finish, following - timedelta(days=1))))
            current = following
    return [dict(id=f"{promotion['id']}:{index + 1}", promotion_id=promotion['id'],
                 number=index + 1, start_date=begin.isoformat(), end_date=finish.isoformat(),
                 label=f"Année {index + 1} · {begin.year}–{finish.year}")
            for index, (begin, finish) in enumerate(ranges)]


def schema(conn):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='planning_subjects'").fetchone()[0]
    if 'UNIQUE(promotion_id,name)' in sql.replace(' ', '').replace('\n', ''):
        # Keep the six-column shape used by historical imports. No foreign keys
        # reference this table; the allocation link below owns annual uniqueness.
        conn.execute('''CREATE TABLE planning_subjects_annual(id TEXT PRIMARY KEY,
            promotion_id TEXT NOT NULL,name TEXT NOT NULL,trainer_id TEXT NOT NULL,
            color TEXT NOT NULL,planned_hours REAL)''')
        conn.execute('INSERT INTO planning_subjects_annual SELECT * FROM planning_subjects')
        conn.execute('DROP TABLE planning_subjects')
        conn.execute('ALTER TABLE planning_subjects_annual RENAME TO planning_subjects')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_periods(id TEXT PRIMARY KEY,
        promotion_id TEXT NOT NULL,number INTEGER NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS planning_subject_periods(
        subject_id TEXT PRIMARY KEY,period_id TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS planning_subject_period ON planning_subject_periods(period_id)')
    for row in conn.execute('SELECT * FROM promotions').fetchall():
        years = periods(dict(row))
        if not years:
            continue
        for year in years:
            existing = conn.execute('SELECT start_date,end_date FROM planning_periods WHERE id=?', (year['id'],)).fetchone()
            if not existing or tuple(existing) != (year['start_date'], year['end_date']):
                conn.execute('''INSERT INTO planning_periods VALUES(?,?,?,?,?) ON CONFLICT(id)
                    DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date''',
                    tuple(year[key] for key in ('id', 'promotion_id', 'number', 'start_date', 'end_date')))
        unmapped = conn.execute('''SELECT s.* FROM planning_subjects s
            LEFT JOIN planning_subject_periods y ON y.subject_id=s.id
            WHERE s.promotion_id=? AND y.subject_id IS NULL''', (row['id'],)).fetchall()
        for subject in unmapped:
            for index, year in enumerate(years):
                sid = subject['id'] if index == 0 else secrets.token_urlsafe(24)
                if index:
                    conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)',
                                 (sid, *tuple(subject)[1:]))
                    conn.execute('''INSERT INTO planning_subject_catalog_links
                        SELECT ?,subject_id FROM planning_subject_catalog_links WHERE planning_subject_id=?''',
                        (sid, subject['id']))
                    conn.execute('''INSERT INTO planning_subject_details
                        SELECT ?,data,updated_at FROM planning_subject_details WHERE subject_id=?''', (sid, subject['id']))
                    # Includes secondary memberships of shared physical courses.
                    conn.execute('''UPDATE planning_courses SET subject_id=?,version=version+1
                        WHERE subject_id=? AND date BETWEEN ? AND ?''',
                        (sid, subject['id'], year['start_date'], year['end_date']))
                    conn.execute('''UPDATE planning_courses SET version=version+1
                        WHERE subject_id!=? AND date BETWEEN ? AND ? AND id IN
                        (SELECT course_id FROM planning_course_groups WHERE subject_id=?)''',
                        (sid, year['start_date'], year['end_date'], subject['id']))
                    conn.execute('''UPDATE planning_course_groups SET subject_id=? WHERE subject_id=?
                        AND course_id IN (SELECT id FROM planning_courses WHERE date BETWEEN ? AND ?)''',
                        (sid, subject['id'], year['start_date'], year['end_date']))
                conn.execute('INSERT INTO planning_subject_periods VALUES(?,?)', (sid, year['id']))
        # Split only rules crossing annual boundaries; already migrated rows are
        # unchanged, and dates outside the annual plans remain stored verbatim.
        boundaries = sorted({y['start_date'] for y in years} | {
            (date.fromisoformat(y['end_date']) + timedelta(days=1)).isoformat() for y in years
            if y['end_date'] != '9999-12-31'})
        for rule in conn.execute('SELECT * FROM planning_calendar_rules WHERE promotion_id=?', (row['id'],)).fetchall():
            cuts = [value for value in boundaries if rule['start_date'] < value <= rule['end_date']]
            if not cuts:
                continue
            starts = [rule['start_date'], *cuts]
            ends = [(date.fromisoformat(value) - timedelta(days=1)).isoformat() for value in cuts] + [rule['end_date']]
            conn.execute('UPDATE planning_calendar_rules SET end_date=? WHERE id=?', (ends[0], rule['id']))
            for begin, finish in zip(starts[1:], ends[1:]):
                conn.execute('INSERT INTO planning_calendar_rules VALUES(?,?,?,?,?,?,?)',
                             (secrets.token_urlsafe(24), row['id'], begin, finish,
                              rule['weekdays'], rule['kind'], rule['label']))


def select(conn, promotion, period_id=None, day=None):
    from planning import PlanningError
    choices = periods(promotion)
    if period_id:
        selected = next((item for item in choices if item['id'] == period_id), None)
        if not selected:
            raise PlanningError('Cette année ne correspond pas à la promotion. Rechargez le planning.', status=409)
        return selected
    if day:
        selected = next((item for item in choices if item['start_date'] <= day <= item['end_date']), None)
        if selected:
            return selected
    return choices[0] if choices else None


def allocation(conn, subject_id):
    row = conn.execute('''SELECT p.* FROM planning_subject_periods s
        JOIN planning_periods p ON p.id=s.period_id WHERE s.subject_id=?''', (subject_id,)).fetchone()
    return dict(row) if row else None


def contains(period, day):
    return bool(period and period['start_date'] <= day <= period['end_date'])


def require_dates(period, *days):
    from planning import PlanningError
    if not period or any(not contains(period, day) for day in days):
        raise PlanningError('Cette action doit rester dans l’année du planning sélectionnée.',
                            [dict(type='outside_planning_year', message='Choisissez une date de cette année.')], 409)
