"""Dossier isolation, real PDF forms, concurrency and Convergence failure handling."""
from contextlib import closing
from copy import deepcopy
from io import BytesIO
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

from flask import Flask, session
from pypdf import PdfReader
import pytest

from apprenticeship import register_apprenticeship, DETAILS
from apprenticeship_data import validate
from apprenticeship_documents import cerfa_pdf, cerfa_values
from apprenticeship_convergence import TransferError
from akto_sync import schema as akto_schema, secret
from opco_sync import schema as opco_schema


def complete_payload():
    address={'adresse1':'12 rue des Écoles','codePostal':'83480','commune':'Puget-sur-Argens','codePays':'99100'}
    return {'cerfa':{
      'versionCERFA':'10103*14','CERFASignatureProbante':True,'CERFAAttestationExactitudeInformations':True,
      'CERFAAttestationConformiteContratApprenti':True,'CERFAAttestationSigneCFA':True,
      'CERFAAttestationSigneEmployeurApprenti':True,'CERFAEngagementDispositionPieces':True,
      'apprenti':{'nom':'EXEMPLE','nomUsage':'EXEMPLE','prenom':'Camille','sexe':'F','nationalite':1,
        'dateNaissance':'2004-01-02','departementNaissance':'083','communeNaissance':'Fréjus','nir':'2040183123456',
        'regimeSocial':1,'handicap':False,'inscriptionSportifDeHautNiveau':False,'situationAvantContrat':3,
        'diplome':42,'diplomePrepare':42,'derniereClasse':1,'intituleDiplomePrepare':'Baccalauréat général',
        'telephone':'0600000000','courriel':'camille@example.test','adresse':address},
      'employeur':{'denomination':'ENTREPRISE EXEMPLE','siret':'12345678900012','naf':'8010Z','nombreDeSalaries':12,
        'codeIdcc':'1351','codeIdccConventionAppliquee':'1351','telephone':'0400000000','courriel':'entreprise@example.test',
        'adresse':address,'typeEmployeur':12,'employeurSpecifique':0,'caisseComplementaire':'AGIRC-ARRCO',
        'attestationEligibilite':True,'attestationPieces':True},
      'maitre1':{'nom':'MARTIN','prenom':'Alex','dateNaissance':'1980-03-04','courriel':'maitre@example.test'},
      'formation':{'rncp':'RNCP41000','codeDiplome':'32034401','typeDiplome':54,'intituleQualification':'BTS Management opérationnel de la sécurité',
        'dateDebutFormation':'2026-09-01','dateFinFormation':'2028-06-30','dureeFormation':1350,'nombreHeuresEnDistanciel':0},
      'organismeFormation':{'denomination':'INTEGRALE SECURITE FORMATIONS','formationInterne':False,'siret':'84089988400026',
        'uaiCfa':'0831774C','adresse':address,'lieuFormationIdentique':True},
      'contrat':{'modeContractuel':1,'typeContratApp':11,'dateConclusion':'2026-08-25','dateDebutContrat':'2026-09-01',
        'dateFormationPratiqueEmployeur':'2026-09-01','dateFinContrat':'2028-08-31','lieuSignatureContrat':'Puget-sur-Argens',
        'dureeTravailHebdoHeures':35,'dureeTravailHebdoMinutes':0,'travailRisque':False,'salaireEmbauche':1000.50,
        'remunerationsAnnuelles':[{'dateDebut':'2026-09-01','dateFin':'2028-08-31','taux':61,'typeSalaire':'SMIC','ordre':'1.1'}]}},
      'convention':{'couts':{'coutTotalPedagogieCFA':14000,'nombreRepasTotaux':0,'nombreHebergementTotaux':0,
        'montantPremierEquipement':0,'mentionMobiliteInternationale':False},'mandatEmployeur':True,'dateSignature':'2026-08-25',
        'attestationConventionSigneeEntreprise':True,'attestationConventionSigneeCFA':True,
        'attestationConventionSignatureProbante':True,'attestationConventionConformeJSON':True}}


@pytest.fixture
def workspace(tmp_path):
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
    app.secret_key='test-apprenticeship-only-long-key';app.testing=True
    def db():
        conn=sqlite3.connect(tmp_path/'data.sqlite',timeout=10);conn.row_factory=sqlite3.Row;return conn
    with closing(db()) as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,date_naissance TEXT,bts TEXT,email TEXT)')
        conn.executemany('INSERT INTO candidats VALUES(?,?,?,?,?,?)',[('A','EXEMPLE','Camille','2004-01-02','MOS','camille@example.test'),('B','AUTRE','Camille','2004-01-02','MCO','other@example.test')]);conn.commit()
        akto_schema(conn);opco_schema(conn)
    register_apprenticeship(app,db,lambda:session.get('admin_ok'))
    client=app.test_client()
    return app,client,db


def authorize(client):
    with client.session_transaction() as s:s.update(admin_ok=True,_planning_csrf='test-csrf')
    return {'X-CSRF-Token':'test-csrf'}


def create(client,headers):
    r=client.post('/admin/apprentissage/dossiers',headers=headers,json={'candidate_id':'A','creation_key':'test-creation-123456'})
    assert r.status_code in (200,201),r.json
    return r.json['dossier']


def ready(client,headers):
    row=create(client,headers)
    details={k:'Texte de test à valider' for k in DETAILS}
    r=client.put('/admin/apprentissage/dossiers/'+row['id'],headers=headers,json={'version':row['version'],'payload':complete_payload(),'details':details,'provider':'akto','environment':'recette'})
    assert r.status_code==200,r.json;row=r.json['dossier']
    pdf=cerfa_pdf(complete_payload())
    for kind in ('cerfa','convention'):
        r=client.post('/admin/apprentissage/dossiers/'+row['id']+'/documents-signes',headers=headers,
          data={'version':str(row['version']),'kind':kind,'confirmed':'true','file':(BytesIO(pdf),'signed.pdf')})
        assert r.status_code==200,r.json;row=r.json['dossier']
    assert not row['errors'],row['errors']
    return row


def test_authorization_idempotent_creation_and_encryption(workspace):
    app,client,db=workspace
    assert client.get('/admin/apprentissage/dossiers').status_code==403
    h=authorize(client)
    assert client.post('/admin/apprentissage/dossiers',json={}).status_code==403
    a=create(client,h);b=create(client,h)
    assert a['id']==b['id'] and len(a['id'])==6
    assert a['name']=='Camille EXEMPLE' and a['state']=='draft'
    assert client.get('/admin/apprentissage/dossiers?candidate_id=B').json['dossiers']==[]
    with closing(db()) as conn:
        row=conn.execute('SELECT payload FROM apprenticeship_dossiers').fetchone()
        assert b'Camille' not in row[0]
        assert json.loads(secret(app).decrypt(row[0]))['cerfa']['apprenti']['nom']=='EXEMPLE'


def test_revision_conflicts_signed_documents_and_no_implicit_send(workspace,monkeypatch):
    app,client,db=workspace;h=authorize(client)
    monkeypatch.setattr('apprenticeship.submit',lambda *a:pytest.fail('No implicit OPCO send'))
    row=ready(client,h);old=deepcopy(row)
    def save(r):return client.put('/admin/apprentissage/dossiers/'+r['id'],headers=h,json={'version':r['version'],'payload':r['payload'],'details':r['details'],'provider':r['provider'],'environment':r['environment']})
    row['details']['notes']='Une nouvelle note';r=save(row);assert r.status_code==200;row=r.json['dossier']
    assert row['revision']==old['revision'] and not row['errors']
    assert save(old).status_code==409
    row['payload']['cerfa']['contrat']['salaireEmbauche']=1200
    row=save(row).json['dossier']
    assert row['revision']==old['revision']+1
    assert {x['path'] for x in row['errors']}=={'documents.cerfa','documents.convention'}
    assert len(row['documents'])==2
    response=client.post('/admin/apprentissage/dossiers/'+row['id']+'/documents',headers=h,json={'kind':'convention','version':row['version']})
    assert response.status_code==200
    pdf=client.get(response.json['document_url'])
    assert pdf.mimetype=='application/pdf' and 'private' in pdf.headers['Cache-Control']
    assert 'Convention de formation' in PdfReader(BytesIO(pdf.data)).pages[0].extract_text()


def test_official_cerfa_fields_and_exact_v2_payload():
    payload=complete_payload();assert validate(payload)==[]
    pdf=PdfReader(BytesIO(cerfa_pdf(payload)));fields=pdf.get_fields()
    assert len(pdf.pages)==2 and len(fields)==216
    for key,value in cerfa_values(payload).items():assert str(fields[key]['/V'])==str(value)
    assert fields['Zone de texte 21_7']['/V']=='02'
    assert fields['Zone de texte 21_9']['/V']=='2004'
    assert fields['Zone de texte 8_18']['/V']=='2040183123456'
    assert fields['Zone de texte 8_72']['/V']=='1000' and fields['Zone de texte 21_73']['/V']=='50'
    assert fields['Case #C3#A0 cocher 5_4']['/V']=='/Yes'
    for page in pdf.pages:
        for ref in page['/Annots']:
            widget=ref.get_object()
            if widget.get('/T') in cerfa_values(payload):
                assert str(widget['/V'])==str(cerfa_values(payload)[widget['/T']])
                assert widget['/AP']['/N']


def test_validation_dates_minor_and_periods():
    p=complete_payload();p['cerfa']['contrat']['dateFinContrat']='2025-01-01'
    assert any('fin' in e['message'] for e in validate(p))
    p=complete_payload();p['cerfa']['apprenti']['dateNaissance']='2010-01-02'
    assert any('mineur' in e['message'] for e in validate(p))
    p=complete_payload();p['cerfa']['formation']['nombreHeuresEnDistanciel']=2000
    assert any('volume' in e['message'] for e in validate(p))
    p=complete_payload();p['cerfa']['contrat']['remunerationsAnnuelles']*=2
    assert any('chevauchent' in e['message'] for e in validate(p))
    p=complete_payload();p['cerfa']['contrat']['dateFinContrat']=42
    assert any(e['message']=='Texte attendu.' for e in validate(p))
    p=complete_payload();p['cerfa']['contrat']['remunerationsAnnuelles'][0]['ordre']={}
    assert validate(p)


@pytest.mark.parametrize('uncertain',[False,True])
def test_failed_send_never_retries_automatically(workspace,monkeypatch,uncertain):
    app,client,db=workspace;h=authorize(client);row=ready(client,h);calls=[]
    monkeypatch.setattr('apprenticeship.connection',lambda *a:('https://api.example.test',{}))
    def failure(*a):calls.append(a);raise TransferError('Résultat à vérifier',uncertain)
    monkeypatch.setattr('apprenticeship.submit',failure)
    url='/admin/apprentissage/dossiers/'+row['id']+'/transmettre'
    data={'version':row['version'],'confirm':row['id'],'environment':'recette'}
    assert client.post(url,headers=h,json={**data,'confirm':'wrong'}).status_code==400
    assert not calls
    assert client.post(url,headers=h,json=data).status_code==502
    assert len(calls)==1
    assert client.post(url,headers=h,json=data).status_code==409
    updated=client.get('/admin/apprentissage/dossiers/'+row['id']).json['dossier']
    assert updated['state']==('uncertain' if uncertain else 'draft')
    if uncertain:
        data['version']=updated['version'];assert client.post(url,headers=h,json=data).status_code==400
    assert len(calls)==1


def test_success_receipt_sync_identity_and_unknown_payments(workspace,monkeypatch):
    app,client,db=workspace;h=authorize(client);row=ready(client,h);calls=[]
    monkeypatch.setattr('apprenticeship.connection',lambda *a:('https://api.example.test',{}))
    def send(*args):calls.append(args);return dict(numeroInterne='OPCO-42',numeroExterne='E42')
    monkeypatch.setattr('apprenticeship.submit',send)
    url='/admin/apprentissage/dossiers/'+row['id']
    r=client.post(url+'/transmettre',headers=h,json={'version':row['version'],'confirm':row['id'],'environment':'recette'})
    assert r.status_code==200,r.json;row=r.json['dossier']
    assert row['state']=='sent' and row['opco_ref']=='OPCO-42' and row['locked'] and len(calls)==1
    raw={'cerfa':dict(complete_payload()['cerfa'],numeroInterne='OPCO-42',numeroExterne='E42',etat='ENGAGE'),
         'engagement':14000,'echeances':[{'numero':1,'dateOuverture':'2026-09-01','montantTotal':4000,'montantRegle':None}]}
    monkeypatch.setattr('apprenticeship.read',lambda *a:raw)
    raw['cerfa']['apprenti']['nom']='AUTRE'
    assert client.post(url+'/recuperer',headers=h,json={'version':row['version']}).status_code==400
    raw['cerfa']['apprenti']['nom']='EXEMPLE'
    r=client.post(url+'/recuperer',headers=h,json={'version':row['version']});assert r.status_code==200,r.json
    assert r.json['dossier']['state']=='accepted'
    dues=client.get('/admin/apprentissage/echeances').json['dues']
    assert dues[0]['state']=='unknown' and dues[0]['paid'] is None and dues[0]['environment']=='recette'
    row=r.json['dossier']
    raw['echeances'][0]['montantTotal']=float('nan')
    assert client.post(url+'/recuperer',headers=h,json={'version':row['version']}).status_code==400
    assert client.get('/admin/apprentissage/echeances').json['dues'][0]['amount']==4000
    raw.pop('echeances')
    r=client.post(url+'/recuperer',headers=h,json={'version':row['version']})
    assert r.status_code==200 and r.json['dossier']['remote']['schedule_missing']
    assert client.get('/admin/apprentissage/echeances').json['dues'][0]['amount']==4000


def test_interrupted_send_can_be_recovered_but_never_resent(workspace,monkeypatch):
    app,client,db=workspace;h=authorize(client);row=ready(client,h)
    url='/admin/apprentissage/dossiers/'+row['id']
    with closing(db()) as conn:
        conn.execute("UPDATE apprenticeship_dossiers SET state='sending', updated_at='2026-01-01T00:00:00+00:00' WHERE id=?",(row['id'],));conn.commit()
    monkeypatch.setattr('apprenticeship.submit',lambda *a:pytest.fail('Never resend an interrupted transmission'))
    assert client.get(url).json['dossier']['recoverable']
    assert client.post(url+'/transmettre',headers=h,json={'version':row['version']}).status_code==400
    monkeypatch.setattr('apprenticeship.connection',lambda *a:('https://api.example.test',{}))
    monkeypatch.setattr('apprenticeship.read',lambda *a:{'cerfa':dict(complete_payload()['cerfa'],numeroInterne='RECOVERED-42',etat='ENGAGE')})
    result=client.post(url+'/recuperer',headers=h,json={'version':row['version'],'reference':'RECOVERED-42'})
    assert result.status_code==200,result.json
    assert result.json['dossier']['opco_ref']=='RECOVERED-42' and result.json['dossier']['state']=='accepted'


def test_transport_uses_official_multipart_field_and_no_pdf_cerfa_endpoint(monkeypatch):
    from apprenticeship_convergence import submit
    calls=[]
    def call(*args,**kwargs):calls.append((args,kwargs));return dict(status='success',numeroInterne='42')
    monkeypatch.setattr('apprenticeship_convergence.call',call)
    submit('base',{},complete_payload(),b'convention signed')
    args,kwargs=calls[0]
    assert args[-2:]==('POST','/v2/dossiers')
    wire=json.loads(kwargs['data']['PostDossierRequestV2'])
    assert wire['cerfa']['contrat']['dateDebutContrat']=='2026-09-01T00:00:00+00:00'
    assert 'numeroInterne' not in wire['cerfa']
    assert kwargs['files']['fichier'][1]==b'convention signed'
    assert len(calls)==1


def test_pdf_upload_bounds_and_manual_dues(workspace):
    app,client,db=workspace;h=authorize(client);row=create(client,h);url='/admin/apprentissage/dossiers/'+row['id']
    assert client.post(url+'/documents-signes',headers=h,data={'version':'1','kind':'cerfa','confirmed':'true','file':(BytesIO(b'not a pdf'),'bad.pdf')}).status_code==400
    due=dict(label='Participation employeur',due_date=(date.today()+timedelta(days=30)).isoformat(),amount_cents=75000,paid_cents=0,payer='Entreprise')
    assert client.post(url+'/echeances',headers=h,json=due).status_code==200
    d=client.get('/admin/apprentissage/echeances').json['dues'][0]
    assert d['source']=='manual' and d['amount']==750 and d['state']=='upcoming'
    update={**due,'id':d['id'],'version':d['version'],'paid_cents':75000}
    assert client.post(url+'/echeances',headers=h,json=update).status_code==200
    assert client.post(url+'/echeances',headers=h,json=update).status_code==409
