# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version finale unifiée)
# =====================================================

import os
from flask import render_template_string

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")

def mail_html(template_name, **kwargs):
    """Retourne le HTML complet d’un mail avec logo et design unifié."""

    # === Logo dynamique (utilise BASE_URL si définie sur Render) ===
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # === Contenu des modèles ===
    templates = {

                 "accuse_reception": {
    "title": "Accusé de réception – Votre pré-inscription",
    "content": """
<p>Bonjour {{ prenom }},</p>

<p>
Nous avons bien reçu votre pré-inscription pour le <strong>{{ bts_label }}</strong>.
Votre dossier est désormais enregistré et va être examiné par notre équipe dans les prochaines heures.
</p>

<!-- 🔗 ACCÈS ESPACE CANDIDAT -->
<p style="text-align:center;margin:25px 0;">
  <a href="{{ lien_espace }}" class="btn">🔎 Accéder à mon Espace Candidat</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin:28px 0;">

<!-- 📄 RÉCAP -->
<h3 style="margin-top:0;margin-bottom:12px;">📄 Récapitulatif de votre inscription</h3>

<table style="width:100%;border-collapse:collapse;font-size:15px;">
  <tr><td style="padding:6px 0;font-weight:600;">Nom</td><td>{{ form_nom }}</td></tr>
  <tr><td style="padding:6px 0;font-weight:600;">Prénom</td><td>{{ prenom }}</td></tr>
  <tr><td style="padding:6px 0;font-weight:600;">Email</td><td>{{ form_email }}</td></tr>
  <tr><td style="padding:6px 0;font-weight:600;">Téléphone</td><td>{{ form_tel }}</td></tr>
  <tr><td style="padding:6px 0;font-weight:600;">Formation</td><td>{{ bts_label }}</td></tr>
  <tr><td style="padding:6px 0;font-weight:600;">Mode choisi</td><td>{{ mode_label }}</td></tr>
</table>

<hr style="border:none;border-top:1px solid #eee;margin:28px 0;">

<!-- 📦 SUIVI -->
<h3 style="margin-top:0;margin-bottom:12px;">📦 Suivi de votre dossier</h3>

<div style="padding-left:15px;border-left:4px solid #f4c45a;margin-bottom:25px;">
  <p style="margin:8px 0;">1️⃣ Pré-inscription reçue – <strong>✔️ Effectué</strong></p>
  <p style="margin:8px 0;">2️⃣ Analyse de votre candidature – <em>En cours</em></p>
  <p style="margin:8px 0;">3️⃣ Validation de votre candidature</p>
  <p style="margin:8px 0;">4️⃣ Confirmation finale de votre inscription</p>
</div>

<p>
Votre espace candidat sera automatiquement mis à jour à chaque nouvelle étape.
</p>

<p style="text-align:center;margin-top:25px;">
  <a href="{{ lien_espace }}" class="btn">🔎 Voir mon suivi</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin:28px 0;">

<!-- 📘 DOCUMENT BTS -->
<h3 style="margin-top:0;margin-bottom:12px;">📘 Découvrez notre BTS en détails</h3>

<p>Téléchargez le dossier de présentation complet :</p>

<p style="text-align:center;margin-top:12px;">
  <a href="https://www.integraleacademy.com/dossiersbts" class="btn">📘 Télécharger le dossier BTS</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin:28px 0;">

<!-- 🛟 ASSISTANCE -->
<h3 style="margin-top:0;margin-bottom:12px;">Besoin d’aide ?</h3>
<p>
Notre équipe est disponible pour vous accompagner si besoin.
</p>

<p style="text-align:center;margin-top:12px;">
  <a href="https://assistance-alw9.onrender.com/" class="btn">🛟 Contacter l’assistance</a>
</p>

<p style="text-align:center;margin-top:10px;font-weight:600;font-size:16px;">
  📞 04 22 47 07 68
</p>
"""
},



        "candidature_validee": {
            "title": "Candidature validée",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Bonne nouvelle 🎉 Votre candidature au <strong>{{ bts_label }}</strong> a été validée.</p>
                <p>Merci de confirmer votre inscription :</p>
                <p><a href="{{ lien_espace }}" class="btn">Confirmer mon inscription</a></p>
            """
        },

        "inscription_confirmee": {
            "title": "Inscription confirmée",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Votre inscription au <strong>{{ bts_label }}</strong> est désormais confirmée ✅.</p>
                <p>Bienvenue à Intégrale Academy 🎓 !</p>
            """
        },

        "reconfirmation": {
            "title": "Reconfirmation d’inscription",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Merci de confirmer à nouveau votre inscription pour le <strong>{{ bts_label }}</strong>.</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{{ lien_espace }}" class="btn">Reconfirmer mon inscription ✅</a>
                </p>
                <p>À très bientôt chez Intégrale Academy.</p>
            """
        },

        "reconfirmation_demandee": {
            "title": "Reconfirmation demandée",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir.</p>
                <p><a href="{{ lien_espace }}" class="btn">Reconfirmer mon inscription</a></p>
            """
        },

        "reconfirmation_validee": {
            "title": "Reconfirmation validée",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Votre reconfirmation d’inscription a bien été enregistrée ✅.</p>
                <p>À très bientôt pour la rentrée chez Intégrale Academy.</p>
            """
        },

        "docs_non_conformes": {
            "title": "Documents non conformes",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Certains documents ne sont pas conformes pour le <strong>{{ bts_label }}</strong>.</p>
                <p>Merci de les renvoyer dès que possible :</p>
                <p><a href="{{ lien_espace }}" class="btn">Envoyer mes nouvelles pièces</a></p>
            """
        },

        "reprendre_plus_tard": {
            "title": "Reprendre ma pré-inscription",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Vous pouvez reprendre votre pré-inscription pour le <strong>{{ bts_label }}</strong> à tout moment.</p>
                <p><a href="{{ lien_espace }}" class="btn">Reprendre maintenant</a></p>
            """
        },

        "certificat": {
            "title": "Votre certificat de scolarité",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{{ bts_label }}</strong>.</p>
                <p>Conservez-le précieusement.</p>
            """
        },

        "certificat_presentiel": {
            "title": "Certificat de scolarité (présentiel)",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{{ bts_label }}</strong>.</p>
                <p>À très bientôt sur le campus !</p>
            """
        },

        "bienvenue": {
            "title": "Bienvenue à Intégrale Academy 🎓",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Nous sommes ravis de vous accueillir au sein d’<strong>Intégrale Academy</strong>.</p>
                <p>Votre inscription au <strong>{{ bts_label }}</strong> est désormais finalisée.</p>
                <p><a href="{{ lien_espace }}" class="btn">Accéder à mon espace</a></p>
            """
        },

        "parcoursup_import": {
            "title": "Votre candidature Parcoursup – Intégrale Academy",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Nous avons bien reçu votre candidature Parcoursup pour le BTS <strong>{{ bts_label }}</strong>.</p>
                <p>Merci de compléter votre pré-inscription dès maintenant via le lien ci-dessous :</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{{ lien_espace }}" style="background:#f4c45a;color:black;padding:10px 16px;
                      border-radius:6px;text-decoration:none;font-weight:bold;">
                    👉 Compléter ma pré-inscription
                  </a>
                </p>
                <p>À bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

        "parcoursup_relance": {
            "title": "Relance – Votre dossier Parcoursup",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Nous n’avons pas encore reçu votre confirmation Parcoursup pour le BTS 
                <strong>{{ bts_label }}</strong>.</p>
                <p>Merci de finaliser votre pré-inscription dès que possible :</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{{ lien_espace }}" style="background:#f4c45a;color:black;padding:10px 16px;
                      border-radius:6px;text-decoration:none;font-weight:bold;">
                    👉 Finaliser ma pré-inscription
                  </a>
                </p>
                <p>Bien cordialement,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

                # =====================================================
        # 🔔 RELANCES (mail + SMS)
        # =====================================================

        "relance_candidature_validee": {
            "title": "Relance – Confirmez votre inscription au BTS",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Votre candidature au <strong>{{ bts_label }}</strong> a bien été validée ✅ 
                mais nous n’avons pas encore reçu votre confirmation.</p>
                <p>Merci de cliquer sur le lien ci-dessous pour finaliser votre inscription :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{{ lien_espace }}" class="btn">👉 Confirmer mon inscription</a>
                </p>
                <p>Sans réponse de votre part, votre place pourrait être proposée à un autre candidat.</p>
                <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

        "relance_reconfirmation": {
            "title": "Relance – Reconfirmez votre inscription à Intégrale Academy",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Nous n’avons pas encore reçu votre <strong>reconfirmation</strong> d’inscription 
                pour le <strong>{{ bts_label }}</strong>.</p>
                <p>Merci de valider dès maintenant votre présence à la rentrée :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{{ lien_espace }}" class="btn">🔁 Reconfirmer mon inscription</a>
                </p>
                <p>Sans validation rapide, votre dossier pourrait être suspendu.</p>
                <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

        "relance_docs_non_conformes": {
            "title": "Relance – Documents à compléter",
            "content": """
                <p>Bonjour {{ prenom }},</p>
                <p>Certains documents de votre dossier pour le <strong>{{ bts_label }}</strong> 
                sont encore manquants ou non conformes ⚠️.</p>
                <p>Merci de les renvoyer dès que possible afin que votre dossier puisse être validé :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{{ lien_espace }}" class="btn">📎 Envoyer mes nouvelles pièces</a>
                </p>
                <p>Notre équipe reste disponible si besoin d’aide.<br><b>Intégrale Academy</b></p>
            """
        },

        # =====================================================
        # 🤝 MAIL PÔLE ALTERNANCE – Notification interne
        # =====================================================

        "pole_alternance": {
            "title": "Nouveau candidat – accompagnement Pôle Alternance",
            "content": """
                <p>Bonjour Clément 👋,</p>
                <p>Un nouveau candidat a indiqué souhaiter être accompagné par le 
                <strong>Pôle Alternance Île-de-France</strong>.</p>

                <p>Voici les documents transmis :</p>
                <ul>
                  <li>📄 <strong>CV</strong> en pièce jointe</li>
                  <li>📝 <strong>Lettre de motivation</strong> en pièce jointe</li>
                  <li>📋 <strong>Fiche PDF du candidat</strong> également jointe</li>
                </ul>

                <p style="margin-top:20px;">
                  Ce dossier est prêt à être transmis à votre contact au Pôle Alternance.
                </p>

                <p>Bonne journée ☀️<br><b>L’équipe Intégrale Academy</b></p>
            """
        }

    }  # 👈 fin du dictionnaire des templates

    # === Vérification : modèle existe ? ===
    tpl = templates.get(template_name)
    if not tpl:
        return f"<p>Modèle inconnu : {template_name}</p>"

    # === Lecture du modèle de base ===
    try:
        with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
            base_html = f.read()
    except FileNotFoundError:
        return tpl["content"]

    # === Rendu final complet ===
    # On injecte toutes les variables passées (nom, prenom, numero_dossier, mode, etc.)
    return render_template_string(
        base_html,
        email_title=tpl["title"],
        email_content=tpl["content"],
        logo_url=logo_url,
        **kwargs
    )





