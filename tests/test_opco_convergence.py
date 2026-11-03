import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask, session

from akto_sync import PARIS, register_akto
from opco_convergence import PROVIDERS, ReadError, endpoint, paged, read_contracts
from opco_sync import register_opcos, student_records, tick
from opco_contracts import register_opco_contracts


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


def test_monitor_manual_daily_cache_and_contract_view(tmp_path):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.testing = True
    app.secret_key = 'a-long-test-secret-not-a-real-account'
    def db():
        conn = sqlite3.connect(tmp_path/'test.sqlite')
        conn.row_factory = sqlite3.Row
        return conn
    with db() as conn:
        conn.executescript("""CREATE TABLE candidats(id TEXT, nom TEXT, prenom TEXT, date_naissance TEXT, bts TEXT);
          INSERT INTO candidats VALUES('A','Exemple','Eve','2005-05-01','MOS'),('B','Autre','Eve','2005-05-01','MCO');""")
    auth = lambda:session.get('admin_ok')
    app.add_url_rule('/admin/parametres', endpoint='admin_settings', view_func=lambda:'')
    register_opco_contracts(app,db,auth)
    register_akto(app,db,auth,tmp_path)
    register_opcos(app,db,auth,tmp_path)
    client = app.test_client()
    url = '/admin/parametres/opco/opcommerce'
    assert client.post(url, data={'action':'sync'}).status_code == 403
    with client.session_transaction() as s:
        s.update(admin_ok=True,_planning_csrf='csrf')
    def action(name, **fields):
        return client.post(url, data={'action':name,'csrf_token':'csrf',**fields})
    assert action('connect',key='secret-cfa',client_id='test',client_secret='secret-client',api='https://api.lopcommerce.com',token='https://auth.lopcommerce.com/token').status_code == 303
    calls = []
    api = FixtureAPI({'1':raw('1')})
    def reader(provider,config,people,since,prior):
        calls.append((since,[p['id'] for p in people]))
        if len(calls)==3:
            raise ReadError('Portail indisponible.')
        return read_contracts(provider,config,people,since,prior,lambda *_:api)
    def run(hour):
        tick(app,db,tmp_path,'opcommerce',datetime(2026,11,4,hour,tzinfo=PARIS),reader)
    run(3); run(4); run(5); run(8)
    assert calls == [('', ['A','B']), ('2026-11-03',['A','B'])]
    action('sync'); run(11)
    with db() as conn:
        assert conn.execute("SELECT state FROM opco_accounts WHERE provider='opcommerce'").fetchone()[0] == 'error'
        assert b'secret-cfa' not in conn.execute("SELECT credential FROM opco_accounts WHERE provider='opcommerce'").fetchone()[0]
        item = student_records(conn,dict(conn.execute("SELECT * FROM candidats WHERE id='A'").fetchone()))[0]
        assert item['read_warning']
    html = client.get('/admin/candidat/A/contrats-apprentissage').json['html']
    assert 'Données L’Opcommerce' in html and 'data-wc-panel="schedule"' in html and 'F1' in html
    assert 'Données WEDOF' not in html and 'data-wc-unlink' not in html
    with db() as conn:
        conn.execute("UPDATE candidats SET date_naissance='2000-01-01' WHERE id='A'")
    assert 'Données L’Opcommerce' not in client.get('/admin/candidat/A/contrats-apprentissage').json['html']
    action('disconnect')
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM opco_contracts').fetchone()[0] == 0


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
