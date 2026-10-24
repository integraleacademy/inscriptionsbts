"""Independent checks for hard public-holiday closures and exact date copies."""
import pytest

from test_planning import app, client, db, admin, call, course, count, setup_school, types


def state(client, pid='p1'):
    response = client.get('/admin/planning/api/state?promotion_id=' + pid)
    assert response.status_code == 200, response.json
    return response.json


def create(client, **changes):
    response = call(client, '/courses', course(**changes))
    assert response.status_code == 200, response.json
    return response.json['course']


def dates_preview(client, dates, **changes):
    payload = dict(promotion_id='p1', mode='dates', dates=dates,
                   template=dict(subject_id='s1', room_id='r1', start='09:00', end='11:00'))
    payload.update(changes)
    if 'source_course_id' in payload:
        payload.pop('template', None)
    return call(client, '/courses/preview', payload)


@pytest.mark.parametrize('year,movable', [
    (2026, ['04-06', '05-14', '05-25']),
    (2027, ['03-29', '05-06', '05-17']),
    (2028, ['04-17', '05-25', '06-05']),
])
def test_all_eleven_national_holidays_are_computed_each_year(client, db, year, movable):
    with db() as conn:
        conn.execute('UPDATE promotions SET date_debut=?,date_fin=? WHERE id=?',
                     (f'{year}-01-01', f'{year}-12-31', 'p1'))
    days = state(client)['days']
    holidays = {day['date'] for day in days if day['kind'] == 'public_holiday'}
    expected = {f'{year}-{day}' for day in movable + ['01-01', '05-01', '05-08', '07-14', '08-15', '11-01', '11-11', '12-25']}
    assert holidays == expected
    assert all(day.get('locked') and day.get('public_holiday') and day['label']
               for day in days if day['date'] in expected)


def test_public_holiday_overrides_legacy_school_exception_and_blocks_creation(client, db):
    setup_school(client)
    with db() as conn:
        conn.execute("INSERT INTO planning_day_exceptions VALUES('p1','2027-01-01','school','Ancienne ouverture')")
    day = next(day for day in state(client)['days'] if day['date'] == '2027-01-01')
    assert day['kind'] == 'public_holiday' and day['locked']
    response = call(client, '/courses', course(date='2027-01-01'))
    assert response.status_code == 409 and 'public_holiday' in types(response)
    assert count(db) == 0


def test_single_exception_and_bulk_paint_cannot_reopen_a_public_holiday(client, db):
    setup_school(client)
    response = call(client, '/calendar/exceptions', dict(promotion_id='p1', date='2027-01-01', kind='school'), 'PUT')
    assert response.status_code == 409 and 'public_holiday' in types(response)
    revision = state(client)['calendar_revision']
    response = call(client, '/calendar/bulk', dict(promotion_id='p1', expected_revision=revision, days=[
        dict(date='2027-01-05', kind='company'), dict(date='2027-01-01', kind='school')]))
    assert response.status_code == 409 and 'public_holiday' in types(response)
    assert state(client)['calendar_revision'] == revision
    assert next(day for day in state(client)['days'] if day['date'] == '2027-01-05')['kind'] == 'school'
    assert count(db, 'planning_day_exceptions') == 0


def test_holiday_availability_and_move_rejected_without_changing_existing_course(client, db):
    setup_school(client)
    lesson = create(client)
    available = client.get('/admin/planning/api/availability', query_string=dict(
        promotion_id='p1', subject_id='s1', room_id='r1', start='2027-03-29', end='2027-03-29',
        duration=120, day_start='08:00', day_end='12:00'))
    assert available.status_code == 200
    assert available.json['slots'] and all(not item['available'] for item in available.json['slots'])
    assert all(any(issue['type'] == 'public_holiday' for issue in item['conflicts']) for item in available.json['slots'])
    moved = call(client, '/courses/' + lesson['id'], dict(version=lesson['version'], date='2027-03-29'), 'PUT')
    assert moved.status_code == 409 and 'public_holiday' in types(moved)
    kept = next(item for item in state(client)['courses'] if item['id'] == lesson['id'])
    assert kept['date'] == lesson['date'] and kept['version'] == lesson['version']


def test_old_holiday_course_stays_visible_and_does_not_block_unrelated_calendar_change(client, db):
    setup_school(client)
    lesson = create(client)
    with db() as conn:
        conn.execute("UPDATE planning_courses SET date='2027-01-01' WHERE id=?", (lesson['id'],))
    prior = state(client)
    kept = next(item for item in prior['courses'] if item['id'] == lesson['id'])
    assert kept.get('warnings'), 'An old holiday lesson must be explicitly flagged.'
    response = call(client, '/calendar/bulk', dict(promotion_id='p1', expected_revision=prior['calendar_revision'],
        days=[dict(date='2027-01-05', kind='company')]))
    assert response.status_code == 200, response.json
    assert count(db) == 1


def test_explicit_dates_preview_blocks_holiday_and_commit_is_atomic(client, db):
    setup_school(client)
    response = dates_preview(client, ['2027-01-01', '2027-01-04', '2027-01-05'])
    assert response.status_code == 200, response.json
    preview = response.json
    holiday = next(item for item in preview['items'] if item['course']['date'] == '2027-01-01')
    assert not holiday['valid'] and any(issue['type'] == 'public_holiday' for issue in holiday['conflicts'])
    response = call(client, '/courses/batch', dict(preview_token=preview['preview_token'], selected_keys=[item['key'] for item in preview['items']]))
    assert response.status_code == 409 and count(db) == 0
    response = call(client, '/courses/batch', dict(preview_token=preview['preview_token'], selected_keys=[item['key'] for item in preview['items'] if item['valid']]))
    assert response.status_code == 200, response.json
    assert count(db) == 2


def test_explicit_dates_charge_cumulative_shared_budget_and_allow_later_subset(client, db):
    setup_school(client)
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=2 WHERE id='s2'")
    response = dates_preview(client, ['2027-01-04', '2027-01-05'], template=dict(
        subject_id='s1', room_id='r1', start='09:00', end='11:00', shared=[dict(promotion_id='p2', subject_id='s2')]))
    assert response.status_code == 200, response.json
    preview = response.json
    response = call(client, '/courses/batch', dict(preview_token=preview['preview_token'], selected_keys=['0', '1']))
    assert response.status_code == 409 and 'subject_budget' in types(response) and count(db) == 0
    response = call(client, '/courses/batch', dict(preview_token=preview['preview_token'], selected_keys=['1']))
    assert response.status_code == 200, response.json
    assert count(db) == 1
    assert state(client, 'p2')['subjects'][0]['scheduled_hours'] == 2


def test_source_version_is_rechecked_at_explicit_date_commit(client, db):
    setup_school(client)
    source = create(client)
    response = dates_preview(client, ['2027-01-05'], source_course_id=source['id'], source_version=source['version'])
    assert response.status_code == 200, response.json
    token = response.json['preview_token']
    edited = call(client, '/courses/' + source['id'], dict(version=source['version'], title='Source modifiée'), 'PUT')
    assert edited.status_code == 200
    result = call(client, '/courses/batch', dict(preview_token=token, selected_keys=['0']))
    assert result.status_code == 409 and count(db) == 1


@pytest.mark.parametrize('dates', [None, [], ['2027-01-04', 'bad'], [True], '2027-01-04', ['2027-02-30'], ['2027-01-04', '2027-01-04']])
def test_explicit_dates_malformed_inputs_fail_closed(client, db, dates):
    setup_school(client)
    response = dates_preview(client, dates)
    assert response.status_code == 400, response.json
    assert count(db) == 0


@pytest.mark.parametrize('resource,where', [
    ('planning_rooms', "id='r1'"), ('trainers', "id='t1'"), ('planning_subjects', "id='s1'"),
])
def test_legacy_orphan_course_is_not_silently_lost_from_planning(client, db, resource, where):
    setup_school(client)
    lesson = create(client)
    with db() as conn:
        conn.execute('DELETE FROM ' + resource + ' WHERE ' + where)
    courses = state(client)['courses']
    kept = next(item for item in courses if item['id'] == lesson['id'])
    assert kept['incomplete'] and kept['warnings']


def test_course_without_room_is_visible_with_accessible_warning(client, db):
    setup_school(client)
    lesson = create(client, room_id=None)
    assert lesson['incomplete'] and lesson['warnings'] and lesson['warning_labels']
    assert count(db) == 1


def test_missing_secondary_subject_does_not_erase_shared_group(client, db):
    setup_school(client)
    lesson = create(client, shared=[dict(promotion_id='p2', subject_id='s2')])
    with db() as conn:
        conn.execute("DELETE FROM planning_subjects WHERE id='s2'")
    kept = next(item for item in state(client, 'p2')['courses'] if item['id'] == lesson['id'])
    assert kept['incomplete'] and any(group['promotion_id'] == 'p2' for group in kept['groups'])
