"""One-candidate trial. The observation is private deployment data."""
from decimal import Decimal, InvalidOperation
import json
import os
import re


def pilot_record():
    raw = os.environ.get("AKTO_PILOT_CONTRACT", "")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict) or not isinstance(record.get("candidate_id"), str) or not record["candidate_id"]:
        return None
    if not re.fullmatch(r"[A-Z0-9]{5,32}", str(record.get("reference", ""))):
        return None
    return record


def contract_for(candidate_id):
    record = pilot_record()
    return record if record and record["candidate_id"] == candidate_id else None


def settings_summary():
    record = pilot_record()
    if record:
        return {key: record.get(key) for key in ('candidate_id', 'checked', 'reference')}
    return None


def amount(value):
    try:
        result = Decimal(''.join(str(value).split()).removesuffix('€').replace(',', '.'))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def contract_card(pilot, candidate, billing):
    total, paid, remaining = (amount(pilot.get(k)) for k in ('funding', 'paid', 'balance'))
    period = str(pilot.get('period') or '').split(' au ')
    item = {
        'source': 'akto', 'rupture_notice': bool(pilot.get('rupture_notice')),
        'deca_number': pilot.get('dgefp'), 'working_contract_id': pilot['reference'], 'external_number': pilot['reference'],
        'financer': 'opcoCfaAkto', 'employer_name': pilot.get('employer'),
        'employer_siret': pilot.get('siret'), 'training_title': pilot.get('training'),
        'training_hours': pilot.get('hours'), 'engagement': total,
        'state': 'accepted' if pilot.get('status') == 'Accordé' else 'unknown',
        'state_label': pilot.get('status'), 'apprentice_first_name': candidate.get('prenom'),
        'apprentice_last_name': candidate.get('nom'),
        'apprentice_birth_date': pilot.get('apprentice_birth_date'),
        'contract_start': pilot.get('contract_start'), 'contract_end': pilot.get('contract_end'),
        'employer_city': pilot.get('employer_city'), 'rncp': pilot.get('rncp'),
        'remote_hours': pilot.get('remote_hours'), 'schedules': pilot.get('schedules', []),
        'extra_costs_available': 'extra_costs' in pilot, 'extra_costs': pilot.get('extra_costs', []),
    }
    # Keep the overall award (including extras) separate from the pedagogical schedule.
    account = billing(item)
    account.update({
        'total': total, 'paid': paid, 'pending': pilot.get('pending'), 'remaining': remaining,
        'paid_percent': round(100 * paid / total) if total and total > 0 and paid is not None else None,
    })
    return {'item': item, 'billing': account, 'module_dates': period if len(period) == 2 else []}

