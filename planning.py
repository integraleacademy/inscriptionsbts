"""Annual BTS planning: explicit school/company days before course scheduling.

Every mutation acquires a SQLite write transaction before validation. Batch
previews do not persist data; commits recheck the selected occurrences together.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
from io import BytesIO
import math
import re
import secrets
import sqlite3

from flask import abort, jsonify, redirect, render_template, request, session, url_for, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from promotions import ensure_promotion_schema, list_promotions

KINDS={'school','company','holiday','closed'}
MAX_BATCH=500


def _has_table(conn,name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def ensure_planning_schema(conn):
    ensure_promotion_schema(conn)
    conn.execute('SAVEPOINT planning_schema')
    try:
        for sql in (
            '''CREATE TABLE IF NOT EXISTS planning_rooms(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1)''',
            '''CREATE TABLE IF NOT EXISTS planning_subjects(id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,name TEXT NOT NULL,
                trainer_id TEXT NOT NULL,color TEXT NOT NULL,planned_hours REAL,UNIQUE(promotion_id,name))''',
            '''CREATE TABLE IF NOT EXISTS planning_calendar_rules(id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,weekdays TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS planning_day_exceptions(promotion_id TEXT NOT NULL,date TEXT NOT NULL,kind TEXT NOT NULL,
                label TEXT NOT NULL,PRIMARY KEY(promotion_id,date))''',
            '''CREATE TABLE IF NOT EXISTS planning_courses(id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,subject_id TEXT NOT NULL,
                trainer_id TEXT NOT NULL,room_id TEXT,date TEXT NOT NULL,start_min INTEGER NOT NULL,end_min INTEGER NOT NULL,
                title TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS planning_trainer_unavailability(id TEXT PRIMARY KEY,trainer_id TEXT NOT NULL,
                start_date TEXT NOT NULL,end_date TEXT NOT NULL,weekdays TEXT NOT NULL,times TEXT NOT NULL,reason TEXT NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS planning_courses_date ON planning_courses(date,start_min,end_min)',
            'CREATE INDEX IF NOT EXISTS planning_courses_promotion ON planning_courses(promotion_id,date)',
            'CREATE INDEX IF NOT EXISTS planning_unavailable_trainer ON planning_trainer_unavailability(trainer_id,start_date,end_date)',
        ):conn.execute(sql)
        conn.execute('RELEASE SAVEPOINT planning_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT planning_schema');conn.execute('RELEASE SAVEPOINT planning_schema');raise


class PlanningError(ValueError):
    def __init__(self,message,conflicts=None,status=400):
        super().__init__(message);self.conflicts=conflicts or [];self.status=status


def _iso(value,field='date'):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise PlanningError('Indiquez une date valide au format AAAA-MM-JJ.',[{'type':'invalid_date','field':field}])
    try:return date.fromisoformat(value)
    except ValueError:raise PlanningError('Cette date n’existe pas.',[{'type':'invalid_date','field':field}])


def _minutes(value,end=False):
    if end and value=='24:00':return 1440
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise PlanningError('Indiquez une heure valide au format HH:MM.')
    hour,minute=map(int,value.split(':'));return hour*60+minute


def _clock(value):return f'{value//60:02d}:{value%60:02d}'


def _text(value,label,maximum=160,required=False):
    if not isinstance(value,str) or len(value.strip())>maximum or any(ord(c)<32 for c in value):raise PlanningError(f'Vérifiez {label}.')
    value=value.strip()
    if required and not value:raise PlanningError(f'Renseignez {label}.')
    return value


def _weekdays(value,default=None):
    if value is None and default is not None:return default
    if not isinstance(value,list) or not value or len(value)>7 or any(isinstance(v,bool) or not isinstance(v,int) or v not in range(7) for v in value):raise PlanningError('Choisissez au moins un jour de la semaine (lundi = 0, dimanche = 6).')
    return sorted(set(value))


def _range(start,end,max_days=740):
    beginning=_iso(start,'start_date');ending=_iso(end,'end_date')
    if ending<beginning or (ending-beginning).days>max_days:raise PlanningError('Vérifiez les dates de début et de fin de la période.')
    return beginning,ending


def _dates(start,end):
    day=start
    while day<=end:
        yield day
        if day==end:break
        day+=timedelta(days=1)


def _promotion(conn,promotion_id,ready=False):
    if not isinstance(promotion_id,str) or not 1<=len(promotion_id)<=128:raise PlanningError('Choisissez une promotion valide.')
    row=conn.execute('SELECT * FROM promotions WHERE id=?',(promotion_id,)).fetchone()
    if not row:raise PlanningError('Promotion introuvable.',status=404)
    result=dict(row)
    if ready and (not result['active'] or not result.get('date_debut') or not result.get('date_fin')):raise PlanningError('Complétez les dates de cette promotion et vérifiez qu’elle est active avant de construire son planning.')
    return result


def _calendar(conn,promotion_id):
    rules=[]
    for row in conn.execute('SELECT * FROM planning_calendar_rules WHERE promotion_id=? ORDER BY start_date,id',(promotion_id,)):
        item=dict(row);item['weekdays']=json.loads(item['weekdays']);rules.append(item)
    exceptions=[dict(row) for row in conn.execute('SELECT * FROM planning_day_exceptions WHERE promotion_id=? ORDER BY date',(promotion_id,))]
    return rules,exceptions


def _day(promotion,day,rules,exceptions):
    key=day.isoformat()
    if not promotion.get('date_debut') or not promotion.get('date_fin'):return {'date':key,'kind':'unconfigured','label':'Dates de la promotion à compléter'}
    if key<promotion['date_debut'] or key>promotion['date_fin']:return {'date':key,'kind':'closed','label':'Hors des dates de la promotion'}
    exception=next((item for item in exceptions if item['date']==key),None)
    if exception:return {'date':key,'kind':exception['kind'],'label':exception['label']}
    matches=[item for item in rules if item['start_date']<=key<=item['end_date'] and day.weekday() in item['weekdays']]
    blocked=[item for item in matches if item['kind'] in ('holiday','closed')]
    selected=(blocked or matches)
    if selected:
        item=selected[-1];return {'date':key,'kind':item['kind'],'label':item['label']}
    return {'date':key,'kind':'unconfigured','label':'Alternance à définir'}


def _load_courses(conn,start=None,end=None,promotion_id=None):
    if not _has_table(conn,'trainers'):return []
    sql='''SELECT c.*,s.name AS subject_name,s.color,t.nom AS trainer_nom,t.prenom AS trainer_prenom,
        r.name AS room_name,p.nom AS promotion_name FROM planning_courses c
        JOIN planning_subjects s ON s.id=c.subject_id JOIN trainers t ON t.id=c.trainer_id
        LEFT JOIN planning_rooms r ON r.id=c.room_id JOIN promotions p ON p.id=c.promotion_id WHERE 1=1'''
    args=[]
    if start:sql+=' AND c.date>=?';args.append(start)
    if end:sql+=' AND c.date<=?';args.append(end)
    if promotion_id:sql+=' AND c.promotion_id=?';args.append(promotion_id)
    sql+=' ORDER BY c.date,c.start_min,c.id'
    items=[]
    for row in conn.execute(sql,args):
        item=dict(row);item['start']=_clock(item['start_min']);item['end']=_clock(item['end_min'])
        item['duration_minutes']=item['end_min']-item['start_min']
        item['trainer_name']=f"{item.pop('trainer_prenom') or ''} {item.pop('trainer_nom') or ''}".strip()
        items.append(item)
    return items


def get_planning_snapshot(conn,promotion_id,start=None,end=None):
    ensure_planning_schema(conn);promotion=_promotion(conn,promotion_id)
    start=start or promotion.get('date_debut');end=end or promotion.get('date_fin')
    if start and end:beginning,ending=_range(start,end)
    else:beginning=ending=None
    rules,exceptions=_calendar(conn,promotion_id)
    days=[_day(promotion,day,rules,exceptions) for day in _dates(beginning,ending)] if beginning else []
    courses=_load_courses(conn,start,end,promotion_id) if beginning else []
    subjects=[];trainers=[]
    if _has_table(conn,'trainers'):
        for row in conn.execute('''SELECT s.*,t.nom,t.prenom,COALESCE((SELECT SUM(c.end_min-c.start_min)/60.0 FROM planning_courses c WHERE c.subject_id=s.id),0) AS scheduled_hours
            FROM planning_subjects s JOIN trainers t ON t.id=s.trainer_id WHERE s.promotion_id=? ORDER BY s.name''',(promotion_id,)):
            item=dict(row);item['trainer_name']=f"{item.pop('prenom') or ''} {item.pop('nom') or ''}".strip();subjects.append(item)
        trainers=[dict(row) for row in conn.execute('SELECT t.id,t.nom,t.prenom,t.email FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE a.promotion_id=? AND t.active=1 ORDER BY t.nom,t.prenom',(promotion_id,))]
    return dict(promotion=promotion,days=days,rules=rules,exceptions=exceptions,subjects=subjects,
                rooms=[dict(row) for row in conn.execute('SELECT * FROM planning_rooms ORDER BY name')],trainers=trainers,
                courses=courses,calendar_configured=bool(rules or exceptions),start=start,end=end)


def _unavailability(conn,trainer_id=None):
    sql='SELECT * FROM planning_trainer_unavailability';args=[]
    if trainer_id:sql+=' WHERE trainer_id=?';args.append(trainer_id)
    items=[]
    for row in conn.execute(sql+' ORDER BY start_date,id',args):
        item=dict(row);item['weekdays']=json.loads(item['weekdays']);item['times']=json.loads(item['times']);items.append(item)
    return items


def _overlap(a,b):return a['start_min']<b['end_min'] and a['end_min']>b['start_min']


def _course(conn,data,existing=None):
    if not isinstance(data,dict):raise PlanningError('Les données du cours sont invalides.')
    merged=dict(existing or {});merged.update(data)
    promotion_id=merged.get('promotion_id');promotion=_promotion(conn,promotion_id,ready=True)
    if not isinstance(merged.get('subject_id'),str):raise PlanningError('Choisissez une matière valide.')
    subject=conn.execute('SELECT * FROM planning_subjects WHERE id=? AND promotion_id=?',(merged.get('subject_id'),promotion_id)).fetchone()
    if not subject:raise PlanningError('Choisissez une matière de cette promotion.')
    trainer_id=merged.get('trainer_id')
    if trainer_id is not None and not isinstance(trainer_id,str):raise PlanningError('Choisissez un formateur valide.')
    trainer_id=trainer_id or subject['trainer_id']
    if not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE t.id=? AND t.active=1 AND a.promotion_id=?',(trainer_id,promotion_id)).fetchone():raise PlanningError('Le formateur doit être actif et affecté à cette promotion.')
    room_id=merged.get('room_id')
    if room_id is not None and not isinstance(room_id,str):raise PlanningError('Choisissez une salle valide.')
    room_id=room_id or None
    if room_id and not conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1',(room_id,)).fetchone():raise PlanningError('Choisissez une salle active.')
    day=_iso(merged.get('date'))
    start=_minutes(merged.get('start'));end=_minutes(merged.get('end'),end=True)
    if end<=start:raise PlanningError('L’heure de fin doit être postérieure à l’heure de début.')
    return dict(promotion_id=promotion_id,subject_id=subject['id'],trainer_id=trainer_id,room_id=room_id,date=day.isoformat(),start=_clock(start),end=_clock(end),start_min=start,end_min=end,title=_text(merged.get('title',''),'le titre du cours',160))


def _conflicts(conn,course,exclude_id=None,pool=None,calendar=None,unavailable=None):
    found=[];day=_iso(course['date']);promotion=_promotion(conn,course['promotion_id'])
    if not promotion.get('date_debut') or not promotion.get('date_fin') or not promotion['date_debut']<=course['date']<=promotion['date_fin']:
        found.append(dict(type='outside_promotion',message='Ce cours est en dehors des dates de la promotion.',date=course['date']))
    rules,exceptions=calendar if calendar is not None else _calendar(conn,course['promotion_id'])
    day_state=_day(promotion,day,rules,exceptions)
    if day_state['kind']!='school':found.append(dict(type='not_school',message='Ce jour n’est pas défini comme une journée école : '+day_state['label']+'.',date=course['date']))
    rows=pool if pool is not None else _load_courses(conn,course['date'],course['date'])
    for other in rows:
        if (exclude_id is not None and other.get('id')==exclude_id) or other['date']!=course['date'] or not _overlap(course,other):continue
        for resource,kind,label in [('promotion_id','promotion_overlap','Cette promotion a déjà un cours'),('trainer_id','trainer_overlap','Ce formateur intervient déjà sur un autre cours'),('room_id','room_overlap','Cette salle est déjà réservée')]:
            if course.get(resource) and course.get(resource)==other.get(resource):
                found.append(dict(type=kind,message=f"{label}, de {_clock(other['start_min'])} à {_clock(other['end_min'])}.",date=course['date'],course_id=other.get('id'),promotion_id=other.get('promotion_id'),promotion_name=other.get('promotion_name',''),subject_name=other.get('subject_name','')))
    for block in unavailable if unavailable is not None else _unavailability(conn,course['trainer_id']):
        if block['trainer_id']!=course['trainer_id'] or not block['start_date']<=course['date']<=block['end_date'] or day.weekday() not in block['weekdays']:continue
        intervals=block['times'] or [{'start':'00:00','end':'24:00'}]
        if any(course['start_min']<_minutes(slot['end'],True) and course['end_min']>_minutes(slot['start']) for slot in intervals):
            found.append(dict(type='unavailable',message='Formateur indisponible : '+block['reason'],date=course['date'],unavailability_id=block.get('id')))
    return found


def _course_issues_for_calendar(conn,promotion_id,rules,exceptions):
    promotion=_promotion(conn,promotion_id)
    return [dict(type='existing_course',message='Un cours existe sur un jour qui ne serait plus à l’école.',date=c['date'],course_id=c['id'],subject_name=c['subject_name'],start=c['start'],end=c['end']) for c in _load_courses(conn,promotion_id=promotion_id) if _day(promotion,_iso(c['date']),rules,exceptions)['kind']!='school']


def _base_rule_conflicts(rules):
    issues=[]
    for index,first in enumerate(rules):
        if first['kind'] not in ('school','company'):continue
        for second in rules[index+1:]:
            if second['kind'] not in ('school','company') or first['kind']==second['kind']:continue
            start=max(first['start_date'],second['start_date']);end=min(first['end_date'],second['end_date'])
            if start>end:continue
            overlap=set(first['weekdays'])&set(second['weekdays'])
            days=[day.isoformat() for day in _dates(_iso(start),_iso(end)) if day.weekday() in overlap]
            if days:issues.append(dict(type='calendar_overlap',message='Ces règles définissent les mêmes jours à la fois à l’école et en entreprise. Modifiez la règle existante ou utilisez une exception.',dates=days[:30],rule_id=second.get('id')))
    return issues


def validate_promotion_change(conn,promotion_id,data):
    """Read-only guard used by the promotion editor; never initializes or commits."""
    if not _has_table(conn,'planning_courses'):return []
    current=conn.execute('SELECT * FROM promotions WHERE id=?',(promotion_id,)).fetchone()
    if not current:return []
    merged=dict(current);merged.update(data);issues=[]
    courses=_load_courses(conn,promotion_id=promotion_id)
    for course in courses:
        if not merged.get('date_debut') or not merged.get('date_fin') or not merged['date_debut']<=course['date']<=merged['date_fin']:
            issues.append(dict(type='outside_promotion',message='Un cours existant serait en dehors des nouvelles dates.',course_id=course['id'],date=course['date']))
    for row in conn.execute('SELECT id,start_date,end_date FROM planning_calendar_rules WHERE promotion_id=?',(promotion_id,)):
        if not merged.get('date_debut') or not merged.get('date_fin') or row['start_date']<merged['date_debut'] or row['end_date']>merged['date_fin']:
            issues.append(dict(type='calendar_outside',message='Une règle d’alternance dépasse les nouvelles dates. Modifiez-la avant de réduire la promotion.',rule_id=row['id']))
    for row in conn.execute('SELECT date FROM planning_day_exceptions WHERE promotion_id=?',(promotion_id,)):
        if not merged.get('date_debut') or not merged.get('date_fin') or not merged['date_debut']<=row['date']<=merged['date_fin']:
            issues.append(dict(type='exception_outside',message='Une exception dépasse les nouvelles dates. Modifiez-la avant de réduire la promotion.',date=row['date']))
    return issues


def validate_trainer_promotions_change(conn,trainer_id,promotion_ids):
    if not _has_table(conn,'planning_courses'):return []
    granted=set(promotion_ids);issues=[];today=date.today().isoformat()
    for row in conn.execute('SELECT id,promotion_id,date FROM planning_courses WHERE trainer_id=? AND date>=?',(trainer_id,today)):
        if row['promotion_id'] not in granted:issues.append(dict(type='trainer_courses',message='Ce formateur a encore un cours à venir dans une promotion retirée.',course_id=row['id'],promotion_id=row['promotion_id'],date=row['date']))
    for row in conn.execute('SELECT id,name,promotion_id FROM planning_subjects WHERE trainer_id=?',(trainer_id,)):
        if row['promotion_id'] not in granted:issues.append(dict(type='trainer_subjects',message='Attribuez cette matière à un autre formateur avant de retirer la promotion : '+row['name'],subject_id=row['id'],promotion_id=row['promotion_id']))
    return issues


def register_planning(app,db_connect,require_admin):
    serializer=URLSafeTimedSerializer(app.secret_key,salt='bts-planning-preview-v1')

    def csrf():
        if '_planning_csrf' not in session:session['_planning_csrf']=secrets.token_urlsafe(32)
        return session['_planning_csrf']

    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise PlanningError('Envoyez un objet JSON valide.')
        return value

    def guard(mutation=False):
        if not require_admin():abort(403)
        if mutation:
            payload=request.get_json(silent=True) or {}
            token=request.headers.get('X-CSRF-Token') or (payload.get('csrf_token','') if isinstance(payload,dict) else '')
            expected=session.get('_planning_csrf','')
            if not isinstance(token,str) or not expected or not hmac.compare_digest(token.encode(),expected.encode()):abort(400,'Rechargez la page avant de réessayer.')

    def result(data=None,status=200,**values):
        payload=dict(ok=True);payload.update(data or {});payload.update(values)
        response=app.make_response((jsonify(payload),status));response.headers['Cache-Control']='no-store';return response

    def fail(error):return result(dict(ok=False,message=str(error),conflicts=error.conflicts),error.status)

    def connect():
        conn=db_connect();ensure_planning_schema(conn);return conn

    def transact(operation):
        guard(True)
        try:
            payload=body()
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                answer=operation(conn,payload)
                conn.commit()
            return result(answer)
        except PlanningError as error:return fail(error)
        except sqlite3.IntegrityError:return fail(PlanningError('Ce nom existe déjà. Choisissez un autre nom.',status=409))
        except sqlite3.OperationalError as error:
            if 'locked' in str(error).lower():return fail(PlanningError('Une autre modification est en cours. Rechargez puis réessayez.',status=409))
            raise

    def reject(issues,message='Cette modification crée des conflits. Aucun changement n’a été enregistré.'):
        if issues:raise PlanningError(message,issues,409)

    def persist(conn,course,course_id=None,version=None):
        now=datetime.now(timezone.utc).isoformat()
        if course_id:
            conn.execute('UPDATE planning_courses SET promotion_id=?,subject_id=?,trainer_id=?,room_id=?,date=?,start_min=?,end_min=?,title=?,version=version+1,updated_at=? WHERE id=?',(*(course[key] for key in ('promotion_id','subject_id','trainer_id','room_id','date','start_min','end_min','title')),now,course_id))
        else:
            course_id=secrets.token_urlsafe(24)
            conn.execute('INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(course_id,*(course[key] for key in ('promotion_id','subject_id','trainer_id','room_id','date','start_min','end_min','title')),now,now))
        return course_id

    def existing_course(conn,course_id,payload,require_version=False):
        row=next((c for c in _load_courses(conn) if c['id']==course_id),None)
        if not row:raise PlanningError('Cours introuvable.',status=404)
        if require_version and (isinstance(payload.get('version'),bool) or not isinstance(payload.get('version'),int) or payload['version']<1):raise PlanningError('Rechargez le cours avant de le modifier : sa version est requise.',[{'type':'version_required','course_id':course_id}])
        if payload.get('version') is not None and payload['version']!=row['version']:raise PlanningError('Ce cours a été modifié entre-temps. Rechargez le planning.',[{'type':'stale','course_id':course_id}],409)
        return row

    @app.context_processor
    def planning_context():return dict(planning_csrf_token=csrf())

    @app.get('/admin/planning')
    def planning_admin():
        if not require_admin() and 'login' in app.view_functions:return redirect(url_for('login',next=request.full_path.rstrip('?')))
        guard()
        with closing(connect()) as conn:promotions=list_promotions(conn)
        response=app.make_response(render_template('planning_admin.html',title='Planning annuel · Plateforme de gestion des BTS',promotions=promotions,selected_promotion=request.args.get('promotion_id',''),csrf_token=csrf()))
        response.headers['Cache-Control']='no-store';return response

    @app.get('/admin/planning/api/state')
    def planning_state():
        guard()
        try:
            with closing(connect()) as conn:snapshot=get_planning_snapshot(conn,request.args.get('promotion_id'),request.args.get('start'),request.args.get('end'))
            return result(snapshot)
        except PlanningError as error:return fail(error)

    @app.get('/admin/planning/export.pdf')
    def planning_export():
        guard()
        try:
            view=request.args.get('view','weekly')
            if view not in ('weekly','annual'):raise PlanningError('Choisissez un export hebdomadaire ou annuel.')
            with closing(connect()) as conn:
                snapshot=get_planning_snapshot(conn,request.args.get('promotion_id'),request.args.get('start'),request.args.get('end'))
            if not snapshot['promotion'].get('date_debut') or not snapshot['promotion'].get('date_fin'):
                raise PlanningError('Complétez les dates de la promotion avant d’exporter le planning.')
            from planning_pdf import build_planning_pdf
            pdf=build_planning_pdf(snapshot['promotion'],snapshot['courses'],snapshot['days'],snapshot['start'],snapshot['end'],mode=view)
            code=re.sub(r'[^A-Za-z0-9_-]','',snapshot['promotion'].get('bts','BTS')) or 'BTS'
            response=send_file(BytesIO(pdf),mimetype='application/pdf',as_attachment=False,download_name=f"planning-{code}-{snapshot['start']}-{snapshot['end']}.pdf")
            response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
            return response
        except PlanningError as error:return fail(error)
        except ValueError as error:return fail(PlanningError(str(error)))

    def rule_values(conn,payload,existing=None):
        values=dict(existing or {});values.update(payload);promotion=_promotion(conn,values.get('promotion_id'),True)
        start,end=_range(values.get('start_date'),values.get('end_date'))
        if start.isoformat()<promotion['date_debut'] or end.isoformat()>promotion['date_fin']:raise PlanningError('La règle doit rester dans les dates de la promotion.')
        kind=values.get('kind')
        if not isinstance(kind,str) or kind not in KINDS:raise PlanningError('Choisissez école, entreprise, vacances ou fermeture.')
        return dict(promotion_id=promotion['id'],start_date=start.isoformat(),end_date=end.isoformat(),weekdays=_weekdays(values.get('weekdays')),kind=kind,label=_text(values.get('label',''),'le libellé',180))

    @app.post('/admin/planning/api/calendar/rules')
    def planning_rule_create():
        def operation(conn,payload):
            rule=rule_values(conn,payload);rule['id']=secrets.token_urlsafe(24)
            rules,exceptions=_calendar(conn,rule['promotion_id']);rules.append(rule)
            reject(_base_rule_conflicts(rules));reject(_course_issues_for_calendar(conn,rule['promotion_id'],rules,exceptions))
            conn.execute('INSERT INTO planning_calendar_rules(id,promotion_id,start_date,end_date,weekdays,kind,label) VALUES(?,?,?,?,?,?,?)',(rule['id'],rule['promotion_id'],rule['start_date'],rule['end_date'],json.dumps(rule['weekdays']),rule['kind'],rule['label']))
            return dict(rule=rule,message='Règle d’alternance enregistrée.')
        return transact(operation)

    @app.route('/admin/planning/api/calendar/rules/<rule_id>',methods=['PUT','DELETE'])
    def planning_rule_update(rule_id):
        def operation(conn,payload):
            row=conn.execute('SELECT * FROM planning_calendar_rules WHERE id=?',(rule_id,)).fetchone()
            if not row:raise PlanningError('Règle introuvable.',status=404)
            existing=dict(row);existing['weekdays']=json.loads(existing['weekdays'])
            rules,exceptions=_calendar(conn,row['promotion_id']);rules=[r for r in rules if r['id']!=rule_id]
            if request.method=='PUT':
                rule=rule_values(conn,payload,existing)
                if rule['promotion_id']!=row['promotion_id']:raise PlanningError('Une règle ne peut pas être déplacée vers une autre promotion.')
                rule['id']=rule_id;rules.append(rule);reject(_base_rule_conflicts(rules))
            reject(_course_issues_for_calendar(conn,row['promotion_id'],rules,exceptions))
            if request.method=='DELETE':conn.execute('DELETE FROM planning_calendar_rules WHERE id=?',(rule_id,));return dict(message='Règle supprimée.')
            conn.execute('UPDATE planning_calendar_rules SET start_date=?,end_date=?,weekdays=?,kind=?,label=? WHERE id=?',(rule['start_date'],rule['end_date'],json.dumps(rule['weekdays']),rule['kind'],rule['label'],rule_id))
            return dict(rule=rule,message='Règle mise à jour.')
        return transact(operation)

    @app.put('/admin/planning/api/calendar/exceptions')
    def planning_exception_put():
        def operation(conn,payload):
            promotion=_promotion(conn,payload.get('promotion_id'),True);day=_iso(payload.get('date')).isoformat();kind=payload.get('kind')
            if not promotion['date_debut']<=day<=promotion['date_fin'] or not isinstance(kind,str) or kind not in KINDS:raise PlanningError('Choisissez un jour de la promotion et un type de journée valide.')
            label=_text(payload.get('label',''),'le libellé',180);rules,exceptions=_calendar(conn,promotion['id'])
            exceptions=[item for item in exceptions if item['date']!=day]+[dict(date=day,kind=kind,label=label)]
            reject(_course_issues_for_calendar(conn,promotion['id'],rules,exceptions))
            conn.execute('INSERT INTO planning_day_exceptions(promotion_id,date,kind,label) VALUES(?,?,?,?) ON CONFLICT(promotion_id,date) DO UPDATE SET kind=excluded.kind,label=excluded.label',(promotion['id'],day,kind,label))
            return dict(message='Exception enregistrée.')
        return transact(operation)

    @app.delete('/admin/planning/api/calendar/exceptions/<promotion_id>/<day>')
    def planning_exception_delete(promotion_id,day):
        def operation(conn,payload):
            _iso(day);_promotion(conn,promotion_id);rules,exceptions=_calendar(conn,promotion_id)
            reject(_course_issues_for_calendar(conn,promotion_id,rules,[item for item in exceptions if item['date']!=day]))
            conn.execute('DELETE FROM planning_day_exceptions WHERE promotion_id=? AND date=?',(promotion_id,day));return dict(message='Exception supprimée.')
        return transact(operation)

    @app.route('/admin/planning/api/rooms',methods=['POST'])
    @app.route('/admin/planning/api/rooms/<room_id>',methods=['PUT','DELETE'])
    def planning_room(room_id=None):
        def operation(conn,payload):
            old=conn.execute('SELECT * FROM planning_rooms WHERE id=?',(room_id,)).fetchone() if room_id else None
            if room_id and not old:raise PlanningError('Salle introuvable.',status=404)
            if request.method=='DELETE':
                reject([dict(type='room_used',message='Cette salle est utilisée par des cours existants. Réaffectez-les avant de la supprimer.')] if conn.execute('SELECT 1 FROM planning_courses WHERE room_id=? LIMIT 1',(room_id,)).fetchone() else [])
                conn.execute('DELETE FROM planning_rooms WHERE id=?',(room_id,));return dict(message='Salle supprimée.')
            name=_text(payload.get('name',old['name'] if old else ''),'le nom de la salle',100,True)
            active=payload.get('active',old['active'] if old else 1)
            if active not in (True,False,0,1):raise PlanningError('L’état de la salle est invalide.')
            if not active and room_id:reject([dict(type='room_used',message='La salle reste utilisée par des cours. Réaffectez-les avant de la désactiver.')] if conn.execute('SELECT 1 FROM planning_courses WHERE room_id=? LIMIT 1',(room_id,)).fetchone() else [])
            rid=room_id or secrets.token_urlsafe(24)
            conn.execute('INSERT INTO planning_rooms(id,name,active) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,active=excluded.active',(rid,name,int(active)))
            return dict(room=dict(id=rid,name=name,active=bool(active)),message='Salle enregistrée.')
        return transact(operation)

    @app.route('/admin/planning/api/subjects',methods=['POST'])
    @app.route('/admin/planning/api/subjects/<subject_id>',methods=['PUT','DELETE'])
    def planning_subject(subject_id=None):
        def operation(conn,payload):
            old=conn.execute('SELECT * FROM planning_subjects WHERE id=?',(subject_id,)).fetchone() if subject_id else None
            if subject_id and not old:raise PlanningError('Matière introuvable.',status=404)
            if request.method=='DELETE':
                reject([dict(type='subject_used',message='Cette matière comporte encore des cours. Supprimez ou réaffectez ces cours avant de la retirer.')] if conn.execute('SELECT 1 FROM planning_courses WHERE subject_id=? LIMIT 1',(subject_id,)).fetchone() else [])
                conn.execute('DELETE FROM planning_subjects WHERE id=?',(subject_id,));return dict(message='Matière supprimée.')
            data=dict(old or {});data.update(payload);promotion=_promotion(conn,data.get('promotion_id'),True)
            if old and old['promotion_id']!=promotion['id']:raise PlanningError('Une matière ne peut pas changer de promotion.')
            trainer_id=data.get('trainer_id')
            if not isinstance(trainer_id,str):raise PlanningError('Choisissez un formateur valide.')
            if not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE t.id=? AND t.active=1 AND a.promotion_id=?',(trainer_id,promotion['id'])).fetchone():raise PlanningError('Choisissez un formateur actif affecté à cette promotion.')
            name=_text(data.get('name',''),'le nom de la matière',120,True);color=data.get('color','#626b4e')
            if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):raise PlanningError('La couleur de la matière doit être au format #RRGGBB.')
            hours=data.get('planned_hours')
            if hours in ('',None):hours=None
            else:
                try:hours=float(hours)
                except (ValueError,TypeError,OverflowError):raise PlanningError('Le volume horaire est invalide.')
                if not math.isfinite(hours) or not 0<hours<=5000:raise PlanningError('Le volume horaire doit être compris entre 0 et 5 000 heures.')
            sid=subject_id or secrets.token_urlsafe(24)
            conn.execute('INSERT INTO planning_subjects(id,promotion_id,name,trainer_id,color,planned_hours) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,trainer_id=excluded.trainer_id,color=excluded.color,planned_hours=excluded.planned_hours',(sid,promotion['id'],name,trainer_id,color,hours))
            return dict(subject=dict(id=sid,promotion_id=promotion['id'],name=name,trainer_id=trainer_id,color=color,planned_hours=hours),message='Matière enregistrée. Les cours existants conservent leur formateur.')
        return transact(operation)

    @app.post('/admin/planning/api/courses')
    def planning_course_create():
        def operation(conn,payload):
            course=_course(conn,payload);reject(_conflicts(conn,course));cid=persist(conn,course)
            return dict(course=next(item for item in _load_courses(conn,course['date'],course['date']) if item['id']==cid),message='Cours ajouté.')
        return transact(operation)

    @app.route('/admin/planning/api/courses/<course_id>',methods=['PUT','DELETE'])
    def planning_course_update(course_id):
        def operation(conn,payload):
            old=existing_course(conn,course_id,payload,require_version=True)
            if request.method=='DELETE':conn.execute('DELETE FROM planning_courses WHERE id=?',(course_id,));return dict(message='Cours supprimé.')
            course=_course(conn,payload,old)
            if course['promotion_id']!=old['promotion_id']:raise PlanningError('Dupliquez le cours pour le proposer à une autre promotion.')
            reject(_conflicts(conn,course,exclude_id=course_id));persist(conn,course,course_id)
            return dict(course=next(item for item in _load_courses(conn,course['date'],course['date']) if item['id']==course_id),message='Cours mis à jour.')
        return transact(operation)

    def batch_items(conn,payload):
        promotion=_promotion(conn,payload.get('promotion_id'),True);mode=payload.get('mode');items=[]
        if mode=='repeat':
            start,end=_range(payload.get('start_date'),payload.get('end_date'));weekdays=_weekdays(payload.get('weekdays'))
            interval=payload.get('interval_weeks',1)
            if isinstance(interval,bool) or not isinstance(interval,int) or not 1<=interval<=52:raise PlanningError('L’intervalle doit être compris entre 1 et 52 semaines.')
            template=payload.get('template')
            if not isinstance(template,dict):raise PlanningError('Choisissez le cours à répéter.')
            anchor=start-timedelta(days=start.weekday())
            for day in _dates(start,end):
                if day.weekday() in weekdays and ((day-anchor).days//7)%interval==0:items.append(dict(template,promotion_id=promotion['id'],date=day.isoformat()))
        elif mode=='duplicate':
            ids=payload.get('course_ids')
            if ids is not None:
                if not isinstance(ids,list) or not ids or len(ids)>MAX_BATCH or any(not isinstance(cid,str) for cid in ids):raise PlanningError('Sélectionnez les cours à dupliquer.')
                source=[item for item in _load_courses(conn,promotion_id=promotion['id']) if item['id'] in set(ids)]
                if len(source)!=len(set(ids)):raise PlanningError('Certains cours sélectionnés n’appartiennent pas à cette promotion.')
                source_start=_iso(payload.get('source_start') or min(item['date'] for item in source))
            else:
                source_start,source_end=_range(payload.get('source_start'),payload.get('source_end'));source=_load_courses(conn,source_start.isoformat(),source_end.isoformat(),promotion['id'])
            target=_iso(payload.get('target_start'));offset=target-source_start
            for item in source:
                try:target_day=(_iso(item['date'])+offset).isoformat()
                except OverflowError:raise PlanningError('Les dates de duplication dépassent les limites du calendrier.')
                items.append({**{key:item[key] for key in ('promotion_id','subject_id','trainer_id','room_id','start','end','title')},'date':target_day})
        else:raise PlanningError('Choisissez une récurrence ou une duplication.')
        if not items or len(items)>MAX_BATCH:raise PlanningError(f'Choisissez entre 1 et {MAX_BATCH} occurrences.')
        return items

    @app.post('/admin/planning/api/courses/preview')
    def planning_course_preview():
        guard(True)
        try:
            payload=body()
            with closing(connect()) as conn:
                items=batch_items(conn,payload);preview=[];normalized=[]
                for index,item in enumerate(items):
                    try:
                        course=_course(conn,item);issues=_conflicts(conn,course);normalized.append((index,course))
                    except PlanningError as error:course=item;issues=error.conflicts or [dict(type='invalid_course',message=str(error),date=item.get('date'))]
                    preview.append(dict(key=str(index),course=course,conflicts=issues,valid=not issues))
                for index,first in normalized:
                    for second_index,second in normalized:
                        if second_index<=index or first['date']!=second['date'] or not _overlap(first,second):continue
                        if any(first.get(key) and first.get(key)==second.get(key) for key in ('promotion_id','trainer_id','room_id')):
                            for target,other in ((index,second_index),(second_index,index)):
                                preview[target]['conflicts'].append(dict(type='batch_overlap',message='Cette occurrence chevauche une autre occurrence sélectionnée.',other_key=str(other),date=first['date']));preview[target]['valid']=False
            token=serializer.dumps(dict(items=items,binding=hashlib.sha256(csrf().encode()).hexdigest()))
            valid=sum(item['valid'] for item in preview)
            return result(items=preview,preview_token=token,summary=dict(total=len(preview),valid=valid,conflicts=len(preview)-valid))
        except PlanningError as error:return fail(error)

    @app.post('/admin/planning/api/courses/batch')
    def planning_course_batch():
        def operation(conn,payload):
            try:preview=serializer.loads(payload.get('preview_token',''),max_age=15*60)
            except (BadSignature,SignatureExpired,TypeError):raise PlanningError('Cet aperçu a expiré. Générez un nouvel aperçu avant de programmer les cours.',status=409)
            if preview.get('binding')!=hashlib.sha256(csrf().encode()).hexdigest():raise PlanningError('Cet aperçu appartient à une autre session. Générez un nouvel aperçu.',status=409)
            selected=payload.get('selected_keys')
            if not isinstance(selected,list) or not selected or len(selected)>MAX_BATCH or len(set(map(str,selected)))!=len(selected):raise PlanningError('Cochez explicitement les occurrences à programmer.')
            courses=[];issues=[]
            for key in selected:
                if not isinstance(key,str) or len(key)>4 or not re.fullmatch(r'0|[1-9][0-9]*',key) or int(key)>=len(preview['items']):raise PlanningError('La sélection de cours est invalide.')
                item=preview['items'][int(key)]
                try:
                    course=_course(conn,item);current_issues=_conflicts(conn,course,pool=_load_courses(conn,course['date'],course['date'])+courses)
                    issues.extend(dict(issue,key=key) for issue in current_issues);courses.append(course)
                except PlanningError as error:issues.append(dict(type='invalid_course',key=key,message=str(error),date=item.get('date')))
            reject(issues,'Le planning a changé ou la sélection contient des conflits. Aucun cours n’a été ajouté.')
            ids=[persist(conn,course) for course in courses]
            return dict(course_ids=ids,count=len(ids),message=f'{len(ids)} cours programmé(s).')
        return transact(operation)

    @app.get('/admin/planning/api/availability')
    def planning_availability():
        guard()
        try:
            beginning,ending=_range(request.args.get('start'),request.args.get('end'),31)
            try:duration=int(request.args.get('duration',120));step=int(request.args.get('step_minutes',30))
            except ValueError:raise PlanningError('La durée du cours est invalide.')
            if not 15<=duration<=1440 or step not in (15,30,60):raise PlanningError('Choisissez une durée et un pas valides.')
            day_start=_minutes(request.args.get('day_start','08:00'));day_end=_minutes(request.args.get('day_end','18:00'),True)
            if day_end<=day_start:raise PlanningError('La plage horaire est invalide.')
            slots=[]
            with closing(connect()) as conn:
                data={key:request.args.get(key) for key in ('promotion_id','subject_id','trainer_id','room_id')};data.update(date=beginning.isoformat(),start=_clock(day_start),end=_clock(min(day_start+duration,1440)))
                template=_course(conn,data);exclude=request.args.get('exclude_course_id')
                if exclude:
                    old=existing_course(conn,exclude,{})
                    if old['promotion_id']!=template['promotion_id']:raise PlanningError('Le cours déplacé appartient à une autre promotion.')
                pool=_load_courses(conn,beginning.isoformat(),ending.isoformat());calendar=_calendar(conn,template['promotion_id']);unavailable=_unavailability(conn,template['trainer_id'])
                for day in _dates(beginning,ending):
                    for start in range(day_start,day_end-duration+1,step):
                        course=dict(template,date=day.isoformat(),start_min=start,end_min=start+duration)
                        issues=_conflicts(conn,course,exclude,pool,calendar,unavailable)
                        slots.append(dict(date=day.isoformat(),start=_clock(start),end=_clock(start+duration),available=not issues,conflicts=issues))
            return result(slots=slots)
        except PlanningError as error:return fail(error)

    @app.route('/admin/formateurs/<trainer_id>/indisponibilites',methods=['GET','POST'])
    @app.delete('/admin/formateurs/<trainer_id>/indisponibilites/<block_id>')
    def planning_trainer_unavailability(trainer_id,block_id=None):
        if request.method=='GET':
            guard()
            with closing(connect()) as conn:
                if not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers WHERE id=?',(trainer_id,)).fetchone():abort(404)
                return result(items=_unavailability(conn,trainer_id))
        def operation(conn,payload):
            if not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers WHERE id=?',(trainer_id,)).fetchone():raise PlanningError('Formateur introuvable.',status=404)
            if request.method=='DELETE':
                if not conn.execute('SELECT 1 FROM planning_trainer_unavailability WHERE id=? AND trainer_id=?',(block_id,trainer_id)).fetchone():raise PlanningError('Indisponibilité introuvable.',status=404)
                conn.execute('DELETE FROM planning_trainer_unavailability WHERE id=? AND trainer_id=?',(block_id,trainer_id));return dict(message='Indisponibilité supprimée.')
            start,end=_range(payload.get('start_date'),payload.get('end_date'));weekdays=_weekdays(payload.get('weekdays'),list(range(7)));times=payload.get('times',[])
            if not isinstance(times,list) or len(times)>12:raise PlanningError('Les horaires d’indisponibilité sont invalides.')
            normalized=[]
            for slot in times:
                if not isinstance(slot,dict):raise PlanningError('Les horaires d’indisponibilité sont invalides.')
                beginning=_minutes(slot.get('start'));ending=_minutes(slot.get('end'),True)
                if ending<=beginning:raise PlanningError('L’heure de fin doit être postérieure à l’heure de début.')
                normalized.append(dict(start=_clock(beginning),end=_clock(ending)))
            reason=_text(payload.get('reason',''),'le motif de l’indisponibilité',240,True)
            block=dict(id=secrets.token_urlsafe(24),trainer_id=trainer_id,start_date=start.isoformat(),end_date=end.isoformat(),weekdays=weekdays,times=normalized,reason=reason)
            issues=[]
            for course in _load_courses(conn,start.isoformat(),end.isoformat()):
                if course['trainer_id']==trainer_id:
                    for issue in _conflicts(conn,course,exclude_id=course['id'],pool=[],unavailable=[block]):
                        if issue['type']=='unavailable':issues.append(dict(issue,course_id=course['id'],subject_name=course['subject_name'],promotion_name=course['promotion_name'],start=course['start'],end=course['end']))
            reject(issues,'Le formateur a déjà des cours pendant cette indisponibilité. Déplacez-les avant de bloquer la période.')
            conn.execute('INSERT INTO planning_trainer_unavailability(id,trainer_id,start_date,end_date,weekdays,times,reason) VALUES(?,?,?,?,?,?,?)',(block['id'],trainer_id,block['start_date'],block['end_date'],json.dumps(weekdays),json.dumps(normalized),reason))
            return dict(item=block,message='Indisponibilité enregistrée.')
        return transact(operation)
