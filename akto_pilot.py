"""One-candidate trial. The observation is private deployment data."""
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
