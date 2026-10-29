"""BTS-year forecasting and dedicated trainer tabs share canonical planning rows."""
from datetime import datetime
from html import unescape
import re

import pytest
import trainer_access
from test_trainer_workload import workload_db, workload_client, lesson, rate
from trainer_workload import get_trainer_annual_workload, WorkloadError


def annual(db, year=2026):
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
    assert data['shared_minutes']==1 and len(data['months'])==11
    assert data['estimated_cents']==3
    assert sum(row['estimated_cents'] for row in data['months'])==4
    assert data['months'][4]['course_count']==data['months'][5]['course_count']==1


def test_annual_missing_tariff_never_appears_fully_costed(workload_db):
    with workload_db() as conn:
        lesson(conn,'jan',day='2027-01-04')
        lesson(conn,'feb',day='2027-02-01')
    rate(workload_db,amount='45',day='2027-02-01')
    data=annual(workload_db)
    assert data['all_priced'] is False and data['unpriced_minutes']==120
    assert data['months'][4]['all_priced'] is False
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


@pytest.mark.parametrize('year',[True,None,'2027',1899,2200,2201])
def test_annual_invalid_year_is_rejected(workload_db,year):
    with pytest.raises(WorkloadError):annual(workload_db,year)


def test_two_selects_navigate_without_javascript(workload_client,workload_db):
    with workload_db() as conn:lesson(conn,'feb',day='2027-02-01')
    response=workload_client.get('/admin/formateurs/t1?tab=accounting&school_year=2026&month_number=02')
    assert response.status_code==200
    assert 'id="tw-month-title">Février 2027' in response.text
    assert 'name="month_number"' in response.text and 'name="school_year"' in response.text
    assert 'Coût BTS à compléter' in response.text
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


def test_bts_year_includes_september_through_july_with_actual_date_rates(workload_db):
    with workload_db() as conn:
        for day in ('2026-01-01', '2026-08-31', '2026-09-01', '2026-12-31',
                    '2027-01-01', '2027-07-31', '2027-08-01', '2027-09-01', '2027-12-31'):
            lesson(conn, day, day=day, groups=('p1', 'p2', 'p3'))
        lesson(conn, 'colleague', day='2026-09-01', trainer='t2')
    rate(workload_db, amount='40', day='2026-09-01')
    rate(workload_db, amount='50', day='2027-01-01', revision=1)
    data = annual(workload_db)
    assert data['start'] == '2026-09-01' and data['end'] == '2027-07-31'
    assert data['label'] == '2026–2027'
    assert data['total_minutes'] == data['shared_minutes'] == 480
    assert data['course_count'] == 4 and data['estimated_cents'] == 36000
    assert data['all_priced']
    assert [(row['year'], row['number']) for row in data['months']] == [
        (2026, 9), (2026, 10), (2026, 11), (2026, 12),
        (2027, 1), (2027, 2), (2027, 3), (2027, 4), (2027, 5), (2027, 6), (2027, 7)]


def test_bts_year_keeps_unpriced_first_term_visible(workload_db):
    with workload_db() as conn:
        lesson(conn, 'sep', day='2026-09-01')
        lesson(conn, 'jan', day='2027-01-01')
    rate(workload_db)
    data = annual(workload_db)
    assert data['unpriced_minutes'] == 120 and not data['all_priced']
    assert not data['months'][0]['all_priced'] and data['months'][4]['all_priced']
    assert data['estimated_cents'] == 9000


@pytest.mark.parametrize('query,month_label,period', [
    ('year=2026&month_number=10', 'Octobre 2026', '2026–2027'),
    ('year=2027&month_number=2', 'Février 2027', '2026–2027'),
    ('month=2027-07', 'Juillet 2027', '2026–2027'),
    ('school_year=2026&month_number=09', 'Septembre 2026', '2026–2027'),
    ('school_year=2026&month_number=01', 'Janvier 2027', '2026–2027'),
    ('school_year=2027&month_number=01', 'Janvier 2028', '2027–2028'),
    ('school_year=1900&month_number=09', 'Septembre 1900', '1900–1901'),
    ('school_year=2199&month_number=07', 'Juillet 2200', '2199–2200'),
])
def test_school_and_legacy_filters_choose_the_same_actual_month(workload_client, query, month_label, period):
    page = workload_client.get('/admin/formateurs/t1?tab=accounting&' + query)
    assert page.status_code == 200
    assert f'id="tw-month-title">{month_label}</h2>' in page.text
    assert f'Année BTS {period}' in page.text


@pytest.mark.parametrize('query', [
    'school_year=1899', 'school_year=2200', 'school_year=2026-2027',
    'school_year=2026&year=2027', 'school_year=2026&school_year=2027',
    'school_year=2026&month=2026-01', 'school_year=2026&month_number=00',
    'school_year=2026&month=2027-09', 'school_year=2026&month=2027-01&month_number=01',
    'tab=planning&school_year=2026', 'month=1900-01', 'month=2200-09',
])
def test_inconsistent_school_year_filters_are_rejected(workload_client, query):
    assert workload_client.get('/admin/formateurs/t1?' + query).status_code == 400


def test_all_eleven_month_links_keep_the_selected_bts_year(workload_client):
    page = workload_client.get('/admin/formateurs/t1?school_year=2026&month_number=10')
    links = re.findall(r'<a href="([^"]+)" class="tw-year-month[^\"]*"', page.text)
    assert len(links) == 11
    assert 'month=2026-09' in links[0] and 'month=2027-07' in links[-1]
    assert 'aria-label="janvier 2027 :' in page.text
    for link in links:
        month_page = workload_client.get(unescape(link))
        assert month_page.status_code == 200
        assert 'Année BTS 2026–2027' in month_page.text
        assert month_page.text.count('aria-current="date"') == 1


@pytest.mark.parametrize('month,previous,next_month', [
    ('2026-12', '2026-11', '2027-01'),
    ('2027-01', '2026-12', '2027-02'),
    ('2027-07', '2027-06', '2027-09'),
    ('2026-09', '2026-07', '2026-10'),
    ('1900-09', None, '1900-10'),
    ('2200-07', '2200-06', None),
])
def test_month_navigation_crosses_bts_years_and_skips_august(workload_client, month, previous, next_month):
    page = workload_client.get('/admin/formateurs/t1?month=' + month)
    for label, expected in [('Mois précédent', previous), ('Mois suivant', next_month)]:
        match = re.search(r'<a href="([^"]+)" aria-label="' + label + '"', page.text)
        if expected is None:
            assert match is None
        else:
            assert f'month={expected}' in match.group(1)
            assert workload_client.get(unescape(match.group(1))).status_code == 200


def test_august_legacy_details_remain_available_outside_bts_totals(workload_client, workload_db):
    with workload_db() as conn:
        lesson(conn, 'summer', day='2027-08-01')
    rate(workload_db)
    page = workload_client.get('/admin/formateurs/t1?year=2027&month_number=08')
    assert page.status_code == 200
    assert 'Août est hors de la période BTS' in page.text
    assert 'Cours summer' in page.text
    assert 'Année BTS 2026–2027' in page.text
    assert annual(workload_db)['total_minutes'] == 0


@pytest.mark.parametrize('today,month_label,period', [
    ((2027, 1, 15), 'Janvier 2027', '2026–2027'),
    ((2027, 8, 15), 'Juillet 2027', '2026–2027'),
    ((2027, 9, 1), 'Septembre 2027', '2027–2028'),
])
def test_default_period_tracks_the_current_bts_year(workload_client, monkeypatch, today, month_label, period):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(*today, tzinfo=tz)
    monkeypatch.setattr(trainer_access, 'datetime', Clock)
    page = workload_client.get('/admin/formateurs/t1?tab=accounting')
    assert page.status_code == 200
    assert f'id="tw-month-title">{month_label}</h2>' in page.text
    assert f'Année BTS {period}' in page.text
