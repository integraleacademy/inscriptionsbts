"""One-candidate trial. The observation is private deployment data."""
from decimal import Decimal, InvalidOperation
import json
import os
import re


def contract_for(candidate_id):
    raw = os.environ.get("AKTO_PILOT_CONTRACT", "")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("candidate_id") != candidate_id:
        return None
    if not re.fullmatch(r"[A-Z0-9]{5,32}", str(record.get("reference", ""))):
        return None
    return record


def amount(value):
    try:
        result = Decimal(''.join(str(value).split()).removesuffix('€').replace(',', '.'))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def contract_card(pilot, candidate):
    total, paid, remaining = (amount(pilot.get(k)) for k in ('funding', 'paid', 'balance'))
    period = str(pilot.get('period') or '').split(' au ')
    item = {
        'working_contract_id': pilot['reference'], 'external_number': pilot['reference'],
        'financer': 'opcoCfaAkto', 'employer_name': pilot.get('employer'),
        'employer_siret': pilot.get('siret'), 'training_title': pilot.get('training'),
        'training_hours': pilot.get('hours'), 'engagement': total,
        'state': 'accepted' if pilot.get('status') == 'Accordé' else 'unknown',
        'state_label': pilot.get('status'), 'apprentice_first_name': candidate.get('prenom'),
        'apprentice_last_name': candidate.get('nom'),
    }
    account = {
        'total': total, 'paid': paid, 'pending': None, 'remaining': remaining,
        'paid_percent': round(100 * paid / total) if total and total > 0 and paid is not None else None,
        'schedules': [], 'next_due': None,
    }
    return {'item': item, 'billing': account, 'module_dates': period if len(period) == 2 else []}
