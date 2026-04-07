# =====================================================
# 📱 Modèles SMS – Intégrale Academy (version complète)
# =====================================================

def sms_text(template, prenom="", bts_label="", lien_espace="", lien_confirmation=""):
    """
    Retourne le message formaté selon le type de SMS demandé.
    Tous les messages utilisent Unicode (accents et emojis OK).
    """
    templates = {
        # 📨 Accusé de réception
"accuse_reception": (
    f"🎓 Intégrale Academy – {bts_label}\n"
    f"Bonjour {prenom}, "
    "Je te confirme que nous avons bien reçu ta demande de Pré-inscription concernant notre BTS en alternance. "
    "Nous allons étudier ton dossier et nous te donnerons une réponse prochainement. "
    "📩 Tu recevras notre réponse officielle par mail et par SMS (penses à vérifier tes courriers indésirables). "
    f"🔗 Tu peux suivre les étapes de ton inscription depuis ton Espace Candidat : {lien_espace} "
    "Si tu as des questions, tu peux m'envoyer un message sur WhatsApp : http://wa.me/33744304527 "
    "- Clément VAILLANT · Directeur Intégrale Academy"
),





"candidature_validee": (
    f"🎓 Intégrale Academy – {bts_label}\n"
    f"Bonjour {prenom},\n"
    "Je reviens vers toi concernant notre BTS en alternance ! Nous avons étudié ta candidature et notre commission a donné un AVIS FAVORABLE 🎉 à ta demande d'admission.\n"
    "Pour intégrer notre école, tu dois maintenant confirmer ton inscription ✅.\n"
    f"Tu peux confirmer ton inscription directement en cliquant ici ou via le mail que je viens de t'envoyer : {lien_confirmation}\n"
    "📩 Penses à vérifier tes courriers indésirables.\n"
    "Si tu as des questions, tu peux m'écrire sur WhatsApp ici : http://wa.me/33744304527\n"
    "- Clément VAILLANT · Directeur Intégrale Academy"
),




        # 🎓 Inscription confirmée
    "inscription_confirmee": (
    f"🎓 Intégrale Academy – {bts_label}\n"
    f"Bonjour {prenom},\n"
    "Je te confirme que tu es désormais officiellement inscrit au sein de notre école Intégrale Academy ! 🎉\n"
    "📩 Tu recevras prochainement par courrier ta carte étudiante et ton certificat de scolarité.\n"
    f"🔗 Tu peux suivre les étapes de ton inscription depuis ton Espace Candidat : {lien_espace}\n"
    "💬 Si tu as des questions, tu peux m'envoyer un message sur WhatsApp : http://wa.me/33744304527\n"
    "— Clément VAILLANT · Directeur Intégrale Academy"
),


        # 📅 Reconfirmation demandée
        "reconfirmation_demandee": (
            f"📅 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Merci de reconfirmer votre inscription pour la prochaine rentrée.\n"
            "Consultez le mail reçu et cliquez sur le lien pour valider votre reconfirmation.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # ✅ Reconfirmation validée
        "reconfirmation_validee": (
            f"🎓 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre reconfirmation d’inscription a bien été prise en compte.\n"
            "À très bientôt pour la rentrée chez Intégrale Academy !\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # ⚠️ Documents non conformes
        "docs_non_conformes": (
            f"⚠️ Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Certains documents doivent être renvoyés.\n"
            "Consultez le mail reçu pour les détails et renvoyez les pièces demandées.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # 💌 Reprendre plus tard
        "reprendre_plus_tard": (
            f"💾 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Vous pouvez reprendre votre pré-inscription à tout moment.\n"
            f"🔗 Cliquez ici pour la continuer : {lien_espace}\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # 📜 Certificat de scolarité
        "certificat": (
            f"📜 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre certificat de scolarité est disponible. Vous le trouverez en pièce jointe dans le mail reçu.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # 🏫 Certificat présentiel
        "certificat_presentiel": (
            f"🏫 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre certificat de scolarité (présentiel) vous a été envoyé par mail.\n"
            "À très bientôt sur le campus Intégrale Academy !\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # =====================================================
        # 🔔 RELANCES – SMS dédiés
        # =====================================================
        "relance_candidature_validee": (
            f"🔔 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre candidature est validée ✅ mais nous n’avons pas encore reçu votre confirmation.\n"
            f"Confirmez votre inscription ici 👉 {lien_espace}\n"
            "— Intégrale Academy"
        ),

        "relance_reconfirmation": (
            f"🔁 Intégrale Academy – BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Merci de reconfirmer votre inscription pour la rentrée à venir.\n"
            f"Faites-le maintenant ici 👉 {lien_espace}\n"
            "— Intégrale Academy"
        ),

        "relance_docs_non_conformes": (
            f"⚠️ Intégrale Academy – BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre dossier est incomplet. Merci d’envoyer vos documents manquants dès que possible.\n"
            f"📎 Déposez-les ici : {lien_espace}\n"
            "— Intégrale Academy"
        ),


        # =====================================================
        # 🟢 SMS PARCOURSUP – Import + Relance
        # =====================================================
        "parcoursup_import": (
            f"🎓 Intégrale Academy – {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Nous avons bien reçu votre candidature Parcoursup.\n"
            f"Merci de compléter votre pré-inscription ici 👉 {lien_espace}\n"
            "— Intégrale Academy · Service Parcoursup"
        ),

        "parcoursup_relance": (
            f"📩 Intégrale Academy – {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Nous n’avons pas encore reçu votre confirmation Parcoursup.\n"
            f"Finalisez dès que possible ici 👉 {lien_espace}\n"
            "— Intégrale Academy · Service Parcoursup"
        ),
    }

    return templates.get(template, "")
















