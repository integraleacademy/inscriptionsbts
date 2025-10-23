import os, smtplib, ssl, secrets, hmac, hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
from datetime import datetime

# =====================================================
# ⚙️ Configuration des variables d'environnement
# =====================================================
MAIL_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_SMTP_PORT", "587"))
MAIL_USER = os.getenv("MAIL_USERNAME")
MAIL_PASS = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER or "no-reply@example.com")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")

# =====================================================
# ✉️ Fonction d'envoi d'e-mail (avec pièces jointes optionnelles)
# =====================================================
def send_mail(to, subject, html, attachments=None):
    if not MAIL_USER or not MAIL_PASS:
        print("❌ Envoi annulé : MAIL_USERNAME / MAIL_PASSWORD manquant.")
        return False

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Intégrale Academy", MAIL_FROM))
    msg["To"] = to

    # 🧾 Corps HTML
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 📎 Pièces jointes (facultatives)
    if attachments:
        for path in attachments:
            try:
                with open(path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(path))
                part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
                msg.attach(part)
                print(f"📎 Pièce jointe ajoutée : {os.path.basename(path)}")
            except Exception as e:
                print(f"⚠️ Erreur ajout pièce jointe {path} :", e)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
            server.starttls(context=context)
            server.login(MAIL_USER, MAIL_PASS)
            server.send_message(msg)

        print(f"✅ Mail envoyé à {to} — {subject}")

        # 🪵 Enregistrement automatique du mail dans les logs
        try:
            from app import add_log  # si ton fichier principal s'appelle app.py
            add_log("MAIL_ENVOYE", f"{subject} → {to}")
        except Exception as log_err:
            print(f"⚠️ Impossible d’enregistrer le log mail ({subject}):", log_err)

        return True

    except Exception as e:
        print(f"❌ Erreur envoi mail vers {to} :", e)
        return False

# =====================================================
# 🔢 Numérotation de dossier
# =====================================================
def dossier_number(now=None, counter=1):
    now = now or datetime.now()
    return f"2026BTS{now.strftime('%d')}{now.strftime('%m')}{counter:04d}"

# =====================================================
# 🔐 Génération et signature de token
# =====================================================
def new_token():
    return secrets.token_urlsafe(32)

def sign_token(value: str) -> str:
    secret = os.getenv("SECRET_KEY", "dev-secret")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()

def make_signed_link(path: str, token: str) -> str:
    sig = sign_token(token)
    base = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    return f"{base}{path}?token={token}&sig={sig}"

# =====================================================
# 📱 ENVOI DE SMS AVEC BREVO
# =====================================================
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

def send_sms_brevo(phone_number, message):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = "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"

    api_instance = sib_api_v3_sdk.TransactionalSMSApi(sib_api_v3_sdk.ApiClient(configuration))
    sender = "INTACAD"  # 11 caractères max, pas d’espace
    sms = sib_api_v3_sdk.SendTransacSms(
        sender=sender,
        recipient=phone_number,
        content=message
    )

    try:
        response = api_instance.send_transac_sms(sms)
        print(f"✅ SMS envoyé à {phone_number} : {response}")
    except ApiException as e:
        print(f"❌ Erreur envoi SMS : {e}")

