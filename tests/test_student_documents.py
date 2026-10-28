"""Private school documents: real PDFs/PNGs, enrollment and account isolation."""
from io import BytesIO
import json
from pathlib import Path
import time

from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader
import pytest

import candidate_access
from test_admissions_2027 import application, client, seed

PAGE = '/espace/documents'
CERTIFICATE = PAGE + '/certificat-scolarite.pdf'
RECTO = PAGE + '/carte-etudiante/recto.png'
VERSO = PAGE + '/carte-etudiante/verso.png'
PATHS = (PAGE, CERTIFICATE, RECTO, VERSO)


@pytest.fixture
def documents(client):
    for cid, name, color in [('alice', 'DUPONT', 'blue'), ('bob', 'MARTIN', 'red')]:
        seed(2026, cid)
        folder = Path(application.UPLOAD_DIR) / cid
        folder.mkdir(parents=True)
        Image.new('RGB', (400, 500), color).save(folder / 'portrait.png')
        with application.db() as conn:
            conn.execute('UPDATE candidats SET nom=?,prenom=?,date_naissance=?,fichiers_photo=? WHERE id=?',
                         (name, cid.title(), '2008-02-29', json.dumps([str(folder / 'portrait.png')]), cid))
            candidate_access._schema(conn)
            conn.execute("INSERT INTO student_accounts VALUES(?,'test-only-unused-hash',0,1,0,0)", (cid,))
            conn.execute('INSERT INTO student_account_members VALUES(?,?)', (cid, cid))
    with client.session_transaction() as state:
        state['_student_auth'] = dict(account_id='alice', candidate_id='alice', version=1, expires_at=time.time() + 3600)
    return client


def update(**fields):
    with application.db() as conn:
        conn.execute('UPDATE candidats SET ' + ','.join(key + '=?' for key in fields) + ' WHERE id=?',
                     (*fields.values(), 'alice'))


def private(response):
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Cookie' in response.headers['Vary']


def test_documents_are_easy_to_find_and_link_only_to_own_private_routes(documents):
    page = documents.get(PAGE)
    assert page.status_code == 200
    private(page)
    soup = BeautifulSoup(page.text, 'html.parser')
    nav = soup.select_one('.student-portal-nav')
    assert nav.select_one('[aria-current="page"]')['href'] == PAGE
    assert page.text.count('aria-label="Navigation de l’espace étudiant"') == 1
    assert soup.select_one(f'a[href="{CERTIFICATE}?download=1"]')
    assert [img['src'] for img in soup.select('[data-student-card-image]')] == [RECTO, VERSO]
    assert 'Alice DUPONT' in page.text and 'MARTIN' not in page.text
    assert '/admin/' not in str(soup.select_one('.sw-school-documents'))
    assert not soup.select('iframe')
    home = documents.get('/espace/alice')
    assert home.status_code == 200
    assert BeautifulSoup(home.text, 'html.parser').select_one('.sw-home-documents a')['href'] == PAGE


@pytest.mark.parametrize('mode', ['presentiel', 'distanciel'])
def test_certificate_is_real_personalized_pdf_with_inline_and_download_modes(documents, mode):
    update(mode=mode)
    reply = documents.get(CERTIFICATE)
    assert reply.status_code == 200 and reply.mimetype == 'application/pdf'
    assert reply.headers['Content-Disposition'].startswith('inline;')
    private(reply)
    pdf = PdfReader(BytesIO(reply.data))
    text = ' '.join(page.extract_text() for page in pdf.pages)
    assert 'Alice DUPONT' in text and 'MARTIN' not in text
    assert '2026' in text and '2028' in text
    downloaded = documents.get(CERTIFICATE + '?download=1')
    assert downloaded.headers['Content-Disposition'].startswith('attachment;')
    assert 'Certificat_scolarite_DUPONT_Alice.pdf' in downloaded.headers['Content-Disposition']


def test_both_card_faces_are_real_images_and_downloadable(documents):
    images = []
    for path, side in [(RECTO, 'recto'), (VERSO, 'verso')]:
        reply = documents.get(path)
        assert reply.status_code == 200 and reply.mimetype == 'image/png'
        assert reply.data.startswith(b'\x89PNG\r\n\x1a\n')
        assert reply.headers['Content-Disposition'].startswith('inline;')
        private(reply)
        image = Image.open(BytesIO(reply.data))
        assert image.width >= 1000 and image.height >= 630
        assert image.width / image.height == pytest.approx(243.779 / 153.071, abs=.01)
        images.append(reply.data)
        download = documents.get(path + '?download=1')
        assert download.headers['Content-Disposition'].startswith('attachment;')
        assert f'Carte_etudiante_{side}_DUPONT_Alice.png' in download.headers['Content-Disposition']
    assert images[0] != images[1]


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('session_type', ['anonymous', 'admin', 'initial', 'expired', 'revoked', 'wrong_member'])
def test_no_document_bypasses_current_student_authentication(documents, path, session_type):
    expected = '/espace/connexion'
    with documents.session_transaction() as state:
        if session_type in ('anonymous', 'admin'):
            state.clear()
            if session_type == 'admin':
                state['admin_ok'] = True
        elif session_type == 'expired':
            state['_student_auth'] = {**state['_student_auth'], 'expires_at': time.time() - 1}
        elif session_type == 'wrong_member':
            state['_student_auth'] = {**state['_student_auth'], 'candidate_id': 'bob'}
    if session_type in ('initial', 'revoked'):
        with application.db() as conn:
            conn.execute('UPDATE student_accounts SET must_change=?,version=? WHERE id=?',
                         (int(session_type == 'initial'), 2 if session_type == 'revoked' else 1, 'alice'))
        if session_type == 'initial':
            expected = '/espace/mot-de-passe'
    reply = documents.get(path)
    assert reply.status_code == 302 and reply.headers['Location'] == expected
    private(reply)


@pytest.mark.parametrize('query', ['cid=bob', 'candidate_id=bob', 'slug=bob', 'debut=2029-09-01', 'fin=2035-09-01', 'download=1&download=1'])
def test_url_cannot_override_identity_or_card_validity(documents, query):
    reply = documents.get(RECTO + '?' + query)
    assert reply.status_code == 400
    private(reply)


@pytest.mark.parametrize('status', ['preinscription', 'validee', 'annulee', 'docs_non_conformes', 'unknown'])
def test_unconfirmed_or_cancelled_candidates_cannot_issue_school_documents(documents, status):
    update(statut=status)
    page = documents.get(PAGE)
    assert page.status_code == 200
    soup = BeautifulSoup(page.text, 'html.parser')
    assert not soup.select('[data-student-card-image]')
    assert not soup.select(f'a[href="{CERTIFICATE}?download=1"]')
    for path in (CERTIFICATE, RECTO, VERSO):
        reply = documents.get(path)
        assert reply.status_code == 403
        private(reply)


@pytest.mark.parametrize('status', ['confirmee', 'reconf_en_cours', 'reconfirmee', 'rentree', 'docs_non_conformes'])
def test_confirmed_enrollment_keeps_access_during_reconfirmation_or_document_correction(documents, status):
    update(statut=status, date_confirmee='2026-09-01')
    assert documents.get(CERTIFICATE).status_code == 200


def test_missing_photo_does_not_hide_or_break_certificate(documents):
    update(fichiers_photo='[]')
    page = documents.get(PAGE)
    assert page.status_code == 200 and 'photo d’identité est manquante' in page.text
    assert not BeautifulSoup(page.text, 'html.parser').select('[data-student-card-image]')
    assert documents.get(CERTIFICATE).status_code == 200
    assert documents.get(RECTO).status_code == 409


def test_incomplete_record_has_clear_states_instead_of_broken_links(documents):
    update(mode='')
    page = documents.get(PAGE)
    assert page.status_code == 200
    assert 'Contacte l’école' in page.text
    assert documents.get(CERTIFICATE).status_code == 409
    assert documents.get(RECTO).status_code == 409
    private(documents.get(RECTO))


def test_replaced_photo_is_reflected_without_marking_card_as_sent(documents):
    with application.db() as conn:
        before = dict(conn.execute("SELECT * FROM candidats WHERE id='alice'").fetchone())
    first = documents.get(RECTO).data
    Image.new('RGB', (400, 500), 'green').save(Path(application.UPLOAD_DIR) / 'alice' / 'portrait.png')
    second = documents.get(RECTO).data
    assert first != second
    with application.db() as conn:
        after = dict(conn.execute("SELECT * FROM candidats WHERE id='alice'").fetchone())
    assert before == after


def test_card_rejects_unknown_face_and_deleted_membership(documents):
    assert documents.get(PAGE + '/carte-etudiante/autre.png').status_code == 404
    with application.db() as conn:
        conn.execute("DELETE FROM student_account_members WHERE candidate_id='alice'")
    assert documents.get(RECTO).headers['Location'] == '/espace/connexion'
