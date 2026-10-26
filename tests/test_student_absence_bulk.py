"""One evidence request across days/courses, with atomic decisions and private files."""
from html import unescape
from io import BytesIO
from pathlib import Path
import re

import pytest
import student_workspace as workspace
from test_student_workspace import env, company_env, student, admin, pdf, send, request_record


@pytest.fixture
def batch_env(env):
    with env[1]() as conn:
        for event,day,begin,end,kind,status in (
            ('b1','2026-10-21',510,600,'absence','pending'),
            ('b2','2026-10-21',780,900,'absence','unjustified'),
            ('b3','2026-11-02',510,525,'late','pending'),
            ('done','2026-10-22',510,600,'absence','justified'),
            ('gone','2026-10-23',510,600,'absence','pending'),
        ):
            conn.execute("INSERT INTO student_attendance VALUES(?,'s1',?,?,?,?,?,1,?,'now','now')",
                         (event,day,begin,end,kind,status,int(event=='gone')))
    return env


def hidden(page):
    return {key:unescape(value) for key,value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"',page.text)}


def payload(client, events=('a1','b1','b2','b3'), **changes):
    values=hidden(client.get('/espace/absences/justifier'))
    values.update(events=list(events),reason='illness',message='Un arrêt pour toute la période.',documents=(pdf(),'periode.pdf'))
    values.update(changes)
    return values


def submit(client,events=('a1','b1','b2','b3'),**changes):
    return client.post('/espace/absences/justifier',data=payload(client,events,**changes))


def decision(env,choice='accepted'):
    record=request_record(env);client=admin(env)
    path='/admin/assiduite/justificatifs/'+record['id']
    values=hidden(client.get(path));values.update(decision=choice,comment='Vérification de la période complète.')
    return client.post(path,data=values)


def counts(env):
    with env[1]() as conn:
        return tuple(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                     for table in ('absence_requests','absence_request_events','absence_files','absence_history'))


def test_selection_only_offers_own_unsubmitted_unjustified_events(batch_env):
    client=student(batch_env)
    assert send(client).status_code==303
    page=client.get('/espace/absences/justifier')
    assert page.status_code==200 and 'Cocher cette période' in page.text
    offered=re.findall(r'name="events" value="([^"]+)"',page.text)
    assert set(offered)=={'b1','b2','b3'}
    assert 'no-store' in page.headers['Cache-Control']
    assert page.text.count('aria-label="Navigation de l’espace étudiant"')==1


def test_one_request_one_file_all_periods_and_one_admin_decision(batch_env):
    client=student(batch_env)
    response=submit(client)
    assert response.status_code==303
    assert counts(batch_env)==(1,4,1,1)
    assert len(list((batch_env[3]/'absence-justifications').glob('*')))==1
    record=request_record(batch_env)
    for event in ('a1','b1','b2','b3'):
        page=client.get('/espace/absences/'+event)
        assert page.status_code==200 and '4 événements de cette demande' in page.text
        assert '20/10/2026' in page.text and '02/11/2026' in page.text
        assert 'periode.pdf' in page.text and 'En cours de traitement' in page.text
    queue=admin(batch_env).get('/admin/assiduite/justificatifs')
    assert queue.text.count('Examiner →')==1
    assert '4 événements' in queue.text
    assert 'Justificatifs étudiants · 1' in admin(batch_env).get('/admin/assiduite').text
    assert decision(batch_env).status_code==303
    with batch_env[1]() as conn:
        events=workspace.linked_events(conn,record['id'])
        assert len(events)==4 and all(e['justification']=='justified' for e in events)
        assert conn.execute("SELECT COUNT(*) FROM company_audit WHERE action='absence_review_accepted'").fetchone()[0]==4
    assert 'Aucune nouvelle absence' in client.get('/espace/absences/justifier').text
    assert not batch_env[2]


@pytest.mark.parametrize('choice,expected',[('needs_info','pending'),('rejected','unjustified')])
def test_complement_and_refusal_apply_to_whole_group_and_reuse_file(batch_env,choice,expected):
    client=student(batch_env);assert submit(client).status_code==303
    assert decision(batch_env,choice).status_code==303
    with batch_env[1]() as conn:
        assert {e['justification'] for e in workspace.linked_events(conn,request_record(batch_env)['id'])}=={expected}
    path='/espace/absences/b2'
    values=hidden(client.get(path));values.update(reason='illness',message='La pièce couvre bien les quatre cours.')
    assert client.post(path,data=values).status_code==303
    assert counts(batch_env)==(1,4,1,3)
    assert request_record(batch_env)['status']=='pending'
    assert decision(batch_env).status_code==303


@pytest.mark.parametrize('events,status',[([],400),(['a1','a2'],404),(['a1','gone'],404),(['a1','done'],409)])
def test_invalid_selection_is_atomic(batch_env,events,status):
    client=student(batch_env)
    data=payload(client,events,event_version_a2=1,event_version_gone=1,event_version_done=1)
    assert client.post('/espace/absences/justifier',data=data).status_code==status
    assert counts(batch_env)==(0,0,0,0)
    assert not list((batch_env[3]/'absence-justifications').glob('*'))


def test_duplicate_ids_do_not_duplicate_events_and_resend_cannot_create_second_request(batch_env):
    client=student(batch_env);data=payload(client,['a1','a1','b1'])
    assert client.post('/espace/absences/justifier',data=data).status_code==303
    assert counts(batch_env)==(1,2,1,1)
    assert submit(client,['a1'],event_version_a1=2).status_code==409
    assert counts(batch_env)==(1,2,1,1)


def test_stale_selected_event_prevents_entire_submission(batch_env):
    client=student(batch_env);values=payload(client)
    with batch_env[1]() as conn:
        conn.execute("UPDATE student_attendance SET version=version+1 WHERE id='b2'")
    assert client.post('/espace/absences/justifier',data=values).status_code==409
    assert counts(batch_env)==(0,0,0,0)


def test_stale_group_review_and_complement_are_rejected_as_a_whole(batch_env):
    client=student(batch_env);assert submit(client).status_code==303
    admin_client=admin(batch_env);path='/admin/assiduite/justificatifs/'+request_record(batch_env)['id']
    values=hidden(admin_client.get(path));values.update(decision='accepted',comment='Valide')
    addition=hidden(client.get('/espace/absences/a1'));addition.update(reason='illness',message='Un complément.')
    with batch_env[1]() as conn:
        conn.execute("UPDATE student_attendance SET version=version+1 WHERE id='b2'")
    assert admin_client.post(path,data=values).status_code==409
    assert client.post('/espace/absences/a1',data=addition).status_code==409
    assert request_record(batch_env)['status']=='pending'
    assert counts(batch_env)==(1,4,1,1)


def test_removed_anchor_keeps_shared_document_and_remaining_review(batch_env):
    client=student(batch_env);assert submit(client).status_code==303
    with batch_env[1]() as conn:
        doc=conn.execute('SELECT id FROM absence_files').fetchone()[0]
        conn.execute("UPDATE student_attendance SET deleted=1 WHERE id='a1'")
    assert client.get('/espace/absences/a1').status_code==404
    assert client.get('/espace/absences/b1').status_code==200
    assert client.get('/espace/absences/documents/'+doc).status_code==200
    assert student(batch_env,'s2').get('/espace/absences/documents/'+doc).status_code==404
    assert admin(batch_env).get('/admin/assiduite/justificatifs').text.count('Examiner →')==1
    assert 'Justificatifs étudiants · 1' in admin(batch_env).get('/admin/assiduite').text
    assert decision(batch_env).status_code==303
    with batch_env[1]() as conn:
        assert conn.execute("SELECT justification FROM student_attendance WHERE id='a1'").fetchone()[0]=='pending'


def test_correction_on_non_anchor_reopens_entire_request(batch_env):
    client=student(batch_env);assert submit(client).status_code==303
    assert decision(batch_env).status_code==303
    with batch_env[1]() as conn:
        event=dict(conn.execute("SELECT * FROM student_attendance WHERE id='b2'").fetchone())
    values=dict(csrf_token='admin-csrf',record_id='b2',version=event['version'],candidate_id='s1',
                date='2026-10-21',start='13:00',end='15:30',kind='absence',justification='justified')
    assert admin(batch_env).post('/admin/assiduite',data=values).status_code==303
    with batch_env[1]() as conn:
        assert all(e['justification']=='pending' for e in workspace.linked_events(conn,request_record(batch_env)['id']))
    assert request_record(batch_env)['status']=='pending'
    assert 'Période corrigée' in client.get('/espace/absences/b1').text


def test_legacy_request_mapping_is_idempotent_and_file_still_works(batch_env):
    client=student(batch_env);assert send(client).status_code==303
    record=request_record(batch_env)
    with batch_env[1]() as conn:
        doc=conn.execute('SELECT id FROM absence_files').fetchone()[0]
        conn.execute('DROP TABLE absence_request_events')
        workspace.ensure_workspace_schema(conn)
        workspace.ensure_workspace_schema(conn)
    assert counts(batch_env)==(1,1,1,1)
    assert request_record(batch_env)==record
    assert client.get('/espace/absences/documents/'+doc).status_code==200


def test_disk_failure_rolls_back_entire_group(batch_env,monkeypatch):
    def fail(*args,**kwargs):
        raise OSError('disk failure')
    monkeypatch.setattr(Path,'chmod',fail)
    with pytest.raises(OSError):
        submit(student(batch_env))
    assert counts(batch_env)==(0,0,0,0)
    assert not list((batch_env[3]/'absence-justifications').glob('*'))


def test_group_across_own_dossiers_is_private_after_account_membership_changes(batch_env):
    with batch_env[1]() as conn:
        conn.execute("UPDATE student_account_members SET account_id='s1' WHERE candidate_id='s2'")
    client=student(batch_env);assert submit(client,['a1','a2']).status_code==303
    with batch_env[1]() as conn:
        doc=conn.execute('SELECT id FROM absence_files').fetchone()[0]
        conn.execute("UPDATE student_account_members SET account_id='s2' WHERE candidate_id='s2'")
    for owner in (client,student(batch_env,'s2')):
        assert owner.get('/espace/absences/documents/'+doc).status_code==404
    assert client.get('/espace/absences/a1').status_code==404


def test_bulk_auth_csrf_document_and_selection_limit(batch_env):
    path='/espace/absences/justifier'
    assert batch_env[0].test_client().get(path).headers['Location']=='/espace/connexion'
    client=student(batch_env)
    assert submit(client,csrf_token='bad').status_code==400
    assert submit(client,documents=[]).status_code==400
    assert submit(client,documents=(BytesIO(b'bad'),'fake.pdf')).status_code==400
    assert submit(client,[str(i) for i in range(201)]).status_code==400
    assert counts(batch_env)==(0,0,0,0)


def test_company_work_requires_planning_for_group_then_reuses_it_for_complement(batch_env):
    client=student(batch_env)
    reply=submit(client,reason='company_work',documents=[])
    assert reply.status_code==400 and 'Joins le planning de ton entreprise' in reply.text
    assert counts(batch_env)==(0,0,0,0)
    assert submit(client,reason='company_work',documents=(pdf(),'planning-entreprise.pdf')).status_code==303
    assert request_record(batch_env)['status']=='pending'
    assert counts(batch_env)==(1,4,1,1)
    assert decision(batch_env,'needs_info').status_code==303
    path='/espace/absences/b2'
    data=hidden(client.get(path));data.update(reason='company_work',message='Le planning joint couvre tous les cours sélectionnés.')
    assert client.post(path,data=data).status_code==303
    assert request_record(batch_env)['status']=='pending'
    assert counts(batch_env)==(1,4,1,3)


def test_switching_to_company_work_requires_new_planning_even_with_existing_document(batch_env):
    client=student(batch_env)
    assert send(client,reason='illness').status_code==303
    before=request_record(batch_env)
    assert send(client,reason='company_work',documents=[]).status_code==400
    assert request_record(batch_env)==before
    assert counts(batch_env)==(1,1,1,1)
    assert send(client,reason='company_work',documents=(pdf(),'planning-entreprise.pdf')).status_code==303
    assert request_record(batch_env)['reason']=='company_work'
    assert request_record(batch_env)['status']=='pending'
    assert counts(batch_env)==(1,1,2,2)
