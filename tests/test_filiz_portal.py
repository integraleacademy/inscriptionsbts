from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest

from flask import Flask, session
from opco_sync import PARIS, same_contract
from filiz_portal import due_row, iso
from opco_sync import register_opcos, tick
from training_programs import BTS_LABELS
from filiz_contracts import billing, register_filiz_contracts


def test_period_and_invoice_amounts():
    summary = 'Échéance N°1\n2 758,80 €\nPayée\nDu 06 juil. 2026 au 06 janv. 2027\nPayé OPCO\n2 758,80 €'
    detail = 'Facture initiale n°FAC-1\n2 758,80 €\nFacture complémentaire n°FAC-2\n500,00 €'
    row, invoices = due_row(summary,detail)
    assert (row['dateDebut'],row['dateFin'],row['montantRegle']) == ('2026-07-06','2027-01-06',2758.80)
    assert [b['amount'] for b in invoices]==[2758.8,500]
    future,_ = due_row('Échéance N°2\n100,20 €\nÀ venir\nÀ partir du 01 sept. 2027','')
    assert future['montantRegle'] is None and future['dateDebut']=='2027-09-01'
    assert iso('30 févr. 2026')==''
    card = billing({'source':'filiz','engagement':2859,'filiz_paid':2758.8,'filiz_pending':0,'schedules':[row,future]})
    assert card['remaining']==100.2 and card['next_due']['status_code']=='upcoming'
    assert not same_contract({'financer':'A','deca_number':'ABC'},{'financer':'B','deca_number':'ABC'})


def test_filiz_account_all_bts_views_and_cache(tmp_path,monkeypatch):
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.secret_key='filiz-testing-secret-long-enough'
    app.testing=True
    def db():
        conn=sqlite3.connect(tmp_path/'test.sqlite')
        conn.row_factory=sqlite3.Row
        return conn
    with closing(db()) as conn:
        conn.execute('CREATE TABLE candidats(id TEXT,nom TEXT,prenom TEXT,date_naissance TEXT,bts TEXT)')
        conn.executemany('INSERT INTO candidats VALUES(?,?,?,?,?)',[(k,k,'Léa','2000-01-02',k) for k in [*BTS_LABELS,'TP TEST']])
        conn.commit()
    auth=lambda:session.get('admin_ok')
    app.add_url_rule('/admin/parametres',endpoint='admin_settings',view_func=lambda:'')
    register_filiz_contracts(app,db,auth)
    register_opcos(app,db,auth,tmp_path)
    client=app.test_client()
    with client.session_transaction() as s:
        s.update(admin_ok=True,_planning_csrf='csrf')
    assert client.post('/admin/parametres/opco/filiz',data={'action':'connect','csrf_token':'csrf','email':'office@example.test','password':'fake-only'}).status_code==303
    calls=[]
    def read(config,people,stored,save,completed,save_batch):
        assert {p['bts'] for p in people}==set(BTS_LABELS)
        calls.append(stored)
        save({'cookies':[],'origins':[]})
        item={'source':'filiz','filiz_id':'abc','working_contract_id':'filiz-abc','financer':'opcoCfaEp',
              'deca_number':'D1','external_number':'E1','state':'accepted','state_label':'Engagé',
              'apprentice_last_name':'PI','apprentice_first_name':'Léa','apprentice_birth_date':'2000-01-02',
              'contract_start':'2025-06-01','checked_at':'2026-11-03T08:00:00+00:00','engagement':100,
              'filiz_paid':80,'filiz_pending':0,'invoices':[{'reference':'F1','amount':80,'state':'','paid_on':''}],
              'schedules':[{'numero':'1','dateDebut':'2025-06-01','montantTotal':100,'montantRegle':80,
                            'filiz_label':'Partiellement payée','filiz_code':'unknown'}]}
        assert not completed
        save_batch(['abc'], {'abc':('PI',item)}, set(), 1, 1)
        return {'abc'}
    monkeypatch.setattr('opco_sync.read_filiz',read)
    for hour in [4,5,6]:
        tick(app,db,tmp_path,datetime(2026,11,4,hour,tzinfo=PARIS))
    assert calls==[None,{'cookies':[],'origins':[]}]
    with closing(db()) as conn:
        assert b'cookies' not in conn.execute('SELECT payload FROM filiz_session').fetchone()[0]
    html=client.get('/admin/candidat/PI/contrats-apprentissage').json['html']
    assert 'FILIZ · OPCO EP' in html and 'F1' in html and 'filiz.io/school/folder/abc' in html
    assert 'ne propose pas le détail' not in html and 'FILIZ · OPCO EP' not in client.get('/admin/candidat/CI/contrats-apprentissage').json['html']
    # A hard process stop between batches leaves committed contracts visible.
    with closing(db()) as conn:
        conn.execute("UPDATE opco_accounts SET requested=1")
        conn.commit()
    def interrupted(config, people, stored, save, completed, save_batch):
        assert not completed
        save_batch(['empty'], {}, set(), 1, 2)
        raise SystemExit
    monkeypatch.setattr('opco_sync.read_filiz', interrupted)
    with pytest.raises(SystemExit):
        tick(app, db, tmp_path, datetime(2026,11,4,7,tzinfo=PARIS))
    def resumed(config, people, stored, save, completed, save_batch):
        assert completed == {'empty'}
        save_batch(['abc'], {}, {'abc'}, 2, 2)
        return {'empty','abc'}
    monkeypatch.setattr('opco_sync.read_filiz', resumed)
    tick(app, db, tmp_path, datetime(2026,11,4,8,tzinfo=PARIS))
    with closing(db()) as conn:
        assert conn.execute("SELECT state FROM opco_accounts").fetchone()[0] == 'partial'
        previous = json.loads(conn.execute("SELECT payload FROM opco_contracts WHERE ref='abc'").fetchone()[0])
        assert previous['invoices'][0]['reference'] == 'F1' and previous['read_warning']
    from playwright.sync_api import TimeoutError as BrowserTimeout
    attempts = []
    def unavailable(config, people, stored, save, completed, save_batch):
        if not attempts:
            save_batch(['empty'], {}, set(), 1, 2)
        attempts.append(completed)
        raise BrowserTimeout('test')
    with closing(db()) as conn:
        conn.execute("UPDATE opco_accounts SET requested=1")
        conn.commit()
    monkeypatch.setattr('opco_sync.read_filiz', unavailable)
    for _ in range(5):
        tick(app, db, tmp_path, datetime(2026,11,4,9,tzinfo=PARIS))
    assert attempts == [set(), {'empty'}, {'empty'}]
    # After the school account is verified, a manual sync continues the interrupted run.
    from opco_sync import account_status
    with closing(db()) as conn:
        conn.execute("UPDATE opco_accounts SET message='Vérification FILIZ demandée.'")
        conn.commit()
        assert 'Dossiers examinés : 1.' in account_status(conn)['message']
    client.post('/admin/parametres/opco/filiz', data={'action':'sync','csrf_token':'csrf'})
    def after_login(config, people, stored, save, completed, save_batch):
        assert completed == {'empty'}
        return completed
    monkeypatch.setattr('opco_sync.read_filiz', after_login)
    tick(app, db, tmp_path, datetime(2026,11,4,10,tzinfo=PARIS))
    with closing(db()) as conn:
        assert account_status(conn)['state'] == 'ok'
    client.post('/admin/parametres/opco/filiz',data={'action':'disconnect','csrf_token':'csrf'})
    with closing(db()) as conn:
        assert conn.execute('SELECT count(*) FROM filiz_session').fetchone()[0]==0


def test_filiz_rupture_precedes_older_wedof_status():
    from datetime import date
    from candidate_statuses import annotate_candidate_statuses
    from filiz_portal import STATUS
    from opco_sync import schema
    from akto_sync import schema as akto_schema
    conn=sqlite3.connect(':memory:')
    conn.row_factory=sqlite3.Row
    schema(conn)
    akto_schema(conn)
    conn.execute("CREATE TABLE student_wedof_contracts(candidate_id TEXT,payload TEXT)")
    conn.execute("UPDATE opco_accounts SET credential=x'01' WHERE provider='filiz'")
    item={'financer':'opcoCfaMobilites','deca_number':'D42','source':'filiz','employer_name':'Test',
          'apprentice_last_name':'Test','apprentice_first_name':'Alice','apprentice_birth_date':'2001-01-01',
          'contract_start':'2025-09-01','contract_end':'2027-08-31','state':STATUS['rupture validee']}
    conn.execute("INSERT INTO opco_contracts VALUES('filiz','demo','student',?)",(json.dumps(item),))
    conn.execute("INSERT INTO student_wedof_contracts VALUES('student',?)",(json.dumps(dict(item,state='accepted')),))
    student=dict(id='student',nom='Test',prenom='Alice',date_naissance='2001-01-01',bts='CI',statut='confirmee')
    annotate_candidate_statuses(conn,[student],date(2026,11,3))
    assert student['display_status']=='confirmee'
    conn.close()


def test_catalogue_and_batches_release_their_browsers(monkeypatch):
    from contextlib import contextmanager
    import filiz_portal as portal
    active, launches, groups = [], [], []
    @contextmanager
    def browser(config, stored):
        assert not active
        active.append(True)
        launches.append(stored)
        class Context:
            def storage_state(self):
                return len(launches)
        try:
            yield object(), Context()
        finally:
            active.pop()
    card = {'text': 'Léa Test\nTitre\nApprentissage\nEngagé'}
    cards = {str(n):card for n in range(9)}
    cards['old'] = dict(text=card['text']+'\n01 mai 2025 - 01 mai 2027')
    monkeypatch.setattr(portal, 'school_browser', browser)
    monkeypatch.setattr(portal, 'catalogue', lambda page:cards)
    monkeypatch.setattr(portal, 'read_item', lambda page, ref, card, people: ('1',{'source':'filiz'}))
    def save(group, results, failed, done, total):
        assert not active and not failed and set(group)==results.keys() and total==9
        groups.append((len(group),done))
    refs = portal.read_filiz({}, [{'prenom':'Léa','nom':'Test'}], None, lambda data:None, {'1'}, save)
    assert refs == {str(n) for n in range(9)}
    assert groups == [(3,4),(3,7),(2,9)] and launches == [None,1,2,3]


def test_confirmed_waiting_schedule_preserves_previous_finance():
    from opco_sync import schema, store_contract
    conn = sqlite3.connect(':memory:')
    schema(conn)
    store_contract(conn, 'ref', 'c', {'schedules':[{'numero':1}], 'filiz_paid':42, 'raw_checked_at':'old'})
    record = {'schedule_notice':'En cours de récupération', 'raw_checked_at':'new'}
    store_contract(conn, 'ref', 'c', record)
    assert record['raw_stale'] and record['raw_checked_at'] == 'old' and record['filiz_paid'] == 42
    conn.close()
