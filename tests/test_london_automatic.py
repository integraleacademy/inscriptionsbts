"""Automatic source resolution, SMS consent, durable delivery and completion notices."""
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from bs4 import BeautifulSoup

from test_london_signatures import application, auth, client, seed, london, signing, attempts, action
from test_london_mobility import data, versions, post
from company_portal import ensure_company_schema
from london_mobility_data import automatic_data, mobile
from london_mobility_signatures import SignatureError
from wedof_contracts import ensure_schema as wedof_schema


@pytest.fixture
def automatic(london, signing, monkeypatch):
    monkeypatch.setitem(application.app.config,'LONDON_AUTOMATIC_DEFER',True)
    with application.db() as conn:
        ensure_company_schema(conn)
        conn.execute('''INSERT INTO companies(id,name,contact,email,phone,siret,created_at,updated_at,address,postal_code,city)
            VALUES('company','Entreprise Exemple','EXEMPLE Alex','alex@entreprise.example','06 12 34 56 78','12345678901234','2026-01-01','2026-01-01','12 rue des Écoles','75001','Paris')''')
        conn.execute("INSERT INTO company_students VALUES('london','company','2026-09-01','2028-08-31','','2026-01-01')")
        conn.execute("UPDATE candidats SET email='camille@apprenti.example',tel='0676543210',resp_nom='EXEMPLE',resp_prenom='Charlie',resp_email='parent@famille.example',resp_tel='0712345678' WHERE id='london'")
    return london


def send_auto(client,cid='london',**changes):
    with client.session_transaction() as state: csrf=state.get('_campus_csrf','')
    return client.post(f'/admin/candidat/{cid}/londres/preparer-et-envoyer',data={'csrf_token':csrf,**changes},headers={'Accept':'application/json'})


def run():
    state=attempts()[0]
    application.app.extensions['london_automatic_run'](state['candidate_id'],state['version_id'],state['id'])


def resolve():
    with application.db() as conn:
        return automatic_data(conn,dict(conn.execute("SELECT * FROM candidats WHERE id='london'").fetchone()))


def test_one_click_creates_sends_sms_and_duplicate_click_is_idempotent(automatic,signing):
    # Old London test text is ignored in favour of the authoritative company.
    post(automatic,data(automatic,action='save',employer_name='test',employer_address='test'))
    page=BeautifulSoup(automatic.get('/admin/candidat/london').data,'html.parser')
    panel=page.select_one('#panel-londres')
    assert not panel.select('input:not([type=hidden]):not([type=checkbox]),select,textarea')
    assert not panel.select_one('[data-london-send] button').has_attr('disabled')
    response=send_auto(automatic)
    assert response.status_code==202,response.json
    assert len(versions())==1 and not signing.calls
    assert send_auto(automatic).status_code==200
    run()
    assert len(signing.requests)==1 and attempts()[0]['status']=='ongoing'
    assert send_auto(automatic).status_code==200
    assert len(signing.requests)==1
    assert all(p['signature_authentication_mode']=='otp_sms' for p in signing.latest['signers'])
    assert [p['info']['phone_number'] for p in signing.latest['signers']]==['+33612345678','+33676543210']
    assert signing.latest['signers'][0]['info']['first_name']=='Alex'
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(signing.latest['content'])).pages)
    assert 'Entreprise Exemple' in text and '12 rue des Écoles' in text
    assert signing.calls[-1][1].endswith('/activate')


def test_minor_auto_includes_guardian_sms(automatic,signing):
    with application.db() as conn:conn.execute("UPDATE candidats SET date_naissance='2010-03-12' WHERE id='london'")
    assert send_auto(automatic).status_code==202
    run();assert len(signing.latest['signers'])==3
    assert signing.latest['signers'][2]['info']['phone_number']=='+33712345678'


@pytest.mark.parametrize('sql,expected',[
    ("UPDATE companies SET phone='0422470768'",'mobile'),
    ("UPDATE companies SET contact='Inconnu'",'prénom et nom'),
    ("UPDATE candidats SET tel='' WHERE id='london'",'mobile'),
    ("UPDATE companies SET email='camille@apprenti.example'",'propre e-mail'),
    ("UPDATE companies SET phone='0676543210'",'propre mobile'),
    ("UPDATE companies SET siret='test'",'SIRET'),
    ("UPDATE company_students SET end_date='2027-01-01'",'rattachement'),
    ("UPDATE companies SET active=0",'désactivée'),
])
def test_missing_authoritative_information_never_sends(automatic,signing,sql,expected):
    with application.db() as conn:conn.execute(sql)
    response=send_auto(automatic)
    assert response.status_code==422,response.json
    assert expected in ' '.join(i['message'] for i in response.json['issues'])
    assert not signing.calls and not versions()


def test_worker_rechecks_changed_phone_before_remote_actions(automatic,signing):
    send_auto(automatic)
    with application.db() as conn:conn.execute("UPDATE companies SET phone='0711223344'")
    run();assert not signing.calls
    assert attempts()[0]['error'] and not attempts()[0].get('request_id')


def test_unauthorized_csrf_foreign_candidate_and_cancelled_trip(automatic,signing):
    assert send_auto(automatic,csrf_token='bad').status_code==400
    assert send_auto(automatic,cid='absent').status_code==404
    with application.db() as conn:
        conn.execute("INSERT INTO voyage_londres_inscriptions(id,candidat_id,statut,created_at,updated_at) VALUES('trip','london','annulee','2026-01-01','2026-01-01')")
    assert send_auto(automatic).status_code==422
    with automatic.session_transaction() as session:session.clear()
    assert send_auto(automatic,csrf_token='').status_code==403
    assert automatic.get('/admin/candidat/london/londres/signature-status').status_code==403
    assert automatic.get('/admin/voyage-londres/notifications').status_code==403
    assert not signing.calls


def test_recovery_after_restart_sends_the_explicitly_authorized_job(automatic,signing):
    send_auto(automatic);state=attempts()[0];state['created_at']='2020-01-01T00:00:00+00:00'
    service=application.app.extensions['london_signatures'];service.save(state)
    with application.app.app_context():service.poll()
    assert attempts()[0]['status']=='ongoing' and len(signing.requests)==1


def test_timeout_recovery_does_not_duplicate_activation(automatic,signing):
    signing.timeout=('POST','activate');send_auto(automatic);run()
    assert attempts()[0]['pending']=='activate'
    state=attempts()[0];state['checked_at']='2020-01-01T00:00:00+00:00'
    service=application.app.extensions['london_signatures'];service.save(state)
    with application.app.app_context():service.poll()
    assert attempts()[0]['status']=='ongoing'
    assert len([c for c in signing.calls if c[1].endswith('/activate')])==1


def test_notification_only_after_all_signed_persists_and_acknowledges(automatic,signing):
    send_auto(automatic);run()
    assert automatic.get('/admin/voyage-londres/notifications').json['count']==0
    signing.latest['signers'][0]['status']='signed'
    action(automatic,'refresh')
    assert automatic.get('/admin/voyage-londres/notifications').json['count']==0
    signing.complete();assert action(automatic,'refresh').status_code==200
    notification=automatic.get('/admin/voyage-londres/notifications').json
    assert notification['count']==1
    item=notification['notifications'][0]
    assert item['candidate_id']=='london' and automatic.get(item['document_url']).status_code==200
    assert action(automatic,'refresh').status_code==200
    assert automatic.get('/admin/voyage-londres/notifications').json['count']==1
    page=BeautifulSoup(automatic.get('/admin/voyage-londres').data,'html.parser')
    assert page.select_one('[data-london-notification-count]').text=='1'
    assert not page.select_one('[data-london-notification-count]').has_attr('hidden')
    url='/admin/voyage-londres/notifications/'+item['version_id']+'/lue'
    assert automatic.post(url,data={'csrf_token':'bad'}).status_code==400
    with automatic.session_transaction() as state:csrf=state.get('_campus_csrf','')
    assert automatic.post(url,data={'csrf_token':csrf}).status_code==200
    assert automatic.get('/admin/voyage-londres/notifications').json['count']==0
    assert send_auto(automatic).status_code==200 and len(signing.requests)==1


def test_tampered_sms_authentication_or_phone_blocks_archiving(automatic,signing):
    send_auto(automatic);run();signing.complete()
    signing.latest['signers'][0]['signature_authentication_mode']='otp_email'
    assert action(automatic,'refresh').status_code==409
    assert not versions()[0]['signed_id']
    signing.latest['signers'][0]['signature_authentication_mode']='otp_sms'
    signing.latest['signers'][0]['info']['phone_number']='+33700000000'
    assert action(automatic,'refresh').status_code==409
    assert automatic.get('/admin/voyage-londres/notifications').json['count']==0


def test_contracts_are_scoped_and_match_company(automatic,signing):
    with application.db() as conn:
        wedof_schema(conn)
        payload={'state':'accepted','employer_name':'Unrelated','employer_siret':'99999999999999','employer_address':'Ailleurs'}
        conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at,error) VALUES(?,?,?,?,?,?)',('other','other',json.dumps(payload),1,1,''))
        assert resolve()['ready']
        conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at,error) VALUES(?,?,?,?,?,?)',('conflict','london',json.dumps(payload),1,1,''))
    assert send_auto(automatic).status_code==422 and not signing.calls


@pytest.mark.parametrize('raw,expected',[('06 12 34 56 78','+33612345678'),('+33 (0)6 12 34 56 78','+33612345678'),('0033 6 12 34 56 78','+33612345678'),('+44 7700 900123','+447700900123')])
def test_mobile_normalisation(raw,expected):assert mobile(raw)==expected


def test_edit_during_upload_blocks_activation(automatic,signing):
    original=signing.perform
    def edit_after_upload(method,path,**kwargs):
        response=original(method,path,**kwargs)
        if method=='POST' and path.endswith('/documents'):
            with application.db() as conn:conn.execute("UPDATE companies SET phone='0711223344'")
        return response
    signing.perform=edit_after_upload
    send_auto(automatic);run()
    assert not any(c[1].endswith('/activate') for c in signing.calls)
    assert attempts()[0]['error']


def test_redesigned_pdf_preserves_clauses_and_signature_zones(automatic):
    from london_mobility_design import source,signature_layout,pdf_document
    from london_mobility_documents import VERSION
    snapshot=resolve()['snapshot']
    snapshot.update(employer_name='Société de prévention et de sécurité internationale des établissements de formation professionnels de Provence et de la Côte d’Azur',employer_address='Immeuble des Entreprises, bâtiment de la Formation, troisième étage, zone d’activité du Grand Parc, 123 avenue des Métiers et des Compétences Professionnelles')
    reader=PdfReader(BytesIO(pdf_document(snapshot)));assert len(reader.pages)==6
    norm=lambda text:' '.join(text.replace('\u00a0',' ').split())
    content=norm(' '.join(page.extract_text() for page in reader.pages));paragraphs,_=source()
    for index in [59,61,63,65,67,78,80,82,84,89,91,95,96,98,100,101,103,109,111,113,115,117,122,123,184,*range(186,197),198,*range(200,210),214,216,*range(218,226),228,*range(230,235),237,239,241]:
        assert norm(paragraphs[index]) in content,index
    for field in signature_layout(snapshot).values():
        assert field['page']==4 and field['y']+field['height']<790
    assert snapshot['version']==VERSION


def test_cancelled_request_previews_fresh_recipients(automatic,signing):
    send_auto(automatic);run();assert action(automatic,'cancel',cancel_confirmed='yes').status_code==200
    with application.db() as conn:conn.execute("UPDATE companies SET email='new.contact@entreprise.example'")
    soup=BeautifulSoup(automatic.get('/admin/candidat/london').data,'html.parser')
    panel=soup.select_one('#panel-londres')
    assert 'new.contact@entreprise.example' in panel.text and 'alex@entreprise.example' not in panel.text
    assert not panel.select_one('[data-london-send] button').has_attr('disabled')


def test_legacy_requests_are_not_mislabelled_as_sms(automatic,signing):
    send_auto(automatic);run();state=attempts()[0];state.pop('authentication_mode')
    for person in state['recipients']:person.pop('phone_number')
    application.app.extensions['london_signatures'].save(state)
    soup=BeautifulSoup(automatic.get('/admin/candidat/london').data,'html.parser')
    panel=soup.select_one('#panel-londres')
    assert 'Code par e-mail · ancienne demande' in panel.text
    assert 'Code personnel par SMS' not in panel.text
