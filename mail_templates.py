# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version finale)
# =====================================================

import os
from flask import render_template_string

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")

def mail_html(template_name, **kwargs):
    prenom = kwargs.get("prenom", "")
    bts_label = kwargs.get("bts_label", "")
    lien_espace = kwargs.get("lien_espace", "#")

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
        }
    }

    tpl = templates.get(template_name)
    if not tpl:
        return f"<p>Modèle inconnu : {template_name}</p>"

    try:
        with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
            base_html = f.read()
    except FileNotFoundError:
        return tpl["content"]

    return render_template_string(base_html, email_title=tpl["title"], email_content=tpl["content"])
