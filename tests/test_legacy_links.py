import hashlib
import hmac
import sqlite3
from datetime import datetime, timezone

import pytest

from legacy_links import snapshot_legacy_links, verify_legacy_link

NOW = 1792860000
TOKEN = 'old-valid-high-entropy-token-0123456789'
NEW_TOKEN = 'new-strong-key-token-9876543210987654'


def signed(token, key='dev-secret'):
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    def connect():
        return sqlite3.connect(path)
    with connect() as conn:
        conn.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY, token_confirm TEXT,token_confirm_exp TEXT,token_reconfirm TEXT,token_reconfirm_exp TEXT,replace_token TEXT,replace_token_exp TEXT)')
        conn.execute('INSERT INTO candidats(id,token_confirm,token_confirm_exp) VALUES(?,?,?)', ('person', TOKEN, datetime.fromtimestamp(NOW + 3600, timezone.utc).isoformat()))
    return connect


def test_old_live_link_preserved_under_both_actual_old_default_configurations(db):
    snapshot_legacy_links(db, now=NOW)
    assert verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW)
    assert verify_legacy_link(db, TOKEN, signed(TOKEN, 'change-me'), now=NOW)
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN, 'wrong-key'), now=NOW)


def test_snapshot_once_never_adds_new_tokens_or_accepts_general_weak_fallback(db):
    assert snapshot_legacy_links(db, now=NOW) == 2
    with db() as conn:
        conn.execute('INSERT INTO candidats(id,token_confirm) VALUES(?,?)', ('new-person', NEW_TOKEN))
    assert snapshot_legacy_links(db, now=NOW + 10) == 0
    assert not verify_legacy_link(db, NEW_TOKEN, signed(NEW_TOKEN), now=NOW + 10)
    assert not verify_legacy_link(db, 'unrecorded-token-with-enough-entropy', signed('unrecorded-token-with-enough-entropy'), now=NOW)


def test_expired_and_rotated_tokens_are_rejected(db):
    snapshot_legacy_links(db, now=NOW)
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW + 3600)
    with db() as conn:
        conn.execute('UPDATE candidats SET token_confirm=? WHERE id=?', (NEW_TOKEN, 'person'))
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW)


def test_deleted_candidate_removes_legacy_access(db):
    snapshot_legacy_links(db, now=NOW)
    with db() as conn:
        conn.execute('DELETE FROM candidats')
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW)


def test_no_raw_token_in_new_snapshot_table(db):
    snapshot_legacy_links(db, now=NOW)
    with db() as conn:
        rows = conn.execute('SELECT * FROM legacy_signed_links').fetchall()
    assert all(TOKEN not in row for row in rows)
    assert all(row[0] == hashlib.sha256(TOKEN.encode()).hexdigest() for row in rows)


def test_missing_expiry_is_bounded_and_malformed_expiry_denied(db):
    with db() as conn:
        conn.execute('UPDATE candidats SET token_confirm_exp=NULL')
        conn.execute('INSERT INTO candidats(id,token_confirm,token_confirm_exp) VALUES(?,?,?)', ('malformed', NEW_TOKEN, 'invalid-date'))
    snapshot_legacy_links(db, now=NOW)
    assert verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW + 29 * 86400)
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW + 30 * 86400)
    assert not verify_legacy_link(db, NEW_TOKEN, signed(NEW_TOKEN), now=NOW)


def test_expired_tokens_not_snapshotted(db):
    with db() as conn:
        conn.execute('UPDATE candidats SET token_confirm_exp=?', (datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),))
    assert snapshot_legacy_links(db, now=NOW) == 0


def test_reconfirm_and_replace_tokens_preserved(db):
    with db() as conn:
        conn.execute('UPDATE candidats SET token_reconfirm=?,replace_token=?', (NEW_TOKEN, 'replace-high-entropy-token-123456789'))
    snapshot_legacy_links(db, now=NOW)
    assert verify_legacy_link(db, NEW_TOKEN, signed(NEW_TOKEN), now=NOW)
    assert verify_legacy_link(db, 'replace-high-entropy-token-123456789', signed('replace-high-entropy-token-123456789'), now=NOW)


def test_legacy_verifier_fails_closed_without_snapshot(db):
    assert not verify_legacy_link(db, TOKEN, signed(TOKEN), now=NOW)


@pytest.mark.parametrize('bad_signature', ['é', '', '0' * 64, None])
def test_invalid_signature_inputs_are_safe(db, bad_signature):
    snapshot_legacy_links(db, now=NOW)
    assert not verify_legacy_link(db, TOKEN, bad_signature, now=NOW)
