"""Read-only interpretation of the establishment's 'Suivre les retours' detail screen."""
import re
from datetime import datetime

from cyclades_data import words

MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
PIECE = re.compile(r"(?m)^\s*([A-Z0-9]{3,15})\s*:\s*([^\n]{2,180})$")
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


def parse_detail(text, record, uai):
    """Return only item labels, explicit upload/control states and the deadline."""
    profile = re.search(r"N[°º]\s*candidat\s*:\s*(\d+)\s+N[°º]\s*inscription\s*:\s*(\d+)\s+Version\s*:\s*(\d+)", text, re.I)
    establishment = re.search(r"Code\s+[ÉE]tab\s*:\s*(\w+)", text, re.I)
    counts = re.search(r"Pièces justificatives conformes\s*:\s*(\d+)\s*/\s*(\d+)", text, re.I)
    keys = ["N° de candidat", "N° d’inscription", "Version"]
    if not (profile and establishment and counts and establishment[1] == uai and
            all(number(a) == number(record["details"].get(k, "")) and record["details"].get(k)
                for a, k in zip(profile.groups(), keys))):
        return None
    pieces = []
    due = None
    current = None
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
            if flat.startswith("traitement administratif statut "):
                current["review"] = REVIEWS.get(flat.removeprefix("traitement administratif statut "))
            if line.startswith("PJ-CONTROLE "):
                current["review"] = REVIEWS.get(words(line[12:]))
    if int(counts[1]) > int(counts[2]) or len(pieces) != int(counts[2]) or len({p["code"] for p in pieces}) != len(pieces):
        return None
    return {"documents": pieces, "conforming": int(counts[1]), "requested": int(counts[2])}
