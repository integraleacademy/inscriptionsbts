"""The admin button opens the student's real pages, without borrowing a login."""
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest
from werkzeug.security import generate_password_hash

from candidate_access import _schema as ensure_account_schema
from student_workspace import ensure_workspace_schema
from test_admissions_2027 import application, auth, client, seed


def page(response):
    assert response.status_code == 200, response.status
    return BeautifulSoup(response.data, 'html.parser')


def open_from_sheet(client, cid):
    sheet = page(client.get(f'/admin/candidat/{cid}?return_to=/admin/inscriptions'))
    button = next(a for a in sheet.select('a[href]') if a.get_text(strip=True) == 'Espace étudiant')
    return client.get(button['href'], follow_redirects=True)


@pytest.fixture
def school(client, monkeypatch):
    monkeypatch.setattr(application.app, 'secret_key', 'student-preview-tests-only')
    seed(2026, 'alice')
    seed(2026, 'bob')
    with application.db() as conn:
        conn.execute("UPDATE candidats SET prenom='Alice',nom='Durand',date_naissance='2005-01-02' WHERE id='alice'")
        conn.execute("UPDATE candidats SET prenom='Bob',nom='Martin',date_naissance='2005-03-04' WHERE id='bob'")
        ensure_workspace_schema(conn)
        for cid in ('alice', 'bob'):
            conn.execute('INSERT INTO companies(id,name,contact,email,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (cid, 'Entreprise ' + cid, 'Tuteur', cid + '@entreprise.test', 'now', 'now'))
            conn.execute('INSERT INTO company_students VALUES(?,?,?,?,?,?)', (cid, cid, '2026-10-01', None, 'Tuteur', 'now'))
            conn.execute("INSERT INTO student_attendance VALUES(?,?, '2026-10-05',540,600,'absence','pending',1,0,'now','now')",
                         (f'absence-{cid}', cid))
    return client


def test_first_login_not_needed_and_two_open_tabs_stay_on_their_dossiers(school):
    auth(school)
    with application.db() as conn:
        conn.execute("UPDATE candidats SET slug_public=NULL WHERE id='alice'")
    a = open_from_sheet(school, 'alice')
    home = page(a)
    assert 'Bonjour Alice' in home.h1.get_text() and 'Ton planning' in home.get_text()
    assert home.select_one('.academy-header-actions').get_text(strip=True) == 'Consultation · Alice DURAND'
    assert home.select_one('.student-portal-nav a[aria-current="page"]')['href'] == a.request.path
    assert home.select_one('.student-portal-nav a[href="/admin/candidat/alice"]')
    tabs = [anchor['href'] for anchor in home.select('.student-portal-nav a') if '/admin/' not in anchor['href']]
    assert len(tabs) == 8
    assert 'Bonjour Bob' in page(open_from_sheet(school, 'bob')).h1.get_text()
    for url in tabs:
        response = school.get(url)
        section = page(response)
        active = section.select_one('.student-portal-nav a[aria-current="page"]')
        assert active and active['href'] == url, url
        assert 'Bob MARTIN' not in section.get_text()
        assert response.headers['Cache-Control'] == 'private, no-store'
        for element in section.select('a[href], form[action], [data-planning-sync-url]'):
            href = element.get('href') or element.get('action') or element.get('data-planning-sync-url')
            assert not urlsplit(href).path.startswith(('/espace/', '/planning/sync')), (url, href)
    docs = page(school.get(tabs[1]))
    assert 'Alice DURAND' in docs.get_text()
    certificate = school.get(docs.select_one('a[href*="certificat-scolarite.pdf"]')['href'])
    assert certificate.status_code == 200 and certificate.mimetype == 'application/pdf'
    company = page(school.get(tabs[6])).get_text()
    assert 'Entreprise alice' in company and 'Entreprise bob' not in company
    absences = page(school.get(tabs[5]))
    detail_url = absences.select_one('a[href$="absence-alice"]')['href']
    assert not absences.select_one('a[href$="absence-bob"]')
    assert page(school.get(detail_url)).select_one('form fieldset[disabled]')
    assert school.get(detail_url.replace('absence-alice', 'absence-bob')).status_code == 404
    assert school.post(detail_url).status_code == 405
    assert school.post(tabs[7]).status_code == 405
    assert school.get(tabs[2] + '/mois?month=1&year=2027').location == tabs[2] + '?date=2027-01-01'
    sync = home.body['data-planning-sync-url']
    assert school.get(sync).get_json()['revision']
    assert school.get(sync.replace('student','admin').replace('today','admin')).status_code == 403
    with school.session_transaction() as state:
        assert state['admin_ok'] and '_student_auth' not in state
    with application.db() as conn:
        assert conn.execute("SELECT slug_public FROM candidats WHERE id='alice'").fetchone()[0] is None
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='student_accounts'").fetchone()
    school.get('/logout')
    for url in [a.request.path, *tabs, sync]:
        assert school.get(url).status_code == 403


def test_preview_matches_a_login_and_preserves_existing_student_session(school):
    password = 'Mon mot de passe personnel'
    with application.db() as conn:
        ensure_account_schema(conn)
        conn.execute("INSERT INTO student_accounts VALUES('account',?,0,1,0,0)", (generate_password_hash(password),))
        conn.execute("INSERT INTO student_account_members VALUES('alice','account')")
    student = application.app.test_client()
    login = page(student.get('/espace/connexion'))
    assert student.post('/espace/connexion', data=dict(nom='Durand', password=password,
                        csrf_token=login.select_one('[name=csrf_token]')['value'])).location == '/espace/mon-dossier'
    actual = page(student.get('/espace/mon-dossier', follow_redirects=True))
    assert student.get('/admin/candidat/alice/espace').status_code == 403
    with student.session_transaction() as state:
        original_identity = state['_student_auth'].copy()
    auth(student)
    preview = page(open_from_sheet(student, 'alice'))
    assert preview.select_one('.candidate-portal').get_text(strip=True) == actual.select_one('.candidate-portal').get_text(strip=True)
    assert 'Bonjour Bob' in page(open_from_sheet(student, 'bob')).h1.get_text()
    assert 'Bonjour Alice' in page(student.get('/espace/mon-dossier', follow_redirects=True)).h1.get_text()
    with student.session_transaction() as state:
        assert state['_student_auth'] == original_identity
    with application.db() as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='account'")
    assert student.get('/espace/mon-dossier').location == '/espace/mot-de-passe'
    assert 'Bonjour Alice' in page(open_from_sheet(student, 'alice')).h1.get_text()
    with application.db() as conn:
        account = conn.execute("SELECT must_change,version FROM student_accounts WHERE id='account'").fetchone()
        assert tuple(account) == (1, 1)
    assert not page(application.app.test_client().get('/espace/bob')).select_one('.student-portal-nav')
    assert student.get('/admin/candidat/unknown/espace', follow_redirects=True).status_code == 404
