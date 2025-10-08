import os, json, uuid
from datetime import datetime
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_file
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from docxtpl import DocxTemplate
from io import BytesIO

# -----------------------
# Config & constantes
# -----------------------
DATA_DIR = os.environ.get("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "inscriptions.json")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# SMTP (Gmail recommandé via mot de passe d'application)
FROM_EMAIL = os.environ.get("FROM_EMAIL", "ecole@integraleacademy.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
BCC_EMAIL = os.environ.get("BCC_EMAIL")  # copie cachée facultative

# Dossier des modèles Word
DOCX_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates_docx")
CERTIFICAT_PRESENTIEL_TEMPLATE = os.path.join(DOCX_TEMPLATES_DIR, "certificat_presentiel_modele.docx")
CERTIFICAT_DISTANCIEL_TEMPLATE = os.path.join(DOCX_TEMPLATES_DIR, "certificat_distanciel_modele.docx")

app = Flask(__name__)
app.secret_key = SECRET_KEY

STATUSES = [
    "EN ATTENTE DE VALIDATION",
    "INSCRIPTION VALIDÉE",
]

# -----------------------
# Utils
# -----------------------
def _load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def _paris_now_str():
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).strftime("%d/%m/%Y %H:%M")

def add_log(item, message):
    if "logs" not in item:
        item["logs"] = []
    item["logs"].append(f"[{_paris_now_str()}] {message}")

@app.template_filter("status_color")
def status_color(status):
    mapping = {
        "EN ATTENTE DE VALIDATION": "orange",
        "INSCRIPTION VALIDÉE": "green",
    }
    return mapping.get(status, "gray")

def _send_html_mail(to_email, subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    recipients = [to_email]
    if BCC_EMAIL:
        recipients.append(BCC_EMAIL)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(FROM_EMAIL, EMAIL_PASSWORD)
        server.sendmail(FROM_EMAIL, recipients, msg.as_string())

def _mail_wrapper(title_html, body_html):
    logo_url = "https://inscriptionsbts.onrender.com/static/img/logo.png"
    assistance = """
      <div style="margin-top:20px; text-align:center;">
        <a href="https://assistance-alw9.onrender.com/"
           style="display:inline-block; padding:10px 20px; background:#F4C45A; color:#000;
                  text-decoration:none; border-radius:6px; font-weight:bold;">
           💬 Cliquez ici pour contacter l’assistance Intégrale Academy
        </a>
        <p style="margin-top:8px; font-size:14px; color:#333;">
          ou par téléphone : <b>04 22 47 07 68</b>
        </p>
      </div>
    """
    return f"""
    <div style="font-family: Arial, sans-serif; max-width:600px; margin:auto; background:#f9f9f9; padding:20px;">
      <div style="background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.1); overflow:hidden;">
        <div style="text-align:center; padding:20px 20px 10px 20px;">
          <img src="{logo_url}" alt="Logo"
               style="max-width:120px; height:auto; display:block; margin:auto;">
          <h2 style="color:#000; font-size:18px; margin:10px 0 0 0;">Intégrale Academy</h2>
        </div>
        <div style="background:#F4C45A; padding:12px; text-align:center;">
          {title_html}
        </div>
        <div style="padding:20px; font-size:15px; color:#333;">
          {body_html}
          {assistance}
        </div>
        <div style="padding:15px; font-size:12px; color:#777; text-align:center; border-top:1px solid #eee;">
          Ceci est un message automatique — Intégrale Academy
        </div>
      </div>
    </div>
    """

def send_ack_mail(to_email, prenom, nom, bts, mode):
    subject = "✅ Accusé de réception — Inscription BTS"
    title = '<h3 style="margin:0; font-size:18px; color:#000;">✅ Accusé de réception</h3>'
    body = f"""
      <p>Bonjour <b>{prenom} {nom}</b>,</p>
      <p>Nous confirmons la bonne réception de votre demande d’inscription en <b>BTS {bts}</b> ({mode}).</p>
      <p>Votre dossier est <b>en attente de validation</b>. Vous recevrez un e-mail dès que votre inscription sera validée.</p>
    """
    _send_html_mail(to_email, subject, _mail_wrapper(title, body))

def send_valid_mail(to_email, prenom, nom, bts, mode):
    subject = "🎉 Inscription validée — Intégrale Academy"
    title = '<h3 style="margin:0; font-size:18px; color:#000;">🎉 Inscription validée</h3>'
    body = f"""
      <p>Bonjour <b>{prenom} {nom}</b>,</p>
      <p>Bonne nouvelle : votre inscription en <b>BTS {bts}</b> ({mode}) est <b>validée</b> ✅.</p>
      <p>Nous allons vous envoyer par courrier votre <b>certificat de scolarité</b> et votre <b>carte étudiante</b>.</p>
    """
    _send_html_mail(to_email, subject, _mail_wrapper(title, body))

def _template_context(item):
    today = datetime.now().strftime("%d/%m/%Y")
    year = datetime.now().year
    next_year = year + 2
    annee_scolaire = f"{year}-{next_year}"
    return {
        "NOM": item.get("nom", ""),
        "PRENOM": item.get("prenom", ""),
        "MAIL": item.get("mail", ""),
        "TELEPHONE": item.get("tel", ""),
        "BTS": item.get("bts", ""),
        "MODE": item.get("mode", ""),
        "DATE_DU_JOUR": today,
        "DATE_DEBUT": f"01/09/{year}",
        "DATE_FIN": f"31/07/{next_year}",
        "ANNEE_SCOLAIRE": annee_scolaire,
        "ANNEE_DEBUT": year,
        "ANNEE_FIN": next_year
    }

def _render_docx(template_path, context, filename):
    if not os.path.exists(template_path):
        abort(404, f"Modèle introuvable : {os.path.basename(template_path)}")
    doc = DocxTemplate(template_path)
    doc.render(context)
    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return send_file(
        bio,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

# -----------------------
# Routes publiques
# -----------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    f = request.form
    item = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "nom": f.get("nom", "").strip(),
        "prenom": f.get("prenom", "").strip(),
        "mail": f.get("mail", "").strip(),
        "tel": f.get("tel", "").strip(),
        "bts": f.get("bts", "").strip(),
        "mode": f.get("mode", "").strip(),
        "status": "EN ATTENTE DE VALIDATION",
        "logs": []
    }
    data = _load_data()
    data.append(item)
    _save_data(data)

    try:
        if item["mail"] and EMAIL_PASSWORD:
            send_ack_mail(item["mail"], item["prenom"], item["nom"], item["bts"], item["mode"])
            add_log(item, f"Mail accusé de réception envoyé à {item['mail']}")
            _save_data(data)
    except Exception as e:
        print("Erreur envoi mail:", e)

    return render_template("thanks.html", prenom=item["prenom"])

# -----------------------
# Auth & Admin
# -----------------------
def require_admin(view):
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    wrapper.__name__ = view.__name__
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        flash("Mot de passe incorrect.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("login"))

@app.route("/admin")
@require_admin
def admin():
    data = _load_data()
    return render_template("admin.html", rows=data, statuses=STATUSES)

@app.route("/validate/<id>", methods=["POST"])
@require_admin
def validate_inscription(id):
    data = _load_data()
    for r in data:
        if r["id"] == id:
            r["status"] = "INSCRIPTION VALIDÉE"
            try:
                if r.get("mail") and EMAIL_PASSWORD:
                    send_valid_mail(r["mail"], r["prenom"], r["nom"], r["bts"], r["mode"])
                    add_log(r, f"Mail validation envoyé à {r['mail']}")
            except Exception as e:
                print("Erreur envoi mail validation:", e)
            _save_data(data)
            break
    return redirect(url_for("admin"))

@app.route("/delete/<id>", methods=["POST"])
@require_admin
def delete_inscription(id):
    data = _load_data()
    new_data = [r for r in data if r["id"] != id]
    _save_data(new_data)
    flash("Inscription supprimée.", "ok")
    return redirect(url_for("admin"))

# -----------------------
# Génération DOCX
# -----------------------
@app.route("/certificat_presentiel/<id>")
@require_admin
def certificat_presentiel(id):
    for r in _load_data():
        if r["id"] == id:
            ctx = _template_context(r)
            filename = f"Certificat_Presentiel_{r.get('nom','')}_{r.get('prenom','')}.docx"
            return _render_docx(CERTIFICAT_PRESENTIEL_TEMPLATE, ctx, filename)
    abort(404)

@app.route("/certificat_distanciel/<id>")
@require_admin
def certificat_distanciel(id):
    for r in _load_data():
        if r["id"] == id:
            ctx = _template_context(r)
            filename = f"Certificat_Distanciel_{r.get('nom','')}_{r.get('prenom','')}.docx"
            return _render_docx(CERTIFICAT_DISTANCIEL_TEMPLATE, ctx, filename)
    abort(404)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
