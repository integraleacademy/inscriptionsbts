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
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

from cyclades_data import ACADEMIES, MAX_BYTES, PARIS, CycladesError, CycladesNetworkError, apply_report, identity, match_report, parse_report, piece_receipt, with_exams, words
from cyclades_portal import read_academy
from cyclades_slips import read_slips, slip_key

READER_VERSION = 25


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
    person = identity(student)
    identifiable = all(person)
    accounts = summaries(conn)
    sources = {key: item["status"] for key, item in accounts.items() if item["connected"]}
    busy = any(status in (None, "pending", "running") for status in sources.values())
    partial = "error" in sources.values()
    checked, outcomes = set(), set()
    matches, history = [], []
    latest = None
    for entry in conn.execute("""SELECT s.*,c.outcome,c.records,c.seen FROM cyclades_students c
        JOIN cyclades_sessions s USING (academy,year) WHERE c.candidate_id=? AND c.identity=?
        ORDER BY s.year DESC,s.issued DESC,s.academy""", (student["id"], json.dumps(person, ensure_ascii=False))):
        checked.add(entry["academy"])
        outcomes.add(entry["outcome"])
        latest = max(latest or 0, entry["issued"])
        if entry["outcome"] not in ("matched", "missing"):
            continue
        for record in json.loads(entry["records"]):
            tone = {"inscrit": "green", "pre inscrit": "blue", "anomalie": "amber",
                    "non inscrit": "amber"}.get(words(record["status"]), "slate")
            attempt = accounts[entry["academy"]]
            item = dict(record, last_partial_attempt=attempt["attempt"] if attempt["connected"] and attempt["status"] == "error" else None, candidate_id=student["id"], academy_key=entry["academy"], academy=ACADEMIES[entry["academy"]][0], year=entry["year"],
                        seen=display_time(entry["seen"]), origin=entry["origin"], tone=tone)
            item["slip_eligible"] = bool(slip_key(record)) and entry["outcome"] == "matched"
            item["slip_ready"] = bool(item.pop("sealed_slip", None))
            (matches if entry["outcome"] == "matched" else history).append(item)

    unsearched = [key for key, status in sources.items() if status == "ok" and key not in checked]
    if not identifiable:
        state = "identity"
    elif matches:
        state = "matched"
    elif "ambiguous" in outcomes:
        state = "ambiguous"
    elif busy or unsearched:
        state = "searching"
    elif partial:
        state = "partial"
    elif checked:
        state = "empty"
    else:
        state = "unconfigured"
    return dict(state=state, matches=matches, history=history, verified=display_time(latest),
                busy=busy and identifiable, partial=partial, ambiguous="ambiguous" in outcomes,
                can_search=bool(sources) and identifiable, unsearched=unsearched if identifiable else [])


def run_due(app, connect, directory, *, now=None, fetch=None):
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
            # The daily slot starts at 08:00 Paris time. An early manual check
            # belongs to the previous slot, so today's scheduled check stays due.
            slot = (clock.date() if clock.hour >= 8 else clock.date() - timedelta(days=1)).isoformat()
            with closing(connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM cyclades_accounts WHERE academy=?", (key,)).fetchone()
                if not row or not row["credential"]:
                    continue
                # First connection is checked immediately. Subsequent days start at 08:00.
                reader_changed = row["reader_version"] < READER_VERSION and (
                    row["status"] == "error" or row["reader_version"] > 0)
                recovering = row["status"] == "running" or (reader_changed and (row["network_retry"] is None or
                    (key == "nice" and row["network_retry"] == -1 and row["reader_version"] < 20)))
                daily_due = clock.hour >= 8 and (row["day"] or "") < slot
                retry_at = row["network_retry"]
                retry_due = retry_at is not None and retry_at > 0 and retry_at <= clock.timestamp() and row["status"] == "error"
                if row["day"] is not None and row["status"] != "pending" and not (recovering or daily_due or retry_due):
                    continue
                # -1 marks the recovery attempt already consumed for this daily slot.
                retry_used = (retry_due or retry_at == -1) and not daily_due
                revision = row["revision"]
                conn.execute("UPDATE cyclades_accounts SET day=?,attempted=?,reader_version=?,network_retry=?,status='running',message='' WHERE academy=?",
                             (slot, clock.timestamp(), READER_VERSION, -1 if retry_used else None, key))
                conn.commit()
            interrupted = False
            errors = []
            counts = []
            try:
                credentials = json.loads(cipher(app).decrypt(row["credential"]))
                if fetch is None:
                    def matched_records(report):
                        with closing(connect()) as conn:
                            _, found, ambiguous = match_report(conn, report)
                        return [r for cid, records in found.items() if cid not in ambiguous for r in records]
                    source = read_academy(key, credentials, matched_records, cipher(app))
                else:
                    source = fetch(key, credentials)
                with closing(source) as reports:
                    for report in reports:
                        if isinstance(report, CycladesError):
                            interrupted |= isinstance(report, CycladesNetworkError)
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
                interrupted = isinstance(error, CycladesNetworkError)
                errors.append(str(error))
            except Exception:
                errors.append("La lecture de CYCLADES a été interrompue. Les dernières données sont conservées.")
            next_retry = -1 if retry_used else None
            if interrupted and not retry_used:
                next_retry = clock.timestamp() + 1800
                errors.append(f"Nouvelle tentative prévue à {datetime.fromtimestamp(next_retry, PARIS):%Hh%M}.")
            with closing(connect()) as conn:
                updated = conn.execute("UPDATE cyclades_accounts SET status=?, message=?, network_retry=? WHERE academy=? AND revision=?",
                             ("error" if errors else "ok", " ".join(errors), next_retry, key, revision))
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
    app.jinja_env.globals["cyclades_receipt"] = piece_receipt

    def guard(key=None):
        if not require_admin():
            abort(403)
        if key is not None and key not in ACADEMIES:
            abort(404)
        expected = session.get("_planning_csrf", "")
        if not expected or not hmac.compare_digest(request.form.get("csrf_token", ""), expected):
            abort(403)

    def finish(key, message, error=False):
        if request.form.get("action") == "retry" and request.headers.get("Accept") == "application/json":
            return jsonify(message=message), 409 if error else 202
        flash(message, "error" if error else "success")
        return redirect(url_for("admin_settings", _anchor=f"cyclades-{key}"), code=303)

    @app.route("/admin/candidat/<cid>/cyclades", methods=["GET", "POST"])
    def cyclades_candidate_search(cid):
        from training_programs import BTS_LABELS

        requested = request.method == "POST"
        if requested:
            guard()
        elif not require_admin():
            abort(403)
        queued = 0
        notice = ""
        with closing(connect()) as conn:
            if requested:
                conn.execute("BEGIN IMMEDIATE")
            student = conn.execute("SELECT id,bts,nom,prenom,date_naissance FROM candidats WHERE id=?", (cid,)).fetchone()
            if not student or student["bts"] not in BTS_LABELS:
                abort(404)
            result = sheet_status(conn, student)
            if requested and result["can_search"]:
                automatic = request.form.get("mode") == "initial"
                keys = result["unsearched"] if automatic else ACADEMIES
                cutoff = datetime.now(PARIS).timestamp() - 300
                for key in keys:
                    queued += conn.execute("""UPDATE cyclades_accounts SET status='pending',message=''
                        WHERE academy=? AND credential IS NOT NULL AND status IN ('ok','error')
                        AND (attempted IS NULL OR attempted < ? OR ?)""",
                        (key, cutoff, key in result["unsearched"])).rowcount
                conn.commit()
                if queued:
                    result = sheet_status(conn, student)
                elif not automatic and not result["busy"]:
                    notice = "Une vérification a eu lieu il y a moins de cinq minutes."
        if queued:
            start()
            wake.set()
        if requested and request.headers.get("X-Cyclades-Fragment") != "1":
            return redirect(url_for("admin_candidate_sheet", cid=cid, return_to=request.form.get("return_to") or None) + "#cyclades", code=303)
        return render_template("_cyclades_result.html", cyclades=result, notice=notice), 200, {"Cache-Control": "no-store"}

    @app.post("/admin/candidat/<cid>/cyclades/<key>/<int:year>/acces")
    def cyclades_student_access(cid, key, year):
        if request.content_length is None or request.content_length > MAX_BYTES + 65536:
            abort(413)
        guard(key)
        candidate = request.form.get("candidate")
        registration = request.form.get("registration")
        importing = request.form.get("action") == "import"
        upload = request.files.get("slip") if importing else None
        with closing(connect()) as conn:
            student = conn.execute("SELECT id,bts,nom,prenom,date_naissance FROM candidats WHERE id=?", (cid,)).fetchone()
            from training_programs import BTS_LABELS
            if not student or student["bts"] not in BTS_LABELS:
                abort(404)
            entry = conn.execute("""SELECT records FROM cyclades_students WHERE candidate_id=? AND academy=?
                AND year=? AND identity=? AND outcome='matched'""",
                (cid, key, year, json.dumps(identity(student), ensure_ascii=False))).fetchone()
            records = json.loads(entry["records"]) if entry else []
            matching = [r for r in records if slip_key(r) and r["details"]["N° de candidat"] == candidate
                        and r["details"]["N° d’inscription"] == registration]
            if len(matching) != 1:
                abort(404)
            record = matching[0]
            ref = slip_key(record)
            try:
                if importing:
                    if not upload:
                        raise CycladesError("Sélectionnez le PDF de papillons délivré par Cyclades.")
                    found = read_slips(upload.stream.read(MAX_BYTES + 1), {ref})
                    if ref not in found:
                        raise CycladesError("Aucun papillon unique ne correspond au candidat, à l’inscription et à l’identifiant de cette fiche.")
                    record["sealed_slip"] = cipher(app).encrypt(found[ref].encode()).decode()
                    record["slip_imported"] = True
                    changed = conn.execute("""UPDATE cyclades_students SET records=? WHERE candidate_id=? AND academy=?
                        AND year=? AND outcome='matched' AND records=? AND identity=?""",
                        (json.dumps(records, ensure_ascii=False), cid, key, year, entry["records"], json.dumps(identity(student), ensure_ascii=False)))
                    if not changed.rowcount:
                        raise CycladesError("Le dossier vient de changer. Actualisez la fiche et relancez la lecture.")
                    conn.commit()
                if not record.get("sealed_slip"):
                    raise CycladesError("Aucun papillon disponible pour cette inscription.")
                password = cipher(app).decrypt(record["sealed_slip"].encode()).decode()
            except (CycladesError, InvalidToken) as exc:
                message = str(exc) if isinstance(exc, CycladesError) else "Le papillon doit être relu ou importé."
                flash(message, "error")
                return redirect(url_for("admin_candidate_sheet", cid=cid, return_to=request.form.get("return_to") or None) + "#cyclades", code=303)
        return render_template("cyclades_access.html", student=student, login=ref[2], password=password,
                               year=year, academy=ACADEMIES[key][0]), 200, {
            "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}

    @app.post("/admin/candidat/<cid>/cyclades/<key>/<int:year>/releve-pieces")
    def cyclades_piece_statement(cid, key, year):
        from cyclades_pieces import parse_detail

        guard(key)
        if request.content_length and request.content_length > 160_000:
            abort(413)
        back = redirect(url_for("admin_candidate_sheet", cid=cid, return_to=request.form.get("return_to") or None)
                        + "#cyclades", code=303)
        try:
            observed = datetime.strptime(request.form.get("observed", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=PARIS)
        except ValueError:
            abort(400)
        raw = request.form.get("statement", "")
        if (observed > datetime.now(PARIS) or not re.search(
                rf"\bbts {year} academie de {words(ACADEMIES[key][0])}\b", words(raw))):
            flash("Vérifiez la date du relevé et la ligne BTS indiquant la session et l’académie.", "error")
            return back
        with closing(connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT records FROM cyclades_students WHERE candidate_id=? AND academy=?
                                  AND year=? AND outcome='matched'""", (cid, key, year)).fetchone()
            if not row:
                abort(409)
            records = json.loads(row["records"])
            matched = [(record, result) for record in records
                       if (result := parse_detail(raw, record, ACADEMIES[key][1])) is not None]
            if len(matched) != 1:
                flash("Le relevé est incomplet ou ne correspond pas à cette inscription.", "error")
                return back
            record, result = matched[0]
            stamp = record.get("documents_checked")
            if stamp and datetime.strptime(stamp, "%d/%m/%Y à %Hh%M").replace(tzinfo=PARIS) >= observed:
                flash("Un relevé aussi récent ou plus récent est déjà affiché.", "info")
                return back
            if record.get("documents") and not stamp:
                flash("Un relevé Cyclades est déjà disponible pour cette inscription.", "info")
                return back
            record.update(result, documents_source="statement", documents_checked=display_time(observed.timestamp()))
            conn.execute("UPDATE cyclades_students SET records=? WHERE candidate_id=? AND academy=? AND year=?",
                         (json.dumps(records, ensure_ascii=False), cid, key, year))
            conn.commit()
        flash("Relevé des pièces justificatives enregistré.", "success")
        return back

    @app.post("/admin/parametres/cyclades/<key>/connexion")
    def cyclades_settings(key):
        guard(key)
        action = request.form.get("action")
        if action == "retry":
            with closing(connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                queued = conn.execute("""UPDATE cyclades_accounts SET status='pending',message=''
                    WHERE academy=? AND credential IS NOT NULL AND status IN ('ok','error')""", (key,)).rowcount
                if not queued:
                    connected = conn.execute("SELECT credential IS NOT NULL FROM cyclades_accounts WHERE academy=?",
                                             (key,)).fetchone()[0]
                    if not connected:
                        return finish(key, "Enregistrez les accès de cette académie avant de lancer la vérification.", True)
                    return finish(key, "Une vérification est déjà prévue ou en cours pour cette académie.")
                conn.commit()
            start()
            wake.set()
            return finish(key, f"{ACADEMIES[key][0]} · Vérification enregistrée sur le serveur. Vous pouvez quitter la page.")
        credential = None
        if action == "save":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            birthdate = request.form.get("birthdate", "").strip() if key == "nice" else ""
            if not (0 < len(username) <= 200 and 0 < len(password) <= 512) or (birthdate and not re.fullmatch(r"[0-9]{8}", birthdate)):
                return finish(key, "Vérifiez l’identifiant, le mot de passe et le format de la date éventuelle.", True)
            try:
                credential = cipher(app).encrypt(json.dumps(dict(username=username, password=password, birthdate=birthdate)).encode())
            except CycladesError as error:
                return finish(key, str(error), True)
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
        return finish(key, f"{ACADEMIES[key][0]} · {message}")

    @app.post("/admin/parametres/cyclades/<key>/import")
    def cyclades_import(key):
        if request.content_length and request.content_length > 2 * MAX_BYTES + 65536:
            abort(413)
        guard(key)
        upload = request.files.get("export")
        if not upload:
            return finish(key, "Sélectionnez une liste détaillée CYCLADES au format CSV.", True)
        try:
            report = parse_report(upload.stream.read(MAX_BYTES + 1), key)
            extra = request.files.get("exams")
            if extra:
                supplement = parse_report(extra.stream.read(MAX_BYTES + 1), key, expected_year=report.year)
                with_exams(report, supplement)
        except CycladesError as error:
            return finish(key, str(error), True)
        try:
            with closing(connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted = apply_report(conn, key, report, "import")
                conn.commit()
        except CycladesError as error:
            return finish(key, str(error), True)
        if not accepted:
            return finish(key, "Une édition identique ou plus récente est déjà disponible.")
        return finish(key, f"{ACADEMIES[key][0]} · Liste de la session {report.year} importée.")
