"""Annual forecasting and dedicated trainer tabs share canonical planning rows."""
import pytest
from test_trainer_workload import workload_db, workload_client, lesson, rate
from trainer_workload import get_trainer_annual_workload, WorkloadError


def annual(db, year=2027):
    with db() as conn:
        return get_trainer_annual_workload(conn,'t1',year)


def test_annual_exact_rounding_and_shared_session_once(workload_db):
    with workload_db() as conn:
        lesson(conn,'jan',end=481,groups=('p1','p2','p3'))
        lesson(conn,'feb',day='2027-02-01',end=481)
        lesson(conn,'other',trainer='t2',end=600)
        lesson(conn,'outside',day='2028-01-01')
    rate(workload_db,amount='1')
    data=annual(workload_db)
    assert data['course_count']==2 and data['total_minutes']==2
    assert data['shared_minutes']==1 and len(data['months'])==12
    assert data['estimated_cents']==3
    assert sum(row['estimated_cents'] for row in data['months'])==4
    assert data['months'][0]['course_count']==data['months'][1]['course_count']==1


def test_annual_missing_tariff_never_appears_fully_costed(workload_db):
    with workload_db() as conn:
        lesson(conn,'jan',day='2027-01-04')
        lesson(conn,'feb',day='2027-02-01')
    rate(workload_db,amount='45',day='2027-02-01')
    data=annual(workload_db)
    assert data['all_priced'] is False and data['unpriced_minutes']==120
    assert data['months'][0]['all_priced'] is False
    assert data['estimated_cents']==9000


def test_annual_changes_and_effective_rates_are_immediate(workload_db):
    with workload_db() as conn:
        lesson(conn,'jan',day='2027-01-04')
        lesson(conn,'jul',day='2027-07-01')
    rate(workload_db,amount='40')
    rate(workload_db,amount='50',day='2027-07-01',revision=1)
    assert annual(workload_db)['estimated_cents']==18000
    with workload_db() as conn:
        conn.execute("DELETE FROM planning_course_groups WHERE course_id='jul'")
        conn.execute("DELETE FROM planning_courses WHERE id='jul'")
    assert annual(workload_db)['estimated_cents']==8000


@pytest.mark.parametrize('year',[True,None,'2027',1899,2201])
def test_annual_invalid_year_is_rejected(workload_db,year):
    with pytest.raises(WorkloadError):annual(workload_db,year)


def test_two_selects_navigate_without_javascript(workload_client,workload_db):
    with workload_db() as conn:lesson(conn,'feb',day='2027-02-01')
    response=workload_client.get('/admin/formateurs/t1?tab=accounting&year=2027&month_number=02')
    assert response.status_code==200
    assert 'Son activité en <em>février 2027' in response.text
    assert 'name="month_number"' in response.text and 'name="year"' in response.text
    assert 'Coût annuel à compléter' in response.text
    assert 'tw-year-chart' in response.text
    assert '<option value="1900"' not in response.text
    assert 'role="dialog"' not in response.text and '<dialog' not in response.text


def test_account_tab_has_inline_fields_without_financial_overload(workload_client):
    response=workload_client.get('/admin/formateurs/t1?tab=account')
    assert response.status_code==200
    assert 'trainer-profile-form' in response.text
    assert 'name="assignments"' in response.text
    assert 'data-profile-action="access"' in response.text
    assert 'Volume mensuel total' not in response.text
    assert 'trainer-hourly-rate-form' not in response.text
    assert '<dialog' not in response.text


@pytest.mark.parametrize('query',['tab=wrong','year=1899','year=2027&year=2028','month_number=13','month=2027-01&month_number=01','year=2028&month=2027-01','tab=planning&date=2027-02-30'])
def test_tab_filters_are_validated(workload_client,query):
    assert workload_client.get('/admin/formateurs/t1?'+query).status_code==400


def test_directory_existing_account_uses_tab_not_modal(workload_client):
    response=workload_client.get('/admin/formateurs')
    assert response.status_code==200
    assert '/admin/formateurs/t1?tab=account' in response.text
    assert 'data-edit-trainer="t1"' not in response.text


def test_planning_tab_renders_real_schedule_without_accounting(workload_client,workload_db):
    with workload_db() as conn:lesson(conn,'jan',day='2027-01-04')
    response=workload_client.get('/admin/formateurs/t1?tab=planning&date=2027-01-04')
    assert response.status_code==200
    assert 'Son <em>planning.' in response.text
    assert 'Cours jan' in response.text
    assert 'tab=accounting&amp;year=2027&amp;month=2027-01' in response.text
    assert 'Volume mensuel total' not in response.text
    assert 'trainer-hourly-rate-form' not in response.text


def test_availability_tab_renders_calendar_without_other_panels(workload_client):
    response=workload_client.get('/admin/formateurs/t1?tab=availability&year=2027')
    assert response.status_code==200
    assert 'data-admin-trainer-availability' in response.text
    assert 'Bloquer les dates' in response.text
    assert 'Volume mensuel total' not in response.text
    assert 'trainer-profile-form' not in response.text
