"""Private trainer portraits reuse the current crop and current roster grants."""
from io import BytesIO
import json
from pathlib import Path
import time

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from test_campus_workspace import campus, client, application


PHOTO_URL = '/formateur/etudiants/onsite/photo'


@pytest.fixture
def trainer_home(campus, monkeypatch):
    c, _, _ = campus
    monkeypatch.setattr(application.app, 'secret_key', 'trainer-portrait-test-only')
    root = Path(application.UPLOAD_DIR) / 'onsite'
    root.mkdir(parents=True)
    photo = root / 'portrait.jpg'
    Image.new('RGB', (320,400), 'blue').save(photo)
    with application.db() as conn:
        conn.execute("UPDATE candidats SET fichiers_photo=? WHERE id='onsite'", (json.dumps([str(photo)]),))
        conn.execute("UPDATE trainers SET password_hash='test-only-hash' WHERE id='t1'")
    with c.session_transaction() as state:
        state.clear()
        state['_trainer_auth'] = dict(trainer_id='t1', version=1, expires_at=time.time()+3600)
    return c, photo


def test_roster_shows_photo_without_exposing_uploads_or_bearer_links(trainer_home):
    c, photo = trainer_home
    response = c.get('/formateur')
    assert response.status_code == 200
    page = BeautifulSoup(response.text, 'html.parser')
    images = page.select('[data-student-photo]')
    assert len(images) == 1 and images[0]['src'] == PHOTO_URL
    assert images[0]['loading'] == 'lazy'
    assert str(photo) not in response.text and '/admin/candidat/onsite' not in response.text
    assert len(page.select('.trainer-student-avatar')) == 2
    image = c.get(PHOTO_URL)
    assert image.status_code == 200 and image.mimetype == 'image/jpeg'
    assert image.headers['Cache-Control'] == 'private, no-store'
    assert 'Cookie' in image.headers['Vary']
    assert image.headers['X-Content-Type-Options'] == 'nosniff'
    assert c.get('/admin/candidat/onsite/photo').status_code == 403


def test_portrait_reuses_crop_and_reflects_replacement(trainer_home):
    c, photo = trainer_home
    source = c.get(PHOTO_URL).headers['X-Photo-Source']
    with application.db() as conn:
        conn.execute('INSERT INTO candidate_photo_crops VALUES(?,?,?)',
                     ('onsite', source, json.dumps(dict(x=0,y=0,width=.5,height=.5,rotation=0))))
    cropped = c.get(PHOTO_URL)
    assert Image.open(BytesIO(cropped.data)).size == (160,200)
    with c.session_transaction() as state:
        state['admin_ok'] = True
    assert c.get('/admin/candidat/onsite/photo').data == cropped.data
    with c.session_transaction() as state:
        state.pop('admin_ok')
    replacement = photo.with_name('replacement.jpg')
    Image.new('RGB', (320,400), 'green').save(replacement)
    with application.db() as conn:
        conn.execute("UPDATE candidats SET fichiers_photo=? WHERE id='onsite'", (json.dumps([str(replacement),str(photo)]),))
    current = c.get(PHOTO_URL)
    assert current.headers['X-Photo-Source'] != source
    assert Image.open(BytesIO(current.data)).size == (320,400)
    assert current.data != cropped.data


@pytest.mark.parametrize('sql,status', [
    ("DELETE FROM trainer_promotions WHERE trainer_id='t1'",404),
    ("UPDATE student_promotions SET promotion_id='p2' WHERE candidate_id='onsite'",404),
    ("UPDATE promotions SET active=0 WHERE id='p1'",404),
    ("UPDATE candidats SET statut='annulee' WHERE id='onsite'",404),
    ("UPDATE candidats SET bts='MOS' WHERE id='onsite'",404),
    ("UPDATE candidats SET rentree_annee=2027 WHERE id='onsite'",404),
    ("UPDATE trainers SET active=0 WHERE id='t1'",403),
    ("UPDATE trainers SET version=2 WHERE id='t1'",403),
])
def test_photo_rechecks_grants_after_roster_was_loaded(trainer_home, sql, status):
    c, _ = trainer_home
    assert c.get('/formateur').status_code == 200
    assert c.get(PHOTO_URL).status_code == 200
    with application.db() as conn:
        conn.execute(sql)
    assert c.get(PHOTO_URL).status_code == status


def test_photo_requires_own_trainer_session_and_cannot_override_scope(trainer_home):
    c, _ = trainer_home
    stranger = application.app.test_client()
    assert stranger.get(PHOTO_URL).status_code == 403
    with stranger.session_transaction() as state:
        state['admin_ok'] = True
    assert stranger.get(PHOTO_URL).status_code == 403
    for url in (PHOTO_URL+'?original=1', PHOTO_URL+'?trainer_id=t1', '/formateur/etudiants/unknown/photo', '/formateur/etudiants/applicant/photo'):
        assert c.get(url).status_code == 404
    with application.db() as conn:
        conn.execute("INSERT INTO trainers(id,nom,prenom,email,password_hash,created_at,updated_at) VALUES('t2','AUTRE','Alex','other@example.test','test-hash','now','now')")
        conn.execute("INSERT INTO trainer_promotions VALUES('t2','p2')")
    with c.session_transaction() as state:
        state['_trainer_auth']['trainer_id'] = 't2'
        state.modified = True
    assert c.get(PHOTO_URL).status_code == 404
    with c.session_transaction() as state:
        state['_trainer_auth']['expires_at'] = 0
        state.modified = True
    assert c.get(PHOTO_URL).status_code == 403


def test_missing_photo_keeps_initials_and_admin_preview_can_consult_existing_photo(trainer_home):
    c, _ = trainer_home
    assert c.get('/formateur/etudiants/remote/photo').status_code == 404
    with c.session_transaction() as state:
        state.clear()
        state['admin_ok'] = True
    c.get('/admin/formateurs/t1')
    with c.session_transaction() as state:
        token = state['_trainer_csrf']
    assert c.post('/admin/formateurs/t1/espace', data={'csrf_token':token}).status_code == 303
    assert c.get(PHOTO_URL).status_code == 200
