import os, secrets, hmac, hashlib, ssl, smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
import requests
import sib_api_v3_sdk
import base64
from sib_api_v3_sdk.rest import ApiException

# =====================================================
# ⚙️ Configuration des variables d'environnement
# =====================================================
MAIL_FROM = os.getenv("SENDER_EMAIL", "ecole@integraleacademy.com")
BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com")
BREVO_KEY = os.getenv("BREVO_API_KEY")

# =====================================================
# ✉️ Envoi d’e-mail via Brevo API (avec suivi)
# =====================================================
def send_mail(to, subject, html, attachments=None):
    """
    Envoie un e-mail via l’API transactionnelle de Brevo
    et renvoie le messageId pour le suivi via webhook.
    """
    api_key = BREVO_KEY
    sender_email = MAIL_FROM

    if not api_key:
        print("❌ Clé Brevo manquante, mail non envoyé.")
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    data = {
        "sender": {"email": sender_email, "name": "Intégrale Academy"},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
        "tags": ["parcoursup"],
    }

    # 📎 Gestion des pièces jointes (version Python 3 corrigée)
    if attachments:
        files = []
        for path in attachments:
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    files.append({
                        "content": b64,
                        "name": os.path.basename(path)
                    })
            except Exception as e:
                print(f"⚠️ Erreur ajout pièce jointe {path}: {e}")
        if files:
            data["attachment"] = files


    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        print("📦 Réponse Brevo mail:", r.text)

        if not r.ok:
            print(f"⚠️ Erreur envoi mail ({r.status_code}): {r.text}")
            return False

        resp = r.json()
        message_id = resp.get("messageId") or (resp.get("messageIds") or [None])[0]
        print(f"✅ Mail envoyé via Brevo à {to} — ID: {message_id}")
        return message_id

    except Exception as e:
        print(f"❌ Erreur envoi mail via Brevo: {e}")
        return False

# =====================================================
# 📱 ENVOI DE SMS AVEC BREVO (VERSION 2025 FINALE)
# =====================================================
def send_sms_brevo(phone_number, message):
    api_key = BREVO_KEY
    print("🟡 DEBUG — Début send_sms_brevo()")
    print("🟡 DEBUG — Numéro :", phone_number)
    print("🟡 DEBUG — Clé Brevo détectée :", "OUI" if api_key else "NON")

    if not api_key:
        print("❌ BREVO_API_KEY manquant.")
        return False

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key
    api_instance = sib_api_v3_sdk.TransactionalSMSApi(sib_api_v3_sdk.ApiClient(configuration))
    sender = "INTACAD"  # 11 caractères max, pas d’espace

    # ✅ Ajout du paramètre unicode_enabled=True
    sms = sib_api_v3_sdk.SendTransacSms(
        sender=sender,
        recipient=phone_number,
        content=message,
        type="transactional",
        unicode_enabled=True
    )

    try:
        response = api_instance.send_transac_sms(sms)
        print("📦 Réponse Brevo SMS complète:", response)

        sms_id = getattr(response, "messageId", None) or getattr(response, "message_id", None)
        print(f"✅ SMS envoyé à {phone_number} — ID: {sms_id}")

        return sms_id

    except ApiException as e:
        print(f"❌ Erreur API Brevo : {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue SMS : {e}")
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
# ✉️ Envoi d’e-mail via Gmail SMTP (indépendant de Brevo)
# =====================================================
def send_mail_gmail(to, subject, html):
    try:
        mail_from = os.getenv("MAIL_FROM")
        mail_pass = os.getenv("MAIL_PASS")

        msg = MIMEMultipart()
        msg["From"] = mail_from
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(mail_from, mail_pass)
        server.send_message(msg)
        server.quit()

        print(f"📨 Mail envoyé via Gmail à {to}")
        return True

    except Exception as e:
        print("❌ Erreur Gmail SMTP:", e)
        return False

