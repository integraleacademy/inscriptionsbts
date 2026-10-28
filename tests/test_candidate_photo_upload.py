"""Manual photo upload: validation, ownership, preservation and crop refresh."""
import io
import json
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from test_candidate_editor import editor, application, auth, client, seed, row, make_photo


def photo(format='PNG', color='green'):
    output = io.BytesIO()
    Image.new('RGB', (320, 400), color).save(output, format)
    output.seek(0)
    return output


def send(editor, data=None, cid='editor', headers=True, filename='portrait.png'):
    client, csrf, _ = editor
    return client.post('/admin/candidat/' + cid + '/photo',
                       data={'photo': (data if data is not None else photo(), filename)},
                       headers=csrf if headers else {})


def test_first_photo_is_available_from_the_sheet_and_shared_with_student(editor):
    client, _, deliveries = editor
    page = BeautifulSoup(client.get('/admin/candidat/editor').text, 'html.parser')
    assert page.select_one('#open-photo-upload').get_text() == 'Ajouter une photo'
    assert page.select_one('#candidate-photo-file')['type'] == 'file'
    before, other = row(), row('other')
    response = send(editor, filename='../../unsafe.png')
    assert response.status_code == 200 and response.json['ok']
    assert response.headers['Cache-Control'] == 'private, no-store'
    after = row()
    paths = json.loads(after['fichiers_photo'])
    assert len(paths) == 1
    saved = Path(paths[0])
    assert saved.parent == Path(application.UPLOAD_DIR) / 'editor'
    assert saved.name.startswith('Photo_') and saved.suffix == '.jpg'
    assert Image.open(saved).format == 'JPEG'
    assert Image.open(saved).size == (320, 400)
    for field in ('statut', 'label_carte_etudiante', 'verif_docs', 'fichiers_ci', 'fichiers_cv'):
        assert after[field] == before[field]
    assert row('other') == other and deliveries == []
    for url in ('/admin/candidat/editor/photo', '/espace/editor/photo'):
        reply = client.get(url)
        assert reply.status_code == 200 and reply.mimetype == 'image/jpeg'
    page = BeautifulSoup(client.get('/admin/candidat/editor').text, 'html.parser')
    assert page.select_one('#open-photo-upload').get_text() == 'Remplacer la photo'
    assert not page.select_one('#open-photo-crop').has_attr('hidden')


def test_replacing_photo_preserves_previous_file_and_resets_its_crop(editor):
    client, headers, _ = editor
    original = make_photo()
    original_bytes = original.read_bytes()
    source = client.get('/admin/candidat/editor/photo?original=1').headers['X-Photo-Source']
    crop = dict(x=.15, y=.05, width=.4, height=.5, rotation=0, source_hash=source)
    assert client.post('/admin/candidat/editor/photo-crop', json=crop, headers=headers).status_code == 200
    assert send(editor).status_code == 200
    paths = json.loads(row()['fichiers_photo'])
    assert len(paths) == 2 and Path(paths[1]) == original
    assert original.read_bytes() == original_bytes
    current = client.get('/admin/candidat/editor/photo?original=1')
    assert current.headers['X-Photo-Source'] != source
    assert 'X-Photo-Crop' not in current.headers
    assert client.post('/admin/candidat/editor/photo-crop', json=crop, headers=headers).status_code == 409
    image = Image.open(io.BytesIO(current.data))
    assert image.size == (320, 400)
    assert image.getpixel((100, 100))[1] > 100


@pytest.mark.parametrize('data', [b'not an image', b'%PDF-1.4', b'<svg onload="alert(1)"></svg>', b''])
def test_rejects_invalid_images_without_changing_dossier_or_files(editor, data):
    before = row()
    reply = send(editor, data=io.BytesIO(data))
    assert reply.status_code == 400 and not reply.json['ok']
    assert row() == before
    assert not (Path(application.UPLOAD_DIR) / 'editor').exists()


def test_checks_real_format_and_file_size(editor):
    assert send(editor, data=photo('GIF'), filename='fake.png').status_code == 400
    assert send(editor, data=io.BytesIO(b'x' * (10 * 1024 * 1024 + 1))).status_code == 413
    assert row()['fichiers_photo'] is None


def test_requires_admin_csrf_and_existing_dossier(editor):
    assert send(editor, headers=False).status_code == 400
    assert send(editor, cid='unknown').status_code == 404
    with editor[0].session_transaction() as state:
        state.pop('admin_ok', None)
    assert send(editor).status_code == 403
    assert row()['fichiers_photo'] is None


def test_cannot_write_through_a_symlink_to_another_dossier(editor, tmp_path):
    root = Path(application.UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / 'another-dossier'
    outside.mkdir()
    (root / 'editor').symlink_to(outside, target_is_directory=True)
    assert send(editor).status_code == 404
    assert list(outside.iterdir()) == [] and row()['fichiers_photo'] is None


def test_phone_photo_orientation_is_applied(editor):
    image = Image.new('RGB', (400, 320), 'blue')
    exif = Image.Exif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, 'JPEG', exif=exif)
    output.seek(0)
    assert send(editor, data=output, filename='phone.jpg').status_code == 200
    saved = Image.open(json.loads(row()['fichiers_photo'])[0])
    assert saved.size == (320, 400) and not saved.getexif()
