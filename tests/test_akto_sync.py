from datetime import datetime
import json

from flask import Flask, session
import sqlite3
from pathlib import Path
from wedof_contracts import register_wedof_contracts
from akto_sync import PARIS, register_akto, run_due, get_records
from wedof_daily_sync import initialize, tick


def test_daily_manual_and_mos_isolation(tmp_path):
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.testing=True
    app.secret_key='long-test-secret-for-akto-only'
    def db():
        conn=sqlite3.connect(tmp_path/'test.db')
        conn.row_factory=sqlite3.Row
        return conn
    with db() as conn:
        conn.executescript("CREATE TABLE candidats(id TEXT,prenom TEXT,nom TEXT,date_naissance TEXT); INSERT INTO candidats VALUES('alice','Alice','Exemple',''),('bob','Bob','Test','');")
    register_wedof_contracts(app,db,lambda:session.get('admin_ok'))
    client=app.test_client()
    headers={'X-CSRF-Token':'test-wedof'}

    with db() as conn:
        conn.execute("ALTER TABLE candidats ADD COLUMN bts TEXT DEFAULT 'MOS'")
        conn.execute("ALTER TABLE candidats ADD COLUMN statut TEXT DEFAULT 'confirmee'")
        conn.execute("UPDATE candidats SET bts='MCO' WHERE id='bob'")
    app.add_url_rule('/admin/parametres', endpoint='admin_settings',view_func=lambda:'')
    register_akto(app,db,lambda:session.get('admin_ok'),tmp_path)
    calls=[]
    def read(email,password,students,save):
        calls.append([p['id'] for p in students])
        save(students[0],[{'reference':'TEST123','status':'Accordé','contract_start':'2025-06-01'}],'')
        return 0
    def run(hour):
        run_due(app,db,tmp_path,datetime(2026,11,4,hour,tzinfo=PARIS),read)
    with client.session_transaction() as s:
        s['_planning_csrf']='settings-test'
        s['_wedof_csrf']='test-wedof'
        s['admin_ok']=True
    def action(a,**fields):
        return client.post('/admin/parametres/akto',data={'csrf_token':'settings-test','action':a,**fields})
    assert action('connect',email='demo@example.test',password='test-pwd').status_code==303
    run(3);run(4);run(5);run(6)
    assert calls==[['alice'],['alice']]
    action('sync');run(12);run(13)
    assert calls==[['alice']]*3
    assert client.post('/admin/candidat/alice/contrats-apprentissage/detecter',headers=headers,json={}).status_code==409
    initialize(db,datetime(2026,11,4,7,tzinfo=PARIS))
    tick(db,lambda *_:{},lambda _:True,now=datetime(2026,11,4,8,tzinfo=PARIS))
    with db() as conn:
        assert [r[0] for r in conn.execute('SELECT candidate_id FROM student_wedof_daily_items')]==['bob']
        assert get_records(conn,'alice')[0][0]['reference']=='TEST123'
        assert b'test-pwd' not in conn.execute('SELECT credential FROM akto_connection').fetchone()[0]
    action('disconnect');run(14)
    assert len(calls)==3


def test_cutoff_uses_contract_date_before_reading_annexes(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock
    from akto_portal import BeforeCutoff, notice
    import pytest
    for start,eligible in [('31/05/2025',False),('01/06/2025',True)]:
        page=Mock()
        page.extract_text.return_value=f"Numéro de dossier : AB123\nBénéficiaire : ALICE TEST né(e) le 05/03/2005\nDates de contrat : Du {start} au 01/07/2026\nDates de formation : Du 01/01/2025 au 01/07/2026"
        page.extract_tables.return_value=[]
        monkeypatch.setattr('akto_portal.pdfplumber.open',lambda _:nullcontext(SimpleNamespace(pages=[page])))
        record={'reference':'AB123'}
        if eligible:
            notice('mock',record,{'prenom':'Alice','nom':'Test'})
            assert record['contract_start']=='2025-06-01'
        else:
            with pytest.raises(BeforeCutoff):
                notice('mock',record,{'prenom':'Alice','nom':'Test'})
            page.extract_tables.assert_not_called()
