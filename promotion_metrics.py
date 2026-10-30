"""Read-only placement indicators for confirmed students, from local records."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from wedof_contracts import directory_contracts


def _not_ended(end, today):
    if not end:
        return True
    try:
        return datetime.fromisoformat(str(end)[:10]).date() >= today
    except ValueError:
        return False


def annotate_promotion_metrics(app, conn, promotions, today=None):
    # Imported here because campus_admin also consumes list_promotions.
    from campus_admin import ENROLLED

    today = today or datetime.now(ZoneInfo('Europe/Paris')).date()
    groups = {p['id']: [] for p in promotions}
    if not groups:
        return
    columns = {r[1] for r in conn.execute('PRAGMA table_info(candidats)')}
    optional = ','.join(f'c.{name}' if name in columns else f"NULL AS {name}"
                        for name in ('entreprise_trouvee', 'date_naissance'))
    rows = [dict(r) for r in conn.execute(f'''SELECT c.id,c.nom,c.prenom,c.email,{optional},s.promotion_id
        FROM student_promotions s JOIN candidats c ON c.id=s.candidate_id
        WHERE c.statut IN (?,?)''', ENROLLED) if r['promotion_id'] in groups]
    directory_contracts(app, conn, rows)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    found = set()
    ids = [r['id'] for r in rows]
    for offset in range(0, len(ids), 400):
        batch = ids[offset:offset + 400]
        marks = ','.join('?' for _ in batch)
        if {'company_students', 'companies'} <= tables:
            for row in conn.execute(f'''SELECT s.candidate_id,s.start_date,s.end_date
                FROM company_students s JOIN companies c ON c.id=s.company_id
                WHERE s.candidate_id IN ({marks})''', batch):
                try:
                    start = datetime.fromisoformat(str(row['start_date'])[:10]).date()
                except ValueError:
                    continue
                if _not_ended(row['end_date'], max(today, start)):
                    found.add(row['candidate_id'])
        if 'student_wedof_contracts' in tables:
            for row in conn.execute(f'''SELECT candidate_id,payload FROM student_wedof_contracts
                WHERE candidate_id IN ({marks})''', batch):
                try:
                    item = json.loads(row['payload'])
                except (ValueError, TypeError):
                    continue
                if not isinstance(item, dict) or item.get('state') not in ('sent', 'pendingAcceptation', 'accepted'):
                    continue
                if not (item.get('employer_name') or item.get('employer_siret')) or not _not_ended(item.get('contract_end'), today):
                    continue
                # A rupture takes effect on its date; a normal end date is inclusive.
                if item.get('contract_break_date') and (not _not_ended(item['contract_break_date'], today)
                                                       or str(item['contract_break_date'])[:10] == today.isoformat()):
                    continue
                found.add(row['candidate_id'])
    for row in rows:
        declared = str(row.get('entreprise_trouvee') or '').strip().casefold()
        row['company'] = 'yes' if row['id'] in found or declared == 'oui' else ('no' if declared == 'non' else 'unknown')
        groups[row['promotion_id']].append(row)
    for promotion in promotions:
        members = groups[promotion['id']]
        total = len(members)
        counts = dict(company_found=sum(r['company'] == 'yes' for r in members),
                      company_searching=sum(r['company'] == 'no' for r in members),
                      company_unknown=sum(r['company'] == 'unknown' for r in members),
                      contract_linked=sum(r['contract'] == 'yes' for r in members),
                      contract_missing=sum(r['contract'] == 'no' for r in members),
                      contract_unknown=sum(r['contract'] == 'linked' for r in members))
        promotion['placement'] = dict(total=total, **{
            name: dict(count=count, percent=round(count * 100 / total, 1) if total else None)
            for name, count in counts.items()
        })
