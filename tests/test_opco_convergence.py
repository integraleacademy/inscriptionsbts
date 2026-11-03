import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask, session

from akto_sync import PARIS, register_akto
from opco_convergence import PROVIDERS, ReadError, endpoint, paged, read_contracts
from opco_sync import register_opcos, student_records, tick
from wedof_contracts import register_wedof_contracts


def raw(ref, start='2025-06-01', birth='2005-05-01', last='Éxemple'):
    return {'cerfa': {'numeroInterne': ref, 'numeroExterne':'E' + ref, 'etat': 'ENGAGE',
                      'apprenti': {'nom':last, 'prenom':'Ève', 'dateNaissance':birth,'nir':'forbidden-nir'},
                      'employeur':{'denomination':'Employeur'},
                      'contrat':{'dateDebutContrat':start, 'dateFinContrat':'2027-06-01'}},
            'engagement':1000, 'echeances':[{'numero':1,'montantTotal':1000,'montantRegle':600,'dateOuverture':'2025-06-01'}]}


class FixtureAPI:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def read(self, path, params):
        self.calls.append((path, params))
        if path == '/v2/dossiers/etats':
            refs = [{'numeroInterne':k} for k in self.docs]
            return {'total':len(refs),'page':1,'count':len(refs),'EtatDossierResult':refs}
        if path == '/v1/dossiers/liste':
            return {'dossiers':[self.docs[k] for k in params['numerosInternes'].split(',')]}
        assert path == '/v2/factures/etats'
        invoice = {'numeroInterneFacture':'42', 'referenceFactureCFA':'F1','montantFacture':900,'etatFacture':'REGLE',
                   'dateReglement':'2026-03-01','organismeFormation':{'IBAN':'forbidden-iban'},
                   'dossiers':[{'numeroInterneDossier':'1','montant':600},{'numeroInterneDossier':'2','montant':300}]}
        return {'page':1,'total':1,'count':1,'factures':[invoice]}


@pytest.mark.parametrize('provider', PROVIDERS)
def test_read_real_schema(provider):
    people = [{'id':'a','nom':'Exemple','prenom':'Eve','date_naissance':'2005-05-01'}]
    api = FixtureAPI({'1':raw('1'), '2':raw('2','2025-05-31'), '3':raw('3',birth='2002-02-02'),'4':raw('4',last='Autre')})
    records, failed, _ = read_contracts(provider, {}, people, '', {}, lambda *_:api)
    assert set(records) == {'1'} and failed == {'3'}
    cid,item = records['1']
    assert cid == 'a' and item['schedules'][0]['montantRegle'] == 600
    assert 'montantEnCoursInstruction' not in item['schedules'][0]
    assert 'forbidden' not in json.dumps(item)
    assert api.calls[0][1]['dateModification'] == '2025-06-01'
    if provider != 'ep':
        assert item['invoices'][0]['amount'] == 600
    else:
        assert not any('factures' in p for p,_ in api.calls)
    records, failed, _ = read_contracts(provider, {}, people + [dict(people[0], id='b')], '', {}, lambda *_:api)
    assert not records and '1' in failed


def test_pages_and_credential_destinations():
    def read(path, p):
        n = p['numeroPage']
        return {'page':n,'count':1,'total':2,'etatDossierResult':[{'ref':n}]}
    assert [x['ref'] for x in paged(read,'/v2/dossiers/etats','EtatDossierResult',{})] == [1,2]
    with pytest.raises(ReadError):
        list(paged(lambda *args:{'total':7,'page':1,'count':0,'factures':[]},'/v2/factures/etats','factures',{}))
    for url in ['http://api.opcoep.fr','https://opcoep.fr.evil.example','https://opcoep.fr@evil.example','https://127.0.0.1','https://api.opcoep.fr:444']:
        with pytest.raises(ReadError):
            endpoint('ep','api',url)


def test_only_filiz_survives_upgrade_and_obsolete_routes_are_closed(tmp_path):
    from filiz_contracts import register_filiz_contracts
    from opco_sync import schema
    app = Flask(__name__)
    app.testing = True
    app.secret_key = 'a-long-test-secret-for-upgrade'
    def db():
        conn = sqlite3.connect(tmp_path/'test.sqlite')
        conn.row_factory = sqlite3.Row
        return conn
    with db() as conn:
        schema(conn)
        conn.executescript("""INSERT INTO opco_accounts(provider,credential) VALUES('ep','old-key');
            CREATE TABLE student_wedof_settings(name TEXT,value TEXT);
            INSERT INTO student_wedof_settings VALUES('api_key','old-key');
            CREATE TABLE akto_connection(id INTEGER,credential BLOB,requested INTEGER,state TEXT);
            INSERT INTO akto_connection VALUES(1,'old-key',1,'pending');
            UPDATE opco_accounts SET credential=x'31',succeeded='hier' WHERE provider='filiz';
            INSERT INTO filiz_session VALUES(1,x'32');""")
    register_filiz_contracts(app,db,lambda: True)
    register_opcos(app,db,lambda:True,tmp_path)
    with db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT provider,credential,succeeded FROM opco_accounts')]==[('filiz',b'1','hier')]
        assert conn.execute('SELECT payload FROM filiz_session').fetchone()[0]==b'2'
        assert conn.execute("SELECT count(*) FROM student_wedof_settings WHERE name='api_key'").fetchone()[0]==0
        assert tuple(conn.execute('SELECT credential,requested FROM akto_connection').fetchone())==(None,0)
    client=app.test_client()
    for path in ['/admin/parametres/akto','/admin/api/wedof/settings','/admin/parametres/wedof/synchroniser',
                 '/admin/candidat/demo/contrats-apprentissage/detecter','/admin/parametres/opco/opcommerce',
                 '/admin/parametres/opco/mobilites','/admin/parametres/opco/ep']:
        assert client.post(path).status_code==404
    assert client.post('/admin/parametres/opco/filiz').status_code==403


def test_read_only_api_headers_and_token_destination(monkeypatch):
    from opco_convergence import Client
    calls = []
    def request(method, url, **kw):
        calls.append((method,url,kw))
        return {'access_token':'test-token','expires_in':3600} if method == 'POST' else {}
    client = Client('ep', {'api':'https://api.opcoep.fr/convergence','token':'https://auth.opcoep.fr/token',
                           'key':'cfa-key','client_id':'software','client_secret':'private','scope':'service/.default'})
    monkeypatch.setattr(client,'json_request',request)
    client.read('/v2/dossiers/etats',{'numeroPage':1})
    client.read('/v1/dossiers/liste',{'numerosInternes':'1,2'})
    assert [method for method,_,_ in calls] == ['POST','GET','GET']
    assert calls[0][1] == 'https://auth.opcoep.fr/token' and 'key' not in calls[0][2]['data']
    assert all(c[2]['headers']['X-Api-Key']=='cfa-key' and c[2]['headers']['VERSION'] for c in calls[1:])
    assert all('private' not in str(c[2]) for c in calls[1:])
