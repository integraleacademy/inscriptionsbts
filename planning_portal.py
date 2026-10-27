"""Read-only, identity-scoped timetables for student and trainer spaces.

A bearer dossier URL never grants timetable access. Every page and PDF resolves
an existing version-bound login and rebuilds its current promotion scope.
"""
from person_names import person_name
from contextlib import closing
from datetime import date, datetime, timedelta
from io import BytesIO
import re
from zoneinfo import ZoneInfo

from flask import abort, redirect, render_template, request, url_for

from candidate_access import get_authenticated_student
from trainer_access import get_authenticated_trainer
from planning import ensure_planning_schema, _calendar, _day, _load_courses
from planning_holidays import public_holiday_name

PARIS = ZoneInfo('Europe/Paris')
STUDENT_STATUSES = ('confirmee', 'reconfirmee', 'rentree')
_WEEKDAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
_MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')
_DAY_LABELS = {'school': 'À l’école', 'company': 'En entreprise', 'holiday': 'Vacances', 'closed': 'Fermeture', 'unconfigured': 'Calendrier à préciser'}


def _now_paris():
    return datetime.now(PARIS)


def _date_label(day, short=False):
    if short:
        return f'{_WEEKDAYS[day.weekday()][:3]}. {day.day}'
    return f'{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]} {day.year}'


def _requested_day(value=None):
    if value is None or value == '':
        return _now_paris().date()
    if isinstance(value, date) and not isinstance(value, datetime):
        parsed = value
    else:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Choisissez une date valide pour consulter le planning.')
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError('Cette date n’existe pas.') from None
    if not 1900 <= parsed.year <= 2200:
        raise ValueError('Choisissez une date entre 1900 et 2200.')
    return parsed


def _identity_scope(conn, role, identity_id):
    """Read current grants; no caller-supplied promotion can widen the scope."""
    if role not in ('student', 'trainer'):
        raise ValueError('Espace inconnu.')
    ensure_planning_schema(conn)
    if role == 'student':
        rows = conn.execute('''SELECT p.* FROM candidats c
            JOIN student_promotions s ON s.candidate_id=c.id
            JOIN promotions p ON p.id=s.promotion_id
            WHERE c.id=? AND p.active=1 AND upper(trim(c.bts))=p.bts
              AND COALESCE(c.rentree_annee,2026)=p.rentree_annee
              AND lower(trim(c.statut)) IN (?,?,?)''', (identity_id, *STUDENT_STATUSES)).fetchall()
        promotions = [dict(row) for row in rows]
        return {'promotions': promotions, 'heading': 'Mon planning', 'empty_message': '' if promotions else 'Ton planning apparaîtra après la confirmation de ton inscription et ton affectation à une promotion.'}
    trainer = conn.execute('SELECT id,nom,prenom,active FROM trainers WHERE id=?', (identity_id,)).fetchone()
    if not trainer or not trainer['active']:
        return {'promotions': [], 'heading': 'Mon planning', 'empty_message': 'Votre espace formateur n’est pas actif.'}
    promotions = [dict(row) for row in conn.execute('''SELECT p.* FROM promotions p
        JOIN trainer_promotions a ON a.promotion_id=p.id
        WHERE a.trainer_id=? AND p.active=1 ORDER BY p.nom''', (identity_id,))]
    full_name = person_name(trainer['nom'],trainer['prenom'])
    return {'promotions': promotions, 'heading': 'Planning de ' + full_name, 'empty_message': '' if promotions else 'Vos cours apparaîtront après votre affectation à une promotion.'}


def _safe_warnings(course, allowed_promotions):
    """Do not expose administrator budgets or names of another shared group."""
    result = []
    for warning in course.get('warnings') or []:
        if warning.get('promotion_id') and warning['promotion_id'] not in allowed_promotions:
            continue
        code = str(warning.get('code') or '')
        if 'room' in code:
            message = 'Salle à confirmer.'
            public_code = 'room_unconfirmed'
        elif 'trainer' in code:
            message = 'Formateur à confirmer.'
            public_code = 'trainer_unconfirmed'
        elif 'holiday' in code:
            message = 'Ce cours tombe un jour férié ; une confirmation de l’école est nécessaire.'
            public_code = 'public_holiday'
        elif 'subject' in code and 'budget' not in code:
            message = 'Matière à confirmer.'
            public_code = 'subject_unconfirmed'
        else:
            message = 'Informations du cours en cours de confirmation.'
            public_code = 'incomplete'
        if not any(item['message'] == message for item in result):
            result.append({'code': public_code, 'message': message})
    if not course.get('room_id') and not any('room' in item['code'] for item in result):
        result.append({'code': 'room_missing', 'message': 'Salle à confirmer.'})
    if course.get('incomplete') and not course.get('warnings') and not result:
        result.append({'code': 'incomplete', 'message': 'Informations du cours en cours de confirmation.'})
    return result


def _course_dto(course, groups, role, now=None):
    now = now or _now_paris()
    local = groups[0]
    live_state = ''
    if course['date'] == now.date().isoformat():
        minute = now.hour * 60 + now.minute
        if minute < course['start_min']:
            live_state = 'upcoming'
        elif minute < course['end_min']:
            live_state = 'ongoing'
    color = local.get('color') or '#66764e'
    if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
        color = '#66764e'
    subject = local.get('subject_name') or 'Matière à confirmer'
    warnings = _safe_warnings(course, {group['promotion_id'] for group in groups})
    safe_groups = [{'promotion_id': group['promotion_id'], 'promotion_name': group.get('promotion_name') or 'Promotion', 'subject_name': group.get('subject_name') or 'Matière à confirmer'} for group in groups]
    return dict(id=course['id'], kind=course.get('kind','course'), date=course['date'], date_label=_date_label(date.fromisoformat(course['date'])), start=course['start'], end=course['end'],
                title=course.get('title') or '', subject_name=subject, display_subject_name=subject,
                trainer_name=course.get('trainer_name') or 'Formateur à confirmer', room_name=course.get('room_name') or '',
                promotion_names=[group['promotion_name'] for group in safe_groups], groups=safe_groups,
                is_shared=bool(course.get('is_shared')), incomplete=bool(warnings), warnings=warnings,
                warning_labels=[warning['message'] for warning in warnings],
                color=color, live_state=live_state, live_label={'ongoing':'En cours','upcoming':'À venir'}.get(live_state,''),
                duration_minutes=course['duration_minutes'])


def _courses(conn, role, identity_id, promotions, start, end, now=None):
    allowed = {promotion['id'] for promotion in promotions}
    if not allowed:
        return []
    rows = _load_courses(conn, start.isoformat(), end.isoformat(), next(iter(allowed)) if role == 'student' else None, trainer_id=identity_id if role == 'trainer' else None)
    now = now or _now_paris()
    courses = []
    for course in rows:
        if role == 'trainer' and course['trainer_id'] != identity_id:
            continue
        groups = [group for group in course.get('groups') or [] if group.get('promotion_id') in allowed]
        if not groups:
            continue
        item = _course_dto(course, groups, role, now)
        if role == 'student':
            from student_course_details import student_details
            item.update(student_details(conn, identity_id, course))
        courses.append(item)
    return courses


def _days(conn, promotions, courses, start, end):
    calendars = [(promotion, *_calendar(conn, promotion['id'])) for promotion in promotions]
    days = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        name = public_holiday_name(cursor)
        day_courses = [course for course in courses if course['date'] == key]
        states = [_day(promotion, cursor, rules, exceptions) for promotion, rules, exceptions in calendars]
        if name:
            kind, day_label = 'public_holiday', name
        elif day_courses:
            kind, day_label = 'school', 'À l’école'
        elif len(states) == 1:
            kind = states[0]['kind']
            day_label = states[0].get('label') or _DAY_LABELS.get(kind, 'Aucun cours prévu')
        elif states and all(state['kind'] == states[0]['kind'] for state in states):
            kind = states[0]['kind']
            day_label = _DAY_LABELS.get(kind, 'Aucun cours prévu')
        else:
            kind, day_label = 'unconfigured', 'Aucun cours prévu'
        days.append(dict(date=key, label=_date_label(cursor), date_label=_date_label(cursor), short_label=_date_label(cursor, True),
                         kind=kind, day_label=day_label, public_holiday=bool(name), courses=day_courses))
        cursor += timedelta(days=1)
    return days


def get_portal_week(conn, role, identity_id, day=None):
    selected = _requested_day(day)
    start = selected - timedelta(days=selected.weekday())
    end = start + timedelta(days=6)
    scope = _identity_scope(conn, role, identity_id)
    courses = _courses(conn, role, identity_id, scope['promotions'], start, end)
    days = _days(conn, scope['promotions'], courses, start, end)
    base = '/formateur/planning' if role == 'trainer' else '/espace/planning'
    promotions = [dict(id=item['id'], name=item['nom'], bts=item['bts']) for item in scope['promotions']]
    total = sum(course['duration_minutes'] for course in courses)
    return dict(role=role, heading=scope['heading'], home_url='/formateur' if role == 'trainer' else '/espace/mon-dossier',
                planning_url=base, pdf_url=base+'.pdf?date='+selected.isoformat(),
                week_start=start.isoformat(), week_end=end.isoformat(), week_label=f'Du {start.day} {_MONTHS[start.month-1]} au {end.day} {_MONTHS[end.month-1]} {end.year}',
                previous_url=base+'?date='+(start-timedelta(days=7)).isoformat(), next_url=base+'?date='+(start+timedelta(days=7)).isoformat(),
                today_url=base, date_input=selected.isoformat(), today=_now_paris().date().isoformat(), days=days, courses=courses,
                empty_message=scope['empty_message'] or ('Aucun cours prévu cette semaine.' if role == 'trainer' else 'Aucun cours prévu cette semaine.'),
                summary=dict(courses=len(courses), hours=total/60, minutes=total), promotions=promotions,
                promotion_label=' · '.join(item['name'] for item in promotions))


def get_portal_today(conn, role, identity_id):
    now = _now_paris()
    today = now.date()
    scope = _identity_scope(conn, role, identity_id)
    # Find future sessions across the full training range, including a later year.
    ends = []
    for promotion in scope['promotions']:
        try:
            ends.append(date.fromisoformat(promotion.get('date_fin') or ''))
        except (TypeError, ValueError):
            pass
    end = max([today+timedelta(days=366), *ends])
    end = min(end, today+timedelta(days=1096))
    courses = _courses(conn, role, identity_id, scope['promotions'], today, end, now)
    todays = [course for course in courses if course['date'] == today.isoformat()]
    upcoming = [course for course in courses if course['date'] > today.isoformat()][:3]
    day = _days(conn, scope['promotions'], todays, today, today)[0]
    return dict(role=role, today=today.isoformat(), today_label=_date_label(today),
                planning_url='/formateur/planning' if role == 'trainer' else '/espace/planning',
                day_kind=day['kind'], day_label=day['day_label'], public_holiday=day['public_holiday'],
                courses=todays, next_courses=upcoming, empty_message=scope['empty_message'] or 'Aucun cours prévu aujourd’hui.', requires_login=False)


def register_planning_portal(app, db_connect):
    def secure(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.vary.add('Cookie')
        return response

    def identity(role):
        if role == 'trainer':
            person = get_authenticated_trainer(app, db_connect)
            if not person:
                return None, secure(redirect(url_for('trainer_login')))
            return person['id'], None
        person = get_authenticated_student(app, db_connect, allow_initial=True)
        if not person:
            return None, secure(redirect(url_for('candidate_login')))
        if person['must_change']:
            return None, secure(redirect(url_for('student_change_password')))
        return person['candidate_id'], None

    def view(role, pdf=False):
        person_id, blocked = identity(role)
        if blocked is not None:
            return blocked
        if set(request.args) - {'date'} or len(request.args.getlist('date')) > 1:
            abort(400, 'Utilisez uniquement une date pour consulter votre planning.')
        try:
            with closing(db_connect()) as conn:
                snapshot = get_portal_week(conn, role, person_id, request.args.get('date'))
        except ValueError as error:
            abort(400, str(error))
        if pdf:
            from flask import send_file
            from planning_pdf import build_portal_planning_pdf
            result = send_file(BytesIO(build_portal_planning_pdf(snapshot)), mimetype='application/pdf', as_attachment=False,
                               download_name=f"mon-planning-{snapshot['week_start']}.pdf")
        else:
            result = app.make_response(render_template('portal_planning.html', title='Mon planning · Intégrale Academy', portal_planning=snapshot))
        return secure(result)

    def jump_to_month(role):
        _person_id, blocked = identity(role)
        if blocked is not None:
            return blocked
        if set(request.args) != {'month', 'year'} or any(len(values) != 1 for _, values in request.args.lists()):
            abort(400, 'Choisissez un mois et une année.')
        month, year = request.args.get('month', ''), request.args.get('year', '')
        if (not re.fullmatch(r'(?:0?[1-9]|1[0-2])', month)
                or not re.fullmatch(r'\d{4}', year) or not 1900 <= int(year) <= 2200):
            abort(400, 'Choisissez un mois valide et une année entre 1900 et 2200.')
        selected = date(int(year), int(month), 1).isoformat()
        endpoint = 'trainer_planning' if role == 'trainer' else 'student_planning'
        return secure(redirect(url_for(endpoint, date=selected)))

    @app.get('/formateur/planning/mois')
    def trainer_planning_month():
        return jump_to_month('trainer')

    @app.get('/espace/planning/mois')
    def student_planning_month():
        return jump_to_month('student')

    @app.get('/formateur/planning')
    def trainer_planning():
        return view('trainer')

    @app.get('/espace/planning')
    def student_planning():
        return view('student')

    @app.get('/formateur/planning.pdf')
    def trainer_planning_pdf():
        return view('trainer', True)

    @app.get('/espace/planning.pdf')
    def student_planning_pdf():
        return view('student', True)
