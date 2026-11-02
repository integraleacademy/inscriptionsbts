"""Daily, read-only BTS examination follow-up on the application's persistent disk."""
import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, flash, redirect, request, session, url_for

from cyclades_data import ACADEMIES, MAX_BYTES, PARIS, CycladesError, apply_report, identity, parse_report, with_exams
from cyclades_portal import read_academy

READER_VERSION = 7


def cipher(app):
    key = app.secret_key
    if not key or len(key) < 20:
        raise CycladesError("La clé de chiffrement de la plateforme doit être configurée avant la connexion.")
    raw = key.encode() if isinstance(key, str) else key
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"bts-cyclades-v1\x00" + raw).digest()))


def display_time(ts):
    return datetime.fromtimestamp(ts, PARIS).strftime("%d/%m/%Y à %Hh%M") if ts else ""


def summaries(conn):
    rows = {row["academy"]: row for row in conn.execute(
        "SELECT academy,credential IS NOT NULL AS connected,status,message,attempted FROM cyclades_accounts")}
    return {key: {"label": values[0], "url": values[2], "connected": bool(rows[key]["connected"]),
                  "status": rows[key]["status"], "message": rows[key]["message"],
                  "attempt": display_time(rows[key]["attempted"])}
            for key, values in ACADEMIES.items()}


def sheet_status(conn, student):
    result = summaries(conn)
    uid = json.dumps(identity(student), ensure_ascii=False)
    for info in result.values():
        info["sessions"] = []
    for entry in conn.execute("""SELECT s.*,c.outcome,c.records,c.seen FROM cyclades_sessions s
        LEFT JOIN cyclades_students c ON c.academy=s.academy AND c.year=s.year
            AND c.candidate_id=? AND c.identity=? ORDER BY s.year DESC""", (student["id"], uid)):
        result[entry["academy"]]["sessions"].append({
            "year": entry["year"], "issued": display_time(entry["issued"]), "origin": entry["origin"],
            "outcome": entry["outcome"], "records": json.loads(entry["records"] or "[]"),
            "seen": display_time(entry["seen"])})
    return result


def run_due(app, connect, directory, *, now=None, fetch=read_academy):
    # flock is held only across this worker's batch, never across a web request.
    # A worker exit frees it immediately. SQLite stores the durable per-academy
    # day and checkpoints completed sessions, independently of Flask sessions.
    with (Path(directory) / "cyclades-sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for key in ACADEMIES:
            clock = (now or datetime.now(PARIS)).astimezone(PARIS)
            today = clock.date().isoformat()
            with closing(connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM cyclades_accounts WHERE academy=?", (key,)).fetchone()
                if not row or not row["credential"]:
                    continue
                # First connection is checked immediately. Subsequent days start at 08:00.
                recovering = row["status"] == "running" or (
                    row["status"] == "error" and row["reader_version"] < READER_VERSION)
                if not recovering and row["day"] is not None and (row["day"] == today or clock.hour < 8):
                    continue
                revision = row["revision"]
                conn.execute("UPDATE cyclades_accounts SET day=?,attempted=?,reader_version=?,status='running',message='' WHERE academy=?",
                             (today, clock.timestamp(), READER_VERSION, key))
                conn.commit()
            errors = []
            counts = []
            try:
                credentials = json.loads(cipher(app).decrypt(row["credential"]))
                with closing(fetch(key, credentials)) as reports:
                    for report in reports:
                        if isinstance(report, CycladesError):
                            errors.append(str(report))
                            continue
                        with closing(connect()) as conn:
                            conn.execute("BEGIN IMMEDIATE")
                            if conn.execute("SELECT revision FROM cyclades_accounts WHERE academy=?", (key,)).fetchone()[0] != revision:
                                break
                            if apply_report(conn, key, report, "auto"):
                                counts.append(f"{report.year}={len(report.records)}")
                            conn.commit()
                            app.logger.info("CYCLADES %s session %d, %d dossiers lus", key, report.year, len(report.records))
            except InvalidToken:
                errors.append("La clé du serveur a changé. Renseignez de nouveau les accès.")
            except CycladesError as error:
                errors.append(str(error))
            except Exception:
                errors.append("La lecture de CYCLADES a été interrompue. Les dernières données sont conservées.")
            with closing(connect()) as conn:
                updated = conn.execute("UPDATE cyclades_accounts SET status=?, message=? WHERE academy=? AND revision=?",
                             ("error" if errors else "ok", " ".join(errors), key, revision))
                conn.commit()
            if updated.rowcount:
                log = app.logger.warning if errors else app.logger.info
                log("CYCLADES %s | %s | listes %s", key, " ".join(errors) or "lecture terminée", ", ".join(counts) or "—")


def register_cyclades(app, connect, require_admin, directory):
    wake = threading.Event()
    mutex = threading.Lock()
    worker_thread = None

    def worker():
        while True:
            wake.clear()
            try:
                run_due(app, connect, directory)
            except Exception:
                app.logger.warning("CYCLADES : vérification quotidienne interrompue.")
            wake.wait(60)

    def start():
        nonlocal worker_thread
        if app.testing or os.getenv("CYCLADES_SYNC_DISABLED") == "1":
            return
        with mutex:
            if worker_thread is None or not worker_thread.is_alive():
                worker_thread = threading.Thread(target=worker, name="cyclades-daily", daemon=True)
                worker_thread.start()

    app.before_request(start)
    app.extensions["cyclades_start"] = start

    def settings():
        with closing(connect()) as conn:
            return summaries(conn)

    app.jinja_env.globals["cyclades_accounts"] = settings

    def guard(key):
        if not require_admin():
            abort(403)
        if key not in ACADEMIES:
            abort(404)
        expected = session.get("_planning_csrf", "")
        if not expected or not hmac.compare_digest(request.form.get("csrf_token", ""), expected):
            abort(403)

    def finish(message, error=False):
        flash(message, "error" if error else "success")
        return redirect(url_for("admin_settings") + "#cyclades", code=303)

    @app.post("/admin/parametres/cyclades/<key>/connexion")
    def cyclades_settings(key):
        guard(key)
        action = request.form.get("action")
        if action == "retry":
            with closing(connect()) as conn:
                queued = conn.execute("""UPDATE cyclades_accounts SET day=NULL,status='pending',message=''
                    WHERE academy=? AND credential IS NOT NULL AND status='error'""", (key,)).rowcount
                conn.commit()
            if queued:
                start()
                wake.set()
            return finish("Nouvelle vérification demandée." if queued else "Aucune vérification en erreur à relancer.")
        credential = None
        if action == "save":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            birthdate = request.form.get("birthdate", "").strip() if key == "nice" else ""
            if not (0 < len(username) <= 200 and 0 < len(password) <= 512) or (birthdate and not re.fullmatch(r"[0-9]{8}", birthdate)):
                return finish("Vérifiez l’identifiant, le mot de passe et le format de la date éventuelle.", True)
            try:
                credential = cipher(app).encrypt(json.dumps(dict(username=username, password=password, birthdate=birthdate)).encode())
            except CycladesError as error:
                return finish(str(error), True)
        elif action != "remove":
            abort(400)
        with closing(connect()) as conn:
            conn.execute("""UPDATE cyclades_accounts SET credential=?,revision=revision+1,
                day=NULL,attempted=NULL,status=NULL,message='' WHERE academy=?""", (credential, key))
            conn.commit()
        if credential:
            start()
            wake.set()
        message = "Accès enregistré. La première vérification est demandée." if credential else "Connexion retirée."
        return finish(f"{ACADEMIES[key][0]} · {message}")

    @app.post("/admin/parametres/cyclades/<key>/import")
    def cyclades_import(key):
        if request.content_length and request.content_length > 2 * MAX_BYTES + 65536:
            abort(413)
        guard(key)
        upload = request.files.get("export")
        if not upload:
            return finish("Sélectionnez une liste détaillée CYCLADES au format CSV.", True)
        try:
            report = parse_report(upload.stream.read(MAX_BYTES + 1), key)
            extra = request.files.get("exams")
            if extra:
                supplement = parse_report(extra.stream.read(MAX_BYTES + 1), key, expected_year=report.year)
                with_exams(report, supplement)
        except CycladesError as error:
            return finish(str(error), True)
        try:
            with closing(connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted = apply_report(conn, key, report, "import")
                conn.commit()
        except CycladesError as error:
            return finish(str(error), True)
        if not accepted:
            return finish("Une édition identique ou plus récente est déjà disponible.")
        return finish(f"{ACADEMIES[key][0]} · Liste de la session {report.year} importée.")
