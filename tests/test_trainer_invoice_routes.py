"""Exercise real Flask routes/SQLite schemas with the AI provider mocked."""
from copy import deepcopy
from io import BytesIO
import json
import sqlite3
import time

import pytest
pytest.importorskip('flask')
from flask import Flask, session
from pypdf import PdfWriter

import trainer_access
import trainer_invoices
from trainer_admin_planning import register_admin_trainer_planning
from trainer_invoice_audit import InvoiceError
from trainer_invoices import ensure_invoice_schema, read_invoice, validate_file
from trainer_workload import save_hourly_rate
from test_trainer_invoice_audit import extraction, context


def pdf(pages=1, password=None):
    writer=PdfWriter()
    for _ in range(pages):writer.add_blank_page(width=300,height=400)
    if password:writer.encrypt(password)
    stream=BytesIO();writer.write(stream);return stream.getvalue()


@pytest.fixture
def setup(tmp_path,monkeypatch):
    path=tmp_path/'test.sqlite'
    def connect():
        conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
    with connect() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,bts TEXT,rentree_annee INTEGER,statut TEXT)')
        trainer_access._schema(conn);ensure_invoice_schema(conn)
        for tid in ('t1','t2'):
            conn.execute('INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (tid,'MARTIN','Camille',tid+'@example.test','now','now'))
        conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     ('p1','BTS CI 1','CI',1,2026,'2026-09-01','2027-07-31','now','now'))
        conn.execute('INSERT INTO trainer_promotions VALUES(?,?)',('t1','p1'))
        conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)',('s1','p1','Anglais','t1','#555555',100))
        conn.execute('INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,date,start_min,end_min,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     ('c1','p1','s1','t1','2026-10-05',480,600,'Anglais','now','now'))
        conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)',('c1','p1','s1'))
        save_hourly_rate(conn,'t1','2026-09-01','45',0);conn.commit()
    app=Flask(__name__);app.secret_key='test-secret-not-a-production-secret'
    app.config.update(TESTING=True,TRAINER_INVOICE_DIR=str(tmp_path/'invoices'))
    guard=lambda:session.get('admin') is True
    trainer_access.register_trainer_access(app,connect,lambda *a,**k:True,guard)
    register_admin_trainer_planning(app,connect,guard)
    client=app.test_client()
    with client.session_transaction() as s:s['admin']=True;s['_trainer_csrf']='test-csrf'
    import subject_references
    monkeypatch.setattr(subject_references,'api_key',lambda *a:'fake-test-key')
    monkeypatch.setattr(trainer_invoices,'read_invoice',lambda *a:deepcopy(extraction()))
    return app,client,connect,tmp_path


def upload(client,data=None,name='facture.pdf',month='2026-10',basis='ht',token='test-csrf'):
    return client.post('/admin/formateurs/t1/factures',data={'month':month,'basis':basis,'file':(BytesIO(data if data is not None else pdf()),name)},
                       headers={'X-CSRF-Token':token},content_type='multipart/form-data')


def analyze(client,identity):
    return client.post('/admin/formateurs/t1/factures/'+identity+'/analyser',headers={'X-CSRF-Token':'test-csrf'})


def listing(client):
    return client.get('/admin/formateurs/t1/factures?month=2026-10').get_json()


def test_routes_registered_from_existing_admin_entry_point(setup):
    app,client,connect,tmp=setup
    assert 'admin_trainer_invoices' in app.view_functions
    assert client.get('/admin/formateurs/t1/factures?month=2026-10').status_code==200


def test_admin_and_csrf_are_required_for_upload_and_read(setup):
    app,client,connect,tmp=setup
    assert upload(client,token='wrong').status_code==400
    with client.session_transaction() as s:s.clear()
    assert client.get('/admin/formateurs/t1/factures?month=2026-10').status_code==403
    assert upload(client).status_code==403
    assert not (tmp/'invoices').exists()


def test_upload_is_durable_private_and_duplicate_safe(setup):
    app,client,connect,tmp=setup
    content=pdf();first=upload(client,content).get_json();second=upload(client,content).get_json()
    assert first['id']==second['id'] and second['duplicate']
    assert len(list((tmp/'invoices').iterdir()))==1
    original=client.get('/admin/formateurs/t1/factures/'+first['id']+'/original')
    assert original.data==content
    assert 'attachment' in original.headers['Content-Disposition']
    assert 'no-store' in original.headers['Cache-Control']
    assert client.get('/admin/formateurs/t2/factures/'+first['id']+'/original').status_code==404
    assert upload(client,content,month='2026-11').get_json()['month']=='2026-10'


@pytest.mark.parametrize('content,name',[(b'<script>alert(1)</script>','fake.pdf'),(b'x','test.html'),(b'','empty.pdf')])
def test_bad_files_do_not_create_invoice_records(setup,content,name):
    app,client,connect,tmp=setup
    assert upload(client,content,name).status_code in (400,413)
    assert listing(client)['invoices']==[]


def test_encrypted_and_overlong_pdfs_are_rejected(setup):
    app,client,connect,tmp=setup
    assert upload(client,pdf(password='secret')).status_code==400
    assert upload(client,pdf(pages=21)).status_code==400


def test_explicit_month_and_rate_basis_required(setup):
    app,client,connect,tmp=setup
    assert upload(client,month='2026-13').status_code==400
    assert upload(client,basis='').status_code==400


def test_analysis_and_history_then_live_planning_reconciliation(setup):
    app,client,connect,tmp=setup
    identity=upload(client).get_json()['id']
    assert analyze(client,identity).status_code==200
    data=listing(client);record=data['invoices'][0]
    assert record['report']['teaching_minutes']==120 and not record['planning_changed']
    with connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainer_invoice_history').fetchone()[0]==1
        conn.execute("UPDATE trainer_hourly_rates SET rate_cents=5000 WHERE trainer_id='t1'")
    record=listing(client)['invoices'][0]
    assert record['planning_changed']
    assert any(i['code']=='planned_amount' for i in record['report']['issues'])
    assert analyze(client,identity).status_code==200
    with connect() as conn:assert conn.execute('SELECT COUNT(*) FROM trainer_invoice_history').fetchone()[0]==2


def test_provider_failure_preserves_original_and_can_retry(setup,monkeypatch):
    app,client,connect,tmp=setup
    identity=upload(client).get_json()['id']
    def fail(*args):raise InvoiceError('Service IA indisponible.',502)
    monkeypatch.setattr(trainer_invoices,'read_invoice',fail)
    assert analyze(client,identity).status_code==502
    assert listing(client)['invoices'][0]['status']=='failed'
    assert len(list((tmp/'invoices').iterdir()))==1
    monkeypatch.setattr(trainer_invoices,'read_invoice',lambda *a:deepcopy(extraction()))
    assert analyze(client,identity).status_code==200


def test_missing_key_does_not_start_processing(setup,monkeypatch):
    app,client,connect,tmp=setup
    import subject_references
    from planning import PlanningError
    def missing(*args):raise PlanningError('Missing secret',status=503)
    monkeypatch.setattr(subject_references,'api_key',missing)
    identity=upload(client).get_json()['id']
    assert analyze(client,identity).status_code==503
    assert listing(client)['invoices'][0]['status']=='uploaded'


def test_one_analysis_per_trainer_and_interruption_recovery(setup):
    app,client,connect,tmp=setup
    identity=upload(client).get_json()['id']
    with connect() as conn:
        conn.execute("UPDATE trainer_invoices SET status='processing',started_at=?,run_token='old' WHERE id=?",(time.time(),identity))
    assert analyze(client,identity).status_code==409
    with connect() as conn:conn.execute('UPDATE trainer_invoices SET started_at=? WHERE id=?',(time.time()-301,identity))
    assert listing(client)['invoices'][0]['status']=='failed'
    assert analyze(client,identity).status_code==200


def test_archive_excludes_billing_but_retains_and_restores_original(setup):
    app,client,connect,tmp=setup
    identity=upload(client).get_json()['id'];analyze(client,identity)
    url='/admin/formateurs/t1/factures/'+identity+'/archiver'
    assert client.post(url,json={'archived':True},headers={'X-CSRF-Token':'test-csrf'}).status_code==200
    assert listing(client)['aggregate']['analyzed_count']==0
    assert client.get('/admin/formateurs/t1/factures/'+identity+'/original').status_code==200
    assert client.post(url,json={'archived':False},headers={'X-CSRF-Token':'test-csrf'}).status_code==200
    assert listing(client)['aggregate']['analyzed_count']==1


def test_request_limit_and_invalid_provider_output_preserve_state(setup,monkeypatch):
    app,client,connect,tmp=setup
    identity=upload(client).get_json()['id']
    with connect() as conn:conn.executemany('INSERT INTO trainer_invoice_usage VALUES(?,?)',[('t1',time.time())]*30)
    assert analyze(client,identity).status_code==429
    assert listing(client)['invoices'][0]['status']=='uploaded'


def test_real_provider_payload_has_no_tools_or_student_records(monkeypatch):
    recorded={}
    class Response:
        status_code=200
        def json(self):return dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(extraction()))])])
    def post(url,**kwargs):recorded.update(url=url,**kwargs);return Response()
    monkeypatch.setattr(trainer_invoices.requests,'post',post)
    result=read_invoice('test-key','gpt-4.1',pdf(),'application/pdf',context())
    assert result['number']=='F-001'
    assert recorded['url']=='https://api.openai.com/v1/responses'
    payload=recorded['json']
    assert payload['store'] is False and 'tools' not in payload
    assert payload['text']['format']['strict'] is True
    text=payload['input'][0]['content'][0]['text']
    assert 'rollcall' not in text and 'journal' not in text
    assert payload['input'][0]['content'][1]['type']=='input_file'
    assert recorded['allow_redirects'] is False
