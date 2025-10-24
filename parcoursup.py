# parcoursup.py
import os, uuid, sqlite3, json, re
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo
from openpyxl import load_workbook

# =====================================================
# 🎨 Styles des statuts
# =====================================================
STATUTS_STYLE = {
    "preinscription": {"label": "Pré-inscription à traiter", "color": "#808080"},  # gris
    "validee": {"label": "Candidature validée", "color": "#3498db"},               # bleu
    "confirmee": {"label": "Inscription confirmée", "color": "#f4c45a"},           # doré
    "reconf_en_cours": {"label": "Reconfirmation en cours", "color": "#ff9800"},   # orange
    "reconfirmee": {"label": "Inscription re-confirmée", "color": "#2ecc71"},      # vert
    "annulee": {"label": "Inscription annulée", "color": "#e74c3c"},               # rouge
    "docs_non_conformes": {"label": "Documents non conformes", "color": "#000000"} # noir
}

# =====================================================
# 🔧 Blueprint & connexion DB
# =====================================================
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
        sms_message_id TEXT DEFAULT '',      -- ✅ ajouté
        statut TEXT DEFAULT 'En attente de candidature',
        logs TEXT DEFAULT '[]',
        created_at TEXT
    );
    """)
    # Index pour éviter les doublons coûteux
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_email ON parcoursup_candidats(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_tel   ON parcoursup_candidats(telephone)")
    conn.commit()
    conn.close()

# =====================================================
# 🧩 Vérifie et ajoute les colonnes manquantes si besoin
# =====================================================
def ensure_parcoursup_schema():
    conn = db()
    cur = conn.cursor()
    table = "parcoursup_candidats"
    cur.execute(f"PRAGMA table_info({table})")
    existing = {r[1] for r in cur.fetchall()}

    to_add = []
    if "mail_ok" not in existing:
        to_add.append(("mail_ok", "INTEGER", 0))
    if "sms_ok" not in existing:
        to_add.append(("sms_ok", "INTEGER", 0))
    if "sms_message_id" not in existing:
        to_add.append(("sms_message_id", "TEXT", ""))
    if "logs" not in existing:
        to_add.append(("logs", "TEXT", "[]"))

    for col, typ, default in to_add:
        if typ == "TEXT":
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ} DEFAULT {json.dumps(default)}")
        else:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ} DEFAULT {default}")

    conn.commit()
    conn.close()

# Appelé automatiquement quand le blueprint est enregistré
@bp_parcoursup.record_once
def _setup(state):
    init_parcoursup_table()
    ensure_parcoursup_schema()

# =====================================================
# 🏠 PAGE PRINCIPALE
# =====================================================
@bp_parcoursup.route("/parcoursup")
def dashboard():
    conn = db()
    cur = conn.cursor()

    # 🔄 Synchronisation avec la table "candidats" (Admin)
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

    # 🔍 Filtrage optionnel
    selected_status = request.args.get("statut")
    if selected_status:
        cur.execute("SELECT * FROM parcoursup_candidats WHERE statut=? ORDER BY created_at DESC", (selected_status,))
    else:
        cur.execute("SELECT * FROM parcoursup_candidats ORDER BY created_at DESC")

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return render_template("parcoursup.html",
                           title="Gestion Parcoursup",
                           rows=rows,
                           STATUTS_STYLE=STATUTS_STYLE)

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
            email = (email or "").strip().lower()
            telephone = str(telephone or "").strip().replace(" ", "")
            if telephone.startswith("0"):
                telephone = "+33" + telephone[1:]
            nom, prenom = (nom or "").upper(), (prenom or "").title()

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
                cur.execute("UPDATE parcoursup_candidats SET mail_ok=1 WHERE id=?", (cid,))
                mails_sent += 1

            # === Envoi du SMS ===
            sms_msg = f"Bonjour {prenom}, nous avons bien reçu votre candidature Parcoursup pour le BTS {formation}. Pour finaliser : inscriptionsbts.onrender.com"
            try:
                message_id = send_sms_brevo(telephone, sms_msg)
                cur.execute("UPDATE parcoursup_candidats SET sms_ok=1, sms_message_id=? WHERE id=?", (message_id, cid))
                sms_sent += 1
            except Exception as e:
                print("❌ Erreur SMS :", e)

            conn.commit()

        except Exception as e:
            print("❌ Erreur ligne :", e)
            errors += 1

    conn.close()
    os.remove(temp_path)
    flash(f"{imported} candidatures importées — {mails_sent} mails envoyés — {sms_sent} SMS envoyés — {duplicates} doublons ignorés — {errors} erreurs.", "success")
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
        flash("Format non supporté. Utilisez un fichier .xlsx", "error")
        return redirect(url_for("parcoursup.dashboard"))

    temp_path = os.path.join(DATA_DIR, secure_filename(file.filename))
    file.save(temp_path)
    wb = load_workbook(temp_path)
    ws = wb.active

    erreurs, ligne = [], 2
    for row in ws.iter_rows(min_row=2, values_only=True):
        nom, prenom, tel, email, formation, mode = row[:6]
        if not nom: erreurs.append(f"Ligne {ligne} : nom manquant")
        if not prenom: erreurs.append(f"Ligne {ligne} : prénom manquant")
        if not re.match(r"^(?:\+33|0)[1-9]\d{8}$", str(tel or "")): erreurs.append(f"Ligne {ligne} : téléphone invalide ({tel})")
        if "@" not in str(email or ""): erreurs.append(f"Ligne {ligne} : e-mail invalide ({email})")
        ligne += 1

    os.remove(temp_path)
    if erreurs:
        msg = f"❌ {len(erreurs)} erreur(s) détectée(s):<br>" + "<br>".join(erreurs[:20])
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
