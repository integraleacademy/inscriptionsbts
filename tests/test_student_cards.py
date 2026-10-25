"""Student card printing, source artwork, identity, crop and access regressions."""
from datetime import date
from io import BytesIO
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from student_cards import TEMPLATE, student_card_dates, student_card_pdf
from test_admissions_2027 import application, auth, client, seed


@pytest.fixture
def student(client):
    seed(2026, 'card-student')
    folder = Path(application.UPLOAD_DIR) / 'card-student'
    folder.mkdir(parents=True)
    photo = Image.new('RGB', (800, 1000), '#982020')
    ImageDraw.Draw(photo).rectangle((200, 200, 599, 699), fill='#2068b5')
    photo.save(folder/'portrait.png')
    with application.db() as conn:
        conn.execute('UPDATE candidats SET nom=?,prenom=?,date_naissance=?,fichiers_photo=? WHERE id=?',
                     ('DUPONT', 'Éléonore', '2008-02-29', json.dumps([str(folder/'portrait.png')]), 'card-student'))
    auth(client)
    return client


def current_row():
    with application.db() as conn:
        return dict(conn.execute("SELECT * FROM candidats WHERE id='card-student'").fetchone())


def test_dates_are_dossier_based_and_follow_the_school_year():
    row = {'rentree_annee':2026}
    assert student_card_dates(row, date(2026, 1, 1)) == {'start':'2026-09-01', 'end':'2027-08-31'}
    assert student_card_dates(row, date(2027, 8, 31))['start'] == '2026-09-01'
    assert student_card_dates(row, date(2027, 9, 1)) == {'start':'2027-09-01', 'end':'2028-08-31'}
    assert student_card_dates(row, date(2030, 1, 1))['end'] == '2028-08-31'
    assert student_card_dates({'numero_dossier':'2027BTS0001'}, date(2026, 10, 25))['start'] == '2027-09-01'


@pytest.mark.parametrize('layout,size', [('a4',A4), ('carte',(243.779,153.071))])
@pytest.mark.parametrize('mode,address,excluded', [('presentiel','54 chemin du Carreou','141 rue de Rivoli'),
                                                   ('distanciel','141 rue de Rivoli','54 chemin du Carreou')])
def test_card_has_original_artwork_identity_correct_address_and_print_settings(student, layout, size, mode, address, excluded):
    with application.db() as conn:
        conn.execute('UPDATE candidats SET mode=? WHERE id=?',(mode,'card-student'))
    before = current_row()
    response = student.get(f'/admin/candidat/card-student/carte-etudiante.pdf?format={layout}&debut=2027-09-01&fin=2028-08-31')
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['Content-Disposition'].startswith('inline;')
    reader = PdfReader(BytesIO(response.data))
    assert len(reader.pages) == 2
    for page in reader.pages:
        assert (float(page.mediabox.width),float(page.mediabox.height)) == pytest.approx(size,abs=.01)
        assert not [a for a in page.get('/Annots',[]) if a.get_object().get('/Subtype') == '/Widget']
    assert not reader.get_fields()
    assert reader.trailer['/Root']['/ViewerPreferences']['/PrintScaling'] == '/None'
    assert reader.trailer['/Root']['/ViewerPreferences']['/Duplex'] == '/DuplexFlipLongEdge'
    front, back = [p.extract_text() for p in reader.pages]
    for value in ['DUPONT', 'Éléonore', '29/02/2008', '01/09/2027 au 31/08/2028']:
        assert value in front
    for value in [address, 'CFA Intégrale Academy', 'Clément VAILLANT', 'integraleacademy.com', '04 22 47 07 68']:
        assert value in back
    assert excluded not in back and 'Clément VAILLANT' not in front
    source = PdfReader(TEMPLATE)
    for generated, original in zip(reader.pages, [source.pages[1],source.pages[0]]):
        original_images = {hashlib.sha256(image.data).hexdigest() for image in original.images}
        generated_images = {hashlib.sha256(image.data).hexdigest() for image in generated.images}
        assert original_images <= generated_images
    assert current_row() == before


def test_download_uses_the_latest_saved_crop_and_does_not_mark_card_sent(student):
    student.get('/admin/candidat/card-student')
    original = student.get('/admin/candidat/card-student/photo?original=1')
    with student.session_transaction() as state:
        headers = {'X-CSRF-Token':state['_candidate_message_csrf']}
    crop = dict(version=2, rotation=0, straighten=0, cx=.5, cy=.45, width=.5, height=.5,
                source_hash=original.headers['X-Photo-Source'])
    assert student.post('/admin/candidat/card-student/photo-crop', json=crop, headers=headers).status_code == 200
    before = current_row()
    response = student.get('/admin/candidat/card-student/carte-etudiante.pdf?download=1&format=carte')
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert 'Carte_etudiante_DUPONT_Eleonore.pdf' in response.headers['Content-Disposition']
    front = PdfReader(BytesIO(response.data)).pages[0]
    # The synthetic crop is blue throughout; a raw source would contain a red border.
    portraits = [image.image.convert('RGB') for image in front.images if image.image.size == (400,500)]
    assert len(portraits) == 1
    assert portraits[0].getpixel((0,0)) == (32,104,181)
    assert portraits[0].getpixel((399,499)) == (32,104,181)
    assert current_row() == before


def test_replaced_photo_does_not_reuse_a_stale_crop(student):
    from candidate_photos import load_candidate_portrait
    row = current_row()
    photo, source_hash, _ = load_candidate_portrait(row, application.UPLOAD_DIR, application.db)
    with application.db() as conn:
        conn.execute('INSERT INTO candidate_photo_crops VALUES(?,?,?)',('card-student',source_hash,json.dumps(dict(x=.25,y=.2,width=.5,height=.5,rotation=0))))
    path = Path(json.loads(row['fichiers_photo'])[0])
    Image.new('RGB',(600,900),'green').save(path)
    photo, _, crop = load_candidate_portrait(row, application.UPLOAD_DIR, application.db)
    assert photo.size == (600,900) and crop is None


@pytest.mark.parametrize('query', ['format=invalid', 'debut=2028-01-01&fin=2027-01-01', 'debut=not-a-date', 'fin=', 'debut=2027-02-29', 'debut=2000-01-01'])
def test_invalid_requests_return_a_helpful_private_error(student,query):
    response = student.get('/admin/candidat/card-student/carte-etudiante.pdf?'+query)
    assert response.status_code == 400
    assert response.mimetype == 'text/html'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Retour à la fiche' in response.text


@pytest.mark.parametrize('field,value,expected', [('date_naissance','','date de naissance'),('nom','','nom'),('mode','','parcours'),('fichiers_photo','[]','photo')])
def test_incomplete_identity_or_photo_is_not_silently_printed(student,field,value,expected):
    with application.db() as conn:
        conn.execute(f'UPDATE candidats SET {field}=? WHERE id=?',(value,'card-student'))
    response = student.get('/admin/candidat/card-student/carte-etudiante.pdf')
    assert response.status_code == 400 and expected in response.text


def test_student_card_endpoint_requires_admin_and_existing_dossier(student):
    assert student.get('/admin/candidat/missing/carte-etudiante.pdf').status_code == 404
    with student.session_transaction() as state:
        state.clear()
        state['student_id'] = 'card-student'
    assert student.get('/admin/candidat/card-student/carte-etudiante.pdf').status_code == 403


def test_long_accented_names_remain_complete(student):
    row = {**current_row(), 'nom':'DE LA ROCHE SAINT-PIERRE DE MONTFORT-DUPUIS', 'prenom':'Anne-Clémence Marie-Joséphine'}
    pdf = student_card_pdf(row, Image.new('RGB',(400,500),'blue'),layout='carte')
    text = ' '.join(PdfReader(BytesIO(pdf)).pages[0].extract_text().split())
    assert row['nom'] in text and row['prenom'] in text


def test_documents_tab_offers_preview_print_dates_and_both_sizes(student):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(student.get('/admin/candidat/card-student?rentree=2027').text,'html.parser')
    form = soup.select_one('#panel-documents .student-card-form')
    assert form['method'] == 'get' and form['target'] == '_blank'
    assert form['action'].endswith('/card-student/carte-etudiante.pdf')
    # The campaign filter cannot change this student's original cohort.
    assert form.select_one('[name=debut]')['value'] == student_card_dates(current_row())['start']
    assert [o['value'] for o in form.select('[name=format] option')] == ['a4','carte']
    assert [b['value'] for b in form.select('button[name=download]')] == ['0','1']
