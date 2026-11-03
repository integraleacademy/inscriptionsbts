"""Read individual access details from the institution's official CYCLADES slips."""
import io
import logging
import re

from pypdf import PdfReader

from cyclades_data import CycladesError, MAX_BYTES

CANDIDATE = re.compile(r"N[°ºo]\s*(?:(?:du|de)\s+)?candidat\s*:\s*(\d+)\b", re.I)
REGISTRATION = re.compile(r"(?:\binscription\s*n[°ºo]|\bN[°ºo]\s*d[’']inscription)\s*:?\s*(\d+)\b", re.I)
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
    references = {(key[0],key[1]) for key in wanted}
    candidates = {key[0] for key in wanted}
    counts = dict(pages=0, headings=0, candidates=0, matched_candidates=0, registrations=0, logins=0, passwords=0)
    try:
        pdf = PdfReader(io.BytesIO(raw), strict=False)
        if pdf.is_encrypted or len(pdf.pages) > 500:
            raise ValueError
        for page in pdf.pages:
            text = page.extract_text() or ""
            counts["pages"] += 1
            title = " ".join(text.casefold().split())
            if not (re.search(r"accès aux? services? en ligne des examens",title)
                    or ("cyclades" in title and LOGIN.search(text) and PASSWORD.search(text))):
                continue
            counts["headings"] += 1
            sections = CANDIDATE.split(text)
            for candidate, block in zip(sections[1::2], sections[2::2]):
                registrations, logins, passwords = (p.findall(block) for p in (REGISTRATION, LOGIN, PASSWORD))
                number = candidate.lstrip("0") or "0"
                counts["candidates"] += 1
                counts["matched_candidates"] += number in candidates
                counts["registrations"] += len(registrations) == 1 and (number,registrations[0].lstrip("0") or "0") in references
                counts["logins"] += len(logins) == 1
                counts["passwords"] += len(passwords) == 1
                if len(registrations) != 1 or len(logins) != 1 or len(passwords) != 1:
                    continue
                key = (candidate.lstrip("0") or "0", registrations[0].lstrip("0") or "0", logins[0])
                if key in wanted and 1 <= len(passwords[0]) <= 128:
                    found.setdefault(key, set()).add(passwords[0])
    except Exception:
        raise CycladesError("Le PDF de papillons est illisible ou protégé.") from None
    logging.getLogger(__name__).warning("CYCLADES PDF papillons : %s", counts)
    return {key: values.pop() for key, values in found.items() if len(values) == 1}
