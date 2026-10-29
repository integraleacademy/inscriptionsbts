"""Timetable and availability panels inside the administrator's trainer file."""
from person_names import person_name
from contextlib import closing
from datetime import date, datetime, timedelta
from calendar import monthrange
import hashlib
import hmac
import json
import secrets
from zoneinfo import ZoneInfo
from flask import abort, jsonify, request, session, send_file
from io import BytesIO
from planning import PlanningError, _iso, _load_courses, _unavailability, ensure_planning_schema
from planning_holidays import public_holiday_name
from planning_portal import _requested_day, _date_label, _course_dto
from trainer_availability import (get_trainer_availability_state, ensure_trainer_availability_schema,
                                  availability_course_date, availability_day_courses)


def _now():
    return datetime.now(ZoneInfo('Europe/Paris'))


def _revision(conn, trainer_id):
    blocks=_unavailability(conn,trainer_id)
    return hashlib.sha256(json.dumps(blocks,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def get_admin_trainer_planning(conn, trainer_id, day=None):
    ensure_planning_schema(conn)
    selected=_requested_day(day)
    beginning=selected-timedelta(days=selected.weekday()); ending=beginning+timedelta(days=6)
    raw=_load_courses(conn,beginning.isoformat(),ending.isoformat(),trainer_id=trainer_id)
    courses=[]
    for course in raw:
        groups=course.get('groups') or []
        if groups:
            item=_course_dto(course,groups,'trainer')
            item.update(warning_labels=course['warning_labels'],incomplete=course['incomplete'])
            courses.append(item)
    days=[]
    for n in range(7):
        value=beginning+timedelta(days=n); holiday=public_holiday_name(value)
        days.append(dict(date=value.isoformat(),label=_date_label(value),short_label=_date_label(value,True),
            public_holiday=bool(holiday),day_label=holiday or '',kind='public_holiday' if holiday else 'school',
            courses=[c for c in courses if c['date']==value.isoformat()]))
    minutes=sum(c['duration_minutes'] for c in courses)
    trainer=conn.execute('SELECT nom,prenom FROM trainers WHERE id=?',(trainer_id,)).fetchone()
    return dict(role='trainer',heading='Planning de '+(person_name(trainer['nom'],trainer['prenom']) if trainer else 'formateur'),
        today=_now().date().isoformat(),date=selected.isoformat(),year=selected.year,month=selected.month,
        week_start=beginning.isoformat(),week_end=ending.isoformat(),week_label=_date_label(beginning)+' — '+_date_label(ending),
        previous=(beginning-timedelta(days=7)).isoformat(),next=(beginning+timedelta(days=7)).isoformat(),
        courses=courses,days=days,summary=dict(courses=len(courses),minutes=minutes,hours=minutes/60),
        pdf_url=f'/admin/formateurs/{trainer_id}/planning.pdf?date={selected.isoformat()}')


def get_admin_trainer_availability(conn, trainer_id, year, *, school_year=False):
    ensure_trainer_availability_schema(conn)
    state=get_trainer_availability_state(conn,trainer_id,year,school_year=school_year)
    state['revision']=_revision(conn,trainer_id)
    from trainer_notifications import notification_status
    blocks=[block for block in _unavailability(conn,trainer_id) if block['start_date']<=state['end'] and block['end_date']>=state['start']]
    for block in blocks:
        block['start_label']=date.fromisoformat(block['start_date']).strftime('%d/%m/%Y')
        block['end_label']=date.fromisoformat(block['end_date']).strftime('%d/%m/%Y')
        block['weekdays_label']='Tous les jours' if len(block['weekdays'])==7 else ', '.join(('Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche')[day] for day in block['weekdays'])
    return dict(state=state,blocks=blocks,year=year,
        save_url=f'/admin/formateurs/{trainer_id}/indisponibilites/jours',
        block_url=f'/admin/formateurs/{trainer_id}/indisponibilites/bloc/',
        courses_url=f'/admin/formateurs/{trainer_id}/indisponibilites/cours',
        planning_url=f'/admin/formateurs/{trainer_id}?tab=planning',
        notifications=notification_status(conn,trainer_id))


def trainer_export_bounds(args):
    allowed = {'date', 'period', 'start', 'end'}
    if set(args) - allowed or any(len(values) != 1 for _, values in args.lists()):
        raise ValueError('Choisissez une seule période.')
    selected = _requested_day(args.get('date'))
    period = args.get('period', 'week')
    if period == 'week':
        start = selected - timedelta(days=selected.weekday())
        end = start + timedelta(days=6)
    elif period == 'month':
        start = selected.replace(day=1)
        end = selected.replace(day=monthrange(selected.year, selected.month)[1])
    elif period == 'school_year':
        year = selected.year if selected.month >= 9 else selected.year - 1
        start, end = date(year, 9, 1), date(year+1, 7, 31)
    elif period == 'custom':
        start, end = _iso(args.get('start')), _iso(args.get('end'))
    else:
        raise ValueError('Choisissez une semaine, un mois, une année scolaire ou une période personnalisée.')
    if not 1900 <= start.year <= end.year <= 2200 or not 0 <= (end-start).days <= 366:
        raise ValueError('La période doit couvrir au maximum une année, entre 1900 et 2200.')
    return start, end


def build_trainer_period_pdf(conn, trainer_id, start, end):
    from planning_pdf import build_planning_pdf
    trainer = conn.execute('SELECT nom,prenom FROM trainers WHERE id=?', (trainer_id,)).fetchone()
    courses = _load_courses(conn, start.isoformat(), end.isoformat(), trainer_id=trainer_id)
    for course in courses:
        course['_promotion_labels'] = list(dict.fromkeys(g.get('promotion_name') or 'Promotion à préciser' for g in course['groups']))
    days = []
    day = start
    while day <= end:
        holiday = public_holiday_name(day)
        days.append(dict(date=day.isoformat(), kind='public_holiday' if holiday else 'school', label=holiday or '', public_holiday=bool(holiday)))
        day += timedelta(days=1)
    return build_planning_pdf({'nom': 'Planning de '+person_name(trainer['nom'],trainer['prenom'])},
        courses, days, start, end, mode='weekly', trainer_view=True)


def register_admin_trainer_planning(app,db_connect,require_admin):
    # Register the private financial checks alongside the admin trainer panels.
    from trainer_invoices import register_trainer_invoices
    register_trainer_invoices(app, db_connect, require_admin)

    def reply(payload,status=200):
        response=app.make_response((jsonify(payload),status));response.headers['Cache-Control']='private, no-store';response.vary.add('Cookie');return response
    def guard(mutation=False):
        if not require_admin():abort(403)
        if mutation:
            token=request.headers.get('X-CSRF-Token','');expected=session.get('_trainer_csrf','')
            if not expected or not hmac.compare_digest(token.encode(),expected.encode()):abort(400)
    def connect():
        conn=db_connect();ensure_trainer_availability_schema(conn);conn.commit();return conn
    def trainer_exists(conn,trainer_id):
        if not conn.execute('SELECT 1 FROM trainers WHERE id=?',(trainer_id,)).fetchone():abort(404)

    @app.get('/admin/formateurs/<trainer_id>/indisponibilites/cours')
    def admin_trainer_availability_courses(trainer_id):
        guard()
        try:
            day = availability_course_date(request.args)
            with closing(connect()) as conn:
                trainer_exists(conn, trainer_id)
                courses = availability_day_courses(conn, trainer_id, day)
            return reply(dict(ok=True, date=day, courses=courses))
        except PlanningError as error:
            return reply(dict(ok=False, message=str(error)), error.status)

    @app.get('/admin/formateurs/<trainer_id>/planning.pdf')
    def admin_trainer_planning_pdf(trainer_id):
        guard()
        try:
            start, end = trainer_export_bounds(request.args)
            with closing(connect()) as conn:
                trainer_exists(conn,trainer_id)
                data = build_trainer_period_pdf(conn,trainer_id,start,end)
            response=send_file(BytesIO(data),mimetype='application/pdf',as_attachment=False,
                download_name=f'planning-formateur-{start.isoformat()}-{end.isoformat()}.pdf')
            response.headers['Cache-Control']='private, no-store';response.vary.add('Cookie');return response
        except (ValueError, PlanningError) as error:abort(400, str(error))

    @app.post('/admin/formateurs/<trainer_id>/indisponibilites/jours')
    def admin_trainer_availability_days(trainer_id):
        guard(True);payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or set(payload)-{'dates','reason','expected_revision'}:abort(400)
        try:
            values=payload.get('dates')
            if not isinstance(values,list) or not 1<=len(values)<=740:raise PlanningError('Sélectionnez de 1 à 740 journées.')
            dates=sorted({_iso(value).isoformat() for value in values})
            if any(not 1900<=date.fromisoformat(day).year<=2200 for day in dates):raise PlanningError('Choisissez une année de 1900 à 2200.')
            reason=payload.get('reason','Indisponibilité ajoutée par l’équipe')
            if not isinstance(reason,str) or not 1<=len(reason.strip())<=240:raise PlanningError('Précisez un motif de 1 à 240 caractères.')
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE');trainer_exists(conn,trainer_id)
                if payload.get('expected_revision')!=_revision(conn,trainer_id):raise PlanningError('Les indisponibilités ont changé. Actualisez la fiche avant de recommencer.',status=409)
                courses=[c for c in _load_courses(conn,dates[0],dates[-1],trainer_id=trainer_id) if c['date'] in dates]
                if courses:
                    return reply(dict(ok=False,message='Des cours sont déjà programmés sur ces journées. Déplacez ou supprimez ces cours dans le planning avant de bloquer les dates.',
                        conflicts=[dict(date=c['date'],start=c['start'],end=c['end'],title=c['title'] or c['subject_name']) for c in courses]),409)
                for day in dates:
                    if public_holiday_name(date.fromisoformat(day)):raise PlanningError('Les jours fériés sont déjà bloqués automatiquement.')
                    conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                        (secrets.token_urlsafe(20),trainer_id,day,day,'[0,1,2,3,4,5,6]','[]',reason.strip()))
                conn.commit()
            return reply(dict(ok=True,message=f'{len(dates)} journée(s) bloquée(s).'))
        except PlanningError as error:return reply(dict(ok=False,message=str(error)),error.status)

    @app.delete('/admin/formateurs/<trainer_id>/indisponibilites/bloc/<block_id>')
    def admin_trainer_availability_remove(trainer_id,block_id):
        guard(True);payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or set(payload)-{'expected_revision'}:abort(400)
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');trainer_exists(conn,trainer_id)
            if payload.get('expected_revision')!=_revision(conn,trainer_id):return reply(dict(ok=False,message='Les indisponibilités ont changé. Actualisez la fiche.'),409)
            if not conn.execute('SELECT 1 FROM planning_trainer_unavailability WHERE id=? AND trainer_id=?',(block_id,trainer_id)).fetchone():abort(404)
            conn.execute('DELETE FROM planning_trainer_unavailability WHERE id=? AND trainer_id=?',(block_id,trainer_id))
            conn.execute('DELETE FROM planning_trainer_owned_absences WHERE block_id=? AND trainer_id=?',(block_id,trainer_id));conn.commit()
        return reply(dict(ok=True,message='Indisponibilité retirée. Les cours supprimés précédemment ne sont pas recréés.'))
