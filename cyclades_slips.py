"""Read individual access details from the institution's official CYCLADES slips."""
import io
import re

from pypdf import PdfReader

from cyclades_data import CycladesError, MAX_BYTES

CANDIDATE = re.compile(r"N[°ºo]\s*(?:de\s+)?candidat\s*:\s*(\d+)\b", re.I)
REGISTRATION = re.compile(r"\binscription\s*n[°ºo]\s*:\s*(\d+)\b", re.I)
LOGIN = re.compile(r"Votre\s+identifiant\s+de\s+connexion\s*:\s*(\S+)", re.I)
PASSWORD = re.compile(r"Votre\s+mot\s+de\s+passe\s*(?:\(\s*\*\s*\))?\s*:[ \t]*(?:\r?\n[ \t]*)?(\S+)[ \t]*\r?$", re.I | re.M)


def slip_key(record):
    details = record["details"]
    candidate = details.get("N° de candidat", "")
    registration = details.get("N° d’inscription", "")
    login = details.get("Identifiant de connexion", "")
    if not candidate.isdecimal() or not registration.isdecimal() or not login or re.search(r"\s", login):
        return None
    return (candidate.lstrip("0") or "0", registration.lstrip("0") or "0", login)


def read_slips(raw, wanted):
    """Match all three official fields inside one slip. Reject conflicting editions."""
    if not raw.startswith(b"%PDF-") or len(raw) > MAX_BYTES:
        raise CycladesError("Sélectionnez un PDF de papillons Cyclades de moins de 12 Mo.")
    found = {}
    try:
        pdf = PdfReader(io.BytesIO(raw), strict=False)
        if pdf.is_encrypted or len(pdf.pages) > 500:
            raise ValueError
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "accès au service en ligne des examens" not in " ".join(text.casefold().split()):
                continue
            sections = CANDIDATE.split(text)
            for candidate, block in zip(sections[1::2], sections[2::2]):
                registrations, logins, passwords = (p.findall(block) for p in (REGISTRATION, LOGIN, PASSWORD))
                if len(registrations) != 1 or len(logins) != 1 or len(passwords) != 1:
                    continue
                key = (candidate.lstrip("0") or "0", registrations[0].lstrip("0") or "0", logins[0])
                if key in wanted and 1 <= len(passwords[0]) <= 128:
                    found.setdefault(key, set()).add(passwords[0])
    except Exception:
        raise CycladesError("Le PDF de papillons est illisible ou protégé.") from None
    return {key: values.pop() for key, values in found.items() if len(values) == 1}
