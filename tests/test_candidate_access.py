"""Private candidate return access, tested without any real mail delivery."""
import re
import sqlite3
from pathlib import Path

import pytest
from flask import Flask, url_for

import candidate_access


@pytest.fixture
def access(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    app.secret_key = 'candidate-login-tests-only'
    app.config['TESTING'] = True
    database = tmp_path / 'access.sqlite'

    def db():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    with db() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,email TEXT,date_naissance TEXT,slug_public TEXT,rentree_annee INTEGER,created_at TEXT)')
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?)', ('test-person', 'DUPRÉ', 'camille@example.test', '2000-01-02', 'private-existing-slug', 2027, '2026-12-01'))
    deliveries = []

    def mail(*args):
        deliveries.append(args)
        return True

    @app.get('/espace/<slug>')
    def espace_candidat(slug):
        return 'Private candidate page'

    candidate_access.register_candidate_access(app, db, mail)
    return app.test_client(), db, deliveries


def csrf(client):
    response = client.get('/espace/connexion')
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()


def start(access, **updates):
    client, _, deliveries = access
    fields = dict(nom='Dupré', date_naissance='2000-01-02', email='camille@example.test', csrf_token=csrf(client))
    fields.update(updates)
    response = client.post('/espace/connexion', data=fields)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/espace/verification')
    if deliveries:
        return re.search(r'>(\d{6})<', deliveries[-1][2]).group(1)
    return None


def verify(client, code):
    with client.session_transaction() as state:
        token = state['_candidate_access_csrf']
    return client.post('/espace/verification', data={'csrf_token': token, 'code': code})


def test_real_code_gates_existing_candidate_link_and_is_not_in_cookie(access):
    client, db, deliveries = access
    code = start(access)
    assert deliveries[0][0] == 'camille@example.test'
    with client.session_transaction() as state:
        assert 'code' not in state and 'candidate_id' not in state
    with db() as conn:
        row = conn.execute('SELECT * FROM candidate_access_challenges').fetchone()
        assert row['code_hash'] != code
    wrong = '000000' if code != '000000' else '111111'
    assert verify(client, wrong).status_code == 200
    response = verify(client, code)
    assert response.status_code == 302
    assert response.headers['Location'] == '/espace/private-existing-slug'
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/espace/verification').headers['Location'].endswith('/espace/connexion')


def test_unknown_identity_has_same_generic_response_and_does_not_send(access):
    client, _, deliveries = access
    start(access, nom='SOMEBODY ELSE')
    assert not deliveries
    response = client.get('/espace/verification')
    assert 'Si les informations correspondent'.encode() in response.data
    assert b'private-existing-slug' not in response.data
    assert verify(client, '123456').status_code == 200


def test_wrong_birth_or_email_never_sends(access):
    _, _, deliveries = access
    start(access, date_naissance='2000-01-03')
    start(access, email='other@example.test')
    assert not deliveries


def test_expired_code_does_not_open_dossier(access):
    client, db, _ = access
    code = start(access)
    with db() as conn:
        conn.execute('UPDATE candidate_access_challenges SET expires_at=0')
    response = verify(client, code)
    assert response.status_code == 200
    assert b'private-existing-slug' not in response.data


def test_code_is_disabled_after_five_invalid_attempts(access):
    client, _, _ = access
    code = start(access)
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(5):
        assert verify(client, wrong).status_code == 200
    assert verify(client, code).status_code == 200


def test_request_limit_is_persisted_for_email(access):
    client, db, deliveries = access
    for _ in range(7):
        start(access)
    assert len(deliveries) == 5
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM candidate_access_requests').fetchone()[0] == 5
    assert 'Si les informations correspondent'.encode() in client.get('/espace/verification').data


def test_csrf_is_required_and_get_is_not_an_email_send(access):
    client, _, deliveries = access
    assert client.get('/espace/connexion').status_code == 200
    assert client.post('/espace/connexion', data=dict(nom='DUPRÉ', date_naissance='2000-01-02', email='camille@example.test')).status_code == 400
    assert not deliveries
    start(access)
    assert client.post('/espace/verification', data={'code': '123456'}).status_code == 400


def test_new_request_replaces_prior_code(access):
    client, db, _ = access
    first = start(access)
    second = start(access)
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM candidate_access_challenges WHERE consumed=1').fetchone()[0] == 1
    # Independently validate challenge rotation even in the tiny chance of identical random codes.
    if first != second:
        assert verify(client, first).status_code == 200
    assert verify(client, second).status_code == 302


def test_accents_case_and_surrounding_spaces_match(access):
    client, _, deliveries = access
    code = start(access, nom=' dupre ', email=' CAMILLE@EXAMPLE.TEST ')
    assert len(deliveries) == 1
    assert verify(client, code).status_code == 302


def test_missing_slug_is_generated_only_after_verification(access):
    client, db, _ = access
    with db() as conn:
        conn.execute('UPDATE candidats SET slug_public=NULL')
    code = start(access)
    with db() as conn:
        assert conn.execute('SELECT slug_public FROM candidats').fetchone()[0] is None
    response = verify(client, code)
    assert response.status_code == 302
    with db() as conn:
        slug = conn.execute('SELECT slug_public FROM candidats').fetchone()[0]
        assert len(slug) >= 24
        assert response.headers['Location'].endswith('/espace/' + slug)


def test_most_recent_cohort_used_for_returning_candidate(access):
    client, db, _ = access
    with db() as conn:
        conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?)', ('old-person', 'DUPRÉ', 'camille@example.test', '2000-01-02', 'old-cohort-slug', 2026, '2025-12-01'))
    response = verify(client, start(access))
    assert response.headers['Location'] == '/espace/private-existing-slug'


def test_ip_limit_cannot_be_bypassed_with_forwarded_header(access):
    client, db, deliveries = access
    token = csrf(client)
    for i in range(22):
        response = client.post('/espace/connexion', data=dict(nom='Dupré', date_naissance='2000-01-02', email=f'unknown{i}@example.test', csrf_token=token), headers={'CF-Connecting-IP': f'203.0.113.{i}'}, environ_overrides={'REMOTE_ADDR': '8.8.8.8'})
        assert response.status_code == 302
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM candidate_access_requests').fetchone()[0] == 20
    assert not deliveries


def test_private_reverse_proxy_does_not_throttle_twenty_candidates(access):
    client, db, _ = access
    token = csrf(client)
    for i in range(22):
        response = client.post('/espace/connexion', data=dict(nom='Dupré', date_naissance='2000-01-02', email=f'unknown{i}@example.test', csrf_token=token), environ_overrides={'REMOTE_ADDR': '10.0.0.1'})
        assert response.status_code == 302
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM candidate_access_requests').fetchone()[0] == 22


def test_non_ascii_csrf_is_rejected_cleanly(access):
    client, _, _ = access
    client.get('/espace/connexion')
    assert client.post('/espace/connexion', data={'csrf_token': 'é'}).status_code == 400


def test_insecure_default_secret_fails_closed(access):
    client, _, _ = access
    client.application.secret_key = 'change-me'
    assert client.get('/espace/connexion').status_code == 503
    assert client.post('/espace/verification').status_code == 503
