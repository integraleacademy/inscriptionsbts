"""Contract views served from the CFA's local OPCO records. Page requests never launch a sync."""
from contextlib import closing
import json

from flask import abort, jsonify, render_template

from akto_portal import START_DATE
from contract_display import billing, display_date, display_stamp, euros
from opco_convergence import PROVIDERS, FINANCER_BY_PROVIDER, identity
from training_programs import BTS_LABELS
from wedof_contract_data import FINANCERS


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def records_by_student(conn, people, *, archives=False):
    students = {p['id']:p for p in people if (p.get('bts') or '').strip().upper() in BTS_LABELS}
    ids, result = list(students), {}
    existing = tables(conn)
    for first in range(0, len(ids), 400):
        group = ids[first:first + 400]
        marks = ','.join('?' for _ in group)
        if {'opco_contracts','opco_accounts'} <= existing:
            source = ("c.provider='filiz'" if archives else
                      "c.provider IN ('akto','opcommerce','mobilites','ep')")
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
                if not archives and (item.get('financer') != FINANCER_BY_PROVIDER[provider] or
                                     item.get('environment', 'production') != 'production'):
                    continue
                if state == 'error':
                    item['read_warning'] = 'Dernière lecture OPCO en échec. Relevé précédent conservé.'
                result.setdefault(cid,[]).append(item)
        # Portal extracts (akto_students), pilot fixtures and FILIZ archives are not
        # Convergence responses. They must never populate live contracts or KPIs.
    return result


def directory_contracts(app, conn, rows, *, include_linked_contracts=False):
    records = records_by_student(conn, rows)
    existing = tables(conn)
    accounts = list(conn.execute("SELECT credential IS NOT NULL,state,roster FROM opco_accounts WHERE provider IN ('opcommerce','ep','mobilites')")) if 'opco_accounts' in existing else []
    production = conn.execute("SELECT 1 FROM apprenticeship_connections WHERE environment='production' LIMIT 1").fetchone() if 'apprenticeship_connections' in existing else None
    configured = any(a[0] for a in accounts) or bool(production)
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
        else:
            row['contract_detail'] = 'Aucun contrat de production récupéré via l’API Convergence pour cette fiche. Les relevés des portails et les dossiers de recette ne sont pas affichés ici.'
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
        items = row['linked_contracts']
        panels = []
        if not items:
            panels.append(render_template('_opco_empty.html',row=row))
        for item in items:
            card = dict(item=item,billing=billing(item))
            card.update(error=item.get('read_warning'),checked_at=item.get('checked_at'),
                        portal=next((info[2] for info in PROVIDERS.values() if info[0]==item.get('financer')),'https://monespace.akto.fr/'))
            panels.append(render_template('_wedof_contracts_list.html',contracts=[card],row=row,pilot=None,
                                          direct=True,configured=configured,archived=False))
        response = jsonify(ok=True,configured=configured,has_contracts=bool(items),html=''.join(panels))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
