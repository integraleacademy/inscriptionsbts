"""Attendance boundaries, privacy, teaching content, documents and durable SMS."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import time

from flask import Flask, session
import pytest

import teaching as t
import teaching_reminders as reminders
from test_planning_portal_security import portal_db

ROOT = Path(__file__).resolve().parents[1]
PARIS = ZoneInfo('Europe/Paris')

@pytest.fixture
def env(portal_db, tmp_path, monkeypatch):
    app = Flask(__name__, template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
    app.secret_key = 'isolated-teaching-fixture-secret'
    app.config['TESTING'] = True
    app.jinja_env.filters['dmy'] = lambda value: value
    monkeypatch.setattr(t, 'now_paris', lambda: datetime(2027,1,4,9,30,tzinfo=PARIS))
    from daily_login import register_daily_login
    register_daily_login(app)
    t.register_teaching(app, portal_db, lambda: str(tmp_path/'uploads'), lambda: bool(session.get('admin_ok')))
    return app, portal_db, tmp_path


def logged(env, role='trainer', identity='t1'):
    client = env[0].test_client()
    with client.session_transaction() as state:
        state['_trainer_csrf'] = 'csrf'
        if role == 'trainer':
            state['_trainer_auth'] = dict(trainer_id=identity, version=1, expires_at=time.time()+3600)
        else:
            state['_student_auth'] = dict(account_id='account-'+identity,candidate_id=identity,version=1,expires_at=time.time()+3600)
    return client


def post(client, action, data, course='own'):
    return client.post('/formateur/cours/'+course+'/'+action,json=data,headers={'X-CSRF-Token':'csrf'})


def state(client, course='own'):
    return client.get('/formateur/cours/'+course+'/state').json


def call(client, **changes):
    snapshot = state(client)['attendance']
    return dict(version=snapshot['version'], students=[dict(id=s['id'],status=changes.get(s['id'],('present',0))[0],late_minutes=changes.get(s['id'],('present',0))[1]) for s in snapshot['students']])


def test_real_pages_and_unsaved_green_defaults(env):
    client = logged(env)
    for path in ['/formateur/pedagogie','/formateur/cours/own']:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert 'googletagmanager' not in response.text
    snapshot = state(client)
    assert {s['id'] for s in snapshot['attendance']['students']} == {'c1','c5'}
    assert all(s['status']=='present' for s in snapshot['attendance']['students'])
    assert snapshot['attendance']['completed_at'] is None
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM teaching_attendance').fetchone()[0] == 0
    assert 'secret-bearer' not in json.dumps(snapshot)
    assert 'secret-social' not in json.dumps(snapshot)


@pytest.mark.parametrize('hour,minute,second,allowed',[(8,59,59,False),(9,0,0,True),(10,59,59,True),(11,0,0,False),(11,0,1,False)])
def test_exact_attendance_time_boundaries(env, monkeypatch, hour, minute, second, allowed):
    monkeypatch.setattr(t,'now_paris',lambda:datetime(2027,1,4,hour,minute,second,tzinfo=PARIS))
    client=logged(env)
    response=post(client,'appel',call(client))
    assert response.status_code == (200 if allowed else 403)
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM teaching_rollcalls').fetchone()[0] == int(allowed)


@pytest.mark.parametrize('day', ['2027-03-28','2027-10-31'])
def test_paris_dst_window(day):
    course=dict(date=day,start_min=540,end_min=660)
    assert t.course_window(course,datetime.fromisoformat(day+'T09:00:00').replace(tzinfo=PARIS))['open']
    assert not t.course_window(course,datetime.fromisoformat(day+'T11:00:00').replace(tzinfo=PARIS))['open']


def test_call_is_atomic_versioned_and_mirrored_to_assiduite(env):
    client=logged(env)
    payload=call(client,c1=('late',12),c5=('absent',0))
    assert post(client,'appel',payload).status_code==200
    assert post(client,'appel',payload).status_code==409
    with env[1]() as conn:
        rows={r['candidate_id']:dict(r) for r in conn.execute('SELECT * FROM student_attendance WHERE deleted=0')}
        assert rows['c1']['kind']=='late' and rows['c1']['end_min']-rows['c1']['start_min']==12
        assert rows['c5']['kind']=='absence' and rows['c5']['end_min']==660
    assert post(client,'appel',call(client)).status_code==200
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM student_attendance WHERE deleted=0').fetchone()[0]==0
        assert conn.execute('SELECT version FROM teaching_rollcalls').fetchone()[0]==2
        assert conn.execute('SELECT COUNT(*) FROM teaching_audit').fetchone()[0]==2


@pytest.mark.parametrize('minutes', [0,-1,121,'12',True,1.5])
def test_invalid_lateness_does_not_partially_save(env,minutes):
    client=logged(env)
    payload=call(client,c1=('absent',0),c5=('late',minutes))
    assert post(client,'appel',payload).status_code==400
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM teaching_attendance').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM student_attendance').fetchone()[0]==0


def test_manual_attendance_and_admin_corrections_are_preserved(env):
    client=logged(env)
    assert post(client,'appel',call(client,c1=('absent',0))).status_code==200
    with env[1]() as conn:
        conn.execute("UPDATE student_attendance SET justification='justified',version=version+1")
    assert post(client,'appel',call(client,c1=('absent',0))).status_code==200
    assert post(client,'appel',call(client)).status_code==409
    with env[1]() as conn:
        assert conn.execute('SELECT justification FROM student_attendance').fetchone()[0]=='justified'


def test_roster_changes_csrf_and_foreign_scope(env):
    client=logged(env)
    payload=call(client)
    assert client.post('/formateur/cours/own/appel',json=payload).status_code==403
    assert logged(env,identity='t2').get('/formateur/cours/own').status_code==404
    assert env[0].test_client().get('/formateur/cours/own/state').status_code==401
    payload['students'][0]['id']='c2'
    assert post(client,'appel',payload).status_code==409
    with env[1]() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    assert client.get('/formateur/cours/own').status_code==404


def test_shared_course_roster_only_in_current_grants(env):
    client=logged(env)
    assert {s['id'] for s in state(client,'shared')['attendance']['students']}=={'c1','c2','c5'}
    with env[1]() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    assert {s['id'] for s in state(client,'shared')['attendance']['students']}=={'c2'}


def add_topics(env):
    with env[1]() as conn:
        t.schema(conn)
        conn.execute("UPDATE planning_subject_diplomas SET data=? WHERE subject_id='s1'",(json.dumps(dict(curriculum_topics='Analyser une situation\nOrganiser une intervention\nCommuniquer',pedagogical_content='Descriptif de la matière. Ceci ne doit pas être un thème.',objectives='Objectifs pédagogiques généraux',source_url='https://education.gouv.fr/referentiel')),))


def test_journal_uses_real_topics_and_is_available_to_student(env):
    add_topics(env)
    client=logged(env)
    topics=state(client)['topics']
    assert len(topics)==3
    payload=dict(version=0,content='Exercices réalisés en groupe.',topics=[topics[0]['id']])
    assert post(client,'cahier',payload).status_code==200
    assert post(client,'cahier',payload).status_code==409
    assert post(client,'cahier',dict(version=1,content='Changed',topics=['invented'])).status_code==409
    student=logged(env,'student','c1')
    response=student.get('/espace/cours/own')
    assert response.status_code==200 and 'Exercices réalisés en groupe.' in response.text
    assert 'ETUDIANT c5' not in response.text
    assert logged(env,'student','c2').get('/espace/cours/own').status_code==404


def test_ai_draft_is_private_not_autosaved_and_has_no_roster(env,monkeypatch):
    add_topics(env)
    sent=[]
    monkeypatch.setattr(t.subject_references,'api_key',lambda *a:'fixture')
    monkeypatch.setattr(t.subject_references,'provider',lambda key,**kw: sent.append(kw['payload']) or {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Une proposition.'}]}]})
    client=logged(env)
    response=post(client,'assistant',dict(task='journal',notes='Exercices',topics=[state(client)['topics'][0]['id']]))
    assert response.status_code==200 and response.json['draft']=='Une proposition.'
    assert sent[0]['store'] is False
    assert 'ETUDIANT' not in sent[0]['input'] and 'secret' not in sent[0]['input']
    assert state(client)['journal']['version']==0
    for _ in range(9):
        assert post(client,'assistant',dict(task='journal',notes='Exercice')).status_code==200
    assert post(client,'assistant',dict(task='journal',notes='Exercice')).status_code==429


def homework(client,**extra):
    return post(client,'devoir',{**dict(version=0,title='Étude de cas',instructions='Analyser la situation.',due_date='2027-01-10',scale=20,coefficient=2,published=False),**extra})


def test_homework_grades_privacy_bounds_and_concurrency(env):
    client=logged(env)
    response=homework(client)
    assert response.status_code==200
    hw=response.json['homework'][0]
    student=logged(env,'student','c1')
    assert 'Étude de cas' not in student.get('/espace/cours/own').text
    payload=dict(id=hw['id'],version=hw['version'],students=[dict(id='c1',status='graded',score=14.5,comment='Très bien'),dict(id='c5',status='graded',score=0,comment='commentaire confidentiel c5')])
    bad=json.loads(json.dumps(payload)); bad['students'][1]['score']=21
    assert post(client,'notes',bad).status_code==400
    assert post(client,'notes',payload).status_code==200
    assert post(client,'notes',payload).status_code==409
    hw=state(client)['homework'][0]
    update={k:hw[k] for k in ('id','version','title','instructions','due_date','scale','coefficient')}; update['published']=True
    assert post(client,'devoir',update).status_code==200
    response=student.get('/espace/devoirs-notes')
    assert response.status_code==200
    import re
    data=json.loads(re.search(r'id="gradebook-state">(.*?)</script>',response.text,re.S).group(1))
    assert data['items'][0]['grades'][0]['score']==14.5 and data['items'][0]['grades'][0]['comment']=='Très bien'
    assert 'commentaire confidentiel c5' not in response.text and 'ETUDIANT c5' not in response.text
    assert 'teaching_attendance' not in response.text


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,'oops',True])
def test_invalid_grades_are_rejected(env,value):
    client=logged(env); hw=homework(client).json['homework'][0]
    response=post(client,'notes',dict(id=hw['id'],version=1,students=[dict(id=sid,status='graded',score=value,comment='') for sid in ['c1','c5']]))
    assert response.status_code==400


def test_document_upload_download_revocation_and_content_validation(env):
    client=logged(env)
    headers={'X-CSRF-Token':'csrf'}
    response=client.post('/formateur/cours/own/documents',data={'file':(BytesIO(b'%PDF-1.7\nFixture'),'support.pdf')},headers=headers)
    assert response.status_code==201
    fid=response.json['id']
    student=logged(env,'student','c1')
    download=student.get('/espace/documents/'+fid)
    assert download.status_code==200 and download.headers['Content-Disposition'].startswith('attachment;')
    assert logged(env,'student','c2').get('/espace/documents/'+fid).status_code==404
    assert logged(env,identity='t2').get('/formateur/documents/'+fid).status_code==404
    assert client.post('/formateur/cours/own/documents',data={'file':(BytesIO(b'<script>'),'fake.pdf')},headers=headers).status_code==400
    assert client.post('/formateur/cours/own/documents',data={'file':(BytesIO(b'<script>'),'fake.html')},headers=headers).status_code==400
    assert post(client,'document-supprimer',dict(id=fid)).status_code==200
    assert student.get('/espace/documents/'+fid).status_code==404


def test_phone_and_reminders_skip_done_no_before_or_after_no_duplicate(env):
    client=logged(env)
    assert client.post('/formateur/pedagogie/telephone',data=dict(csrf_token='csrf',phone='06 12 34 56 78')).status_code==303
    sent=[]
    sender=lambda phone,message: sent.append((phone,message)) or ('sent','sms-fixture','')
    def run(hour,minute):
        return reminders.dispatch_reminders(env[0],env[1],now=datetime(2027,1,4,hour,minute,tzinfo=PARIS),sender=sender)
    assert run(9,59)==0 and not sent
    assert run(10,0)==1 and len(sent)==1
    assert sent[0][0]=='+33612345678' and '/formateur/cours/own#appel' in sent[0][1]
    assert run(10,1)==0 and run(11,0)==0 and len(sent)==1
    with env[1]() as conn:
        conn.execute('DELETE FROM teaching_reminders')
    assert post(client,'appel',call(client)).status_code==200
    assert run(10,0)==0


def test_missing_phone_and_ambiguous_delivery_do_not_generate_duplicates(env):
    client=logged(env); state(client)
    now=datetime(2027,1,4,10,0,tzinfo=PARIS)
    assert reminders.dispatch_reminders(env[0],env[1],now=now,sender=lambda *a:pytest.fail('missing phone'))==0
    with env[1]() as conn:
        assert conn.execute('SELECT status FROM teaching_reminders').fetchone()[0]=='blocked'
        conn.execute("INSERT INTO teaching_contacts VALUES('t1','+33612345678')")
    sent=[]
    sender=lambda *args: sent.append(args) or ('unknown',None,'Timed out')
    assert reminders.dispatch_reminders(env[0],env[1],now=now.replace(minute=1),sender=sender)==1
    assert reminders.dispatch_reminders(env[0],env[1],now=now.replace(minute=2),sender=sender)==0
    assert len(sent)==1


def test_manual_absence_cannot_be_silently_overridden_by_default_present(env):
    client=logged(env); state(client)
    with env[1]() as conn:
        conn.execute("INSERT INTO student_attendance(id,candidate_id,date,start_min,end_min,kind,justification,created_at,updated_at) VALUES('manual','c1','2027-01-04',540,660,'absence','pending','now','now')")
    assert post(client,'appel',call(client)).status_code==409
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM teaching_rollcalls').fetchone()[0]==0
        assert conn.execute("SELECT deleted FROM student_attendance WHERE id='manual'").fetchone()[0]==0


def test_revoked_group_grades_are_not_exposed_to_trainer(env):
    client=logged(env)
    hw=post(client,'devoir',dict(version=0,title='Cours commun',instructions='',due_date='2027-01-10',scale=20,coefficient=1,published=True),course='shared').json['homework'][0]
    with env[1]() as conn:
        conn.execute("INSERT INTO teaching_grades VALUES(?, 'c1', 12, 'graded', 'note groupe retiré', 'now')",(hw['id'],))
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    response=client.get('/formateur/cours/shared/state')
    assert response.status_code==200
    assert 'note groupe retiré' not in response.text


def test_reminder_claim_is_unique_across_workers(env):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    client=logged(env); state(client)
    with env[1]() as conn:
        conn.execute("INSERT INTO teaching_contacts VALUES('t1','+33612345678')")
    sent=[]; guard=threading.Lock()
    def sender(*args):
        with guard: sent.append(args)
        return 'sent','sms-concurrency',''
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:reminders.dispatch_reminders(env[0],env[1],now=datetime(2027,1,4,10,0,tzinfo=PARIS),sender=sender),[1,2]))
    assert sum(results)==1 and len(sent)==1


def test_sms_transport_uses_current_endpoint_and_bounds_time(monkeypatch):
    monkeypatch.setenv('BREVO_API_KEY','test-only-not-real')
    calls=[]
    class Response:
        status_code=201
        def json(self): return {'messageId':123}
    monkeypatch.setattr(reminders.requests,'post',lambda *a,**kw:calls.append((a,kw)) or Response())
    assert reminders.send_reminder('+33612345678','Test')==('sent','123','')
    assert calls[0][0][0]=='https://api.brevo.com/v3/transactionalSMS/send'
    assert calls[0][1]['timeout']==(3,10) and calls[0][1]['allow_redirects'] is False
    assert calls[0][1]['json']['type']=='transactional'


@pytest.mark.parametrize('value',[0.001,0.009,1.999])
def test_fractional_scale_underflow_rejected(value):
    with pytest.raises(t.PlanningError):
        t.decimal_field(value,'barème',1000)
