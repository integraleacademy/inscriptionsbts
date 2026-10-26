"""Diploma catalogue migration, shared curricula and independent planning budgets."""
import json
from unittest.mock import patch

import pytest

import planning
import subject_catalog as catalog
import subject_references as refs
from test_planning import db, app, client, call, BASE
from test_subject_references import provider_result, KEY


def create(client, **updates):
    payload = dict(name='Culture commune', diploma_codes=['MOS', 'MCO'], color='#2563eb',
        diploma_details={'MOS': dict(coefficient=3, objectives='Programme MOS'), 'MCO': dict(coefficient=4, objectives='Programme MCO')})
    payload.update(updates)
    result = call(client, '/subject-catalog', payload)
    assert result.status_code == 200, result.json
    return result.json['subject']


def test_catalogue_can_be_created_without_any_promotion(client, db):
    with db() as conn:
        conn.execute('DELETE FROM planning_subjects')
        conn.execute('DELETE FROM promotions')
    item = create(client)
    assert item['diploma_codes'] == ['MCO', 'MOS']
    assert item['planning_count'] == 0
    assert item['diploma_details']['MCO']['coefficient'] == 4
    assert item['diploma_details']['MOS']['coefficient'] == 3
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_subjects').fetchone()[0] == 0


def test_subject_used_by_independent_evaluation_cannot_be_deleted(client, db):
    item=create(client)
    import teaching
    with db() as conn:
        teaching.schema(conn)
        conn.execute('INSERT INTO teaching_homework_groups VALUES(?,?,?)',('evaluation-history','p1',item['id']))
    response=call(client,'/subject-catalog/'+item['id'],{},'DELETE')
    assert response.status_code==409
    with db() as conn:
        assert conn.execute('SELECT 1 FROM planning_subject_catalog WHERE id=?',(item['id'],)).fetchone()


def test_migration_groups_same_subject_by_diploma_without_rewriting_history(client, db):
    with db() as conn:
        conn.execute("UPDATE promotions SET bts='MOS' WHERE id='p2'")
        conn.execute("UPDATE planning_subjects SET name='Culture générale' WHERE id IN ('s1','s2')")
        refs.save_details(conn, 's1', dict(coefficient=4, objectives='Programme MCO', source_url=refs.MOS_URL))
        refs.save_details(conn, 's2', dict(coefficient=3, objectives='Programme MOS'))
        conn.execute("INSERT INTO planning_courses VALUES('history','p1','s1','t1',NULL,'2027-01-05',510,630,'Cours conservé',1,'now','now')")
        conn.execute("INSERT INTO planning_course_groups VALUES('history','p1','s1')")
        before = {table: [tuple(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY 1')]
            for table in ['planning_subjects', 'planning_subject_details', 'planning_courses', 'planning_course_groups']}
    response = client.get(BASE+'/catalog').json
    matches = [item for item in response['subject_catalog'] if item['name'] == 'Culture générale']
    assert len(matches) == 1
    shared = matches[0]
    assert shared['diploma_codes'] == ['MCO', 'MOS']
    assert shared['planning_count'] == 2
    assert shared['diploma_details']['MCO']['coefficient'] == 4
    assert shared['diploma_details']['MOS']['coefficient'] == 3
    with db() as conn:
        planning.ensure_planning_schema(conn)
        planning.ensure_planning_schema(conn)
        for table, rows in before.items():
            assert [tuple(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY 1')] == rows
        assert catalog.linked_subject(conn, 's1') == catalog.linked_subject(conn, 's2') == shared['id']
    assert next(item for item in response['subjects'] if item['id'] == 's1')['scheduled_minutes'] == 120


def test_duplicate_name_adds_diploma_by_editing_existing_subject(client):
    item = create(client, diploma_codes=['MOS'], diploma_details={'MOS': dict(coefficient=3)})
    duplicate = call(client, '/subject-catalog', dict(name='  CULTURE COMMUNE ', diploma_codes=['MCO']))
    assert duplicate.status_code == 409
    updated = call(client, '/subject-catalog/'+item['id'], dict(version=item['version'], diploma_codes=['MOS', 'MCO'],
        diploma_details={'MCO': dict(coefficient=4)}), 'PUT')
    assert updated.status_code == 200, updated.json
    assert updated.json['subject']['diploma_details']['MOS']['coefficient'] == 3
    assert updated.json['subject']['diploma_details']['MCO']['coefficient'] == 4
    stale = call(client, '/subject-catalog/'+item['id'], dict(version=item['version'], name='Écrasement ancien'), 'PUT')
    assert stale.status_code == 409


@pytest.mark.parametrize('codes', [None, [], 'MOS', ['UNKNOWN'], ['MOS', 'MOS'], [True]])
def test_invalid_diplomas_rejected(client, codes):
    assert call(client, '/subject-catalog', dict(name='Invalide', diploma_codes=codes)).status_code == 400


def test_diploma_filter_and_permissions(client, app):
    shared = create(client)
    create(client, name='Gestion spécifique', diploma_codes=['MCO'], diploma_details={})
    result = client.get(BASE+'/subject-catalog?diploma=MOS')
    assert result.status_code == 200
    assert [item['id'] for item in result.json['subjects']] == [shared['id']]
    assert client.get(BASE+'/subject-catalog?diploma=invalid').status_code == 400
    anonymous = app.test_client()
    assert anonymous.get(BASE+'/subject-catalog').status_code == 403
    for path, method in [('/subject-catalog', 'POST'), ('/subject-catalog/'+shared['id'], 'PUT'), ('/subject-catalog/'+shared['id'], 'DELETE')]:
        assert anonymous.open(BASE+path, method=method, json={}).status_code == 403
        assert client.open(BASE+path, method=method, json={}).status_code == 400


def test_one_catalogue_subject_has_independent_teachers_and_budgets(client, db):
    item = create(client)
    first = call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id='p1', trainer_id='t1', planned_hours=40))
    second = call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id='p2', trainer_id='t2', planned_hours=80))
    assert first.status_code == second.status_code == 200
    first_id, second_id = first.json['subject']['id'], second.json['subject']['id']
    assert first_id != second_id
    assert first.json['subject']['catalog_subject_id'] == second.json['subject']['catalog_subject_id'] == item['id']
    assert call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id='p1', trainer_id='t2', planned_hours=20)).status_code == 409
    updated = call(client, '/subject-catalog/'+item['id'], dict(name='Culture et expression', diploma_details={'MCO': dict(coefficient=6)}), 'PUT')
    assert updated.status_code == 200, updated.json
    snapshot = client.get(BASE+'/catalog').json
    allocations = {row['id']: row for row in snapshot['subjects'] if row['catalog_subject_id'] == item['id']}
    assert allocations[first_id]['planned_hours'] == 40 and allocations[first_id]['trainer_id'] == 't1'
    assert allocations[second_id]['planned_hours'] == 80 and allocations[second_id]['trainer_id'] == 't2'
    assert all(row['name'] == 'Culture et expression' and row['coefficient'] == 6 for row in allocations.values())
    assert updated.json['subject']['diploma_details']['MOS']['coefficient'] == 3
    assert call(client, '/subject-catalog/'+item['id'], method='DELETE').status_code == 409
    removed = call(client, '/subject-catalog/'+item['id'], dict(diploma_codes=['MOS']), 'PUT')
    assert removed.status_code == 409
    assert call(client, '/subjects/'+first_id, method='DELETE').status_code == 200
    assert call(client, '/subjects/'+second_id, method='DELETE').status_code == 200
    assert any(row['id'] == item['id'] for row in client.get(BASE+'/subject-catalog').json['subjects'])
    assert call(client, '/subject-catalog/'+item['id'], dict(diploma_codes=['MOS']), 'PUT').status_code == 200


def test_planning_can_only_prepare_subjects_of_its_diploma(client):
    item = create(client, diploma_codes=['MOS'], diploma_details={})
    result = call(client, '/subjects', dict(catalog_subject_id=item['id'], promotion_id='p1', trainer_id='t1', planned_hours=40))
    assert result.status_code == 400
    assert 'BTS' in result.json['message']


def test_promotion_diploma_change_requires_compatible_subjects(client, db):
    client.get(BASE+'/catalog')
    with db() as conn:
        issues = planning.validate_promotion_change(conn, 'p1', {'bts': 'MOS'})
    assert any(item['type'] == 'subject_diploma' for item in issues)


def test_official_import_reuses_subject_for_another_diploma_without_allocations(client, db, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    ids = []
    for code, coefficient in [('MOS', 3), ('MCO', 4)]:
        with patch.object(refs, 'provider', return_value={'id': 'resp_shared', 'status': 'queued'}):
            started = call(client, '/references/analyze', dict(diploma_code=code, exam_year=2029, source_url=refs.MOS_URL))
        assert started.status_code == 202, started.json
        assert started.json['diploma_code'] == code and 'promotion_id' not in started.json
        response = provider_result()
        data = json.loads(response['output'][1]['content'][0]['text'])
        data['subjects'][0].update(coefficient=coefficient, objectives='Objectif '+code)
        response['output'][1]['content'][0]['text'] = json.dumps(data)
        jid = started.json['job_id']
        with patch.object(refs, 'provider', return_value=response):
            assert client.get(BASE+'/references/'+jid).json['status'] == 'ready'
        imported = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1')]))
        assert imported.status_code == 200, imported.json
        ids.append(imported.json['subject_ids'][0])
    assert ids[0] == ids[1]
    item = next(row for row in client.get(BASE+'/subject-catalog').json['subjects'] if row['id'] == ids[0])
    assert item['diploma_codes'] == ['MCO', 'MOS']
    assert item['diploma_details']['MOS']['coefficient'] == 3
    assert item['diploma_details']['MCO']['coefficient'] == 4
    assert item['diploma_details']['MOS']['objectives'] == 'Objectif MOS'
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_subjects').fetchone()[0] == 4


def test_catalogue_update_preserves_official_provenance(client, db):
    with db() as conn:
        planning.ensure_planning_schema(conn)
        sid = catalog.import_subject(conn, 'Imported', 'MOS', {'coefficient': 3, 'full_text': {'Texte': 'Texte conservé'}, 'source_url': refs.MOS_URL, 'import_id': 'original'})
    result = call(client, '/subject-catalog/'+sid, dict(diploma_details={'MOS': dict(coefficient=5, full_text={}, import_id='forged')}), 'PUT')
    assert result.status_code == 200
    data = result.json['subject']['diploma_details']['MOS']
    assert data['coefficient'] == 5 and data['full_text'] == {'Texte': 'Texte conservé'} and data['import_id'] == 'original'
