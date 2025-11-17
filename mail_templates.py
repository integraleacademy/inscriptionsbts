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

    # === Logo dynamique (utilise BASE_URL si définie sur Render) ===
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # === Contenu des modèles ===
    templates = {
        "accuse_reception": {
    "title": "Confirmation de réception – Votre candidature Parcoursup",
    "content": f"""

        <!-- ===================== -->
        <!--   INTRODUCTION        -->
        <!-- ===================== -->

        <p>Bonjour {prenom},</p>

        <p>
        Nous avons bien reçu votre candidature Parcoursup concernant notre {bts_label} en alternance,
        en présentiel (Puget sur Argens, Var) / 100% en ligne à distance en visioconférence ZOOM.
        Nous vous confirmons que votre candidature a bien été prise en compte et que allons étudier
        votre dossier dans les prochains jours.
        </p>

        <p>
        Notre commission d'admission se réunit toutes les semaines et traite les dossiers par ordre d'arrivée.
        Vous recevrez donc une réponse (avis Favorable ou avis Défavorable) dans un délai de 10 à 15 jours.
        La réponse sera envoyée par mail et par SMS.
        </p>


        <!-- ===================== -->
        <!--   RÉCAPITULATIF       -->
        <!-- ===================== -->

        <div style="background:#fff8e1;border-left:5px solid #f4c45a;padding:18px 22px;border-radius:10px;margin:30px 0;">
            <h3 style="margin-top:0;">🧾 Récapitulatif de l'inscription</h3>

            <p><strong>Numéro de dossier :</strong> {{ numero_dossier }}</p>
            <p><strong>Nom :</strong> {{ nom }}</p>
            <p><strong>Prénom :</strong> {{ prenom }}</p>
            <p><strong>Date de naissance :</strong> {{ date_naissance }}</p>
            <p><strong>Formation choisie :</strong> {bts_label}</p>

            <p><strong>Mode choisi :</strong><br>
            {% if mode == "presentiel" %}
                Présentiel (Puget sur Argens, Var)
            {% else %}
                100% en ligne à distance en visioconférence (ZOOM)
            {% endif %}
            </p>
        </div>


        <!-- ============================= -->
        <!--   📦 SUIVI INSCRIPTION        -->
        <!-- ============================= -->

        <h3 style="margin-top:40px;">📦 Suivi de votre inscription</h3>

        <p>
        Ensuite il faut un suivi comme pour les colis, il faudrait intégrer le suivi comme sur la page
        Espace Candidat (tu veux que je t'envoie le fichier espace candidat pour que tu vois ?)
        </p>

        <p>Retrouvez le suivi de votre inscription depuis votre Espace Candidat :</p>

        <!-- ==== Frise verticale ==== -->

        <div style="margin-top:20px;padding:20px;background:#fafafa;border-radius:12px;border:1px solid #eee;">

            <!-- Étape 1 -->
            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">🕓</div>
                <p style="margin:5px 0 0 0;"><strong>Pré-inscription reçue</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Votre dossier a bien été enregistré.</p>
            </div>

            <!-- Étape 2 -->
            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">📨</div>
                <p style="margin:5px 0 0 0;"><strong>Candidature en cours d’analyse</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Traitement sous 10 à 15 jours.</p>
            </div>

            <!-- Étape 3 -->
            <div style="margin-bottom:18px;">
                <div style="font-size:20px;">✅</div>
                <p style="margin:5px 0 0 0;"><strong>Candidature validée</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">(si avis favorable)</p>
            </div>

            <!-- Étape 4 -->
            <div>
                <div style="font-size:20px;">🎓</div>
                <p style="margin:5px 0 0 0;"><strong>Inscription confirmée</strong></p>
                <p style="margin:3px 0 0 0;color:#555;">Vous rejoindrez officiellement la rentrée 2026.</p>
            </div>

        </div>

        <p style="text-align:center;margin:30px 0;">
            <a href="{lien_espace}" class="btn" style="
                display:inline-block;padding:12px 22px;background:#f4c45a;
                color:#000;border-radius:8px;font-weight:bold;text-decoration:none;">
                👉 Ouvrir mon espace candidat
            </a>
        </p>


        <!-- ===================== -->
        <!--   BLOC DISTANCIEL     -->
        <!-- ===================== -->

        {% if mode == "distanciel" %}
        <h3 style="margin-top:40px;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

        <p>
        ECOLE 100 % en ligne (2 jours par semaine pour tous les BTS sauf MOS 15 jours par mois > affiche selon le BTS) :
        Cette formation se déroule 100 % en ligne à distance en visio-conférence (ZOOM) avec des formateurs expérimentés
        pour les thématiques professionnelles et des enseignants de l'Éducation nationale pour les thématiques générales.
        </p>

        <p>
        Les étudiants suivent un emploi du temps fixe, se connectant à ZOOM à des heures précises et suivent tous les mêmes 
        cours aux mêmes heures. Il n'y a pas de plateforme de e-learning où les cours peuvent être visionnés à tout moment.
        Les interactions sont en temps réel : Grâce à la visioconférence, les étudiants peuvent poser des questions à leurs 
        enseignants, interagir avec les autres étudiants et participer aux mêmes discussions comme s’ils étaient tous réunis 
        dans la même salle de classe.
        </p>

        <p>
        Les deux années de formation se déroulent entièrement à distance, il n'y a pas de déplacements à prévoir.
        Les évaluations et devoirs sont déposés sur l'espace étudiant et sont ensuite corrigés par les enseignants.
        Cette formation offre le même niveau de suivi et d’accompagnement que les formations en présentiel mais avec la 
        possibilité de pouvoir suivre les cours depuis n'importe où grâce aux visioconférences ZOOM.
        </p>

        <p>
        L'examen aura lieu en fin de 2ème année dans un centre d'examen (lycée public).
        </p>

        <p>
        ENTREPRISE (3 jours par semaine pour tous les BTS sauf MOS 15 jours par mois > affiche selon le BTS) :
        En présentiel au sein d'une entreprise.
        </p>
        {% endif %}


        <!-- ===================== -->
        <!--         FAQ           -->
        <!-- ===================== -->

        <h3 style="margin-top:40px;">❓ Questions fréquentes</h3>

        <p>
        J'ai des questions est-il possible d'échanger avec vous ?<br>
        Bien sûr, nous serons ravis de répondre à toutes vos questions lors d'un rendez-vous téléphonique.
        Pour réserver un rendez-vous téléphonique vous pouvez nous contacter au 04 22 47 07 68.
        </p>

        <p>
        Dois-je obligatoirement signer un contrat d'apprentissage avant septembre 2026 ?<br>
        Vous aurez jusqu’au mois de décembre 2026 pour trouver une entreprise d’accueil et signer un contrat d’apprentissage.
        Pas d'inquiétude : la plupart des contrats d’apprentissage se concrétisent après la rentrée entre septembre et novembre.
        Vous pourrez donc commencer les cours au mois de septembre, même si vous n'avez pas encore signé de contrat d'apprentissage.
        </p>

        <p>
        Avez-vous un réseau d'entreprises partenaires ?<br>
        En effet, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation selon votre 
        profil et votre situation géographique. Dès que votre inscription aura été validée, nous vous accompagnerons dans la 
        recherche d'une entreprise pour la signature de votre contrat d'apprentissage.
        </p>

        <p>
        La formation est-elle payante ?<br>
        La formation est totalement gratuite pour les apprentis. Elle est prise en charge par l'Etat lors de la signature du 
        contrat d'apprentissage avec l'entreprise.
        </p>

        <p>
        Quels sont les prérequis ?<br>
        Vous devez être titulaire d'un baccalauréat ou un autre diplôme de niveau 4.
        </p>

        <p>
        Quels sont vos agréments officiels ?<br>
        Notre Centre de Formation des Apprentis (CFA) est agréé par le Ministère de l'Education Nationale
        (UAI Paris : 0756548K - UAI Côte d'Azur : 0831774C) et par le Préfet de la Région PACA (NDA 93830600283).
        Nous sommes certifiés QUALIOPI, le label qui atteste de la qualité des formations proposées.
        Découvrez tous nos agréments en cliquant-ici (lien : https://www.integraleacademy.com/ecole)
        </p>

        <p>
        Vos diplômes sont-ils reconnus par l'Etat ?<br>
        Les diplômes que nous proposons (Brevet de Technicien Supérieur BTS) sont des diplômes officiels délivrés par le
        Ministère de l'Education Nationale. L'examen se déroulera en fin de 2ème année dans un lycée public.
        </p>

        <p>
        Prévoir un encart "Découvrez notre BTS en détails. Téléchargez le Dossier de présentation en cliquant ici"
        (voir lien : https://www.integraleacademy.com/dossiersbts)
        </p>

        <p>
        Vous avez des questions ? Appelez nous au 04 22 47 07 68 ou contactez l'assistance en cliquant ici 
        (mettre un bouton qui renvoie vers : https://assistance-alw9.onrender.com/)
        </p>


        <!-- ===================== -->
        <!--        FOOTER         -->
        <!-- ===================== -->

        <hr style="margin:40px 0;border:none;border-top:1px solid #eee;">

        <p style="font-size:13px;color:#555;line-height:1.5;">
            Intégrale Academy<br>
            54 chemin du Carreou 83480 PUGET SUR ARGENS / 142 rue de Rivoli 75001 PARIS<br>
            SIREN 840 899 884 - NDA 93830600283 - Certification Nationale QUALIOPI : n°03169 en date du 21/10/2024<br>
            UAI Côte d'Azur 0831774C - UAI Paris 0756548K
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


