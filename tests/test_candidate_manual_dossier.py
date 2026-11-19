"""Complete an existing dossier through the same routes as the admin sheet."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from bs4 import BeautifulSoup
import pytest

from test_admissions_2027 import application, auth, client, seed


@pytest.fixture
def dossier(client):
    seed(2027, 'manual')
    seed(2026, 'other')
    auth(client)
    assert client.get('/admin/candidat/manual?rentree=2027').status_code == 200
    with client.session_transaction() as state:
        headers = {'X-CSRF-Token': state['_candidate_message_csrf']}
    return client, headers


def attach(client, headers, files, category='ci'):
    return client.post('/admin/candidat/manual/documents',
                       data={'category': category, 'documents': [(BytesIO(content), name) for name, content in files]},
                       headers=headers)


def row():
    with application.db() as conn:
        return dict(conn.execute("SELECT * FROM candidats WHERE id='manual'").fetchone())


def test_append_review_retry_and_zip(dossier):
    client, headers = dossier
    old = Path(application.UPLOAD_DIR) / 'manual' / 'CI_manual.pdf'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'%PDF-1.4 ancien')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET fichiers_ci=?, verif_docs=? WHERE id='manual'",
                     (json.dumps([str(old)]), json.dumps({old.name: {'etat': 'conforme'}})))
    files = [('recto.pdf', b'%PDF-1.4 recto'), ('verso.pdf', b'%PDF-1.4 verso')]
    assert attach(client, headers, files).json == {'ok': True, 'added': 2}
    assert attach(client, headers, files).json['added'] == 0
    additional = [('attestation.pdf', b'%PDF-1.4 attestation')]
    assert attach(client, headers, additional, 'autre').json['added'] == 1
    inventory = {item['display_name']: item for item in client.get('/admin/files/manual').json}
    assert inventory[old.name]['status'] == 'conforme'
    assert inventory['attestation.pdf']['category'] == 'autre'
    assert row()['statut'] == 'confirmee' and client.get('/admin/files/other').json == []
    for name, content in files + additional:
        item = inventory[name]
        assert item['status'] == 'en_attente' and client.get(item['url']).data == content
        assert name in client.get(item['url'] + '?download=1').headers['Content-Disposition']
    with ZipFile(BytesIO(client.get('/admin/files/download/manual').data)) as archive:
        assert len(archive.namelist()) == 4
    events = client.get('/admin/logs/manual').json
    assert sum(event['type'] == 'DOCUMENTS_AJOUTES' for event in events) == 2


def test_batch_is_atomic_and_requires_admin(dossier):
    client, headers = dossier
    good = [('recto.pdf', b'%PDF-1.4 recto')]
    assert attach(application.app.test_client(), headers, good).status_code == 403
    assert attach(client, {}, good).status_code == 400
    assert attach(client, headers, good, 'photo').status_code == 400
    assert attach(client, headers, good + [('vide.pdf', b'')]).status_code == 400
    assert attach(client, headers, [('image.png', b'pas une image')]).status_code == 400
    assert client.get('/admin/files/manual').json == []
    assert not any(path.is_file() for path in Path(application.UPLOAD_DIR).rglob('*'))


def test_simultaneous_deposits_keep_both_files(dossier):
    def send(name):
        client = application.app.test_client()
        auth(client)
        with client.session_transaction() as state:
            state['_candidate_message_csrf'] = 'manual-test'
        return attach(client, {'X-CSRF-Token': 'manual-test'},
                      [(name, b'%PDF-1.4 ' + name.encode())], 'cv').json
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(result['added'] == 1 for result in pool.map(send, ['one.pdf', 'two.pdf']))
    assert len(json.loads(row()['fichiers_cv'])) == 2


def test_edit_partial_information_project_and_legacy_profile(dossier):
    client, headers = dossier
    with application.db() as conn:
        conn.execute("""UPDATE candidats SET bts='MOS',bac_status='bac_ms',tel='+442012345678',
                     projet_qualites=?,projet_objectif='Ancien objectif' WHERE id='manual'""",
                     (json.dumps(['Autre qualité', 'rigoureux']),))
    info = '/admin/candidat/manual/informations'
    assert client.post(info, json={'date_naissance': '2012-01-02', 'resp_prenom': 'camille',
                                   'resp_tel': '+44 2012345678'}).json['ok']
    assert row()['est_mineur'] == 1 and row()['resp_prenom'] == 'Camille'
    project = '/admin/candidat/manual/projet'
    data = {'permis_b': 'non', 'entreprise_trouvee': 'oui', 'projet_pourquoi': 'Apprendre',
            'qualites': ['Autre qualité', 'rigoureux', 'organise']}
    assert client.post(project, json=data).status_code == 400
    assert client.post(project, json=data, headers=headers).json['ok']
    assert row()['permis_b'] == 0 and row()['projet_objectif'] == 'Ancien objectif'
    page = BeautifulSoup(client.get('/admin/candidat/manual').text, 'html.parser')
    assert page.select_one('[name=mos_parcours] option:checked')['value'] == 'bac_pro_ms'
    assert page.select_one('[name=qualites][value="Autre qualité"]').has_attr('checked')
    assert page.select_one('[name=projet_pourquoi]').text == 'Apprendre'
    assert client.post(project, json={'projet_pourquoi': 'Perdu', 'permis_b': 'invalide'}, headers=headers).status_code == 400
    assert row()['projet_pourquoi'] == 'Apprendre'


def test_manual_security_answers_without_fabricating_a_submission(dossier):
    client, headers = dossier
    with application.db() as conn:
        conn.execute("UPDATE candidats SET bts='PARCOURS-SECURITE' WHERE id='manual'")
    update = {'situation': 'En études', 'available_year': 'oui', 'mobile_departments': 'non', 'vehicle': 'planned'}
    assert client.post('/admin/candidat/manual/projet', json=update, headers=headers).json['ok']
    page = BeautifulSoup(client.get('/admin/candidat/manual').text, 'html.parser')
    for key, value in update.items():
        assert page.select_one(f'[name={key}] option:checked')['value'] == value
    with application.db() as conn:
        assert not conn.execute("SELECT 1 FROM formation_submissions WHERE candidate_id='manual'").fetchone()
