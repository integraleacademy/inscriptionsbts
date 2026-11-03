"""Display the current employment situation without changing admission workflows."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json

EMPLOYMENT_ELIGIBLE = {'validee', 'confirmee', 'reconfirmee', 'reconf_en_cours', 'rentree'}
EMPLOYMENT_STATUS = ('en_entreprise', 'En entreprise', 'green')


def active_period(start, end, today):
    try:
        first = date.fromisoformat(str(start or '')[:10])
        last = date.fromisoformat(str(end)[:10]) if end else None
    except ValueError:
        return False
    return first <= today and (last is None or last >= today)


def annotate_candidate_statuses(conn, rows, today=None):
    today = today or datetime.now(ZoneInfo('Europe/Paris')).date()
    eligible = {r['id']: r for r in rows if r.get('statut') in EMPLOYMENT_ELIGIBLE}
    for row in rows:
        row['display_status'] = row.get('statut', '')
        row['display_status_label'] = ''
    if not eligible:
        return rows
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    employed = set()
    verified_mos = set()
    direct_by_candidate = {}
    if 'akto_students' in tables:
        from akto_sync import get_records
        from opco_sync import same_contract, student_records
        for cid,row in eligible.items():
            is_mos = (row.get('bts') or '').strip().upper() == 'MOS'
            records, message = get_records(conn,cid) if is_mos else ([], '')
            direct = student_records(conn, row)
            if direct:
                direct_by_candidate[cid] = direct
            if any(i.get('state') == 'accepted' and
                   (not i.get('contract_break_date') or i['contract_break_date'] > today.isoformat()) and
                   active_period(i.get('contract_start'),i.get('contract_end'),today) for i in direct):
                employed.add(cid)
            if is_mos and (records or direct or not message):
                verified_mos.add(cid)
            if any(r.get('status') == 'Accordé' and active_period(r.get('contract_start'),r.get('contract_end'),today) for r in records):
                employed.add(cid)
    ids = list(eligible)
    for offset in range(0, len(ids), 400):
        batch = ids[offset:offset+400]
        marks = ','.join('?' for _ in batch)
        if {'company_students', 'companies'} <= tables:
            # Disabling an employer's portal access does not terminate employment.
            for row in conn.execute(f'''SELECT s.candidate_id,s.start_date,s.end_date FROM company_students s
                JOIN companies c ON c.id=s.company_id WHERE s.candidate_id IN ({marks})''', batch):
                if active_period(row['start_date'], row['end_date'], today):
                    employed.add(row['candidate_id'])
        if 'student_wedof_contracts' in tables:
            for row in conn.execute(f'SELECT candidate_id,payload FROM student_wedof_contracts WHERE candidate_id IN ({marks})', batch):
                if row['candidate_id'] in verified_mos:
                    continue
                try:
                    item = json.loads(row['payload'])
                except (ValueError, TypeError):
                    continue
                if not isinstance(item, dict) or item.get('state') != 'accepted' or not (item.get('employer_name') or item.get('employer_siret')):
                    continue
                if any(same_contract(item,r) for r in direct_by_candidate.get(row['candidate_id'],())):
                    continue
                if item.get('contract_break_date') and str(item['contract_break_date'])[:10] <= today.isoformat():
                    continue
                if active_period(item.get('contract_start'), item.get('contract_end'), today):
                    employed.add(row['candidate_id'])
    for cid in employed:
        eligible[cid].update(display_status=EMPLOYMENT_STATUS[0], display_status_label=EMPLOYMENT_STATUS[1])
    return rows

