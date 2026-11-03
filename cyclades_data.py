"""Read institution BTS exports. Only keep exam administration fields for matched students."""
import csv
import io
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
ACADEMIES = {
    "paris": ("Paris", "0756548K", "https://arena.ac-paris.fr/arena/domaines/eleves/evaluation-et-examens",
              "https://bv.ac-paris.fr/mdp/redirectionhub/redirect.jsp?applicationname=cycetab"),
    "nice": ("Nice", "0831774C", "https://esterel.ac-nice.fr/",
             "https://id.ac-nice.fr/mdp/redirectionhub/redirect.jsp?applicationname=cycetab"),
}
MAX_BYTES = 12 * 1024 * 1024
ALL_STATES = {"anomalie", "inscrit", "non inscrit", "pre inscrit", "redoublant"}
# Exact headers from the detailed BTS CSV. Health data and login information in
# other columns must never be retained with a student's exam record.
DETAILS = {
    "N° Candidat": "N° de candidat", "N° inscription": "N° d’inscription", "N° version": "Version",
    "Spécialité": "Spécialité", "Code Spécialité": "Code spécialité", "Division de classe": "Classe",
    "Catégorie": "Catégorie", "Forme de passage": "Forme de passage", "VAE": "VAE",
    "Etalement de session autorisé": "Étalement de session autorisé",
    "Situation à l'inscription": "Situation à l’inscription",
    "Nom établissement inscription": "Établissement d’inscription",
    "Code établissement inscription": "UAI", "Commune établissement inscription": "Commune de l’établissement",
    "Date Création": "Création dans CYCLADES", "Date Modification": "Modification dans CYCLADES",
    "INE": "INE", "Nom de famille": "Nom de famille", "Prénom(s)": "Prénoms",
    "Nom": "Nom déclaré", "Date de naissance": "Date de naissance", "Email": "E-mail déclaré",
    "Nature établissement inscription": "Nature de l’établissement",
    "Statut établissement inscription": "Statut de l’établissement",
}


class CycladesError(Exception):
    """Only static, user-facing diagnostics. Never include portal responses or credentials."""


class CycladesNetworkError(CycladesError):
    """The official portal connection was interrupted during a read."""


class Report(NamedTuple):
    year: int
    issued: float
    records: list
    complete: bool


def words(value):
    plain = unicodedata.normalize("NFKD", str(value or "").casefold().replace("œ", "oe"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def birth(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def identity(row):
    return (words(row["nom"]).replace(" ", ""), words(row["prenom"]), birth(row["date_naissance"]))


def document_status(data):
    """Read only explicitly identified PJ fields, never filenames or free-text comments."""
    cols = {words(k): v.strip() for k, v in data.items()}
    label = next((cols[k] for k in ("piece justificative demandee", "libelle piece justificative",
                                    "codelibelle piece justificative", "code libelle piece justificative")
                  if cols.get(k)), "")
    if not label or label in ("-", "–"):
        return None
    deposit = words(cols.get("pj deposee par candidat on") or cols.get("pj deposee par candidat"))
    deposited = {"oui": "Déposée", "o": "Déposée", "non": "Non déposée", "n": "Non déposée"}.get(deposit)
    review = words(cols.get("statut piece justificative") or cols.get("statut pj")
                   or cols.get("traitement administratif de la piece"))
    official = {words(v): v for v in ("En attente de contrôle", "Reçue", "Conforme", "Non conforme")}
    return {"label": label, "deposit": deposited, "review": official.get(review)}


def parse_report(raw, academy, expected_year=None, expected_states=None):
    if not raw or len(raw) > MAX_BYTES:
        raise CycladesError("Fichier CYCLADES vide ou trop volumineux.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise CycladesError("Encodage du fichier CYCLADES non reconnu.") from None
    try:
        reader = csv.reader(io.StringIO(content, newline=""), delimiter=";", strict=True)
        meta = []
        for row in reader:
            if "Nom de famille" in row and "Etat" in row:
                headers = [c.strip() for c in row]
                break
            meta.append(next((c.strip() for c in row if c.strip()), ""))
            if len(meta) > 24:
                raise CycladesError("La liste détaillée CYCLADES au format CSV est nécessaire.")
        else:
            raise CycladesError("Les colonnes de la liste détaillée CYCLADES sont absentes.")
        expected = {"N° Candidat", "Nom de famille", "Prénom(s)", "Date de naissance",
                    "N° inscription", "Code établissement inscription", "Etat"}
        uai = ACADEMIES[academy][1]
        if not expected.issubset(headers) or len(headers) != len(set(headers)):
            raise CycladesError("Le format de la liste détaillée CYCLADES a changé.")
        if not meta or not re.fullmatch(r"20\d{2}", meta[0]) or not any(f"({uai})" in line for line in meta):
            raise CycladesError("La session ou l’UAI du fichier ne correspond pas à cet établissement.")
        year = int(meta[0])
        if expected_year is not None and year != expected_year:
            raise CycladesError("La session du fichier diffère de la session sélectionnée.")
        stamp = next((re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", line) for line in meta
                      if words(line).startswith("edite le ")), None)
        if not stamp:
            raise CycladesError("La date d’édition du fichier CYCLADES est introuvable.")
        try:
            issued = datetime.strptime(stamp[1], "%d/%m/%Y %H:%M").replace(tzinfo=PARIS).timestamp()
        except ValueError:
            raise CycladesError("La date d’édition du fichier CYCLADES est invalide.") from None
        records = []
        grouped_documents = {}
        for row in reader:
            if not any(v.strip() for v in row):
                continue
            if len(row) != len(headers):
                raise CycladesError("Le fichier CYCLADES est incomplet.")
            data = dict(zip(headers, (v.strip() for v in row)))
            if data["Code établissement inscription"] != uai or not data["N° Candidat"] or not data["Etat"]:
                raise CycladesError("Une ligne est incomplète ou appartient à un autre établissement.")
            details = {label: data[col].strip("'") for col, label in DETAILS.items()
                       if data.get(col) and data[col] not in ("-", "–")}
            exams = {key: value for key, value in data.items()
                     if re.match(r"^(?:[0-9]{4,6}\s*:\s*E|ECT\s*-)", key, re.I)
                     and value and value not in ("-", "–")}
            entry = {"status": data["Etat"], "details": details, "exams": exams}
            document = document_status(data)
            if document:
                # A list can contain one row per piece for the same registration.
                key = (data["N° Candidat"], data["N° inscription"], data.get("N° version"), data["Etat"],
                       data["Nom de famille"], data.get("Nom"), data["Prénom(s)"], data["Date de naissance"])
                if key in grouped_documents:
                    pieces = grouped_documents[key]
                    if document not in pieces:
                        pieces.append(document)
                    continue
                entry["documents"] = grouped_documents[key] = [document]
            records.append((data["Nom de famille"], data.get("Nom", ""), data["Prénom(s)"],
                            birth(data["Date de naissance"]), entry))
    except csv.Error:
        raise CycladesError("Le fichier CSV CYCLADES est illisible.") from None
    # This line is generated by CYCLADES, including any extra name/class filters.
    # Only a whole-academy list can be used as evidence of a missing student.
    criteria = next((line.partition(":")[2].strip() for line in meta if words(line).startswith("criteres de recherche ")), "")
    states = re.fullmatch(r"[ÉE]tat\s+[EÉ]gal\s+(.+)", criteria, flags=re.I)
    selected = {words(v) for v in states[1].split(",")} if states else set()
    return Report(year, issued, records, selected == (expected_states or ALL_STATES))


def with_exams(report, supplement):
    if report.year != supplement.year:
        raise CycladesError("Les fichiers CYCLADES doivent concerner la même session.")
    def key(entry):
        family, _, given, dob, record = entry
        details = record["details"]
        return (family, given, dob, record["status"], details.get("N° de candidat"),
                details.get("N° d’inscription"), details.get("Version"), details.get("UAI"))
    additional = {key(entry): entry[-1] for entry in supplement.records}
    for entry in report.records:
        extra = additional.get(key(entry))
        if extra:
            entry[-1]["exams"] = extra["exams"]
            if extra.get("documents") and not entry[-1].get("documents"):
                entry[-1]["documents"] = extra["documents"]
    return report


def schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cyclades_accounts (
            academy TEXT PRIMARY KEY, credential BLOB, revision INTEGER NOT NULL DEFAULT 0,
            day TEXT, attempted REAL, status TEXT, message TEXT);
        CREATE TABLE IF NOT EXISTS cyclades_sessions (
            academy TEXT, year INTEGER, issued REAL NOT NULL, origin TEXT NOT NULL,
            PRIMARY KEY (academy, year));
        CREATE TABLE IF NOT EXISTS cyclades_students (
            candidate_id TEXT, academy TEXT, year INTEGER, identity TEXT NOT NULL,
            outcome TEXT NOT NULL, records TEXT NOT NULL, seen REAL,
            PRIMARY KEY (candidate_id, academy, year));
        CREATE TRIGGER IF NOT EXISTS cyclades_delete_student AFTER DELETE ON candidats
            BEGIN DELETE FROM cyclades_students WHERE candidate_id=OLD.id; END;
        CREATE TRIGGER IF NOT EXISTS cyclades_change_identity AFTER UPDATE OF nom,prenom,date_naissance ON candidats
            WHEN NEW.nom IS NOT OLD.nom OR NEW.prenom IS NOT OLD.prenom OR NEW.date_naissance IS NOT OLD.date_naissance
            BEGIN DELETE FROM cyclades_students WHERE candidate_id=OLD.id; END;
    """)
    conn.executemany("INSERT OR IGNORE INTO cyclades_accounts(academy) VALUES(?)", [(key,) for key in ACADEMIES])
    # The INSERT above holds the SQLite write lock, including during migration on existing disks.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(cyclades_accounts)")}
    if "reader_version" not in columns:
        conn.execute("ALTER TABLE cyclades_accounts ADD COLUMN reader_version INTEGER NOT NULL DEFAULT 0")
    if "network_retry" not in columns:
        conn.execute("ALTER TABLE cyclades_accounts ADD COLUMN network_retry REAL")


def registration_indicator(record):
    status = record.get("status")
    if words(status) != "inscrit":
        return "red", status or "Statut inconnu"
    summary = record.get("piece_summary") or {}
    docs = record.get("documents") or []
    # A newer count-only or partial observation cannot confirm an older complete list.
    if summary and summary.get("checked") != record.get("documents_checked"):
        if not record.get("documents_checked"):
            return "red", "Lecture partielle"
        stamp_format = "%d/%m/%Y à %Hh%M"
        if datetime.strptime(summary["checked"], stamp_format) > datetime.strptime(record["documents_checked"], stamp_format):
            return "red", "Lecture partielle"
        summary = {}  # A more recent complete observation takes precedence.
    requested = summary.get("requested", record.get("requested"))
    conforming = summary.get("conforming", record.get("conforming"))
    if requested != len(docs) or conforming is None:
        return "red", "Pièces à vérifier"
    if any(p.get("review") == "Non conforme" for p in docs):
        return "red", "Pièce non conforme"
    for piece in docs:
        if "Déposée" not in (piece.get("deposit"), piece.get("manager")):
            return "red", "Dépôt à vérifier" if not piece.get("deposit") else "Dépôt manquant"
    reviews = [p.get("review") for p in docs]
    if conforming != reviews.count("Conforme"):
        return "red", "Contrôle à vérifier"
    if conforming == requested:
        return "green", "Pièces conformes" if requested else "Aucune pièce demandée"
    if all(r in ("Conforme", "En attente de contrôle") for r in reviews):
        return "orange", "En attente de contrôle"
    return "red", "Contrôle à vérifier"


def directory_indicators(conn, rows):
    """Add a single status per BTS student for the current exam session."""
    from training_programs import BTS_LABELS
    today = datetime.now(PARIS).date()
    year = today.year + (today.month >= 9)
    students = {r["id"]: r for r in rows if r["bts"] in BTS_LABELS}
    indicators = defaultdict(list)
    for entry in conn.execute("""SELECT candidate_id,identity,outcome,records FROM cyclades_students
                                 WHERE year=? AND outcome IN ('matched','ambiguous')""", (year,)):
        row = students.get(entry["candidate_id"])
        if row is None or json.dumps(identity(row), ensure_ascii=False) != entry["identity"]:
            continue
        results = indicators[row["id"]]
        if entry["outcome"] == "ambiguous":
            results.append(("red", "Identité à vérifier"))
        else:
            results.extend(registration_indicator(rec) for rec in json.loads(entry["records"]))
    # When several registrations are attached, show the one that needs attention.
    rank = {"red": 0, "orange": 1, "green": 2}
    for cid, row in students.items():
        row["cyclades_indicator"] = min(indicators[cid], key=lambda item: rank[item[0]],
                                        default=("red", "Inscription non vérifiée"))
    return year


def match_report(conn, report):
    students = {}
    by_name_birth = defaultdict(list)
    from training_programs import BTS_LABELS
    bts = tuple(BTS_LABELS)
    for row in conn.execute("SELECT id,nom,prenom,date_naissance FROM candidats WHERE bts IN (" + ",".join("?" for _ in bts) + ")", bts):
        family, given, dob = identity(row)
        students[row["id"]] = (family, given, dob)
        if all((family, given, dob)):
            by_name_birth[family, dob].append((row["id"], given))
    found = defaultdict(list)
    ambiguous = set()
    for family, use_name, given, dob, record in report.records:
        given = words(given)
        matches = {cid for name in (family, use_name)
                   for cid, firstname in by_name_birth.get((words(name).replace(" ", ""), dob), ())
                   if given == firstname or given.startswith(firstname + " ")}
        if len(matches) == 1:
            found[matches.pop()].append(record)
        elif matches:
            ambiguous.update(matches)
    return students, found, ambiguous


def apply_report(conn, academy, report, origin):
    """Replace one complete academy/session observation inside a single transaction."""
    year, issued, records, complete = report
    if not complete:
        raise CycladesError("Sélectionnez tous les états et retirez les autres critères de la liste détaillée.")
    previous = conn.execute("SELECT issued,origin FROM cyclades_sessions WHERE academy=? AND year=?",
                            (academy, year)).fetchone()
    if previous and (previous["issued"] > issued or
                     (previous["issued"] == issued and previous["origin"] == "auto" and origin == "import")):
        return False
    students, found, ambiguous = match_report(conn, report)
    for cid, ident in students.items():
        outcome = ("ambiguous" if cid in ambiguous else "matched" if found[cid] else
                   "incomplete" if not all(ident) else "missing")
        fingerprint = json.dumps(ident, ensure_ascii=False)
        if outcome == "matched":
            last = conn.execute("SELECT records FROM cyclades_students WHERE candidate_id=? AND academy=? AND year=? AND identity=?",
                                (cid, academy, year, fingerprint)).fetchone()
            if last:
                def registration(record):
                    return tuple(record["details"].get(k) for k in ("N° de candidat", "N° d’inscription", "Version"))
                earlier = {registration(r): r for r in json.loads(last[0]) if r.get("documents_checked") or r.get("piece_summary")}
                for record in found[cid]:
                    old = earlier.get(registration(record))
                    if old and old.get("piece_summary") and not record.get("documents_checked") and not record.get("piece_summary"):
                        record["piece_summary"] = old["piece_summary"]
                    if old and old.get("documents_checked") and not record.get("documents_checked") and not record.get("documents"):
                        for key in ("documents", "documents_checked", "requested", "conforming"):
                            record[key] = old[key]
                        if old.get("documents_source"):
                            record["documents_source"] = old["documents_source"]
        payload = json.dumps(found[cid] if outcome == "matched" else [], ensure_ascii=False)
        conn.execute("""INSERT INTO cyclades_students VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id,academy,year) DO UPDATE SET
            identity=excluded.identity, outcome=excluded.outcome,
            records=CASE WHEN excluded.outcome='missing' AND cyclades_students.identity=excluded.identity
                         THEN cyclades_students.records ELSE excluded.records END,
            seen=CASE WHEN excluded.outcome='missing' AND cyclades_students.identity=excluded.identity
                         THEN cyclades_students.seen ELSE excluded.seen END""",
                     (cid, academy, year, fingerprint, outcome, payload, issued if outcome == "matched" else None))
    conn.execute("INSERT OR REPLACE INTO cyclades_sessions VALUES (?,?,?,?)", (academy, year, issued, origin))
    return True
