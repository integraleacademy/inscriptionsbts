import os, uuid, sqlite3, json, re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo
from openpyxl import load_workbook

bp_parcoursup = Blueprint("parcoursup", __name__, template_folder="templates")

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "app.db")

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

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
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()

@bp_parcoursup.record_once
def _setup(state):
    init_parcoursup_table()

# =====================================================
# 🏠 PAGE PRINCIPALE
# =====================================================
@bp_parcoursup.route("/parcoursup")
def dashboard():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM parcoursup_candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template("parcoursup.html", rows=rows, title="Gestion Parcoursup")

# =====================================================
# 📤 IMPORTER UN FICHIER EXCEL (.xlsx)
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

    conn = db()
    cur = conn.cursor()

    imported = mails_sent = sms_sent = duplicates = errors = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
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
                INSERT INTO parcoursup_candidats (id, nom, prenom, telephone, email, formation, mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, nom, prenom, telephone, email, formation, mode, now))
            conn.commit()
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

            # === Envoi du SMS ===
            sms_msg = f"Bonjour {prenom}, nous avons bien reçu votre candidature Parcoursup pour le BTS {formation}. Pour finaliser : inscriptionsbts.onrender.com"
            sms_id = send_sms_brevo(telephone, sms_msg)
            if sms_id:
                sms_sent += 1
                cur.execute("UPDATE parcoursup_candidats SET sms_ok=1 WHERE id=?", (cid,))

            conn.commit()

        except Exception as e:
            print("❌ Erreur ligne :", e)
            errors += 1

    conn.close()
    os.remove(temp_path)
    flash(f"{imported} importées — {mails_sent} mails — {sms_sent} SMS — {duplicates} doublons — {errors} erreurs.", "success")
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
    flash("Candidature supprimée.", "success")
    return redirect(url_for("parcoursup.dashboard"))
