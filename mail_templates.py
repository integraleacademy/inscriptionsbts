# =====================================================
# ✉️ SYSTEME TEMPLATES EMAIL – VERSION FINALE NETTOYÉE
# =====================================================

import os
from flask import render_template_string

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")

def mail_html(template_name, **kwargs):
    """Retourne le HTML complet d’un mail en utilisant un fichier HTML dédié."""

    # Variables courantes
    prenom = kwargs.get("prenom", "")
    bts_label = kwargs.get("bts_label", "")
    lien_espace = kwargs.get("lien_espace", "#")

    numero_dossier  = kwargs.get("numero_dossier", "")
    form_nom        = kwargs.get("form_nom", "")
    form_prenom     = kwargs.get("form_prenom", "")
    form_email      = kwargs.get("form_email", "")
    form_tel        = kwargs.get("form_tel", "")
    form_mode_label = kwargs.get("form_mode_label", "")

    # Logo dynamique
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # ---------------------------
    # 1) Charger le mail HTML dédié
    # ---------------------------
    file_path = os.path.join("templates", "emails", f"{template_name}.html")

    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8") as f:
                html_content = f.read()

            # Rendu complet dans base email + injection du content
            with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
                base_html = f.read()

            return render_template_string(
                base_html,
                email_title=template_name.replace("_", " ").title(),
                email_content=render_template_string(
                    html_content,
                    **kwargs,
                    prenom=prenom,
                    bts_label=bts_label,
                    lien_espace=lien_espace,
                    numero_dossier=numero_dossier,
                    form_nom=form_nom,
                    form_prenom=form_prenom,
                    form_email=form_email,
                    form_tel=form_tel,
                    form_mode_label=form_mode_label,
                    logo_url=logo_url
                ),
                logo_url=logo_url
            )

        except Exception as e:
            return f"<p>Erreur template : {e}</p>"

    # ---------------------------
    # 2) Si fichier non trouvé
    # ---------------------------
    return f"<p>Modèle introuvable : {template_name}</p>"
