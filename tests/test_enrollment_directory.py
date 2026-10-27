"""The filtered directory and its KPIs use verified WEDOF links and portraits."""
import hashlib
import io
import json
from pathlib import Path
import re
import time

from PIL import Image
import pytest

from test_admissions_2027 import application, auth, client, seed
from test_campus_workspace import campus
from wedof_contracts import discovery_fingerprint


def kpis(html):
    return {key: int(value) for key, value in re.findall(r'data-kpi="([^"]+)">(\d+)', html)}


@pytest.fixture
def directory(campus, monkeypatch):
    client, _, _ = campus
    monkeypatch.setenv('WEDOF_API_KEY', 'synthetic-key-never-sent')
    monkeypatch.setattr('wedof_contracts.requests.get', lambda *a, **kw: pytest.fail('A directory GET must not call WEDOF'))
    seed(2027, 'unknown')
    seed(2026, 'pending-contract')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET bts='MOS' WHERE id IN ('unknown','pending-contract')")
        conn.execute("UPDATE candidats SET label_carte_etudiante=1 WHERE id='remote'")
        for contract_id, state in [('new', 'pendingAcceptation'), ('old', 'broken')]:
            conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)',
                         (contract_id, 'pending-contract', json.dumps({'state': state}), 1, 'now'))
        row = dict(conn.execute("SELECT * FROM candidats WHERE id='onsite'").fetchone())
        fingerprint = discovery_fingerprint(row, hashlib.sha256(b'synthetic-key-never-sent').hexdigest())
        conn.execute('INSERT INTO student_wedof_discovery VALUES(?,?,?,?)',
                     ('onsite', fingerprint, json.dumps({'step': 'done', 'items': [], 'not_found': True, 'incomplete': False}), time.time()))
    return client


@pytest.mark.parametrize('query,expected', [
    ('', (4, 2, 1, 1, 2, 1)),
    ('mode=distanciel', (1, 1, 0, 0, 0, 1)),
    ('bts=MOS', (2, 1, 0, 1, 2, 0)),
    ('promotion=none', (2, 1, 0, 1, 2, 0)),
    ('promotion=p1', (2, 1, 1, 0, 0, 1)),
    ('contract=yes', (2, 2, 0, 0, 1, 1)),
    ('contract=no', (1, 0, 1, 0, 0, 0)),
    ('contract=linked', (1, 0, 0, 1, 1, 0)),
    ('rentree=2027', (1, 0, 0, 1, 1, 0)),
    ('q=pending-contract', (1, 1, 0, 0, 1, 0)),
    ('carte_etudiante_manquante=1', (3, 1, 1, 1, 2, 0)),
    ('bts=MOS&rentree=2026&contract=yes&mode=presentiel&promotion=none', (1, 1, 0, 0, 1, 0)),
    ('bts=MOS&mode=distanciel', (0, 0, 0, 0, 0, 0)),
])
def test_every_kpi_matches_all_filters_and_async_refresh(directory, query, expected):
    page = directory.get('/admin/inscriptions?' + query)
    assert page.status_code == 200
    names = ('total', 'with_contract', 'without_contract', 'unverified', 'unassigned', 'remote')
    assert kpis(page.text) == dict(zip(names, expected))
    assert expected[0] == sum(expected[1:4])
    data = directory.get('/admin/inscriptions/donnees?' + query)
    assert data.status_code == 200 and data.headers['Cache-Control'] == 'private, no-store'
    assert kpis(data.json['stats_html']) == kpis(page.text)
    assert len(re.findall('data-enrollment-id=', data.json['rows_html'])) == expected[0]
    assert 'synthetic-key' not in data.text and 'date_naissance' not in data.text


def test_discovery_scope_uses_other_filters_before_contract_filter(directory):
    data = directory.get('/admin/inscriptions/donnees?rentree=2027&contract=yes').json
    assert data['discovery'] == ['unknown']
    assert kpis(data['stats_html'])['total'] == 0
    assert directory.get('/admin/inscriptions/donnees?rentree=2026').json['discovery'] == []


def test_a_link_appears_immediately_and_multiple_contracts_count_one_student(directory):
    assert kpis(directory.get('/admin/inscriptions').text)['with_contract'] == 2
    with application.db() as conn:
        conn.execute('INSERT INTO student_wedof_contracts(contract_id,candidate_id,payload,checked_at,linked_at) VALUES(?,?,?,?,?)',
                     ('found', 'unknown', json.dumps({'state': 'accepted'}), time.time(), 'now'))
    data = directory.get('/admin/inscriptions/donnees?contract=yes').json
    assert kpis(data['stats_html'])['with_contract'] == 3
    assert 'data-enrollment-id="unknown"' in data['rows_html']
    assert 'En instruction' in data['rows_html'] and 'Rompu' in data['rows_html']
    assert not data['discovery']


def test_uploaded_photo_uses_existing_private_cropped_portrait(directory):
    folder = Path(application.UPLOAD_DIR) / 'onsite'
    folder.mkdir(parents=True)
    Image.new('RGB', (80, 100), '#416f89').save(folder / 'portrait.png')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET fichiers_photo=? WHERE id='onsite'", (json.dumps(['portrait.png']),))
    page = directory.get('/admin/inscriptions?q=onsite').text
    assert 'src="/admin/candidat/onsite/photo"' in page and 'data-student-photo' in page
    response = directory.get('/admin/candidat/onsite/photo')
    assert response.status_code == 200 and response.mimetype == 'image/jpeg'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert Image.open(io.BytesIO(response.data)).size == (80, 100)
    assert 'data-student-photo' not in directory.get('/admin/inscriptions?q=remote').text


@pytest.mark.parametrize('stored', ['invalid-json', '{}', '[null, 1]', 'null'])
def test_invalid_photo_metadata_keeps_initials(directory, stored):
    with application.db() as conn:
        conn.execute("UPDATE candidats SET fichiers_photo=? WHERE id='onsite'", (stored,))
    page = directory.get('/admin/inscriptions?q=onsite')
    assert page.status_code == 200 and 'data-student-photo' not in page.text


def test_directory_data_and_portraits_remain_admin_only(directory):
    anonymous = application.app.test_client()
    for route in ['/admin/inscriptions', '/admin/inscriptions/donnees']:
        assert anonymous.get(route).status_code == 302
    assert anonymous.get('/admin/candidat/onsite/photo').status_code == 403
