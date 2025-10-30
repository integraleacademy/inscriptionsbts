# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version uniformisée)
# =====================================================

import os
from flask import render_template_string

# Emplacement du modèle de base (le tien)
BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")


def mail_html(template_name, **kwargs):
    """Retourne le HTML d’un mail avec le layout complet (logo, design, etc.)."""

    prenom = kwargs.get("prenom", "")
    bts_label = kwargs.get("bts_label", "")
    lien_espace = kwargs.get("lien_espace", "#")

    # Contenu spécifique à chaque mail
    templates = {
        # 📨 Accusé de réception
        "accuse_reception": {
            "title": "Confirmation de réception",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous avons bien reçu votre pré-inscription pour le <strong>{bts_label}</strong>.</p>
                <p>Notre équipe va étudier votre dossier et vous contactera rapidement.</p>
                <p>➡️ Vous pouvez suivre l’évolution de votre dossier ici :
                   <a href="{lien_espace}" class="btn">Ouvrir mon espace</a></p>
            """
        },

        # ✅ Candidature validée
        "candidature_validee": {
            "title": "Candidature validée",
            "content": f"""
                <p>Bonjour {prenom.upper()},</p>
                <p>Bonne nouvelle 🎉 ! Votre candidature au <strong>{bts_label}</strong> a été validée.</p>
                <p>Merci de confirmer votre inscription en cliquant sur le lien ci-dessous :</p>
                <p><a href="{lien_espace}" class="btn">👉 Confirmer mon inscription</a></p>
            """
        },

        # 🎓 Inscription confirmée
        "inscription_confirmee": {
            "title": "Inscription confirmée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Votre inscription au <strong>{bts_label}</strong> est désormais confirmée ✅.</p>
                <p>Bienvenue à Intégrale Academy 🎓 !</p>
                <p>Notre équipe vous contactera prochainement pour la suite.</p>
            """
        },

        # 🔁 Reconfirmation demandée
        "reconfirmation_demandee": {
            "title": "Reconfirmation demandée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir.</p>
                <p>👉 Cliquez sur le lien reçu pour finaliser votre reconfirmation.</p>
            """
        },

        # 📄 Documents non conformes
        "docs_non_conformes": {
            "title": "Documents non conformes",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Certains de vos documents ne sont pas conformes pour le <strong>{bts_label}</strong>.</p>
                <p>Merci de les renvoyer dès que possible via le lien suivant :</p>
                <p><a href="{lien_espace}" class="btn">➡️ Envoyer mes nouvelles pièces</a></p>
            """
        },

        # 💌 Reprendre plus tard
        "reprendre_plus_tard": {
            "title": "Reprendre ma pré-inscription",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Vous pouvez reprendre votre pré-inscription pour le <strong>{bts_label}</strong> à tout moment.</p>
                <p><a href="{lien_espace}" class="btn">👉 Reprendre ma pré-inscription</a></p>
            """
        },

        # 📜 Certificat distanciel
        "certificat": {
            "title": "Certificat de scolarité",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
                <p>Conservez-le précieusement pour vos démarches administratives.</p>
            """
        },

        # 🏫 Certificat présentiel
        "certificat_presentiel": {
            "title": "Certificat de scolarité (présentiel)",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité (présentiel) pour le <strong>{bts_label}</strong>.</p>
                <p>À très bientôt sur le campus !</p>
            """
        },

        # 🎓 Bienvenue
        "bienvenue": {
            "title": "Bienvenue à Intégrale Academy 🎓",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous sommes ravis de vous accueillir au sein d’<strong>Intégrale Academy</strong>.</p>
                <p>Votre inscription au <strong>{bts_label}</strong> est désormais finalisée.</p>
                <p>Notre équipe vous contactera très prochainement pour la suite de votre intégration.</p>
            """
        },
    }

    # Vérifie que le modèle existe
    tpl = templates.get(template_name)
    if not tpl:
        return f"<p>Modèle inconnu : {template_name}</p>"

    # Charge le layout global
    try:
        with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
            base_html = f.read()
    except FileNotFoundError:
        return tpl["content"]

    # Rend le HTML complet avec le layout
    html = render_template_string(base_html, email_title=tpl["title"], email_content=tpl["content"])
    return html
