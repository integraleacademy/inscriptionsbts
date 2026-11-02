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
            records.append((data["Nom de famille"], data.get("Nom", ""), data["Prénom(s)"],
                            birth(data["Date de naissance"]), {"status": data["Etat"], "details": details, "exams": exams}))
    except csv.Error:
        raise CycladesError("Le fichier CSV CYCLADES est illisible.") from None
    # This line is generated by CYCLADES, including any extra name/class filters.
    # Only a whole-academy list can be used as evidence of a missing student.
    criteria = next((line.partition(":")[2].strip() for line in meta if words(line).startswith("criteres de recherche ")), "")
    states = re.fullmatch(r"[ÉE]tat\s+[EÉ]gal\s+(.+)", criteria, flags=re.I)
    selected = {words(v) for v in states[1].split(",")} if states else set()
    all_states = {"anomalie", "inscrit", "non inscrit", "pre inscrit", "redoublant"}
    return Report(year, issued, records, selected == (expected_states or all_states))


def with_exams(report, supplement):
    if report.year != supplement.year:
        raise CycladesError("Les fichiers CYCLADES doivent concerner la même session.")
    def key(entry):
        family, _, given, dob, record = entry
        details = record["details"]
        return (family, given, dob, record["status"], details.get("N° de candidat"),
                details.get("N° d’inscription"), details.get("Version"), details.get("UAI"))
    exams = {key(entry): entry[-1]["exams"] for entry in supplement.records}
    for entry in report.records:
        if key(entry) in exams:
            entry[-1]["exams"] = exams[key(entry)]
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
    students = {}
    by_name_birth = defaultdict(list)
    for row in conn.execute("SELECT id,nom,prenom,date_naissance FROM candidats"):
        family, given, dob = identity(row)
        students[row["id"]] = (family, given, dob)
        if all((family, given, dob)):
            by_name_birth[family, dob].append((row["id"], given))
    found = defaultdict(list)
    ambiguous = set()
    for family, use_name, given, dob, record in records:
        given = words(given)
        matches = {cid for name in (family, use_name)
                   for cid, firstname in by_name_birth.get((words(name).replace(" ", ""), dob), ())
                   if given == firstname or given.startswith(firstname + " ")}
        if len(matches) == 1:
            found[matches.pop()].append(record)
        elif matches:
            ambiguous.update(matches)
    for cid, ident in students.items():
        outcome = ("ambiguous" if cid in ambiguous else "matched" if found[cid] else
                   "incomplete" if not all(ident) else "missing")
        fingerprint = json.dumps(ident, ensure_ascii=False)
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
