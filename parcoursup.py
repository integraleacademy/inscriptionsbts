# parcoursup.py
import os, uuid, sqlite3, json, re, time
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo
from openpyxl import load_workbook

# Blueprint Parcoursup
bp_parcoursup = Blueprint("parcoursup", __name__, template_folder="templates")

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "app.db")

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def get_stats_parcoursup():
    conn = db()
    cur = conn.cursor()
    # Totaux
    total = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats").fetchone()[0]
    mail_ok = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE mail_ok=1").fetchone()[0]
    sms_ok  = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE sms_ok=1").fetchone()[0]
    both_ok = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE mail_ok=1 AND sms_ok=1").fetchone()[0]
    only_mail = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE mail_ok=1 AND sms_ok=0").fetchone()[0]
    only_sms  = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE mail_ok=0 AND sms_ok=1").fetchone()[0]
    none_ok   = cur.execute("SELECT COUNT(*) FROM parcoursup_candidats WHERE mail_ok=0 AND sms_ok=0").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "mail_ok": mail_ok,
        "sms_ok": sms_ok,
        "both_ok": both_ok,
        "only_mail": only_mail,
        "only_sms": only_sms,
        "none_ok": none_ok,
        "incomplete": only_mail + only_sms + none_ok,  # tout ce qui n'a pas les 2 OK
    }

STATUTS_STYLE = {
    "preinscription": {"label": "Pré-inscription à traiter", "color": "#808080"},
    "validee": {"label": "Candidature validée", "color": "#3498db"},
    "confirmee": {"label": "Inscription confirmée", "color": "#f4c45a"},
    "reconf_en_cours": {"label": "Reconfirmation en cours", "color": "#ff9800"},
    "reconfirmee": {"label": "Inscription re-confirmée", "color": "#2ecc71"},
    "annulee": {"label": "Inscription annulée", "color": "#e74c3c"},
    "docs_non_conformes": {"label": "Documents non conformes", "color": "#000000"},
}

# =====================================================
# 🧱 Initialisation table Parcoursup
# =====================================================
def init_parcoursup_table():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS parcoursup_candidats (
        id TEXT PRIMARY KEY,
        nom TEXT,
        prenom TEXT,
        telephone TEXT,
        email TEXT,
        formation TEXT,
        mode TEXT,
        mail_ok INTEGER DEFAULT 0,
        sms_ok INTEGER DEFAULT 0,
        statut TEXT DEFAULT 'En attente de candidature',
        logs TEXT DEFAULT '[]',
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()

init_parcoursup_table()

# =====================================================
# 🏠 PAGE PRINCIPALE AVEC SYNCHRONISATION AUTO
# =====================================================
@bp_parcoursup.route("/parcoursup")
def dashboard():
    conn = db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, email, telephone FROM parcoursup_candidats")
        parcoursup_rows = cur.fetchall()

        for r in parcoursup_rows:
            email = (r["email"] or "").strip().lower()
            tel = (r["telephone"] or "").replace(" ", "").replace("+33", "0").strip()

            cur2 = conn.execute("""
                SELECT statut FROM candidats
                WHERE LOWER(TRIM(email)) = ?
                   OR REPLACE(REPLACE(tel, ' ', ''), '+33', '0') = ?
            """, (email, tel))
            existing = cur2.fetchone()

            if existing and existing["statut"]:
                cur.execute("UPDATE parcoursup_candidats SET statut=? WHERE id=?", (existing["statut"], r["id"]))

        conn.commit()
        print("✅ Synchronisation Parcoursup ↔ Admin réussie")

    except Exception as e:
        print("⚠️ Erreur de synchronisation Parcoursup ↔ Admin :", e)

    cur.execute("SELECT * FROM parcoursup_candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # 🔍 Extraction des dates d’envoi Mail/SMS depuis les logs
    for r in rows:
        try:
            logs = json.loads(r.get("logs", "[]"))
            mail_log = next((log for log in logs if log.get("type") == "mail"), None)
            sms_log = next((log for log in logs if log.get("type") == "sms"), None)
            r["mail_date"] = mail_log.get("date") if mail_log else None
            r["sms_date"] = sms_log.get("date") if sms_log else None
        except Exception as e:
            r["mail_date"] = r["sms_date"] = None

        # 🔍 Ajout du dernier statut SMS pour affichage direct
    for r in rows:
        try:
            logs = json.loads(r.get("logs", "[]"))
            sms_status = next((l.get("event") for l in reversed(logs) if l.get("type") == "sms_status"), None)
            r["sms_status"] = sms_status or "unknown"
        except Exception:
            r["sms_status"] = "unknown"


    stats = get_stats_parcoursup()
    return render_template(
        "parcoursup.html",
        title="Gestion Parcoursup",
        rows=rows,
        STATUTS_STYLE=STATUTS_STYLE,
        stats=stats
    )




# =====================================================
# 📤 IMPORTER UN FICHIER EXCEL (.xlsx) — AVEC LOGS + PAUSES
# =====================================================
@bp_parcoursup.route("/parcoursup/import", methods=["POST"])
def import_file():
    if "file" not in request.files:
        flash("Aucun fichier sélectionné", "error")
        return redirect(url_for("parcoursup.dashboard"))

    file = request.files["file"]
    if not file.filename.endswith(".xlsx"):
        flash("Format non supporté. Utilisez un fichier .xlsx", "error")
        return redirect(url_for("parcoursup.dashboard"))

    temp_path = os.path.join(DATA_DIR, secure_filename(file.filename))
    file.save(temp_path)
    wb = load_workbook(temp_path)
    ws = wb.active

    LOT_SIZE = 100
    total_rows = ws.max_row - 1
    total_lots = (total_rows // LOT_SIZE) + (1 if total_rows % LOT_SIZE else 0)

    print(f"🚀 Import total : {total_rows} lignes ({total_lots} lots de {LOT_SIZE})")

    conn = db()
    cur = conn.cursor()
    imported = mails_sent = sms_sent = duplicates = errors = 0
    row_index = 0

    try:
        for lot_index in range(total_lots):
            start_row = 2 + lot_index * LOT_SIZE
            end_row = min(start_row + LOT_SIZE - 1, ws.max_row)
            print(f"➡️ Traitement du lot {lot_index + 1}/{total_lots} (lignes {start_row}-{end_row})")

            for row in ws.iter_rows(min_row=start_row, max_row=end_row, values_only=True):
                try:
                    nom, prenom, telephone, email, formation, mode = row[:6]
                    if not email or not telephone:
                        continue

                    email = email.strip().lower()
                    telephone = str(telephone).strip().replace(" ", "")
                    if telephone.startswith("0"):
                        telephone = "+33" + telephone[1:]

                    cur.execute("SELECT id FROM parcoursup_candidats WHERE email=? OR telephone=?", (email, telephone))
                    if cur.fetchone():
                        duplicates += 1
                        continue

                    cid = str(uuid.uuid4())
                    now = datetime.now().isoformat()

                    cur.execute("""
                        INSERT INTO parcoursup_candidats 
                        (id, nom, prenom, telephone, email, formation, mode, mail_ok, sms_ok, statut, logs, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'En attente de candidature', '[]', ?)
                    """, (cid, nom, prenom, telephone, email, formation, mode, now))
                    imported += 1

                    # === Envoi du mail ===
                    html = f"""
                    <p>Bonjour {prenom},</p>
                    <p>Nous avons bien reçu votre candidature Parcoursup pour le BTS <b>{formation}</b>.</p>
                    <p>Merci de compléter votre pré-inscription ici :</p>
                    <p><a href='https://inscriptionsbts.onrender.com/'><b>👉 Formulaire de pré-inscription</b></a></p>
                    <p>À bientôt,<br><b>L’équipe Intégrale Academy</b></p>
                    """
                    if send_mail(email, "Votre candidature Parcoursup – Intégrale Academy", html):
                        mails_sent += 1
                        cur.execute("UPDATE parcoursup_candidats SET mail_ok=1 WHERE id=?", (cid,))
                        cur.execute("UPDATE parcoursup_candidats SET logs=json_insert(logs, '$[#]', json_object('type', 'mail', 'dest', ?, 'date', ?)) WHERE id=?", (email, now, cid))

                    # === Envoi du SMS ===
                    sms_msg = f"Bonjour {prenom}, nous avons bien reçu votre candidature Parcoursup pour le BTS {formation}. Pour finaliser : inscriptionsbts.onrender.com"
                    sms_id = send_sms_brevo(telephone, sms_msg)
                    if sms_id:
                        sms_sent += 1
                        cur.execute("UPDATE parcoursup_candidats SET sms_ok=1 WHERE id=?", (cid,))
                        cur.execute("UPDATE parcoursup_candidats SET logs=json_insert(logs, '$[#]', json_object('type', 'sms', 'dest', ?, 'id', ?, 'date', ?)) WHERE id=?", (telephone, str(sms_id), now, cid))

                    row_index += 1

                except Exception as e:
                    errors += 1
                    print(f"⚠️ Erreur ligne {row_index}: {e}")

            conn.commit()
            print(f"✅ Lot {lot_index + 1}/{total_lots} terminé — total partiel : {imported} importés, {mails_sent} mails, {sms_sent} SMS")
            time.sleep(2)  # 💤 pause 2 secondes entre lots

    finally:
        conn.close()
        os.remove(temp_path)

    flash(f"{imported} importés — {mails_sent} mails — {sms_sent} SMS — {duplicates} doublons — {errors} erreurs.", "success")
    print("🏁 Import terminé avec succès.")
    return redirect(url_for("parcoursup.dashboard"))

# =====================================================
# 🕵️‍♂️ VÉRIFICATION DU FICHIER EXCEL (AVANT IMPORT)
# =====================================================
@bp_parcoursup.route("/parcoursup/check", methods=["POST"])
def check_file():
    if "file" not in request.files:
        flash("Aucun fichier sélectionné", "error")
        return redirect(url_for("parcoursup.dashboard"))

    file = request.files["file"]
    if not file.filename.endswith(".xlsx"):
        flash("Format de fichier non supporté. Utilisez un fichier .xlsx", "error")
        return redirect(url_for("parcoursup.dashboard"))

    temp_path = os.path.join(DATA_DIR, secure_filename(file.filename))
    file.save(temp_path)
    wb = load_workbook(temp_path)
    ws = wb.active

    erreurs = []
    ligne_num = 2

    for row in ws.iter_rows(min_row=2, values_only=True):
        nom, prenom, telephone, email, formation, mode = row[:6]
        if not nom:
            erreurs.append(f"Ligne {ligne_num} : nom manquant")
        if not prenom:
            erreurs.append(f"Ligne {ligne_num} : prénom manquant")

        tel = str(telephone or "").strip().replace(" ", "")
        if not re.match(r"^(?:\+33|0)[1-9]\d{8}$", tel):
            erreurs.append(f"Ligne {ligne_num} : téléphone invalide ({tel})")

        mail = (email or "").strip().lower()
        if "@" not in mail or "." not in mail:
            erreurs.append(f"Ligne {ligne_num} : e-mail invalide ({mail})")

        if (mode or "").strip().lower() not in ("presentiel", "présentiel", "distanciel"):
            erreurs.append(f"Ligne {ligne_num} : mode invalide ({mode})")

        ligne_num += 1

    os.remove(temp_path)
    if erreurs:
        msg = f"❌ {len(erreurs)} erreur(s) détectée(s) :<br>" + "<br>".join(erreurs[:20])
        if len(erreurs) > 20:
            msg += f"<br>… et {len(erreurs) - 20} autres lignes à corriger."
        flash(msg, "error")
    else:
        flash("✅ Aucun problème détecté : le fichier est prêt à être importé.", "success")

    return redirect(url_for("parcoursup.dashboard"))

# =====================================================
# 🗑️ SUPPRIMER UN CANDIDAT
# =====================================================
@bp_parcoursup.route("/parcoursup/delete/<cid>", methods=["POST"])
def delete_candidat(cid):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM parcoursup_candidats WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    flash("Candidature supprimée avec succès.", "success")
    return redirect(url_for("parcoursup.dashboard"))

@bp_parcoursup.route("/parcoursup/check-sms", methods=["POST"])
def check_sms_status_all():
    # Vérifie la clé API Brevo
    BREVO_KEY = os.getenv("BREVO_API_KEY")
    if not BREVO_KEY:
        flash("BREVO_API_KEY manquant dans les variables d'environnement.", "error")
        return redirect(url_for("parcoursup.dashboard"))

    conn = db()
    cur = conn.cursor()

    # On ne vérifie que ceux pour lesquels on a (a priori) envoyé un SMS
    cur.execute("SELECT id, logs FROM parcoursup_candidats WHERE sms_ok=1")
    rows = cur.fetchall()

    headers = {"api-key": BREVO_KEY}
    delivered = failed = pending = 0

    def last_event(message_id: str):
        """Retourne l'événement le plus récent pour ce SMS Brevo (delivered/failed/...)."""
        try:
            url = f"https://api.brevo.com/v3/transactionalSMS/statistics/events?messageId={message_id}"
            r = requests.get(url, headers=headers, timeout=15)
            if not r.ok:
                return None
            data = r.json()
            events = data.get("events") or []
            if not events:
                return None
            return events[-1].get("event")  # delivered / failed / etc.
        except Exception as e:
            print("❌ check_sms_status error:", e)
            return None

    for r in rows:
        try:
            raw_logs = r["logs"] or "[]"
            try:
                logs = json.loads(raw_logs)
            except Exception:
                logs = []

            # Cherche l’entrée de type "sms" qui contient l’id Brevo
            sms_log = next((l for l in logs if l.get("type") == "sms" and l.get("id")), None)
            if not sms_log:
                continue

            evt = last_event(sms_log["id"])
            now = datetime.now().isoformat()

            if evt == "delivered":
                delivered += 1
                cur.execute(
                    "UPDATE parcoursup_candidats "
                    "SET sms_ok=1, logs=json_insert(logs, '$[#]', json_object('type','sms_status','event',?,'date',?)) "
                    "WHERE id=?",
                    (evt, now, r["id"])
                )
            elif evt == "failed":
                failed += 1
                cur.execute(
                    "UPDATE parcoursup_candidats "
                    "SET sms_ok=0, logs=json_insert(logs, '$[#]', json_object('type','sms_status','event',?,'date',?)) "
                    "WHERE id=?",
                    (evt, now, r["id"])
                )
            else:
                pending += 1
                cur.execute(
                    "UPDATE parcoursup_candidats "
                    "SET logs=json_insert(logs, '$[#]', json_object('type','sms_status','event',?,'date',?)) "
                    "WHERE id=?",
                    (evt or "unknown", now, r["id"])
                )

        except Exception as e:
            print("❌ boucle check_sms_status:", e)
        finally:
            # On évite de saturer l’API Brevo
            time.sleep(0.15)

    conn.commit()
    conn.close()

    flash(f"SMS livrés ✅ {delivered} — échoués ❌ {failed} — en attente ⏳ {pending}", "success")
    return redirect(url_for("parcoursup.dashboard"))





