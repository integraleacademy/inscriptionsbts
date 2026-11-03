"""Read-only interpretation of the establishment's 'Suivre les retours' detail screen."""
import re
from datetime import datetime

from cyclades_data import words

MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
PIECE = re.compile(r"(?m)^\s*([A-Z][A-Z0-9]{1,13}[0-9])\s*:\s*([^\n]{2,180})$")
REVIEWS = {"en attente de controle": "En attente de contrôle", "conforme": "Conforme",
           "non conforme": "Non conforme", "recue": "Reçue"}

def number(value):
    return str(value).strip().lstrip("0") or "0"


def deadline(line):
    match = re.search(r"(\d{1,2})\s+(\w+)\s+(20\d{2})\s+(\d{1,2}):(\d{2})\s*\(heure/Paris\)", line, re.I)
    if match:
        day, month, year, hour, minute = match.groups()
        try:
            return datetime(int(year), MONTHS.index(month.lower()) + 1, int(day), int(hour), int(minute)).strftime("%d/%m/%Y à %Hh%M")
        except ValueError:
            pass
    return None


COUNT = re.compile(r"Pièces\s+justificatives\s+conformes\s*:\s*(\d+)\s*/\s*(\d+)", re.I)
REF_FIELDS = (
    (r"N[°º]\s*(?:de\s+)?candidat\s*:\s*(\d+)", "N° de candidat"),
    (r"N[°º]\s*(?:d[’']\s*)?inscription\s*:\s*(\d+)", "N° d’inscription"),
    (r"Version\s*:\s*(\d+)", "Version"),
)


def verified_counts(text, record, uai):
    counts = COUNT.search(text)
    if not counts:
        return None
    header = text[:counts.start()]
    school = re.search(r"Code\s+[ÉE]tab\.?\s*:\s*(\d{7}[A-Z])", header, re.I)
    if not school or school[1].upper() != uai:
        return None
    for pattern, key in REF_FIELDS:
        values = {number(v) for v in re.findall(pattern, header, re.I)}
        if not record["details"].get(key) or values != {number(record["details"][key])}:
            return None
    conforming, requested = map(int, counts.groups())
    if conforming > requested:
        return None
    return {"conforming": conforming, "requested": requested}


def parse_detail(text, record, uai):
    """Return only item labels, explicit upload/control states and the deadline."""
    summary = verified_counts(text, record, uai)
    if summary is None:
        return None
    text = text[COUNT.search(text).end():]
    pieces = []
    due = None
    current = None
    # The legacy layout separates the file indicator and actor into adjacent cells.
    text = re.sub(r"aucun\s+fichier\s*par\s+le\s+(candidat|gestionnaire)",
                  r"Aucun fichier par le \1", text, flags=re.I)
    text = re.sub(r"(?m)^\s*([A-Z][A-Z0-9]{1,13}[0-9])\s*:\s*\n\s*(?=\S)", r"\1 : ", text)
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"[àa] déposer en ligne entre", line, re.I):
            due = deadline(line)
        heading = PIECE.fullmatch(line)
        if heading:
            current = dict(code=heading[1], label=heading[2], deposit=None, manager=None, review=None, deadline=due)
            pieces.append(current)
        elif current:
            flat = words(line)
            for actor, field in [("candidat", "deposit"), ("gestionnaire", "manager")]:
                if re.search(r"aucun fichier par le " + actor + r"\b", flat):
                    current[field] = "Non déposée"
                elif re.search(r"depose le .* par le " + actor + r"\b", flat):
                    current[field] = "Déposée"
            # CYCLADES also prints the candidate's upload date without the actor.
            if re.fullmatch(r"d[eé]pos[eé] le \d{2}/\d{2}/\d{4}[^\n]*\(heure/Paris\)", line, re.I):
                current["deposit"] = "Déposée"
            if flat.startswith("traitement administratif statut ") and flat.removeprefix("traitement administratif statut ") in REVIEWS:
                current["review"] = REVIEWS.get(flat.removeprefix("traitement administratif statut "))
            if line.startswith("PJ-CONTROLE "):
                current["review"] = REVIEWS.get(words(line[12:]))
    if len(pieces) != summary["requested"] or len({p["code"] for p in pieces}) != len(pieces):
        return None
    return {"documents": pieces, **summary}
