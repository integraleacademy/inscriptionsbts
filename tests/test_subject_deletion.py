"""Catalogue deletion removes empty preparations and preserves teaching history."""
import pytest

import subject_references
from test_planning import db, app, client, call, BASE
from test_subject_catalog import create
from test_planning_years import annual, raw_course


def prepared(client):
    item = create(client, name='TEST')
    rows = []
    for pid, year in [('p1', 1), ('p1', 2), ('p2', 1)]:
        response = call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id=pid,
            period_id=f'{pid}:{year}', trainer_id='t1', planned_hours=25))
        assert response.status_code == 200, response.json
        rows.append(response.json['subject'])
    return item, rows


TABLES = ('planning_subject_catalog', 'planning_subject_diplomas', 'planning_subject_catalog_links',
          'planning_subjects', 'planning_subject_details', 'planning_subject_periods', 'planning_courses',
          'planning_course_groups', 'planning_periods', 'planning_calendar_rules', 'trainer_promotions', 'trainers')


def state(db):
    with db() as conn:
        return {table: [tuple(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY 1,2')] for table in TABLES}


def test_delete_unused_preparations_in_all_years_and_promotions(annual, client, db):
    item, rows = prepared(client)
    ids = {row['id'] for row in rows}
    with db() as conn:
        conn.execute("UPDATE promotions SET active=0 WHERE id='p2'")
        for sid in ids:
            subject_references.save_details(conn, sid, dict(objectives='Programme test'))
    before = state(db)
    response = call(client, '/subject-catalog/'+item['id'], dict(version=item['version']), 'DELETE')
    assert response.status_code == 200, response.json
    after = state(db)
    for table in ('planning_subject_catalog', 'planning_subject_diplomas'):
        assert after[table] == [row for row in before[table] if row[0] != item['id']]
    for table in ('planning_subjects', 'planning_subject_details', 'planning_subject_periods', 'planning_subject_catalog_links'):
        assert after[table] == [row for row in before[table] if row[0] not in ids]
    for table in TABLES[6:]:
        assert after[table] == before[table]
    # A later schema pass cannot re-create the deleted catalogue entry.
    for _ in range(2):
        data = client.get(BASE+'/catalog').json
        assert not any(row['id'] == item['id'] for row in data['subject_catalog'])
        assert not any(row['id'] in ids for row in data['subjects'])


@pytest.mark.parametrize('usage', ['primary', 'shared', 'outside_year', 'second_year'])
def test_course_references_block_the_entire_deletion(annual, client, db, usage):
    item, rows = prepared(client)
    target = rows[1] if usage == 'second_year' else rows[0]
    with db() as conn:
        if usage == 'shared':
            raw_course(conn, 'test-course', 's2', '2026-11-05', pid='p2')
            conn.execute('INSERT INTO planning_course_groups VALUES(?,?,?)', ('test-course', 'p1', target['id']))
        else:
            day = {'primary': '2026-11-05', 'outside_year': '2027-08-12', 'second_year': '2027-11-05'}[usage]
            raw_course(conn, 'test-course', target['id'], day)
            # The primary course still protects the subject without its group row.
            conn.execute("DELETE FROM planning_course_groups WHERE course_id='test-course'")
    before = state(db)
    response = call(client, '/subject-catalog/'+item['id'], dict(version=item['version']), 'DELETE')
    assert response.status_code == 409, response.json
    issue = response.json['conflicts'][0]
    assert issue['type'] == 'subject_used' and issue['subject_id'] == target['id']
    assert issue['promotion_id'] == 'p1' and issue['period_id'] == target['period_id']
    assert issue['course_count'] == 1 and issue['study_year'] == target['study_year']
    assert state(db) == before


def test_gradebook_protects_empty_preparations_too(annual, client, db):
    import teaching
    item, _ = prepared(client)
    with db() as conn:
        teaching.schema(conn)
        conn.execute('INSERT INTO teaching_homework_groups VALUES(?,?,?)', ('evaluation-history', 'p1', item['id']))
    before = state(db)
    response = call(client, '/subject-catalog/'+item['id'], {}, 'DELETE')
    assert response.status_code == 409 and 'notes' in response.json['message']
    assert state(db) == before
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM teaching_homework_groups WHERE subject_id=?', (item['id'],)).fetchone()[0] == 1


def test_late_database_failure_rolls_back_deleted_preparations(annual, client, db):
    item, _ = prepared(client)
    with db() as conn:
        conn.execute("CREATE TRIGGER prevent_test_delete BEFORE DELETE ON planning_subject_catalog WHEN OLD.name='TEST' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    before = state(db)
    assert call(client, '/subject-catalog/'+item['id'], {}, 'DELETE').status_code == 409
    assert state(db) == before


def test_stale_editor_cannot_delete_a_changed_subject(annual, client, db):
    item, _ = prepared(client)
    assert call(client, '/subject-catalog/'+item['id'], dict(name='TEST modifié'), 'PUT').status_code == 200
    before = state(db)
    for version in (item['version'], True, '2'):
        response = call(client, '/subject-catalog/'+item['id'], dict(version=version), 'DELETE')
        assert response.status_code == 409
        assert state(db) == before


def test_unknown_subject_and_authentication(client, app, db):
    item = create(client)
    path = BASE+'/subject-catalog/'+item['id']
    assert app.test_client().delete(path, json={}).status_code == 403
    assert client.delete(path, json={}).status_code == 400
    assert call(client, '/subject-catalog/unknown', {}, 'DELETE').status_code == 404
    assert call(client, path, dict(version=item['version']), 'DELETE').status_code == 200
