import os, sqlite3, json, uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file, session, abort, jsonify, flash
from werkzeug.utils import secure_filename
from utils import send_mail, dossier_number, new_token, sign_token, make_signed_link
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")

# =====================================================
# 💾 CONFIGURATION DU STOCKAGE PERSISTANT (Render)
# =====================================================

# 📁 Dossier persistant (base de données et PDF)
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)

# 📦 Base SQLite stockée sur le disque Render
DB_PATH = os.path.join(DATA_DIR, "app.db")

# 📂 Dossier des fichiers uploadés
# ⚠️ Pour qu’ils soient persistants aussi, on les place dans /data/uploads
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # optional

STATUTS = [
    ("preinscription", "Pré-inscription à traiter", "gray"),
    ("validee", "Candidature validée", "blue"),
    ("confirmee", "Inscription confirmée", "gold"),
    ("reconf_en_cours", "Reconfirmation en cours", "orange"),
    ("reconfirmee", "Inscription re-confirmée", "green"),
    ("annulee", "Inscription annulée", "red"),
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_nir(nir: str) -> str:
    """Remplace 2A/2B et retire espaces."""
    if not nir:
        return ""
    nir = nir.strip().upper().replace(" ", "")
    nir = nir.replace("2A", "19").replace("2B", "18")
    return "".join(ch for ch in nir if ch.isdigit())

def validate_nir(nir_raw, date_naissance_str, sexe_str):
    """Valide le NIR (clé + cohérence date + sexe). Gère Corse & DOM-TOM."""
    digits = normalize_nir(nir_raw)
    if len(digits) != 15:
        return False, "Le numéro de sécurité sociale doit comporter 15 chiffres."

    # Vérif clé
    try:
        corps, cle = digits[:13], int(digits[13:15])
        calc = 97 - (int(corps) % 97)
        if calc != cle:
            return False, "Clé de contrôle du NIR incorrecte."
    except Exception:
        return False, "Format du NIR invalide."

    # Cohérence date
    if date_naissance_str:
        try:
            annee = int(date_naissance_str[:4])
            mois = int(date_naissance_str[5:7])
            yy_expected = str(annee)[-2:]
            mm_expected = f"{mois:02d}"
            yy, mm = digits[1:3], digits[3:5]

            if yy != yy_expected:
                return False, f"L'année ({yy}) ne correspond pas à la date ({yy_expected})."

            if mm.isdigit() and 1 <= int(mm) <= 12 and mm != mm_expected:
                return False, f"Le mois ({mm}) ne correspond pas au mois de naissance ({mm_expected})."
        except Exception:
            return False, "Date de naissance invalide."

    # Cohérence sexe
    s = int(digits[0])
    sexe_str = (sexe_str or "").lower()
    if (sexe_str.startswith("h") and s != 1) or (sexe_str.startswith("f") and s != 2):
        return False, "Le sexe indiqué ne correspond pas au NIR."

    return True, ""

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidats (
        id TEXT PRIMARY KEY,
        numero_dossier TEXT,
        created_at TEXT,
        updated_at TEXT,
        nom TEXT, prenom TEXT, sexe TEXT,
        date_naissance TEXT, ville_naissance TEXT, cp_naissance TEXT, pays_naissance TEXT,
        num_secu TEXT, email TEXT, tel TEXT,
        adresse TEXT, cp TEXT, ville TEXT,
        bts TEXT, mode TEXT,
        bac_status TEXT, bac_type TEXT, bac_autre TEXT,
        permis_b INTEGER,
        est_mineur INTEGER,
        resp_nom TEXT, resp_prenom TEXT, resp_email TEXT, resp_tel TEXT,
        mos_parcours TEXT,
        aps_souhaitee INTEGER, aps_session TEXT,
        projet_pourquoi TEXT, projet_objectif TEXT, projet_passions TEXT,
        fichiers_ci TEXT, fichiers_photo TEXT, fichiers_carte_vitale TEXT, fichiers_cv TEXT, fichiers_lm TEXT,
        statut TEXT,
        label_aps INTEGER, label_aut_ok INTEGER, label_cheque_ok INTEGER,
        token_confirm TEXT, token_confirm_exp TEXT,
        token_reconfirm TEXT, token_reconfirm_exp TEXT,
        commentaires TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        candidat_id TEXT,
        numero_dossier TEXT,
        type TEXT,
        payload TEXT,
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()

# Initialisation de la base de données au démarrage de l'application
with app.app_context():
    init_db()


def log_event(candidat, type_, payload_dict):
    conn = db()
    cur = conn.cursor()
    cid = candidat["id"] if isinstance(candidat, dict) else candidat
    nd = candidat.get("numero_dossier","") if isinstance(candidat, dict) else ""
    cur.execute("INSERT INTO logs (id, candidat_id, numero_dossier, type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), cid, nd, type_, json.dumps(payload_dict, ensure_ascii=False), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_counter_for_today(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candidats WHERE DATE(created_at) = DATE(?)", (datetime.now().isoformat(),))
    c = cur.fetchone()[0]
    return c + 1

def require_admin():
    if ADMIN_PASSWORD and not session.get("admin_ok"):
        return False
    return True

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        return redirect(url_for("admin"))
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == ADMIN_PASSWORD:
            session["admin_ok"] = True
            return redirect(url_for("admin"))
        flash("Mot de passe incorrect", "error")
    return render_template("admin_login.html", title="Admin – Connexion")

@app.route("/health")
def health():
    return "ok"

# ---------------- Public: Pré-inscriptions ----------------

@app.route("/")
def index():
    return render_template("index.html", title="Pré-inscriptions BTS 2026")

def save_files(field):
    files = request.files.getlist(field)
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        name = datetime.now().strftime("%Y%m%d%H%M%S_") + secure_filename(f.filename)
        path = os.path.join(UPLOAD_DIR, name)
        f.save(path)
        saved.append(path)
    return saved

@app.route("/submit", methods=["POST"])
def submit():
    form = request.form
    conn = db()
    cur = conn.cursor()
    counter = get_counter_for_today(conn)
    numero = dossier_number(counter=counter)

    # ici ton bloc NIR ↓
    nir = form.get("num_secu", "")
    date_naiss = form.get("date_naissance", "")
    sexe = form.get("sexe", "")
    ok, msg = validate_nir(nir, date_naiss, sexe)
    if not ok:
        flash(msg, "error")
        return redirect(request.referrer or url_for("index"))



    cand_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    def b(v): return 1 if v in ("on", "true", "1", "yes") else 0

    fichiers_ci = save_files("ci")
    fichiers_photo = save_files("photo")
    fichiers_carte_vitale = save_files("carte_vitale")
    fichiers_cv = save_files("cv")
    fichiers_lm = save_files("lm")

    token_confirm = new_token()
    token_confirm_exp = (datetime.now() + timedelta(days=30)).isoformat()

    cur.execute("""
    INSERT INTO candidats (
        id, numero_dossier, created_at, updated_at,
        nom, prenom, sexe,
        date_naissance, ville_naissance, cp_naissance, pays_naissance,
        num_secu, email, tel,
        adresse, cp, ville,
        bts, mode,
        bac_status, bac_type, bac_autre,
        permis_b, est_mineur, resp_nom, resp_prenom, resp_email, resp_tel,
        mos_parcours, aps_souhaitee, aps_session,
        projet_pourquoi, projet_objectif, projet_passions,
        fichiers_ci, fichiers_photo, fichiers_carte_vitale, fichiers_cv, fichiers_lm,
        statut, label_aps, label_aut_ok, label_cheque_ok,
        token_confirm, token_confirm_exp,
        token_reconfirm, token_reconfirm_exp,
        commentaires
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        cand_id, numero, now, now,
        form.get("nom", "").strip(), form.get("prenom", "").strip(), form.get("sexe", ""),
        form.get("date_naissance", ""), form.get("ville_naissance", ""), form.get("cp_naissance", ""), form.get("pays_naissance", ""),
        form.get("num_secu", ""), form.get("email", ""), form.get("tel", ""),
        form.get("adresse", ""), form.get("cp", ""), form.get("ville", ""),
        form.get("bts", ""), form.get("mode", ""),
        form.get("bac_status", ""), form.get("bac_type", ""), form.get("bac_autre", ""),
        b(form.get("permis_b")), b(form.get("est_mineur")),
        form.get("resp_nom", ""), form.get("resp_prenom", ""), form.get("resp_email", ""), form.get("resp_tel", ""),
        form.get("mos_parcours", ""), b(form.get("aps_souhaitee")), form.get("aps_session", ""),
        form.get("projet_pourquoi", ""), form.get("projet_objectif", ""), form.get("projet_passions", ""),
        json.dumps(fichiers_ci), json.dumps(fichiers_photo),
        json.dumps(fichiers_carte_vitale), json.dumps(fichiers_cv), json.dumps(fichiers_lm),
        "preinscription", 1 if form.get("aps_souhaitee") else 0, 0, 0,
        token_confirm, token_confirm_exp,
        "", "",   # 🧩 colonnes manquantes ajoutées : token_reconfirm, token_reconfirm_exp
        ""        # commentaires
    ))
    conn.commit()

    # --- Logs et mails
    candidat = {
        "id": cand_id,
        "numero_dossier": numero,
        "email": form.get("email", ""),
        "prenom": form.get("prenom", "")
    }
    log_event(candidat, "PREINSCRIPTION_RECU", {"email": candidat["email"]})

    html = render_template("mail_accuse.html", prenom=form.get("prenom", ""), numero=numero)
    send_mail(form.get("email", ""), "Nous avons bien reçu votre pré-inscription", html)
    log_event(candidat, "MAIL_ENVOYE", {"type": "accuse_reception"})

    admin_html = render_template("mail_admin_notif.html", numero=numero, nom=form.get("nom", ""), prenom=form.get("prenom", ""))
    from_addr = os.getenv("MAIL_FROM", "ecole@integraleacademy.com")
    send_mail(from_addr, f"[ADMIN] Nouvelle pré-inscription {numero}", admin_html)

    return render_template("submit_ok.html", title="Merci", numero=numero)

# ---------------- Admin ----------------

@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))
    q = request.args.get("q","").strip().lower()
    flt_bts = request.args.get("bts","")
    flt_statut = request.args.get("statut","")
    flt_mode = request.args.get("mode","")
    flt_label = request.args.get("label","")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]

    def match(row):
        ok = True
        if q:
            blob = " ".join([str(row.get(k,'')) for k in ("nom","prenom","email","tel","bts","numero_dossier")]).lower()
            ok &= q in blob
        if flt_bts:
            ok &= row.get("bts","") == flt_bts
        if flt_statut:
            ok &= row.get("statut","") == flt_statut
        if flt_mode:
            ok &= row.get("mode","") == flt_mode
        if flt_label == "APS":
            ok &= row.get("label_aps",0) == 1
        if flt_label == "AUT":
            ok &= row.get("label_aut_ok",0) == 1
        if flt_label == "CHEQUE":
            ok &= row.get("label_cheque_ok",0) == 1
        return ok

    rows = [r for r in rows if match(r)]
    return render_template("admin.html", title="Administration", rows=rows, statuts=STATUTS)

@app.route("/admin/update-field", methods=["POST"])
def admin_update_field():
    if not require_admin(): abort(403)
    data = request.json or {}
    cid = data.get("id")
    field = data.get("field")
    value = data.get("value")
    allowed = {"nom","prenom","bts","mode","tel","email","label_aps","label_aut_ok","label_cheque_ok","commentaires"}
    if field not in allowed: return jsonify({"ok":False,"error":"field not allowed"}), 400
    conn = db(); cur = conn.cursor()
    cur.execute(f"UPDATE candidats SET {field}=?, updated_at=? WHERE id=?", (value, datetime.now().isoformat(), cid))
    conn.commit()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())
    log_event(row, "FIELD_UPDATE", {"field": field, "value": value})
    return jsonify({"ok":True})

@app.route("/admin/update-status", methods=["POST"])
def admin_update_status():
    if not require_admin(): abort(403)
    data = request.json or {}
    cid = data.get("id")
    value = data.get("value")
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE candidats SET statut=?, updated_at=? WHERE id=?", (value, datetime.now().isoformat(), cid))
    conn.commit()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())

    if value == "validee":
        token = row.get("token_confirm") or ""
        link = make_signed_link("/confirm-inscription", token)
        html = render_template("mail_validation.html", prenom=row.get("prenom",""), bts=row.get("bts",""), link=link, numero=row.get("numero_dossier",""))
        send_mail(row.get("email",""), "Votre candidature est validée – Confirmez votre inscription", html)
        log_event(row, "MAIL_ENVOYE", {"type":"validation_inscription"})
    log_event(row, "STATUT_CHANGE", {"statut": value})
    return jsonify({"ok":True})

@app.route("/admin/reconfirm/<cid>", methods=["POST"])
def admin_reconfirm(cid):
    if not require_admin(): abort(403)
    conn = db(); cur = conn.cursor()
    token = new_token()
    exp = (datetime.now() + timedelta(days=30)).isoformat()
    cur.execute("UPDATE candidats SET token_reconfirm=?, token_reconfirm_exp=?, statut=?, updated_at=? WHERE id=?",
                (token, exp, "reconf_en_cours", datetime.now().isoformat(), cid))
    conn.commit()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())
    link = make_signed_link("/reconfirm", token)
    html = render_template("mail_reconfirm.html", prenom=row.get("prenom",""), link=link)
    send_mail(row.get("email",""), "Confirmez votre inscription – Rentrée septembre", html)
    log_event(row, "MAIL_ENVOYE", {"type":"reconfirmation"})
    log_event(row, "STATUT_CHANGE", {"statut": "reconf_en_cours"})
    return jsonify({"ok":True})

@app.route("/admin/print/<cid>")
def admin_print(cid):
    if not require_admin(): abort(403)
    from weasyprint import HTML
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())
    html = render_template("pdf_fiche.html", row=row, now=datetime.now())
    pdf = HTML(string=html, base_url=url_for('index', _external=True)).write_pdf()
    fname = f"fiche_{row.get('numero_dossier','')}.pdf"
    path = os.path.join(DATA_DIR, fname)
    with open(path, "wb") as f:
        f.write(pdf)
    log_event(row, "PDF_GENERE", {"file": fname})
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=fname)

@app.route("/admin/delete/<cid>", methods=["POST"])
def admin_delete(cid):
    if not require_admin(): abort(403)
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = cur.fetchone()
    if row:
        row = dict(row)
        cur.execute("DELETE FROM candidats WHERE id=?", (cid,))
        conn.commit()
        log_event(row, "FICHE_SUPPRIMEE", {})
    return jsonify({"ok":True})

@app.route("/admin/export.csv")
def admin_export_csv():
    if not require_admin(): abort(403)
    import csv, io
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return buf.getvalue(), 200, {"Content-Type":"text/csv; charset=utf-8", "Content-Disposition":"attachment; filename=export.csv"}

@app.route("/admin/export.json")
def admin_export_json():
    if not require_admin(): abort(403)
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    return jsonify(rows)

@app.route("/admin/logs")
def admin_logs():
    if not require_admin(): abort(403)
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT 1000")
    rows = [dict(r) for r in cur.fetchall()]
    return render_template("logs.html", title="Logs", rows=rows)

# ---------------- Confirmation ----------------

def verify_token(query_token, query_sig):
    if not query_token or not query_sig: return False
    return sign_token(query_token) == query_sig

@app.route("/confirm-inscription", methods=["GET","POST"])
def confirm_inscription():
    if request.method == "GET":
        token = request.args.get("token",""); sig = request.args.get("sig","")
        if not verify_token(token, sig): abort(403)
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT * FROM candidats WHERE token_confirm=?", (token,))
        row = cur.fetchone()
        if not row: abort(404)
        return render_template("confirm_inscription.html", title="Confirmer mon inscription", row=dict(row), token=token, sig=sig)

    token = request.form.get("token",""); sig = request.form.get("sig","")
    if not verify_token(token, sig): abort(403)
    c1 = request.form.get("c1") == "on"
    c2 = request.form.get("c2") == "on"
    c3 = request.form.get("c3") == "on"
    if not (c1 and c2 and c3):
        flash("Merci de cocher les 3 cases obligatoires.", "error")
        return redirect(request.referrer or url_for("index"))

    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE token_confirm=?", (token,))
    row = dict(cur.fetchone())
    cur.execute("UPDATE candidats SET statut=?, updated_at=? WHERE id=?", ("confirmee", datetime.now().isoformat(), row["id"]))
    conn.commit()

    html = render_template("mail_confirmee.html", prenom=row.get("prenom",""), aps=bool(row.get("label_aps",0)))
    send_mail(row.get("email",""), "Inscription confirmée – Intégrale Academy", html)
    merci_html = render_template("mail_bienvenue.html", prenom=row.get("prenom",""), bts=row.get("bts",""))
    send_mail(row.get("email",""), "Bienvenue à Intégrale Academy 🎓", merci_html)
    log_event(row, "MAIL_ENVOYE", {"type":"bienvenue"})
    log_event(row, "MAIL_ENVOYE", {"type":"inscription_confirmee"})
    log_event(row, "STATUT_CHANGE", {"statut": "confirmee"})
    return render_template("confirm_ok.html", title="Inscription confirmée")

@app.route("/reconfirm")
def reconfirm():
    token = request.args.get("token",""); sig = request.args.get("sig","")
    if not verify_token(token, sig): abort(403)
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE token_reconfirm=?", (token,))
    row = cur.fetchone()
    if not row: abort(404)
    row = dict(row)
    cur.execute("UPDATE candidats SET statut=?, updated_at=? WHERE id=?", ("reconfirmee", datetime.now().isoformat(), row["id"]))
    conn.commit()
    log_event(row, "STATUT_CHANGE", {"statut": "reconfirmee"})
    return render_template("reconfirm_ok.html", title="Merci ❤️")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
