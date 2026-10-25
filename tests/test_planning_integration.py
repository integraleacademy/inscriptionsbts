"""Planning cannot be invalidated through the existing promotion/trainer editors."""
from pathlib import Path
import sqlite3

from flask import Flask, session
import pytest

from planning import register_planning, ensure_planning_schema
from promotions import register_promotions
from trainer_access import register_trainer_access, _schema


@pytest.fixture
def connected(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    app.secret_key = 'planning-integration-fixture-only'
    app.config['TESTING'] = True
    app.jinja_env.filters['dmy'] = lambda value: str(value or '')
    path = tmp_path / 'planning.sqlite'

    def db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,mode TEXT,email TEXT,tel TEXT,numero_dossier TEXT,rentree_annee INTEGER,statut TEXT)')
        _schema(conn)
        ensure_planning_schema(conn)
        conn.execute("INSERT INTO promotions VALUES('demo','BTS MOS · première année','MOS',1,2026,'2026-09-01','2027-08-31',1,0,'now','now')")
        conn.execute("INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES('trainer','EXEMPLE','Alex','alex@example.test','now','now')")
        conn.execute("INSERT INTO trainer_promotions VALUES('trainer','demo')")
    guard = lambda: session.get('admin_ok', False)
    register_promotions(app, db, guard)
    register_trainer_access(app, db, lambda *args, **kwargs: pytest.fail('Unexpected e-mail'), guard)
    register_planning(app, db, guard)
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin_ok'] = True
    page = client.get('/admin/planning?promotion_id=demo')
    assert page.status_code == 200
    assert 'js/planning.js' in page.text and 'css/planning.css' in page.text
    with client.session_transaction() as state:
        planning_token = state['_planning_csrf']
        promotion_token = state['_promotion_csrf']
        trainer_token = state['_trainer_csrf']
    headers = {'X-CSRF-Token': planning_token}
    rule = client.post('/admin/planning/api/calendar/rules', headers=headers, json={
        'promotion_id': 'demo', 'start_date': '2026-09-01', 'end_date': '2027-08-31',
        'weekdays': [0, 1, 2, 3, 4], 'kind': 'school', 'label': 'École'})
    assert rule.status_code == 200, rule.text
    subject = client.post('/admin/planning/api/subjects', headers=headers, json={
        'promotion_id': 'demo', 'trainer_id': 'trainer', 'name': 'Culture générale', 'planned_hours': 50})
    assert subject.status_code == 200, subject.text
    course = client.post('/admin/planning/api/courses', headers=headers, json={
        'promotion_id': 'demo', 'subject_id': subject.json['subject']['id'],
        'date': '2027-01-04', 'start': '08:30', 'end': '10:30'})
    assert course.status_code == 200, course.text
    return client, db, promotion_token, trainer_token


def test_promotion_dates_cannot_leave_existing_calendar_or_course_outside(connected):
    client, db, promotion_token, _ = connected
    response = client.post('/admin/promotions/demo/update', headers={'X-CSRF-Token': promotion_token}, json={
        'nom': 'BTS MOS · première année', 'bts': 'MOS', 'niveau': 1, 'rentree_annee': 2026,
        'date_debut': '2026-09-01', 'date_fin': '2026-12-31'})
    assert response.status_code == 409
    assert response.json['conflicts']
    with db() as conn:
        assert conn.execute("SELECT date_fin FROM promotions WHERE id='demo'").fetchone()[0] == '2027-08-31'
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0] == 1


def test_trainer_assignment_cannot_be_removed_while_it_is_used(connected):
    client, db, _, trainer_token = connected
    response = client.post('/admin/formateurs/trainer/update', headers={'X-CSRF-Token': trainer_token}, json={
        'nom': 'EXEMPLE', 'prenom': 'Alex', 'email': 'alex@example.test', 'assignments': []})
    assert response.status_code == 409
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trainer_promotions WHERE trainer_id='trainer'").fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM planning_subjects').fetchone()[0] == 1


def test_non_admin_roles_cannot_read_admin_planning_or_private_pdf(connected):
    client, _, _, _ = connected
    with client.session_transaction() as state:
        state.pop('admin_ok')
        state['_trainer_auth'] = {'trainer_id': 'trainer'}
    for url in ('/admin/planning', '/admin/matieres', '/admin/salles', '/admin/planning/api/catalog', '/admin/planning/api/state?promotion_id=demo',
                '/admin/planning/export.pdf?promotion_id=demo&start=2027-01-04&end=2027-01-10'):
        assert client.get(url).status_code == 403


def test_planning_catalog_pages_share_admin_navigation_and_secure_assets(connected):
    client, _, _, _ = connected
    for path in ('/admin/matieres', '/admin/salles'):
        page = client.get(path)
        assert page.status_code == 200
        assert ('js/subject-catalog.js' if path == '/admin/matieres' else 'js/planning-catalog.js') in page.text
        assert 'css/planning-catalog.css' in page.text
        assert 'js/main_admin.js' not in page.text
        assert 'googletagmanager.com' not in page.text
        assert '/static/logo-integrale.png?v=2' in page.text
        assert 'href="/admin/matieres"' in page.text
        assert 'href="/admin/salles"' in page.text
        assert page.headers['Cache-Control'] == 'no-store'


def test_settings_page_moves_secret_form_out_of_importer(connected):
    client, _, _, _ = connected
    page = client.get('/admin/parametres')
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    assert 'id="openai-key"' in page.text and 'data-csrf="' in page.text
    assert 'href="/admin/parametres" title="Paramètres" class="active"' in page.text
    for unwanted in ('googletagmanager.com', 'brevo.com', 'js/main_front.js', 'js/main_admin.js', 'Pôle Alternance'):
        assert unwanted not in page.text
    subjects = client.get('/admin/matieres').text
    assert 'reference-settings-link' in subjects
    assert 'id="reference-key"' not in subjects and 'id="reference-settings"' not in subjects
    with client.session_transaction() as state:
        state.clear()
    assert client.get('/admin/parametres').status_code == 403
