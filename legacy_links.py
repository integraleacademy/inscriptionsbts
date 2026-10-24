"""Bounded compatibility for links issued before the October 2026 key rotation.

Only existing, unexpired tokens are snapshotted once. Verification consults that
snapshot; it never signs a new input with a historical/default key.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import re
import sqlite3
import time

_MIGRATION = 'signed-links-before-2026-10-key-rotation'
_TOKEN_COLUMNS = (
    ('token_confirm', 'token_confirm_exp'),
    ('token_reconfirm', 'token_reconfirm_exp'),
    ('replace_token', 'replace_token_exp'),
)
# The old application used one default for Flask and another for link signing.
# No general verification fallback is permitted for either historical value.
_OLD_DEFAULTS = ('dev-secret', 'change-me')


def _expires_at(value, now):
    if not value:
        return now + 30 * 86400
    try:
        expires = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        # Historical values used naive datetime.now() on the UTC Render host.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0


def snapshot_legacy_links(db_connect, *, now=None):
    """Run once after candidate schema initialization, before serving requests."""
    now = time.time() if now is None else now
    with closing(db_connect()) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS legacy_link_migrations (
                name TEXT PRIMARY KEY, completed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS legacy_signed_links (
                token_hash TEXT NOT NULL, signature TEXT NOT NULL,
                candidate_id TEXT NOT NULL, token_column TEXT NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY(token_hash, signature, candidate_id, token_column)
            );
        ''')
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM legacy_link_migrations WHERE name=?', (_MIGRATION,)).fetchone():
            conn.commit()
            return 0
        columns = {row[1] for row in conn.execute('PRAGMA table_info(candidats)')}
        inserted = 0
        for token_column, expiry_column in _TOKEN_COLUMNS:
            if token_column not in columns:
                continue
            expiry_select = expiry_column if expiry_column in columns else 'NULL'
            rows = conn.execute(f'SELECT id,{token_column},{expiry_select} FROM candidats WHERE {token_column} IS NOT NULL').fetchall()
            for candidate_id, token, expiry in rows:
                if not isinstance(token, str) or len(token) < 20:
                    continue
                expires_at = _expires_at(expiry, now)
                if expires_at <= now:
                    continue
                token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
                for old_default in _OLD_DEFAULTS:
                    signature = hmac.new(old_default.encode(), token.encode('utf-8'), hashlib.sha256).hexdigest()
                    conn.execute('INSERT OR IGNORE INTO legacy_signed_links(token_hash,signature,candidate_id,token_column,expires_at) VALUES(?,?,?,?,?)', (token_hash, signature, candidate_id, token_column, expires_at))
                    inserted += 1
        conn.execute('INSERT INTO legacy_link_migrations(name,completed_at) VALUES(?,?)', (_MIGRATION, now))
        conn.commit()
        return inserted


def verify_legacy_link(db_connect, token, signature, *, now=None):
    """Accept a recorded legacy link only while its original token is current."""
    if not isinstance(token, str) or not isinstance(signature, str) or len(token) < 20 or len(token) > 512 or not re.fullmatch(r'[0-9a-f]{64}', signature):
        return False
    now = time.time() if now is None else now
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    try:
        with closing(db_connect()) as conn:
            matches = conn.execute('SELECT signature,candidate_id,token_column FROM legacy_signed_links WHERE token_hash=? AND expires_at>?', (token_hash, now)).fetchall()
            allowed_columns = {column for column, _ in _TOKEN_COLUMNS}
            for stored_sig, candidate_id, token_column in matches:
                if token_column not in allowed_columns or not hmac.compare_digest(stored_sig, signature):
                    continue
                current = conn.execute(f'SELECT {token_column} FROM candidats WHERE id=?', (candidate_id,)).fetchone()
                if current and isinstance(current[0], str) and hmac.compare_digest(current[0].encode('utf-8'), token.encode('utf-8')):
                    return True
    except sqlite3.OperationalError:
        # Missing migration tables must fail closed, including freshly isolated tests.
        return False
    return False
