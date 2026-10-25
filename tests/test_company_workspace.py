"""Directory filters and progressive company profiles use the real routes."""
from contextlib import contextmanager
from flask import template_rendered
from bs4 import BeautifulSoup
import pytest
from test_company_portal import env, admin, logged, post


@contextmanager
def rendered(app):
    output = []
    def record(sender, template, context, **extra):
        output.append((template.name, context))
    template_rendered.connect(record, app)
    try:
        yield output
    finally:
        template_rendered.disconnect(record, app)


def directory(env, **query):
    with rendered(env[0]) as output:
        response = admin(env).get('/admin/entreprises', query_string=query)
    assert response.status_code == 200
    return output[-1][1]


@pytest.mark.parametrize('query', ['mediterranee', 'MÉDITERRANÉE', 'frejus camille', '123 456 789 00022', 'contact1@example.test'])
def test_search_matches_accents_contact_and_siret(env, query):
    with env[1]() as conn:
        conn.execute("UPDATE companies SET name='Atelier Méditerranée',contact='Camille',city='Fréjus',siret='12345678900022' WHERE id='e1'")
    context = directory(env, q=query)
    assert [c['id'] for c in context['companies']] == ['e1']
    assert context['stats']['total'] == 2


def test_access_counts_and_filters_include_invited_but_exclude_disabled(env):
    with env[1]() as conn:
        conn.execute("UPDATE companies SET password_hash=NULL WHERE id IN ('e1','e2')")
        conn.execute("UPDATE companies SET invited_at='2026-10-20' WHERE id='e2'")
    assert directory(env, access='awaiting')['stats']['pending'] == 2
    assert [c['id'] for c in directory(env, access='pending')['companies']] == ['e1']
    assert [c['id'] for c in directory(env, access='invited')['companies']] == ['e2']
    with env[1]() as conn:
        conn.execute("UPDATE companies SET active=0 WHERE id='e2'")
    assert [c['id'] for c in directory(env, access='awaiting')['companies']] == ['e1']
    assert directory(env)['stats']['pending'] == 1
    assert [c['id'] for c in directory(env, access='disabled')['companies']] == ['e2']


def test_student_counts_exclude_ended_and_cancelled_links(env):
    with env[1]() as conn:
        conn.execute("UPDATE company_students SET end_date='2026-10-01' WHERE candidate_id='s1'")
        conn.execute("INSERT INTO company_students VALUES('s3','e1','2026-10-01',NULL,'','now')")
    context = directory(env, order='students')
    assert [(c['id'], c['student_count']) for c in context['companies']] == [('e2',1),('e1',0)]
    assert context['stats']['students'] == 1


def test_pagination_sorting_and_empty_results(env):
    with env[1]() as conn:
        for i in range(25):
            conn.execute("INSERT INTO companies(id,name,contact,email,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                         (f'new{i}',f'Partenaire {i:02d}','Camille',f'p{i}@example.test','now','now'))
    first, second = directory(env), directory(env,page='2')
    assert len(first['companies']) == 20 and len(second['companies']) == 7
    assert not set(c['id'] for c in first['companies']) & set(c['id'] for c in second['companies'])
    assert second['first_result'] == 21 and second['last_result'] == 27
    assert directory(env,page='999999')['current_page'] == 2
    assert directory(env,order='name_desc')['companies'][0]['name'] == 'Partenaire 24'
    empty = directory(env,q='introuvable')
    assert empty['companies'] == [] and empty['first_result'] == 0
    assert empty['stats']['total'] == 27


@pytest.mark.parametrize('query',[{'page':'wrong'},{'order':'injected'},{'access':'injected'}])
def test_invalid_directory_controls_return_400(env, query):
    assert admin(env).get('/admin/entreprises',query_string=query).status_code == 400


@pytest.mark.parametrize('tab',['overview','information','registry','students','access'])
def test_each_profile_tab_is_addressable_and_only_one_panel_is_visible(env, tab):
    response=admin(env).get('/admin/entreprises/e1',query_string={'tab':tab})
    assert response.status_code==200
    soup=BeautifulSoup(response.text,'html.parser')
    assert [p['data-company-panel'] for p in soup.select('[data-company-panel]:not([hidden])')]==[tab]
    assert len(soup.select('[role=tab]'))==5
    assert not soup.select('main details')
    assert len(soup.select('main form[action="/admin/entreprises/e1?tab=information"]'))==1
    assert all(b.get_text(strip=True) for b in soup.select('main button'))


def test_creation_has_a_separate_form_and_validation_keeps_entered_values(env):
    client=admin(env)
    assert 'data-company-edit-form' not in client.get('/admin/entreprises').text
    assert 'data-company-edit-form' in client.get('/admin/entreprises?view=create').text
    response=post(client,'/admin/entreprises',name='Nom à conserver',contact='Camille',email='incorrect')
    assert response.status_code==400
    soup=BeautifulSoup(response.text,'html.parser')
    assert soup.select_one('input[name=name]')['value']=='Nom à conserver'
    assert soup.select_one('[data-dirty-on-load]')
    with env[1]() as conn:
        assert conn.execute('SELECT count(*) FROM companies').fetchone()[0]==2
    assert not env[2]


def test_profile_save_and_errors_return_to_information_tab(env):
    client=admin(env)
    response=post(client,'/admin/entreprises/e1',version='1',name='Entreprise 1',contact='Camille',email='wrong')
    assert response.status_code==400
    assert 'data-active-tab="information"' in response.text
    response=post(client,'/admin/entreprises/e1',version='1',name='Entreprise 1',contact='Camille',email='contact1@example.test')
    assert response.status_code==303 and response.location.endswith('?tab=information')


def test_get_confirmation_screens_are_read_only_and_foreign_students_denied(env):
    client=admin(env)
    for suffix in ['?tab=students&edit=s1','?tab=students&remove=s1','?tab=access&confirm=status']:
        assert client.get('/admin/entreprises/e1'+suffix).status_code==200
    for suffix in ['?tab=students&edit=s2','?tab=students&remove=s2']:
        assert client.get('/admin/entreprises/e1'+suffix).status_code==404
    assert client.get('/admin/entreprises/e1?tab=unknown').status_code==400
    with env[1]() as conn:
        assert conn.execute("SELECT active FROM companies WHERE id='e1'").fetchone()[0]==1
        assert conn.execute("SELECT company_id FROM company_students WHERE candidate_id='s1'").fetchone()[0]=='e1'
    assert not env[2]


@pytest.mark.parametrize('path',['/admin/entreprises?view=create','/admin/entreprises?access=awaiting','/admin/entreprises/e1?tab=access'])
def test_new_views_remain_admin_only(env,path):
    assert logged(env).get(path).status_code==403
