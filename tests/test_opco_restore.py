import json
import sqlite3

import pytest

from flask import Flask
from test_admissions_2027 import client

from akto_sync import schema as akto_schema
from opco_contracts import records_by_student, register_opco_contracts
from opco_sync import register_opcos, schema


def test_portal_and_filiz_archives_never_populate_live_contracts(tmp_path):
    def db():
        c = sqlite3.connect(tmp_path/'opco.sqlite')
        c.row_factory = sqlite3.Row
        return c
    with db() as c:
        schema(c)
        akto_schema(c)
        c.executescript("""CREATE TABLE candidats(id TEXT,nom TEXT,prenom TEXT,bts TEXT,date_naissance TEXT);
            INSERT INTO candidats VALUES('a','Exemple','Ève','PI','2000-01-02');
            INSERT INTO opco_accounts(provider,credential,requested) VALUES('filiz','retired',1);
            CREATE TABLE filiz_session(id INTEGER,payload BLOB);
            INSERT INTO filiz_session VALUES(1,'obsolete');
            UPDATE akto_connection SET credential='kept';
            UPDATE opco_accounts SET credential='kept' WHERE provider='ep';""")
        record = dict(source='filiz',financer='opcoCfaEp',filiz_id='ref',working_contract_id='filiz-ref',contract_start='2025-06-01',
                      apprentice_first_name='Ève',apprentice_last_name='Exemple',apprentice_birth_date='2000-01-02',
                      state='accepted',state_label='Engagé',schedules=[])
        c.execute("INSERT INTO opco_contracts VALUES('filiz','ref','a',?)", (json.dumps(record),))
    from pathlib import Path
    app = Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.testing = True
    register_opcos(app,db,lambda:True,tmp_path)
    register_opco_contracts(app,db,lambda:True)
    with db() as c:
        assert {r[0] for r in c.execute('SELECT provider FROM opco_accounts')} == {'ep','opcommerce','mobilites'}
        assert c.execute('SELECT count(*) FROM filiz_session').fetchone()[0] == 0
        assert c.execute('SELECT credential FROM akto_connection').fetchone()[0] == 'kept'
        assert c.execute("SELECT credential FROM opco_accounts WHERE provider='ep'").fetchone()[0] == 'kept'
        p = dict(c.execute('SELECT * FROM candidats').fetchone())
        assert not records_by_student(c,[p])
        assert records_by_student(c,[p],archives=True)['a'][0]['filiz_id']=='ref'
    client = app.test_client()
    assert client.post('/admin/parametres/opco/filiz',data={'action':'sync'}).status_code == 404
    result = client.get('/admin/candidat/a/contrats-apprentissage').get_json()
    assert not result['has_contracts'] and 'Archive FILIZ' not in result['html']
    assert 'app.filiz.io' not in result['html']
    # A portal agreement is not evidence of a Convergence API contract.
    with db() as c:
        c.execute('UPDATE akto_connection SET credential=NULL')
        akto = dict(reference='AKTO123', status='Accordé', employer='Entreprise test', contract_start='2025-06-01',
                    schedules=[dict(numero=1,montantTotal=120,dateOuverture='2025-07-01')])
        c.execute("INSERT INTO akto_students VALUES('a',?,'','test')", (json.dumps([akto]),))
    result = client.get('/admin/candidat/a/contrats-apprentissage').get_json()
    assert not result['has_contracts'] and 'Données AKTO' not in result['html'] and '120,00' not in result['html']
    assert 'Archive FILIZ' not in result['html'] and 'app.filiz.io' not in result['html']


def test_akto_training_filter_all_bts():
    from akto_portal import course_matches
    from training_programs import BTS_LABELS
    for bts, title in BTS_LABELS.items():
        assert course_matches([title],bts)
        assert course_matches(['Formation BTS '+bts],bts)
    assert not course_matches(['BTS MCO'],'MOS')
    assert not course_matches(['Commerce international'],'TP ASSISTANT RH')


def test_settings_show_each_provider_and_no_filiz_login(client):
    from test_admissions_2027 import application, auth
    with application.db() as conn:
        akto_schema(conn)
        schema(conn)
    auth(client)
    page = client.get('/admin/parametres')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for key in ('akto', 'opco-opcommerce', 'opco-mobilites', 'opco-ep'):
        assert f'id="{key}"' in html
    assert 'id="opco-filiz"' not in html and 'action="/admin/parametres/opco/filiz"' not in html


@pytest.mark.parametrize('changes', [dict(source='filiz'), dict(source='portal'), dict(source=''),
    dict(environment='recette'), dict(financer='opcoCfaAkto'), dict(apprentice_birth_date='2001-01-02')])
def test_contract_cache_requires_convergence_provenance_and_identity(changes):
    from opco_contracts import directory_contracts
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    schema(conn)
    person=dict(id='a',nom='Exemple',prenom='Eve',date_naissance='2000-01-02',bts='MOS')
    record=dict(source='convergence',financer='opcoCfaEp',contract_start='2026-09-01',
                apprentice_first_name='Eve',apprentice_last_name='Exemple',apprentice_birth_date='2000-01-02',
                state='accepted',state_label='Engagé',internal_number='42')
    conn.execute("INSERT INTO opco_contracts VALUES('ep','42','a',?)",(json.dumps(record),))
    assert records_by_student(conn,[person])['a'][0]['internal_number']=='42'
    conn.execute('UPDATE opco_contracts SET payload=?',(json.dumps({**record,**changes}),))
    assert records_by_student(conn,[person])=={}
    directory_contracts(None,conn,[person]);assert person['contract']!='yes'
    conn.close()
