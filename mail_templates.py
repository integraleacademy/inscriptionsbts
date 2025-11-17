# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version finale unifiée)
# =====================================================

import os
from flask import render_template_string

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")

def mail_html(template_name, **kwargs):
    """Retourne le HTML complet d’un mail avec logo et design unifié."""

    # === Variables de base ===
    prenom = kwargs.get("prenom", "") or ""
    bts_label = kwargs.get("bts_label", "") or ""
    lien_espace = kwargs.get("lien_espace", "#") or "#"

    # 🔹 Variables pour le récap
    numero_dossier   = kwargs.get("numero_dossier", "") or ""
    form_nom         = kwargs.get("form_nom", "") or ""
    form_prenom      = kwargs.get("form_prenom", "") or ""
    form_email       = kwargs.get("form_email", "") or ""
    form_tel         = kwargs.get("form_tel", "") or ""
    form_mode_label  = kwargs.get("form_mode_label", "") or ""


    # === Logo dynamique (utilise BASE_URL si définie sur Render) ===
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # === Contenu des modèles ===
    templates = {
                "accuse_reception": {
            "title": "Confirmation de réception",
            "content": f"""
                <p>Bonjour {prenom},</p>

                <p>Nous avons bien reçu votre pré-inscription pour le 
                <strong>{bts_label}</strong>. Merci pour votre confiance.</p>

                <!-- 🧾 RÉCAP COMPLET DU DOSSIER -->
                <table width="100%" cellpadding="0" cellspacing="0" 
                       style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:18px 0;">
                  <tr>
                    <td style="font-weight:600;padding-bottom:8px;">
                      📄 Récapitulatif de votre demande :
                    </td>
                  </tr>
                  <tr>
                    <td style="padding-left:4px;font-size:14px;line-height:1.6;">
                      <div><strong>Numéro de dossier :</strong> {numero_dossier}</div>
                      <div><strong>Nom :</strong> {form_nom}</div>
                      <div><strong>Prénom :</strong> {form_prenom}</div>
                      <div><strong>Email :</strong> {form_email}</div>
                      <div><strong>Téléphone :</strong> {form_tel}</div>
                      <div><strong>Formation :</strong> {bts_label}</div>
                      <div><strong>Mode :</strong> {form_mode_label}</div>
                    </td>
                  </tr>
                </table>

                <!-- 🚀 SUIVI ÉTAPES (style proche de l’espace candidat) -->
                <p style="margin-top:22px;margin-bottom:10px;font-weight:600;">
                  🚀 Suivi de votre dossier
                </p>

                <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;line-height:1.6;">
                  <tr>
                    <td width="26" valign="top" align="center">🟢</td>
                    <td>
                      <strong>Pré-inscription reçue</strong><br>
                      <span style="color:#555;">Votre formulaire a bien été enregistré.</span>
                    </td>
                  </tr>
                  <tr><td colspan="2" style="font-size:12px;color:#bbb;padding:4px 0 4px 26px;">➜</td></tr>

                  <tr>
                    <td width="26" valign="top" align="center">🟡</td>
                    <td>
                      <strong>Candidature en cours d’analyse</strong><br>
                      <span style="color:#555;">Notre équipe pédagogique étudie actuellement votre dossier.</span>
                    </td>
                  </tr>
                  <tr><td colspan="2" style="font-size:12px;color:#bbb;padding:4px 0 4px 26px;">➜</td></tr>

                  <tr>
                    <td width="26" valign="top" align="center">⚪</td>
                    <td>
                      <strong>Candidature validée</strong><br>
                      <span style="color:#777;">Vous recevrez un mail pour confirmer définitivement votre inscription.</span>
                    </td>
                  </tr>
                  <tr><td colspan="2" style="font-size:12px;color:#bbb;padding:4px 0 4px 26px;">➜</td></tr>

                  <tr>
                    <td width="26" valign="top" align="center">⚪</td>
                    <td>
                      <strong>Inscription confirmée</strong><br>
                      <span style="color:#777;">Votre place est réservée à Intégrale Academy.</span>
                    </td>
                  </tr>
                  <tr><td colspan="2" style="font-size:12px;color:#bbb;padding:4px 0 4px 26px;">➜</td></tr>

                  <tr>
                    <td width="26" valign="top" align="center">⚪</td>
                    <td>
                      <strong>Rentrée septembre 2026</strong><br>
                      <span style="color:#777;">Nous aurons le plaisir de vous accueillir à la rentrée.</span>
                    </td>
                  </tr>
                </table>

                <!-- 🔘 Ouvrir l’espace -->
                <p style="text-align:center;margin-top:22px;">
                    <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
                </p>

                <p style="margin-top:20px;">
                    À très bientôt,<br>
                    <strong>L’équipe Intégrale Academy</strong>
                </p>
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
        },

                # =====================================================
        # 🔔 RELANCES (mail + SMS)
        # =====================================================
        "relance_candidature_validee": {
            "title": "Relance – Confirmez votre inscription au BTS",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Votre candidature au <strong>{bts_label}</strong> a bien été validée ✅ mais nous n’avons pas encore reçu votre confirmation.</p>
                <p>Merci de cliquer sur le lien ci-dessous pour finaliser votre inscription :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{lien_espace}" class="btn">👉 Confirmer mon inscription</a>
                </p>
                <p>Sans réponse de votre part, votre place pourrait être proposée à un autre candidat.</p>
                <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },
        "relance_reconfirmation": {
            "title": "Relance – Reconfirmez votre inscription à Intégrale Academy",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous n’avons pas encore reçu votre <strong>reconfirmation</strong> d’inscription pour le <strong>{bts_label}</strong>.</p>
                <p>Merci de valider dès maintenant votre présence à la rentrée :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{lien_espace}" class="btn">🔁 Reconfirmer mon inscription</a>
                </p>
                <p>Sans validation rapide, votre dossier pourrait être suspendu.</p>
                <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },
        "relance_docs_non_conformes": {
            "title": "Relance – Documents à compléter",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Certains documents de votre dossier pour le <strong>{bts_label}</strong> sont encore manquants ou non conformes ⚠️.</p>
                <p>Merci de les renvoyer dès que possible afin que votre dossier puisse être validé :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{lien_espace}" class="btn">📎 Envoyer mes nouvelles pièces</a>
                </p>
                <p>Notre équipe reste disponible si besoin d’aide.<br><b>Intégrale Academy</b></p>
            """
        },

        # =====================================================
        # 🤝 MAIL PÔLE ALTERNANCE – Notification interne
        # =====================================================
        "pole_alternance": {
            "title": "Nouveau candidat – accompagnement Pôle Alternance",
            "content": f"""
                <p>Bonjour Clément 👋,</p>
                <p>Un nouveau candidat a indiqué souhaiter être accompagné par le <strong>Pôle Alternance Île-de-France</strong>.</p>
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
    }  # 👈 ici on ferme le dictionnaire, proprement.

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

    # === Rendu final complet ===
    return render_template_string(
        base_html,
        email_title=tpl["title"],
        email_content=tpl["content"],
        logo_url=logo_url
    )

