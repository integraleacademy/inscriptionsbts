import os, sqlite3, json, uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file, session, abort, jsonify, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo, dossier_number, new_token, sign_token, make_signed_link
from dotenv import load_dotenv
from parcoursup import bp_parcoursup
from sms_templates import sms_text
from mail_templates import mail_html

# ============================
# 🔒 STARTUP INTEGRITY CHECK – STRICT (Parcoursup inclus)
# ============================
import os, re, sys, json, glob

def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None

def run_startup_integrity_checks():
    print("\n================= 🔎 INTÉGRITÉ PROJET – DÉMARRAGE STRICT =================")
    if os.getenv("INTEGRITY_CHECK", "1") == "0":
        print("⚠️  INTEGRITY_CHECK=0 → contrôle désactivé (non recommandé en prod).")
        return

    # --- 1) FICHIERS CRITIQUES À PRÉSENCE OBLIGATOIRE ---
    DATA_DIR = os.getenv("DATA_DIR", "/data")
    required_files = [
        # Python
        "app.py",
        "parcoursup.py",
        "mail_templates.py",
        "sms_templates.py",
        # Templates & statiques
        "templates/index.html",
        "templates/admin.html",
        "templates/parcoursup.html",
        "templates/email_base.html",
        "static/js/main_front.js",
        "static/js/main_admin.js",
        "static/css/styles.css",
        "static/logo-integrale.png",
    ]
    missing = [p for p in required_files if not os.path.exists(p)]
    if not os.path.exists(DATA_DIR):
        missing.append(DATA_DIR + "/ (répertoire)")
    if missing:
        print("❌ Fichiers/répertoires manquants :")
        for m in missing: print("   •", m)
        sys.exit(1)
    print("✅ Fichiers critiques présents.")

    # --- 2) ENV REQUISES ---
    env_required = {
        "BREVO_API_KEY": os.getenv("BREVO_API_KEY"),
        "SENDER_EMAIL": os.getenv("SENDER_EMAIL", "ecole@integraleacademy.com"),
        "BASE_URL": os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com"),
    }
    if not env_required["BREVO_API_KEY"]:
        print("❌ BREVO_API_KEY manquant (requis pour mails/SMS).")
        sys.exit(1)
    print(f"✅ Env OK (SENDER_EMAIL={env_required['SENDER_EMAIL']}, BASE_URL={env_required['BASE_URL']})")

    # --- 3) ROUTES FLASK DÉFINIES (tous .py) ---
    py_sources = {}
    for p in ["app.py", "parcoursup.py", "mail_templates.py", "sms_templates.py"]:
        py_sources[p] = _read(p)

    route_regex = re.compile(r"""@(?:app|bp_[a-zA-Z0-9_]+)\.route\(\s*['"]([^'"]+)['"]""")
    defined_routes = set()
    for name, src in py_sources.items():
        if not src: continue
        for r in route_regex.findall(src):
            # Normalise: on retire la partie paramétrée (ex: /admin/delete/<id> -> /admin/delete/)
            r_norm = re.sub(r"<[^>]+>", "", r)
            if not r_norm.endswith("/") and "/" in r and "<" in r:
                r_norm += "/"  # facilite les comparaisons par préfixe
            defined_routes.add(r_norm)

    # --- 4) ROUTES PARCOURSUP INDISPENSABLES ---
    required_parcoursup = [
        "/parcoursup",
        "/parcoursup/import",
        "/parcoursup/check",
        "/parcoursup/delete/",      # avec <cid>
        "/parcoursup/check-sms",
        "/parcoursup/logs/",        # avec <cid>
        "/brevo-sms-webhook",
        "/brevo-mail-webhook",
    ]
    missing_routes = []
    for need in required_parcoursup:
        ok = any(
            need == r or need.startswith(r) or r.startswith(need)
            for r in defined_routes
        )
        if not ok: missing_routes.append(need)
    if missing_routes:
        print("❌ Routes Parcoursup manquantes côté Flask :")
        for r in missing_routes: print("   •", r)
        sys.exit(1)
    print("✅ Routes Parcoursup détectées.")

    # --- 5) FETCH() DANS JS DOIVENT EXISTER EN ROUTES PYTHON ---
    js_fetch_targets = set()
    fetch_regex = re.compile(r"""fetch\(\s*['"](/[^'"]+)['"]""")
    for js_path in ["static/js/main_front.js", "static/js/main_admin.js"]:
        js = _read(js_path) or ""
        for u in fetch_regex.findall(js):
            # on ignore les querystrings et paramètres dynamiques
            u_clean = u.split("?")[0]
            js_fetch_targets.add(u_clean)

    # Construire une version "prefix-friendly" des routes
    def _matches_defined(u):
        # exemple: /admin/delete/123 doit matcher /admin/delete/
        for r in defined_routes:
            if u == r:
                return True
            # si la route définie est paramétrée, on a ajouté un trailing "/" plus haut
            if r.endswith("/") and u.startswith(r):
                return True
        return False

    bad = [u for u in js_fetch_targets if not _matches_defined(u)]
    if bad:
        print("❌ Des endpoints sont appelés en JS mais non définis en Python :")
        for b in sorted(bad): print("   •", b)
        sys.exit(1)
    print(f"✅ {len(js_fetch_targets)} endpoints JS → tous présents côté Flask.")

    # --- 6) TEMPLATE MAIL DE BASE DOIT AVOIR LES PLACEHOLDERS ---
    base_mail = _read("templates/email_base.html") or ""
    if ("{{ email_title }}" not in base_mail) or ("{{ email_content }}" not in base_mail):
        print("❌ templates/email_base.html doit contenir {{ email_title }} et {{ email_content }}.")
        sys.exit(1)
    if "logo_url" not in base_mail:
        print("⚠️  (recommandé) Utiliser {{ logo_url }} dans email_base.html pour l’image.")
    print("✅ email_base.html OK.")

    print("🎉 INTÉGRITÉ OK – Démarrage de l’application.\n")

# 👉 Appelle le contrôle immédiatement au démarrage :

# 🩵 Signal de vie immédiat pour Render
print("🚀 Lancement Flask en cours… (Render healthcheck OK)")
import sys; sys.stdout.flush()

run_startup_integrity_checks()
# ============================ FIN AUTO-CHECK ============================



load_dotenv()

# =====================================================
# 📎 GESTION DES PIÈCES JUSTIFICATIVES
# =====================================================

DOC_FIELDS = {
    "ci": ("fichiers_ci", "🪪 Carte d’identité / Passeport"),
    "photo": ("fichiers_photo", "📸 Photo d’identité"),
    "carte_vitale": ("fichiers_carte_vitale", "💳 Carte Vitale"),
    "cv": ("fichiers_cv", "📄 CV"),
    "lm": ("fichiers_lm", "🖋️ Lettre de motivation"),
}
# 📦 Préfixes utilisés pour nommer les fichiers de manière déterministe
FILE_PREFIX = {
    "ci": "CI",
    "photo": "Photo",
    "carte_vitale": "CarteVitale",
    "cv": "CV",
    "lm": "LettreMotivation",
}



def get_candidat(conn, cid):
    """Récupère un candidat complet par ID."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = cur.fetchone()
    return dict(row) if row else None

def parse_list(v):
    """Convertit le JSON stocké des fichiers en vraie liste Python."""
    try:
        data = json.loads(v or "[]")
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

def load_verif_docs(row):
    """Récupère le dictionnaire de vérification des pièces (conforme / non conforme)."""
    try:
        return json.loads(row.get("verif_docs") or "{}")
    except Exception:
        return {}


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.register_blueprint(bp_parcoursup)

# --- Filtres d'affichage pour le PDF / pages ---
def _fmt_date_dmy(s: str) -> str:
    if not s:
        return ""
    try:
        if "T" in s or ":" in s:
            dt = datetime.fromisoformat(s.replace("Z",""))
            return dt.strftime("%d/%m/%Y")
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return s

def _nir_spaced(nir: str) -> str:
    """Affiche le NIR en groupes avec espaces sans retirer A/B (ex: 1 93 09 74 256 233 79)."""
    if not nir:
        return ""
    raw = nir.strip().upper().replace(" ", "")
    groups, cuts, i = [], [1,2,2,2,3,3,2], 0  # 1|2|2|2|3|3|2 = 15
    for c in cuts:
        groups.append(raw[i:i+c])
        i += c
        if i >= len(raw):
            break
    return " ".join([g for g in groups if g])

def _bts_full(code: str) -> str:
    code = (code or "").strip().upper()
    return BTS_LABELS.get(code, code)

def _mode_emoji(mode: str) -> str:
    m = (mode or "").lower()
    return ("🏫 Présentiel" if "pres" in m else "💻 Distanciel")

# rendre dispo dans Jinja
app.jinja_env.filters["dmy"] = _fmt_date_dmy
app.jinja_env.filters["nirsp"] = _nir_spaced
app.jinja_env.filters["btsfull"] = _bts_full
app.jinja_env.filters["modeemo"] = _mode_emoji

# petit helper pour décoder du JSON côté template
import json as _json_for_filter
app.jinja_env.filters["load_json"] = lambda s: _json_for_filter.loads(s or "[]")


@app.template_filter('basename')
def basename_filter(path):
    """Retourne juste le nom du fichier sans le chemin complet"""
    return os.path.basename(path or "")

# --- Filtres d'affichage pour le PDF / pages ---
def _fmt_date_dmy(s: str) -> str:
    if not s:
        return ""
    try:
        # accepte 'YYYY-MM-DD' ou ISO
        if "T" in s or ":" in s:
            dt = datetime.fromisoformat(s.replace("Z",""))
            return dt.strftime("%d/%m/%Y")
        # input date HTML (YYYY-MM-DD)
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return s

def _nir_spaced(nir: str) -> str:
    """Affiche le NIR en groupes avec espaces sans retirer A/B (ex: 1 93 09 74 256 233 79)."""
    if not nir:
        return ""
    raw = nir.strip().upper().replace(" ", "")
    groups = []
    cuts = [1,2,2,2,3,3,2]  # 1 | 2 | 2 | 2 | 3 | 3 | 2
    i = 0
    for c in cuts:
        groups.append(raw[i:i+c])
        i += c
        if i >= len(raw):
            break
    return " ".join([g for g in groups if g])

def _bts_full(code: str) -> str:
    code = (code or "").strip().upper()
    return BTS_LABELS.get(code, code)

def _mode_emoji(mode: str) -> str:
    m = (mode or "").lower()
    return ("🏫 Présentiel" if "pres" in m else "💻 Distanciel")

app.jinja_env.filters["dmy"] = _fmt_date_dmy
app.jinja_env.filters["nirsp"] = _nir_spaced
app.jinja_env.filters["btsfull"] = _bts_full
app.jinja_env.filters["modeemo"] = _mode_emoji



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
    ("docs_non_conformes", "Docs non conformes", "black"),
]

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_nir(nir: str) -> str:
    """Nettoie le NIR sans modifier sa structure (garde 2A/2B pour l'affichage)."""
    if not nir:
        return ""
    return nir.strip().upper().replace(" ", "")

def validate_nir(nir_raw, date_naissance_str, sexe_str):
    """Valide le NIR (clé + cohérence date + sexe). 
    Conserve 2A/2B dans la valeur stockée, mais effectue la vérification avec conversion temporaire."""
    if not nir_raw:
        return False, "Numéro de sécurité sociale manquant."

    nir_clean = normalize_nir(nir_raw)

    # 🔁 copie temporaire pour le calcul (convertit juste pour la vérif)
    nir_calc = nir_clean.replace("2A", "19").replace("2B", "18")
    digits = "".join(ch for ch in nir_calc if ch.isdigit())

    if len(digits) != 15:
        return False, "Le numéro de sécurité sociale doit comporter 15 caractères (chiffres ou A/B)."

    # ✅ Vérification de la clé de contrôle
    try:
        corps, cle = digits[:13], int(digits[13:15])
        calc = 97 - (int(corps) % 97)
        if calc != cle:
            return False, "Clé de contrôle du NIR incorrecte."
    except Exception:
        return False, "Format du NIR invalide."

    # ✅ Cohérence date
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

    # ✅ Cohérence sexe
    try:
        s = int(digits[0])
        sexe_str = (sexe_str or "").lower()
        if (sexe_str.startswith("h") and s != 1) or (sexe_str.startswith("f") and s != 2):
            return False, "Le sexe indiqué ne correspond pas au NIR."
    except Exception:
        return False, "Format du NIR invalide."

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
def ensure_schema():
    """Ajoute les colonnes manquantes si besoin (migration douce)."""
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    existing = {r[1] for r in cur.fetchall()}

    to_add = []
    if "verif_docs" not in existing:
        to_add.append(("verif_docs", "TEXT", ""))
    if "nouveau_doc" not in existing:
        to_add.append(("nouveau_doc", "INTEGER", "0"))
    if "replace_token" not in existing:
        to_add.append(("replace_token", "TEXT", ""))
    if "replace_token_exp" not in existing:
        to_add.append(("replace_token_exp", "TEXT", ""))
    if "replace_meta" not in existing:
        to_add.append(("replace_meta", "TEXT", ""))

    for col, typ, default in to_add:
        cur.execute(
            f"ALTER TABLE candidats ADD COLUMN {col} {typ} DEFAULT {json.dumps(default) if typ=='TEXT' else default}"
        )

    # 🧩 Ajout automatique des nouvelles étiquettes
    new_columns = {
        "label_ypareo": "INTEGER DEFAULT 0",
        "label_carte_etudiante": "INTEGER DEFAULT 0"
    }

    for col, definition in new_columns.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE candidats ADD COLUMN {col} {definition}")

    # 🕓 Ajout automatique des colonnes de dates d'étape
    date_cols = {
        "date_validee": "TEXT DEFAULT ''",
        "date_confirmee": "TEXT DEFAULT ''",
        "date_reconfirmee": "TEXT DEFAULT ''"
    }
    for col, definition in date_cols.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE candidats ADD COLUMN {col} {definition}")

    conn.commit()
    conn.close()




# ✅ Appel après définition
with app.app_context():
    init_db()
    ensure_schema()



import time
import sqlite3

def log_event(candidat, type_, payload_dict):
    cid = candidat["id"] if isinstance(candidat, dict) else candidat
    nd = candidat.get("numero_dossier","") if isinstance(candidat, dict) else ""
    payload = json.dumps(payload_dict, ensure_ascii=False)
    attempt = 0
    while attempt < 5:
        try:
            conn = db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO logs (id, candidat_id, numero_dossier, type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), cid, nd, type_, payload, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                attempt += 1
                print(f"⚠️ DB verrouillée (tentative {attempt}/5), nouvelle tentative dans 0.3s…")
                time.sleep(0.3)
            else:
                print("❌ Erreur log_event :", e)
                break
        except Exception as e:
            print("❌ Erreur inattendue log_event :", e)
            break


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

def save_files(field_key: str, cand_id: str):
    """
    Sauvegarde les fichiers du champ `field_key` pour le candidat `cand_id`
    dans un dossier dédié : /uploads/<cand_id>/
    avec un nom clair : <PREFIX>_<cand_id>[_2].ext
    """
    files = request.files.getlist(field_key)
    saved = []
    prefix = FILE_PREFIX.get(field_key, field_key)

    # 📁 Crée un sous-dossier par candidat
    cand_dir = os.path.join(UPLOAD_DIR, cand_id)
    os.makedirs(cand_dir, exist_ok=True)

    idx = 1
    for f in files:
        if not f or not f.filename:
            continue
        _, ext = os.path.splitext(secure_filename(f.filename))
        base = f"{prefix}_{cand_id}{'' if idx == 1 else f'_{idx}'}{ext.lower()}"
        dest = os.path.join(cand_dir, base)
        f.save(dest)
        saved.append(dest)
        idx += 1

    return saved

# --- Convertit une valeur Oui/Non en booléen (1 ou 0) ---
def b(v):
    """Convertit les réponses 'Oui', 'True', '1', etc. en 1, sinon 0."""
    if v is None:
        return 0
    s = str(v).strip().lower()
    return 1 if s in ("on", "true", "1", "yes", "oui") else 0

# =====================================================
# 💾 SAUVEGARDE DU BROUILLON ("Reprendre plus tard")
# =====================================================
@app.route("/save_draft", methods=["POST"])
def save_draft():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Aucune donnée reçue"}), 400

        # 🔹 Récupération des infos principales
        email = data.get("email", "").strip()
        prenom = data.get("prenom", "").strip()
        bts_label = data.get("bts", "BTS")
        mode = data.get("mode", "")
        numero = dossier_number()
        token = new_token()

        # 🔹 Génération du lien de reprise
        resume_link = f"{request.url_root.rstrip('/')}/reprendre/{token}"

        # 🔹 Enregistrement du brouillon local (fichier ou base JSON)
        draft_data = {
            "id": token,
            "email": email,
            "prenom": prenom,
            "bts": bts_label,
            "mode": mode,
            "numero_dossier": numero,
            "timestamp": datetime.now().isoformat()
        }

        DATA_FILE = os.path.join(DATA_DIR, "drafts.json")
        all_drafts = []
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    all_drafts = json.load(f)
            except Exception:
                all_drafts = []
        all_drafts.append(draft_data)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(all_drafts, f, indent=2, ensure_ascii=False)

        # 💌 Envoi du mail de reprise
        html = mail_html(
            "reprendre_plus_tard",
            prenom=prenom,
            bts_label=bts_label,
            lien_espace=resume_link
        )
        send_mail(email, "Reprenez votre pré-inscription – Intégrale Academy", html)

        print(f"🟢 Brouillon enregistré pour {prenom} ({email}) — lien : {resume_link}")
        return jsonify({"success": True, "link": resume_link})

    except Exception as e:
        print(f"❌ Erreur /save_draft : {e}")
        return jsonify({"success": False, "error": str(e)}), 500



# =====================================================
# 🔁 ROUTE DE REPRISE DU FORMULAIRE
# =====================================================
@app.route("/reprendre/<token>")
def reprendre_formulaire(token):
    DATA_DIR = os.getenv("DATA_DIR", "/data")
    DRAFT_PATH = os.path.join(DATA_DIR, "drafts.json")

    if not os.path.exists(DRAFT_PATH):
        abort(404)

    with open(DRAFT_PATH, "r", encoding="utf-8") as f:
        try:
            drafts = json.load(f)
        except:
            drafts = []

    # 🔍 On cherche le bon brouillon par son ID
    draft = next((d for d in drafts if d["id"] == token), None)
    if not draft:
        abort(404)

    # ✅ On utilise les données du brouillon existant
    data = draft
    step = 1  # tu peux changer si tu veux reprendre à une étape spécifique

    # 🧩 On affiche le formulaire principal avec les données sauvegardées
    return render_template(
        "index.html",
        saved_data=data,
        step=step,
        title="Reprendre votre pré-inscription"
    )




@app.route("/submit", methods=["POST"])
def submit():
    form = request.form
    conn = db()
    cur = conn.cursor()
    counter = get_counter_for_today(conn)
    numero = dossier_number(counter=counter)

    # ✅ Vérification du numéro de sécurité sociale (NIR)
    nir = form.get("num_secu", "")
    date_naiss = form.get("date_naissance", "")
    sexe = form.get("sexe", "")
    ok, msg = validate_nir(nir, date_naiss, sexe)
    if not ok:
        flash(msg, "error")
        return redirect(request.referrer or url_for("index"))

    # 🧩 Création du candidat
    cand_id = str(uuid.uuid4())
    now = datetime.now().isoformat()




    # 📎 Sauvegarde des fichiers
    fichiers_ci = save_files("ci", cand_id)
    fichiers_photo = save_files("photo", cand_id)
    fichiers_carte_vitale = save_files("carte_vitale", cand_id)
    fichiers_cv = save_files("cv", cand_id)
    fichiers_lm = save_files("lm", cand_id)

    token_confirm = new_token()
    token_confirm_exp = (datetime.now() + timedelta(days=30)).isoformat()

    # 💾 Insertion en base
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
        "", "",   # token_reconfirm, token_reconfirm_exp
        ""        # commentaires
    ))
    conn.commit()

    # 🧾 Logs et mails
    candidat = {
        "id": cand_id,
        "numero_dossier": numero,
        "email": form.get("email", ""),
        "prenom": form.get("prenom", "")
    }
    log_event(candidat, "PREINSCRIPTION_RECU", {"email": candidat["email"]})

    # ✉️ Mail au candidat avec lien espace
    cur.execute("SELECT slug_public FROM candidats WHERE id=?", (cand_id,))
    row = cur.fetchone()
    slug = row[0] if row and row[0] else uuid.uuid4().hex[:10]
    if not row or not row[0]:
        cur.execute("UPDATE candidats SET slug_public=? WHERE id=?", (slug, cand_id))
        conn.commit()

    lien_espace = url_for("espace_candidat", slug=slug, _external=True)

    # ✉️ Mail d’accusé de réception (design doré avec logo)
    html = mail_html(
        "accuse_reception",
        prenom=form.get("prenom", ""),
        bts_label=BTS_LABELS.get((form.get("bts") or "").strip().upper(), form.get("bts")),
        lien_espace=lien_espace
    )
    send_mail(form.get("email", ""), "Nous avons bien reçu votre pré-inscription – Intégrale Academy", html)

    # 📱 SMS accusé de réception
    tel = (form.get("tel", "") or "").replace(" ", "")
    if tel.startswith("0"):
        tel = "+33" + tel[1:]
    bts_label = BTS_LABELS.get((form.get("bts") or "").strip().upper(), form.get("bts"))
    msg = sms_text(
        "accuse_reception",
        prenom=form.get("prenom", ""),
        bts_label=bts_label,
        lien_espace=lien_espace
    )
    send_sms_brevo(tel, msg)
    log_event(candidat, "SMS_ENVOYE", {"type": "accuse_reception", "tel": tel})


    # 🧾 Log après envoi du mail
    log_event(candidat, "MAIL_ENVOYE", {"type": "accuse_reception"})

    # 📩 Mail interne admin
    admin_html = render_template(
        "mail_admin_notif.html",
        numero=numero,
        nom=form.get("nom", ""),
        prenom=form.get("prenom", "")
    )
    from_addr = os.getenv("MAIL_FROM", "ecole@integraleacademy.com")
    send_mail(from_addr, f"[ADMIN] Nouvelle pré-inscription {numero}", admin_html)

    # 🚀 Redirection directe vers l’espace candidat
    return redirect(lien_espace)




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
    allowed = {
    "nom","prenom","bts","mode","tel","email",
    "label_aps","label_aut_ok","label_cheque_ok",
    "label_ypareo","label_carte_etudiante",
    "commentaires","nouveau_doc",
    "date_validee","date_confirmee","date_reconfirmee"
}
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
    if not require_admin():
        abort(403)

    data = request.json or {}
    cid = data.get("id")
    value = data.get("value")

    conn = db()
    cur = conn.cursor()

    # 🕓 Enregistre la date correspondante selon le statut
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if value == "validee":
        cur.execute("UPDATE candidats SET statut=?, date_validee=?, updated_at=? WHERE id=?", (value, now_str, datetime.now().isoformat(), cid))
    elif value == "confirmee":
        cur.execute("UPDATE candidats SET statut=?, date_confirmee=?, updated_at=? WHERE id=?", (value, now_str, datetime.now().isoformat(), cid))
    elif value == "reconfirmee":
        cur.execute("UPDATE candidats SET statut=?, date_reconfirmee=?, updated_at=? WHERE id=?", (value, now_str, datetime.now().isoformat(), cid))
    else:
        cur.execute("UPDATE candidats SET statut=?, updated_at=? WHERE id=?", (value, datetime.now().isoformat(), cid))
    conn.commit()

    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())

    # =====================================================
    # ✉️ Envois automatiques selon le statut choisi
    # =====================================================
    if value == "validee":
        # 🔐 Assurer la présence d'un token de confirmation
        token = row.get("token_confirm")
        if not token:
            token = new_token()
            exp = (datetime.now() + timedelta(days=30)).isoformat()
            cur.execute("UPDATE candidats SET token_confirm=?, token_confirm_exp=?, updated_at=? WHERE id=?",
                        (token, exp, datetime.now().isoformat(), cid))
            conn.commit()
            cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
            row = dict(cur.fetchone())

        # 🔗 Lien signé vers la confirmation
        link = make_signed_link("/confirm-inscription", token)

        # ✉️ Mail "candidature validée"
        html = mail_html(
            "candidature_validee",
            prenom=row.get("prenom", ""),
            bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts")),
            lien_espace=link
        )
        send_mail(row.get("email", ""), "Votre candidature est validée – Confirmez votre inscription", html)
        log_event(row, "MAIL_ENVOYE", {"type": "validation_inscription"})

        # 📱 SMS "candidature validée"
        tel = (row.get("tel", "") or "").replace(" ", "")
        if tel.startswith("0"):
            tel = "+33" + tel[1:]
        msg = sms_text(
            "candidature_validee",
            prenom=row.get("prenom", ""),
            bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
        )
        send_sms_brevo(tel, msg)
        log_event(row, "SMS_ENVOYE", {"type": "candidature_validee", "tel": tel})

    elif value == "confirmee":
        html = mail_html(
            "inscription_confirmee",
            prenom=row.get("prenom", ""),
            bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
        )
        send_mail(row.get("email", ""), "Inscription confirmée – Intégrale Academy", html)
        log_event(row, "MAIL_ENVOYE", {"type": "inscription_confirmee"})

        tel = (row.get("tel", "") or "").replace(" ", "")
        if tel.startswith("0"):
            tel = "+33" + tel[1:]
        msg = sms_text(
            "inscription_confirmee",
            prenom=row.get("prenom", ""),
            bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
        )
        send_sms_brevo(tel, msg)
        log_event(row, "SMS_ENVOYE", {"type": "inscription_confirmee", "tel": tel})

        merci_html = render_template("mail_bienvenue.html",
                                     prenom=row.get("prenom", ""),
                                     bts=row.get("bts", ""))
        send_mail(row.get("email", ""), "Bienvenue à Intégrale Academy 🎓", merci_html)
        log_event(row, "MAIL_ENVOYE", {"type": "bienvenue"})

    elif value == "reconfirmee":
        merci_html = render_template("mail_bienvenue.html",
                                     prenom=row.get("prenom", ""),
                                     bts=row.get("bts", ""))
        send_mail(row.get("email", ""), "Bienvenue à Intégrale Academy 🎓", merci_html)
        log_event(row, "MAIL_ENVOYE", {"type": "bienvenue_manuel"})
        log_event(row, "STATUT_CHANGE", {"statut": "reconfirmee"})

    # 🪶 Log général du changement de statut
    log_event(row, "STATUT_CHANGE", {"statut": value})
    conn.close()

    return jsonify({"ok": True})



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

# =====================================================
# 📘 NOMS COMPLETS DES BTS
# =====================================================
BTS_LABELS = {
    "MCO": "BTS MANAGEMENT COMMERCIAL OPÉRATIONNEL (MCO)",
    "MOS": "BTS MANAGEMENT OPÉRATIONNEL DE LA SÉCURITÉ (MOS)",
    "PI": "BTS PROFESSIONS IMMOBILIÈRES (PI)",
    "NDRC": "BTS NÉGOCIATION ET DIGITALISATION DE LA RELATION CLIENT (NDRC)",
    "CG": "BTS COMPTABILITÉ ET GESTION (CG)",
    "CI": "BTS COMMERCE INTERNATIONAL (CI)"
}


# =====================================================
# 🧾 GÉNÉRATION CERTIFICAT DE SCOLARITÉ (DOCX UNIQUEMENT)
# =====================================================
@app.route("/admin/generate_certificat/<id>")
def admin_generate_certificat(id):
    from docx import Document
    from datetime import datetime
    from flask import send_file

    # 📂 chemins
    template_path = os.path.join("static", "templates", "certificat de scolarité 2026.docx")
    output_dir = os.path.join(DATA_DIR, "certificats")
    os.makedirs(output_dir, exist_ok=True)

    # 🧾 récupérer infos candidat
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT nom, prenom, bts FROM candidats WHERE id = ?", (id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return "Candidat introuvable", 404

    nom, prenom, bts = row
    full_name = f"{prenom.upper()} {nom.upper()}"
    date_now = datetime.now().strftime("%d/%m/%Y")

    # 🧩 Nom complet du BTS
    bts_nom_complet = BTS_LABELS.get(bts.strip().upper(), bts)

    # 🔧 valeurs de remplacement
    replacements = {
        "{{NOM_PRENOM}}": full_name,
        "{{FORMATION}}": bts_nom_complet,
        "{{DATE_AUJOURDHUI}}": date_now,
        "{{ANNEE_DEBUT}}": "2026",
        "{{ANNEE_FIN}}": "2028",
    }

    # 🧩 ouvrir modèle Word et remplacer les balises dans tous les paragraphes et tables
    doc = Document(template_path)

    def replace_text_in_paragraph(paragraph):
        for key, val in replacements.items():
            if key in paragraph.text:
                for run in paragraph.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, val)

    for p in doc.paragraphs:
        replace_text_in_paragraph(p)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    replace_text_in_paragraph(p)

    # 💾 sauvegarde du document Word généré
    output_docx = os.path.join(output_dir, f"certificat_{id}.docx")
    doc.save(output_docx)

    # 🧩 Log d’action
    log_event({"id": id}, "DOC_GENERE", {
        "type": "certificat_scolarite_distanciel",
        "file": output_docx
    })

    print(f"✅ Certificat généré pour {full_name}")
    return send_file(output_docx, as_attachment=True)


# =====================================================
# 🏫 CERTIFICAT DE SCOLARITÉ PRÉSENTIEL
# =====================================================
@app.route("/admin/generate_certificat_presentiel/<id>")
def admin_generate_certificat_presentiel(id):
    from docx import Document
    from datetime import datetime
    from flask import send_file

    # 📂 chemins
    template_path = os.path.join("static", "templates", "certificat_scolarite_presentiel.docx")
    output_dir = os.path.join(DATA_DIR, "certificats")
    os.makedirs(output_dir, exist_ok=True)

    # 🧾 récupérer infos candidat
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT nom, prenom, bts FROM candidats WHERE id = ?", (id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return "Candidat introuvable", 404

    nom, prenom, bts = row
    full_name = f"{prenom.upper()} {nom.upper()}"
    date_now = datetime.now().strftime("%d/%m/%Y")

    # 🧩 Nom complet du BTS
    bts_nom_complet = BTS_LABELS.get(bts.strip().upper(), bts)

    # 🔧 valeurs de remplacement
    replacements = {
        "{{NOM_PRENOM}}": full_name,
        "{{FORMATION}}": bts_nom_complet,
        "{{DATE_AUJOURDHUI}}": date_now,
        "{{ANNEE_DEBUT}}": "2026",
        "{{ANNEE_FIN}}": "2028",
    }

    # 🧩 ouvrir modèle Word et remplacer les balises dans tous les paragraphes et tables
    doc = Document(template_path)

    def replace_text_in_paragraph(paragraph):
        for key, val in replacements.items():
            if key in paragraph.text:
                for run in paragraph.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, val)

    for p in doc.paragraphs:
        replace_text_in_paragraph(p)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    replace_text_in_paragraph(p)

    # 💾 sauvegarde du document Word généré
    output_docx = os.path.join(output_dir, f"certificat_presentiel_{id}.docx")
    doc.save(output_docx)

    # 🧩 Log d’action
    log_event({"id": id}, "DOC_GENERE", {
        "type": "certificat_scolarite_presentiel",
        "file": output_docx
    })

    print(f"✅ Certificat présentiel généré pour {full_name}")
    return send_file(output_docx, as_attachment=True)





# =====================================================
# ✉️ ENVOI DU CERTIFICAT DE SCOLARITÉ PAR MAIL
# =====================================================
@app.route("/admin/send_certificat/<id>")
def admin_send_certificat(id):
    from flask import jsonify
    from utils import send_mail
    import os

    # 📂 Chemins des certificats
    cert_dir = os.path.join(DATA_DIR, "certificats")
    cert_path = os.path.join(cert_dir, f"certificat_{id}.docx")

    # 🔍 Vérifier que le fichier existe
    if not os.path.exists(cert_path):
        return jsonify({"ok": False, "error": "Le certificat n’a pas encore été généré."}), 404

    # 🧾 Récupérer les infos du candidat
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT prenom, nom, email, bts FROM candidats WHERE id = ?", (id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"ok": False, "error": "Candidat introuvable"}), 404

    prenom, nom, email, bts = row
    bts_nom_complet = BTS_LABELS.get(bts.strip().upper(), bts)

    # ✉️ Mail HTML
    html = mail_html(
        "certificat",
        prenom=prenom.title(),
        bts_label=bts_nom_complet
    )
    subject = f"Votre certificat de scolarité – {bts_nom_complet} 2026-2028"

    try:
        send_mail(email, subject, html, attachments=[cert_path])
        log_event({"id": id}, "MAIL_ENVOYE", {"type": "certificat"})
        print(f"✅ Certificat envoyé à {prenom} {nom} ({email})")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"❌ Erreur envoi certificat à {prenom} {nom} :", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# =====================================================
# ✉️ ENVOI DU CERTIFICAT DE SCOLARITÉ PRÉSENTIEL PAR MAIL
# =====================================================
@app.route("/admin/send_certificat_presentiel/<id>")
def admin_send_certificat_presentiel(id):
    from flask import jsonify
    from utils import send_mail
    import os

    cert_dir = os.path.join(DATA_DIR, "certificats")
    cert_path = os.path.join(cert_dir, f"certificat_presentiel_{id}.docx")

    if not os.path.exists(cert_path):
        return jsonify({"ok": False, "error": "Le certificat présentiel n’a pas encore été généré."}), 404

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT prenom, nom, email, bts FROM candidats WHERE id = ?", (id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"ok": False, "error": "Candidat introuvable"}), 404

    prenom, nom, email, bts = row
    bts_nom_complet = BTS_LABELS.get(bts.strip().upper(), bts)

    html = mail_html(
        "certificat_presentiel",
        prenom=prenom.title(),
        bts_label=bts_nom_complet
    )
    subject = f"Votre certificat de scolarité – Présentiel ({bts_nom_complet} 2026-2028)"

    try:
        send_mail(email, subject, html, attachments=[cert_path])
        log_event({"id": id}, "MAIL_ENVOYE", {"type": "certificat_presentiel"})
        print(f"✅ Certificat présentiel envoyé à {prenom} {nom} ({email})")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"❌ Erreur envoi certificat présentiel à {prenom} {nom} :", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# =====================================================
# 🕓 HISTORIQUE DES ACTIONS (LOGS)
# =====================================================
@app.route("/admin/logs/<cid>")
def admin_logs(cid):
    if not require_admin():
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT type, payload, created_at 
        FROM logs 
        WHERE candidat_id=? 
        ORDER BY datetime(created_at) DESC
    """, (cid,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # 🧩 Nettoyage : on affiche un résumé lisible
    for r in rows:
        try:
            p = json.loads(r["payload"])
            if isinstance(p, dict):
                r["payload"] = " / ".join(f"{k}: {v}" for k, v in p.items())
        except Exception:
            pass
    return jsonify(rows)


# =====================================================
# 📎 GESTION SIMPLIFIÉE DES PIÈCES JUSTIFICATIVES
# =====================================================

@app.route("/admin/files/<cid>")
def admin_files(cid):
    if not require_admin():
        abort(403)

    conn = db()
    row = get_candidat(conn, cid)
    if not row:
        conn.close()
        abort(404)

    verif = load_verif_docs(row)
    files_data = []

    # === Étape 1 : Fichiers enregistrés en base ===
    for key, (field, label) in DOC_FIELDS.items():
        file_list = parse_list(row.get(field))
        for path in file_list:
            fname = os.path.basename(path)
            status_info = verif.get(fname, {})
            files_data.append({
                "type": key,
                "label": label,
                "filename": fname,
                "path": path,
                "status": status_info.get("etat", "en_attente"),
                "horodatage": status_info.get("horodatage", "")
            })

    # === Étape 2 : Détection automatique des nouveaux fichiers dans le dossier du candidat ===
    cand_dir = os.path.join(UPLOAD_DIR, cid)
    try:
        all_on_disk = os.listdir(cand_dir)
    except Exception as e:
        print(f"⚠️ Erreur lecture du dossier candidat {cid} : {e}")
        all_on_disk = []

    existing_filenames = {os.path.basename(f["filename"]) for f in files_data}
    nouveaux_detectes = []

    for f in all_on_disk:
        if f not in existing_filenames:
            full_path = os.path.join(cand_dir, f)
            if os.path.isfile(full_path):
                files_data.append({
                    "type": "nouveau",
                    "label": "📥 Nouveau document déposé",
                    "filename": f,
                    "path": full_path,
                    "status": "nouveau",
                    "horodatage": datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%d/%m/%Y à %H:%M")
                })
                nouveaux_detectes.append(f)

    # === Étape 3 : Marquage des fichiers présents dans replace_meta (si applicable) ===
    if row.get("replace_meta"):
        try:
            meta = json.loads(row["replace_meta"])
            nouveaux_fichiers = [x["fichier"] for x in meta.get("nouveaux_fichiers", [])]
            for f in files_data:
                if f["filename"] in nouveaux_fichiers:
                    f["type"] = "nouveau"
                    f["label"] = f"📥 Nouveau document déposé — {f['label']}"
        except Exception as e:
            print("⚠️ Erreur détection replace_meta :", e)

    # === Étape 4 : Nettoyage des doublons ===
    unique_files = []
    seen = set()
    for f in files_data:
        if f["filename"] not in seen:
            unique_files.append(f)
            seen.add(f["filename"])

    conn.close()

    print(f"📎 {len(unique_files)} fichiers trouvés pour {cid} (dont {len(nouveaux_detectes)} nouveaux)")

    # (Sécurité) on ignore les statuts fantômes
    existing = {os.path.basename(f["path"]) for f in unique_files if os.path.exists(f["path"])}
    verif = {k: v for k, v in verif.items() if k in existing}

    return jsonify(unique_files)






@app.route("/admin/files/mark", methods=["POST"])
def admin_files_mark():
    if not require_admin():
        abort(403)

    data = request.json or {}
    cid = data.get("id")
    fname = data.get("filename")
    decision = data.get("decision")  # "conforme" ou "non_conforme"

    if not cid or not fname or decision not in ("conforme", "non_conforme"):
        return jsonify({"ok": False, "error": "paramètres invalides"}), 400

    conn = db()
    row = get_candidat(conn, cid)
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "candidat introuvable"}), 404

    verif = load_verif_docs(row)
    horodatage = datetime.now().strftime("%d/%m/%Y à %H:%M")

    # ✅ Marquer le document avec le label humain
    label_associe = ""
    for key, (field, label) in DOC_FIELDS.items():
        file_list = parse_list(row.get(field))
        if any(p.endswith(fname) for p in file_list):
            label_associe = label
            break

    verif[fname] = {
        "etat": decision,
        "horodatage": horodatage,
        "label": label_associe or "Pièce justificative"
    }

    cur = conn.cursor()

    # ❌ Si non conforme → supprimer physiquement le fichier
    if decision == "non_conforme":
        for key, (field, _) in DOC_FIELDS.items():
            file_list = parse_list(row.get(field))
            new_list = [p for p in file_list if not p.endswith(fname)]
            if len(new_list) != len(file_list):
                cur.execute(
                    f"UPDATE candidats SET {field}=?, updated_at=? WHERE id=?",
                    (json.dumps(new_list), datetime.now().isoformat(), cid)
                )
                try:
                    os.remove(os.path.join(UPLOAD_DIR, cid, fname))
                except FileNotFoundError:
                    pass

        # ✅ Mettre à jour le statut global
        cur.execute(
            "UPDATE candidats SET statut=?, verif_docs=?, updated_at=? WHERE id=?",
            ("docs_non_conformes", json.dumps(verif, ensure_ascii=False),
             datetime.now().isoformat(), cid)
        )

    else:
        # ✅ conforme → juste mise à jour
        cur.execute(
            "UPDATE candidats SET verif_docs=?, updated_at=? WHERE id=?",
            (json.dumps(verif, ensure_ascii=False), datetime.now().isoformat(), cid)
        )

    conn.commit()
    conn.close()

    log_event(row, "DOC_MARK", {"file": fname, "decision": decision})
    print(f"✅ Pièce {fname} marquée comme {decision}")
    return jsonify({"ok": True, "horodatage": horodatage})


# 💾 ROUTE : Fusionner les nouveaux fichiers dans les pièces normales
@app.route("/admin/files/merge", methods=["POST"])
def admin_files_merge():
    if not require_admin():
        abort(403)

    data = request.json or {}
    cid = data.get("id")
    if not cid:
        return jsonify({"ok": False, "error": "id manquant"}), 400

    conn = db()
    row = get_candidat(conn, cid)
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "candidat introuvable"}), 404

    # Charger le JSON meta existant
    try:
        meta = json.loads(row.get("replace_meta") or "{}")
        nouveaux = meta.get("nouveaux_fichiers", [])
        verif = load_verif_docs(row)
    except Exception:
        nouveaux = []
        verif = {}

    if not nouveaux:
        conn.close()
        return jsonify({"ok": False, "error": "aucun nouveau fichier"}), 400

    # Fusionner chaque nouveau fichier dans la bonne colonne
    for info in nouveaux:
        fname = info.get("fichier")
        label = info.get("label")
        if not fname:
            continue

        # Trouver la colonne correspondante selon le label
        for key, (col, label_ref) in DOC_FIELDS.items():
            if label_ref in label or label in label_ref:
                cur = conn.cursor()
                lst = parse_list(row.get(col))

                # 🧹 Supprime les anciens fichiers du même type
                prefix = fname.split("_")[0]
                lst = [p for p in lst if not os.path.basename(p).startswith(prefix)]

                # ➕ Ajoute la nouvelle version propre (avec le bon chemin)
                lst.append(os.path.join(UPLOAD_DIR, row["id"], fname))

                cur.execute(
                    f"UPDATE candidats SET {col}=?, updated_at=? WHERE id=?",
                    (json.dumps(lst, ensure_ascii=False), datetime.now().isoformat(), cid)
                )

                # 🧹 Remet le statut de ce fichier en "en_attente"
                verif[fname] = {
                    "etat": "en_attente",
                    "horodatage": datetime.now().strftime("%d/%m/%Y à %H:%M"),
                    "label": label
                }

                break

    # 🧩 Enregistrer le dictionnaire verif mis à jour et nettoyer replace_meta
    cur = conn.cursor()
    cur.execute(
        "UPDATE candidats SET nouveau_doc=0, replace_meta=?, verif_docs=?, updated_at=? WHERE id=?",
        ("{}", json.dumps(verif, ensure_ascii=False), datetime.now().isoformat(), cid)
    )
    conn.commit()

    # 🔄 Recharger la fiche pour nettoyage
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = dict(cur.fetchone())

    # 🧽 Nettoyage des entrées orphelines dans verif_docs
    existing_files = []
    for key, (col, _) in DOC_FIELDS.items():
        existing_files += [os.path.basename(p) for p in parse_list(row.get(col))]

    verif_purged = {f: v for f, v in load_verif_docs(row).items() if f in existing_files}

    cur.execute(
        "UPDATE candidats SET verif_docs=?, updated_at=? WHERE id=?",
        (json.dumps(verif_purged, ensure_ascii=False), datetime.now().isoformat(), cid)
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


# =====================================================
# ✉️ NOTIFICATION DE DOCUMENTS NON CONFORMES
# =====================================================

@app.route("/admin/files/notify", methods=["POST"])
def admin_files_notify():
    if not require_admin():
        abort(403)

    data = request.json or {}
    cid = data.get("id")
    commentaire = (data.get("commentaire") or "").strip()

    if not cid:
        return jsonify({"ok": False, "error": "ID manquant"}), 400

    conn = db()
    row = get_candidat(conn, cid)
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Candidat introuvable"}), 404

    verif = load_verif_docs(row)

    # 🔍 Lister les documents non conformes
    non_conformes = []
    for f, v in verif.items():
        if v.get("etat") == "non_conforme":
            label = v.get("label", "Pièce justificative")
            date = v.get("horodatage", "")
            non_conformes.append(f"{label} – {f} (le {date})")


    if not non_conformes:
        return jsonify({"ok": False, "error": "Aucune pièce non conforme"}), 400

    recap = "\n".join(["• " + n for n in non_conformes])

    # 🧩 Générer un token de remplacement valable 15 jours
    token = new_token()
    exp = (datetime.now() + timedelta(days=15)).isoformat()
    cur = conn.cursor()
    cur.execute("""
        UPDATE candidats 
        SET statut=?, replace_token=?, replace_token_exp=?, replace_meta=?, updated_at=? 
        WHERE id=?
    """, (
        "docs_non_conformes",
        token,
        exp,
        json.dumps({"pieces": non_conformes, "commentaire": commentaire}),
        datetime.now().isoformat(),
        cid
    ))
    conn.commit()
    conn.close()

    # ✉️ Envoi du mail au candidat
    link = make_signed_link("/replace-files", token)
    html = mail_html(
        "docs_non_conformes",
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts")),
        lien_espace=link
    )
    send_mail(row.get("email", ""), "Documents non conformes – Intégrale Academy", html)

    # 📱 SMS documents non conformes
    tel = (row.get("tel", "") or "").replace(" ", "")
    if tel.startswith("0"):
        tel = "+33" + tel[1:]
    msg = sms_text(
        "docs_non_conformes",
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
    )
    send_sms_brevo(tel, msg)
    log_event(row, "SMS_ENVOYE", {"type": "docs_non_conformes", "tel": tel})

    log_event(row, "MAIL_ENVOYE", {"type": "docs_non_conformes", "pieces": non_conformes})

    return jsonify({"ok": True})

# =====================================================
# 📤 PAGE PUBLIQUE – RENVOI DE NOUVELLES PIÈCES
# =====================================================

@app.route("/replace-files", methods=["GET"])
def replace_files_form():
    token = request.args.get("token", "")
    sig = request.args.get("sig", "")
    if not verify_token(token, sig):
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE replace_token=?", (token,))
    row = cur.fetchone()
    conn.close()
    if not row:
        abort(404)

    row = dict(row)
    meta = json.loads(row.get("replace_meta") or "{}")
    pieces = meta.get("pieces", [])
    commentaire = meta.get("commentaire", "")

    return render_template(
        "replace_files.html",
        title="Envoyer mes nouvelles pièces justificatives",
        pieces=pieces,
        commentaire=commentaire,
        token=token,
        sig=sig
    )


@app.route("/replace-files", methods=["POST"])
def replace_files_submit():
    token = request.form.get("token", "")
    sig = request.form.get("sig", "")
    if not verify_token(token, sig):
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE replace_token=?", (token,))
    row = cur.fetchone()
    if not row:
        conn.close()
        abort(404)

    row = dict(row)

    # 🔁 Mise à jour du candidat : on sauvegarde les nouveaux fichiers dans replace_meta
    meta = json.loads(row.get("replace_meta") or "{}")
    nouveaux = []

    for field_name, (col_name, label) in DOC_FIELDS.items():
        files = request.files.getlist(field_name)
        prefix = FILE_PREFIX.get(field_name, field_name)

        # 📁 Dossier du candidat (même principe que save_files)
        cand_dir = os.path.join(UPLOAD_DIR, row["id"])
        os.makedirs(cand_dir, exist_ok=True)

        idx = 1
        for f in files:
            if not f or not f.filename:
                continue
            _, ext = os.path.splitext(secure_filename(f.filename))
            base = f"{prefix}_{row['id']}{'' if idx == 1 else f'_{idx}'}{ext.lower()}"
            dest = os.path.join(cand_dir, base)
            f.save(dest)
            nouveaux.append({"fichier": base, "label": label})
            idx += 1

    meta["nouveaux_fichiers"] = nouveaux

    cur.execute("""
        UPDATE candidats
        SET nouveau_doc=1,
            replace_meta=?,
            updated_at=?,
            statut=?
        WHERE id=?
    """, (
        json.dumps(meta, ensure_ascii=False),
        datetime.now().isoformat(),
        "preinscription",
        row["id"]
    ))
    conn.commit()
    conn.close()

    # ✉️ Mail à l’admin
    admin_html = render_template(
        "mail_new_docs_admin.html",
        numero=row.get("numero_dossier", ""),
        nom=row.get("nom", ""),
        prenom=row.get("prenom", ""),
        fichiers=[n["fichier"] for n in nouveaux]
    )
    from_addr = os.getenv("MAIL_FROM", "ecole@integraleacademy.com")
    send_mail(from_addr, f"[ADMIN] Nouvelles pièces déposées ({row.get('numero_dossier')})", admin_html)

    log_event(row, "DOCS_RENVOYES", {"files": [n["fichier"] for n in nouveaux]})

    return render_template("replace_ok.html", title="Merci", fichiers=[n["fichier"] for n in nouveaux])








# =====================================================
# 📦 ROUTE : Télécharger toutes les pièces justificatives (ZIP)
# =====================================================

@app.route("/admin/files/download/<cid>")
def admin_files_download(cid):
    if not require_admin():
        abort(403)
    import zipfile, io

    conn = db()
    row = get_candidat(conn, cid)
    if not row:
        abort(404)
    conn.close()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for key, (field, label) in DOC_FIELDS.items():
            file_list = parse_list(row.get(field))
            for path in file_list:
                if os.path.exists(path):
                    zipf.write(path, arcname=os.path.basename(path))
    buffer.seek(0)

    zip_name = f"pieces_{row.get('numero_dossier','')}.zip"
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name
    )




@app.route("/admin/status/<cid>")
def admin_status(cid):
    if not require_admin():
        abort(403)
    conn = db()
    row = get_candidat(conn, cid)
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "statut": row.get("statut")})




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

    html = mail_html(
    "inscription_confirmee",
    prenom=row.get("prenom",""),
    bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
)

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

    # 📱 SMS reconfirmation validée
    tel = (row.get("tel", "") or "").replace(" ", "")
    if tel.startswith("0"):
        tel = "+33" + tel[1:]
    msg = sms_text(
    "reconfirmation_validee",
    prenom=row.get("prenom", ""),
    bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
)

    send_sms_brevo(tel, msg)
    log_event(row, "SMS_ENVOYE", {"type": "reconfirmation_validee", "tel": tel})


    log_event(row, "STATUT_CHANGE", {"statut": "reconfirmee"})
    return render_template("reconfirm_ok.html", title="Merci ❤️")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin"))

# ------------------------------------------------------------
# 📊 API publique : /data.json
#    → Sert au tableau de bord principal pour afficher le nombre
#      de pré-inscriptions à traiter en temps réel.
# ------------------------------------------------------------
@app.route("/data.json")
def data_json():
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT statut FROM candidats")
        rows = [r[0] for r in cur.fetchall()]

        # 🔍 Comptage : uniquement les statuts "pré-inscription à traiter"
        a_traiter = len([s for s in rows if not s or s == "preinscription" or s.lower().startswith("pré")])

        payload = {"a_traiter": a_traiter, "total": len(rows)}
        headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        }
        return json.dumps(payload, ensure_ascii=False), 200, headers

    except Exception as e:
        print("❌ Erreur /data.json :", e)
        return json.dumps({"error": str(e)}), 500, {"Access-Control-Allow-Origin": "*"}

# =====================================================
# 👁️ ROUTE : Prévisualiser une pièce justificative
# =====================================================
@app.route("/uploads/<path:filename>")
def preview_upload(filename):
    # 🧩 Normalisation du nom
    filename = os.path.basename(filename)

    # 🧩 Chemin direct (compatibilité)
    direct_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(direct_path):
        return send_file(direct_path)

    # 🔎 Recherche dans les sous-dossiers candidats
    for cid in os.listdir(UPLOAD_DIR):
        sub_path = os.path.join(UPLOAD_DIR, cid, filename)
        if os.path.exists(sub_path):
            return send_file(sub_path)

    print(f"⚠️ Fichier introuvable : {filename}")
    abort(404)


# =====================================================
# 🧹 NETTOYAGE AUTOMATIQUE DES DOSSIERS ORPHELINS
# =====================================================
def cleanup_orphan_folders():
    print("🧹 Vérification des dossiers orphelins dans /uploads...")
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM candidats")
    valid_ids = {r[0] for r in cur.fetchall()}
    conn.close()

    import shutil
    removed = 0

    for f in os.listdir(UPLOAD_DIR):
        full = os.path.join(UPLOAD_DIR, f)
        if os.path.isdir(full) and f not in valid_ids:
            try:
                shutil.rmtree(full)
                removed += 1
            except Exception as e:
                print(f"⚠️ Impossible de supprimer {f}: {e}")

    if removed:
        print(f"✅ {removed} dossier(s) orphelin(s) supprimé(s) du répertoire uploads.")
    else:
        print("✅ Aucun dossier orphelin trouvé.")


# Lancer le nettoyage une fois au démarrage
with app.app_context():
    cleanup_orphan_folders()


print("🚀 Application Flask démarrée – gestion CNAPS & pièces justificatives OK")

@app.route("/admin/clear-db", methods=["POST"])
def admin_clear_db():
    if not require_admin():
        abort(403)

    conn = db()
    cur = conn.cursor()
    # Supprimer tous les candidats et logs
    cur.execute("DELETE FROM candidats")
    cur.execute("DELETE FROM logs")
    conn.commit()
    conn.close()

    # 🧹 Supprimer tous les sous-dossiers candidats dans /uploads
    try:
        import shutil
        for f in os.listdir(UPLOAD_DIR):
            full = os.path.join(UPLOAD_DIR, f)
            if os.path.isdir(full):
                shutil.rmtree(full)
            elif os.path.isfile(full):
                os.remove(full)
    except Exception as e:
        print("⚠️ Erreur suppression fichiers :", e)

    flash("Base de données et fichiers effacés ✅", "success")
    return redirect(url_for("admin"))

    # =====================================================
# 🧩 AJOUT DU SLUG PUBLIC (IDENTIFIANT UNIQUE)
# =====================================================
def ensure_slug_public():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]
    if "slug_public" not in cols:
        print("🧩 Ajout de la colonne slug_public...")
        cur.execute("ALTER TABLE candidats ADD COLUMN slug_public TEXT DEFAULT ''")
        conn.commit()

    # Génération automatique d’un slug pour les candidats sans identifiant public
    cur.execute("SELECT id, slug_public FROM candidats")
    rows = cur.fetchall()
    for cid, slug in rows:
        if not slug:
            new_slug = uuid.uuid4().hex[:10]
            cur.execute("UPDATE candidats SET slug_public=? WHERE id=?", (new_slug, cid))
    conn.commit()
    conn.close()

with app.app_context():
    ensure_slug_public()

    # =====================================================
# 👤 PAGE PUBLIQUE – ESPACE CANDIDAT
# =====================================================
@app.route("/espace/<slug>")
def espace_candidat(slug):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE slug_public=?", (slug,))
    row = cur.fetchone()
    conn.close()

    if not row:
        abort(404)

    row = dict(row)
    statut = (row.get("statut") or "").lower()
    commentaire = row.get("commentaires") or ""

    # === Nom complet de la formation ===
    bts_code = (row.get("bts") or "").strip().upper()
    bts_label = BTS_LABELS.get(bts_code, row.get("bts"))
    row["bts_label"] = bts_label

    # === Libellé du mode de formation ===
    mode = (row.get("mode") or "").lower()
    if "dist" in mode:
        row["mode_label"] = "💻 À distance 100% en ligne (visioconférence)"
    else:
        row["mode_label"] = "🏫 En présentiel à Puget-sur-Argens (Var, 83)"

    explications = {
        "preinscription": "Votre candidature a bien été enregistrée. Elle est en cours d’examen par notre équipe.",
        "validee": "Votre candidature est validée. Vous allez recevoir un mail pour confirmer votre inscription.",
        "confirmee": "Votre inscription est confirmée 🎓. Bienvenue à Intégrale Academy !",
        "reconf_en_cours": "Une reconfirmation est en attente de votre part. Consultez vos e-mails pour finaliser.",
        "reconfirmee": "Votre reconfirmation a été validée ✅.",
        "docs_non_conformes": "Certains documents ont été jugés non conformes. Veuillez consulter votre e-mail pour les renvoyer.",
        "annulee": "Votre inscription a été annulée. Pour toute question, contactez notre équipe.",
    }

    explication_statut = explications.get(statut, "Le traitement de votre dossier est en cours.")

    return render_template(
        "espace_candidat.html",
        row=row,
        statut=statut,
        explication_statut=explication_statut,
        commentaire=commentaire
    )


    # =====================================================
# 👁️ LIEN DIRECT DEPUIS L’ADMIN VERS L’ESPACE CANDIDAT
# =====================================================
@app.route("/admin/candidat/<cid>/espace")
def admin_espace_candidat(cid):
    if not require_admin():
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT slug_public FROM candidats WHERE id=?", (cid,))
    row = cur.fetchone()
    conn.close()

    if not row or not row["slug_public"]:
        abort(404)

    slug = row["slug_public"]
    return redirect(url_for("espace_candidat", slug=slug))

# =====================================================
# 🔁 RECONFIRMATION MANUELLE D'INSCRIPTION (depuis admin)
# =====================================================
@app.route("/admin/reconfirm/<cid>", methods=["POST"])
def admin_reconfirm(cid):
    if not require_admin():
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Candidat introuvable"}), 404

    row = dict(row)

    # 🔹 Génération du token de reconfirmation
    token = new_token()
    exp = (datetime.now() + timedelta(days=15)).isoformat()
    cur.execute(
        "UPDATE candidats SET token_reconfirm=?, token_reconfirm_exp=?, statut=?, updated_at=? WHERE id=?",
        (token, exp, "reconf_en_cours", datetime.now().isoformat(), cid)
    )
    conn.commit()
    conn.close()

    # 🔗 Lien de reconfirmation (signé)
    link = make_signed_link("/reconfirm", token)

    # ✉️ Mail HTML (utilise ton template)
    html = mail_html(
        "reconfirmation",
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts")),
        lien_espace=link
    )

    # 🔹 Envoi du mail
    send_mail(
        row.get("email", ""),
        "Reconfirmation de votre inscription – Intégrale Academy",
        html
    )

    # 📱 SMS de notification (optionnel)
    tel = (row.get("tel", "") or "").replace(" ", "")
    if tel.startswith("0"):
        tel = "+33" + tel[1:]
    msg = sms_text(
        "reconfirmation_demandee",
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
    )
    send_sms_brevo(tel, msg)

    # 🧾 Log
    log_event(row, "MAIL_ENVOYE", {"type": "reconfirmation"})
    log_event(row, "SMS_ENVOYE", {"type": "reconfirmation", "tel": tel})
    log_event(row, "STATUT_CHANGE", {"statut": "reconf_en_cours"})

    return jsonify({"ok": True})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
