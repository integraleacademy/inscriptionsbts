# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version finale unifiée)
# =====================================================

import os
from flask import render_template_string
from email.mime.image import MIMEImage

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")

def mail_html(template_name, **kwargs):
    """Retourne le HTML complet d’un mail avec logo et design unifié."""

    # === Variables de base ===
    prenom = kwargs.get("prenom", "") or ""
    bts_label = kwargs.get("bts_label", "") or ""
    lien_espace = kwargs.get("lien_espace", "#") or "#"

    # === Logo dynamique (utilise BASE_URL si définie sur Render) ===
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # === Contenu des modèles ===
    templates = {
        "accuse_reception": {
            "title": "Confirmation de réception",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous avons bien reçu votre pré-inscription pour le <strong>{bts_label}</strong>.</p>
                <p>Notre équipe va étudier votre dossier et vous contactera rapidement.</p>
                <p><a href="{lien_espace}" class="btn">Ouvrir mon espace</a></p>
            """
        },
        "candidature_validee": {
            "title": "Candidature validée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Bonne nouvelle 🎉 Votre candidature au <strong>{bts_label}</strong> a été validée.</p>
                <p>Merci de confirmer votre inscription :</p>
                <p><a href="{lien_espace}" class="btn">Confirmer mon inscription</a></p>
            """
        },
        "inscription_confirmee": {
            "title": "Inscription confirmée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Votre inscription au <strong>{bts_label}</strong> est désormais confirmée ✅.</p>
                <p>Bienvenue à Intégrale Academy 🎓 !</p>
            """
        },
        # ✅ Nouveau modèle ajouté pour la reconfirmation
   "reconfirmation": {
    "title": "Reconfirmation d’inscription",
    "content": f"""
        <p>Bonjour {prenom},</p>
        <p>Merci de confirmer à nouveau votre inscription pour le <strong>{bts_label}</strong>.</p>
        <p style="text-align:center;margin:25px 0;">
          <a href="{lien_espace}" class="btn">Reconfirmer mon inscription ✅</a>
        </p>
        <p>À très bientôt chez Intégrale Academy.</p>
    """
},

        "reconfirmation_demandee": {
            "title": "Reconfirmation demandée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir.</p>
                <p><a href="{lien_espace}" class="btn">Reconfirmer mon inscription</a></p>
            """
        },
        "reconfirmation_validee": {
            "title": "Reconfirmation validée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Votre reconfirmation d’inscription a bien été enregistrée ✅.</p>
                <p>À très bientôt pour la rentrée chez Intégrale Academy.</p>
            """
        },
        "docs_non_conformes": {
            "title": "Documents non conformes",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Certains documents ne sont pas conformes pour le <strong>{bts_label}</strong>.</p>
                <p>Merci de les renvoyer dès que possible :</p>
                <p><a href="{lien_espace}" class="btn">Envoyer mes nouvelles pièces</a></p>
            """
        },
        "reprendre_plus_tard": {
            "title": "Reprendre ma pré-inscription",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Vous pouvez reprendre votre pré-inscription pour le <strong>{bts_label}</strong> à tout moment.</p>
                <p><a href="{lien_espace}" class="btn">Reprendre maintenant</a></p>
            """
        },
        "certificat": {
            "title": "Votre certificat de scolarité",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
                <p>Conservez-le précieusement.</p>
            """
        },
        "certificat_presentiel": {
            "title": "Certificat de scolarité (présentiel)",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
                <p>À très bientôt sur le campus !</p>
            """
        },
        "bienvenue": {
            "title": "Bienvenue à Intégrale Academy 🎓",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous sommes ravis de vous accueillir au sein d’<strong>Intégrale Academy</strong>.</p>
                <p>Votre inscription au <strong>{bts_label}</strong> est désormais finalisée.</p>
                <p><a href="{lien_espace}" class="btn">Accéder à mon espace</a></p>
            """
        },

        # =====================================================
        # 🟢 MAILS PARCOURSUP – Import + Relance automatique
        # =====================================================
        "parcoursup_import": {
            "title": "Votre candidature Parcoursup – Intégrale Academy",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous avons bien reçu votre candidature Parcoursup pour le BTS <strong>{bts_label}</strong>.</p>
                <p>Merci de compléter votre pré-inscription dès maintenant via le lien ci-dessous :</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{lien_espace}" style="background:#f4c45a;color:black;padding:10px 16px;border-radius:6px;text-decoration:none;font-weight:bold;">
                    👉 Compléter ma pré-inscription
                  </a>
                </p>
                <p>À bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

        "parcoursup_relance": {
            "title": "Relance – Votre dossier Parcoursup",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous n’avons pas encore reçu votre confirmation Parcoursup pour le BTS <strong>{bts_label}</strong>.</p>
                <p>Merci de finaliser votre pré-inscription dès que possible :</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{lien_espace}" style="background:#f4c45a;color:black;padding:10px 16px;border-radius:6px;text-decoration:none;font-weight:bold;">
                    👉 Finaliser ma pré-inscription
                  </a>
                </p>
                <p>Bien cordialement,<br><b>L’équipe Intégrale Academy</b></p>
            """
        }
    }  # ← cette accolade ferme le dictionnaire templates

    # === Sécurité : vérifie que le modèle existe ===
    tpl = templates.get(template_name)
    if not tpl:
        return f"<p>Modèle inconnu : {template_name}</p>"

    # === Lecture du modèle de base ===
    try:
        with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
            base_html = f.read()
    except FileNotFoundError:
        return tpl["content"]

    # === Utilisation du logo intégré (CID) ===
    logo_cid = "logo_inline"

    html_final = render_template_string(
        base_html,
        email_title=tpl["title"],
        email_content=tpl["content"],
        logo_cid=logo_cid
    )

    return html_final




