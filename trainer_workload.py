"""Admin-only monthly teaching workload and effective-dated hourly rates.

The canonical planning course is one physical teaching session, even when
several promotions attend. Per-promotion/BTS figures describe attendance and
are intentionally non-additive. No invoice or attendance claim is inferred.
"""
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo

from planning import _load_courses, ensure_planning_schema

MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
          'août', 'septembre', 'octobre', 'novembre', 'décembre')


class WorkloadError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def ensure_workload_schema(conn):
    ensure_planning_schema(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS trainer_hourly_rates (
        trainer_id TEXT NOT NULL, effective_date TEXT NOT NULL,
        rate_cents INTEGER NOT NULL CHECK(rate_cents >= 0), updated_at TEXT NOT NULL,
        PRIMARY KEY(trainer_id,effective_date))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trainer_workload_versions (
        trainer_id TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0)''')


def _month_bounds(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        raise WorkloadError('Sélectionnez un mois valide.')
    try:
        year, month = map(int, value.split('-'))
        if not 1900 <= year <= 2200:
            raise ValueError
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
    except ValueError:
        raise WorkloadError('Sélectionnez un mois valide.') from None
    return start, end


def format_minutes(minutes):
    hours, remainder = divmod(minutes, 60)
    return f'{hours} h' + (f' {remainder:02d}' if remainder else '')


def format_cents(cents):
    if cents is None:
        return 'À renseigner'
    return f'{Decimal(cents) / 100:,.2f}'.replace(',', '\u202f').replace('.', ',') + ' €'


def _rate_cents(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'\d{1,5}(?:[.,]\d{1,2})?', raw.strip()):
        raise WorkloadError('Indiquez un tarif horaire en euros, avec deux décimales au maximum.')
    try:
        value = Decimal(raw.strip().replace(',', '.'))
    except InvalidOperation:
        raise WorkloadError('Indiquez un tarif horaire valide.') from None
    if not value.is_finite() or not Decimal('0') <= value <= Decimal('10000'):
        raise WorkloadError('Le tarif horaire doit être compris entre 0 et 10 000 €.')
    return int(value * 100)


def workload_revision(conn, trainer_id):
    row = conn.execute('SELECT version FROM trainer_workload_versions WHERE trainer_id=?', (trainer_id,)).fetchone()
    return row[0] if row else 0


def save_hourly_rate(conn, trainer_id, effective_date, rate, expected_revision):
    """Caller holds BEGIN IMMEDIATE; schema setup happens before the lock."""
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise WorkloadError('Rechargez la fiche avant de modifier le tarif.', 409)
    if workload_revision(conn, trainer_id) != expected_revision:
        raise WorkloadError('Le tarif a été modifié entre-temps. Rechargez la fiche.', 409)
    if not isinstance(effective_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', effective_date):
        raise WorkloadError('Indiquez une date d’effet valide.')
    try:
        day = date.fromisoformat(effective_date)
        if not 1900 <= day.year <= 2200:
            raise ValueError
    except ValueError:
        raise WorkloadError('Indiquez une date d’effet valide.') from None
    cents = _rate_cents(rate)
    if not conn.execute('SELECT 1 FROM trainers WHERE id=?', (trainer_id,)).fetchone():
        raise WorkloadError('Ce formateur est introuvable.', 404)
    conn.execute('''INSERT INTO trainer_hourly_rates(trainer_id,effective_date,rate_cents,updated_at)
        VALUES(?,?,?,?) ON CONFLICT(trainer_id,effective_date) DO UPDATE
        SET rate_cents=excluded.rate_cents,updated_at=excluded.updated_at''',
        (trainer_id, effective_date, cents, datetime.now(timezone.utc).isoformat()))
    conn.execute('''INSERT INTO trainer_workload_versions(trainer_id,version) VALUES(?,1)
        ON CONFLICT(trainer_id) DO UPDATE SET version=version+1''', (trainer_id,))
    return workload_revision(conn, trainer_id)


def get_trainer_workload(conn, trainer_id, month, today=None):
    start, end = _month_bounds(month)
    today = today or datetime.now(ZoneInfo('Europe/Paris')).date()
    rates = [dict(row) for row in conn.execute(
        'SELECT effective_date,rate_cents,updated_at FROM trainer_hourly_rates WHERE trainer_id=? ORDER BY effective_date',
        (trainer_id,))]
    promotions = {row['id']: dict(row) for row in conn.execute('SELECT id,nom,bts FROM promotions')}
    def rate_on(day):
        return next((item['rate_cents'] for item in reversed(rates) if item['effective_date'] <= day), None)
    courses = _load_courses(conn, start.isoformat(), end.isoformat(), trainer_id=trainer_id)
    total_minutes = elapsed_minutes = shared_minutes = unpriced_minutes = 0
    exact_amount = Decimal(0)
    by_promotion, by_bts, details = {}, {}, []
    for course in courses:
        minutes = course['end_min'] - course['start_min']
        total_minutes += minutes
        if course['date'] < today.isoformat():
            elapsed_minutes += minutes
        rate = rate_on(course['date'])
        if rate is None:
            unpriced_minutes += minutes
            exact_line_amount = None
        else:
            exact_line_amount = Decimal(minutes) * Decimal(rate) / Decimal(60)
            exact_amount += exact_line_amount
        group_ids = {group['promotion_id'] for group in course['groups']}
        if len(group_ids) > 1:
            shared_minutes += minutes
        group_names, group_bts = [], set()
        for group_id in group_ids:
            promotion = promotions.get(group_id, {'nom': 'Promotion à renseigner', 'bts': 'Non renseigné'})
            group_names.append(promotion['nom'])
            bucket = by_promotion.setdefault(group_id, dict(id=group_id, name=promotion['nom'], bts=promotion['bts'], minutes=0, courses=0))
            bucket['minutes'] += minutes
            bucket['courses'] += 1
            group_bts.add(promotion['bts'])
        for bts in group_bts:
            bucket = by_bts.setdefault(bts, dict(name=bts, minutes=0, courses=0))
            bucket['minutes'] += minutes
            bucket['courses'] += 1
        rounded_line = int(exact_line_amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if exact_line_amount is not None else None
        details.append(dict(
            id=course['id'], date=course['date'], date_label=date.fromisoformat(course['date']).strftime('%d/%m/%Y'),
            start=course['start'], end=course['end'], title=course['title'] or course['subject_name'] or 'Matière à renseigner',
            minutes=minutes, duration_label=format_minutes(minutes), promotions=sorted(group_names),
            is_shared=len(group_ids) > 1, rate_cents=rate, rate_label=format_cents(rate),
            amount_cents=rounded_line, amount_label=format_cents(rounded_line) if rounded_line is not None else 'Tarif manquant',
            incomplete=course['incomplete'], warning_labels=course['warning_labels']))
    estimated_cents = int(exact_amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    previous_month = date(start.year - 1, 12, 1) if start.month == 1 else date(start.year, start.month - 1, 1)
    next_month = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    for bucket in [*by_promotion.values(), *by_bts.values()]:
        bucket['hours_label'] = format_minutes(bucket['minutes'])
        bucket['percent'] = round(bucket['minutes'] * 100 / total_minutes) if total_minutes else 0
    for item in rates:
        item['rate_label'] = format_cents(item['rate_cents'])
        item['date_label'] = date.fromisoformat(item['effective_date']).strftime('%d/%m/%Y')
    current_rate = rate_on(today.isoformat())
    return dict(
        month=month, month_label=f'{MONTHS[start.month-1]} {start.year}', start=start.isoformat(), end=end.isoformat(),
        previous_month=previous_month.strftime('%Y-%m') if previous_month.year >= 1900 else None,
        next_month=next_month.strftime('%Y-%m') if next_month.year <= 2200 else None,
        today=today.isoformat(), courses=details, course_count=len(details), total_minutes=total_minutes,
        total_label=format_minutes(total_minutes), elapsed_minutes=elapsed_minutes, elapsed_label=format_minutes(elapsed_minutes),
        future_minutes=total_minutes-elapsed_minutes, future_label=format_minutes(total_minutes-elapsed_minutes),
        shared_minutes=shared_minutes, shared_label=format_minutes(shared_minutes),
        unpriced_minutes=unpriced_minutes, unpriced_label=format_minutes(unpriced_minutes),
        estimated_cents=estimated_cents, estimated_label=format_cents(estimated_cents), all_priced=not unpriced_minutes,
        by_promotion=sorted(by_promotion.values(), key=lambda item: item['name']),
        by_bts=sorted(by_bts.values(), key=lambda item: item['name']), rates=list(reversed(rates)),
        current_rate_cents=current_rate, current_rate_label=format_cents(current_rate),
        rate_input=f'{Decimal(current_rate)/100:.2f}' if current_rate is not None else '',
        rate_revision=workload_revision(conn, trainer_id))


def get_trainer_annual_workload(conn, trainer_id, year):
    """Calendar-year forecast, priced once per physical session and exact minute."""
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
        raise WorkloadError('Sélectionnez une année comprise entre 1900 et 2200.')
    rates = [dict(row) for row in conn.execute(
        'SELECT effective_date,rate_cents FROM trainer_hourly_rates WHERE trainer_id=? ORDER BY effective_date',
        (trainer_id,))]
    courses = _load_courses(conn, f'{year:04d}-01-01', f'{year:04d}-12-31', trainer_id=trainer_id)
    months = [dict(month=f'{year:04d}-{number:02d}', number=number, name=MONTHS[number-1],
                   minutes=0, course_count=0, unpriced_minutes=0, price_numerator=0)
              for number in range(1, 13)]
    shared_minutes = 0
    for course in courses:
        row = months[int(course['date'][5:7])-1]
        minutes = course['end_min'] - course['start_min']
        row['minutes'] += minutes
        row['course_count'] += 1
        rate = next((item['rate_cents'] for item in reversed(rates) if item['effective_date'] <= course['date']), None)
        if rate is None:
            row['unpriced_minutes'] += minutes
        else:
            row['price_numerator'] += minutes * rate
        if len({group['promotion_id'] for group in course['groups']}) > 1:
            shared_minutes += minutes
    total_minutes = sum(row['minutes'] for row in months)
    unpriced_minutes = sum(row['unpriced_minutes'] for row in months)
    numerator = sum(row['price_numerator'] for row in months)
    estimated_cents = int((Decimal(numerator)/60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    peak = max((row['minutes'] for row in months), default=0)
    for row in months:
        row['estimated_cents'] = int((Decimal(row.pop('price_numerator'))/60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        row.update(hours_label=format_minutes(row['minutes']), estimated_label=format_cents(row['estimated_cents']),
                   unpriced_label=format_minutes(row['unpriced_minutes']), all_priced=not row['unpriced_minutes'],
                   percent=round(row['minutes']*100/peak) if peak else 0)
    return dict(year=year, months=months, total_minutes=total_minutes, total_label=format_minutes(total_minutes),
                course_count=len(courses), estimated_cents=estimated_cents, estimated_label=format_cents(estimated_cents),
                unpriced_minutes=unpriced_minutes, unpriced_label=format_minutes(unpriced_minutes), all_priced=not unpriced_minutes,
                shared_minutes=shared_minutes, shared_label=format_minutes(shared_minutes))
