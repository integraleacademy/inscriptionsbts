"""Automatic trainer creation stays atomic, explicit and duplicate-safe."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from planning_import_trainers import propose
from trainer_records import ensure_optional_trainer_email
from test_planning import db, app, client, admin, call
from test_planning_import import analyze, preview, commit, count, pdf_bytes, two_weeks
from test_trainer_access import access, csrf, admin_post


@pytest.fixture
def records(db):
    with db() as conn:
        conn.execute('ALTER TABLE trainers RENAME TO old_trainers')
        conn.execute('''CREATE TABLE trainers(id TEXT PRIMARY KEY,nom TEXT NOT NULL,prenom TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,password_hash TEXT,active INTEGER NOT NULL DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,invited_at TEXT)''')
        conn.execute('''INSERT INTO trainers(id,nom,prenom,email,active,version,created_at,updated_at)
            SELECT id,nom,prenom,email,active,version,'before','before' FROM old_trainers''')
        conn.execute('DROP TABLE old_trainers')
    return db


def missing(client, content=None):
    return analyze(client, content or pdf_bytes(teacher='Mme EXEMPLE P.')).json


def creation_preview(client, extracted, **updates):
    data = dict(mappings=extracted['mappings'], new_trainers=extracted['new_trainers'], assign_trainers=True)
    data.update(updates)
    return preview(client, extracted['source_token'], **data)


def test_missing_trainer_created_without_email_only_at_commit_and_reimport_is_idempotent(client, records):
    extracted = missing(client)
    assert len(extracted['new_trainers']) == 1
    draft = extracted['new_trainers'][0]
    assert (draft['nom'], draft['prenom'], draft['email']) == ('EXEMPLE', 'P', '')
    assert extracted['mappings']['subject_trainers']['Matiere s1'] == draft['id']
    reviewed = creation_preview(client, extracted).json
    assert reviewed['summary']['ready'] == 1 and len(reviewed['trainer_creations']) == 1
    with records() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainers').fetchone()[0] == 4
        assert next(c for c in conn.execute('PRAGMA table_info(trainers)') if c[1] == 'email')[3] == 1
    saved = commit(client, reviewed['preview_token']).json
    assert saved['count'] == 1 and saved['created_trainers'] == 1
    with records() as conn:
        trainer = dict(conn.execute('SELECT * FROM trainers WHERE id=?', (draft['id'],)).fetchone())
        assert trainer['email'] is None and trainer['password_hash'] is None and trainer['invited_at'] is None
        assert trainer['version'] == 1 and trainer['active'] == 1
        assert conn.execute('SELECT 1 FROM trainer_promotions WHERE trainer_id=? AND promotion_id=?', (draft['id'], 'p1')).fetchone()
    repeated = commit(client, reviewed['preview_token']).json
    assert repeated['count'] == 0 and repeated['created_trainers'] == 0 and repeated['duplicates'] == 1
    next_analysis = missing(client)
    assert not next_analysis['new_trainers']
    assert next_analysis['mappings']['subject_trainers']['Matiere s1'] == draft['id']
    assert creation_preview(client, next_analysis).json['summary']['duplicate'] == 1


def test_one_missing_person_is_reused_for_several_subjects_and_can_be_completed(client, records):
    # Two weeks share the same missing source name, despite different subjects.
    with records() as conn:
        conn.execute("UPDATE trainers SET nom='ANOTHER' WHERE id='t1'")
    extracted = missing(client, two_weeks(subject='Matiere s3'))
    assert len(extracted['new_trainers']) == 1
    draft = extracted['new_trainers'][0]
    assert set(extracted['mappings']['subject_trainers'].values()) == {draft['id']}
    draft.update(prenom='Paul', email='paul@example.test')
    result = creation_preview(client, extracted).json
    assert result['summary']['ready'] == 2 and len(result['trainer_creations']) == 1
    assert commit(client, result['preview_token'], ['0','1']).json['created_trainers'] == 1
    with records() as conn:
        assert tuple(conn.execute('SELECT prenom,email FROM trainers WHERE id=?', (draft['id'],)).fetchone()) == ('Paul','paul@example.test')
        assert conn.execute('SELECT COUNT(DISTINCT trainer_id) FROM planning_courses').fetchone()[0] == 1


def test_deselected_or_blocked_courses_never_create_their_trainer(client, records):
    extracted = missing(client, two_weeks(subject='Matiere s3', teacher='Mme EXEMPLE P.'))
    result = creation_preview(client, extracted).json
    assert result['summary']['ready'] == 2
    assert commit(client, result['preview_token'], ['0']).json['created_trainers'] == 0
    with records() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainers').fetchone()[0] == 4
        conn.execute("UPDATE planning_subjects SET planned_hours=0 WHERE id='s3'")
    assert commit(client, result['preview_token'], ['1']).status_code == 409
    with records() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainers').fetchone()[0] == 4


def test_failed_course_insert_rolls_back_new_record_assignment_and_schema(client, records):
    result = creation_preview(client, missing(client)).json
    with records() as conn:
        conn.execute("CREATE TRIGGER reject_course BEFORE INSERT ON planning_courses BEGIN SELECT RAISE(ABORT,'failure'); END")
    assert commit(client, result['preview_token']).status_code == 409
    with records() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainers').fetchone()[0] == 4
        assert next(c for c in conn.execute('PRAGMA table_info(trainers)') if c[1] == 'email')[3] == 1
        assert not conn.execute("SELECT 1 FROM trainer_promotions WHERE trainer_id LIKE 'import-%'").fetchone()
    assert count(records) == 0


def test_concurrent_creation_and_double_submission_cannot_duplicate_person(app, client, records):
    first = creation_preview(client, missing(client)).json
    other = creation_preview(client, missing(client)).json
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _:commit(admin(app),first['preview_token']), range(2)))
    assert sorted(r.json['created_trainers'] for r in responses) == [0,1]
    assert commit(client, other['preview_token']).status_code == 409
    with records() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trainers WHERE nom='EXEMPLE'").fetchone()[0] == 1


@pytest.mark.parametrize('updates', [{'email':'invalid'}, {'nom':''}, {'prenom':[]}, {'id':'forged'}])
def test_invalid_draft_cannot_be_used(client, records, updates):
    extracted = missing(client)
    extracted['new_trainers'][0].update(updates)
    assert creation_preview(client, extracted).status_code == 400
    assert count(records) == 0


def test_draft_cannot_impersonate_existing_name_email_or_disabled_account(client, records):
    extracted = missing(client)
    extracted['new_trainers'][0]['email'] = 't1@example.test'
    assert creation_preview(client, extracted).status_code == 409
    extracted['new_trainers'][0].update(email='',nom='NOM inactive',prenom='P')
    assert creation_preview(client, extracted).status_code == 409
    inactive = analyze(client, pdf_bytes(teacher='M. NOM inactive P.')).json
    assert inactive['new_trainers'] == [] and inactive['trainer_warnings']


def test_ambiguous_initials_are_not_treated_as_missing_and_aliases_share_one_draft():
    existing = [dict(id=str(i),nom='EXEMPLE',prenom=p,active=1) for i,p in enumerate(['Paul','Pierre'])]
    drafts, matches, warnings = propose(['M. EXEMPLE P.'], existing)
    assert not drafts and not matches and warnings
    drafts, matches, warnings = propose(['M. EXEMPLE P.', 'M. EXEMPLE Paul'], [])
    assert len(drafts) == 1 and len(set(matches.values())) == 1 and drafts[0]['prenom'] == 'Paul'
    drafts, matches, _ = propose(['Mme EXEMPLE Jeanne Marie'], [dict(id='known',nom='EXEMPLE',prenom='Jeanne Marie',active=1)])
    assert not drafts and matches == {'Mme EXEMPLE Jeanne Marie':'known'}


def test_email_migration_preserves_records_constraints_indexes_and_triggers(records):
    with records() as conn:
        before = [tuple(r) for r in conn.execute('SELECT * FROM trainers ORDER BY id')]
        conn.execute('CREATE INDEX trainer_name_idx ON trainers(nom)')
        conn.execute("CREATE TRIGGER protect_name BEFORE UPDATE OF nom ON trainers WHEN new.nom='' BEGIN SELECT RAISE(ABORT,'empty name'); END")
        ensure_optional_trainer_email(conn)
        ensure_optional_trainer_email(conn)
        assert [tuple(r) for r in conn.execute('SELECT * FROM trainers ORDER BY id')] == before
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='trainer_name_idx'").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE trainers SET nom='' WHERE id='t1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE trainers SET email='t1@example.test' WHERE id='t2'")
        conn.execute("UPDATE trainers SET email=NULL WHERE id IN ('t1','t2')")
        assert conn.execute('SELECT COUNT(*) FROM trainers WHERE email IS NULL').fetchone()[0] == 2


def test_simultaneous_email_migrations_preserve_the_same_accounts(records):
    def migrate(_):
        with records() as conn:
            ensure_optional_trainer_email(conn)
            return conn.execute('SELECT COUNT(*) FROM trainers').fetchone()[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(migrate, range(2))) == [4,4]


def test_email_can_be_completed_later_and_missing_email_prevents_invitations(access):
    client, connect, mails, _ = access
    csrf(client)
    with connect() as conn:
        conn.execute("INSERT INTO trainers(id,nom,prenom,email,created_at,updated_at) VALUES('import-example','EXEMPLE','P',NULL,'now','now')")
    assert 'E-mail à renseigner' in client.get('/admin/formateurs').text
    detail = client.get('/admin/formateurs/import-example?tab=account')
    assert detail.status_code == 200 and 'E-mail à renseigner' in detail.text
    assert admin_post(access, 'import-example', 'send-access').status_code == 400
    assert mails == []
    assert admin_post(access, 'import-example', 'update', nom='EXEMPLE',prenom='Paul',email='',assignments=[]).status_code == 200
    assert admin_post(access, 'import-example', 'update', nom='EXEMPLE',prenom='Paul',email='paul@example.test',assignments=[]).status_code == 200
    assert mails == []
    with connect() as conn:
        assert conn.execute("SELECT email FROM trainers WHERE id='import-example'").fetchone()[0] == 'paul@example.test'
    assert admin_post(access, 'import-example', 'send-access').status_code == 200
    assert len(mails) == 1
