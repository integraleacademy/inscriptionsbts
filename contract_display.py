"""Financial display helpers for apprenticeship contract cards."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo


def euros(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 'Non communiqué'
    if not number.is_finite():
        return 'Non communiqué'
    return f'{number:,.2f}'.replace(',', '\u202f').replace('.', ',') + ' €'


def display_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return 'Non communiquée'


def display_stamp(value):
    from zoneinfo import ZoneInfo
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M')
    except (ValueError, TypeError):
        return 'Non communiquée'


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if value is not None else None


def billing(item):
    today = datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    schedules = []
    for source in item.get('schedules', []):
        row = dict(source)
        total, paid, pending = (cents(row.get(k)) for k in ('montantTotal', 'montantRegle', 'montantEnCoursInstruction'))
        row['remaining'] = max(0, total-paid)/100 if total is not None and paid is not None else None
        if item.get('raw_stale'):
            row['status'], row['status_code'] = 'À vérifier', 'stale'
        elif item.get('source')=='filiz' and row.get('filiz_label'):
            row['status'],row['status_code'] = row['filiz_label'],row['filiz_code']
        elif total is not None and paid is not None and paid >= total:
            row['status'], row['status_code'] = 'Réglée', 'paid'
        elif pending is not None and pending > 0:
            row['status'], row['status_code'] = 'En instruction', 'pending'
        elif item.get('source')=='akto' and item.get('rupture_notice'):
            row['status'], row['status_code'] = 'Prévision à vérifier', 'stale'
        elif item.get('source')=='akto' and paid is None and row.get('dateOuverture','') <= today:
            row['status'], row['status_code'] = 'Règlement à vérifier', 'unknown'
        elif row.get('dateOuverture') and row['dateOuverture'] <= today:
            row['status'], row['status_code'] = 'Ouverte à facturation', 'open'
        elif row.get('dateOuverture'):
            row['status'], row['status_code'] = 'À venir', 'upcoming'
        else:
            row['status'], row['status_code'] = 'Non communiqué', 'unknown'
        row['paid_percent'] = min(100, max(0, round(paid/total*100))) if total and paid is not None else None
        schedules.append(row)
    def total(key):
        values = [cents(r.get(key)) for r in schedules]
        return sum(values)/100 if values and all(v is not None for v in values) else None
    amount, paid = total('montantTotal'), total('montantRegle')
    if item.get('source')=='filiz':
        amount,paid = item.get('engagement'),item.get('filiz_paid')
    counts = {code: sum(r['status_code'] == code for r in schedules) for code in ('paid', 'pending', 'open', 'upcoming', 'stale', 'unknown')}
    date_key = 'dateDebut' if item.get('source')=='filiz' else 'dateOuverture'
    next_due = next(iter(sorted((r for r in schedules if r['status_code'] in {'open', 'upcoming', 'pending'} and r.get(date_key)),
                               key=lambda r: r[date_key])), None)
    return {'schedules': schedules, 'total': amount, 'paid': paid, 'pending': item.get('filiz_pending') if item.get('source')=='filiz' else total('montantEnCoursInstruction'),
            'counts': counts, 'next_due': next_due,
            'paid_percent': min(100, max(0, round(cents(paid)/cents(amount)*100))) if amount and paid is not None and not item.get('raw_stale') else None,
            'remaining': max(0, cents(amount)-cents(paid))/100 if amount is not None and paid is not None else None}
