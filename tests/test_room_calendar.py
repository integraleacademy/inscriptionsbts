"""Cross-source room moves, closures and lossless projection upgrade."""
from copy import deepcopy
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest
from pypdf import PdfReader
import planning_rooms
from test_planning import db, app, client, call, BASE, setup_school, add, admin
from test_planning_rooms_events import event, reservation, machine, linked


def seed(client, **changes):
    data=reservation(**changes)
    result=machine(client,'prepare',data)
    assert result.status_code==200,result.json
    assert machine(client,'finish',dict(token=result.json['token'],commit=True)).status_code==200
    return data


def schedule(client):
    result=client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10')
    assert result.status_code==200,result.json
    return result.json['reservations']


def move(client,rows,room='r2'):
    return call(client,'/rooms/calendar-move',dict(room_id=room,slots=rows))


def block(client,**changes):
    data=dict(room_id='r2',start_date='2027-01-04',end_date='2027-01-05',reason='Travaux')
    data.update(changes)
    return call(client,'/rooms/unavailability',data)


def test_mixed_selection_moves_exactly_chosen_slots_and_conflict_checks_effective_rooms(linked,client,db):
    seed(client,slots=[dict(room_id='r1',date=d,start='09:00',end='11:00') for d in ['2027-01-04','2027-01-05']])
    c=event(client,start='12:00',end='13:00',room_id='r1').json['course']
    rows=[r for r in schedule(client) if r['date']=='2027-01-04']
    assert move(client,rows).status_code==200
    after=schedule(client)
    assert {r['room_id'] for r in after if r['date']=='2027-01-04'}=={'r2'}
    assert next(r for r in after if r['date']=='2027-01-05')['room_id']=='r1'
    assert event(client,room_id='r1',promotion_id='p2').status_code==200
    assert event(client,room_id='r2',promotion_id='p1').status_code==409
    assert machine(client,'prepare',reservation(owner='session:other',room='r2')).status_code==409
    assert call(client,'/rooms/r2',dict(active=False),'PUT').status_code==409
    assert move(client,rows,'r1').status_code==409
    with db() as conn:
        saved=dict(conn.execute('SELECT * FROM planning_courses WHERE id=?',(c['id'],)).fetchone())
        assert saved['title']==c['title'] and saved['version']==2


def test_mixed_batch_rejected_whole_if_one_conflict_or_stale(linked,client):
    seed(client)
    event(client,start='12:00',end='13:00',room_id='r1')
    blocked=event(client,promotion_id='p2',room_id='r2',start='12:00',end='13:00').json['course']
    rows=[r for r in schedule(client) if r.get('id')!=blocked['id']]
    assert move(client,rows).status_code==409
    assert {r['room_id'] for r in schedule(client) if r['key'] in {x['key'] for x in rows}}=={'r1'}
    stale=deepcopy(rows);next(r for r in stale if r['source']=='session')['room_version']=0
    assert move(client,stale,'r1').status_code==409
    assert move(client,rows+rows).status_code==400


def test_multi_date_batch_keeps_times_exam_and_one_version_per_session(linked,client,db):
    seed(client,slots=[dict(room_id='r1',date=d,start='09:00',end='11:00') for d in ['2027-01-04','2027-01-06']],
         metadata=dict(name='APS JANVIER 2027',formation='APS',exam_dates=['2027-01-06']))
    event(client,date='2027-01-05',room_id='r1')
    untouched=event(client,date='2027-01-07',room_id='r1').json['course']
    rows=[r for r in schedule(client) if r['date']<'2027-01-07']
    before={r['key']:(r['date'],r['start_min'],r['end_min'],r.get('exam',False)) for r in rows}
    assert move(client,rows).status_code==200
    after=schedule(client)
    chosen=[r for r in after if r['key'] in before]
    assert len(chosen)==3 and all(r['room_id']=='r2' for r in chosen)
    assert {r['key']:(r['date'],r['start_min'],r['end_min'],r.get('exam',False)) for r in chosen}==before
    old_version=next(r['room_version'] for r in rows if r['source']=='session')
    assert {r['room_version'] for r in chosen if r['source']=='session'}=={old_version+1}
    assert next(r for r in after if r.get('id')==untouched['id'])['room_id']=='r1'


def test_selected_courses_cannot_overlap_in_destination(client):
    a=event(client,room_id='r1').json['course']
    event(client,promotion_id='p2',room_id='r2')
    assert move(client,schedule(client)).status_code==409
    assert next(r for r in schedule(client) if r['id']==a['id'])['room_id']=='r1'


def test_override_survives_source_metadata_change_and_aborted_global_assignment(linked,client,db):
    original=seed(client,metadata=dict(name='APS JANVIER',formation='APS',assignment='initial'))
    assert move(client,schedule(client)).status_code==200
    update=dict(original,revision='2'*64,previous_revision='1'*64,metadata=dict(original['metadata'],name='APS JANVIER 2027'))
    token=machine(client,'prepare',update).json['token']
    assert move(client,schedule(client),'r1').status_code==409
    machine(client,'finish',dict(token=token,commit=True))
    assert schedule(client)[0]['room_id']=='r2' and schedule(client)[0]['title']=='APS JANVIER 2027'
    reset=dict(update,revision='3'*64,previous_revision='2'*64,metadata=dict(update['metadata'],assignment='new'))
    token=machine(client,'prepare',reset).json['token']
    assert {r['room_id'] for r in schedule(client)}=={'r1','r2'}
    machine(client,'finish',dict(token=token,commit=False))
    assert schedule(client)[0]['room_id']=='r2'
    token=machine(client,'prepare',reset).json['token']
    machine(client,'finish',dict(token=token,commit=True))
    assert schedule(client)[0]['room_id']=='r1'
    with db() as conn:assert conn.execute('SELECT COUNT(*) FROM planning_room_overrides').fetchone()[0]==0


def test_closure_blocks_both_sources_and_all_room_assignments(client,linked,db):
    assert block(client).status_code==200
    rows=schedule(client);assert len(rows)==2 and all(r['source']=='unavailable' for r in rows)
    assert event(client,room_id='r2').status_code==409
    c=event(client,room_id='r1').json['course']
    assert call(client,'/rooms/courses/'+c['id']+'/assign',dict(version=1,room_id='r2')).status_code==409
    assert machine(client,'prepare',reservation(room='r2')).status_code==409
    assert call(client,'/rooms/r2',{},'DELETE').status_code==409
    b=next(r for r in schedule(client) if r['source']=='unavailable')
    payload=dict(version=b['version'],room_id='r2',start_date=b['start_date'],end_date=b['end_date'],start='11:00',end='12:00',reason='Intervention')
    assert call(client,'/rooms/unavailability/'+b['id'],payload,'PUT').status_code==200
    assert event(client,promotion_id='p2',room_id='r2').status_code==200
    assert call(client,'/rooms/unavailability/'+b['id'],dict(version=1),'DELETE').status_code==409
    assert call(client,'/rooms/unavailability/'+b['id'],dict(version=2),'DELETE').status_code==200
    assert not any(r['source']=='unavailable' for r in schedule(client))


def test_closure_never_evicts_existing_booking_and_invalid_input(client):
    event(client,room_id='r2')
    assert block(client).status_code==409
    assert not any(r['source']=='unavailable' for r in schedule(client))
    for data in [dict(start_date='2027-02-01',end_date='2027-01-01'),dict(end_date='2029-01-01'),dict(reason=''),dict(start='12:00',end='11:00'),dict(room_id='bad')]:
        assert block(client,**data).status_code==400


def test_closure_and_source_race_have_one_winner(linked,app):
    gate=Barrier(2)
    def writer(n):
        client=admin(app);gate.wait()
        return (block(client) if n==0 else machine(client,'prepare',reservation(room='r2'))).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(writer,[0,1]))==[200,409]


def test_projection_upgrade_requires_exact_legacy_revision_and_keeps_new_exam_conflict(linked,client,db):
    old=seed(client)
    event(client,room_id='r1',date='2027-01-05')
    new=dict(old,revision='2'*64,legacy_revision='f'*64,schema=2,title='APS JANVIER 2027',
             metadata=dict(name='APS JANVIER 2027',formation='APS',start='2027-01-04',exam_dates=['2027-01-05'],exam_full_day=['2027-01-05']),
             slots=old['slots']+[dict(room_id='r1',date='2027-01-05',start='00:00',end='24:00')])
    machine(client,'reconcile',dict(owners=[new]))
    assert len([r for r in schedule(client) if r['source']=='session'])==1
    new['legacy_revision']=old['revision']
    result=machine(client,'reconcile',dict(owners=[new]))
    assert result.status_code==200 and result.json['calendar_owners']==1
    rows=schedule(client);exam=next(r for r in rows if r.get('exam'))
    assert exam['conflict'] and exam['exam_full_day'] and exam['title']=='APS JANVIER 2027'
    assert exam['formation']=='APS' and exam['presence_start']=='2027-01-04'
    version=exam['room_version'];machine(client,'reconcile',dict(owners=[new]))
    assert next(r for r in schedule(client) if r.get('exam'))['room_version']==version


def test_upgrade_can_reconcile_v1_pending_saved_revision(linked,client):
    seed(client)
    pending=reservation(revision='2',room='r2',previous_revision='1'*64)
    machine(client,'prepare',pending)
    new=dict(pending,revision='3'*64,legacy_revision='2'*64,schema=2,metadata=dict(name='A3P',formation='A3P'))
    assert machine(client,'reconcile',dict(owners=[new])).status_code==200
    rows=schedule(client)
    assert len(rows)==1 and rows[0]['room_id']=='r2' and rows[0]['revision']=='3'*64 and not rows[0]['pending']


def test_sync_runs_without_database_write_lock_and_reports_failure(linked,client,monkeypatch):
    from planning import PlanningError
    def sync(*args):
        assert machine(client,'reconcile',dict(owners=[])).status_code==200
        raise PlanningError('Connexion temporairement indisponible',status=503)
    monkeypatch.setattr(planning_rooms,'remote',sync)
    result=client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10&sync=1')
    assert result.status_code==200 and result.json['sync_warning']=='Connexion temporairement indisponible'


def test_pdf_inclusive_dates_full_names_colors_exams_and_permissions(client,app,linked):
    seed(client,metadata=dict(name='APS JANVIER 2027',formation='APS',start='2027-01-04',exam_dates=['2027-01-04']))
    block(client)
    url='/admin/salles/export.pdf?start=2027-01-04&end=2027-01-05'
    assert app.test_client().get(url).status_code==403
    response=client.get(url)
    assert response.status_code==200 and response.mimetype=='application/pdf'
    assert response.headers['Cache-Control']=='no-store'
    reader=PdfReader(BytesIO(response.data));text='\n'.join(p.extract_text() for p in reader.pages)
    assert '04/01/2027' in text and '05/01/2027' in text and '2027-01-04' not in text
    assert 'APS JANVIER 2027' in text and 'Travaux' in text and 'EXAMEN' in text
    assert all(label in text for label in ['A3P','APS','DESP','SSIAP','BTS'])
    assert client.get(url.replace('end=2027-01-05','end=2029-01-01')).status_code==400
    assert client.get(url.replace('end=2027-01-05','end=2027-01-03')).status_code==400


def test_mutations_require_admin_and_csrf(client,app):
    for path in ['/rooms/calendar-move','/rooms/unavailability']:
        assert app.test_client().post(BASE+path,json={}).status_code==403
        assert client.post(BASE+path,json={}).status_code==400


def test_source_cannot_overlap_another_slot_after_manual_override(linked,client):
    original=seed(client)
    assert move(client,schedule(client)).status_code==200
    changed=dict(original,revision='2'*64,previous_revision='1'*64,
                 slots=original['slots']+[dict(room_id='r2',date='2027-01-04',start='10:00',end='12:00')])
    response=machine(client,'prepare',changed)
    assert response.status_code==409
    assert len(schedule(client))==1 and schedule(client)[0]['room_id']=='r2'


def test_source_name_only_edit_preserves_historical_conflict(client,monkeypatch):
    event(client,room_id='r1')
    monkeypatch.setenv('SHARED_ROOMS_TOKEN','room-test');monkeypatch.setenv('SESSION_ROOMS_URL','https://sessions.example.test')
    original=reservation(metadata=dict(name='Ancien nom',formation='APS'))
    assert machine(client,'bootstrap',dict(owners=[original])).status_code==200
    update=dict(original,revision='2'*64,previous_revision='1'*64,metadata=dict(name='APS JANVIER 2027',formation='APS'))
    prepared=machine(client,'prepare',update)
    assert prepared.status_code==200,prepared.json
    machine(client,'finish',dict(token=prepared.json['token'],commit=True))
    assert all(r['conflict'] for r in schedule(client))
    assert next(r for r in schedule(client) if r['source']=='session')['title']=='APS JANVIER 2027'


def test_crowded_pdf_continues_rooms_and_keeps_every_booking():
    from planning_rooms_pdf import build_pdf
    rows=[dict(room_id='r1',date='2027-01-04',start='09:00',end='11:00',start_min=540,end_min=660,
               formation='BTS',title=f'Créneau {n:03d} · Préparation de la prestation de sécurité et réunion de coordination',
               promotion_name='BTS MOS 2026–2028') for n in range(36)]
    data=dict(start='2027-01-04',end='2027-01-10',rooms=[dict(id='r1',name='Salle principale')],reservations=rows)
    reader=PdfReader(BytesIO(build_pdf(data)));text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>2
    assert all(f'Créneau {n:03d}' in text for n in range(36))
    assert '(suite)' in text
