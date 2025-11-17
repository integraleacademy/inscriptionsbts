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
            "title": "Confirmation de réception – Votre candidature Parcoursup",
            "content": """

        <p>Bonjour {{ prenom }},</p>

        <p>
        Nous avons bien reçu votre candidature Parcoursup concernant notre {{ bts_label }} en alternance,
        en présentiel (Puget sur Argens, Var) / 100% en ligne à distance en visioconférence ZOOM.
        Nous vous confirmons que votre candidature a bien été prise en compte et que allons étudier
        votre dossier dans les prochains jours.
        </p>

        <p>
        Notre commission d'admission se réunit toutes les semaines et traite les dossiers par ordre d'arrivée.
        Vous recevrez donc une réponse (avis Favorable ou avis Défavorable) dans un délai de 10 à 15 jours.
        La réponse sera envoyée par mail et par SMS.
        </p>

        <div style="background:#fff8e1;border-left:5px solid #f4c45a;padding:18px 22px;
                    border-radius:10px;margin:30px 0;">
            <h3 style="margin-top:0;">🧾 Récapitulatif de l'inscription</h3>

            <p><strong>Numéro de dossier :</strong> {{ numero_dossier }}</p>
            <p><strong>Nom :</strong> {{ nom }}</p>
            <p><strong>Prénom :</strong> {{ prenom }}</p>
            <p><strong>Date de naissance :</strong> {{ date_naissance }}</p>
            <p><strong>Formation choisie :</strong> {{ bts_label }}</p>

            <p><strong>Mode choisi :</strong><br>
            {% if mode == "presentiel" %}
                Présentiel (Puget sur Argens, Var)
            {% else %}
                100% en ligne à distance en visioconférence (ZOOM)
            {% endif %}
            </p>
        </div>

        <h3 style="margin-top:40px;">📦 Suivi de votre inscription</h3>
        <p>Retrouvez le suivi de votre inscription depuis votre Espace Candidat :</p>

        <div style="margin-top:20px;padding:20px;background:#fafafa;border-radius:12px;
                    border:1px solid #eee;">

            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">🕓</div>
                <p style="margin:5px 0 0 0;"><strong>Pré-inscription reçue</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Votre dossier a bien été enregistré.</p>
            </div>

            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">📨</div>
                <p style="margin:5px 0 0 0;"><strong>Candidature en cours d’analyse</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Traitement sous 10 à 15 jours.</p>
            </div>

            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">✅</div>
                <p style="margin:5px 0 0 0;"><strong>Candidature validée</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">(si avis favorable)</p>
            </div>

            <div>
                <div style="font-size:20px;">🎓</div>
                <p style="margin:5px 0 0 0;"><strong>Inscription confirmée</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Vous rejoindrez officiellement la rentrée 2026.</p>
            </div>
        </div>

        <p style="text-align:center;margin:30px 0;">
            <a href="{{ lien_espace }}" class="btn" style="
                display:inline-block;padding:12px 22px;background:#f4c45a;
                color:#000;border-radius:8px;font-weight:bold;text-decoration:none;">
                👉 Ouvrir mon espace candidat
            </a>
        </p>

        {% if mode == "distanciel" %}
        <h3 style="margin-top:40px;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

        <p>
        ECOLE 100 % en ligne (2 jours par semaine pour tous les BTS sauf MOS 15 jours par mois).
        Formation en visio-conférence ZOOM, en direct, avec enseignants de l'Éducation nationale.
        </p>

        <p>
        Les étudiants suivent un emploi du temps fixe, se connectent à ZOOM à des heures précises
        et suivent tous les mêmes cours aux mêmes heures. Pas de plateforme e-learning,
        les interactions sont 100% en direct.
        </p>

        <p>
        Les deux années de formation sont entièrement à distance. Les évaluations sont déposées
        sur l'espace étudiant. Aucun déplacement. L’examen a lieu en fin de 2ᵉ année dans un lycée public.
        </p>

        <p>
        ENTREPRISE (3 jours/semaine, ou 15 jours/mois pour MOS) :  
        En présentiel en entreprise.
        </p>
        {% endif %}

        <h3 style="margin-top:40px;">❓ Questions fréquentes</h3>

        <p>
        J'ai des questions ? Appelez le 04 22 47 07 68 pour réserver un rendez-vous téléphonique.
        </p>

        <p>
        Dois-je signer un contrat avant septembre 2026 ?  
        Non : vous avez jusqu'à décembre 2026. Vous pouvez commencer les cours sans entreprise.
        </p>

        <p>
        Avez-vous des entreprises partenaires ? Oui, dans toute la France.
        Nous vous accompagnerons après validation de la pré-inscription.
        </p>

        <p>
        La formation est-elle payante ?  
        Non, totalement gratuite pour les apprentis (prise en charge par l'État).
        </p>

        <p>
        Prérequis : être titulaire d'un bac ou diplôme niveau 4.
        </p>

        <p>
        Agréments officiels : CFA agréé Ministère Éducation Nationale (UAI Paris 0756548K –
        UAI Côte d’Azur 0831774C), Préfet PACA (NDA 93830600283), Qualiopi.
        </p>

        <p>
        Diplômes reconnus par l'État : examen officiel en fin de 2ᵉ année.
        </p>

        <p>
        Dossier BTS à télécharger :  
        <a href="https://www.integraleacademy.com/dossiersbts">https://www.integraleacademy.com/dossiersbts</a>
        </p>

        <p>
        Assistance :  
        <a href="https://assistance-alw9.onrender.com/">https://assistance-alw9.onrender.com/</a>
        </p>

        <hr style="margin:40px 0;border:none;border-top:1px solid #eee;">
        <p style="font-size:13px;color:#555;line-height:1.5;">
            Intégrale Academy<br>
            54 chemin du Carreou 83480 PUGET SUR ARGENS / 142 rue de Rivoli 75001 PARIS<br>
            SIREN 840899884 - NDA 93830600283 - Qualiopi n°03169<br>
            UAI 0831774C / 0756548K
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



