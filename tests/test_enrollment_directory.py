"""The filtered directory and its KPIs use verified WEDOF links and portraits."""
import hashlib
from html import unescape
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import url_for
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


@pytest.mark.parametrize('cid', ['onsite', 'remote'])
def test_return_from_enrolled_student_sheet_opens_directory(directory, cid):
    sheet = directory.get('/admin/candidat/' + cid)
    assert sheet.status_code == 200
    back_url = re.search(r'class="sheet-back" href="([^"]+)"', sheet.text).group(1)
    assert back_url == '/admin/inscriptions'
    page = directory.get(back_url)
    assert page.status_code == 200 and page.mimetype == 'text/html'
    assert 'data-enrollments' in page.text and 'js/campus.js' in page.text
    with application.app.test_request_context():
        assert url_for('admin_enrollments') == '/admin/inscriptions'
        assert url_for('admin_enrollments_data') == '/admin/inscriptions/donnees'


@pytest.mark.parametrize('headers', [
    {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'},
    {'Sec-Fetch-Mode': 'navigate', 'Accept': '*/*'},
])
@pytest.mark.parametrize('query', ['', '?mode=distanciel&rentree=2026&q=Camille+TEST&contract=yes'])
def test_browser_navigation_to_data_returns_directory_with_filters(directory, headers, query):
    response = directory.get('/admin/inscriptions/donnees' + query, headers=headers)
    assert response.status_code == 302
    assert response.headers['Cache-Control'] == 'private, no-store'
    destination = urlsplit(response.headers['Location'])
    assert destination.path == '/admin/inscriptions'
    assert parse_qs(destination.query) == parse_qs(query.lstrip('?'))
    page = directory.get(response.headers['Location'], headers=headers)
    assert page.status_code == 200 and page.mimetype == 'text/html'
    assert 'data-enrollments' in page.text


@pytest.mark.parametrize('accept', ['*/*', 'application/json'])
def test_background_data_refresh_still_returns_json(directory, accept):
    response = directory.get('/admin/inscriptions/donnees?mode=distanciel',
                             headers={'Accept': accept, 'Sec-Fetch-Mode': 'cors'})
    assert response.status_code == 200 and response.mimetype == 'application/json'
    assert response.json['ok']
    assert kpis(response.json['stats_html'])['total'] == 1
    assert 'data-enrollment-id="remote"' in response.json['rows_html']


def test_anonymous_browser_cannot_open_data_or_directory(directory):
    anonymous = application.app.test_client()
    for route in ['/admin/inscriptions', '/admin/inscriptions/donnees']:
        response = anonymous.get(route, headers={'Accept': 'text/html', 'Sec-Fetch-Mode': 'navigate'})
        assert response.status_code == 302 and response.headers['Location'] == '/login'


@pytest.mark.parametrize('source', ['/admin/inscriptions', '/admin/inscriptions/donnees'])
def test_filtered_directory_survives_photo_change_and_sheet_reload(directory, source):
    with application.db() as conn:
        conn.execute("UPDATE candidats SET nom=? WHERE id='onsite'", ('Élise & Dupont',))
    filters = dict(q='Élise & Dupont', bts='MCO', mode='presentiel', promotion='p1',
                   contract='linked', rentree='2026', carte_etudiante_manquante='1')
    response = directory.get(source + '?' + urlencode(filters))
    html = response.json['rows_html'] if response.is_json else response.text
    links = [unescape(link) for link in re.findall(r'href="([^"]+)"', html)
             if urlsplit(unescape(link)).path == '/admin/candidat/onsite']
    assert len(links) == 3
    assert [urlsplit(link).fragment for link in links] == ['', 'contrat-apprentissage', '']
    for link in links:
        sheet = directory.get(link)
        back = unescape(re.search(r'class="sheet-back" href="([^"]+)"', sheet.text).group(1))
        assert urlsplit(back).path == '/admin/inscriptions'
        assert parse_qs(urlsplit(back).query) == {name: [value] for name, value in filters.items()}
    with directory.session_transaction() as state:
        headers = {'X-CSRF-Token': state['_candidate_message_csrf']}
    portrait = io.BytesIO()
    Image.new('RGB', (80, 100), '#416f89').save(portrait, 'PNG')
    portrait.seek(0)
    upload = directory.post('/admin/candidat/onsite/photo',
                            data={'photo': (portrait, 'portrait.png')}, headers=headers)
    assert upload.status_code == 200 and upload.json['ok']
    reloaded = directory.get(links[0])
    back = unescape(re.search(r'class="sheet-back" href="([^"]+)"', reloaded.text).group(1))
    sidebar = unescape(re.search(r'href="([^"]+)" title="Inscriptions"', reloaded.text).group(1))
    assert sidebar == back
    assert parse_qs(urlsplit(back).query) == {name: [value] for name, value in filters.items()}
    returned = directory.get(back)
    assert re.findall(r'data-enrollment-id="([^"]+)"', returned.text) == ['onsite']
    assert 'data-student-photo' in returned.text
    reset = unescape(re.search(r'href="([^"]+)">Réinitialiser</a>', returned.text).group(1))
    assert reset == '/admin/inscriptions'
    assert kpis(directory.get(reset).text)['total'] == 4


def test_two_filtered_tabs_keep_independent_return_links(directory):
    destinations = ['/admin/inscriptions?bts=MCO', '/admin/inscriptions?bts=MOS&promotion=none']
    sheets = []
    for destination in destinations:
        page = directory.get(destination)
        sheets.append(unescape(re.search(r'class="campus-person" href="([^"]+)"', page.text).group(1)))
    for sheet_url, destination in zip(sheets, destinations):
        # Reload the first sheet after another filtered list has been opened.
        page = directory.get(sheet_url)
        back = unescape(re.search(r'class="sheet-back" href="([^"]+)"', page.text).group(1))
        assert back == destination


@pytest.mark.parametrize('return_to', [
    'https://outside.example/admin/inscriptions?bts=MOS',
    '//outside.example/admin/inscriptions?bts=MOS',
    'javascript:alert(1)', '/admin/inscriptions/donnees?bts=MOS', '/admin/delete/onsite',
    'http://[invalid',
])
def test_sheet_rejects_unsafe_return_destinations(directory, return_to):
    page = directory.get('/admin/candidat/onsite?' + urlencode({'return_to': return_to}))
    assert page.status_code == 200
    assert 'class="sheet-back" href="/admin/inscriptions"' in page.text
