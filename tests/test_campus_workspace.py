"""School operations: enrollment boundaries, atomic placement, messages and privacy."""
import json
import time

import pytest
from test_admissions_2027 import application, auth, client, seed
from campus_admin import sheet_context
from teaching import schema as teaching_schema
from trainer_access import _schema as trainer_schema
from candidate_access import _schema as account_schema
from student_course_details import student_details, zoom_url
from wedof_contracts import ensure_schema as wedof_schema


@pytest.fixture
def campus(client,monkeypatch):
    for cid,status,mode in [('onsite','confirmee','presentiel'),('remote','reconfirmee','distanciel'),('applicant','validee','presentiel'),('pending','reconf_en_cours','distanciel')]:
        seed(2026,cid,status)
        with application.db() as conn:
            conn.execute('UPDATE candidats SET mode=?,tel=?,date_naissance=? WHERE id=?',(mode,'0600000001' if cid=='onsite' else '0600000002','2000-01-01',cid))
    with application.db() as conn:
        trainer_schema(conn)
        teaching_schema(conn)
        conn.execute("INSERT INTO promotions VALUES('p1','BTS MCO 2026–2028','MCO',1,2026,'2026-09-01','2028-07-01',1,0,'now','now')")
        conn.execute("INSERT INTO promotions VALUES('p2','BTS MOS 2026–2028','MOS',1,2026,'2026-09-01','2028-07-01',1,0,'now','now')")
        conn.execute("INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES('t1','PROF','Alex','teacher@example.test','now','now')")
        conn.execute("INSERT INTO teaching_contacts VALUES('t1','0600000003')")
        conn.execute("INSERT INTO companies(id,name,contact,email,phone,created_at,updated_at) VALUES('co','Entreprise exemple','Contact','onsite@example.test','0600000001','now','now')")
        conn.execute("INSERT INTO planning_subjects VALUES('s1','p1','Culture générale','t1','#123456',20)")
        conn.execute("INSERT INTO trainer_promotions VALUES('t1','p1')")
        for cid in ['onsite','remote']:
            conn.execute("INSERT INTO student_promotions VALUES(?,'p1','now')",(cid,))
        conn.execute("INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,date,start_min,end_min,title,created_at,updated_at,zoom_url) VALUES('course','p1','s1','t1','2026-10-26',540,660,'Cours','now','now','https://school.zoom.us/j/123?pwd=example')")
        conn.execute("INSERT INTO planning_course_groups VALUES('course','p1','s1')")
        conn.commit()
        wedof_schema(conn)
        conn.execute("INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES('contract','remote',?,1,'now')",(json.dumps({'state':'accepted','contract_end':'2030-01-01'}),))
    application.migrate_voyage_londres()
    auth(client)
    assert client.get('/admin/inscriptions').status_code==200
    with client.session_transaction() as s:
        headers={'X-CSRF-Token':s['_campus_csrf']}
    sent=[]
    def mail(*args,**kwargs): sent.append(('email',args,kwargs));return 'mail-provider'
    def sms(*args,**kwargs): sent.append(('sms',args,kwargs));return 'sms-provider'
    monkeypatch.setattr(application,'send_mail',mail)
    monkeypatch.setattr(application,'send_sms_brevo',sms)
    return client,headers,sent


def message(**changes):
    return dict(channel='email',groups=['students'],promotions=[],mode='',subject='Les nouvelles de l’école',body='Bonjour,\n\nNotre prochain cours approche.',**changes)


def test_directory_separates_real_status_and_filters(campus):
    c,h,_=campus
    page=c.get('/admin?rentree=2026').text
    assert 'data-id="applicant"' in page and 'data-id="pending"' in page
    assert 'data-id="onsite"' not in page and 'data-id="remote"' not in page
    assert {r['id'] for r in c.get('/admin/json?rentree=2026').json['rows']}=={'applicant','pending'}
    page=c.get('/admin/inscriptions').text
    assert 'data-enrollment-id="onsite"' in page and 'data-enrollment-id="remote"' in page
    assert 'En présentiel' in page and 'En distanciel' in page
    assert 'data-enrollment-id="applicant"' not in page
    page=c.get('/admin/inscriptions?mode=distanciel&contract=yes').text
    assert 'data-enrollment-id="remote"' in page and 'data-enrollment-id="onsite"' not in page
    with application.db() as conn: conn.execute("UPDATE candidats SET label_carte_etudiante=1 WHERE id='onsite'")
    page=c.get('/admin/inscriptions?carte_etudiante_manquante=1').text
    assert 'data-enrollment-id="remote"' in page and 'data-enrollment-id="onsite"' not in page
    page=c.get('/admin/inscriptions?q=remote').text
    assert 'data-enrollment-id="remote"' in page and 'data-enrollment-id="onsite"' not in page


def test_bulk_assignment_atomic_and_secured(campus):
    c,h,_=campus
    data={'ids':['onsite','applicant'],'promotion_id':'p1'}
    assert c.post('/admin/inscriptions/affecter',json=data).status_code==400
    with application.db() as conn: conn.execute("DELETE FROM student_promotions WHERE candidate_id='onsite'")
    assert c.post('/admin/inscriptions/affecter',json=data,headers=h).status_code==400
    with application.db() as conn: assert not conn.execute("SELECT 1 FROM student_promotions WHERE candidate_id='onsite'").fetchone()
    data={'ids':['onsite','remote'],'promotion_id':'p2'}
    assert c.post('/admin/inscriptions/affecter',json=data,headers=h).status_code==400
    data['promotion_id']='p1'
    assert c.post('/admin/inscriptions/affecter',json=data,headers=h).json['count']==2


def test_candidate_tabs_london_and_grade_zero(campus):
    c,h,_=campus
    with application.db() as conn:
        conn.execute("INSERT INTO teaching_homework(id,course_id,title,instructions,due_date,scale,coefficient,published,created_at,updated_at,trainer_id,evaluation_date) VALUES('hw','course','Évaluation exemple','','2026-10-26',20,2,1,'now','now','t1','2026-10-26')")
        conn.execute("INSERT INTO teaching_grades VALUES('hw','onsite',0,'graded','À revoir','now')")
    page=c.get('/admin/candidat/onsite').text
    assert all('id="tab-'+tab+'"' in page for tab in ['assiduite','pedagogie','londres'])
    assert 'Évaluation exemple' in page and 'À revoir' in page
    with application.db() as conn: assert sheet_context(conn,'onsite')['student_average']==0
    page=c.get('/admin/candidat/remote').text
    assert 'id="tab-londres"' not in page
    assert c.post('/admin/candidat/remote/londres',data={'csrf_token':h['X-CSRF-Token']}).status_code==400
    result=c.post('/admin/candidat/onsite/londres',data={'csrf_token':h['X-CSRF-Token'],'convention':'Signée','billet':'on'})
    assert result.status_code==303
    with application.db() as conn:
        trip=conn.execute("SELECT * FROM voyage_londres_inscriptions WHERE candidat_id='onsite'").fetchone()
        assert trip['billet']==1 and trip['convention']=='Signée'


def test_search_admin_only_and_no_sensitive_fields(campus):
    c,h,_=campus
    result=c.get('/admin/recherche?q=remote').json['results']
    assert result[0]['url']=='/admin/candidat/remote'
    assert result[0]['mode']=='distanciel'
    assert 'num_secu' not in json.dumps(result) and 'slug_public' not in json.dumps(result)
    assert c.get('/admin/recherche?q=zoom').json['results'][0]['url']=='/admin/planning'
    anonymous=application.app.test_client()
    for path in ['/admin/recherche?q=remote','/admin/messagerie']:
        assert anonymous.get(path).status_code==403


def test_messages_preview_deduplicate_and_send_exactly_once(campus):
    c,h,sent=campus
    payload=message();payload['groups']=['students','trainers','companies']
    recipients=c.post('/admin/messagerie/destinataires',json=payload,headers=h).json
    assert len(recipients['recipients'])==3 and recipients['duplicate']==1
    assert not sent
    preview=c.post('/admin/messagerie/apercu',json=payload,headers=h).json
    assert preview['ok'] and preview['total']==3 and not sent
    assert 'data-academy-email="v1"' in preview['html']
    path='/admin/messagerie/'+preview['id']+'/envoyer'
    assert c.post(path,json={},headers=h).status_code==400 and not sent
    for _ in range(4): assert c.post(path,json={'confirm':True},headers=h).json['ok']
    assert len(sent)==3 and all(args[2]==preview['html'] for _,args,_ in sent)
    assert all(kwargs.get('copy_admin') is False for _,_,kwargs in sent)
    state=c.get('/admin/messagerie/'+preview['id']).json
    assert state['done'] and state['counts']['sent']==3


def test_sms_selection_invalid_and_failure_not_retried(campus,monkeypatch):
    c,h,sent=campus
    payload=message();payload.update(channel='sms',mode='distanciel',promotions=['p1'])
    preview=c.post('/admin/messagerie/apercu',json=payload,headers=h).json
    assert preview['total']==1 and preview['html']==''
    calls=[]
    monkeypatch.setattr(application,'send_sms_brevo',lambda *args:calls.append(args) or False)
    path='/admin/messagerie/'+preview['id']+'/envoyer'
    assert c.post(path,json={'confirm':True},headers=h).json['counts']['failed']==1
    assert c.post(path,json={'confirm':True},headers=h).json['done'] and len(calls)==1
    assert c.post('/admin/messagerie/apercu',json=payload).status_code==400


@pytest.mark.parametrize('sender_id,name',[('clement','Clément VAILLANT'),('aurelie','Aurélie CHAUSSEZ')])
@pytest.mark.parametrize('layout',['crm','letter'])
def test_sender_signature_preview_and_actual_delivery_share_frozen_identity(campus,monkeypatch,sender_id,name,layout):
    from school_email import SENDERS
    c,h,sent=campus
    payload=message(sender_id=sender_id,layout=layout,accent_title='Notre rentrée, ensemble.')
    payload['body']='Bonjour,\n\n<script>ne pas exécuter</script> & à bientôt.'
    response=c.post('/admin/messagerie/apercu',json=payload,headers=h)
    assert response.status_code==200,response.json
    preview=response.json
    assert preview['sender']['name']==name and name in preview['html']
    assert 'Notre rentrée, ensemble.' in preview['html']
    assert '<script>' not in preview['html'] and '&lt;script&gt;' in preview['html']
    assert '/static/messaging/'+sender_id+'.png' in preview['html']
    assert 'border-radius:50%' in preview['html']
    assert 'Gardons le lien' not in preview['html'] and not sent
    # Changing a future profile or forging a new sender at send time must not
    # change the already-reviewed identity, signature or reply address.
    monkeypatch.setitem(SENDERS[sender_id],'email','future@example.test')
    path='/admin/messagerie/'+preview['id']+'/envoyer'
    assert c.post(path,json={'confirm':True,'sender_id':'forged'},headers=h).json['ok']
    assert sent[0][1][2]==preview['html']
    options=sent[0][2]
    assert options['sender_email']==sender_id+'@integraleacademy.com'
    assert options['reply_to']==options['sender_email']
    assert options['sender_name']==name+' · Intégrale Academy'
    assert c.get('/admin/messagerie/'+preview['id']).json['sender']==preview['sender']


@pytest.mark.parametrize('field,value',[('sender_id','outsider'),('sender_id',{}),('layout','unknown')])
def test_messaging_rejects_unknown_sender_or_layout(campus,field,value):
    c,h,sent=campus
    payload=message();payload[field]=value
    response=c.post('/admin/messagerie/apercu',json=payload,headers=h)
    assert response.status_code==400 and not sent


def test_old_message_preview_migration_preserves_original_sender(campus):
    from school_messaging import schema
    c,h,sent=campus
    with application.db() as conn:
        # A preview created before sender selection was introduced.
        conn.execute('CREATE TABLE school_messages(id TEXT PRIMARY KEY,channel TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,html TEXT NOT NULL,created_at REAL NOT NULL,started_at REAL,owner TEXT NOT NULL)')
        conn.execute('INSERT INTO school_messages VALUES(?,?,?,?,?,?,?,?)',('legacy','email','Objet','Texte','<p>Ancien aperçu</p>',time.time(),None,h['X-CSRF-Token']))
        conn.commit();schema(conn);schema(conn)
        conn.execute("INSERT INTO school_message_recipients(message_id,recipient,name,kind,updated_at) VALUES('legacy','example@example.test','EXEMPLE Alex','Étudiant',?)",(time.time(),))
    preview=c.get('/admin/messagerie/legacy').json
    assert preview['sender']=={} and preview['html']=='<p>Ancien aperçu</p>'
    assert c.post('/admin/messagerie/legacy/envoyer',json={'confirm':True},headers=h).json['ok']
    assert sent[0][2]=={'copy_admin':False}


def test_student_access_mail_preserves_password_and_previews(campus):
    c,h,sent=campus
    c.get('/admin/candidat/onsite')
    with c.session_transaction() as s: headers={'X-CSRF-Token':s['_candidate_message_csrf']}
    data={'type':'email','template':'student_access','subject':'Votre espace étudiant','body':'Bonjour, votre espace vous attend.'}
    preview=c.post('/admin/candidat/onsite/message-preview',json=data,headers=headers).json
    assert not sent and '/espace/connexion' in preview['html']
    assert 'Votre mot de passe personnel reste inchangé' in preview['html']
    data['preview_token']=preview['preview_token']
    assert c.post('/admin/candidat/onsite/message',json=data,headers=headers).json['ok']
    assert len(sent)==1 and sent[0][1][2]==preview['html']


def test_zoom_is_per_course_and_presence_is_never_assumed(campus):
    with application.db() as conn:
        course=dict(conn.execute("SELECT * FROM planning_courses WHERE id='course'").fetchone())
        assert student_details(conn,'onsite',course)['zoom_url']==''
        assert student_details(conn,'remote',course)['zoom_url']==course['zoom_url']
        assert student_details(conn,'remote',course)['attendance_status']=='unrecorded'
        conn.execute("INSERT INTO teaching_rollcalls VALUES('course',1,'now','now','t1')")
        conn.execute("INSERT INTO teaching_attendance VALUES('course','remote','present',0,NULL,NULL)")
        assert student_details(conn,'remote',course)['attendance_label']=='Présent'
        conn.execute("INSERT INTO student_attendance(id,candidate_id,date,start_min,end_min,kind,justification,created_at,updated_at) VALUES('a','remote','2026-10-26',540,660,'absence','pending','now','now')")
        assert student_details(conn,'remote',course)['attendance_label']=='Absent'


@pytest.mark.parametrize('link',['javascript:alert(1)','https://zoom.us.evil.test/j/1','https://zoom.us@evil.test/j/1','http://zoom.us/j/1','https://example.test','https://zoom.us:evil/j/1'])
def test_zoom_rejects_unsafe_links(link):
    with pytest.raises(ValueError): zoom_url(link)


def test_student_pages_never_expose_onsite_zoom(campus):
    c,h,_=campus
    with application.db() as conn:
        account_schema(conn)
        for cid in ['onsite','remote']:
            conn.execute("INSERT INTO student_accounts VALUES(?,'test-unused',0,1,0,0)",(cid,))
            conn.execute('INSERT INTO student_account_members VALUES(?,?)',(cid,cid))
    for cid in ['onsite','remote']:
        student=application.app.test_client()
        with student.session_transaction() as s:
            s['_student_auth']=dict(account_id=cid,candidate_id=cid,version=1,expires_at=time.time()+3600)
        for path in ['/espace/planning?date=2026-10-26','/espace/cours/course','/espace/pedagogie?month=2026-10']:
            page=student.get(path)
            assert page.status_code==200
            if cid=='onsite': assert 'school.zoom.us' not in page.text
            elif '/pedagogie' not in path: assert 'school.zoom.us' in page.text
            assert 'Appel non renseigné' in page.text
        assert student.get('/espace/absences/guide').status_code==200
    anonymous=application.app.test_client()
    assert anonymous.get('/espace/absences/guide').status_code==302
