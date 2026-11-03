"""Read individual access details from the institution's official CYCLADES slips."""
import io
import re

from pypdf import PdfReader

from cyclades_data import CycladesError, MAX_BYTES, words

HEADING = re.compile(r"Accès\s+aux?\s+services?\s+en\s+ligne\s+des\s+examens", re.I)
CANDIDATE = re.compile(r"N[°ºo]\s*(?:(?:du|de)\s+)?candidat\s*:?\s*(\d+)\b", re.I)
REGISTRATION = re.compile(r"(?:\binscription\s*n[°ºo]|\bN[°ºo]\s*d[’']inscription)\s*:?\s*(\d+)\b", re.I)
LOGIN = re.compile(r"(?:votre\s+)?identi(?:fi|ﬁ)ant\s+(?:de\s+)?connexion\s*(?:\(login\))?\s*:\s*(\S+)", re.I)
PASSWORD = re.compile(r"(?:^\s*|\bVotre\s+)mot\s+de\s+passe(?:\s+(?:provisoire|initial|de\s+connexion))?\s*(?:\(\s*\*\s*\))?\s*:[ \t]*(?:\r?\n[ \t]*)?(\S+)[ \t]*\r?$", re.I|re.M)


def slip_key(record):
    details = record["details"]
    candidate = details.get("N° de candidat", "")
    registration = details.get("N° d’inscription", "")
    login = details.get("Identifiant de connexion", "")
    if not candidate.isdecimal() or not registration.isdecimal() or not login or re.search(r"\s", login):
        return None
    return (candidate.lstrip("0") or "0", registration.lstrip("0") or "0", login)


def collect_slips(pages, wanted, found):
    # A slip can continue onto the next page. Its candidate reference bounds
    # the block, even when the edition contains several slips on one page.
    text = "\n".join(pages)
    normal = words(text)
    if not ("service en ligne des examens" in normal or "services en ligne des examens" in normal
            or ("cyclades" in normal and "connexion" in normal and "mot de passe" in normal)):
        return
    references = {}
    for key in wanted:
        references.setdefault(key[:2], []).append(key)
    # Prefer the printed slip heading as a boundary. A document may put
    # its identifier fields before the candidate reference in text order.
    for section in HEADING.split(text):
        markers = list(CANDIDATE.finditer(section))
        for index, marker in enumerate(markers):
            if len(markers) == 1:
                block = section
            else:
                end = markers[index + 1].start() if index + 1 < len(markers) else len(section)
                block = section[marker.start():end]
            registrations = {v.lstrip("0") or "0" for v in REGISTRATION.findall(block)}
            if len(registrations) != 1:
                continue
            keys = references.get((marker[1].lstrip("0") or "0", registrations.pop()), [])
            if len(keys) != 1:
                continue
            key = keys[0]
            pattern = r"(?<![\w.@+-])" + re.escape(key[2]) + r"(?![\w.@+-])"
            if not re.search(pattern, block):
                continue
            logins = set(LOGIN.findall(block))
            if logins and logins != {key[2]}:
                continue
            passwords = {value for value in PASSWORD.findall(block)
                         if 1 <= len(value) <= 128 and set(value) != {"*"}}
            if passwords:
                found.setdefault(key, set()).update(passwords)


def read_slips(raw, wanted):
    """Match all three official fields. Never store a PDF or a conflicting pair."""
    if not raw.startswith(b"%PDF-") or len(raw) > MAX_BYTES:
        raise CycladesError("Sélectionnez un PDF de papillons Cyclades de moins de 12 Mo.")
    found = {}
    try:
        pdf = PdfReader(io.BytesIO(raw), strict=False)
        if pdf.is_encrypted or len(pdf.pages) > 500:
            raise ValueError
        pages = [page.extract_text() or "" for page in pdf.pages]
        collect_slips(pages, wanted, found)
        if any(key not in found for key in wanted):
            # Some official editions paint labels and values in different text
            # objects; reconstruct their visual reading order before matching.
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as layout:
                pages = [page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in layout.pages]
            collect_slips(pages, wanted, found)
    except Exception:
        raise CycladesError("Le PDF de papillons est illisible ou protégé.") from None
    return {key: values.pop() for key, values in found.items() if len(values) == 1}
