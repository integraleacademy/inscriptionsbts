"""Annual BTS planning: explicit school/company days before course scheduling.

Every mutation acquires a SQLite write transaction before validation. Batch
previews do not persist data; commits recheck the selected occurrences together.

The original course row is one physical reservation. ``shared`` contains only
additional promotion/subject pairs; ``groups`` in responses includes its primary
pair as well. Legacy rows are backfilled once, without inventing annual budgets.
Every participating subject receives the full duration, checked in integer
minutes against its annual target. Calendar painting is one transaction guarded
by the snapshot's ``calendar_revision`` sent as ``expected_revision``.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import hmac
import json
from io import BytesIO
import re
import secrets
import sqlite3

from flask import abort, jsonify, redirect, render_template, request, session, url_for, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from promotions import ensure_promotion_schema, list_promotions
from planning_holidays import public_holiday_name
import subject_references
import subject_catalog

KINDS={'school','company','holiday','closed'}
MAX_BATCH=500
COURSE_TEMPLATE_FIELDS=('subject_id','trainer_id','room_id','start','end','title','shared')


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
            '''CREATE TABLE IF NOT EXISTS planning_course_groups(course_id TEXT NOT NULL,promotion_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,PRIMARY KEY(course_id,promotion_id))''',
            '''CREATE TABLE IF NOT EXISTS planning_migrations(name TEXT PRIMARY KEY)''',
            '''CREATE TABLE IF NOT EXISTS planning_calendar_versions(promotion_id TEXT PRIMARY KEY,version INTEGER NOT NULL DEFAULT 0)''',
            '''CREATE TABLE IF NOT EXISTS planning_trainer_unavailability(id TEXT PRIMARY KEY,trainer_id TEXT NOT NULL,
                start_date TEXT NOT NULL,end_date TEXT NOT NULL,weekdays TEXT NOT NULL,times TEXT NOT NULL,reason TEXT NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS planning_courses_date ON planning_courses(date,start_min,end_min)',
            'CREATE INDEX IF NOT EXISTS planning_courses_promotion ON planning_courses(promotion_id,date)',
            'CREATE INDEX IF NOT EXISTS planning_groups_subject ON planning_course_groups(subject_id,course_id)',
            'CREATE INDEX IF NOT EXISTS planning_groups_promotion ON planning_course_groups(promotion_id,course_id)',
            'CREATE INDEX IF NOT EXISTS planning_unavailable_trainer ON planning_trainer_unavailability(trainer_id,start_date,end_date)',
        ):conn.execute(sql)
        if not conn.execute('SELECT 1 FROM planning_migrations WHERE name=?',('shared_courses_v1',)).fetchone():
            conn.execute('INSERT OR IGNORE INTO planning_course_groups(course_id,promotion_id,subject_id) SELECT id,promotion_id,subject_id FROM planning_courses')
            conn.execute('INSERT INTO planning_migrations(name) VALUES(?)',('shared_courses_v1',))
        subject_references.schema(conn)
        subject_catalog.schema(conn)
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
    holiday=public_holiday_name(day)
    if holiday:return {'date':key,'kind':'public_holiday','label':holiday,'public_holiday':True,'locked':True}
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


def _load_courses(conn,start=None,end=None,promotion_id=None,trainer_id=None):
    if not _has_table(conn,'trainers'):return []
    has_groups=_has_table(conn,'planning_course_groups')
    sql='''SELECT c.*,s.name AS subject_name,s.color,t.nom AS trainer_nom,t.prenom AS trainer_prenom,
        t.active AS trainer_active,r.name AS room_name,r.active AS room_active,p.nom AS promotion_name,
        p.active AS promotion_active FROM planning_courses c
        LEFT JOIN planning_subjects s ON s.id=c.subject_id LEFT JOIN trainers t ON t.id=c.trainer_id
        LEFT JOIN planning_rooms r ON r.id=c.room_id LEFT JOIN promotions p ON p.id=c.promotion_id WHERE 1=1'''
    args=[]
    if start:sql+=' AND c.date>=?';args.append(start)
    if end:sql+=' AND c.date<=?';args.append(end)
    if trainer_id:sql+=' AND c.trainer_id=?';args.append(trainer_id)
    if promotion_id:
        if has_groups:sql+=' AND (c.promotion_id=? OR EXISTS(SELECT 1 FROM planning_course_groups g WHERE g.course_id=c.id AND g.promotion_id=?))';args.extend((promotion_id,promotion_id))
        else:sql+=' AND c.promotion_id=?';args.append(promotion_id)
    sql+=' ORDER BY c.date,c.start_min,c.id'
    items=[];subject_rows={};promotion_rows={};grants={}
    def subject_info(sid):
        if sid not in subject_rows:subject_rows[sid]=conn.execute('SELECT name,planned_hours FROM planning_subjects WHERE id=?',(sid,)).fetchone()
        return subject_rows[sid]
    def promotion_info(pid):
        if pid not in promotion_rows:promotion_rows[pid]=conn.execute('SELECT nom,active FROM promotions WHERE id=?',(pid,)).fetchone()
        return promotion_rows[pid]
    for row in conn.execute(sql,args):
        item=dict(row);item['start']=_clock(item['start_min']);item['end']=_clock(item['end_min'])
        item['duration_minutes']=item['end_min']-item['start_min']
        item['trainer_name']=f"{item.pop('trainer_prenom') or ''} {item.pop('trainer_nom') or ''}".strip()
        groups=[dict(group) for group in conn.execute('''SELECT g.promotion_id,g.subject_id,p.nom AS promotion_name,s.name AS subject_name,s.color
            FROM planning_course_groups g LEFT JOIN promotions p ON p.id=g.promotion_id LEFT JOIN planning_subjects s ON s.id=g.subject_id
            WHERE g.course_id=? ORDER BY g.promotion_id''',(item['id'],))] if has_groups else []
        if not any(group['promotion_id']==item['promotion_id'] for group in groups):groups.append({key:item[key] for key in ('promotion_id','subject_id','promotion_name','subject_name','color')})
        groups.sort(key=lambda group:group['promotion_id']!=item['promotion_id'])
        item['groups']=groups;item['promotion_ids']=[group['promotion_id'] for group in groups]
        item['shared']=[dict(promotion_id=group['promotion_id'],subject_id=group['subject_id']) for group in groups if group['promotion_id']!=item['promotion_id']]
        item['is_shared']=len(groups)>1
        warnings=[]
        def warn(code,message,promotion_id=None):
            if not any(value['code']==code and value['message']==message and value.get('promotion_id')==promotion_id for value in warnings):
                value=dict(code=code,message=message)
                if promotion_id:value['promotion_id']=promotion_id
                warnings.append(value)
        if not item['room_id']:warn('room_missing','Salle non affectée')
        elif item['room_name'] is None:warn('room_missing','Salle introuvable')
        elif not item['room_active']:warn('room_inactive','Salle désactivée')
        if item['trainer_active'] is None or not item['trainer_name']:warn('trainer_missing','Formateur à renseigner')
        elif not item['trainer_active']:warn('trainer_inactive','Formateur désactivé')
        for group in groups:
            subject=subject_info(group['subject_id']);promotion=promotion_info(group['promotion_id'])
            suffix=' · '+group['promotion_name'] if group.get('promotion_name') else ''
            if not subject or not subject['name']:warn('subject_missing','Matière à renseigner'+suffix,group['promotion_id'])
            elif _budget_minutes(subject['planned_hours']) is None:warn('annual_hours_missing','Volume annuel à renseigner : '+subject['name']+suffix,group['promotion_id'])
            if not promotion:warn('promotion_missing','Promotion introuvable',group['promotion_id'])
            elif not promotion['active']:warn('promotion_inactive','Promotion archivée : '+promotion['nom'],group['promotion_id'])
            grant=(item['trainer_id'],group['promotion_id'])
            if grant not in grants:grants[grant]=bool(conn.execute('SELECT 1 FROM trainer_promotions WHERE trainer_id=? AND promotion_id=?',grant).fetchone())
            if not grants[grant]:warn('trainer_assignment_missing','Formateur non affecté à la promotion'+suffix,group['promotion_id'])
        holiday=public_holiday_name(item['date'])
        if holiday:warn('public_holiday','Cours à déplacer : jour férié ('+holiday+')')
        item['incomplete']=bool(warnings);item['warnings']=warnings;item['warning_labels']=[value['message'] for value in warnings]
        displayed=next((group for group in groups if group['promotion_id']==promotion_id),groups[0])
        item['display_subject_name']=displayed['subject_name'] or 'Matière à renseigner';item['display_color']=displayed['color'] or '#9a7538';item['display_subject_id']=displayed['subject_id']
        item['subject_name']=item['subject_name'] or 'Matière à renseigner';item['color']=item['color'] or '#9a7538'
        item['trainer_name']=item['trainer_name'] or 'Formateur à renseigner';item['promotion_name']=item['promotion_name'] or 'Promotion à renseigner'
        items.append(item)
    return items


def _subject_minutes(conn,subject_id,exclude_id=None):
    return conn.execute('''SELECT COALESCE(SUM(c.end_min-c.start_min),0) FROM planning_courses c
        WHERE (? IS NULL OR c.id!=?) AND (c.subject_id=? OR EXISTS(
            SELECT 1 FROM planning_course_groups g WHERE g.course_id=c.id AND g.subject_id=?))''',
        (exclude_id,exclude_id,subject_id,subject_id)).fetchone()[0]


def _budget_minutes(hours):
    if hours is None:return None
    try:
        value=Decimal(str(hours))*60
        return int(value) if value.is_finite() and value>0 else None
    except (InvalidOperation,ValueError,TypeError,OverflowError):return None


def _annual_hours(value):
    if value is None or isinstance(value,bool) or value=='':raise PlanningError('Renseignez le volume horaire annuel de cette matière.')
    raw=str(value)
    if len(raw)>80:raise PlanningError('Le volume horaire annuel est invalide.')
    try:hours=Decimal(raw)
    except (InvalidOperation,ValueError,TypeError):raise PlanningError('Le volume horaire annuel est invalide.')
    if not hours.is_finite() or not 0<hours<=5000:raise PlanningError('Le volume horaire annuel doit être supérieur à 0 et ne pas dépasser 5 000 heures.')
    with localcontext() as context:
        context.prec=100
        minutes=hours*60
    if not minutes.is_finite() or minutes<1 or minutes!=minutes.to_integral_value():raise PlanningError('Le volume annuel doit correspondre à un nombre entier de minutes (par exemple 1,1 h = 66 minutes).')
    return float(hours)


def _subjects(conn,promotion_id=None):
    if not _has_table(conn,'trainers'):return []
    sql='''SELECT s.*,t.nom,t.prenom,p.nom AS promotion_name,p.bts AS diploma_code FROM planning_subjects s
        LEFT JOIN trainers t ON t.id=s.trainer_id JOIN promotions p ON p.id=s.promotion_id'''
    args=[]
    if promotion_id:sql+=' WHERE s.promotion_id=?';args.append(promotion_id)
    items=[]
    for row in conn.execute(sql+' ORDER BY p.nom,s.name',args):
        item=dict(row);item['trainer_name']=f"{item.pop('prenom') or ''} {item.pop('nom') or ''}".strip()
        item['catalog_subject_id']=subject_catalog.linked_subject(conn,item['id'])
        item.update(subject_catalog.diploma_details(conn,item['catalog_subject_id'],item['diploma_code'])
            if item['catalog_subject_id'] else subject_references.details(conn,item['id']))
        item['scheduled_minutes']=_subject_minutes(conn,item['id']);item['scheduled_hours']=item['scheduled_minutes']/60
        item['planned_minutes']=_budget_minutes(item['planned_hours']);item['budget_configured']=item['planned_minutes'] is not None
        item['remaining_minutes']=max(0,item['planned_minutes']-item['scheduled_minutes']) if item['budget_configured'] else None
        item['remaining_hours']=item['remaining_minutes']/60 if item['budget_configured'] else None
        items.append(item)
    return items


def get_planning_catalog(conn):
    ensure_planning_schema(conn);trainers=[]
    if _has_table(conn,'trainers'):
        for row in conn.execute('SELECT id,nom,prenom,email,active FROM trainers WHERE active=1 ORDER BY nom,prenom'):
            item=dict(row);item['promotion_ids']=[grant[0] for grant in conn.execute('SELECT promotion_id FROM trainer_promotions WHERE trainer_id=?',(item['id'],))];trainers.append(item)
    return dict(promotions=list_promotions(conn),subjects=_subjects(conn),trainers=trainers,
                subject_catalog=subject_catalog.subjects(conn),diplomas=subject_catalog.BTS_LABELS,
                rooms=[dict(row) for row in conn.execute('SELECT * FROM planning_rooms ORDER BY name')])


def _calendar_version(conn,promotion_id):
    row=conn.execute('SELECT version FROM planning_calendar_versions WHERE promotion_id=?',(promotion_id,)).fetchone()
    return row[0] if row else 0


def get_planning_snapshot(conn,promotion_id,start=None,end=None):
    ensure_planning_schema(conn);promotion=_promotion(conn,promotion_id)
    start=start or promotion.get('date_debut');end=end or promotion.get('date_fin')
    if start and end:beginning,ending=_range(start,end)
    else:beginning=ending=None
    rules,exceptions=_calendar(conn,promotion_id)
    days=[_day(promotion,day,rules,exceptions) for day in _dates(beginning,ending)] if beginning else []
    courses=_load_courses(conn,start,end,promotion_id) if beginning else []
    subjects=_subjects(conn,promotion_id);trainers=[]
    if _has_table(conn,'trainers'):
        trainers=[dict(row) for row in conn.execute('SELECT t.id,t.nom,t.prenom,t.email FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE a.promotion_id=? AND t.active=1 ORDER BY t.nom,t.prenom',(promotion_id,))]
    return dict(promotion=promotion,days=days,rules=rules,exceptions=exceptions,subjects=subjects,
                rooms=[dict(row) for row in conn.execute('SELECT * FROM planning_rooms ORDER BY name')],trainers=trainers,
                courses=courses,calendar_configured=bool(rules or exceptions),calendar_revision=_calendar_version(conn,promotion_id),
                catalog=get_planning_catalog(conn),start=start,end=end)


def _unavailability(conn,trainer_id=None):
    sql='SELECT * FROM planning_trainer_unavailability';args=[]
    if trainer_id:sql+=' WHERE trainer_id=?';args.append(trainer_id)
    items=[]
    for row in conn.execute(sql+' ORDER BY start_date,id',args):
        item=dict(row);item['weekdays']=json.loads(item['weekdays']);item['times']=json.loads(item['times']);items.append(item)
    return items


def _overlap(a,b):return a['start_min']<b['end_min'] and a['end_min']>b['start_min']


def _groups(course):
    return course.get('groups') or [dict(promotion_id=course['promotion_id'],subject_id=course['subject_id'])]


def _course(conn,data,existing=None):
    if not isinstance(data,dict):raise PlanningError('Les données du cours sont invalides.')
    merged=dict(existing or {});merged.update(data)
    promotion_id=merged.get('promotion_id');_promotion(conn,promotion_id,ready=True)
    if not isinstance(merged.get('subject_id'),str):raise PlanningError('Choisissez une matière valide.')
    subject=conn.execute('SELECT * FROM planning_subjects WHERE id=? AND promotion_id=?',(merged.get('subject_id'),promotion_id)).fetchone()
    if not subject:raise PlanningError('Choisissez une matière de cette promotion.')
    trainer_id=merged.get('trainer_id')
    if trainer_id is not None and not isinstance(trainer_id,str):raise PlanningError('Choisissez un formateur valide.')
    trainer_id=trainer_id or subject['trainer_id']
    shared=merged.get('shared',[])
    if not isinstance(shared,list) or len(shared)>49:raise PlanningError('Choisissez au maximum 50 promotions pour une séance commune.')
    groups=[dict(promotion_id=promotion_id,subject_id=subject['id'])];seen={promotion_id}
    for entry in shared:
        if not isinstance(entry,dict) or not isinstance(entry.get('promotion_id'),str) or not isinstance(entry.get('subject_id'),str):raise PlanningError('Chaque promotion supplémentaire doit avoir sa propre matière.')
        if entry['promotion_id'] in seen:raise PlanningError('Une promotion ne peut apparaître qu’une seule fois dans une séance.')
        seen.add(entry['promotion_id']);groups.append(dict(promotion_id=entry['promotion_id'],subject_id=entry['subject_id']))
    for group in groups:
        promotion=_promotion(conn,group['promotion_id'],ready=True)
        matched=conn.execute('SELECT name,color FROM planning_subjects WHERE id=? AND promotion_id=?',(group['subject_id'],group['promotion_id'])).fetchone()
        if not matched:raise PlanningError('Chaque matière doit appartenir à la promotion sélectionnée.')
        catalog_id=subject_catalog.linked_subject(conn,group['subject_id'])
        if catalog_id:subject_catalog.available(conn,catalog_id,promotion['bts'])
        if not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE t.id=? AND t.active=1 AND a.promotion_id=?',(trainer_id,group['promotion_id'])).fetchone():raise PlanningError('Le formateur de la séance doit être actif et affecté à chacune des promotions participantes.')
        group.update(promotion_name=promotion['nom'],subject_name=matched['name'],color=matched['color'])
    room_id=merged.get('room_id')
    if room_id is not None and not isinstance(room_id,str):raise PlanningError('Choisissez une salle valide.')
    room_id=room_id or None
    if room_id and not conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1',(room_id,)).fetchone():raise PlanningError('Choisissez une salle active.')
    day=_iso(merged.get('date'));start=_minutes(merged.get('start'));end=_minutes(merged.get('end'),end=True)
    if end<=start:raise PlanningError('L’heure de fin doit être postérieure à l’heure de début.')
    return dict(promotion_id=promotion_id,subject_id=subject['id'],trainer_id=trainer_id,room_id=room_id,date=day.isoformat(),
                start=_clock(start),end=_clock(end),start_min=start,end_min=end,title=_text(merged.get('title',''),'le titre du cours',160),
                groups=groups,shared=[dict(promotion_id=g['promotion_id'],subject_id=g['subject_id']) for g in groups[1:]],
                promotion_ids=[g['promotion_id'] for g in groups],is_shared=len(groups)>1)


def _budget_conflicts(conn,course,exclude_id=None,pending=None):
    found=[];duration=course['end_min']-course['start_min']
    for group in _groups(course):
        subject=conn.execute('SELECT name,planned_hours FROM planning_subjects WHERE id=?',(group['subject_id'],)).fetchone()
        limit=_budget_minutes(subject['planned_hours']) if subject else None
        base=dict(subject_id=group['subject_id'],subject_name=subject['name'] if subject else '',promotion_id=group['promotion_id'],date=course['date'])
        if limit is None:
            found.append(dict(base,type='subject_budget_missing',message='Renseignez le volume annuel de cette matière avant de programmer un cours.'));continue
        consumed=_subject_minutes(conn,group['subject_id'],exclude_id)
        added=sum(item['end_min']-item['start_min'] for item in pending or [] if any(g['subject_id']==group['subject_id'] for g in _groups(item)))
        if consumed+added+duration>limit:
            found.append(dict(base,type='subject_budget',message=f"Le volume annuel de {subject['name']} serait dépassé.",
                              planned_minutes=limit,scheduled_minutes=consumed,pending_minutes=added,requested_minutes=duration,
                              remaining_minutes=max(0,limit-consumed-added)))
    return found


def _conflicts(conn,course,exclude_id=None,pool=None,calendar=None,unavailable=None,pending=None,include_budget=True):
    found=[];day=_iso(course['date'])
    for group in _groups(course):
        promotion=_promotion(conn,group['promotion_id'])
        if not promotion.get('date_debut') or not promotion.get('date_fin') or not promotion['date_debut']<=course['date']<=promotion['date_fin']:
            found.append(dict(type='outside_promotion',message='Ce cours est en dehors des dates de la promotion.',date=course['date'],promotion_id=group['promotion_id']))
        rules,exceptions=calendar if calendar is not None and group['promotion_id']==course['promotion_id'] else _calendar(conn,group['promotion_id'])
        day_state=_day(promotion,day,rules,exceptions)
        if day_state['kind']=='public_holiday':found.append(dict(type='public_holiday',message=day_state['label']+' : aucun cours ne peut être planifié un jour férié.',date=course['date'],promotion_id=group['promotion_id']))
        elif day_state['kind']!='school':found.append(dict(type='not_school',message=promotion['nom']+' : ce jour n’est pas défini comme une journée école ('+day_state['label']+').',date=course['date'],promotion_id=group['promotion_id']))
    rows=pool if pool is not None else _load_courses(conn,course['date'],course['date'])
    own_promotions={g['promotion_id'] for g in _groups(course)}
    for other in rows:
        if (exclude_id is not None and other.get('id')==exclude_id) or other['date']!=course['date'] or not _overlap(course,other):continue
        common=own_promotions & {g['promotion_id'] for g in _groups(other)}
        if common:found.append(dict(type='promotion_overlap',message=f"Une promotion participante a déjà un cours de {_clock(other['start_min'])} à {_clock(other['end_min'])}.",date=course['date'],course_id=other.get('id'),promotion_ids=sorted(common)))
        for resource,kind,label in [('trainer_id','trainer_overlap','Ce formateur intervient déjà sur un autre cours'),('room_id','room_overlap','Cette salle est déjà réservée')]:
            if course.get(resource) and course.get(resource)==other.get(resource):
                found.append(dict(type=kind,message=f"{label}, de {_clock(other['start_min'])} à {_clock(other['end_min'])}.",date=course['date'],course_id=other.get('id'),promotion_id=other.get('promotion_id'),promotion_name=other.get('promotion_name',''),subject_name=other.get('subject_name','')))
    for block in unavailable if unavailable is not None else _unavailability(conn,course['trainer_id']):
        if block['trainer_id']!=course['trainer_id'] or not block['start_date']<=course['date']<=block['end_date'] or day.weekday() not in block['weekdays']:continue
        intervals=block['times'] or [{'start':'00:00','end':'24:00'}]
        if any(course['start_min']<_minutes(slot['end'],True) and course['end_min']>_minutes(slot['start']) for slot in intervals):
            found.append(dict(type='unavailable',message='Formateur indisponible : '+block['reason'],date=course['date'],unavailability_id=block.get('id')))
    if include_budget:found.extend(_budget_conflicts(conn,course,exclude_id,pending))
    return found


def _course_issues_for_calendar(conn,promotion_id,rules,exceptions):
    promotion=_promotion(conn,promotion_id);old_rules,old_exceptions=_calendar(conn,promotion_id)
    return [dict(type='existing_course',message='Un cours existe sur un jour qui ne serait plus à l’école.',date=c['date'],course_id=c['id'],subject_name=c['subject_name'],start=c['start'],end=c['end']) for c in _load_courses(conn,promotion_id=promotion_id) if _day(promotion,_iso(c['date']),rules,exceptions)['kind']!='school' and _day(promotion,_iso(c['date']),old_rules,old_exceptions)['kind']=='school']


def _base_rule_conflicts(rules):
    issues=[]
    for index,first in enumerate(rules):
        if first['kind'] not in ('school','company'):continue
        for second in rules[index+1:]:
            if second['kind'] not in ('school','company') or first['kind']==second['kind']:continue
            start=max(first['start_date'],second['start_date']);end=min(first['end_date'],second['end_date'])
            if start>end:continue
            overlap=set(first['weekdays'])&set(second['weekdays'])
            days=[day.isoformat() for day in _dates(_iso(start),_iso(end)) if day.weekday() in overlap and not public_holiday_name(day)]
            if days:issues.append(dict(type='calendar_overlap',message='Ces règles définissent les mêmes jours à la fois à l’école et en entreprise. Modifiez la règle existante ou utilisez une exception.',dates=days[:30],rule_id=second.get('id')))
    return issues


def validate_promotion_change(conn,promotion_id,data):
    """Read-only guard used by the promotion editor; never initializes or commits."""
    if not _has_table(conn,'planning_courses'):return []
    current=conn.execute('SELECT * FROM promotions WHERE id=?',(promotion_id,)).fetchone()
    if not current:return []
    merged=dict(current);merged.update(data);issues=[]
    if merged.get('bts')!=current['bts'] and _has_table(conn,'planning_subject_catalog_links'):
        for row in conn.execute('''SELECT s.id,s.name FROM planning_subjects s
            LEFT JOIN planning_subject_catalog_links l ON l.planning_subject_id=s.id
            LEFT JOIN planning_subject_diplomas d ON d.subject_id=l.subject_id AND d.diploma_code=?
            WHERE s.promotion_id=? AND d.subject_id IS NULL''',(merged.get('bts'),promotion_id)):
            issues.append(dict(type='subject_diploma',subject_id=row['id'],message='La matière « '+row['name']+' » n’est pas rattachée au nouveau diplôme. Modifiez ses diplômes dans Matières avant de changer cette promotion.'))
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
    for row in _load_courses(conn,start=today):
        if row['trainer_id']!=trainer_id:continue
        for group in _groups(row):
            if group['promotion_id'] not in granted:issues.append(dict(type='trainer_courses',message='Ce formateur a encore un cours à venir dans une promotion retirée.',course_id=row['id'],promotion_id=group['promotion_id'],date=row['date']))
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
        conn.execute('DELETE FROM planning_course_groups WHERE course_id=?',(course_id,))
        conn.executemany('INSERT INTO planning_course_groups(course_id,promotion_id,subject_id) VALUES(?,?,?)',[(course_id,g['promotion_id'],g['subject_id']) for g in _groups(course)])
        return course_id

    def touch_calendar(conn,promotion_id):
        conn.execute('INSERT INTO planning_calendar_versions(promotion_id,version) VALUES(?,1) ON CONFLICT(promotion_id) DO UPDATE SET version=version+1',(promotion_id,))
        return _calendar_version(conn,promotion_id)

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

    def catalog_page(template,title):
        if not require_admin() and 'login' in app.view_functions:return redirect(url_for('login',next=request.full_path.rstrip('?')))
        guard()
        response=app.make_response(render_template(template,title=title+' · Plateforme de gestion des BTS',csrf_token=csrf(),selected_promotion=request.args.get('promotion_id','')))
        response.headers['Cache-Control']='no-store';return response

    @app.get('/admin/matieres')
    def planning_subjects_admin():return catalog_page('planning_subjects.html','Matières')

    @app.get('/admin/salles')
    def planning_rooms_admin():return catalog_page('planning_rooms.html','Salles')

    @app.get('/admin/parametres')
    def admin_settings():return catalog_page('admin_settings.html','Paramètres')

    @app.get('/admin/planning/api/catalog')
    def planning_catalog():
        guard()
        with closing(connect()) as conn:return result(get_planning_catalog(conn))

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
            pdf=build_planning_pdf(snapshot['promotion'],snapshot['courses'],snapshot['days'],snapshot['start'],snapshot['end'],mode=view,**({'subjects':snapshot['subjects']} if view=='annual' else {}))
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
            return dict(rule=rule,calendar_revision=touch_calendar(conn,rule['promotion_id']),message='Règle d’alternance enregistrée.')
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
            if request.method=='DELETE':
                conn.execute('DELETE FROM planning_calendar_rules WHERE id=?',(rule_id,));return dict(calendar_revision=touch_calendar(conn,row['promotion_id']),message='Règle supprimée.')
            conn.execute('UPDATE planning_calendar_rules SET start_date=?,end_date=?,weekdays=?,kind=?,label=? WHERE id=?',(rule['start_date'],rule['end_date'],json.dumps(rule['weekdays']),rule['kind'],rule['label'],rule_id))
            return dict(rule=rule,calendar_revision=touch_calendar(conn,row['promotion_id']),message='Règle mise à jour.')
        return transact(operation)

    @app.put('/admin/planning/api/calendar/exceptions')
    def planning_exception_put():
        def operation(conn,payload):
            promotion=_promotion(conn,payload.get('promotion_id'),True);day=_iso(payload.get('date')).isoformat();kind=payload.get('kind')
            if not promotion['date_debut']<=day<=promotion['date_fin'] or not isinstance(kind,str) or kind not in KINDS:raise PlanningError('Choisissez un jour de la promotion et un type de journée valide.')
            if public_holiday_name(day):raise PlanningError('Un jour férié est automatiquement bloqué et ne peut pas être modifié.',[dict(type='public_holiday',date=day)],409)
            label=_text(payload.get('label',''),'le libellé',180);rules,exceptions=_calendar(conn,promotion['id'])
            exceptions=[item for item in exceptions if item['date']!=day]+[dict(date=day,kind=kind,label=label)]
            reject(_course_issues_for_calendar(conn,promotion['id'],rules,exceptions))
            conn.execute('INSERT INTO planning_day_exceptions(promotion_id,date,kind,label) VALUES(?,?,?,?) ON CONFLICT(promotion_id,date) DO UPDATE SET kind=excluded.kind,label=excluded.label',(promotion['id'],day,kind,label))
            return dict(calendar_revision=touch_calendar(conn,promotion['id']),message='Exception enregistrée.')
        return transact(operation)

    @app.delete('/admin/planning/api/calendar/exceptions/<promotion_id>/<day>')
    def planning_exception_delete(promotion_id,day):
        def operation(conn,payload):
            _iso(day);_promotion(conn,promotion_id);rules,exceptions=_calendar(conn,promotion_id)
            reject(_course_issues_for_calendar(conn,promotion_id,rules,[item for item in exceptions if item['date']!=day]))
            conn.execute('DELETE FROM planning_day_exceptions WHERE promotion_id=? AND date=?',(promotion_id,day));return dict(calendar_revision=touch_calendar(conn,promotion_id),message='Exception supprimée.')
        return transact(operation)

    @app.post('/admin/planning/api/calendar/bulk')
    def planning_calendar_bulk():
        def operation(conn,payload):
            promotion=_promotion(conn,payload.get('promotion_id'),True);expected=payload.get('expected_revision')
            if isinstance(expected,bool) or not isinstance(expected,int) or expected<0:raise PlanningError('Rechargez le calendrier avant de sauvegarder : sa révision est requise.')
            if expected!=_calendar_version(conn,promotion['id']):raise PlanningError('Le calendrier a été modifié entre-temps. Rechargez-le avant de sauvegarder.',[dict(type='calendar_stale')],409)
            days=payload.get('days')
            if not isinstance(days,list) or not 1<=len(days)<=741:raise PlanningError('Sélectionnez entre 1 et 741 journées à enregistrer.')
            changed={}
            for item in days:
                if not isinstance(item,dict):raise PlanningError('Les journées du calendrier sont invalides.')
                day=_iso(item.get('date')).isoformat();kind=item.get('kind')
                if day in changed:raise PlanningError('Chaque date doit apparaître une seule fois dans la sauvegarde.')
                if not promotion['date_debut']<=day<=promotion['date_fin'] or not isinstance(kind,str) or kind not in KINDS:raise PlanningError('Chaque journée doit avoir un type valide et rester dans les dates de la promotion.')
                if public_holiday_name(day):raise PlanningError('Un jour férié est automatiquement bloqué. Retirez-le des journées à colorier.',[dict(type='public_holiday',date=day)],409)
                changed[day]=dict(date=day,kind=kind,label=_text(item.get('label',''),'le libellé',180))
            rules,exceptions=_calendar(conn,promotion['id'])
            proposed=[item for item in exceptions if item['date'] not in changed]+list(changed.values())
            reject(_course_issues_for_calendar(conn,promotion['id'],rules,proposed),'Des cours existent sur des journées modifiées. Aucune journée n’a été enregistrée.')
            conn.executemany('INSERT INTO planning_day_exceptions(promotion_id,date,kind,label) VALUES(?,?,?,?) ON CONFLICT(promotion_id,date) DO UPDATE SET kind=excluded.kind,label=excluded.label',[(promotion['id'],item['date'],item['kind'],item['label']) for item in changed.values()])
            return dict(calendar_revision=touch_calendar(conn,promotion['id']),count=len(changed),message='Calendrier annuel enregistré.')
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
                reject([dict(type='subject_used',message='Cette matière comporte encore des cours. Supprimez ou réaffectez ces cours avant de la retirer.')] if conn.execute('SELECT 1 FROM planning_courses c WHERE c.subject_id=? OR EXISTS(SELECT 1 FROM planning_course_groups g WHERE g.course_id=c.id AND g.subject_id=?) LIMIT 1',(subject_id,subject_id)).fetchone() else [])
                conn.execute('DELETE FROM planning_subject_details WHERE subject_id=?',(subject_id,))
                conn.execute('DELETE FROM planning_subject_catalog_links WHERE planning_subject_id=?',(subject_id,))
                conn.execute('DELETE FROM planning_subjects WHERE id=?',(subject_id,));return dict(message='Matière retirée de ce planning. Sa fiche reste dans le catalogue des diplômes.')
            metadata=subject_references.details(conn,subject_id) if old else {}
            imported=bool(metadata.get('import_id'))
            data=dict(old or {});data.update(payload);promotion=_promotion(conn,data.get('promotion_id'),not imported)
            if not promotion['active']:raise PlanningError('Cette promotion est archivée.')
            if old and old['promotion_id']!=promotion['id']:raise PlanningError('Une matière ne peut pas changer de promotion.')
            trainer_id=data.get('trainer_id')
            if not isinstance(trainer_id,str):raise PlanningError('Choisissez un formateur valide.')
            if not (imported and trainer_id=='') and (not _has_table(conn,'trainers') or not conn.execute('SELECT 1 FROM trainers t JOIN trainer_promotions a ON a.trainer_id=t.id WHERE t.id=? AND t.active=1 AND a.promotion_id=?',(trainer_id,promotion['id'])).fetchone()):raise PlanningError('Choisissez un formateur actif affecté à cette promotion.')
            catalog_id=subject_catalog.linked_subject(conn,subject_id) if old else payload.get('catalog_subject_id')
            if old and 'catalog_subject_id' in payload and payload['catalog_subject_id']!=catalog_id:
                raise PlanningError('La matière d’une préparation existante ne peut pas être remplacée. Ajoutez une nouvelle préparation.')
            master=subject_catalog.available(conn,catalog_id,promotion['bts']) if catalog_id else None
            # New clients choose a catalogue entry. Legacy clients may still create
            # a named subject; it is immediately attached to this diploma's catalogue.
            if payload.get('catalog_subject_id') and master:
                data.update(name=master['name'],color=master['color'])
            name=_text(data.get('name',''),'le nom de la matière',120,True);color=data.get('color','#626b4e')
            if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):raise PlanningError('La couleur de la matière doit être au format #RRGGBB.')
            hours=None if imported and data.get('planned_hours') in (None,'') else _annual_hours(data.get('planned_hours'))
            used=_subject_minutes(conn,subject_id) if subject_id else 0
            reject([dict(type='subject_budget',subject_id=subject_id,planned_minutes=_budget_minutes(hours),scheduled_minutes=used,message='Le volume annuel ne peut pas être inférieur aux heures déjà planifiées.')] if used and used>(_budget_minutes(hours) or 0) else [])
            sid=subject_id or secrets.token_urlsafe(24)
            if not catalog_id:
                match=conn.execute('SELECT c.id FROM planning_subject_catalog c JOIN planning_subject_diplomas d ON d.subject_id=c.id WHERE c.name_key=? AND d.diploma_code=?',(subject_references.normal(name),promotion['bts'])).fetchone()
                catalog_id=match['id'] if match else subject_catalog.import_subject(conn,name,promotion['bts'],subject_references.validate_details(payload),color)
                master=subject_catalog.find(conn,catalog_id)
                name,color=master['name'],master['color']
            if not old and conn.execute('''SELECT 1 FROM planning_subject_catalog_links l JOIN planning_subjects s ON s.id=l.planning_subject_id
                WHERE l.subject_id=? AND s.promotion_id=?''',(catalog_id,promotion['id'])).fetchone():
                raise PlanningError('Cette matière est déjà préparée dans le planning de cette promotion.',status=409)
            if old and (name!=master['name'] or color!=master['color'] or any(key in payload for key in (*subject_references.DETAIL_TEXT,*subject_references.DETAIL_NUMBERS,'optional'))):
                subject_catalog.save(conn,dict(name=name,color=color,diploma_details={promotion['bts']:payload}),catalog_id)
            conn.execute('INSERT INTO planning_subjects(id,promotion_id,name,trainer_id,color,planned_hours) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,trainer_id=excluded.trainer_id,color=excluded.color,planned_hours=excluded.planned_hours',(sid,promotion['id'],name,trainer_id,color,hours))
            if not old:subject_catalog.link_allocation(conn,sid,catalog_id)
            subject_references.save_details(conn,sid,payload,metadata or subject_catalog.diploma_details(conn,catalog_id,promotion['bts']))
            return dict(subject=next(item for item in _subjects(conn,promotion['id']) if item['id']==sid),message='Matière enregistrée. Les cours existants conservent leur formateur.')
        return transact(operation)

    subject_references.register(app,connect,guard,body,result,fail,transact)
    subject_catalog.register(app,connect,guard,result,fail,transact)

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
            if request.method=='DELETE':
                conn.execute('DELETE FROM planning_course_groups WHERE course_id=?',(course_id,));conn.execute('DELETE FROM planning_courses WHERE id=?',(course_id,));return dict(message='Cours supprimé.')
            course=_course(conn,payload,old)
            if course['promotion_id']!=old['promotion_id']:raise PlanningError('Dupliquez le cours pour le proposer à une autre promotion.')
            reject(_conflicts(conn,course,exclude_id=course_id));persist(conn,course,course_id)
            return dict(course=next(item for item in _load_courses(conn,course['date'],course['date']) if item['id']==course_id),message='Cours mis à jour.')
        return transact(operation)

    def batch_items(conn,payload):
        promotion=_promotion(conn,payload.get('promotion_id'),True);mode=payload.get('mode');items=[]
        if mode=='weeks':
            source_start=_iso(payload.get('source_start'),'source_start')
            if source_start.weekday()!=0:raise PlanningError('La semaine source doit commencer un lundi.')
            try:source_end=source_start+timedelta(days=6)
            except OverflowError:raise PlanningError('Les dates de duplication dépassent les limites du calendrier.')
            chosen=payload.get('target_weeks')
            if not isinstance(chosen,list) or not 1<=len(chosen)<=MAX_BATCH:raise PlanningError(f'Choisissez entre 1 et {MAX_BATCH} semaines.')
            weeks=[_iso(day,'target_weeks') for day in chosen]
            if len(set(weeks))!=len(weeks):raise PlanningError('Chaque semaine doit être sélectionnée une seule fois.')
            if any(day.weekday()!=0 for day in weeks):raise PlanningError('Chaque semaine sélectionnée doit commencer un lundi.')
            if source_start in weeks:raise PlanningError('Choisissez d’autres semaines que la semaine source.')
            source=_load_courses(conn,source_start.isoformat(),source_end.isoformat(),promotion['id'])
            if not source:raise PlanningError('La semaine source ne contient aucun cours à dupliquer.')
            if len(source)*len(weeks)>MAX_BATCH:raise PlanningError(f'La sélection dépasse {MAX_BATCH} cours. Sélectionnez moins de semaines.')
            for week in sorted(weeks):
                for item in source:
                    try:target_day=(week+timedelta(days=(_iso(item['date'])-source_start).days)).isoformat()
                    except OverflowError:raise PlanningError('Les dates de duplication dépassent les limites du calendrier.')
                    items.append({**{key:item[key] for key in ('promotion_id','subject_id','trainer_id','room_id','start','end','title','shared')},
                                  'date':target_day,'_source_course_id':item['id'],'_source_version':item['version'],'_source_date':item['date']})
        elif mode=='dates':
            chosen=payload.get('dates')
            if not isinstance(chosen,list) or not 1<=len(chosen)<=MAX_BATCH:raise PlanningError(f'Choisissez entre 1 et {MAX_BATCH} dates.')
            dates=[_iso(day).isoformat() for day in chosen]
            if len(set(dates))!=len(dates):raise PlanningError('Chaque jour doit être sélectionné une seule fois.')
            source_id=payload.get('source_course_id')
            if source_id is not None:
                if not isinstance(source_id,str):raise PlanningError('Choisissez un cours à dupliquer.')
                source=existing_course(conn,source_id,dict(version=payload.get('source_version')),require_version=True)
                if promotion['id'] not in source['promotion_ids']:raise PlanningError('Ce cours n’appartient pas à cette promotion.')
                template={key:source[key] for key in ('promotion_id','subject_id','trainer_id','room_id','start','end','title','shared')}
                template.update(_source_course_id=source['id'],_source_version=source['version'])
            else:
                template=payload.get('template')
                if not isinstance(template,dict):raise PlanningError('Choisissez le cours à dupliquer.')
                template={key:template[key] for key in COURSE_TEMPLATE_FIELDS if key in template}
                template['promotion_id']=promotion['id']
            items=[dict(template,date=day) for day in sorted(dates)]
        elif mode=='repeat':
            start,end=_range(payload.get('start_date'),payload.get('end_date'));weekdays=_weekdays(payload.get('weekdays'))
            interval=payload.get('interval_weeks',1)
            if isinstance(interval,bool) or not isinstance(interval,int) or not 1<=interval<=52:raise PlanningError('L’intervalle doit être compris entre 1 et 52 semaines.')
            template=payload.get('template')
            if not isinstance(template,dict):raise PlanningError('Choisissez le cours à répéter.')
            template={key:template[key] for key in COURSE_TEMPLATE_FIELDS if key in template}
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
                items.append({**{key:item[key] for key in ('promotion_id','subject_id','trainer_id','room_id','start','end','title','shared')},'date':target_day})
        else:raise PlanningError('Choisissez des dates, des semaines, une récurrence ou une duplication.')
        if not items or len(items)>MAX_BATCH:raise PlanningError(f'Choisissez entre 1 et {MAX_BATCH} occurrences.')
        return items

    @app.post('/admin/planning/api/courses/preview')
    def planning_course_preview():
        guard(True)
        try:
            payload=body()
            with closing(connect()) as conn:
                # The UI must use the same budget snapshot as this preview,
                # never a catalog that was loaded before another planning edit.
                conn.execute('BEGIN')
                items=batch_items(conn,payload);preview=[];normalized=[]
                subject_ids=set()
                for item in items:
                    if isinstance(item.get('subject_id'),str):subject_ids.add(item['subject_id'])
                    for group in item.get('shared',[]) if isinstance(item.get('shared'),list) else []:
                        if isinstance(group,dict) and isinstance(group.get('subject_id'),str):subject_ids.add(group['subject_id'])
                budgets=[{key:subject[key] for key in ('id','name','planned_minutes','scheduled_minutes','remaining_minutes','planned_hours','budget_configured')}
                         for subject in _subjects(conn) if subject['id'] in subject_ids]
                if payload.get('mode')=='weeks':
                    accepted=[]
                    for index,item in enumerate(items):
                        try:
                            course=_course(conn,item)
                            issues=_conflicts(conn,course,pool=_load_courses(conn,course['date'],course['date'])+accepted,pending=accepted)
                        except PlanningError as error:course=item;issues=error.conflicts or [dict(type='invalid_course',message=str(error),date=item.get('date'))]
                        if not issues:accepted.append(course)
                        preview.append(dict(key=str(index),course=course,conflicts=issues,valid=not issues,
                                            source_course_id=item['_source_course_id'],source_date=item['_source_date']))
                    source_versions={item['_source_course_id']:item['_source_version'] for item in items}
                    token=serializer.dumps(dict(items=items,mode='weeks',promotion_id=payload['promotion_id'],source_start=payload['source_start'],
                                                source_versions=source_versions,binding=hashlib.sha256(csrf().encode()).hexdigest()))
                    valid=sum(item['valid'] for item in preview)
                    return result(items=preview,budgets=budgets,mode='weeks',partial=True,preview_token=token,
                                  summary=dict(total=len(preview),valid=valid,conflicts=len(preview)-valid))
                for index,item in enumerate(items):
                    try:
                        course=_course(conn,item);issues=_conflicts(conn,course);normalized.append((index,course))
                    except PlanningError as error:course=item;issues=error.conflicts or [dict(type='invalid_course',message=str(error),date=item.get('date'))]
                    preview.append(dict(key=str(index),course=course,conflicts=issues,valid=not issues))
                for index,first in normalized:
                    for second_index,second in normalized:
                        if second_index<=index or first['date']!=second['date'] or not _overlap(first,second):continue
                        if ({g['promotion_id'] for g in _groups(first)} & {g['promotion_id'] for g in _groups(second)}) or any(first.get(key) and first.get(key)==second.get(key) for key in ('trainer_id','room_id')):
                            for target,other in ((index,second_index),(second_index,index)):
                                preview[target]['conflicts'].append(dict(type='batch_overlap',message='Cette occurrence chevauche une autre occurrence sélectionnée.',other_key=str(other),date=first['date']));preview[target]['valid']=False
                accepted=[]
                for index,course in normalized:
                    if not preview[index]['valid']:continue
                    budget_issues=_budget_conflicts(conn,course,pending=accepted)
                    if budget_issues:
                        preview[index]['conflicts'].extend(budget_issues);preview[index]['valid']=False
                    else:accepted.append(course)
            token=serializer.dumps(dict(items=items,binding=hashlib.sha256(csrf().encode()).hexdigest()))
            valid=sum(item['valid'] for item in preview)
            return result(items=preview,budgets=budgets,preview_token=token,summary=dict(total=len(preview),valid=valid,conflicts=len(preview)-valid))
        except PlanningError as error:return fail(error)

    @app.post('/admin/planning/api/courses/batch')
    def planning_course_batch():
        def operation(conn,payload):
            try:preview=serializer.loads(payload.get('preview_token',''),max_age=15*60)
            except (BadSignature,SignatureExpired,TypeError):raise PlanningError('Cet aperçu a expiré. Générez un nouvel aperçu avant de programmer les cours.',status=409)
            if preview.get('binding')!=hashlib.sha256(csrf().encode()).hexdigest():raise PlanningError('Cet aperçu appartient à une autre session. Générez un nouvel aperçu.',status=409)
            selected=payload.get('selected_keys')
            if not isinstance(selected,list) or not selected or len(selected)>MAX_BATCH or len(set(map(str,selected)))!=len(selected):raise PlanningError('Cochez explicitement les occurrences à programmer.')
            for key in selected:
                if not isinstance(key,str) or len(key)>4 or not re.fullmatch(r'0|[1-9][0-9]*',key) or int(key)>=len(preview['items']):raise PlanningError('La sélection de cours est invalide.')
            if preview.get('mode')=='weeks':
                # A changed source week requires a fresh preview. It must never be
                # treated as an ordinary destination conflict and silently skipped.
                source_start=_iso(preview['source_start']);source_end=source_start+timedelta(days=6)
                current_sources={item['id']:item['version'] for item in _load_courses(conn,source_start.isoformat(),source_end.isoformat(),preview['promotion_id'])}
                if current_sources!=preview['source_versions']:
                    raise PlanningError('La semaine source a été modifiée entre-temps. Générez un nouvel aperçu. Aucun cours n’a été ajouté.',
                                        [dict(type='stale_source_week')],409)
                courses=[];skipped=[];created_keys=[]
                # Always use preview chronology, not client checkbox order, so
                # scarce annual hours go to the earliest chosen occurrences.
                for key in sorted(selected,key=int):
                    item=preview['items'][int(key)]
                    try:
                        course=_course(conn,item)
                        issues=_conflicts(conn,course,pool=_load_courses(conn,course['date'],course['date'])+courses,pending=courses)
                    except PlanningError as error:course=item;issues=error.conflicts or [dict(type='invalid_course',message=str(error),date=item.get('date'))]
                    if issues:
                        skipped.append(dict(key=key,course=course,conflicts=issues,source_course_id=item['_source_course_id'],source_date=item['_source_date']))
                    else:courses.append(course);created_keys.append(key)
                ids=[persist(conn,course) for course in courses]
                message=f'{len(ids)} cours programmé(s).'
                if skipped:message+=f' {len(skipped)} cours non dupliqué(s) en raison de conflits.'
                return dict(course_ids=ids,count=len(ids),created_keys=created_keys,skipped_count=len(skipped),skipped=skipped,
                            summary=dict(total=len(selected),created=len(ids),skipped=len(skipped)),message=message)
            courses=[];issues=[];checked_sources={}
            for key in selected:
                if not isinstance(key,str) or len(key)>4 or not re.fullmatch(r'0|[1-9][0-9]*',key) or int(key)>=len(preview['items']):raise PlanningError('La sélection de cours est invalide.')
                item=preview['items'][int(key)]
                try:
                    if item.get('_source_course_id'):
                        if not isinstance(item['_source_course_id'],str) or isinstance(item.get('_source_version'),bool) or not isinstance(item.get('_source_version'),int):raise PlanningError('La référence du cours à dupliquer est invalide.')
                        reference=(item['_source_course_id'],item.get('_source_version'))
                        if reference not in checked_sources:
                            try:
                                existing_course(conn,reference[0],dict(version=reference[1]),require_version=True)
                                checked_sources[reference]=None
                            except PlanningError as source_error:checked_sources[reference]=source_error
                        if checked_sources[reference]:raise checked_sources[reference]
                    course=_course(conn,item);current_issues=_conflicts(conn,course,pool=_load_courses(conn,course['date'],course['date'])+courses,pending=courses)
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
                if 'shared' in request.args:
                    try:data['shared']=json.loads(request.args['shared'])
                    except (ValueError,TypeError):raise PlanningError('Les promotions de la séance commune sont invalides.')
                template=_course(conn,data);exclude=request.args.get('exclude_course_id')
                if exclude:
                    old=existing_course(conn,exclude,{})
                    if old['promotion_id']!=template['promotion_id']:raise PlanningError('Le cours déplacé appartient à une autre promotion.')
                pool=_load_courses(conn,beginning.isoformat(),ending.isoformat());calendar=_calendar(conn,template['promotion_id']);unavailable=_unavailability(conn,template['trainer_id'])
                budget_issues=_budget_conflicts(conn,template,exclude)
                for day in _dates(beginning,ending):
                    for start in range(day_start,day_end-duration+1,step):
                        course=dict(template,date=day.isoformat(),start_min=start,end_min=start+duration)
                        issues=_conflicts(conn,course,exclude,pool,calendar,unavailable,include_budget=False)
                        issues.extend(dict(issue,date=day.isoformat()) for issue in budget_issues)
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
