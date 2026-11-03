"""Read the saved FILIZ school contracts for BTS student and staff views."""
from contextlib import closing

from flask import abort, jsonify, render_template

from contract_display import billing, display_date, display_stamp, euros
from filiz_portal import CATALOG
from opco_sync import account_status, bts_students, identity, records_by_student, roster_key
from training_programs import BTS_LABELS
from wedof_contract_data import FINANCERS


def directory_contracts(app, conn, rows, *, include_linked_contracts=False):
    status = account_status(conn)
    complete = (status['configured'] and status['state']=='ok' and status['roster'] and
                status['roster']==roster_key(bts_students(conn)))
    records = records_by_student(conn,rows)
    for row in rows:
        items = records.get(row['id'],[])
        row.update(contract='linked', contract_label='À vérifier', contract_needs_check=False)
        if include_linked_contracts:
            row['linked_contracts'] = items
        if items:
            labels = dict.fromkeys(' · '.join(filter(None,(FINANCERS.get(i.get('financer')),i.get('state_label')))) for i in items)
            row.update(contract='yes',contract_label='Contrat d’apprentissage',contract_detail='FILIZ · '+' / '.join(labels))
        elif (row.get('bts') or '').strip().upper() not in BTS_LABELS:
            row['contract_detail'] = 'La lecture FILIZ concerne les six filières BTS.'
        elif not status['configured']:
            row['contract_detail'] = 'Compte école FILIZ à connecter.'
        elif not all(identity(row.get('nom'),row.get('prenom'),row.get('date_naissance'))):
            row['contract_detail'] = 'Identité à compléter avant le rapprochement FILIZ.'
        elif complete:
            row.update(contract='no',contract_label='Sans contrat identifié',
                       contract_detail='Aucun contrat depuis le 1er juin 2025 trouvé lors de la dernière lecture complète de FILIZ.')
        else:
            row['contract_detail'] = 'En attente d’une lecture complète de FILIZ pour cette fiche.'
        row['contract_needs_check'] = bool(status['configured'] and row['contract']=='linked' and (row.get('bts') or '').strip().upper() in BTS_LABELS)
    return bool(status['configured'])


def register_filiz_contracts(app, connect, require_admin):
    app.jinja_env.filters.update(wedof_money=euros, wedof_date=display_date, wedof_stamp=display_stamp)
    app.jinja_env.globals['wedof_financers'] = FINANCERS

    @app.get('/admin/candidat/<cid>/contrats-apprentissage')
    def filiz_student_contracts(cid):
        if not require_admin():
            abort(403)
        with closing(connect()) as conn:
            person = conn.execute('SELECT * FROM candidats WHERE id=?',(cid,)).fetchone()
            if not person:
                abort(404)
            row = dict(person)
            configured = directory_contracts(app,conn,[row],include_linked_contracts=True)
        cards = [dict(item=item, billing=billing(item), checked_at=item.get('checked_at'), error=item.get('read_warning'),
                      portal=CATALOG+'/'+item['filiz_id']) for item in row['linked_contracts']]
        html = (render_template('_wedof_contracts_list.html',contracts=cards,row=row,direct=True,configured=configured) if cards
                else render_template('_filiz_empty.html', row=row))
        response = jsonify(ok=True, configured=configured, has_contracts=bool(cards), html=html)
        response.headers['Cache-Control'] = 'private, no-store'
        return response
