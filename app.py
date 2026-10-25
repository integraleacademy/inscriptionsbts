from contextlib import closing

import os, sqlite3, json, uuid, shutil
from datetime import datetime, timedelta
from admission_options import PROFILE_GROUPS
from place_search import register_place_search
from candidate_access import register_candidate_access, get_authenticated_student
from candidate_messages import register_candidate_messages
from candidate_photos import photo_response, register_candidate_photos
from candidate_workflows import register_candidate_workflows
from candidate_documents import register_candidate_documents, document_preview_response
from student_cards import register_student_cards, student_card_dates
from trainer_access import register_trainer_access
from company_portal import register_company_portal
from daily_login import register_daily_login
from promotions import register_promotions, ensure_promotions_schema, get_candidate_promotion, list_promotions
from planning import register_planning
from planning_portal import register_planning_portal, get_portal_today
from planning_sync import register_planning_sync
from trainer_availability import register_trainer_availability
from trainer_admin_planning import register_admin_trainer_planning
from legacy_links import snapshot_legacy_links, verify_legacy_link
from campaign import ADMISSION_YEAR, OPENS_AT, OPENING_LABEL, campaign_is_open, candidate_year
from flask import Flask, render_template, request, redirect, url_for, send_file, session, abort, jsonify, flash
from werkzeug.utils import secure_filename
from utils import send_mail, send_sms_brevo, dossier_number, new_token, sign_token, make_signed_link
from dotenv import load_dotenv
from parcoursup import bp_parcoursup
from sms_templates import sms_text
from mail_templates import mail_html
from utils import get_mail_context
from utils import BTS_LABELS


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
        "static/js/application-2027.js",
        "static/js/admission-validation.js",
        "static/js/place-autocomplete.js",
        "static/js/bts-management.js",
        "static/js/workspace-shell.js",
        "static/css/bts-experience.css",
        "templates/candidate_sheet.html",
        "admission_options.py",
        "place_search.py",
        "candidate_access.py",
        "candidate_messages.py",
        "candidate_documents.py",
        "candidate_photos.py",
        "student_cards.py",
        "assets/student_cards/carte_etudiante_original.pdf",
        "templates/_candidate_student_card.html",
        "templates/student_card_error.html",
        "certificates.py",
        "assets/certificates/manifest.json",
        "assets/certificates/models.pdf",
        "assets/certificates/fonts/LiberationSans-Regular.ttf",
        "assets/certificates/fonts/LiberationSans-Bold.ttf",
        "assets/certificates/fonts/LiberationSans-Italic.ttf",
        "static/js/candidate-photo.js",
        "static/css/candidate-editor.css",
        "candidate_workflows.py",
        "trainer_access.py",
        "company_portal.py",
        "company_registry.py",
        "reference_data/company_nomenclatures.json",
        "static/js/company-registry.js",
        "static/js/company-admin.js",
        "static/css/company-admin.css",
        "static/admissions/company-space-illustration.webp",
        "templates/company_auth.html",
        "templates/company_admin.html",
        "templates/company_create.html",
        "templates/_company_admin_ui.html",
        "templates/_company_profile_overview.html",
        "templates/_company_profile_registry.html",
        "templates/_company_profile_students.html",
        "templates/_company_profile_access.html",
        "templates/company_detail.html",
        "templates/company_dashboard.html",
        "templates/company_attendance.html",
        "templates/_company_fields.html",
        "templates/_company_attendance_table.html",
        "static/css/company-space.css",
        "templates/trainer_admin.html",
        "templates/trainer_login.html",
        "templates/trainer_password.html",
        "templates/trainer_forgot_password.html",
        "templates/trainer_dashboard.html",
        "static/css/trainer-space.css",
        "static/js/trainer-space.js",
        "daily_login.py",
        "promotions.py",
        "planning.py",
        "subject_catalog.py",
        "planning_holidays.py",
        "planning_portal.py",
        "planning_sync.py",
        "trainer_availability.py",
        "trainer_workload.py",
        "trainer_admin_planning.py",
        "trainer_notifications.py",
        "templates/email_trainer_availability.html",
        "templates/_trainer_admin_planning.html",
        "templates/_trainer_admin_availability.html",
        "templates/_trainer_portal_nav.html",
        "static/css/trainer-admin-planning.css",
        "static/js/trainer-admin-planning.js",
        "static/css/academy-vibrant.css",
        "templates/trainer_availability.html",
        "templates/trainer_detail.html",
        "static/css/trainer-availability.css",
        "static/js/trainer-availability.js",
        "static/css/trainer-workload.css",
        "static/js/trainer-workload.js",
        "static/css/planning-sync.css",
        "static/js/planning-sync.js",
        "templates/portal_planning.html",
        "templates/_portal_today.html",
        "templates/_portal_course.html",
        "static/css/portal-planning.css",
        "static/js/portal-planning.js",
        "planning_pdf.py",
        "branded_email.py",
        "templates/planning_admin.html",
        "templates/planning_subjects.html",
        "templates/planning_rooms.html",
        "static/css/planning-catalog.css",
        "static/js/planning-catalog.js",
        "static/js/subject-catalog.js",
        "static/css/subject-catalog.css",
        "static/css/planning.css",
        "static/js/planning.js",
        "templates/promotions_admin.html",
        "static/css/academy-neutral.css",
        "static/css/daily-login.css",
        "static/css/promotions.css",
        "static/js/promotions.js",
        "static/js/candidate-promotion.js",
        "templates/document_preview.html",
        "legacy_links.py",
        "templates/candidate_login.html",
        "templates/candidate_verify.html",
        "templates/student_password.html",
        "templates/student_forgot_password.html",
        "templates/student_reset_password.html",
        "static/css/public-refinement.css",
        "static/css/candidate-refinement.css",
        "static/css/candidate-access.css",
        "static/js/admission-celebration.js",
        "static/js/candidate-refinement.js",
        "static/admissions/countries-fr.json",
        "static/css/styles.css",
        "static/logo-integrale.png",
        "static/academy-official-logo.png",
    ]
    required_files.extend(f"static/admissions/daily/{role}-{day}.webp"
                          for role in ("student", "trainer")
                          for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
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
    for p in ["app.py", "parcoursup.py", "mail_templates.py", "sms_templates.py", "place_search.py", "candidate_access.py", "candidate_messages.py", "candidate_documents.py", "candidate_photos.py", "candidate_workflows.py", "trainer_access.py", "company_portal.py", "promotions.py", "planning.py", "planning_portal.py", "planning_sync.py", "trainer_availability.py", "trainer_workload.py", "trainer_admin_planning.py"]:
        py_sources[p] = _read(p)

    route_regex = re.compile(r"""@(?:app|bp_[a-zA-Z0-9_]+)\.(?:route|get|post|put|delete)\(\s*['"]([^'"]+)['"]""")
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
    for js_path in ["static/js/main_front.js", "static/js/main_admin.js", "static/js/application-2027.js", "static/js/bts-management.js", "static/js/place-autocomplete.js"]:
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
    base_html_path = os.path.join(os.getcwd(), "templates", "email_base.html")
    base_mail = _read(base_html_path) or ""
    print(f"📂 Vérification email_base.html → {base_html_path}")

    # Autorise aussi {{ email_content | safe }}
    if ("{{ email_title" not in base_mail) or ("{{ email_content" not in base_mail):
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
# 🔒 Limite maximale pour les uploads (50 Mo)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# 🛑 Erreur fichiers trop lourds (413)
@app.errorhandler(413)
def too_large(e):
    return (
        render_template(
            "error_upload.html",
            message="Le fichier que vous essayez d’envoyer est trop volumineux (maximum 8 Mo par fichier)."
        ),
        413
    )
     
app.secret_key = os.getenv("SECRET_KEY", "change-me")
# 🔐 Protection du module Parcoursup (toutes les routes /parcoursup)
@bp_parcoursup.before_request
def protect_parcoursup_routes():
    if not session.get("admin_ok"):
        return redirect(url_for("login"))

# 🔧 Rendre la fonction now() accessible dans les templates Jinja
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow, 'server_now': datetime.utcnow().isoformat() + 'Z', 'admission_year': ADMISSION_YEAR, 'opening_iso': OPENS_AT.isoformat(), 'opening_label': OPENING_LABEL, 'candidate_year': candidate_year, 'selected_year': request.args.get('rentree', str(ADMISSION_YEAR)), 'profile_groups': PROFILE_GROUPS}

# 🕓 Filtre Jinja pour convertir une chaîne ISO en datetime
from datetime import datetime

@app.template_filter("to_datetime")
def to_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.utcnow()

if "parcoursup" not in app.blueprints:
    app.register_blueprint(bp_parcoursup)
else:
    print("⚠️ Blueprint 'parcoursup' déjà enregistré — enregistrement ignoré.")


# =====================================================
# 🔤 Filtres Jinja pour affichage PDF
# =====================================================

@app.template_filter('modeemo')
def modeemo(value):
    if not value:
        return ""
    return "🏫 Présentiel" if value.lower() == "presentiel" else "💻 Distanciel"

@app.template_filter('btsfull')
def btsfull(value):
    if value == "MOS": return "BTS Management Opérationnel de la Sécurité (MOS)"
    if value == "MCO": return "BTS Management Commercial Opérationnel (MCO)"
    if value == "PI": return "BTS Professions Immobilières (PI)"
    if value == "CI": return "BTS Commerce International (CI)"
    if value == "NDRC": return "BTS Négociation et Digitalisation de la Relation Client (NDRC)"
    if value == "CG": return "BTS Comptabilité et Gestion (CG)"
    return value or ""

@app.template_filter('bacdisp')
def bacdisp(value):
    if not value: return ""
    if "prévu" in value.lower(): return value
    if "oui" in value.lower(): return "Oui"
    if "non" in value.lower(): return "Non"
    return value

@app.template_filter('nirsp')
def nirsp(value):
    if not value: return ""
    value = value.replace(" ", "")
    return " ".join([value[i:i+2] for i in range(0, len(value), 2)]).strip()

@app.template_filter('dmy')
def dmy(value):
    try:
        from datetime import datetime
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except Exception:
        return value



# =====================================================
# 🎨 Filtres d'affichage Jinja unifiés
# =====================================================
import unicodedata

def _normalize(s: str) -> str:
    if not s: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def _fmt_date_dmy(s: str) -> str:
    if not s: return ""
    try:
        if "T" in s or ":" in s:
            dt = datetime.fromisoformat(s.replace("Z",""))
            return dt.strftime("%d/%m/%Y")
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return s

def _nir_spaced(nir: str) -> str:
    """Formate le NIR en groupes exacts ex: 1 93 09 74 256 233 79"""
    if not nir:
        return ""
    raw = (nir or "").strip().upper().replace(" ", "")
    groups, cuts, i = [], [1,2,2,2,3,3,2], 0
    for c in cuts:
        groups.append(raw[i:i+c])
        i += c
        if i >= len(raw):
            break
    return " ".join([g for g in groups if g])

def _bts_full(code: str) -> str:
    code = (code or "").strip().upper()
    return {
        "MCO": "BTS MANAGEMENT COMMERCIAL OPÉRATIONNEL (MCO)",
        "MOS": "BTS MANAGEMENT OPÉRATIONNEL DE LA SÉCURITÉ (MOS)",
        "PI":  "BTS PROFESSIONS IMMOBILIÈRES (PI)",
        "NDRC":"BTS NÉGOCIATION ET DIGITALISATION DE LA RELATION CLIENT (NDRC)",
        "CG":  "BTS COMPTABILITÉ ET GESTION (CG)",
        "CI":  "BTS COMMERCE INTERNATIONAL (CI)",
    }.get(code, code)

def _mode_emoji(mode: str) -> str:
    m = _normalize((mode or "").strip().lower())
    if "pres" in m: return "🏫 Présentiel"
    if "dist" in m: return "💻 Distanciel"
    return mode or ""

def _bac_status_display(v: str) -> str:
    s = _normalize((v or "").strip().lower())
    if s in {"oui","yes","true","1"}: return "Oui"
    if s in {"non","no","false","0"}: return "Non"
    if "prev" in s: return v
    return (v or "").strip() or "—"

# 🔗 Enregistrement global
app.jinja_env.filters["dmy"]      = _fmt_date_dmy
app.jinja_env.filters["nirsp"]    = _nir_spaced
app.jinja_env.filters["btsfull"]  = _bts_full
app.jinja_env.filters["modeemo"]  = _mode_emoji
app.jinja_env.filters["bacdisp"]  = _bac_status_display



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

def normalize_candidate_names(values):
    """Persist the same readable identity formatting as the application form."""
    for key in ("nom", "prenom", "resp_nom", "resp_prenom"):
        if key in values:
            clean = " ".join(str(values.get(key) or "").split())
            values[key] = clean.upper() if key.endswith("nom") and not key.endswith("prenom") else clean.title()
    return values

def validate_nir(nir_raw, date_naissance_str, sexe_str):
    """Valide le NIR (clé + cohérence date + sexe). 
    Conserve 2A/2B dans la valeur stockée, mais effectue la vérification avec conversion temporaire."""
    if not nir_raw:
        return False, "Numéro de sécurité sociale manquant."

    nir_clean = normalize_nir(nir_raw)

    # 🔁 copie temporaire pour le calcul (convertit juste pour la vérif)
    if not re.fullmatch(r"[0-9]{5}(?:[0-9]{2}|2[AB])[0-9]{8}", nir_clean):
        return False, "Le numéro doit comporter 15 caractères ; 2A et 2B sont autorisés pour la Corse."
    nir_calc = nir_clean.replace("2A", "19").replace("2B", "18")
    digits = "".join(ch for ch in nir_calc if ch.isdigit())

    if len(digits) != 15:
        return False, "Le numéro de sécurité sociale doit comporter 15 caractères (chiffres ou A/B)."

    # ✅ Vérification de la clé de contrôle
    try:
        corps, cle = digits[:13], int(digits[13:15])
        calc = 97 - (int(corps) % 97)
        if calc != cle:
            return False, "Le numéro et sa clé de contrôle ne correspondent pas. Vérifiez les 15 caractères sur votre attestation de droits : l’erreur peut se trouver n’importe où dans le numéro, pas seulement dans les deux derniers chiffres."
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
    date_naissance TEXT, ville_naissance TEXT, cp_naissance TEXT,
    pays_naissance TEXT, nationalite TEXT,
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
    projet_qualites TEXT, projet_motivation TEXT, projet_recherche TEXT, projet_travail TEXT,
    fichiers_ci TEXT, fichiers_photo TEXT, fichiers_carte_vitale TEXT, fichiers_cv TEXT, fichiers_lm TEXT,
    statut TEXT,
    label_aps INTEGER, label_aut_ok INTEGER, label_cheque_ok INTEGER,
    token_confirm TEXT, token_confirm_exp TEXT,
    token_reconfirm TEXT, token_reconfirm_exp TEXT,
    commentaires TEXT,
    verif_docs TEXT, nouveau_doc INTEGER,
    replace_token TEXT, replace_token_exp TEXT, replace_meta TEXT,
    label_ypareo INTEGER, label_carte_etudiante INTEGER,
    ypareo_id TEXT, ypareo_statut TEXT, ypareo_erreur TEXT,
    ypareo_cursus_id TEXT, ypareo_cursus_statut TEXT,
    ypareo_cursus_erreur TEXT,
    ypareo_id_personne TEXT, ypareo_id_cursus TEXT,
    ypareo_id_dossier TEXT, ypareo_inscriptions TEXT,
    ypareo_af_statut TEXT, ypareo_af_error TEXT,
    ypareo_af_url_affectation TEXT, ypareo_af_id_numerique TEXT,
    ypareo_af_synced_at TEXT,
    ypareo_sync_at TEXT,
    date_validee TEXT, date_confirmee TEXT, date_reconfirmee TEXT,
    slug_public TEXT,
    rentree_annee INTEGER NOT NULL DEFAULT 2026
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

def ensure_schema():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Vérifie les colonnes existantes
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]

    expected_cols = [
        "nationalite", "raison_aps",
        "projet_qualites", "projet_motivation", "projet_recherche", "projet_travail",
        "verif_docs", "nouveau_doc", "replace_token", "replace_token_exp", "replace_meta",
        "label_ypareo", "label_carte_etudiante",
        "date_validee", "date_confirmee", "date_reconfirmee", "slug_public",
        "ypareo_id", "ypareo_statut", "ypareo_erreur", "ypareo_cursus_id",
        "ypareo_cursus_statut", "ypareo_cursus_erreur",
        "ypareo_id_personne", "ypareo_id_cursus", "ypareo_id_dossier",
        "ypareo_inscriptions", "ypareo_af_statut", "ypareo_af_error",
        "ypareo_af_url_affectation", "ypareo_af_id_numerique",
        "ypareo_af_synced_at", "ypareo_sync_at"
    ]

    for col in expected_cols:
        if col not in cols:
            print(f"🧱 Ajout automatique de la colonne {col} dans 'candidats'")
            cur.execute(f"ALTER TABLE candidats ADD COLUMN {col} TEXT DEFAULT ''")

    conn.commit()
    conn.close()

# ✅ Appel après définition
with app.app_context():
    init_db()
    ensure_schema()



import time
import sqlite3

# =====================================================
# 🧾 Vérifie et ajoute les colonnes apprentissage si manquantes
# =====================================================
def ensure_apprentissage_fields():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]

    if "entreprise_trouvee" not in cols:
        cur.execute("ALTER TABLE candidats ADD COLUMN entreprise_trouvee TEXT DEFAULT ''")
    if "recherches_commencees" not in cols:
        cur.execute("ALTER TABLE candidats ADD COLUMN recherches_commencees TEXT DEFAULT ''")

    conn.commit()
    conn.close()

# 🔁 Exécuter la vérification au démarrage
with app.app_context():
    ensure_apprentissage_fields()

# =====================================================
# 🎓 Vérifie et ajoute la colonne BACCALAURÉAT si manquante
# =====================================================
def ensure_baccalaureat_field():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]
    if "baccalaureat" not in cols:
        cur.execute("ALTER TABLE candidats ADD COLUMN baccalaureat TEXT DEFAULT ''")
        print("🧱 Colonne 'baccalaureat' ajoutée à la table 'candidats'")
    conn.commit()
    conn.close()

with app.app_context():
    ensure_baccalaureat_field()

# =====================================================
# 🧾 Vérifie et ajoute la colonne "cid" dans la table logs si manquante
# =====================================================
def ensure_logs_cid_column():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(logs)")
    cols = [r[1] for r in cur.fetchall()]
    if "cid" not in cols:
        print("🧩 Ajout automatique de la colonne 'cid' dans logs…")
        cur.execute("ALTER TABLE logs ADD COLUMN cid TEXT")
        conn.commit()
    conn.close()

with app.app_context():
    ensure_logs_cid_column()


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
    return session.get("admin_ok", False)

# =====================================================
# 🕓 Ajout automatique de la colonne "last_relance" dans la table candidats
# =====================================================
def ensure_relance_field():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]
    if "last_relance" not in cols:
        print("🧩 Ajout automatique de la colonne 'last_relance' dans candidats…")
        cur.execute("ALTER TABLE candidats ADD COLUMN last_relance TEXT")
        conn.commit()
    conn.close()

with app.app_context():
    ensure_relance_field()



# =========================
# 🔐 PAGE DE CONNEXION SÉCURISÉE
# =========================
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL", "clement@integraleacademy.com")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "Lv15052021@")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if email == LOGIN_EMAIL and password == LOGIN_PASSWORD:
            session["admin_ok"] = True
            flash("Connexion réussie", "success")
            destination = request.args.get("next", "")
            return redirect(destination if destination.startswith("/") and not destination.startswith("//") else url_for("admin"))
        else:
            return render_template("login.html", error="Identifiants incorrects.")

    # si déjà connecté → admin
    if session.get("admin_ok"):
        return redirect(url_for("admin"))
    return render_template("login.html")


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

@app.route("/login-pole", methods=["GET", "POST"])
@app.get("/admin/pole-alternance")
def retired_partner_portal():
    session.pop("polealternance", None)
    return "Cet espace partenaire n’est plus disponible.", 410


@app.route("/admin/reprendre-plus-tard")
def admin_reprendre_plus_tard():
    # 🔐 Même protection que l’admin
    if not require_admin():
        return redirect("/login")

    DATA_DIR = os.getenv("DATA_DIR", "/data")
    DRAFT_PATH = os.path.join(DATA_DIR, "drafts.json")

    drafts = []
    if os.path.exists(DRAFT_PATH):
        try:
            with open(DRAFT_PATH, "r", encoding="utf-8") as f:
                drafts = json.load(f)
        except:
            drafts = []

    # 📌 Connexion DB pour vérifier les candidats existants
    conn = db()
    cur = conn.cursor()

    rows = []
    for d in drafts:
        form = d.get("full_form", {})

        email = form.get("email", "")

        # 🔍 Vérifie si l'email existe dans la table candidats (= inscrit)
        existing = cur.execute(
            "SELECT 1 FROM candidats WHERE email = ?", (email,)
        ).fetchone()

        deja_inscrit = 1 if existing else 0

        rows.append({
            "id": d.get("id"),
            "nom": form.get("nom", "—"),
            "prenom": form.get("prenom", "—"),
            "email": email,
            "tel": form.get("tel", "—"),
            "bts": form.get("bts", "—"),
            "updated_at": d.get("timestamp", "—"),
            "resume_link": d.get("resume_link", "#"),
            "deja_inscrit": deja_inscrit   # 👈 Pour afficher ✔️ / ❌
        })

    return render_template("admin_reprendre_plus_tard.html", rows=rows)



@app.route("/admin/reprendre-plus-tard/delete/<token>", methods=["POST"])
def admin_delete_draft(token):
    if not require_admin():
        abort(403)

    DATA_DIR = os.getenv("DATA_DIR", "/data")
    DRAFT_PATH = os.path.join(DATA_DIR, "drafts.json")

    drafts = []
    if os.path.exists(DRAFT_PATH):
        try:
            with open(DRAFT_PATH, "r", encoding="utf-8") as f:
                drafts = json.load(f)
        except:
            drafts = []

    # supprimer le bon token
    new_drafts = [d for d in drafts if d.get("id") != token]

    # écrire le fichier
    try:
        with open(DRAFT_PATH, "w", encoding="utf-8") as f:
            json.dump(new_drafts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("❌ Erreur écriture drafts.json :", e)
        return jsonify({"ok": False, "error": str(e)}), 500

    print(f"🗑️ Brouillon supprimé : {token}")
    return jsonify({"ok": True})



# =====================================================
# 🎯 Vérifie et ajoute la colonne "souhaite_accompagnement" si manquante
# =====================================================
def ensure_souhaite_accompagnement_field():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]

    if "souhaite_accompagnement" not in cols:
        cur.execute("ALTER TABLE candidats ADD COLUMN souhaite_accompagnement TEXT DEFAULT ''")
        print("🧱 Colonne 'souhaite_accompagnement' ajoutée à la table 'candidats'")

    conn.commit()
    conn.close()


# ---------------- Public: Pré-inscriptions ----------------

def admissions_available():
    portal = get_portal_status()
    manual_closed = portal.get("campaign_year") == ADMISSION_YEAR and portal.get("status") == "closed"
    return campaign_is_open() and not manual_closed


def admission_landing():
    portal = get_portal_status()
    return render_template("admissions_landing.html", title="BTS en alternance · Rentrée 2027", admission_open=admissions_available(), scheduled=not campaign_is_open(), portal_message=portal.get("message", "") if portal.get("campaign_year") == ADMISSION_YEAR else "")


@app.route("/")
def index():
    return admission_landing()


@app.route("/candidature")
def candidature():
    preview = require_admin() and request.args.get("preview") == "1"
    if request.args.get("preview") == "1" and not require_admin():
        return redirect(url_for("login", next="/candidature?preview=1"))
    if not admissions_available() and not preview:
        return redirect(url_for("index"))
    return render_template("index.html", title="Ma candidature BTS · Rentrée 2027", saved_data=None, preview=preview)


register_place_search(app)
register_candidate_access(app, db, lambda *args, **kwargs: send_mail(*args, copy_admin=False, **kwargs))
register_candidate_messages(app, db, lambda *args, **kwargs: send_mail(*args, copy_admin=False, **kwargs), lambda *args, **kwargs: send_sms_brevo(*args, **kwargs), log_event)
register_candidate_documents(app, db, lambda: UPLOAD_DIR, require_admin)
register_candidate_photos(app, db, lambda: UPLOAD_DIR, require_admin, log_event)
register_student_cards(app, db, lambda: UPLOAD_DIR, require_admin)
candidate_workflow_response = register_candidate_workflows(
    app, db, lambda *args, **kwargs: send_mail(*args, **kwargs),
    lambda *args, **kwargs: send_sms_brevo(*args, **kwargs), log_event,
    lambda status: campaign_rows(status))
register_daily_login(app)
register_promotions(app, db, require_admin)
register_trainer_access(app, db, lambda *args, **kwargs: send_mail(*args, copy_admin=False, **kwargs), require_admin)
register_planning(app, db, require_admin)
register_planning_portal(app, db)
register_company_portal(app, db, lambda *args, **kwargs: send_mail(*args, copy_admin=False, **kwargs), require_admin)
register_trainer_availability(app, db, lambda *args, **kwargs: send_mail(*args, copy_admin=False, **kwargs))
register_admin_trainer_planning(app, db, require_admin)
register_planning_sync(app, db, require_admin)


@app.route("/ouverture.ics")
def opening_calendar():
    content = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Integrale Academy//Admissions//FR",
        "BEGIN:VEVENT", "UID:bts-2027-opening@integraleacademy.com", "DTSTAMP:20261024T000000Z",
        "DTSTART:20261201T090000Z", "DTEND:20261201T093000Z",
        "SUMMARY:Ouverture des inscriptions BTS 2027 - Integrale Academy",
        "DESCRIPTION:Candidatez sur https://inscriptionsbts.onrender.com/",
        "URL:https://inscriptionsbts.onrender.com/", "END:VEVENT", "END:VCALENDAR", ""
    ])
    return content, 200, {"Content-Type": "text/calendar; charset=utf-8", "Content-Disposition": "attachment; filename=ouverture-bts-2027.ics"}


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
    if not admissions_available():
        return jsonify(success=False, error=f"Les inscriptions ouvriront le {OPENING_LABEL}."), 403
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Aucune donnée reçue"}), 400

        # 🔥 On sauvegarde TOUT, absolument tout :
        # tous les champs text, select, radios, checkboxes, etc.
        full_form = data.get("full_form", {})
        if not isinstance(full_form, dict) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(full_form.get("email", ""))):
            return jsonify(success=False, error="Indiquez une adresse e-mail valide pour recevoir votre lien de reprise."), 400
        if str(full_form.get("admin_preview", "")) == "1":
            return jsonify(success=False, error="Cet aperçu ne permet pas d’enregistrer un brouillon."), 403
        normalize_candidate_names(full_form)
        full_form["rentree_annee"] = ADMISSION_YEAR

        # 🔑 Id unique du brouillon (token)
        token = new_token()

        # 🔗 Lien de reprise
        resume_link = f"{request.url_root.rstrip('/')}/reprendre/{token}"

        # 🗂 Enregistrement complet du formulaire
        draft_data = {
            "id": token,
            "resume_link": resume_link,
            "full_form": full_form,
            "timestamp": datetime.now().isoformat()
        }

        DATA_FILE = os.path.join(DATA_DIR, "drafts.json")
        all_drafts = []

        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    all_drafts = json.load(f)
            except:
                all_drafts = []

        all_drafts.append(draft_data)

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(all_drafts, f, indent=2, ensure_ascii=False)

        # 💌 Mail de reprise
        send_mail(
            full_form.get("email", ""),
            "Reprenez votre pré-inscription – Intégrale Academy",
            mail_html(
                "reprendre_plus_tard",
                prenom=full_form.get("prenom", ""),
                bts_label=full_form.get("bts", "BTS"),
                lien_espace=resume_link
            )
        )

        print(f"🟢 Brouillon complet enregistré — {resume_link}")
        return jsonify({"success": True, "link": resume_link})

    except Exception as e:
        print(f"❌ Erreur /save_draft : {e}")
        return jsonify({"success": False, "error": str(e)}), 500




# =====================================================
# 🔁 ROUTE DE REPRISE DU FORMULAIRE
# =====================================================
@app.route("/reprendre/<token>")
def reprendre_formulaire(token):
    if not admissions_available():
        return redirect(url_for("index"))
    DRAFT_PATH = os.path.join(DATA_DIR, "drafts.json")

    if not os.path.exists(DRAFT_PATH):
        abort(404)

    # 📂 Charger le fichier drafts.json
    try:
        with open(DRAFT_PATH, "r", encoding="utf-8") as f:
            drafts = json.load(f)
    except:
        drafts = []

    draft = next((d for d in drafts if d.get("id") == token), None)
    if not draft:
        abort(404)

    saved_full_form = draft.get("full_form", {})
    if saved_full_form.get("rentree_annee") != ADMISSION_YEAR:
        flash("Ce brouillon concerne une ancienne rentrée. Commencez une nouvelle candidature pour septembre 2027.", "info")
        return redirect(url_for("candidature"))

    # 💥 On injecte TOUT dans la page
    return render_template(
        "index.html",
        saved_data=saved_full_form,   # <--- ici : les données
        step=1,
        portal_closed=False
    )


def validate_application(form, files):
    required = ("nom", "prenom", "sexe", "date_naissance", "ville_naissance", "cp_naissance", "pays_naissance", "nationalite", "email", "email_confirm", "tel", "adresse", "cp", "ville", "num_secu", "baccalaureat", "bac_type", "permis_b", "projet_pourquoi", "projet_objectif", "projet_passions")
    if any(not (form.get(k) or "").strip() for k in required):
        return "Complétez les champs obligatoires avant d’envoyer votre candidature."
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", form.get("email", "")) or form.get("email", "").lower() != form.get("email_confirm", "").lower():
        return "Les deux adresses e-mail doivent être valides et identiques."
    if form.get("bts") not in {"MOS", "MCO", "NDRC", "PI", "CI", "CG"} or form.get("mode") not in {"presentiel", "distanciel"}:
        return "Choisissez votre BTS et votre mode de formation."
    if form.get("sexe") not in ("Homme", "Femme"):
        return "Précisez le sexe indiqué sur votre état civil."
    if not re.fullmatch(r"0[1-9]\d{8}", form.get("tel", "")):
        return "Indiquez un numéro de téléphone français à 10 chiffres."
    try:
        birth = datetime.strptime(form["date_naissance"], "%Y-%m-%d").date()
        today = datetime.now().date()
        if birth >= today:
            return "Vérifiez votre date de naissance."
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        if age < 18 and any(not form.get(k, "").strip() for k in ("resp_nom", "resp_prenom", "resp_email", "resp_tel")):
            return "Les coordonnées de votre responsable légal sont obligatoires."
        if age < 18 and (not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", form.get("resp_email", "")) or not re.fullmatch(r"0[1-9]\d{8}", form.get("resp_tel", ""))):
            return "Vérifiez l’e-mail et le téléphone de votre responsable légal."
    except ValueError:
        return "Vérifiez votre date de naissance."
    valid, message = validate_nir(form["num_secu"], form["date_naissance"], form["sexe"])
    if not valid and form["num_secu"] != "123456789123456":
        return message
    if form.get("bts") == "MOS":
        if form.get("mos_parcours") not in {"bac_pro_ms", "bac_pro_ms_en_cours", "carte_cnaps", "autre"}:
            return "Précisez votre situation pour le BTS MOS."
        if form.get("mos_parcours") == "autre" and form.get("aps_souhaitee") not in {"oui", "non"}:
            return "Précisez votre souhait concernant la formation APS."
    if form.get("bac_type") == "Autre" and not form.get("bac_autre", "").strip():
        return "Précisez votre type de baccalauréat."
    for key in ("entreprise_trouvee", "recherches_commencees", "cherche_idf"):
        if form.get(key) not in ("oui", "non"):
            return "Complétez les réponses concernant votre recherche d’entreprise."
    if form.get("bts") == "MOS" and form.get("mos_parcours") == "autre" and form.get("aps_souhaitee") == "non" and not form.get("raison_aps", "").strip():
        return "Précisez la solution envisagée pour la formation APS."
    for group in PROFILE_GROUPS:
        selected = form.getlist(group["name"] + "[]")
        if not selected or any(value not in dict(group["options"]) for value in selected):
            return "Sélectionnez au moins une réponse dans chaque partie du projet motivé."
    if form.get("consent") != "1":
        return "Confirmez l’exactitude de vos informations."
    allowed = {"ci": {"pdf", "jpg", "jpeg", "png"}, "ci2": {"pdf", "jpg", "jpeg", "png"}, "photo": {"jpg", "jpeg", "png"}, "carte_vitale": {"pdf"}, "cv": {"pdf"}, "lm": {"pdf"}}
    for key, extensions in allowed.items():
        file = files.get(key)
        if not file or not file.filename:
            if key != "ci2":
                return "Ajoutez tous les justificatifs obligatoires."
            continue
        extension = file.filename.rsplit(".", 1)[-1].lower()
        file.seek(0, 2); size = file.tell(); file.seek(0)
        if extension not in extensions or not 0 < size <= 8 * 1024 * 1024:
            return "Un justificatif a un format non accepté ou dépasse 8 Mo."
        if key in ("carte_vitale", "cv", "lm") and size < 10 * 1024:
            return "Un PDF semble vide ou incomplet (moins de 10 Ko). Transmettez un document lisible."
        header = file.read(8); file.seek(0)
        if (extension == "pdf" and not header.startswith(b"%PDF-")) or (extension in ("jpg", "jpeg") and not header.startswith(b"\xff\xd8")) or (extension == "png" and not header.startswith(b"\x89PNG\r\n\x1a\n")):
            return "Le contenu d’un justificatif ne correspond pas à son format. Vérifiez le fichier."
    return None


@app.route("/submit", methods=["POST"])
def submit():
    from datetime import date  # ✅ import ici (ou mets-le en haut du fichier)

    if request.form.get("admin_preview") == "1":
        return jsonify(ok=False, error="Cet aperçu ne permet pas de déposer un dossier."), 403
    if not admissions_available():
        return jsonify(ok=False, error=f"Les inscriptions ouvriront le {OPENING_LABEL}."), 403
    form = normalize_candidate_names(request.form.copy())
    error = validate_application(form, request.files)
    if error:
        return jsonify(ok=False, error=error), 400
    conn = db()
    cur = conn.cursor()
    counter = get_counter_for_today(conn)
    numero = dossier_number(counter=counter, year=ADMISSION_YEAR)

    # === Normalisation du BAC ===
    baccalaureat = (form.get("baccalaureat") or "").strip()

    # === Projet motivé : nouveaux champs ===
    projet_pourquoi = (form.get("projet_pourquoi") or "").strip()
    projet_objectif = (form.get("projet_objectif") or "").strip()
    projet_passions = (form.get("projet_passions") or "").strip()

    # Cases à cocher
    qualites_list = request.form.getlist("qualites[]")
    motivation_list = request.form.getlist("motivation[]")
    valeurs_list = request.form.getlist("valeurs[]")
    travail_list = request.form.getlist("travail[]")

    projet_qualites = ", ".join(qualites_list)
    projet_motivation = ", ".join(motivation_list)
    projet_recherche = ", ".join(valeurs_list)
    projet_travail = ", ".join(travail_list)

    # === APS (sessions datées) ===
    aps_souhaitee = 1 if form.get("aps_souhaitee") == "oui" else 0
    aps_session_value = (form.get("aps_session") or "").strip()
    aps_session_other = (form.get("aps_session_other") or "").strip()
    raison_aps = (form.get("raison_aps") or "").strip()

    aps_session = "Calendrier 2027 à confirmer avec l’équipe" if aps_souhaitee else ""


    entreprise_trouvee = (form.get("entreprise_trouvee") or "").strip()
    recherches_commencees = (form.get("recherches_commencees") or "").strip()
    souhaite_accompagnement = ""  # Retired partner programme; keep historical database values.

    # 🎯 Vérification du numéro de sécurité sociale
    nir = form.get("num_secu", "").strip()
    date_naiss = form.get("date_naissance", "")
    sexe = form.get("sexe", "")

    # 🔞 Calcul automatique : mineur ou non
    est_mineur = 0
    try:
        naissance = datetime.strptime(date_naiss, "%Y-%m-%d").date()
        today = date.today()
        age = today.year - naissance.year - (
            (today.month, today.day) < (naissance.month, naissance.day)
        )
        if age < 18:
            est_mineur = 1
    except Exception:
        est_mineur = 0

    # 👤 Responsable légal (si mineur)
    resp_nom = (form.get("resp_nom") or "").strip()
    resp_prenom = (form.get("resp_prenom") or "").strip()
    resp_email = (form.get("resp_email") or "").strip()
    resp_tel = (form.get("resp_tel") or "").strip()

    # ✅ Maintenant seulement : form_overrides (car est_mineur/resp_* existent)
    form_overrides = {
        "rentree_annee": ADMISSION_YEAR,
        "permis_b": int(form.get("permis_b") == "Oui"),
        "mos_parcours": form.get("mos_parcours", ""),
        "projet_pourquoi": projet_pourquoi,
        "projet_objectif": projet_objectif,
        "projet_passions": projet_passions,
        "projet_qualites": projet_qualites,
        "projet_motivation": projet_motivation,
        "projet_recherche": projet_recherche,
        "projet_travail": projet_travail,

        # APS
        "aps_souhaitee": aps_souhaitee,
        "aps_session": aps_session,
        "raison_aps": raison_aps,
        "label_aps": aps_souhaitee,

        # Bac / apprentissage
        "bac_status": baccalaureat,
        "entreprise_trouvee": entreprise_trouvee,
        "recherches_commencees": recherches_commencees,
        "baccalaureat": baccalaureat,
        "souhaite_accompagnement": souhaite_accompagnement,

        # Mineur / responsable légal
        "est_mineur": est_mineur,
        "resp_nom": resp_nom,
        "resp_prenom": resp_prenom,
        "resp_email": resp_email,
        "resp_tel": resp_tel,
    }

    # 👍 Exception : ce numéro doit passer même s'il est invalide
    if nir == "123456789123456":
        print("⚠️ Bypass NIR activé pour un cas particulier (123456789123456)")
    else:
        ok, msg = validate_nir(nir, date_naiss, sexe)
        if not ok:
            flash(msg, "error")
            return redirect(request.referrer or url_for("index"))

    # 🧩 Création du candidat
    cand_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    # 📎 Sauvegarde des fichiers
    fichiers_ci = save_files("ci", cand_id) + save_files("ci2", cand_id)
    fichiers_photo = save_files("photo", cand_id)
    fichiers_carte_vitale = save_files("carte_vitale", cand_id)
    fichiers_cv = save_files("cv", cand_id)
    fichiers_lm = save_files("lm", cand_id)

    token_confirm = new_token()
    token_confirm_exp = (datetime.now() + timedelta(days=30)).isoformat()

    cur.execute("PRAGMA table_info(candidats)")
    cols = [r[1] for r in cur.fetchall()]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO candidats ({','.join(cols)}) VALUES ({placeholders})"

    values = []
    for c in cols:
        if c == "id":
            values.append(cand_id)
        elif c == "numero_dossier":
            values.append(numero)
        elif c in ("created_at", "updated_at"):
            values.append(now)
        elif "fichiers" in c:
            mapping = {
                "fichiers_ci": fichiers_ci,
                "fichiers_photo": fichiers_photo,
                "fichiers_carte_vitale": fichiers_carte_vitale,
                "fichiers_cv": fichiers_cv,
                "fichiers_lm": fichiers_lm,
            }
            values.append(json.dumps(mapping.get(c, [])))
        elif "verif_docs" in c or "replace_meta" in c:
            values.append("{}")
        elif c == "nouveau_doc":
            values.append(0)
        elif c in ("permis_b", "est_mineur"):
            values.append(int(form_overrides.get(c, 0)))
        elif "label" in c:
            values.append(form_overrides.get(c, 0))
        elif c == "statut":
            values.append("preinscription")
        elif c == "token_confirm":
            values.append(token_confirm)
        elif c == "token_confirm_exp":
            values.append(token_confirm_exp)
        elif c in ("token_reconfirm", "token_reconfirm_exp", "commentaires"):
            values.append("")
        elif c == "slug_public":
            values.append("")
        else:
            values.append(form_overrides.get(c, form.get(c, "")))

    cur.execute(sql, tuple(values))
    conn.commit()

    # 🧾 Logs et mails
    candidat = {
        "id": cand_id,
        "numero_dossier": numero,
        "email": form.get("email", ""),
        "prenom": form.get("prenom", "")
    }
    log_event(candidat, "PREINSCRIPTION_RECU", {"email": candidat["email"]})

    cur.execute("SELECT slug_public FROM candidats WHERE id=?", (cand_id,))
    row = cur.fetchone()
    slug = row[0] if row and row[0] else uuid.uuid4().hex[:10]
    if not row or not row[0]:
        cur.execute("UPDATE candidats SET slug_public=? WHERE id=?", (slug, cand_id))
        conn.commit()

    lien_espace = url_for("espace_candidat", slug=slug, _external=True)

    # 🔹 Préparation des libellés pour le mail
    bts_code = (form.get("bts") or "").strip().upper()
    bts_label = BTS_LABELS.get(bts_code, form.get("bts"))

    mode_raw = form.get("mode", "") or ""
    if "dist" in mode_raw.lower():
        mode_label_email = "💻 À distance 100% en ligne (visioconférence)"
    else:
        mode_label_email = "🏫 En présentiel à Puget-sur-Argens (Var, 83)"

    # ✉️ Mail accusé de réception
    html = mail_html(
        "accuse_reception",
        rentree_annee=ADMISSION_YEAR,
        prenom=form.get("prenom", ""),
        bts_label=bts_label,
        lien_espace=lien_espace,

        numero_dossier=numero,
        form_nom=form.get("nom", ""),
        form_prenom=form.get("prenom", ""),
        form_email=form.get("email", ""),
        form_tel=form.get("tel", ""),
        form_mode_label=mode_label_email,
    )
    send_mail(form.get("email", ""), "Nous avons bien reçu votre pré-inscription – Intégrale Academy", html)

    # SMS accusé réception
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
    log_event(candidat, "MAIL_ENVOYE", {"type": "accuse_reception"})

    # Notification email to the admin inbox disabled on request.

    if request.accept_mimetypes.best == "application/json":
        return jsonify(ok=True, redirect=lien_espace)
    return redirect(lien_espace)








# ---------------- Admin ----------------

def _admin_filtered_rows(args):
    q = args.get("q", "").strip().lower()
    flt_year = args.get("rentree", str(ADMISSION_YEAR))
    flt_bts = args.get("bts", "")
    flt_statut = args.get("statut", "")
    flt_mode = args.get("mode", "")
    flt_label = args.get("label", "")
    flt_relance = args.get("relances", "")
    flt_carte_manquante = args.get("carte_etudiante_manquante", "")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    def is_checked(value):
        return value in (1, "1", True, "true", "True", "on", "yes")

    def match(row):
        ok = flt_year == "all" or str(candidate_year(row)) == flt_year
        if q:
            blob = " ".join([str(row.get(k, "")) for k in ("nom", "prenom", "email", "tel", "bts", "numero_dossier")]).lower()
            ok &= q in blob
        if flt_bts:
            ok &= row.get("bts", "") == flt_bts
        if flt_statut and not flt_carte_manquante:
            ok &= row.get("statut", "") == flt_statut
        if flt_mode:
            ok &= row.get("mode", "") == flt_mode
        if flt_relance:
            ok &= row.get("last_relance") not in (None, "", "null")
        if flt_carte_manquante:
            ok &= row.get("statut", "") == "confirmee"
            ok &= not is_checked(row.get("label_carte_etudiante"))
        if flt_label == "APS":
            ok &= is_checked(row.get("label_aps", 0))
        if flt_label == "AUT":
            ok &= is_checked(row.get("label_aut_ok", 0))
        if flt_label == "CHEQUE":
            ok &= is_checked(row.get("label_cheque_ok", 0))
        return ok

    return [r for r in rows if match(r)]


@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("login"))

    rows = _admin_filtered_rows(request.args)
    return render_template("admin.html", title="Plateforme de gestion des BTS", rows=rows, statuts=STATUTS)


@app.route("/admin/candidat/<cid>")
def admin_candidate_sheet(cid):
    if not require_admin():
        return redirect(url_for("login", next=request.full_path))
    with closing(db()) as conn:
        row = get_candidat(conn, cid)
        if row:
            current_promotion = get_candidate_promotion(conn, cid)
            available_promotions = list_promotions(conn, bts=row.get('bts'), rentree_annee=candidate_year(row), active_only=True)
    if not row: abort(404)
    year = candidate_year(row)
    columns = {"qualites": "projet_qualites", "motivation": "projet_motivation", "valeurs": "projet_recherche", "travail": "projet_travail"}
    profile_display = {g["name"]: [dict(g["options"]).get(v, v) for v in (parse_list(row.get(columns[g["name"]])) or [v.strip() for v in (row.get(columns[g["name"]]) or "").split(",") if v.strip()])] for g in PROFILE_GROUPS}
    return render_template("candidate_sheet.html", current_promotion=current_promotion, available_promotions=available_promotions, candidate_photo_url=url_for('admin_candidate_photo', cid=cid) if parse_list(row.get('fichiers_photo')) else None, profile_display=profile_display, title=f"{row.get('prenom', '')} {row.get('nom', '')} · Plateforme de gestion des BTS", row=row, statuts=STATUTS, year=year, student_card_dates=student_card_dates(row))


@app.post("/admin/candidat/<cid>/informations")
def admin_candidate_information(cid):
    if not require_admin(): abort(403)
    data = request.get_json(silent=True) or {}
    fields = {"nom", "prenom", "email", "tel", "bts", "mode", "adresse", "cp", "ville", "sexe", "date_naissance", "ville_naissance", "cp_naissance", "pays_naissance", "nationalite", "num_secu", "resp_nom", "resp_prenom", "resp_email", "resp_tel", "baccalaureat", "bac_type", "bac_autre", "entreprise_trouvee", "recherches_commencees", "cherche_idf", "souhaite_accompagnement"}
    changes = {key: str(value or "").strip() for key, value in data.items() if key in fields}
    normalize_candidate_names(changes)
    if not changes: return jsonify(ok=False, error="Aucune modification à enregistrer."), 400
    with closing(db()) as conn:
        ensure_promotions_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        row = get_candidat(conn, cid)
        if not row: abort(404)
        merged = {**row, **changes}
        if merged.get("bts") not in BTS_LABELS or merged.get("mode") not in ("presentiel", "distanciel"):
            return jsonify(ok=False, error="Vérifiez la formation et son mode de suivi."), 400
        placement = get_candidate_promotion(conn, cid)
        if placement and merged.get('bts') != placement['bts']:
            return jsonify(ok=False, error="Retirez d’abord la promotion de cet étudiant avant de changer son BTS, puis affectez-lui une promotion du nouveau BTS."), 409
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", merged.get("email") or "") or not re.fullmatch(r"0[1-9]\d{8}", merged.get("tel") or ""):
            return jsonify(ok=False, error="Vérifiez l’e-mail et le téléphone."), 400
        if {"num_secu", "date_naissance", "sexe"}.intersection(changes) and merged.get("num_secu") and merged["num_secu"] != "123456789123456":
            ok, message = validate_nir(merged["num_secu"], merged.get("date_naissance"), merged.get("sexe"))
            if not ok: return jsonify(ok=False, error=message), 400
        changed = {key: value for key, value in changes.items() if str(row.get(key) or "") != value}
        if changed:
            conn.execute("UPDATE candidats SET " + ", ".join(key + "=?" for key in changed) + ", updated_at=? WHERE id=?", [*changed.values(), datetime.now().isoformat(), cid])
            conn.commit()
    if changed: log_event(row, "FICHE_MODIFIEE", {"champs": list(changed)})
    return jsonify(ok=True)


@app.post('/admin/candidat/<cid>/parcours')
def admin_candidate_mode(cid):
    from candidate_messages import _equal
    if not require_admin(): abort(403)
    if not _equal(request.headers.get('X-CSRF-Token'), session.get('_candidate_message_csrf')):
        return jsonify(ok=False, error='La session a expiré. Rechargez la fiche.'), 400
    data = request.get_json(silent=True) or {}
    mode = data.get('mode')
    if mode not in ('presentiel', 'distanciel'):
        return jsonify(ok=False, error='Choisissez Présentiel ou Distanciel.'), 400
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = get_candidat(conn, cid)
        if not row: abort(404)
        conn.execute('UPDATE candidats SET mode=?,updated_at=? WHERE id=?', (mode, datetime.now().isoformat(), cid))
        conn.commit()
    if row.get('mode') != mode:
        log_event(row, 'PARCOURS_MODIFIE', {'ancien': row.get('mode'), 'nouveau': mode})
    return jsonify(ok=True, mode=mode)


@app.get('/admin/candidat/<cid>/certificat.pdf')
def admin_candidate_certificate(cid):
    return _certificate_pdf_response(cid)


def _certificate_pdf_response(cid):
    from io import BytesIO
    from certificates import certificate_pdf
    if not require_admin(): abort(403)
    with closing(db()) as conn:
        row = get_candidat(conn, cid)
    if not row: abort(404)
    try:
        content = certificate_pdf(row)
    except ValueError as exc:
        return str(exc), 400
    response = send_file(BytesIO(content), mimetype='application/pdf',
                         download_name=f'Certificat_scolarite_{cid}_{row["mode"]}.pdf',
                         as_attachment=request.args.get('download') == '1')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def campaign_rows(statut=None):
    args = {"rentree": request.args.get("rentree", str(ADMISSION_YEAR))}
    if statut:
        args["statut"] = statut
    return _admin_filtered_rows(args)


@app.get("/api/kpi")
def api_kpi():
    if not require_admin():
        abort(403)
    stats = {key: 0 for key, _, _ in STATUTS}
    for row in _admin_filtered_rows({"rentree": request.args.get("rentree", str(ADMISSION_YEAR))}):
        if row.get("statut") in stats:
            stats[row["statut"]] += 1
    return jsonify(stats)

# =====================================================
# 🔁 API JSON – Liste simplifiée des candidats pour refresh auto
# =====================================================
@app.route("/admin/json")
def admin_json():
    if not require_admin():
        abort(403)
    rows = _admin_filtered_rows(request.args)
    keys = ("id", "nom", "prenom", "bts", "mode", "tel", "email", "statut", "created_at", "rentree_annee")
    return jsonify(ok=True, rows=[{k: r.get(k) for k in keys} for r in rows])

# =====================================================
# ⚡ API JSON – Détail d'une ligne candidat (refresh dynamique)
# =====================================================
@app.route("/admin/row/<cid>")
def admin_row(cid):
    if not require_admin():
        abort(403)
    conn = db()
    row = conn.execute("SELECT * FROM candidats WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return jsonify(ok=False, error="Candidat introuvable"), 404

    row = dict(row)

    # ✅ Indique au front si le candidat a la carte étudiante cochée
    row["has_badge_carte"] = bool(
    row.get("label_carte_etudiante")
    or row.get("label_carte_ok")
    or row.get("carte_etudiante")
)

    # 🔹 Liste des statuts disponibles pour le <select>
    statuts = [{"key": s[0], "label": s[1]} for s in STATUTS]

    return jsonify(ok=True, row=row, statuts=statuts)


@app.route("/admin/update-field", methods=["POST"])
def admin_update_field():
    if not require_admin():
        abort(403)

    data = request.get_json(force=True)
    cid = data.get("id")
    field = data.get("field")
    value = data.get("value")

    allowed = [
        "nom", "prenom", "bts", "mode", "tel", "email",
        "label_aps", "label_aut_ok", "label_cheque_ok",
        "label_carte_etudiante",
        "commentaires", "nouveau_doc"
    ]

    if field not in allowed:
        return jsonify({"ok": False, "error": "Champ non autorisé"}), 400

    try:
        # 🧩 On garde le type exact selon le champ
        if field.startswith("label_"):
            # c’est une case à cocher → booléen
            value = 1 if str(value).lower() in ("true", "1", "on", "yes") else 0
        else:
            # c’est un champ texte
            value = str(value).strip()

        conn = db()
        if field == 'bts':
            value = value.upper()
            if value not in BTS_LABELS:
                conn.close()
                return jsonify(ok=False, error="Choisissez un BTS valide."), 400
            ensure_promotions_schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            placement = get_candidate_promotion(conn, cid)
            if placement and value != placement['bts']:
                conn.close()
                return jsonify(ok=False, error="Retirez d’abord la promotion de cet étudiant avant de changer son BTS."), 409
        cur = conn.cursor()
        cur.execute(f"UPDATE candidats SET {field}=?, updated_at=? WHERE id=?",
                    (value, datetime.now().isoformat(), cid))
        conn.commit()

        print(f"🟢 UPDATE-FIELD: id={cid}, field={field}, value={value}")

        # Log interne
        cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
        row = dict(cur.fetchone())
        log_event(row, "FIELD_UPDATE", {"field": field, "value": value})

        conn.close()
        return jsonify({"ok": True, "value": value})

    except Exception as e:
        print("❌ Erreur update-field :", e)
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/admin/update-status", methods=["POST"])
def admin_update_status():
    return candidate_workflow_response("status")






@app.route("/admin/print/<cid>")
def admin_print(cid):
    if not require_admin(): abort(403)
    from weasyprint import HTML
    from io import BytesIO
    with closing(db()) as conn:
        result = conn.execute("SELECT * FROM candidats WHERE id=?", (cid,)).fetchone()
    if not result: abort(404)
    row = dict(result)
    html = render_template("pdf_fiche.html", row=row, now=datetime.now())
    pdf = HTML(string=html, base_url=url_for('index', _external=True)).write_pdf()
    fname = f"fiche_{row.get('numero_dossier','')}.pdf"
    log_event(row, "PDF_GENERE", {"file": fname})
    response = send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=False, download_name=fname)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route("/admin/delete/<cid>", methods=["POST"])
def admin_delete(cid):
    if not require_admin(): abort(403)
    conn = db()
    ensure_promotions_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE id=?", (cid,))
    row = cur.fetchone()
    if row:
        row = dict(row)
        cur.execute("DELETE FROM student_promotions WHERE candidate_id=?", (cid,))
        cur.execute("DELETE FROM student_promotion_history WHERE candidate_id=?", (cid,))
        cur.execute("DELETE FROM candidats WHERE id=?", (cid,))
        conn.commit()
        log_event(row, "FICHE_SUPPRIMEE", {})
    conn.close()
    return jsonify({"ok":True})

@app.route("/admin/export.csv")
def admin_export_csv():
    if not require_admin(): abort(403)
    import csv, io
    rows = _admin_filtered_rows(request.args)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return buf.getvalue(), 200, {"Content-Type":"text/csv; charset=utf-8", "Content-Disposition":"attachment; filename=export.csv"}


@app.route("/admin/export-filtered.xlsx")
def admin_export_filtered_xlsx():
    if not require_admin(): abort(403)
    from io import BytesIO
    from openpyxl import Workbook

    rows = _admin_filtered_rows(request.args)
    headers = list(rows[0].keys()) if rows else [
        "id", "created_at", "numero_dossier", "nom", "prenom", "email", "tel",
        "bts", "mode", "statut", "last_relance"
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Export filtré"
    ws.append(headers)

    for row in rows:
        ws.append([row.get(header, "") for header in headers])

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 45)

    out = BytesIO()
    wb.save(out)
    out.seek(0)

    return (
        out.getvalue(),
        200,
        {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": "attachment; filename=export_admin_filtre.xlsx"
        },
    )

@app.route("/admin/export.json")
def admin_export_json():
    if not require_admin(): abort(403)
    rows = _admin_filtered_rows(request.args)
    return jsonify(rows)

@app.route("/admin/export-confirmed.xlsx")
def admin_export_confirmed_xlsx():
    if not require_admin(): abort(403)
    import re
    from io import BytesIO
    from openpyxl import Workbook

    def format_nom(v: str) -> str:
        return (v or "").strip().upper()

    def format_prenom(v: str) -> str:
        raw = (v or "").strip().lower()
        if not raw:
            return ""
        return " ".join(part[:1].upper() + part[1:] for part in raw.split())

    def format_tel(v: str) -> str:
        digits = re.sub(r"\D", "", v or "")
        if len(digits) == 10 and digits.startswith("0"):
            return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
        return (v or "").strip()

    rows = campaign_rows("confirmee")

    wb = Workbook()
    ws = wb.active
    ws.title = "Inscriptions confirmées"

    headers = ["Nom", "Prénom", "Mail", "Téléphone", "Formation choisie", "Mode de suivi"]
    ws.append(headers)

    for row in rows:
        ws.append([
            format_nom(row.get("nom", "")),
            format_prenom(row.get("prenom", "")),
            row.get("email", ""),
            format_tel(row.get("tel", "")),
            row.get("bts", ""),
            row.get("mode", "")
        ])

    out = BytesIO()
    wb.save(out)
    out.seek(0)

    return (
        out.getvalue(),
        200,
        {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": "attachment; filename=inscriptions_confirmees.xlsx"
        },
    )

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
    return _certificate_legacy_response(id)


# =====================================================
# 🏫 CERTIFICAT DE SCOLARITÉ PRÉSENTIEL
# =====================================================
@app.route("/admin/generate_certificat_presentiel/<id>")
def admin_generate_certificat_presentiel(id):
    return _certificate_legacy_response(id)


def _certificate_legacy_response(cid):
    if request.args.get('preview') == '1':
        return _certificate_pdf_response(cid)
    from io import BytesIO
    from certificates import certificate_word
    if not require_admin(): abort(403)
    with closing(db()) as conn:
        row = get_candidat(conn, cid)
    if not row: abort(404)
    try:
        out = BytesIO()
        certificate_word(row).save(out)
        out.seek(0)
    except ValueError as exc:
        return str(exc), 400
    response = send_file(out, as_attachment=True, download_name=f'Certificat_scolarite_{cid}_{row["mode"]}.docx',
                         mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response.headers['Cache-Control'] = 'private, no-store'
    return response





# =====================================================
# ✉️ ENVOI DU CERTIFICAT DE SCOLARITÉ PAR MAIL
# =====================================================
@app.route("/admin/send_certificat/<id>", methods=["POST"])
def admin_send_certificat(id):
    return candidate_workflow_response("certificate", id)


# =====================================================
# ✉️ ENVOI DU CERTIFICAT DE SCOLARITÉ PRÉSENTIEL PAR MAIL
# =====================================================
@app.route("/admin/send_certificat_presentiel/<id>", methods=["POST"])
def admin_send_certificat_presentiel(id):
    return candidate_workflow_response("certificate", id)


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
        WHERE candidat_id=? OR cid=?
        ORDER BY datetime(created_at) DESC
    """, (cid, cid))
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

    for item in unique_files:
        item['url'] = url_for('admin_candidate_document', cid=cid, filename=item['filename'])
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
    return candidate_workflow_response("notify")

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
        # 🧹 Suppression automatique du badge relance si le candidat a renvoyé ses documents
    try:
        cur.execute("UPDATE candidats SET last_relance=NULL WHERE id=?", (row["id"],))
        conn.commit()
        print(f"🧹 Badge relance supprimé pour {row['prenom']} {row['nom']} (nouveaux docs reçus)")
    except Exception as e:
        print("⚠️ Erreur suppression badge relance (replace-files):", e)

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
    import hmac
    if not query_token or len(query_token) > 512 or not re.fullmatch(r'[0-9a-f]{64}', query_sig or ''):
        return False
    return hmac.compare_digest(sign_token(query_token), query_sig) or verify_legacy_link(db, query_token, query_sig)


@app.route("/confirm-inscription", methods=["GET", "POST"])
def confirm_inscription():

    # -------------------- GET --------------------
    if request.method == "GET":
        token = request.args.get("token", "")
        sig = request.args.get("sig", "")

        if not verify_token(token, sig):
            abort(403)

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM candidats WHERE token_confirm=?", (token,))
        row = cur.fetchone()

        if not row:
            abort(404)

        row = dict(row)

        # 🛑 L'utilisateur a déjà confirmé son inscription
        if row.get("statut") == "confirmee":
            return render_template(
                "confirm_inscription.html",
                title="Inscription déjà confirmée",
                row=row,
                token=token,
                sig=sig,
                deja=True
            )

        # 🎓 Nom complet du BTS
        bts_label = BTS_LABELS.get(
            (row.get("bts") or "").strip().upper(),
            row.get("bts")
        )

        return render_template(
            "confirm_inscription.html",
            title="Confirmer mon inscription",
            row=row,
            token=token,
            sig=sig,
            bts_label=bts_label
        )


    # -------------------- POST --------------------
    token = request.form.get("token", "")
    sig = request.form.get("sig", "")

    if not verify_token(token, sig):
        abort(403)

    c1 = request.form.get("c1") == "on"
    c2 = request.form.get("c2") == "on"
    c3 = request.form.get("c3") == "on"

    if not (c1 and c2 and c3):
        flash("Merci de cocher les 3 cases obligatoires.", "error")
        return redirect(request.referrer or url_for("index"))

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE token_confirm=?", (token,))
    row = dict(cur.fetchone())

    # ➕ Mise à jour du statut
    cur.execute(
        "UPDATE candidats SET statut=?, updated_at=? WHERE id=?",
        ("confirmee", datetime.now().isoformat(), row["id"])
    )
    conn.commit()

    # 🧹 Suppression badge relance
    try:
        cur.execute("UPDATE candidats SET last_relance=NULL WHERE id=?", (row["id"],))
        conn.commit()
    except Exception as e:
        print("⚠️ Erreur suppression badge relance :", e)

    # ---------------------- MAILS ----------------------
    mode_raw = (row.get("mode") or "").lower()

    if "pres" in mode_raw:
        mode_label = "En présentiel (Puget sur Argens, Var)"
    else:
        mode_label = "100% en ligne à distance en visioconférence ZOOM"

    # 👉 Construire lien espace candidat
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    slug = row.get("slug_public")
    lien_espace = f"{BASE_URL}/espace/{slug}"

    html = mail_html(
        "inscription_confirmee",
        rentree_annee=candidate_year(row),
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts")),
        numero_dossier=row.get("numero_dossier", ""),
        form_nom=row.get("nom", ""),
        form_prenom=row.get("prenom", ""),
        form_email=row.get("email", ""),
        form_tel=row.get("tel", ""),
        form_mode_label=mode_label,
        lien_espace=lien_espace   # 👈 ESSENTIEL
    )
    send_mail(row.get("email", ""), "Inscription confirmée – Intégrale Academy", html)

    log_event(row, "MAIL_ENVOYE", {"type": "inscription_confirmee"})
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

# =====================================================
# 🔁 PAGE PUBLIQUE – Reconfirmation manuelle (avec bouton)
# =====================================================

@app.route("/reconfirm-page")
def reconfirm_page():
    token = request.args.get("token", "")
    sig = request.args.get("sig", "")
    if not verify_token(token, sig):
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE token_reconfirm=?", (token,))
    row = cur.fetchone()
    conn.close()
    if not row:
        abort(404)

    row = dict(row)
    prenom = row.get("prenom", "")
    bts_label = BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))

    return render_template(
        "reconfirm.html",
        prenom=prenom,
        bts_label=bts_label,
        token=token,
        sig=sig,
        title="Reconfirmer mon inscription"
    )


@app.route("/reconfirm-validate", methods=["POST"])
def reconfirm_validate():
    token = request.form.get("token", "")
    sig = request.form.get("sig", "")
    if not verify_token(token, sig):
        abort(403)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidats WHERE token_reconfirm=?", (token,))
    row = cur.fetchone()
    if not row:
        conn.close()
        abort(404)

    row = dict(row)
    cur.execute(
        "UPDATE candidats SET statut=?, date_reconfirmee=?, updated_at=? WHERE id=?",
        ("reconfirmee", datetime.now().isoformat(), datetime.now().isoformat(), row["id"])
    )
    conn.commit()

    # 🧹 Suppression automatique du badge relance après reconfirmation
    try:
        cur.execute("UPDATE candidats SET last_relance=NULL WHERE id=?", (row["id"],))
        conn.commit()
        print(f"🧹 Badge relance supprimé pour {row['prenom']} {row['nom']} (reconfirmation)")
    except Exception as e:
        print("⚠️ Erreur suppression badge relance (reconfirm-validate):", e)


    conn.close()

    # ✉️ Mail confirmation reconfirmation
    html = mail_html(
        "reconfirmation_validee",
        rentree_annee=candidate_year(row),
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
    )
    send_mail(row.get("email", ""), "Reconfirmation validée ✅", html)

    # 📱 SMS reconfirmation validée
    tel = (row.get("tel", "") or "").replace(" ", "")
    if tel.startswith("0"):
        tel = "+33" + tel[1:]
    msg = sms_text(
        "reconfirmation_validee",
        rentree_annee=candidate_year(row),
        prenom=row.get("prenom", ""),
        bts_label=BTS_LABELS.get((row.get("bts") or "").strip().upper(), row.get("bts"))
    )
    send_sms_brevo(tel, msg)

    log_event(row, "STATUT_CHANGE", {"statut": "reconfirmee"})
    log_event(row, "MAIL_ENVOYE", {"type": "reconfirmation_validee"})
    log_event(row, "SMS_ENVOYE", {"type": "reconfirmation_validee", "tel": tel})

    return render_template("reconfirm_ok.html", prenom=row.get("prenom", ""), bts_label=row.get("bts"))



@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

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
    # Keep historical admin links working through the same private viewer.
    if not require_admin():
        abort(403)
    filename = os.path.basename(filename)
    if not filename or filename in ('.', '..') or '\\' in filename:
        abort(404)
    with closing(db()) as conn:
        rows = [dict(row) for row in conn.execute('SELECT * FROM candidats')]
    for row in rows:
        path = os.path.join(UPLOAD_DIR, row['id'], filename)
        listed = any(filename == os.path.basename(stored)
                     for field, _ in DOC_FIELDS.values()
                     for stored in parse_list(row.get(field)) if isinstance(stored, str))
        if os.path.isfile(path) or listed:
            return redirect(url_for('admin_candidate_document', cid=row['id'], filename=filename))
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

with app.app_context():
    ensure_souhaite_accompagnement_field()


print("🚀 Application Flask démarrée – gestion CNAPS & pièces justificatives OK")

@app.route("/admin/clear-db", methods=["POST"])
def admin_clear_db():
    if not require_admin():
        abort(403)

    conn = db()
    ensure_promotions_schema(conn)
    cur = conn.cursor()
    # Supprimer tous les candidats et logs
    cur.execute("DELETE FROM student_promotions")
    cur.execute("DELETE FROM student_promotion_history")
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
        "preinscription": "Nous avons bien reçu ta candidature. Notre équipe étudie ton dossier et te répondra par e-mail et SMS.",
        "validee": "Ta candidature est validée. Confirme maintenant ton inscription depuis le lien reçu par e-mail et SMS.",
        "confirmee": "Ton inscription est confirmée. Bienvenue à Intégrale Academy !",
        "reconf_en_cours": "Confirme que tu souhaites toujours nous rejoindre depuis le lien reçu par e-mail.",
        "reconfirmee": "Ta présence à la rentrée est confirmée. À très bientôt !",
        "docs_non_conformes": "Certains documents doivent être remplacés ou complétés. Consulte ton e-mail pour les transmettre.",
        "annulee": "Ton inscription a été annulée. Notre équipe reste disponible si tu souhaites faire le point.",
    }

    explication_statut = explications.get(statut, "Le traitement de votre dossier est en cours.")

    portal_today = dict(role='student', requires_login=True,
                        planning_url=url_for('candidate_login'), today_label='')
    identity = get_authenticated_student(app, db)
    if identity and identity['candidate_id'] == row['id']:
        with closing(db()) as planning_conn:
            portal_today = get_portal_today(planning_conn, 'student', identity['candidate_id'])

    response = app.make_response(render_template(
        "espace_candidat.html",
        title="Mon espace étudiant · Intégrale Academy",
        row=row,
        portal_today=portal_today,
        statut=statut,
        explication_statut=explication_statut,
        commentaire=commentaire,
        candidate_photo_url=url_for('candidate_photo', slug=slug) if parse_list(row.get('fichiers_photo')) else None
    ))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.vary.add('Cookie')
    return response


def _candidate_photo_response(row):
    return photo_response(row, UPLOAD_DIR, db)


@app.get('/admin/candidat/<cid>/photo')
def admin_candidate_photo(cid):
    if not require_admin(): abort(403)
    with closing(db()) as conn:
        row = get_candidat(conn, cid)
    return photo_response(row, UPLOAD_DIR, db, original=request.args.get("original") == "1")


@app.get('/espace/<slug>/photo')
def candidate_photo(slug):
    with closing(db()) as conn:
        row = conn.execute('SELECT * FROM candidats WHERE slug_public=?', (slug,)).fetchone()
    return _candidate_photo_response(row)




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
    return candidate_workflow_response("reconfirm", cid)


# =====================================================
# 🌐 GESTION DU PORTAIL – OUVERT / FERMÉ
# =====================================================

PORTAL_FILE = os.path.join(DATA_DIR, "portal.json")

def get_portal_status():
    """Lit le statut du portail (open/closed + message)"""
    if not os.path.exists(PORTAL_FILE):
        return {"status": "open", "message": "Ouvert aux inscriptions"}
    try:
        with open(PORTAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "open", "message": "Ouvert aux inscriptions"}

def set_portal_status(status, message):
    """Met à jour le statut du portail"""
    data = {"status": status, "message": message}
    with open(PORTAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# =====================================================
# 🔐 GESTION PORTAIL (Ouvrir / Fermer les inscriptions)
# =====================================================

PORTAL_FILE = os.path.join(DATA_DIR, "portal.json")

def load_portal_status():
    """Charge l'état actuel du portail (ou valeurs par défaut)."""
    if os.path.exists(PORTAL_FILE):
        with open(PORTAL_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"status": "open", "message": "", "comment": ""}


# =====================================================
# 🌐 API – GESTION DU PORTAIL (État ouvert/fermé)
# =====================================================

@app.route("/get_portal_status")
def api_get_portal_status():
    """
    🔎 Route API pour récupérer l’état actuel du portail
    (utilisé par l’admin.js pour afficher le statut et le message).
    """
    data = load_portal_status()
    data.update(scheduled=not campaign_is_open(), opening=OPENING_LABEL, effective_open=admissions_available())
    return jsonify(data)


@app.route("/set_portal_status", methods=["POST"])
def api_set_portal_status():
    """
    💾 Route API pour modifier le statut du portail
    (open / closed) + message + commentaire.
    """
    if not require_admin():
        return jsonify(ok=False, error="Authentification administrateur requise."), 403
    data = request.get_json() or {}
    status = data.get("status", "open")
    if status not in ("open", "closed"):
        return jsonify(ok=False, error="Statut invalide."), 400
    message = data.get("message", "")
    comment = data.get("comment", "")  # 🗒️ Nouveau champ commentaire

    # Enregistre le tout dans /data/portal.json
    with open(PORTAL_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"status": status, "message": message, "comment": comment, "campaign_year": ADMISSION_YEAR},
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"✅ Portail mis à jour → {status.upper()} ({message})")
    if comment:
        print(f"🗒️ Commentaire : {comment}")

    return jsonify({"ok": True, "status": status, "message": message, "comment": comment})


# =====================================================
# ✉️📱 ADMIN – RENVOI MAILS (mail + SMS) — VERSION CORRIGÉE
# =====================================================
@app.route("/admin/resend_mail_sms/<cid>", methods=["POST"])
def admin_resend_mail_sms(cid):
    return candidate_workflow_response("resend", cid)



# =====================================================
# 🔔 RELANCES (mail + SMS) — VERSION CORRIGÉE
# =====================================================
@app.route("/admin/relance/<cid>", methods=["POST"])
def admin_relance(cid):
    return candidate_workflow_response("remind", cid)



def _send_relance_candidature_validee(cur, row):
    """Envoie la même relance que le bouton individuel pour une candidature validée."""
    row = dict(row)
    cid = row["id"]
    prenom = row.get("prenom") or ""
    email = row.get("email") or ""
    tel = row.get("tel") or ""
    bts_label = row.get("bts") or ""

    token = row.get("token_confirm")
    now_iso = datetime.now().isoformat()
    if not token:
        token = new_token()
        cur.execute(
            "UPDATE candidats SET token_confirm=?, updated_at=? WHERE id=?",
            (token, now_iso, cid)
        )
        row["token_confirm"] = token

    base_url = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    lien_confirmation = f"{base_url}/confirm-inscription?token={token}&sig={sign_token(token)}"

    from mail_templates import get_mail_context, mail_html
    from sms_templates import sms_text
    from utils import send_mail, send_sms_brevo

    ctx = get_mail_context(row, lien_espace=lien_confirmation)
    ctx["bts_label"] = BTS_LABELS.get(ctx["bts_label"], ctx["bts_label"])
    ctx["lien_confirmation"] = lien_confirmation

    mail_html_content = mail_html("relance_candidature_validee", **ctx)
    mail_id = send_mail(
        email,
        "Relance – Confirmez votre inscription BTS en alternance",
        mail_html_content
    )

    tel_fmt = str(tel).strip().replace(" ", "")
    if tel_fmt.startswith("0"):
        tel_fmt = "+33" + tel_fmt[1:]

    sms_id = send_sms_brevo(
        tel_fmt,
        sms_text(
            "relance_candidature_validee",
            prenom=prenom,
            bts_label=bts_label,
            lien_espace=lien_confirmation
        )
    )

    cur.execute(
        "INSERT INTO logs (cid, type, payload, created_at) VALUES (?, ?, ?, datetime('now','localtime'))",
        (cid, "RELANCE_ENVOYEE", f"candidature_validee / mail_id: {mail_id} / sms_id: {sms_id}")
    )
    cur.execute(
        "UPDATE candidats SET last_relance=?, updated_at=? WHERE id=?",
        (datetime.now().isoformat(), datetime.now().isoformat(), cid)
    )

    return mail_id, sms_id


# =====================================================
# 🧮 COMPTE LES CANDIDATS "Candidature validée"
# =====================================================
@app.route("/admin/count_validated_applications")
def admin_count_validated_applications():
    if not require_admin():
        return jsonify(ok=False, error="Non autorisé"), 403

    try:
        conn = db()
        count = len(campaign_rows("validee"))
        conn.close()
        return jsonify(ok=True, count=count)
    except Exception as e:
        print("Erreur count_validated_applications:", e)
        return jsonify(ok=False, error=str(e)), 500


# =====================================================
# 🔔 RELANCE TOUTES LES CANDIDATURES VALIDÉES
# =====================================================
@app.route("/admin/relance_all_validated", methods=["POST"])
def admin_relance_all_validated():
    return candidate_workflow_response("bulk-remind")


# =====================================================
# 🧮 COMPTE LES CANDIDATS "Inscription confirmée"
# =====================================================
@app.route("/admin/count_confirmed")
def admin_count_confirmed():
    if not require_admin():
        return jsonify(ok=False, error="Non autorisé"), 403
    try:
        conn = db()
        count = len(campaign_rows("confirmee"))
        conn.close()
        return jsonify(ok=True, count=count)
    except Exception as e:
        print("Erreur count_confirmed:", e)
        return jsonify(ok=False, error=str(e)), 500


# =====================================================
# 📢 ENVOI DE RECONFIRMATION À TOUS LES CANDIDATS "Inscription confirmée"
# =====================================================
@app.route("/admin/reconfirm_all", methods=["POST"])
def admin_reconfirm_all():
    return candidate_workflow_response("bulk-reconfirm")


# =====================================================
# 🔔 MONITORING AUTOMATIQUE DE L'API BREVO
# =====================================================
import threading
import time
import requests

LAST_BREVO_ALERT = 0  # timestamp de la dernière alerte envoyée


def send_alert_brevo(message):
    """Envoie une alerte par Gmail (indépendant de Brevo)"""
    global LAST_BREVO_ALERT

    # Anti-spam : pas plus d'une alerte toutes les 30 minutes
    if time.time() - LAST_BREVO_ALERT < 1800:
        print("⏳ Alerte déjà envoyée il y a moins de 30 minutes, on ignore.")
        return

    LAST_BREVO_ALERT = time.time()

    try:
        # 📌 On utilise Gmail SMTP ici, jamais Brevo
        from utils import send_mail_gmail

        html = f"""
        <h2>⚠️ ALERTE CRITIQUE – API BREVO</h2>
        <p>{message}</p>
        <p><strong>L'API Brevo ne répond plus.</strong></p>
        <p>Site : inscriptionsbts.onrender.com</p>
        <p>Heure : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
        """

        send_mail_gmail(
            "gestion@integraleacademy.com",
            "⚠️ ALERTE CRITIQUE – Échec API Brevo",
            html
        )

        print("🚨 Alerte envoyée à gestion@integraleacademy.com via Gmail (OK)")

    except Exception as e:
        print("❌ Impossible d'envoyer l'alerte Gmail :", e)


def check_brevo_health():
    """Teste la disponibilité de l'API Brevo toutes les 5 minutes"""
    while True:
        try:
            print("🔎 Vérification API Brevo...")

            api_key = os.getenv("BREVO_API_KEY", "")

            headers = {
                "api-key": api_key,
                "Content-Type": "application/json"
            }

            # petit appel simple à l'API Brevo
            r = requests.get("https://api.brevo.com/v3/account", headers=headers, timeout=10)

            if r.status_code != 200:
                msg = f"API Brevo en erreur : {r.status_code} – {r.text}"
                print("❌", msg)
                send_alert_brevo(msg)
            else:
                print("🟢 API Brevo OK")

        except Exception as e:
            msg = f"Erreur critique Brevo : {str(e)}"
            print("❌", msg)
            send_alert_brevo(msg)

        time.sleep(300)  # 5 minutes


# 🚀 Démarrage du monitoring Brevo
if os.getenv('BREVO_HEALTH_MONITOR', '1') == '1':
    monitor_thread = threading.Thread(target=check_brevo_health, daemon=True)
    monitor_thread.start()

@app.route("/brevo/status")
def brevo_status():
    """Retourne l'état actuel de Brevo"""
    import requests
    api_key = os.getenv("BREVO_API_KEY", "")

    try:
        r = requests.get(
            "https://api.brevo.com/v3/account",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=5
        )
        if r.status_code == 200:
            return {"status": "ok"}
        else:
            return {"status": "error", "code": r.status_code}
    except:
        return {"status": "error", "code": "exception"}

@app.route("/admin/stats")
def admin_stats():
    response = api_kpi()
    return jsonify(ok=True, stats=response.get_json())



# =====================================================
# 📩 ENVOI MANUEL DU MAIL APS (bouton dans l’admin)
# =====================================================
@app.route("/admin/send_mail_aps/<cid>", methods=["POST"])
def admin_send_mail_aps(cid):
    return candidate_workflow_response("aps", cid)

from flask import send_from_directory

@app.route('/sw.js')
def sw():
    return send_from_directory('.', 'sw.js', mimetype='application/javascript')

@app.route('/brevo-frame.html')
def brevo_frame():
    return send_from_directory('.', 'brevo-frame.html', mimetype='text/html')


# =====================================================
# 🇬🇧 VOYAGE À LONDRES
# =====================================================
VOYAGE_DIR = os.path.join(DATA_DIR, "voyage_londres")
os.makedirs(VOYAGE_DIR, exist_ok=True)
VOYAGE_CONVENTIONS = ("À faire", "Éditée", "Signée", "Transmise OPCO")
VOYAGE_CATEGORIES = ("Accord de prise en charge OPCO", "Convention signée", "Passeport", "Billet", "Hébergement", "Autre")
VOYAGE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx"}

def migrate_voyage_londres():
    """Migration idempotente, également livrée sous migrations/001_voyage_londres.sql."""
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS voyage_londres_inscriptions (
      id TEXT PRIMARY KEY, candidat_id TEXT NOT NULL UNIQUE,
      statut TEXT NOT NULL DEFAULT 'active' CHECK(statut IN ('active','annulee')),
      convention TEXT NOT NULL DEFAULT 'À faire', opco INTEGER NOT NULL DEFAULT 0,
      billet INTEGER NOT NULL DEFAULT 0, hebergement INTEGER NOT NULL DEFAULT 0,
      passeport INTEGER NOT NULL DEFAULT 0, numero_passeport TEXT,
      passeport_delivrance TEXT, passeport_expiration TEXT,
      immigration INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, cancelled_at TEXT,
      FOREIGN KEY(candidat_id) REFERENCES candidats(id) ON DELETE RESTRICT);
    CREATE TABLE IF NOT EXISTS voyage_londres_documents (
      id TEXT PRIMARY KEY, inscription_id TEXT NOT NULL, categorie TEXT NOT NULL,
      nom_original TEXT NOT NULL, nom_stockage TEXT NOT NULL UNIQUE,
      mime_type TEXT NOT NULL, taille INTEGER NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(inscription_id) REFERENCES voyage_londres_inscriptions(id) ON DELETE CASCADE);
    CREATE INDEX IF NOT EXISTS idx_voyage_statut ON voyage_londres_inscriptions(statut);
    """)
    conn.commit(); conn.close()

migrate_voyage_londres()

def _voyage_guard(api=True):
    if session.get("admin_ok"): return None
    return (jsonify(ok=False, error="Authentification administrateur requise"), 403) if api else redirect(url_for("login"))

def _csrf_token():
    if not session.get("voyage_csrf"): session["voyage_csrf"] = uuid.uuid4().hex
    return session["voyage_csrf"]

def _voyage_csrf():
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    return bool(token and token == session.get("voyage_csrf"))

def _voyage_rows(conn):
    return [dict(r) for r in conn.execute("""SELECT v.*, c.nom, c.prenom, c.email, c.tel,
      (SELECT COUNT(*) FROM voyage_londres_documents d WHERE d.inscription_id=v.id) document_count
      FROM voyage_londres_inscriptions v JOIN candidats c ON c.id=v.candidat_id
      ORDER BY CASE v.statut WHEN 'active' THEN 0 ELSE 1 END, c.nom COLLATE NOCASE, c.prenom COLLATE NOCASE""")]

def _canonical_voyage_convention(value):
    """Mappe les libellés historiques de convention vers les quatre statuts affichés."""
    key = re.sub(r"[^a-z0-9]+", "-", _normalize(str(value or "")).lower()).strip("-")
    aliases = {
        "a-faire": "À faire", "a-fair": "À faire", "faire": "À faire",
        "editee": "Éditée", "edite": "Éditée", "edition": "Éditée",
        "signee": "Signée", "signe": "Signée",
        "transmise-opco": "Transmise OPCO", "transmis-opco": "Transmise OPCO",
        "transmise-a-l-opco": "Transmise OPCO", "envoyee-opco": "Transmise OPCO",
    }
    return aliases.get(key, "À faire")

def _voyage_public_row(row):
    r = dict(row)
    r["convention"] = _canonical_voyage_convention(r.get("convention"))
    number = r.pop("numero_passeport", None) or ""
    r["passeport_masque"] = ("••••" + number[-4:]) if number else ""
    return r

@app.route("/admin/voyage-londres")
def voyage_londres():
    denied = _voyage_guard(False)
    if denied: return denied
    return render_template("voyage_londres.html", title="Gestion du voyage à Londres", csrf_token=_csrf_token())

@app.route("/admin/voyage-londres/api/inscriptions")
def voyage_londres_list():
    denied = _voyage_guard()
    if denied: return denied
    conn=db(); rows=[_voyage_public_row(r) for r in _voyage_rows(conn)]; conn.close()
    return jsonify(ok=True, inscriptions=rows)

@app.route("/admin/voyage-londres/api/recherche")
def voyage_londres_search():
    denied = _voyage_guard()
    if denied: return denied
    q = re.sub(r"[\s\-]+", "", _normalize(request.args.get("q", "")).lower())
    if not q: return jsonify(ok=True, personnes=[])
    conn=db(); candidates=[]
    for row in conn.execute("""SELECT c.id,c.nom,c.prenom,c.email,v.id inscription_id,v.statut
      FROM candidats c LEFT JOIN voyage_londres_inscriptions v ON v.candidat_id=c.id ORDER BY c.nom LIMIT 500"""):
        item=dict(row); hay=re.sub(r"[\s\-]+", "", _normalize((item['nom'] or '')+(item['prenom'] or '')).lower())
        if q in hay: candidates.append(item)
        if len(candidates) == 20: break
    conn.close(); return jsonify(ok=True, personnes=candidates)

@app.route("/admin/voyage-londres/api/inscriptions", methods=["POST"])
def voyage_londres_create():
    denied=_voyage_guard()
    if denied:return denied
    if not _voyage_csrf(): return jsonify(ok=False,error="Jeton CSRF invalide"),400
    data=request.get_json(silent=True) or {}; cid=str(data.get("candidat_id", ""))
    conn=db(); person=conn.execute("SELECT id FROM candidats WHERE id=?",(cid,)).fetchone()
    if not person: conn.close(); return jsonify(ok=False,error="Personne introuvable"),404
    existing=conn.execute("SELECT * FROM voyage_londres_inscriptions WHERE candidat_id=?",(cid,)).fetchone()
    now=datetime.utcnow().isoformat()
    if existing:
        if existing["statut"] == "active": conn.close(); return jsonify(ok=False,error="Cette personne est déjà inscrite"),409
        conn.execute("UPDATE voyage_londres_inscriptions SET statut='active',cancelled_at=NULL,updated_at=? WHERE candidat_id=?",(now,cid))
    else:
        conn.execute("INSERT INTO voyage_londres_inscriptions(id,candidat_id,created_at,updated_at) VALUES(?,?,?,?)",(uuid.uuid4().hex,cid,now,now))
    conn.commit(); conn.close(); return jsonify(ok=True)

@app.route("/admin/voyage-londres/api/inscriptions/<iid>", methods=["PATCH", "DELETE"])
def voyage_londres_change(iid):
    denied=_voyage_guard()
    if denied:return denied
    if not _voyage_csrf(): return jsonify(ok=False,error="Jeton CSRF invalide"),400
    conn=db(); current=conn.execute("SELECT * FROM voyage_londres_inscriptions WHERE id=?",(iid,)).fetchone()
    if not current: conn.close(); return jsonify(ok=False,error="Inscription introuvable"),404
    if request.method == "DELETE":
        docs=list(conn.execute("SELECT nom_stockage FROM voyage_londres_documents WHERE inscription_id=?",(iid,)))
        conn.execute("DELETE FROM voyage_londres_documents WHERE inscription_id=?",(iid,)); conn.execute("DELETE FROM voyage_londres_inscriptions WHERE id=?",(iid,)); conn.commit(); conn.close()
        for doc in docs:
            try: os.remove(os.path.join(VOYAGE_DIR,doc[0]))
            except FileNotFoundError: pass
        return jsonify(ok=True)
    data=request.get_json(silent=True) or {}; allowed={"convention","opco","billet","hebergement","immigration","statut"}
    updates={k:v for k,v in data.items() if k in allowed}
    if "convention" in updates and updates["convention"] not in VOYAGE_CONVENTIONS: conn.close(); return jsonify(ok=False,error="Convention invalide"),400
    for key in ("opco","billet","hebergement","immigration"):
        if key in updates and updates[key] not in (0,1,False,True): conn.close(); return jsonify(ok=False,error=f"Valeur {key} invalide"),400
    if "statut" in updates and updates["statut"] not in ("active","annulee"): conn.close(); return jsonify(ok=False,error="Statut invalide"),400
    if not updates: conn.close(); return jsonify(ok=False,error="Aucune modification valide"),400
    now=datetime.utcnow().isoformat(); updates["updated_at"]=now
    if updates.get("statut")=="annulee": updates["cancelled_at"]=now
    elif updates.get("statut")=="active": updates["cancelled_at"]=None
    conn.execute("UPDATE voyage_londres_inscriptions SET "+",".join(f"{k}=?" for k in updates)+" WHERE id=?",(*updates.values(),iid)); conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route("/admin/voyage-londres/api/inscriptions/<iid>/passeport", methods=["GET", "PATCH"])
def voyage_londres_passport(iid):
    denied=_voyage_guard()
    if denied:return denied
    if request.method == "GET":
        conn=db(); row=conn.execute("SELECT passeport,numero_passeport,passeport_delivrance,passeport_expiration FROM voyage_londres_inscriptions WHERE id=?",(iid,)).fetchone(); conn.close()
        return (jsonify(ok=True,passeport=dict(row)) if row else (jsonify(ok=False,error="Inscription introuvable"),404))
    if not _voyage_csrf(): return jsonify(ok=False,error="Jeton CSRF invalide"),400
    d=request.get_json(silent=True) or {}; available=d.get("passeport") in (1,True)
    number=str(d.get("numero_passeport","")).strip().upper(); issued=d.get("passeport_delivrance") or None; expires=d.get("passeport_expiration") or None
    if available:
        if not number or not issued or not expires: return jsonify(ok=False,error="Numéro et dates obligatoires"),400
        try:
            if datetime.fromisoformat(expires).date() <= datetime.fromisoformat(issued).date(): raise ValueError()
        except ValueError: return jsonify(ok=False,error="L'expiration doit être postérieure à la délivrance"),400
    conn=db(); cur=conn.execute("UPDATE voyage_londres_inscriptions SET passeport=?,numero_passeport=?,passeport_delivrance=?,passeport_expiration=?,updated_at=? WHERE id=?",(int(available),number if available else None,issued if available else None,expires if available else None,datetime.utcnow().isoformat(),iid)); conn.commit(); conn.close()
    return (jsonify(ok=True) if cur.rowcount else (jsonify(ok=False,error="Inscription introuvable"),404))

def _valid_upload(file):
    ext=(file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else '')
    head=file.stream.read(8); file.stream.seek(0)
    signatures={"pdf":head.startswith(b"%PDF"),"jpg":head.startswith(b"\xff\xd8\xff"),"jpeg":head.startswith(b"\xff\xd8\xff"),"png":head.startswith(b"\x89PNG"),"doc":head.startswith(b"\xd0\xcf\x11\xe0"),"docx":head.startswith(b"PK")}
    return ext in VOYAGE_EXTENSIONS and signatures.get(ext,False),ext

@app.route("/admin/voyage-londres/api/inscriptions/<iid>/documents", methods=["GET","POST"])
def voyage_londres_documents(iid):
    denied=_voyage_guard()
    if denied:return denied
    conn=db()
    if not conn.execute("SELECT id FROM voyage_londres_inscriptions WHERE id=?",(iid,)).fetchone(): conn.close(); return jsonify(ok=False,error="Inscription introuvable"),404
    if request.method == "GET":
        rows=[dict(r) for r in conn.execute("SELECT id,categorie,nom_original,mime_type,taille,created_at FROM voyage_londres_documents WHERE inscription_id=? ORDER BY created_at DESC",(iid,))]; conn.close(); return jsonify(ok=True,documents=rows)
    if not _voyage_csrf(): conn.close(); return jsonify(ok=False,error="Jeton CSRF invalide"),400
    category=request.form.get("categorie","")
    if category not in VOYAGE_CATEGORIES: conn.close(); return jsonify(ok=False,error="Catégorie invalide"),400
    files=request.files.getlist("documents")
    if not files: conn.close(); return jsonify(ok=False,error="Aucun document"),400
    saved=[]
    for f in files:
        ok,ext=_valid_upload(f); f.seek(0,2); size=f.tell(); f.seek(0)
        if not ok or size>15*1024*1024: conn.rollback(); conn.close(); return jsonify(ok=False,error="Format invalide ou fichier supérieur à 15 Mo"),400
        storage=uuid.uuid4().hex+"."+ext; f.save(os.path.join(VOYAGE_DIR,storage)); saved.append(storage)
        conn.execute("INSERT INTO voyage_londres_documents VALUES(?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,iid,category,secure_filename(f.filename) or ('document.'+ext),storage,f.mimetype or 'application/octet-stream',size,datetime.utcnow().isoformat()))
    conn.commit(); conn.close(); return jsonify(ok=True)

@app.route("/admin/voyage-londres/documents/<did>/telecharger")
def voyage_londres_download(did):
    denied=_voyage_guard()
    if denied:return denied
    conn=db(); doc=conn.execute("SELECT * FROM voyage_londres_documents WHERE id=?",(did,)).fetchone(); conn.close()
    if not doc: abort(404)
    return send_file(os.path.join(VOYAGE_DIR,doc["nom_stockage"]),as_attachment=True,download_name=doc["nom_original"])

@app.route("/admin/voyage-londres/documents/<did>",methods=["DELETE"])
def voyage_londres_delete_document(did):
    denied=_voyage_guard()
    if denied:return denied
    if not _voyage_csrf(): return jsonify(ok=False,error="Jeton CSRF invalide"),400
    conn=db(); doc=conn.execute("SELECT nom_stockage FROM voyage_londres_documents WHERE id=?",(did,)).fetchone()
    if not doc: conn.close(); return jsonify(ok=False,error="Document introuvable"),404
    conn.execute("DELETE FROM voyage_londres_documents WHERE id=?",(did,)); conn.commit(); conn.close()
    try: os.remove(os.path.join(VOYAGE_DIR,doc[0]))
    except FileNotFoundError: pass
    return jsonify(ok=True)

@app.route("/admin/voyage-londres/recapitulatif/<iid>")
def voyage_londres_recap(iid):
    denied=_voyage_guard(False)
    if denied:return denied
    conn=db(); row=conn.execute("""SELECT v.*,c.nom,c.prenom,c.email,c.tel FROM voyage_londres_inscriptions v JOIN candidats c ON c.id=v.candidat_id WHERE v.id=?""",(iid,)).fetchone()
    docs=[dict(r) for r in conn.execute("SELECT * FROM voyage_londres_documents WHERE inscription_id=? ORDER BY created_at",(iid,))]; conn.close()
    if not row: abort(404)
    return render_template("voyage_londres_recap.html",inscription=dict(row),documents=docs)





def ensure_campaign_schema():
    conn = db()
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(candidats)")}
        if "rentree_annee" not in columns:
            conn.execute("ALTER TABLE candidats ADD COLUMN rentree_annee INTEGER NOT NULL DEFAULT 2026")
        conn.commit()
    finally:
        conn.close()


ensure_campaign_schema()
snapshot_legacy_links(db)

from gestionstagiaires_api import register_gestionstagiaires_api
register_gestionstagiaires_api(app, db, UPLOAD_DIR)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
