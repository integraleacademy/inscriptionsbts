"""Contract views served from the CFA's local OPCO records. Page requests never launch a sync."""
from contextlib import closing
import json

from flask import abort, jsonify, render_template

from akto_pilot import contract_card, pilot_record
from akto_portal import START_DATE
from contract_display import billing, display_date, display_stamp, euros
from opco_convergence import PROVIDERS, identity
from opco_sync import bts_students, roster_key, same_contract
from training_programs import BTS_LABELS
from wedof_contract_data import FINANCERS


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def records_by_student(conn, people, *, archives=False):
    students = {p['id']:p for p in people if (p.get('bts') or '').strip().upper() in BTS_LABELS}
    ids, result = list(students), {}
    existing = tables(conn)
    pilot = pilot_record() if not archives else None
    for first in range(0, len(ids), 400):
        group = ids[first:first + 400]
        marks = ','.join('?' for _ in group)
        if {'opco_contracts','opco_accounts'} <= existing:
            source = ("c.provider='filiz'" if archives else
                      "c.provider IN ('opcommerce','mobilites','ep') AND a.credential IS NOT NULL")
            for cid, data, state, provider in conn.execute(f"""SELECT c.candidate_id,c.payload,a.state,c.provider FROM opco_contracts c
                    LEFT JOIN opco_accounts a ON a.provider=c.provider WHERE {source}
                    AND c.candidate_id IN ({marks}) ORDER BY c.ref""", group):
                try:
                    item = json.loads(data)
                except (ValueError, TypeError):
                    continue
                p = students[cid]
                key = identity(p.get('nom'),p.get('prenom'),p.get('date_naissance'))
                if (not isinstance(item,dict) or not all(key) or (item.get('contract_start') or '') < START_DATE or
                        item.get('source') != ('filiz' if archives else 'convergence') or
                        key != identity(item.get('apprentice_last_name'),item.get('apprentice_first_name'),item.get('apprentice_birth_date'))):
                    continue
                if not archives and item.get('financer') != PROVIDERS[provider][0]:
                    continue
                if state == 'error':
                    item['read_warning'] = 'Dernière lecture OPCO en échec. Relevé précédent conservé.'
                result.setdefault(cid,[]).append(item)
        if archives or 'akto_students' not in existing:
            continue
        saved = list(conn.execute(f"""SELECT candidate_id,records,message FROM akto_students
                WHERE candidate_id IN ({marks}) AND records IS NOT NULL""", group))
        if pilot and pilot['candidate_id'] in group and not any(r[0]==pilot['candidate_id'] for r in saved):
            saved.append((pilot['candidate_id'],json.dumps([pilot]),'Dernier relevé AKTO enregistré.'))
        for cid, data, message in saved:
            p = students[cid]
            try:
                raw = json.loads(data)
            except (ValueError, TypeError):
                continue
            for record in (raw if isinstance(raw,list) else []):
                if not isinstance(record,dict) or not record.get('reference') or (record.get('contract_start') or '') < START_DATE:
                    continue
                # New AKTO records retain the identity verified on the agreement. Older records are scoped to their original candidate ID.
                if record.get('apprentice_last_name') and identity(record['apprentice_last_name'],
                        record.get('apprentice_first_name'),record.get('apprentice_birth_date')) != identity(
                        p.get('nom'),p.get('prenom'),p.get('date_naissance')):
                    continue
                item = contract_card(record,p,billing)['item']
                item['akto_record'] = record
                item['read_warning'] = message
                result.setdefault(cid,[]).append(item)
    return result


def directory_contracts(app, conn, rows, *, include_linked_contracts=False):
    records = records_by_student(conn, rows)
    existing = tables(conn)
    accounts = list(conn.execute("SELECT credential IS NOT NULL,state,roster FROM opco_accounts WHERE provider IN ('opcommerce','ep','mobilites')")) if 'opco_accounts' in existing else []
    akto = conn.execute("SELECT credential IS NOT NULL,state,succeeded FROM akto_connection WHERE id=1").fetchone() if 'akto_connection' in existing else None
    configured = any(a[0] for a in accounts) or bool(akto and akto[0])
    complete = False
    if akto and akto[0] and akto[1]=='ok' and len(accounts)==len(PROVIDERS) and all(a[0] and a[1]=='ok' for a in accounts):
        roster = roster_key(bts_students(conn))
        complete = all(a[2] == roster for a in accounts)
    akto_checked = ({r[0] for r in conn.execute("SELECT candidate_id FROM akto_students WHERE seen=? AND records IS NOT NULL AND message=''", (akto[2],))}
                    if complete else set())
    for row in rows:
        items = records.get(row['id'],[])
        row.update(contract='linked',contract_label='À vérifier',contract_needs_check=False)
        if include_linked_contracts:
            row['linked_contracts'] = items
        if items:
            labels = dict.fromkeys(' · '.join(filter(None,(FINANCERS.get(i.get('financer')), i.get('state_label')))) for i in items)
            row.update(contract='yes',contract_label='Contrat d’apprentissage',contract_detail=' / '.join(labels))
        elif (row.get('bts') or '').strip().upper() not in BTS_LABELS:
            row['contract_detail'] = 'La lecture des contrats OPCO concerne les six filières BTS.'
        elif not all(identity(row.get('nom'),row.get('prenom'),row.get('date_naissance'))):
            row['contract_detail'] = 'Identité à compléter pour vérifier les contrats auprès des OPCO.'
        elif row['id'] in akto_checked:
            row.update(contract='no',contract_label='Sans contrat identifié',
                       contract_detail='Aucun contrat depuis le 1er juin 2025 dans les quatre sources OPCO vérifiées.')
        else:
            row['contract_detail'] = 'Les connexions OPCO doivent être renseignées et leur lecture terminée pour vérifier cette fiche.'
        row['contract_needs_check'] = bool(configured and row['contract']=='linked' and
                                           (row.get('bts') or '').strip().upper() in BTS_LABELS)
    return configured


def register_opco_contracts(app, connect, require_admin):
    app.jinja_env.filters.update(wedof_money=euros, wedof_date=display_date, wedof_stamp=display_stamp)
    app.jinja_env.globals['wedof_financers'] = FINANCERS

    @app.get('/admin/candidat/<cid>/contrats-apprentissage')
    def opco_student_contracts(cid):
        if not require_admin():
            abort(403)
        with closing(connect()) as conn:
            person = conn.execute('SELECT * FROM candidats WHERE id=?',(cid,)).fetchone()
            if not person:
                abort(404)
            row = dict(person)
            configured = directory_contracts(app,conn,[row],include_linked_contracts=True)
            archives = records_by_student(conn,[row],archives=True).get(cid,[])
        items = row['linked_contracts']
        panels = []
        if not items:
            panels.append(render_template('_opco_empty.html',row=row))
        for item in items + [old for old in archives if not any(same_contract(old,live) for live in items)]:
            record = item.get('akto_record')
            card = contract_card(record,row,billing) if record else dict(item=item,billing=billing(item))
            card.update(error=item.get('read_warning'),checked_at=item.get('checked_at'),
                        portal=next((info[2] for info in PROVIDERS.values() if info[0]==item.get('financer')),None))
            panels.append(render_template('_wedof_contracts_list.html',contracts=[card],row=row,pilot=record,
                                          direct=True,configured=configured,archived=item.get('source')=='filiz'))
        response = jsonify(ok=True,configured=configured,has_contracts=bool(items),html=''.join(panels))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
