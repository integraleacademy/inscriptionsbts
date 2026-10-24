"""Admission campaign dates and cohort identity (independent of calendar year)."""
from datetime import datetime, timezone
import re

ADMISSION_YEAR = 2027
OPENS_AT = datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc)
OPENING_LABEL = "1er décembre 2026 à 10 h (heure de Paris)"


def campaign_is_open(now=None):
    now = now or datetime.now(timezone.utc)
    return now >= OPENS_AT


def candidate_year(candidate):
    row = dict(candidate or {})
    year = row.get("rentree_annee")
    if str(year).isdigit():
        return int(year)
    match = re.match(r"(20\d{2})BTS", str(row.get("numero_dossier") or ""))
    return int(match.group(1)) if match else 2026
