"""Read-only attached-contract indicator for confirmed students."""

from wedof_contracts import directory_contracts


def annotate_promotion_metrics(app, conn, promotions):
    # Imported here because campus_admin also consumes list_promotions.
    from campus_admin import ENROLLED

    groups = {p['id']: [] for p in promotions}
    if not groups:
        return
    columns = {r[1] for r in conn.execute('PRAGMA table_info(candidats)')}
    optional = 'c.date_naissance' if 'date_naissance' in columns else 'NULL AS date_naissance'
    rows = [dict(r) for r in conn.execute(f'''SELECT c.id,c.nom,c.prenom,c.email,{optional},s.promotion_id
        FROM student_promotions s JOIN candidats c ON c.id=s.candidate_id
        WHERE c.statut IN (?,?)''', ENROLLED) if r['promotion_id'] in groups]
    directory_contracts(app, conn, rows)
    for row in rows:
        groups[row['promotion_id']].append(row)
    for promotion in promotions:
        members = groups[promotion['id']]
        total = len(members)
        count = sum(r['contract'] == 'yes' for r in members)
        promotion['placement'] = dict(total=total, contract_linked=dict(
            count=count, percent=round(count * 100 / total, 1) if total else None))
