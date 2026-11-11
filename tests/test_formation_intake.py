"""Real Flask entry points for the two new admission families; all transports are mocked."""
import hashlib
import hmac
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image
from test_admissions_2027 import application, auth, client, payload

from training_programs import SECURITY


def security_data(client):
    guide = BeautifulSoup(client.get('/parcoursalternance/candidature').data, 'html.parser')
    assert ['Obligatoire' in item.text for item in guide.select('.document-format')] == [True, True, True, False, False]
    start = guide.select_one('#start-application')['href']
    doc = BeautifulSoup(client.get(start).data, 'html.parser')
    form = doc.select_one('#application-form')
    assert form['data-endpoint'] == '/parcoursalternance/candidature'
    return dict(csrf=form['data-csrf'], submission_token=form['data-token'], last_name='EXEMPLE', first_name='Alice',
                email='alice@example.test', birth_date='2005-05-15', phone='06 12 34 56 78', city='Puget-sur-Argens',
                postcode='83480', situation='En études', contact_slot='Le matin', vehicle='planned',
                motivation='Je souhaite travailler dans les métiers de la sécurité en alternance.',
                available_year=True, judicial_clear=True, license_b=True, mobile_departments=True, privacy_consent=True)


def security_submission(data, *, optional=False):
    files = payload()
    form = {key: ('yes' if value else 'no') if isinstance(value, bool) else value for key, value in data.items()}
    form.update(sexe='Femme', pays_naissance='France', ville_naissance='Paris', cp_naissance='75001',
                nationalite='Française', adresse='12 rue Test', diplome_obtenu='CAP Agent de sécurité',
                num_secu='2050575123456' + str(97 - 2050575123456 % 97).zfill(2),
                projet_objectif='Travailler en protection rapprochée.', projet_passions='Je suis calme et je pratique la natation.')
    for group in application.PROFILE_GROUPS:
        form[group['name'] + '[]'] = [value for value, _ in group['options'][:2]]
    photo = io.BytesIO()
    Image.new('RGB', (90, 120), 'tan').save(photo, format='PNG')
    photo.seek(0)
    form.update(photo=(photo, 'portrait.png'), ci=files['ci'], carte_vitale=files['carte_vitale'])
    if optional:
        form.update(ci2=files['ci2'], cv=files['cv'], lm=files['lm'])
    return form


def promotion(client, code):
    client.get('/admin/promotions')
    with client.session_transaction() as session:
        csrf = session['_promotion_csrf']
    response = client.post('/admin/promotions', json=dict(csrf_token=csrf, nom='Promotion '+code, bts=code,
                           niveau=1, rentree_annee=2027, date_debut='2027-01-04', date_fin='2027-12-17'))
    assert response.status_code == 201, response.data
    return response.json['promotion_id']


def test_security_to_enrollment_and_promotion(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: False)
    messages = []
    monkeypatch.setattr(application,'send_mail',lambda *a, **k: messages.append((a,k)) or True)
    data = security_data(client)
    assert client.post('/parcoursalternance/candidature', data=security_submission({**data, 'judicial_clear':False})).status_code == 400
    assert client.post('/parcoursalternance/candidature', data=security_submission({**data, 'csrf':'wrong'})).status_code == 400
    answer = client.post('/parcoursalternance/candidature', data=security_submission(data))
    assert answer.status_code == 201 and answer.json['email_sent'] and 'ALT' in answer.json['reference']
    assert client.post('/parcoursalternance/candidature', data=security_submission(data)).json == answer.json
    assert client.post('/parcoursalternance/candidature', data=security_submission(security_data(client))).json['reference'] == ''
    assert len(messages) == 2
    with application.db() as conn:
        row, = conn.execute('SELECT * FROM candidats').fetchall()
        assert row['bts'] == SECURITY and row['statut']=='preinscription' and row['projet_pourquoi']==data['motivation']
        assert 'judicial' not in conn.execute('SELECT details FROM formation_submissions').fetchone()[0]
        cid=row['id']
    auth(client)
    page = client.get('/admin?bts='+SECURITY)
    assert page.status_code == 200 and b'EXEMPLE' in page.data
    form = client.get('/admin/candidat/'+cid)
    assert form.status_code == 200 and 'Le matin' in form.text and 'BTS PARCOURS' not in form.text
    assert all(answer in form.text for answer in ('CAP Agent de sécurité', '12 rue Test', 'Française', 'Paris', '75001',
        'Travailler en protection rapprochée.', 'je pratique la natation', 'Organisation', 'Je suis méthodique'))
    documents = client.get('/admin/files/' + cid).json
    assert {entry['category'] for entry in documents} == {'ci', 'photo', 'carte_vitale'}
    assert all(client.get(entry['url']).status_code == 200 for entry in documents)
    assert client.get('/admin/candidat/' + cid + '/photo').mimetype == 'image/jpeg'
    assert application.app.test_client().get(documents[0]['url']).status_code == 403
    pid=promotion(client,SECURITY)
    with client.session_transaction() as s:
        csrf=s['_promotion_csrf']
    assert client.post(f'/admin/candidat/{cid}/promotion', json={'csrf_token':csrf,'promotion_id':pid}).status_code == 200
    from candidate_workflows import prepare_workflow
    with application.app.test_request_context():
        planned = prepare_workflow(dict(row),'status',{'value':'validee'})
        assert all('BTS' not in (item.get('html') or item.get('body','')).split('<body')[-1].replace('inscriptionsbts','') for item in planned['messages'])
        assert 'Écrire à Aurélie pour mon entretien' in planned['messages'][0]['html']
        assert '/confirm-inscription?' not in planned['messages'][0]['html']
    with application.db() as conn:
        conn.execute("UPDATE candidats SET statut='confirmee' WHERE id=?",(cid,))
    listed=client.get('/admin/inscriptions',query_string={'bts':SECURITY,'promotion':pid})
    assert listed.status_code==200 and b'EXEMPLE' in listed.data
    assert client.get('/admin/candidat/'+cid+'/certificat.pdf').data.startswith(b'%PDF')
    with application.app.test_request_context(), application.db() as conn:
        from certificates import certificate_pdf
        assert certificate_pdf(dict(conn.execute('SELECT * FROM candidats WHERE id=?',(cid,)).fetchone())).startswith(b'%PDF')


def test_security_rejects_incomplete_dossiers_and_accepts_optional_files(client):
    path = '/parcoursalternance/candidature'
    data = security_data(client)
    assert client.post(path, json=data).status_code == 400
    for missing in ('photo', 'ci', 'carte_vitale', 'nationalite', 'travail[]', 'projet_objectif', 'diplome_obtenu'):
        form = security_submission(data)
        form.pop(missing)
        assert client.post(path, data=form).status_code == 400
    assert client.post(path, data=dict(security_submission(data), num_secu='000000000000000')).status_code == 400
    assert client.post(path, data=dict(security_submission(data), photo=(io.BytesIO(b'invalid'), 'photo.png'))).status_code == 400
    with application.db() as conn:
        assert not conn.execute('SELECT 1 FROM candidats').fetchone()
    assert client.post(path, data=security_submission(data, optional=True)).status_code == 201
    with application.db() as conn:
        row = conn.execute('SELECT * FROM candidats').fetchone()
        for key, count in [('ci', 2), ('photo', 1), ('carte_vitale', 1), ('cv', 1), ('lm', 1)]:
            paths = json.loads(row['fichiers_' + key])
            assert len(paths) == count and all(Path(path).is_file() for path in paths)


def test_expiring_security_application_removes_only_its_files(client, tmp_path):
    from formation_intake import expire_submissions
    auth(client)
    client.get('/admin/promotions')
    path = '/parcoursalternance/candidature'
    for surname in ('ANCIEN', 'INSCRIT'):
        assert client.post(path, data=security_submission(dict(security_data(client), last_name=surname))).status_code == 201
    with application.db() as conn:
        dossiers = {row['nom']: row['id'] for row in conn.execute('SELECT nom,id FROM candidats')}
        conn.execute("UPDATE formation_submissions SET received_at='2025-01-01'")
        conn.execute("UPDATE candidats SET statut='confirmee' WHERE nom='INSCRIT'")
    root = tmp_path / 'uploads'
    with application.db() as conn:
        expire_submissions(conn, '2026-01-01', root)
        assert [row['id'] for row in conn.execute('SELECT id FROM candidats')] == [dossiers['INSCRIT']]
    assert not (root / dossiers['ANCIEN']).exists()
    assert any((root / dossiers['INSCRIT']).iterdir())


def test_title_uses_full_dossier_and_dated_promotion_independently_of_bts(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: True)
    messages = []
    monkeypatch.setattr(application, 'send_mail', lambda *a, **kw: messages.append(a) or True)
    auth(client)
    code = 'TP GESTIONNAIRE DE PAIE'
    pid = promotion(client, code)
    path = '/titres-professionnels/candidature/' + pid
    assert path in client.get('/admin/promotions').text
    guest = application.app.test_client()
    form = BeautifulSoup(guest.get(path).data, 'html.parser').select_one('#application-form')
    credentials = {key: form.select_one(f'[name={key}]')['value'] for key in ('csrf', 'submission_token')}
    def dossier():
        data = payload()
        data.pop('cherche_idf')
        return dict(data, **credentials, bts=code, mode='presentiel')
    assert guest.post(path, data=dict(dossier(), mode='distanciel')).status_code == 400
    assert guest.post(path, data=dict(dossier(), bts='MCO')).status_code == 400
    incomplete = dossier()
    del incomplete['lm']
    assert guest.post(path, data=incomplete).status_code == 400
    assert guest.post(path, data=dict(dossier(), csrf='wrong')).status_code == 400
    assert guest.post(path, data=dict(dossier(), admin_preview='1')).status_code == 403
    with application.db() as conn:
        assert not conn.execute('SELECT 1 FROM candidats').fetchone()
    assert not messages
    assert guest.post(path, data=dossier(), headers={'Accept':'application/json'}).json == {'ok':True, 'redirect':'/espace/connexion'}
    assert guest.post(path, data=dossier()).status_code == 303
    with application.db() as conn:
        row, = conn.execute('SELECT c.*,s.promotion_id FROM candidats c JOIN student_promotions s ON s.candidate_id=c.id').fetchall()
        assert (row['bts'], row['statut'], row['promotion_id']) == (code, 'preinscription', pid)
        assert row['numero_dossier'].startswith('2027TP') and row['mode'] == 'presentiel'
        assert row['adresse'] == '1 rue Test' and row['projet_objectif'] == 'Devenir responsable' and row['projet_qualites']
        for key, count in [('ci', 2), ('photo', 1), ('carte_vitale', 1), ('cv', 1), ('lm', 1)]:
            paths = json.loads(row['fichiers_' + key])
            assert len(paths) == count and all(Path(p).is_file() for p in paths)
        assert len(messages) == 2
        conn.execute('UPDATE promotions SET active=0 WHERE id=?',(pid,))
    assert guest.get(path).status_code == 404
    assert guest.post(path,data=dossier()).status_code == 404


def test_before_opening_only_security_accepts_applications(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: False)
    auth(client)
    pid = promotion(client, 'TP GESTIONNAIRE DE PAIE')
    guest = application.app.test_client()
    path = '/titres-professionnels/candidature/' + pid
    response = guest.get(path)
    assert response.status_code == 302 and response.location.endswith('/#ouverture-tp')
    waiting = BeautifulSoup(guest.get(response.location).data, 'html.parser')
    assert '1er décembre' in waiting.select_one('#ouverture-tp').get_text()
    assert not waiting.select('#application-form')
    assert guest.post(path, data={}).status_code == 403
    assert guest.post(path+'/brouillon', json={}).status_code == 403
    assert guest.post('/submit', data={}).status_code == 403
    assert guest.post('/parcoursalternance/candidature', data=security_submission(security_data(guest), optional=True)).status_code == 201


def test_title_draft_resumes_correct_session_with_fresh_credentials(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: True)
    auth(client)
    code = 'TP GESTIONNAIRE DE PAIE'
    pid = promotion(client, code)
    guest = application.app.test_client()
    path = '/titres-professionnels/candidature/' + pid
    form = BeautifulSoup(guest.get(path).data, 'html.parser').select_one('#application-form')
    fields = {key: form.select_one(f'[name={key}]')['value'] for key in ('csrf','submission_token')}
    fields.update(email='camille@example.test', bts=code, prenom='camille', **{'qualites[]':['curieux','rigoureux']})
    assert guest.post(path + '/brouillon', json={'full_form': dict(fields, bts='MCO')}).status_code == 400
    link = guest.post(path + '/brouillon', json={'full_form': fields}).json['link']
    resumed = BeautifulSoup(application.app.test_client().get(link).data, 'html.parser')
    saved = json.loads(resumed.select_one('#saved-application').string)
    assert saved['title_promotion_id'] == pid and saved['prenom'] == 'Camille'
    assert saved['qualites[]'] == fields['qualites[]'] and 'csrf' not in saved and 'submission_token' not in saved
    assert resumed.select_one('#application-form')['action'] == path
    assert resumed.select_one('[name=submission_token]')['value'] != fields['submission_token']
    with application.db() as conn:
        conn.execute('UPDATE promotions SET active=0 WHERE id=?', (pid,))
    assert guest.get(link).status_code == 302 and guest.post(path + '/brouillon', json={'full_form':fields}).status_code == 404


def test_legacy_replay_preserves_notes_and_sends_nothing(client,monkeypatch):
    secret='s'*40
    monkeypatch.setenv('BTS_IMPORT_API_KEY',secret)
    monkeypatch.setattr(application,'send_mail',lambda *a,**k: (_ for _ in ()).throw(AssertionError('historical mail')))
    data=security_data(client)
    data.pop('judicial_clear')
    record={'id':'ALT-123456ABCDEF','payload':data,'status':'interview','created_at':datetime.now(timezone.utc).isoformat(),'notes':'Rappeler mardi.'}
    body=json.dumps(record).encode()
    path='/api/admissions/reprise-parcours-securite'
    assert client.post(path,data=body,content_type='application/json').status_code==401
    key=hmac.digest(secret.encode(), b'parcours-securite-import-v1', 'sha256')
    headers={'X-Parcours-Signature':hmac.new(key,body,hashlib.sha256).hexdigest()}
    first=client.post(path,data=body,headers=headers,content_type='application/json')
    assert first.status_code==200 and first.json==client.post(path,data=body,headers=headers,content_type='application/json').json
    with application.db() as conn:
        row,=conn.execute('SELECT statut,commentaires FROM candidats').fetchall()
        assert tuple(row)==('preinscription','Rappeler mardi.')
        assert conn.execute('SELECT count(*) FROM formation_receipts').fetchone()[0]==0
