"""Independent identity-scope checks for student and trainer schedules."""
from datetime import datetime, timezone
from io import BytesIO
import json
import sqlite3
import time
from zoneinfo import ZoneInfo

from flask import Flask
from jinja2 import DictLoader
import pytest
from pypdf import PdfReader

import candidate_access
import planning
import planning_portal
import trainer_access


@pytest.fixture
def portal_db(tmp_path):
    path = tmp_path / 'portal-scope.sqlite'

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        conn.execute('''CREATE TABLE candidats(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,bts TEXT,
            rentree_annee INTEGER,statut TEXT,slug_public TEXT,email TEXT,tel TEXT,num_secu TEXT,date_naissance TEXT)''')
        trainer_access._schema(conn)
        candidate_access._schema(conn)
        planning.ensure_planning_schema(conn)
        for pid, active in [('p1', 1), ('p2', 1), ('p3', 0)]:
            conn.execute('''INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,active,created_at,updated_at)
                VALUES(?,?,?,1,2026,'2026-09-01','2027-08-31',?,'fixture','fixture')''',
                (pid, {'p1': 'PROMOTION LOCALE', 'p2': 'PROMOTION AUTRE', 'p3': 'PROMOTION ARCHIVEE'}[pid], 'MCO', active))
        for tid in ('t1', 't2'):
            conn.execute('''INSERT INTO trainers(id,nom,prenom,email,password_hash,active,version,created_at,updated_at)
                VALUES(?,?,?,?,?,1,1,'fixture','fixture')''', (tid, 'FORMATEUR ' + tid, 'Camille', 'secret-' + tid + '@example.test', 'fixture-not-a-real-hash'))
            for pid in ('p1', 'p2', 'p3'):
                conn.execute('INSERT INTO trainer_promotions VALUES(?,?)', (tid, pid))
        conn.execute("INSERT INTO planning_rooms VALUES('r1','Salle locale',1)")
        for sid, pid, tid, name in [
            ('s1', 'p1', 't1', 'MATIERE LOCALE'), ('s2', 'p2', 't2', 'MATIERE AUTRE'),
            ('s3', 'p1', 't2', 'MATIERE COLLEGUE'), ('s4', 'p3', 't1', 'MATIERE ARCHIVEE'),
        ]:
            conn.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,30)', (sid, pid, name, tid, '#626b4e'))
        people = [
            ('c1', 'p1', 'confirmee', 'MCO', 2026), ('c2', 'p2', 'reconfirmee', 'MCO', 2026),
            ('c3', 'p1', 'preinscription', 'MCO', 2026), ('c4', 'p1', 'annulee', 'MCO', 2026),
            ('c5', 'p1', 'rentree', 'MCO', 2026), ('c6', 'p1', 'confirmee', 'MOS', 2026),
            ('c7', 'p1', 'confirmee', 'MCO', 2027), ('c8', 'p3', 'confirmee', 'MCO', 2026),
        ]
        for cid, pid, status, bts, year in people:
            conn.execute('INSERT INTO candidats VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (cid, 'ETUDIANT ' + cid, 'Alex', bts, year, status, 'secret-bearer-' + cid,
                 'secret-' + cid + '@example.test', '0600000000', 'secret-social-number', '1999-09-09'))
            conn.execute("INSERT INTO student_promotions VALUES(?,?,'fixture')", (cid, pid))
            conn.execute("INSERT INTO student_accounts VALUES(?,?,0,1,0,0)", ('account-' + cid, 'fixture-not-a-real-hash'))
            conn.execute('INSERT INTO student_account_members VALUES(?,?)', (cid, 'account-' + cid))
        lessons = [
            ('own', 'p1', 's1', 't1', '2027-01-04', 540, 660),
            ('colleague', 'p1', 's3', 't2', '2027-01-04', 660, 720),
            ('foreign', 'p2', 's2', 't2', '2027-01-04', 780, 840),
            ('shared', 'p1', 's1', 't1', '2027-01-05', 540, 660),
            ('future', 'p1', 's1', 't1', '2027-02-01', 540, 600),
            ('archived', 'p3', 's4', 't1', '2027-01-04', 900, 960),
        ]
        for lid, pid, sid, tid, day, start, end in lessons:
            conn.execute('''INSERT INTO planning_courses(id,promotion_id,subject_id,trainer_id,room_id,date,start_min,end_min,title,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,'fixture','fixture')''', (lid, pid, sid, tid, 'r1', day, start, end, 'Cours ' + lid))
            conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)', (lid, pid, sid))
        conn.execute("INSERT INTO planning_course_groups VALUES('shared','p2','s2')")
    return connect


@pytest.fixture
def portal_app(portal_db):
    app = Flask(__name__)
    app.secret_key = 'independent-portal-fixture-only'
    app.config['TESTING'] = True
    app.jinja_loader = DictLoader({'portal_planning.html': '{{ portal_planning|tojson }}'})
    app.add_url_rule('/formateur/connexion', 'trainer_login', lambda: 'Connexion formateur')
    app.add_url_rule('/espace/connexion', 'candidate_login', lambda: 'Connexion étudiant')
    app.add_url_rule('/espace/mot-de-passe', 'student_change_password', lambda: 'Changer le mot de passe')
    planning_portal.register_planning_portal(app, portal_db)
    return app


def logged(app, role='student', identity='c1', **updates):
    client = app.test_client()
    if role == 'student':
        auth = dict(account_id='account-' + identity, candidate_id=identity, version=1, expires_at=time.time() + 3600)
        key = '_student_auth'
    else:
        auth = dict(trainer_id=identity, version=1, expires_at=time.time() + 3600)
        key = '_trainer_auth'
    auth.update(updates)
    with client.session_transaction() as state:
        state[key] = auth
    return client


def week(db, role='student', identity='c1', day='2027-01-04'):
    with db() as conn:
        return planning_portal.get_portal_week(conn, role, identity, day)


def ids(snapshot):
    return {item['id'] for item in snapshot['courses']}


def test_student_only_sees_current_promotion_including_teachers_and_shared_course(portal_db):
    local = week(portal_db)
    other = week(portal_db, identity='c2')
    assert ids(local) == {'own', 'colleague', 'shared'}
    assert ids(other) == {'foreign', 'shared'}
    shared = next(item for item in other['courses'] if item['id'] == 'shared')
    assert shared['subject_name'] == 'MATIERE AUTRE'
    assert {g['promotion_id'] for g in shared['groups']} == {'p2'}
    assert shared['promotion_names'] == ['PROMOTION AUTRE']


def test_trainer_only_sees_actual_teaching_assignments_not_colleagues(portal_db):
    assert ids(week(portal_db, 'trainer', 't1')) == {'own', 'shared'}
    assert ids(week(portal_db, 'trainer', 't2')) == {'colleague', 'foreign'}


def test_revoked_primary_group_is_removed_without_leaking_its_subject_or_name(portal_db):
    with portal_db() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    result = week(portal_db, 'trainer', 't1')
    assert ids(result) == {'shared'}
    serialized = json.dumps(result, ensure_ascii=False)
    assert 'PROMOTION LOCALE' not in serialized
    assert 'MATIERE LOCALE' not in serialized
    assert result['courses'][0]['subject_name'] == 'MATIERE AUTRE'


@pytest.mark.parametrize('identity', ['c3', 'c4', 'c6', 'c7', 'c8', 'missing'])
def test_unconfirmed_cancelled_mismatched_and_inactive_students_have_no_scope(portal_db, identity):
    result = week(portal_db, identity=identity)
    assert result['courses'] == [] and result['promotions'] == []


def test_rentree_status_and_reassignment_rebuild_scope_from_database(portal_db):
    assert ids(week(portal_db, identity='c5')) == {'own', 'colleague', 'shared'}
    with portal_db() as conn:
        conn.execute("UPDATE student_promotions SET promotion_id='p2' WHERE candidate_id='c1'")
    assert ids(week(portal_db)) == {'foreign', 'shared'}


def test_schedule_dto_never_exposes_roster_contact_bearer_or_budget_data(portal_db):
    for role, identity in [('student', 'c1'), ('student', 'c2'), ('trainer', 't1')]:
        result = week(portal_db, role, identity)
        serialized = json.dumps(result)
        for secret in ('secret-', '0600000000', '1999-09-09', 'planned_hours', 'num_secu', 'account-', 'password_hash', 'email', 'tel'):
            assert secret not in serialized
        for item in result['courses']:
            assert 'trainer_id' not in item and 'candidate_id' not in item and 'room_id' not in item


@pytest.mark.parametrize('path', ['/espace/planning', '/formateur/planning', '/espace/planning.pdf', '/formateur/planning.pdf'])
def test_no_schedule_or_pdf_without_role_login_even_with_bearer_query(portal_app, path):
    response = portal_app.test_client().get(path + '?slug=secret-bearer-c1&candidate_id=c1')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/connexion')
    assert 'private' in response.headers['Cache-Control'] and 'no-store' in response.headers['Cache-Control']


@pytest.mark.parametrize('role,identity,path', [('student', 'c1', '/espace/planning'), ('trainer', 't1', '/formateur/planning')])
def test_identity_query_parameters_cannot_widen_schedule(portal_app, role, identity, path):
    client = logged(portal_app, role, identity)
    for parameter in ('promotion_id=p2', 'candidate_id=c2', 'trainer_id=t2', 'slug=secret-bearer-c2', 'date=2027-01-05&date=2027-01-06'):
        response = client.get(path + '?date=2027-01-04&' + parameter)
        assert response.status_code == 400
        assert 'Cours foreign' not in response.text
    safe = client.get(path + '?date=2027-01-04')
    assert safe.status_code == 200
    assert 'Cookie' in safe.headers['Vary']
    assert 'private' in safe.headers['Cache-Control'] and 'no-store' in safe.headers['Cache-Control']
    assert safe.headers['Referrer-Policy'] == 'no-referrer'
    assert safe.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize('date_value', ['not-a-date', '2027-02-30', '0001-01-01', '9999-12-31'])
def test_bad_and_extreme_date_filters_return_400_not_500(portal_app, date_value):
    response = logged(portal_app).get('/espace/planning', query_string={'date': date_value})
    assert response.status_code == 400


def test_student_session_version_expiry_and_initial_password_are_enforced(portal_app, portal_db):
    assert logged(portal_app, version=999).get('/espace/planning').status_code == 302
    assert logged(portal_app, expires_at=time.time() - 1).get('/espace/planning').status_code == 302
    with portal_db() as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='account-c1'")
    response = logged(portal_app).get('/espace/planning')
    assert response.status_code == 302 and response.headers['Location'] == '/espace/mot-de-passe'


def test_trainer_disable_version_expiry_and_grant_revocation_take_effect_immediately(portal_app, portal_db):
    assert logged(portal_app, 'trainer', 't1', version=999).get('/formateur/planning').status_code == 302
    assert logged(portal_app, 'trainer', 't1', expires_at=time.time() - 1).get('/formateur/planning').status_code == 302
    client = logged(portal_app, 'trainer', 't1')
    with portal_db() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1'")
    response = client.get('/formateur/planning?date=2027-01-04')
    assert response.status_code == 200 and not json.loads(response.text)['courses']
    with portal_db() as conn:
        conn.execute("UPDATE trainers SET active=0 WHERE id='t1'")
    assert client.get('/formateur/planning').status_code == 302


def test_other_role_session_does_not_grant_access(portal_app):
    assert logged(portal_app, 'trainer', 't1').get('/espace/planning').status_code == 302
    assert logged(portal_app, 'student', 'c1').get('/formateur/planning').status_code == 302


def test_today_uses_paris_date_and_retains_next_courses_without_other_groups(portal_db, monkeypatch):
    instant = datetime(2027, 1, 3, 23, 30, tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Paris'))
    monkeypatch.setattr(planning_portal, '_now_paris', lambda: instant)
    with portal_db() as conn:
        today = planning_portal.get_portal_today(conn, 'student', 'c1')
        selected = planning_portal.get_portal_week(conn, 'student', 'c1')
    assert today['today'] == selected['today'] == selected['week_start'] == '2027-01-04'
    assert ids(today) == {'own', 'colleague'}
    assert {item['id'] for item in today['next_courses']} == {'shared', 'future'}
    assert 'foreign' not in json.dumps(today)


@pytest.mark.parametrize('day,expected', [(4, {'own'}), (6, set())])
def test_trainer_home_reads_only_today_in_paris_even_when_future_courses_exist(portal_db, monkeypatch, day, expected):
    instant = datetime(2027, 1, day-1, 23, 30, tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Paris'))
    monkeypatch.setattr(planning_portal, '_now_paris', lambda: instant)
    read_ranges = []
    original = planning_portal._courses
    def courses(*args):
        read_ranges.append((args[4], args[5]))
        return original(*args)
    monkeypatch.setattr(planning_portal, '_courses', courses)
    with portal_db() as conn:
        today = planning_portal.get_portal_today(conn, 'trainer', 't1')
    assert today['today'] == f'2027-01-{day:02}'
    assert ids(today) == expected
    assert today['next_courses'] == []
    assert read_ranges[0][0] == read_ranges[0][1] == instant.date()


def test_public_holidays_are_named_and_red_ready_in_both_portals(portal_db, monkeypatch):
    monkeypatch.setattr(planning_portal, '_now_paris', lambda: datetime(2027, 1, 1, 9, 0, tzinfo=ZoneInfo('Europe/Paris')))
    for role, identity in [('student', 'c1'), ('trainer', 't1')]:
        with portal_db() as conn:
            today = planning_portal.get_portal_today(conn, role, identity)
        assert today['public_holiday'] and today['day_kind'] == 'public_holiday'
        assert today['day_label'] and today['courses'] == []


def test_warning_does_not_leak_other_groups_private_labels(portal_db):
    with portal_db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=NULL WHERE id='s2'")
    shared = next(item for item in week(portal_db)['courses'] if item['id'] == 'shared')
    assert not shared['incomplete'], 'A budget warning belonging only to another group is not student information.'
    with portal_db() as conn:
        conn.execute("UPDATE planning_courses SET room_id=NULL WHERE id='shared'")
    shared = next(item for item in week(portal_db)['courses'] if item['id'] == 'shared')
    assert shared['incomplete'] and shared['warnings']
    serialized = json.dumps(shared)
    assert 'PROMOTION AUTRE' not in serialized and 'MATIERE AUTRE' not in serialized


@pytest.mark.parametrize('role,identity,expected,forbidden', [
    ('student', 'c1', ['Cours own', 'Cours colleague', 'Cours shared'], ['Cours foreign', 'MATIERE AUTRE', 'PROMOTION AUTRE']),
    ('trainer', 't1', ['Cours own', 'Cours shared'], ['Cours colleague', 'Cours foreign']),
])
def test_personal_pdf_uses_exact_same_private_scope(portal_app, role, identity, expected, forbidden):
    prefix = '/espace' if role == 'student' else '/formateur'
    response = logged(portal_app, role, identity).get(prefix + '/planning.pdf?date=2027-01-04')
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    assert response.headers['Content-Disposition'].startswith('inline')
    assert 'private' in response.headers['Cache-Control'] and 'no-store' in response.headers['Cache-Control']
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
    for value in expected:
        assert value in text
    for value in forbidden + ['secret-', '0600000000', '1999-09-09', 'Volume annuel']:
        assert value not in text
