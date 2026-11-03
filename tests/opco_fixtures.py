"""Synthetic, identity-verified direct OPCO data for tests of contract consumers."""
import json
from akto_sync import schema as akto_schema
from opco_sync import bts_students, roster_key, schema
from wedof_contract_data import STATES


def account(conn):
    schema(conn)
    akto_schema(conn)
    conn.execute("UPDATE opco_accounts SET credential=x'01'")
    conn.execute("UPDATE akto_connection SET credential=x'01' WHERE id=1")


def complete(conn):
    people = bts_students(conn)
    conn.execute("UPDATE opco_accounts SET state='ok',roster=?", (roster_key(people),))
    conn.execute("UPDATE akto_connection SET state='ok',succeeded='test'")
    conn.executemany("INSERT OR IGNORE INTO akto_students VALUES(?,'[]','','test')", [(p['id'],) for p in people])


def contract(conn, cid, ref=None, **changes):
    student = conn.execute('SELECT nom,prenom,date_naissance FROM candidats WHERE id=?',(cid,)).fetchone()
    if not student:
        raise AssertionError(f'Missing fixture student {cid}')
    if not student['date_naissance']:
        conn.execute("UPDATE candidats SET date_naissance='2000-01-01' WHERE id=?",(cid,))
    if ref is None:
        ref = str(1+conn.execute('SELECT count(*) FROM opco_contracts').fetchone()[0])
    item = dict(source='convergence',working_contract_id='ep-'+ref,financer='opcoCfaEp',state='accepted',
                employer_name='Entreprise Exemple',contract_start='2026-09-01',contract_end='2028-08-31',
                apprentice_first_name=student['prenom'],apprentice_last_name=student['nom'],
                apprentice_birth_date=student['date_naissance'] or '2000-01-01',checked_at='2026-11-03T04:00:00+00:00')
    item.update(changes)
    item['state_label'] = STATES[item['state']]
    conn.execute('INSERT INTO opco_contracts VALUES(?,?,?,?)',('ep',ref,cid,json.dumps(item)))
