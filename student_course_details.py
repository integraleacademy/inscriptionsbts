"""Student-only course details, rebuilt from the current identity and register."""
from urllib.parse import urlsplit


def zoom_url(value):
    value = str(value or '').strip()
    parsed = urlsplit(value)
    if not value:
        return ''
    host = (parsed.hostname or '').lower()
    if (len(value) > 2000 or parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443) or any(ord(c) < 33 for c in value)
            or not any(host == domain or host.endswith('.'+domain) for domain in ('zoom.us', 'zoom.com', 'zoomgov.com'))):
        raise ValueError('Ajoutez un lien de réunion Zoom valide commençant par https://.')
    return value


def student_details(conn, candidate_id, course):
    """Call only after authorizing access to this course. Never assume presence."""
    columns = {r[1] for r in conn.execute('PRAGMA table_info(candidats)')}
    row = conn.execute('SELECT mode FROM candidats WHERE id=?', (candidate_id,)).fetchone() if 'mode' in columns else None
    link = ''
    if row and row['mode'] == 'distanciel':
        try:
            link = zoom_url(course.get('zoom_url'))
        except ValueError:
            pass
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    status, minutes = 'unrecorded', 0
    if 'teaching_attendance' in tables:
        call = conn.execute('''SELECT a.status,a.late_minutes FROM teaching_attendance a
            JOIN teaching_rollcalls r ON r.course_id=a.course_id
            WHERE a.course_id=? AND a.candidate_id=? AND r.completed_at IS NOT NULL''',
            (course['id'], candidate_id)).fetchone()
        if call:
            status, minutes = call['status'], call['late_minutes']
    # Administrative corrections in the attendance register take precedence.
    if 'student_attendance' in tables:
        events = conn.execute('''SELECT kind,start_min,end_min FROM student_attendance
            WHERE candidate_id=? AND date=? AND deleted=0 AND start_min<? AND end_min>?''',
            (candidate_id, course['date'], course['end_min'], course['start_min'])).fetchall()
        if any(e['kind'] == 'absence' for e in events):
            status = 'absent'
        elif events:
            status = 'late'
            minutes = sum(min(e['end_min'],course['end_min'])-max(e['start_min'],course['start_min']) for e in events)
        elif status in ('absent', 'late'):
            # A removed/moved event is a correction, not a continuing absence.
            status, minutes = 'unrecorded', 0
    label = {'present':'Présent', 'absent':'Absent', 'late':'En retard', 'unrecorded':'Appel non renseigné'}[status]
    return dict(zoom_url=link, attendance_status=status, attendance_label=label, late_minutes=minutes)
