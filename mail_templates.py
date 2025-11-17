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
    "title": "Confirmation de réception de votre candidature",
    "content": f"""
        <p>Bonjour {prenom},</p>

        <!-- ✉️ TEXTE INTRO DE CLÉMENT -->
        <p>
        Nous avons bien reçu votre candidature concernant notre <strong>{bts_label}</strong> 
        en alternance, en présentiel (Puget sur Argens, Var) / 100% en ligne à distance en visioconférence ZOOM.
        Nous vous confirmons que votre candidature a bien été prise en compte et que nous allons étudier 
        votre dossier dans les prochains jours.
        </p>

        <p>
        Notre commission d'admission se réunit toutes les semaines et traite les dossiers par ordre d'arrivée. 
        Vous recevrez donc une réponse (<strong>avis Favorable</strong> ou <strong>avis Défavorable</strong>) dans un délai de 
        <strong>10 à 15 jours</strong>. La réponse sera envoyée par <strong>mail</strong> et par <strong>SMS</strong>.
        </p>

        <!-- 🧾 RÉCAP DU DOSSIER -->
        <table width="100%" cellpadding="0" cellspacing="0" 
            style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:22px 0;">
          <tr>
            <td style="font-weight:600;padding-bottom:8px;font-size:15px;">
              📄 Récapitulatif de votre candidature :
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

        <!-- 🔗 REDIRECTION UNIQUE -->
        <p style="margin-top:25px;margin-bottom:10px;font-weight:600;font-size:15px;">
          📌 Suivez les étapes de votre inscription directement depuis votre Espace Candidat :
        </p>

        <p style="text-align:center;margin-top:10px;">
            <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
        </p>
    """
        + (
        # 🖥️ SI DISTANCIEL → AJOUT DU BLOC FORMATION EN LIGNE
        """
        <!-- 💻 BLOC FORMATION 100% EN LIGNE (affiché uniquement si distanciel) -->
        <div style="background:#f3f7ff;border-left:4px solid #2b6cff;padding:18px;margin-top:30px;border-radius:10px;">
          <h3 style="margin:0 0 10px 0;color:#2b6cff;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

          <p style="margin:0 0 10px 0;">
          <strong>ÉCOLE 100 % en ligne :</strong><br>
          Cette formation se déroule entièrement en visio-conférence (ZOOM) avec des formateurs expérimentés. 
          Les étudiants suivent un emploi du temps fixe, se connectent à des horaires précis 
          et interagissent en temps réel avec leurs enseignants et les autres étudiants.
          </p>

          <p style="margin:0 0 10px 0;">
          Il ne s’agit pas d’une plateforme e-learning : les cours ne sont pas en libre accès, 
          tout se déroule en direct comme dans une vraie classe.
          </p>

          <p style="margin:0 0 10px 0;">
          Les deux années sont intégralement à distance (aucun déplacement). 
          Les évaluations et devoirs sont déposés sur l’espace étudiant, puis corrigés par les enseignants.
          </p>

          <p style="margin:0 0 10px 0;">
          L’examen final se déroule en fin de 2e année dans un centre d’examen public (lycée).
          </p>

          <p style="margin:0 0 0 0;">
          <strong>ENTREPRISE :</strong><br>
          En présentiel au sein de l’entreprise (alternance).
          </p>
        </div>
        """
        if "distance" in form_mode_label.lower() or "en ligne" in form_mode_label.lower() or "dist" in form_mode_label.lower()
        else ""
        )
        + 
        """
        <!-- ❓ FAQ COMPACTE -->
        <div style="margin-top:32px;padding:18px;background:#fafafa;border-radius:10px;border:1px solid #eee;">
          <h3 style="margin-top:0;color:#444;">❓ Questions fréquentes</h3>

          <p><strong>J'ai des questions, est-il possible d'échanger avec vous ?</strong><br>
          Oui, avec plaisir 😊 Vous pouvez nous contacter au <strong>04 22 47 07 68</strong> pour réserver un rendez-vous téléphonique.</p>

          <p><strong>Dois-je obligatoirement signer un contrat d’apprentissage avant septembre 2026 ?</strong><br>
          Non — vous avez jusqu’à <strong>décembre 2026</strong>. La majorité des contrats se signent entre septembre et novembre.</p>

          <p><strong>Avez-vous un réseau d'entreprises partenaires ?</strong><br>
          Oui, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation selon votre profil.</p>

          <p><strong>La formation est-elle payante ?</strong><br>
          Non, elle est 100% prise en charge dans le cadre d’un contrat d’apprentissage.</p>

          <p><strong>Quels sont les prérequis ?</strong><br>
          Avoir un <strong>baccalauréat</strong> ou un diplôme de niveau 4.</p>

          <p><strong>Quels sont vos agréments officiels ?</strong><br>
          CFA agréé Education Nationale (UAI Paris 0756548K / UAI Côte d’Azur 0831774C), 
          NDA 93830600283, certification <strong>QUALIOPI</strong>. 
          <a href="https://www.integraleacademy.com/ecole" style="color:#f4c45a;">Cliquez ici</a> pour les voir.</p>

          <p><strong>Vos diplômes sont-ils reconnus ?</strong><br>
          Oui, ce sont des diplômes d’État délivrés par le Ministère de l’Éducation Nationale.</p>
        </div>

        <!-- 📘 DOSSIER BTS -->
        <div style="margin-top:28px;text-align:center;">
          <a href="https://www.integraleacademy.com/dossiersbts" 
             class="btn" 
             style="background:#f4c45a;color:#000;font-weight:600;">
             📘 Télécharger le dossier de présentation BTS
          </a>
        </div>

        <!-- 🆘 ASSISTANCE -->
        <div style="margin-top:24px;text-align:center;">
          <p style="margin-bottom:10px;">Vous avez une question ?</p>
          <a href="https://assistance-alw9.onrender.com/" 
             class="btn" 
             style="background:#222;color:#fff;">
             🆘 Contacter l'assistance
          </a>
        </div>

        <p style="margin-top:30px;">
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



