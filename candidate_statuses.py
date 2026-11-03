"""Display the current employment situation without changing admission workflows."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from opco_sync import records_by_student

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
    for cid, items in records_by_student(conn,eligible.values()).items():
        if any(i.get('state') == 'accepted' and (i.get('employer_name') or i.get('employer_siret'))
               and (not i.get('contract_break_date') or i['contract_break_date'] > today.isoformat())
               and active_period(i.get('contract_start'),i.get('contract_end'),today) for i in items):
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
    for cid in employed:
        eligible[cid].update(display_status=EMPLOYMENT_STATUS[0], display_status_label=EMPLOYMENT_STATUS[1])
    return rows

