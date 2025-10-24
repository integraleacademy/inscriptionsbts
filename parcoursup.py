# parcoursup.py
import os, uuid, sqlite3, json
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

# Initialisation table Parcoursup
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

# Page principale
@bp_parcoursup.route("/parcoursup")
def dashboard():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM parcoursup_candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return render_template("parcoursup.html", title="Gestion Parcoursup", rows=rows)
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
        flash("Format de fichier non supporté. Utilisez un fichier .xlsx", "error")
        return redirect(url_for("parcoursup.dashboard"))

    # Sauvegarde temporaire
    temp_path = os.path.join(DATA_DIR, secure_filename(file.filename))
    file.save(temp_path)

    wb = load_workbook(temp_path)
    ws = wb.active

    conn = db()
    cur = conn.cursor()

    imported = 0
    mails_sent = 0
    sms_sent = 0
    duplicates = 0
    errors = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        try:
            nom, prenom, telephone, email, formation, mode = row[:6]

            # Normalisation basique
            email = (email or "").strip().lower()
            telephone = (str(telephone or "")).strip()
            nom = (nom or "").strip().upper()
            prenom = (prenom or "").strip().title()

            # Vérif doublon (email ou téléphone)
            cur.execute("SELECT id FROM parcoursup_candidats WHERE email=? OR telephone=?", (email, telephone))
            if cur.fetchone():
                duplicates += 1
                continue

            cid = str(uuid.uuid4())
            now = datetime.now().isoformat()

            # Insère la ligne
            cur.execute("""
                INSERT INTO parcoursup_candidats 
                (id, nom, prenom, telephone, email, formation, mode, mail_ok, sms_ok, statut, logs, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'En attente de candidature', '[]', ?)
            """, (cid, nom, prenom, telephone, email, formation, mode, now))
            conn.commit()
            imported += 1

            # --- Mail ---
            html = f"""
            <p>Bonjour {prenom},</p>
            <p>Nous avons bien reçu votre candidature Parcoursup pour le BTS <b>{formation}</b>.</p>
            <p>Si vous souhaitez intégrer notre école, merci de compléter votre pré-inscription ici :</p>
            <p><a href='https://inscriptionsbts.onrender.com/'><b>👉 Formulaire de pré-inscription</b></a></p>
            <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
            if send_mail(email, "Votre candidature Parcoursup – Intégrale Academy", html):
                cur.execute("UPDATE parcoursup_candidats SET mail_ok=1 WHERE id=?", (cid,))
                mails_sent += 1

            # --- SMS ---
            message_sms = f"Bonjour {prenom}, nous avons bien reçu votre candidature Parcoursup pour le BTS {formation}. Pour finaliser : inscriptionsbts.onrender.com"
            try:
                send_sms_brevo(telephone, message_sms)
                cur.execute("UPDATE parcoursup_candidats SET sms_ok=1 WHERE id=?", (cid,))
                sms_sent += 1
            except Exception as e:
                print("❌ Erreur SMS :", e)

            conn.commit()

        except Exception as e:
            print("❌ Erreur ligne :", e)
            errors += 1

    conn.close()
    os.remove(temp_path)

    # Message de récapitulatif
    recap = f"{imported} candidatures importées, {mails_sent} mails envoyés, {sms_sent} SMS envoyés, {duplicates} doublons ignorés, {errors} erreurs."
    flash(recap, "success")

    return redirect(url_for("parcoursup.dashboard"))



