"""Room calendar, atomic mixed selections, closures and printable snapshots."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import secrets

from flask import request, send_file


def unavailable_slots(conn, start, end):
    rows=[]
    for row in conn.execute('SELECT * FROM planning_room_unavailability WHERE start_date<=? AND end_date>=?',(end,start)):
        first=max(date.fromisoformat(start),date.fromisoformat(row['start_date']))
        last=min(date.fromisoformat(end),date.fromisoformat(row['end_date']))
        for offset in range((last-first).days+1):
            day=(first+timedelta(days=offset)).isoformat()
            rows.append(dict(row, date=day,key='unavailable:'+row['id']+':'+day,
                             source='unavailable',formation='UNAVAILABLE',title=row['reason']))
    return rows


def snapshot(conn,start,end):
    from planning import _load_courses, _clock
    from planning_rooms import external_slots, configured, ready, overlap
    rooms=[dict(r) for r in conn.execute('SELECT * FROM planning_rooms ORDER BY name')]
    rows=[]
    for c in _load_courses(conn,start,end):
        rows.append(dict(c,key='course:'+c['id'],source='event' if c['kind']=='event' else 'bts',
                         title=c.get('title') or c['subject_name'],formation='BTS',url='/admin/salles?course_id='+c['id']))
    rows += [dict(r) for r in external_slots(conn) if start<=r['date']<=end]
    rows += unavailable_slots(conn,start,end)
    buckets={}
    for row in rows:
        row.update(start=_clock(row['start_min']),end=_clock(row['end_min']),conflict=False)
        for other in buckets.setdefault((row['room_id'],row['date']),[]):
            if row.get('owner') and row.get('owner')==other.get('owner'):
                continue  # both sides of the same in-flight source reservation
            if overlap(row,other):row['conflict']=other['conflict']=True
        buckets[(row['room_id'],row['date'])].append(row)
    if any(not r['room_id'] for r in rows):rooms.append(dict(id=None,name='Salle à définir',active=True))
    return dict(rooms=rooms,reservations=rows,connected=configured(),ready=ready(conn),start=start,end=end)


def register(app,connect,guard,result,fail,transact):
    from planning import PlanningError, _iso, _minutes
    from planning_rooms import overlap, ready

    def room(conn,rid):
        if not isinstance(rid,str) or not conn.execute('SELECT 1 FROM planning_rooms WHERE id=? AND active=1',(rid,)).fetchone():
            raise PlanningError('Choisissez une salle active.')
        if not ready(conn):raise PlanningError('La synchronisation des salles doit être terminée.',status=503)
        return rid

    def issues_for(proposed,others):
        issues=[]
        for i,item in enumerate(proposed):
            for other in others+proposed[:i]:
                if overlap(item,other):
                    issues.append(dict(type='room',date=item['date'],message='Salle indisponible : '+other['title']))
                    if len(issues)>=80:return issues
        return issues

    @app.post('/admin/planning/api/rooms/calendar-move')
    def move_calendar_slots():
        def operation(conn,payload):
            rid=room(conn,payload.get('room_id'))
            items=payload.get('slots')
            if not isinstance(items,list) or not 1<=len(items)<=1000 or any(not isinstance(i,dict) for i in items):
                raise PlanningError('Sélectionnez entre 1 et 1 000 créneaux.')
            keys=[i.get('key') for i in items]
            if any(not isinstance(k,str) or len(k)>400 for k in keys) or len(set(keys))!=len(keys):
                raise PlanningError('Sélection de créneaux invalide.')
            dates=[_iso(i.get('date')).isoformat() for i in items]
            if (date.fromisoformat(max(dates))-date.fromisoformat(min(dates))).days>366:
                raise PlanningError('Sélectionnez des créneaux sur un an au maximum.')
            all_rows=snapshot(conn,min(dates),max(dates))['reservations']
            lookup={r['key']:r for r in all_rows}; selected=[]
            for item in items:
                row=lookup.get(item['key'])
                if not row or row['date']!=item['date'] or row['source']=='unavailable':
                    raise PlanningError('Un créneau n’existe plus. Actualisez la sélection.',status=409)
                if row['source']=='session':
                    valid=(not row.get('pending') and item.get('revision')==row['revision'] and
                           type(item.get('room_version')) is int and item['room_version']==row['room_version'])
                else:valid=type(item.get('version')) is int and item['version']==row['version']
                if not valid:raise PlanningError('Un créneau a changé. Actualisez la sélection.',status=409)
                selected.append(dict(row,room_id=rid))
            issues=issues_for(selected,[r for r in all_rows if r['key'] not in keys])
            if issues:raise PlanningError('Aucune salle modifiée : la sélection comporte un conflit.',issues,409)
            owners=set();now=datetime.now(timezone.utc).isoformat()
            for row in selected:
                if row['source']=='session':
                    conn.execute('INSERT INTO planning_room_overrides(owner,slot_key,room_id) VALUES(?,?,?) ON CONFLICT(owner,slot_key) DO UPDATE SET room_id=excluded.room_id',
                                 (row['owner'],row['slot_key'],rid));owners.add(row['owner'])
                else:
                    conn.execute('UPDATE planning_courses SET room_id=?,version=version+1,updated_at=? WHERE id=?',(rid,now,row['id']))
            for owner in owners:conn.execute('UPDATE planning_room_owners SET room_version=room_version+1 WHERE owner=?',(owner,))
            return dict(count=len(selected),message='La salle a été modifiée pour tous les créneaux sélectionnés.')
        return transact(operation)

    @app.route('/admin/planning/api/rooms/unavailability',methods=['POST'])
    @app.route('/admin/planning/api/rooms/unavailability/<block_id>',methods=['PUT','DELETE'])
    def room_unavailability(block_id=None):
        def operation(conn,payload):
            existing=conn.execute('SELECT * FROM planning_room_unavailability WHERE id=?',(block_id,)).fetchone() if block_id else None
            if block_id and not existing:raise PlanningError('Cette indisponibilité n’existe plus.',status=404)
            if existing and (type(payload.get('version')) is not int or payload['version']!=existing['version']):
                raise PlanningError('Cette indisponibilité a changé. Actualisez le planning.',status=409)
            if request.method=='DELETE':
                conn.execute('DELETE FROM planning_room_unavailability WHERE id=?',(block_id,))
                return dict(message='L’indisponibilité a été supprimée.')
            rid=room(conn,payload.get('room_id'))
            first,last=_iso(payload.get('start_date')),_iso(payload.get('end_date'))
            if not 0<=(last-first).days<366:raise PlanningError('Choisissez une période de 366 jours au maximum.')
            start,end=_minutes(payload.get('start','00:00')),_minutes(payload.get('end','24:00'),True)
            if start>=end:raise PlanningError('L’heure de fin doit suivre l’heure de début.')
            reason=payload.get('reason')
            if not isinstance(reason,str) or not 1<=len(reason.strip())<=200:raise PlanningError('Indiquez un motif de 1 à 200 caractères.')
            proposed=[dict(room_id=rid,date=(first+timedelta(days=i)).isoformat(),start_min=start,end_min=end,title=reason.strip()) for i in range((last-first).days+1)]
            others=[r for r in snapshot(conn,first.isoformat(),last.isoformat())['reservations'] if not (r['source']=='unavailable' and r['id']==block_id)]
            issues=issues_for(proposed,others)
            if issues:raise PlanningError('La salle est déjà réservée. Réaffectez ces créneaux avant de la rendre indisponible.',issues,409)
            values=(rid,first.isoformat(),last.isoformat(),start,end,reason.strip())
            if existing:
                conn.execute('UPDATE planning_room_unavailability SET room_id=?,start_date=?,end_date=?,start_min=?,end_min=?,reason=?,version=version+1 WHERE id=?',(*values,block_id))
            else:
                conn.execute('INSERT INTO planning_room_unavailability(id,room_id,start_date,end_date,start_min,end_min,reason) VALUES(?,?,?,?,?,?,?)',(secrets.token_urlsafe(24),*values))
            return dict(message='L’indisponibilité a été enregistrée.')
        return transact(operation)

    @app.get('/admin/salles/export.pdf')
    def export_room_calendar():
        guard()
        try:
            first,last=_iso(request.args.get('start')),_iso(request.args.get('end'))
            if not 0<=(last-first).days<366:raise PlanningError('Exportez entre 1 et 366 jours.')
            from planning_rooms_pdf import build_pdf
            with closing(connect()) as conn:
                conn.execute('BEGIN')
                data=snapshot(conn,first.isoformat(),last.isoformat())
            response=send_file(BytesIO(build_pdf(data)),mimetype='application/pdf',as_attachment=True,
                               download_name=f'planning-salles-{first:%d-%m-%Y}-{last:%d-%m-%Y}.pdf')
            response.headers['Cache-Control']='no-store'
            return response
        except PlanningError as exc:return fail(exc)
