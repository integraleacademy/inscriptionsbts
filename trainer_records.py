"""Trainer records may exist for planning before their email is known."""
import re


def ensure_optional_trainer_email(conn):
    columns = list(conn.execute('PRAGMA table_info(trainers)'))
    if not any(c[1] == 'email' and c[3] for c in columns):
        return
    conn.execute('SAVEPOINT trainer_email_optional')
    try:
        conn.execute('UPDATE trainers SET id=id WHERE 0')  # Serialize simultaneous first migrations.
        columns = list(conn.execute('PRAGMA table_info(trainers)'))
        if not any(c[1] == 'email' and c[3] for c in columns):
            conn.execute('RELEASE trainer_email_optional')
            return
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='trainers'").fetchone()[0]
        sql, count = re.subn(r'\bemail\s+TEXT\s+NOT\s+NULL\b', 'email TEXT', sql, count=1, flags=re.I)
        if count != 1:
            raise RuntimeError('Unrecognized trainers email constraint')
        sql = re.sub(r'^(CREATE TABLE\s+)(?:IF NOT EXISTS\s+)?["`\[]?trainers["`\]]?',
                     r'\1trainers_email_optional', sql, count=1, flags=re.I)
        objects = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name='trainers' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        names = ','.join('"' + c[1].replace('"', '""') + '"' for c in columns)
        conn.execute(sql)
        conn.execute(f'INSERT INTO trainers_email_optional({names}) SELECT {names} FROM trainers')
        conn.execute('DROP TABLE trainers')
        conn.execute('ALTER TABLE trainers_email_optional RENAME TO trainers')
        for definition in objects:
            conn.execute(definition)
        conn.execute('RELEASE trainer_email_optional')
    except Exception:
        conn.execute('ROLLBACK TO trainer_email_optional')
        conn.execute('RELEASE trainer_email_optional')
        raise
