"""Month/year shortcuts stay authenticated and point to canonical private weeks."""
from contextlib import closing
import re

import pytest
from flask import Flask,render_template
from pathlib import Path
from test_planning_portal import portal_db,portal_app,login


@pytest.mark.parametrize('role,person,prefix',[('trainer','t1','/formateur'),('student','student1','/espace')])
def test_month_jump_is_server_side_and_keeps_identity_scope(portal_app,role,person,prefix):
    client=login(portal_app,role,person)
    reply=client.get(prefix+'/planning/mois?month=02&year=2027')
    assert reply.status_code==302
    assert reply.headers['Location']==prefix+'/planning?date=2027-02-01'
    assert reply.headers['Cache-Control']=='private, no-store'
    assert 'Cookie' in reply.headers['Vary']
    rendered=client.get(reply.headers['Location'])
    assert rendered.status_code==200
    assert '<select name="month" id="portal-month">' in rendered.text
    assert '<option value="02" selected>Février</option>' in rendered.text
    assert '<option value="2027" selected>2027</option>' in rendered.text
    assert 'Choisir une date précise' in rendered.text
    assert '<input id="portal-date" type="date" name="date"' in rendered.text
    assert 'Semaine précédente' in rendered.text and 'Semaine suivante' in rendered.text


@pytest.mark.parametrize('query',[
    'month=0&year=2027','month=13&year=2027','month=02&year=1899','month=02&year=2201',
    'month=02&year=2027&year=2028','month=02&year=2027&trainer_id=t2',
    'month=02&year=2027&next=https://example.test','month=02',
    'month=02&year=2027&date=2026-10-26','month=1.0&year=2027'
])
def test_month_jump_rejects_overrides_and_invalid_inputs(portal_app,query):
    assert login(portal_app,'trainer','t1').get('/formateur/planning/mois?'+query).status_code==400


def test_month_jump_preserves_authentication_and_initial_password_guard(portal_app,portal_db):
    assert portal_app.test_client().get('/formateur/planning/mois?month=02&year=2027').headers['Location']=='/formateur/connexion'
    client=login(portal_app,'student','student1')
    with closing(portal_db()) as conn:
        conn.execute("UPDATE student_accounts SET must_change=1 WHERE id='student1'");conn.commit()
    assert client.get('/espace/planning/mois?month=02&year=2027').headers['Location']=='/espace/mot-de-passe'


def test_trainer_planning_uses_real_page_tabs_with_current_page(portal_app):
    html=login(portal_app,'trainer','t1').get('/formateur/planning?date=2026-10-26').text
    nav=re.search(r'<nav class="trainer-portal-nav".*?</nav>',html,re.S).group(0)
    assert nav.count('<a ')==5
    assert '/formateur/pedagogie' in nav
    assert 'href="/formateur"' in nav
    assert 'href="/formateur/indisponibilites"' in nav
    assert re.search(r'href="/formateur/planning"[^>]*aria-current="page"',nav)
    assert 'onclick' not in nav and '<button' not in nav


def test_student_planning_does_not_render_trainer_tabs(portal_app):
    html=login(portal_app,'student','student1').get('/espace/planning?date=2026-10-26').text
    assert 'class="trainer-portal-nav"' not in html


def test_availability_page_has_year_and_month_shortcuts():
    root=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(root/'templates'))
    app.secret_key='navigation-template-only'
    with app.test_request_context('/formateur/indisponibilites'):
        html=render_template('trainer_availability.html',availability=dict(year=2027,home_url='/formateur',planning_url='/formateur/planning'),trainer={})
    assert '<select name="year" id="ta-year-select">' in html
    assert '<option value="2027" selected>2027</option>' in html
    assert 'id="ta-month-select"' in html and '>Décembre 2027</option>' in html
    assert re.search(r'href="/formateur/indisponibilites"[^>]*aria-current="page"',html)
