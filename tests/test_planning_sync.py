"""Changes are visible everywhere without exposing another identity's timetable."""
from contextlib import closing
from unittest.mock import patch
from flask import session
import pytest
import planning_sync
from test_planning_portal import portal_db, portal_app, login


@pytest.fixture
def synced_app(portal_app, portal_db):
    planning_sync.register_planning_sync(portal_app, portal_db, lambda:session.get('admin_ok',False))
    return portal_app


def revision(client,scope='student',view='week',day='2026-10-26'):
    params=dict(scope=scope,view=view)
    if day:params['date']=day
    response=client.get('/planning/sync',query_string=params)
    assert response.status_code==200,response.text
    assert response.headers['Cache-Control']=='private, no-store'
    assert response.headers['Vary']=='Cookie'
    value=response.json
    assert list(value)==['revision'] and len(value['revision'])==64
    return value['revision']


def test_deleted_shared_class_updates_both_students_and_trainer(synced_app,portal_db):
    users=[(login(synced_app,'student','student1'),'student'),(login(synced_app,'student','student2'),'student'),(login(synced_app,'trainer','t1'),'trainer')]
    before=[revision(client,scope) for client,scope in users]
    with closing(portal_db()) as conn:
        conn.execute("DELETE FROM planning_course_groups WHERE course_id='common'")
        conn.execute("DELETE FROM planning_courses WHERE id='common'");conn.commit()
    assert all(revision(client,scope)!=old for (client,scope),old in zip(users,before))


def test_other_teachers_unrelated_courses_do_not_change_private_fingerprint(synced_app,portal_db):
    client=login(synced_app,'trainer','t1')
    before=revision(client,'trainer')
    with closing(portal_db()) as conn:
        conn.execute("UPDATE planning_courses SET title='A different class' WHERE id='other-teacher'");conn.commit()
    assert revision(client,'trainer')==before


def test_public_bearer_and_initial_password_are_not_authentication(synced_app,portal_db):
    assert synced_app.test_client().get('/planning/sync?scope=student&view=today').status_code==401
    client=login(synced_app)
    with closing(portal_db()) as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='student1'");conn.commit()
    assert client.get('/planning/sync?scope=student&view=today').status_code==401


@pytest.mark.parametrize('query',['scope=student&view=week&candidate_id=student2','scope=student&view=week&date=2026-10-26&date=2026-10-27','scope=student&view=admin','scope=admin&view=week','scope=student&view=week&date=0001-01-01'])
def test_invalid_scope_or_override_rejected(synced_app,query):
    assert login(synced_app).get('/planning/sync?'+query).status_code==400


def test_admin_required_for_full_revision(synced_app,portal_db):
    client=login(synced_app)
    assert client.get('/planning/sync?scope=admin&view=admin').status_code==401
    with client.session_transaction() as state:state['admin_ok']=True
    before=revision(client,'admin','admin',None)
    with closing(portal_db()) as conn:
        conn.execute("DELETE FROM planning_courses WHERE id='next'");conn.commit()
    assert revision(client,'admin','admin',None)!=before


def test_page_has_initial_revision_and_private_poll_url(synced_app):
    page=login(synced_app).get('/espace/planning?date=2026-10-26')
    assert page.status_code==200
    assert 'data-planning-sync-revision="' in page.text
    assert 'scope=student&amp;view=week&amp;date=2026-10-26' in page.text
    assert 'planning-sync.js' in page.text
