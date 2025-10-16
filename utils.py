import os, smtplib, ssl, secrets, hmac, hashlib
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

MAIL_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_SMTP_PORT", "587"))
MAIL_USER = os.getenv("MAIL_USERNAME")
MAIL_PASS = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER or "no-reply@example.com")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")

def send_mail(to, subject, html):
    if not MAIL_USER or not MAIL_PASS:
        print("[DEV] email skipped -> missing MAIL_USERNAME/PASSWORD")
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Intégrale Academy", MAIL_FROM))
    msg["To"] = to
    context = ssl.create_default_context()
    with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
        server.starttls(context=context)
        server.login(MAIL_USER, MAIL_PASS)
        server.send_message(msg)
    return True

def dossier_number(now=None, counter=1):
    now = now or datetime.now()
    return f"2026BTS{now.strftime('%d')}{now.strftime('%m')}{counter:04d}"

def new_token():
    return secrets.token_urlsafe(32)

def sign_token(value: str) -> str:
    secret = os.getenv("SECRET_KEY", "dev-secret")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()

def make_signed_link(path: str, token: str) -> str:
    sig = sign_token(token)
    return f"{BASE_URL}{path}?token={token}&sig={sig}"
