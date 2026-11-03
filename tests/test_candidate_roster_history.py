from io import BytesIO

from test_admissions_2027 import application, auth, client, seed
from school_messaging import schema

PATH = '/admin/candidatures/importer'
DATA = 'nom_famille;prenoms;adresse_mail;date_naissance;division_classe\r\nPetit;Léa;lea@example.test;16/02/2005;MOS2A252\r\n'


def submit(client, action, raw=DATA):
    with client.session_transaction() as session:
        token = session['_candidate_message_csrf']
    return client.post(PATH, data=dict(csv=(BytesIO(raw.encode('cp1252')),'export.csv'),csrf_token=token,action=action))


def test_preview_import_retry_and_invalid_batch(client, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('Notification during import')
    monkeypatch.setattr(application,'send_mail',unexpected)
    monkeypatch.setattr(application,'send_sms_brevo',unexpected)
    assert client.post(PATH).status_code==403
    auth(client)
    assert client.get(PATH).status_code==200
    assert client.post(PATH).status_code==400
    assert 'rentrée 2025' in submit(client,'preview').text
    with application.db() as conn:
        assert not conn.execute('SELECT id FROM candidats').fetchall()
    assert submit(client,'import',DATA.replace('MOS2A252','xxx')).status_code==400
    assert submit(client,'import').status_code==200
    assert submit(client,'import').status_code==200
    with application.db() as conn:
        row, = conn.execute('SELECT * FROM candidats')
        assert (row['statut'],row['bts'],row['prenom'],row['rentree_annee'])==('confirmee','MOS','Léa',2025)
        assert row['date_confirmee']
        assert row['id'] in client.get('/admin/inscriptions').text
        assert row['id'] not in client.get('/admin?rentree=2025').text


def test_existing_candidate_is_confirmed_but_conflicts_are_skipped(client):
    auth(client)
    client.get(PATH)
    seed(2025,'lea','preinscription')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET nom='Petit',prenom='Léa',bts='MOS' WHERE id='lea'")
    assert 'À vérifier' in submit(client,'import',DATA.replace('Petit','Autre')).text
    assert '1 candidature(s) confirmée(s)' in submit(client,'import').text
    with application.db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT id,statut FROM candidats')]==[('lea','confirmee')]


def test_history_separates_sent_mail_by_student(client):
    seed(2026,'lea')
    url = '/admin/candidat/lea/emails'
    assert client.get(url).status_code==403
    auth(client)
    application.log_event('lea','MAIL_ENVOYE',dict(objet='Courrier individuel',message='<script>texte</script>'))
    application.log_event('lea','SMS_ENVOYE',dict(message='SMS privé'))
    application.log_event('other','MAIL_ENVOYE',dict(message='Autre dossier'))
    with application.db() as conn:
        schema(conn)
        conn.execute("""INSERT INTO school_messages(id,channel,subject,body,html,created_at,owner)
                        VALUES('m','email','Courrier collectif','Infos classe','',1,'owner')""")
        conn.execute("""INSERT INTO school_message_recipients(message_id,recipient,name,kind,status,updated_at,candidate_id)
                        VALUES('m','ancienne@example.test','Camille TEST','Étudiant','sent',2,'lea')""")
    page = client.get(url).text
    assert 'Courrier individuel' in page and 'Infos classe' in page and 'ancienne@example.test' in page
    assert '<script>texte' not in page and 'SMS privé' not in page and 'Autre dossier' not in page
