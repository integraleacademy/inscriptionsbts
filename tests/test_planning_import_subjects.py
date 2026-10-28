"""Import catalogue subjects into an unprepared year without separate setup."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json

import pytest

import planning
import subject_catalog
from test_planning import db, app, client, admin
from test_planning_import import analyze, preview, commit, count, pdf_bytes, two_weeks
from test_planning_import_trainers import records


@pytest.fixture
def catalog(db):
    with db() as conn:
        planning.ensure_planning_schema(conn)
        return {
            'english': subject_catalog.import_subject(conn, 'Anglais', 'MCO',
                dict(annual_hours_first=30, annual_hours_second=45)),
            'french': subject_catalog.import_subject(conn, 'Expression', 'MCO', {}),
            'foreign': subject_catalog.import_subject(conn, 'Sécurité', 'MOS', {}),
        }


def allocations(db, catalog_id):
    with db() as conn:
        return [dict(r) for r in conn.execute('''SELECT s.*,y.period_id FROM planning_subjects s
            JOIN planning_subject_catalog_links l ON l.planning_subject_id=s.id
            JOIN planning_subject_periods y ON y.subject_id=s.id WHERE l.subject_id=?''', (catalog_id,))]


def review_catalog(client, extracted, **extra):
    return preview(client, extracted['source_token'], **dict(
        dict(mappings=extracted['mappings'], assign_trainers=True, new_trainers=extracted['new_trainers']), **extra))


def test_empty_second_year_can_use_catalogue_with_its_own_annual_hours(client, db, catalog):
    with db() as conn:
        conn.execute("UPDATE promotions SET date_debut='2025-09-01',date_fin='2027-07-01',niveau=2 WHERE id='p1'")
        planning.ensure_planning_schema(conn)
        # Existing allocations stay in year one; year two starts empty.
        for table, key in [('planning_subject_catalog_links','planning_subject_id'),
                           ('planning_subject_details','subject_id'), ('planning_subjects','id')]:
            conn.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT subject_id FROM planning_subject_periods WHERE period_id='p1:2')")
        conn.execute("DELETE FROM planning_subject_periods WHERE period_id='p1:2'")
        before = [tuple(r) for r in conn.execute('SELECT * FROM planning_subjects ORDER BY id')]
    extracted = analyze(client, pdf_bytes(subject='Anglais'), period='p1:2').json
    choice = next(s for s in extracted['subjects'] if s['name'] == 'Anglais')
    assert choice['prepare_on_import'] and choice['planned_hours'] == 45
    assert choice['study_year'] == 2
    assert extracted['mappings']['subjects'] == {'Anglais': choice['id']}
    assert not any(s['name'] == 'Sécurité' for s in extracted['subjects'])
    reviewed = review_catalog(client, extracted).json
    assert reviewed['summary']['ready'] == 1, reviewed
    assert reviewed['subject_preparations'][0]['planned_hours'] == 45
    with db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT * FROM planning_subjects ORDER BY id')] == before
    assert not allocations(db, catalog['english']) and count(db) == 0
    saved = commit(client, reviewed['preview_token'])
    assert saved.status_code == 200 and saved.json['prepared_subjects'] == 1, saved.json
    subject = allocations(db, catalog['english'])[0]
    assert (subject['period_id'], subject['planned_hours'], subject['trainer_id']) == ('p1:2',45,'t1')
    repeated = commit(client, reviewed['preview_token']).json
    assert repeated['count'] == 0 and repeated['prepared_subjects'] == 0 and repeated['duplicates'] == 1
    again = analyze(client, pdf_bytes(subject='Anglais'), period='p1:2').json
    assert again['mappings']['subjects'] == {'Anglais': subject['id']}
    assert len([s for s in again['subjects'] if s['name'] == 'Anglais']) == 1
    with db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT * FROM planning_subjects WHERE id!=? ORDER BY id', (subject['id'],))] == before


def test_missing_budget_can_be_completed_in_import_and_does_not_change_catalogue(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Expression')).json
    key = extracted['mappings']['subjects']['Expression']
    missing = review_catalog(client, extracted).json
    assert missing['summary']['blocked'] == 1 and not missing['subject_preparations']
    assert 'volume annuel' in missing['items'][0]['issues'][0]
    reviewed = review_catalog(client, extracted, subject_hours={key: 12}).json
    assert reviewed['summary']['ready'] == 1
    assert commit(client, reviewed['preview_token']).json['prepared_subjects'] == 1
    assert allocations(db, catalog['french'])[0]['planned_hours'] == 12
    with db() as conn:
        assert subject_catalog.diploma_details(conn, catalog['french'], 'MCO') == {}


@pytest.mark.parametrize('hours', [0, -2, 'NaN', 'Infinity', True, [], {}, 6000, 1])
def test_invalid_or_insufficient_annual_budget_does_not_create_subject(client, db, catalog, hours):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    key = extracted['mappings']['subjects']['Anglais']
    result = review_catalog(client, extracted, subject_hours={key: hours}).json
    assert result['summary']['blocked'] == 1 and not result['subject_preparations']
    assert not allocations(db, catalog['english'])


def test_truncated_labels_share_one_catalogue_allocation_and_combined_budget(client, db, catalog):
    extracted = analyze(client, two_weeks(subject='Anglais')).json
    key = 'catalog:' + catalog['english']
    mappings = dict(extracted['mappings'], subjects={'Matiere s1':key, 'Anglais':key})
    reviewed = review_catalog(client, extracted, mappings=mappings, subject_hours={key:3}).json
    assert reviewed['summary']['ready'] == 1 and reviewed['summary']['blocked'] == 1
    assert len(reviewed['subject_preparations']) == 1
    assert commit(client, reviewed['preview_token'], ['0']).json['prepared_subjects'] == 1
    assert len(allocations(db, catalog['english'])) == 1


def test_deselected_courses_never_prepare_their_catalogue_subject(client, db, catalog):
    extracted = analyze(client, two_weeks(subject='Anglais')).json
    reviewed = review_catalog(client, extracted).json
    assert reviewed['summary']['ready'] == 2
    assert commit(client, reviewed['preview_token'], ['0']).json['prepared_subjects'] == 0
    assert not allocations(db, catalog['english'])


def test_foreign_diploma_or_removed_catalogue_link_is_rejected(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    mappings = dict(extracted['mappings'], subjects={'Anglais':'catalog:' + catalog['foreign']})
    wrong = review_catalog(client, extracted, mappings=mappings).json
    assert wrong['summary']['blocked'] == 1
    reviewed = review_catalog(client, extracted).json
    with db() as conn:
        conn.execute('DELETE FROM planning_subject_diplomas WHERE subject_id=?', (catalog['english'],))
    assert commit(client, reviewed['preview_token']).status_code == 409
    assert not allocations(db, catalog['english']) and count(db) == 0


def test_concurrent_preparation_is_reused_without_overwriting_its_budget(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    reviewed = review_catalog(client, extracted).json
    with db() as conn:
        conn.execute("INSERT INTO planning_subjects VALUES('concurrent','p1','Anglais','t2','#2563eb',1)")
        conn.execute("INSERT INTO planning_subject_periods VALUES('concurrent','p1:1')")
        subject_catalog.link_allocation(conn, 'concurrent', catalog['english'])
    assert commit(client, reviewed['preview_token']).status_code == 409
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=10 WHERE id='concurrent'")
    saved = commit(client, reviewed['preview_token']).json
    assert saved['count'] == 1 and saved['prepared_subjects'] == 0
    assert len(allocations(db, catalog['english'])) == 1
    subject = allocations(db, catalog['english'])[0]
    assert subject['trainer_id'] == 't2' and subject['planned_hours'] == 10


def test_concurrent_imports_create_one_allocation_and_one_course(app, client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    with ThreadPoolExecutor(max_workers=2) as pool:
        reviews = list(pool.map(lambda _: review_catalog(admin(app), extracted), range(2)))
    assert all(r.status_code == 200 for r in reviews)
    first, second = [r.json for r in reviews]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda token: commit(admin(app), token),
                               [first['preview_token'],second['preview_token']]))
    assert sorted(r.json['count'] for r in results) == [0,1]
    assert sorted(r.json['prepared_subjects'] for r in results) == [0,1]
    assert len(allocations(db, catalog['english'])) == 1 and count(db) == 1


def test_deleted_preparation_cannot_be_recreated_without_review(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    with db() as conn:
        conn.execute("INSERT INTO planning_subjects VALUES('concurrent','p1','Anglais','t2','#2563eb',10)")
        conn.execute("INSERT INTO planning_subject_periods VALUES('concurrent','p1:1')")
        subject_catalog.link_allocation(conn, 'concurrent', catalog['english'])
    reviewed = review_catalog(client, extracted).json
    assert reviewed['summary']['ready'] == 1 and not reviewed['subject_preparations']
    with db() as conn:
        conn.execute("DELETE FROM planning_subject_catalog_links WHERE planning_subject_id='concurrent'")
        conn.execute("DELETE FROM planning_subject_periods WHERE subject_id='concurrent'")
        conn.execute("DELETE FROM planning_subjects WHERE id='concurrent'")
    assert commit(client, reviewed['preview_token']).status_code == 409
    assert not allocations(db, catalog['english']) and count(db) == 0


def test_subject_and_trainer_assignment_roll_back_if_course_cannot_be_saved(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais', teacher='M. NOM unassigned P.')).json
    reviewed = review_catalog(client, extracted).json
    assert reviewed['summary']['ready'] == 1
    with db() as conn:
        conn.execute("CREATE TRIGGER reject_course BEFORE INSERT ON planning_courses BEGIN SELECT RAISE(ABORT,'failure'); END")
    assert commit(client, reviewed['preview_token']).status_code == 409
    assert not allocations(db, catalog['english']) and count(db) == 0
    with db() as conn:
        assert not conn.execute("SELECT 1 FROM trainer_promotions WHERE trainer_id='unassigned' AND promotion_id='p1'").fetchone()


def test_catalogue_budget_edits_do_not_change_explicitly_reviewed_new_budget(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    reviewed = review_catalog(client, extracted).json
    with db() as conn:
        conn.execute('UPDATE planning_subject_diplomas SET data=? WHERE subject_id=?',
                     (json.dumps(dict(annual_hours_first=50)), catalog['english']))
    assert commit(client, reviewed['preview_token']).json['prepared_subjects'] == 1
    assert allocations(db, catalog['english'])[0]['planned_hours'] == 30


def test_unprepared_subject_still_enforces_calendar_and_holidays(client, db, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais')).json
    assert review_catalog(client, extracted, school_days=False).json['summary']['blocked'] == 1
    holiday = analyze(client, pdf_bytes(subject='Anglais', monday=date(2027,3,29))).json
    assert review_catalog(client, holiday).json['summary']['blocked'] == 1
    assert not allocations(db, catalog['english'])


def test_missing_subject_and_trainer_are_created_together(client, records, catalog):
    extracted = analyze(client, pdf_bytes(subject='Anglais', teacher='Mme NOUVELLE A.')).json
    assert len(extracted['new_trainers']) == 1
    reviewed = review_catalog(client, extracted).json
    assert reviewed['summary']['ready'] == 1
    assert not allocations(records, catalog['english'])
    saved = commit(client, reviewed['preview_token']).json
    assert saved['count'] == saved['prepared_subjects'] == saved['created_trainers'] == 1
    trainer_id = allocations(records, catalog['english'])[0]['trainer_id']
    assert trainer_id == extracted['new_trainers'][0]['id']
    with records() as conn:
        assert conn.execute('SELECT 1 FROM trainer_promotions WHERE trainer_id=? AND promotion_id=?', (trainer_id,'p1')).fetchone()
