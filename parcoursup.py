# parcoursup.py
import os, uuid, sqlite3, json, re
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo
from openpyxl import load_workbook

STATUTS_STYLE = {
    "preinscription": {"label": "Pré-inscription à traiter", "color": "#f0ad4e"},   # orange
    "validee": {"label": "Candidature validée", "color": "#0275d8"},               # bleu
    "confirmee": {"label": "Inscription confirmée", "color": "#5cb85c"},           # vert
    "reconf_en_cours": {"label": "Reconfirmation en cours", "color": "#f0ad4e"},   # orange clair
    "reconfirmee": {"label": "Inscription re-confirmée", "color": "#5cb85c"},      # vert
    "annulee": {"label": "Inscription annulée", "color": "#d9534f"},               # rouge
    "docs_non_conformes": {"label": "Documents non conformes", "color": "#292b2c"} # noir/gris
}

# Blueprint Parcoursup
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
        # 🔄 Synchronisation avec la table ADMIN (candidats)
        cur.execute("SELECT id, email, telephone FROM parcoursup_candidats")
        parcoursup_rows = cur.fetchall()

        for r in parcoursup_rows:
            email = (r["email"] or "").strip().lower()
            tel = (r["telephone"] or "").replace(" ", "").replace("+33", "0").strip()

            # ✅ compare avec la table "candidats" (colonne tel)
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

    # 🔍 Filtrage optionnel par statut
    selected_status = request.args.get("statut")
    if selected_status:
        cur.execute(
            "SELECT * FROM parcoursup_candidats WHERE statut=? ORDER BY created_at DESC",
            (selected_status,)
        )
    else:
        cur.execute("SELECT * FROM parcoursup_candidats ORDER BY created_at DESC")

    # ✅ ICI on garde bien l’indentation à l’intérieur de la fonction
    rows = [dict(r) for r in cur.fetchall()]

    # 🔧 Harmonisation des statuts pour correspondre aux clés de STATUTS_STYLE
    for r in rows:
        s = (r["statut"] or "").strip().lower()
        if "pré" in s or "preinscription" in s:
            r["statut"] = "preinscription"
        elif "validée" in s and "candidature" in s:
            r["statut"] = "candidature_validee"
        elif "confirmée" in s:
            r["statut"] = "inscription_confirmee"
        elif "reconfirmation" in s and "attente" in s:
            r["statut"] = "reconfirmation_en_attente"
        elif "reconfirmation" in s and "validée" in s:
            r["statut"] = "reconfirmation_validee"
        elif "non conforme" in s:
            r["statut"] = "docs_non_conformes"
        elif "incomplet" in s:
            r["statut"] = "incomplet"
        elif "traité" in s:
            r["statut"] = "traite"

    conn.close()

    return render_template(
        "parcoursup.html",
        title="Gestion Parcoursup",
        rows=rows,
        STATUTS_STYLE=STATUTS_STYLE
    )



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
            telephone = (str(telephone or "")).strip().replace(" ", "")
            if telephone.startswith("0"):
                telephone = "+33" + telephone[1:]

            nom = (nom or "").strip().upper()
            prenom = (prenom or "").strip().title()

            # Vérif doublon
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

    recap = f"{imported} candidatures importées, {mails_sent} mails envoyés, {sms_sent} SMS envoyés, {duplicates} doublons ignorés, {errors} erreurs."
    flash(recap, "success")

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

        # Vérif nom
        if not nom:
            erreurs.append(f"Ligne {ligne_num} : nom manquant")

        # Vérif prénom
        if not prenom:
            erreurs.append(f"Ligne {ligne_num} : prénom manquant")

        # Vérif téléphone
        tel = str(telephone or "").strip().replace(" ", "")
        if not re.match(r"^(?:\+33|0)[1-9]\d{8}$", tel):
            erreurs.append(f"Ligne {ligne_num} : téléphone invalide ({tel})")

        # Vérif e-mail
        mail = (email or "").strip().lower()
        if "@" not in mail or "." not in mail:
            erreurs.append(f"Ligne {ligne_num} : e-mail invalide ({mail})")

        # Vérif mode
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




