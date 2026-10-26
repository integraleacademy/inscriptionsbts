"""The existing bearer-link student home must not expose new schedule data."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from flask import Flask, abort, session, url_for
import pytest


@pytest.fixture
def home(tmp_path):
    app = Flask(__name__)
    app.secret_key = 'student-home-isolated-test'
    app.config['TESTING'] = True
    path = tmp_path / 'home.sqlite'
    def db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,slug_public TEXT,statut TEXT,bts TEXT,mode TEXT,commentaires TEXT,fichiers_photo TEXT)')
        conn.execute("INSERT INTO candidats VALUES('student-a','existing-private-link','confirmee','MOS','presentiel','','')")
    app.add_url_rule('/espace/connexion', 'candidate_login', lambda: 'Sign in')
    calls = []
    def today(conn, role, identity):
        calls.append((role, identity))
        return dict(role=role, courses=[dict(title='Cours réservé au bon étudiant')])
    source = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text())
    route = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'espace_candidat')
    namespace = dict(app=app, db=db, abort=abort, url_for=url_for, closing=closing,
                     BTS_LABELS={'MOS': 'Management opérationnel de la sécurité'},
                     parse_list=lambda value: [],
                     get_authenticated_student=lambda *_args, **_kwargs: session.get('test_student'),
                     get_portal_today=today,
                     student_home_summary=lambda conn, identity: {},
                     render_template=lambda _name, **context: json.dumps(context['portal_today']))
    exec(compile(ast.Module(body=[route], type_ignores=[]), '<real-student-home-route>', 'exec'), namespace)
    return app.test_client(), calls


def test_bearer_link_alone_has_login_prompt_without_planning_query(home):
    client, calls = home
    response = client.get('/espace/existing-private-link')
    assert response.status_code == 200
    context = json.loads(response.text)
    assert context['requires_login'] is True
    assert context['planning_url'] == '/espace/connexion'
    assert 'courses' not in context and calls == []
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Cookie' in response.headers['Vary']
    assert response.headers['Referrer-Policy'] == 'no-referrer'


def test_other_current_student_session_cannot_unlock_linked_student_schedule(home):
    client, calls = home
    with client.session_transaction() as state:
        state['test_student'] = {'candidate_id': 'student-b'}
    response = client.get('/espace/existing-private-link')
    assert json.loads(response.text)['requires_login'] is True
    assert calls == []


def test_current_student_home_gets_only_its_own_today_context(home):
    client, calls = home
    with client.session_transaction() as state:
        state['test_student'] = {'candidate_id': 'student-a'}
    response = client.get('/espace/existing-private-link')
    assert calls == [('student', 'student-a')]
    assert json.loads(response.text)['courses'][0]['title'] == 'Cours réservé au bon étudiant'
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_unknown_student_link_remains_not_found(home):
    client, calls = home
    assert client.get('/espace/not-a-student').status_code == 404
    assert calls == []
