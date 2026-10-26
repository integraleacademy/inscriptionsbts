"""Student evidence lifecycle, cross-account isolation, and administrative review."""
from io import BytesIO
from pathlib import Path
import re
import time

from flask import session, render_template
from pypdf import PdfWriter
import pytest

import candidate_access
import student_workspace as workspace
from test_company_portal import env as company_env, admin, logged as company_logged


@pytest.fixture
def env(company_env, tmp_path):
    app, db, mails = company_env
    with db() as conn:
        candidate_access._schema(conn)
        for cid in ('s1','s2'):
            conn.execute("INSERT INTO student_accounts VALUES(?,'unused-test-hash',0,1,0,0)", (cid,))
            conn.execute('INSERT INTO student_account_members VALUES(?,?)', (cid,cid))
        conn.execute("UPDATE companies SET address='12 rue des Oliviers',city='Puget',siret='12345678900012' WHERE id='e1'")
    candidate_access.register_candidate_access(app,db,lambda *a:False)
    workspace.register_student_workspace(app,db,lambda:str(tmp_path/'uploads'),lambda:bool(session.get('admin_ok')))
    @app.get('/espace/<slug>')
    def espace_candidat(slug):
        return 'dossier'
    return app,db,mails,tmp_path


def student(env,cid='s1'):
    client=env[0].test_client()
    with client.session_transaction() as state:
        state['_student_auth']=dict(account_id=cid,candidate_id=cid,version=1,expires_at=time.time()+3600)
        state['_candidate_access_csrf']='student-csrf'
    return client


def pdf():
    writer=PdfWriter();writer.add_blank_page(width=200,height=200)
    data=BytesIO();writer.write(data);data.seek(0)
    return data


def send(client,event='a1',**changes):
    page=client.get('/espace/absences/'+event)
    values={key:re.search(fr'name="{key}" value="([^"]+)"',page.text).group(1) for key in ('csrf_token','version','event_version')}
    values.update(reason='illness',message='Document couvrant la période',documents=(pdf(),'arret.pdf'))
    values.update(changes)
    return client.post('/espace/absences/'+event,data=values)


def request_record(env):
    with env[1]() as conn:
        return dict(conn.execute('SELECT * FROM absence_requests ORDER BY submitted_at DESC LIMIT 1').fetchone())


def review(env,decision='accepted',comment='Justificatif vérifié.'):
    record=request_record(env);client=admin(env)
    with env[1]() as conn:
        event=dict(conn.execute('SELECT * FROM student_attendance WHERE id=?',(record['attendance_id'],)).fetchone())
    return client.post('/admin/assiduite/justificatifs/'+record['id'],data=dict(csrf_token='admin-csrf',version=record['version'],event_version=event['version'],decision=decision,comment=comment))


def test_list_has_all_periods_only_own_events_and_one_menu(env):
    with env[1]() as conn:
        conn.execute("INSERT INTO student_attendance VALUES('old','s1','2025-01-02',510,520,'late','unjustified',1,0,'now','now')")
    reply=student(env).get('/espace/absences')
    assert reply.status_code==200
    assert '/espace/absences/a1' in reply.text and '/espace/absences/old' in reply.text
    assert '/espace/absences/a2' not in reply.text
    assert reply.text.count('aria-label="Navigation de l’espace étudiant"')==1
    assert 'Choisir un espace' not in reply.text
    assert '05/01/2025' not in reply.text
    assert '02/01/2025' in reply.text
    assert '/espace/absences/old' not in student(env).get('/espace/absences?month=2026-10').text
    assert student(env).get('/espace/absences?month=2026-13').status_code==400
    assert 'no-store' in reply.headers['Cache-Control']


def test_treatment_dates_are_displayed_in_paris():
    assert workspace.display_date('2026-10-25T23:30:00+00:00')=='26/10/2026'
    assert workspace.display_date('2026-10-25')=='25/10/2026'


def test_submit_pending_review_and_student_company_projection(env):
    client=student(env)
    assert send(client).status_code==303
    pending=client.get('/espace/absences/a1')
    assert 'En cours de traitement' in pending.text and 'arret.pdf' in pending.text
    assert 'href="/espace/absences/documents/' in pending.text
    record=request_record(env)
    admin_page=admin(env).get('/admin/assiduite/justificatifs/'+record['id'])
    assert admin_page.status_code==200 and 'Document couvrant la période' in admin_page.text
    assert review(env).status_code==303
    done=client.get('/espace/absences/a1')
    assert 'Justificatif validé' in done.text and 'Justificatif vérifié.' in done.text
    assert 'data-absence-form' not in done.text
    with env[1]() as conn:
        assert conn.execute("SELECT justification FROM student_attendance WHERE id='a1'").fetchone()[0]=='justified'
    company=company_logged(env).get('/entreprise?tab=attendance&month=2026-10')
    assert 'Justifié' in company.text
    for private in ('arret.pdf','Document couvrant','illness','Justificatif vérifié'):
        assert private not in company.text
    assert not env[2]


def test_request_complement_then_resubmit_then_refuse(env):
    client=student(env);assert send(client).status_code==303
    assert review(env,'needs_info','Merci de préciser les dates.').status_code==303
    assert 'À compléter' in client.get('/espace/absences').text
    assert send(client,documents=[],message='Les dates sont précisées sur le document.').status_code==303
    assert request_record(env)['status']=='pending'
    assert review(env,'rejected','La période ne correspond pas.').status_code==303
    page=client.get('/espace/absences/a1')
    assert 'Refusée' in page.text and 'Merci de préciser les dates.' in page.text and 'Complément envoyé' in page.text
    assert send(client).status_code==303
    assert request_record(env)['status']=='pending'


@pytest.mark.parametrize('path',['/espace/absences','/espace/entreprise','/espace/absences/a1'])
def test_authentication_and_initial_password_required(env,path):
    assert env[0].test_client().get(path).headers['Location']=='/espace/connexion'
    assert admin(env).get(path).headers['Location']=='/espace/connexion'
    with env[1]() as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='s1'")
    assert student(env).get(path).headers['Location']=='/espace/mot-de-passe'


def test_files_private_scoped_and_persist_outside_dossier_cleanup(env):
    owner=student(env);assert send(owner).status_code==303
    with env[1]() as conn:
        doc=dict(conn.execute('SELECT * FROM absence_files').fetchone())
    path='/espace/absences/documents/'+doc['id']
    assert owner.get(path).status_code==200
    assert 'attachment' in owner.get(path).headers['Content-Disposition']
    assert owner.get(path).data.startswith(b'%PDF-')
    assert student(env,'s2').get(path).status_code==404
    assert env[0].test_client().get(path).status_code==403
    assert company_logged(env).get(path).status_code==403
    assert (env[3]/'absence-justifications'/doc['storage_name']).exists()
    assert not (env[3]/'uploads'/doc['storage_name']).exists()
    assert admin(env).get('/admin/assiduite/justificatifs/documents/'+doc['id']).status_code==200
    assert owner.get('/admin/assiduite/justificatifs/documents/'+doc['id']).status_code==403
    with env[1]() as conn:
        conn.execute("UPDATE student_accounts SET version=2 WHERE id='s1'")
    assert owner.get(path).status_code==403


def test_cross_account_write_and_csrf_rejected(env):
    other=student(env,'s2')
    assert other.get('/espace/absences/a1').status_code==404
    assert other.post('/espace/absences/a1',data={'csrf_token':'student-csrf'}).status_code==404
    assert send(student(env),csrf_token='bad').status_code==400
    assert student(env).get('/admin/assiduite/justificatifs').status_code==403


@pytest.mark.parametrize('filename,data',[('bad.pdf',b'<html>not PDF</html>'),('bad.png',b'not an image'),('file.html',b'bad'),('file.pdf',b'')])
def test_invalid_documents_leave_no_request_or_files(env,filename,data):
    assert send(student(env),documents=(BytesIO(data),filename)).status_code==400
    with env[1]() as conn:
        assert conn.execute('SELECT count(*) FROM absence_requests').fetchone()[0]==0
    assert not list((env[3]/'absence-justifications').glob('*'))


def test_required_evidence_reason_and_comment(env):
    client=student(env)
    assert send(client,documents=[]).status_code==400
    assert send(client,reason='automatic-accept').status_code==400
    assert send(client,reason='other',message='').status_code==400
    assert send(client).status_code==303
    assert review(env,'rejected','').status_code==400
    assert request_record(env)['status']=='pending'


def test_stale_submit_and_stale_admin_review_are_atomic(env):
    client=student(env);assert send(client).status_code==303
    before=request_record(env)
    assert send(client,version='0').status_code==409
    assert request_record(env)==before
    assert review(env).status_code==303
    admin_client=admin(env)
    assert admin_client.post('/admin/assiduite/justificatifs/'+before['id'],data=dict(csrf_token='admin-csrf',version=before['version'],event_version=2,decision='rejected',comment='Une autre décision')).status_code==409
    assert request_record(env)['status']=='accepted'


def test_admin_correction_reopens_review_and_prevents_reassignment(env):
    assert send(student(env)).status_code==303;assert review(env).status_code==303
    with env[1]() as conn:
        event=dict(conn.execute("SELECT * FROM student_attendance WHERE id='a1'").fetchone())
    data=dict(csrf_token='admin-csrf',record_id='a1',version=event['version'],candidate_id='s2',date='2026-10-20',start='09:00',end='10:30',kind='absence',justification='justified')
    assert admin(env).post('/admin/assiduite',data=data).status_code==400
    data['candidate_id']='s1'
    assert admin(env).post('/admin/assiduite',data=data).status_code==303
    assert request_record(env)['status']=='pending'
    assert 'Période corrigée' in student(env).get('/espace/absences/a1').text


def test_company_only_own_grant_and_empty_state(env):
    page=student(env).get('/espace/entreprise')
    assert page.status_code==200
    assert 'Entreprise 1' in page.text and 'Tuteur 1' in page.text
    assert 'Entreprise 2' not in page.text and 'password_hash' not in page.text and 'secret-nir' not in page.text
    with env[1]() as conn:
        conn.execute("DELETE FROM company_students WHERE candidate_id='s1'")
    assert 'Aucune entreprise rattachée' in student(env).get('/espace/entreprise').text


def test_multiple_dossiers_same_account_have_all_absences(env):
    with env[1]() as conn:
        conn.execute("UPDATE student_account_members SET account_id='s1' WHERE candidate_id='s2'")
    page=student(env).get('/espace/absences')
    assert '/espace/absences/a1' in page.text and '/espace/absences/a2' in page.text
    assert send(student(env),event='a2').status_code==303


def test_html_is_escaped_in_student_and_admin_comments(env):
    assert send(student(env),message='<script>alert(1)</script>').status_code==303
    record=request_record(env)
    assert '<script>alert(1)</script>' not in admin(env).get('/admin/assiduite/justificatifs/'+record['id']).text
    assert review(env,'needs_info','<script>alert(2)</script>').status_code==303
    assert '<script>alert(2)</script>' not in student(env).get('/espace/absences/a1').text


def test_revoked_session_during_upload_cannot_commit(env,monkeypatch):
    original=workspace.validated_files
    def revoke(files):
        prepared=original(files)
        with env[1]() as conn:
            conn.execute("UPDATE student_accounts SET version=version+1 WHERE id='s1'")
        return prepared
    monkeypatch.setattr(workspace,'validated_files',revoke)
    assert send(student(env)).status_code==403
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM absence_requests').fetchone()[0]==0
    assert not list((env[3]/'absence-justifications').glob('*'))


def test_upload_failure_rolls_back_request_and_written_file(env,monkeypatch):
    original=Path.chmod
    def failure(path,*args,**kwargs):
        if path.parent.name=='absence-justifications':
            raise OSError('simulated disk write failure')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'chmod',failure)
    with pytest.raises(OSError):
        send(student(env))
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM absence_requests').fetchone()[0]==0
    assert not list((env[3]/'absence-justifications').glob('*'))


def test_total_document_limit_and_deleted_absence(env,monkeypatch):
    client=student(env)
    monkeypatch.setattr(workspace,'FILE_LIMIT',100)
    assert send(client).status_code==400
    monkeypatch.setattr(workspace,'FILE_LIMIT',10*1024*1024)
    assert send(client,documents=[(pdf(),str(n)+'.pdf') for n in range(5)]).status_code==303
    assert send(client).status_code==400
    with env[1]() as conn:
        assert conn.execute('SELECT COUNT(*) FROM absence_files').fetchone()[0]==5
        doc=conn.execute('SELECT id FROM absence_files LIMIT 1').fetchone()[0]
        conn.execute("UPDATE student_attendance SET deleted=1 WHERE id='a1'")
    assert client.get('/espace/absences/a1').status_code==404
    assert client.get('/espace/absences/documents/'+doc).status_code==404
    assert '/espace/absences/a1' not in client.get('/espace/absences').text
