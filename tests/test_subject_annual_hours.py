"""Annual defaults and explicit, atomic budget edits from a subject's catalogue."""
import pytest

from test_planning import db, app, client, call, BASE
from test_subject_catalog import create
from test_planning_years import annual, snapshot, allocation


def test_defaults_follow_diploma_and_study_year_without_overwriting_allocations(client, db):
    with db() as conn:
        conn.execute("UPDATE promotions SET date_debut='2026-09-01',date_fin='2028-07-01' WHERE id='p1'")
        conn.execute("UPDATE promotions SET bts='MOS',niveau=2 WHERE id='p2'")
    item = create(client, diploma_details={
        'MCO': dict(annual_hours_first=120, annual_hours_second=90),
        'MOS': dict(annual_hours_first=80, annual_hours_second=60)})
    ids = []
    for pid, period, expected in [('p1', 'p1:1', 120), ('p1', 'p1:2', 90), ('p2', 'p2:1', 60)]:
        response = call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id=pid, period_id=period, trainer_id='t1'))
        assert response.status_code == 200, response.json
        assert response.json['subject']['planned_hours'] == expected
        ids.append(response.json['subject']['id'])
    assert snapshot(client, 2)['study_year'] == 2
    assert snapshot(client, 1, 'p2')['study_year'] == 2
    result = call(client, '/subject-catalog/'+item['id'], dict(diploma_details={'MCO': dict(annual_hours_first=150)}), 'PUT')
    assert result.status_code == 200, result.json
    with db() as conn:
        assert [conn.execute('SELECT planned_hours FROM planning_subjects WHERE id=?', (sid,)).fetchone()[0] for sid in ids] == [120, 90, 60]
    data = result.json['subject']['diploma_details']
    assert data['MCO']['annual_hours_second'] == 90 and data['MOS']['annual_hours_second'] == 60
    # Explicit custom budgets still take precedence over the catalogue default.
    custom = call(client, '/subjects/'+ids[0], dict(planned_hours=125), 'PUT')
    assert custom.status_code == 200 and custom.json['subject']['planned_hours'] == 125


@pytest.mark.parametrize('value', [True, False, -1, 0, 5001, 'nan', 'Infinity', '0.01', [], {}, '1e999'])
def test_invalid_annual_defaults_are_rejected_atomically(client, value):
    item = create(client)
    response = call(client, '/subject-catalog/'+item['id'], dict(name='Should not save', diploma_details={
        'MOS': dict(annual_hours_first=120), 'MCO': dict(annual_hours_second=value)}), 'PUT')
    assert response.status_code == 400, response.json
    saved = next(row for row in client.get(BASE+'/subject-catalog').json['subjects'] if row['id'] == item['id'])
    assert saved == item


def test_optional_defaults_preserve_official_data_and_can_be_cleared(client):
    item = create(client, diploma_details={'MOS': dict(coefficient=3, weekly_hours_first=2, annual_hours_first=1.1, annual_hours_second=5000)})
    response = call(client, '/subject-catalog/'+item['id'], dict(diploma_details={'MOS': dict(annual_hours_first=None, annual_hours_second='')}), 'PUT')
    assert response.status_code == 200, response.json
    data = response.json['subject']['diploma_details']['MOS']
    assert data == dict(coefficient=3, weekly_hours_first=2, annual_hours_first=None, annual_hours_second=None)


def edit(row, hours):
    return dict(id=row['id'], previous_planned_hours=row['planned_hours'], planned_hours=hours)


def test_existing_budgets_edit_from_catalogue_with_year_isolation(annual, client):
    first, second = allocation(snapshot(client)), allocation(snapshot(client, 2))
    response = call(client, '/subject-catalog/'+first['catalog_subject_id'], dict(planning_allocations=[edit(second, 5.5)]), 'PUT')
    assert response.status_code == 200, response.json
    assert allocation(snapshot(client))['planned_hours'] == 30
    edited = allocation(snapshot(client, 2))
    assert edited['planned_hours'] == 5.5 and edited['scheduled_hours'] == 2 and edited['remaining_hours'] == 3.5
    assert edited['trainer_id'] == second['trainer_id']


def test_failed_reduction_rolls_back_other_year_and_catalogue(annual, client):
    first, second = allocation(snapshot(client)), allocation(snapshot(client, 2))
    sid = first['catalog_subject_id']
    before = next(row for row in client.get(BASE+'/subject-catalog').json['subjects'] if row['id'] == sid)
    response = call(client, '/subject-catalog/'+sid, dict(name='Should not save', diploma_details={'MCO': dict(annual_hours_first=80)},
        planning_allocations=[edit(first, 40), edit(second, 1)]), 'PUT')
    assert response.status_code == 409 and response.json['conflicts'][0]['scheduled_minutes'] == 120
    assert allocation(snapshot(client))['planned_hours'] == allocation(snapshot(client, 2))['planned_hours'] == 30
    assert next(row for row in client.get(BASE+'/subject-catalog').json['subjects'] if row['id'] == sid) == before


def test_shared_courses_count_towards_the_minimum(annual, client):
    row = allocation(snapshot(client, 2, 'p2'), 'Matière s2')
    assert row['scheduled_hours'] == 2
    response = call(client, '/subject-catalog/'+row['catalog_subject_id'], dict(planning_allocations=[edit(row, 1)]), 'PUT')
    assert response.status_code == 409


def test_stale_budget_and_unrelated_or_archived_allocations_cannot_be_overwritten(client, db):
    data = client.get(BASE+'/catalog').json
    first = next(row for row in data['subjects'] if row['id'] == 's1')
    other = next(row for row in data['subjects'] if row['id'] == 's2')
    path = '/subject-catalog/'+first['catalog_subject_id']
    assert call(client, '/subjects/s1', dict(planned_hours=40), 'PUT').status_code == 200
    for changes in ([edit(first, 50)], [edit(other, 50)], [dict(id='s1', planned_hours=50)],
                    [dict(id='s1', previous_planned_hours=True, planned_hours=50)]):
        response = call(client, path, dict(planning_allocations=changes), 'PUT')
        assert response.status_code == 409, response.json
    with db() as conn:
        conn.execute("UPDATE promotions SET active=0 WHERE id='p1'")
    assert call(client, path, dict(planning_allocations=[dict(id='s1', previous_planned_hours=40, planned_hours=50)]), 'PUT').status_code == 409
    with db() as conn:
        assert conn.execute("SELECT planned_hours FROM planning_subjects WHERE id='s1'").fetchone()[0] == 40


def test_unconfigured_volume_can_be_filled_but_changes_cannot_clear_a_budget(client, db):
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=NULL WHERE id='s1'")
    row = next(row for row in client.get(BASE+'/catalog').json['subjects'] if row['id'] == 's1')
    path = '/subject-catalog/'+row['catalog_subject_id']
    assert call(client, path, dict(planning_allocations=[edit(row, 20)]), 'PUT').status_code == 200
    for changes in ([dict(id='s1', previous_planned_hours=20, planned_hours=None)],
                    [dict(id='s1', previous_planned_hours=20, planned_hours=0)]):
        assert call(client, path, dict(planning_allocations=changes), 'PUT').status_code == 400


def test_catalogue_budgets_require_admin_csrf_and_valid_collections(client, app):
    item = create(client)
    path = BASE+'/subject-catalog/'+item['id']
    payload = dict(diploma_details={'MOS': dict(annual_hours_first=120)})
    assert app.test_client().put(path, json=payload).status_code == 403
    assert client.put(path, json=payload).status_code == 400
    for changes in ({}, [None], [dict(id=[])], [dict(id='x'), dict(id='x')]):
        assert call(client, path, dict(planning_allocations=changes), 'PUT').status_code in (400, 409)
