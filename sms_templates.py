# =====================================================
# 📱 Modèles SMS – Intégrale Academy (version complète)
# =====================================================

def sms_text(template, prenom="", bts_label="", lien_espace=""):
    """
    Retourne le message formaté selon le type de SMS demandé.
    Tous les messages utilisent Unicode (accents et emojis OK).
    """
    templates = {
        # 📨 Accusé de réception
        "accuse_reception": (
            f"🎓 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Nous avons bien reçu votre pré-inscription pour intégrer notre BTS.\n"
            "Nous allons étudier votre dossier et revenir vers vous dans les meilleurs délais.\n"
            "📩 Vous recevrez notre réponse par mail et par SMS (pensez à vérifier vos SPAMS).\n"
            f"🔗 Suivez votre dossier ici : {lien_espace}\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # ✅ Candidature validée
        "candidature_validee": (
            f"✅ Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Bonne nouvelle ! Votre candidature a été validée par notre équipe.\n"
            "Merci de confirmer votre inscription via le lien reçu par mail.\n"
            "📩 Pensez à vérifier vos SPAMS.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        # 🎓 Inscription confirmée
        "inscription_confirmee": (
            f"🎉 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre inscription est confirmée. Bienvenue à Intégrale Academy !\n"
            "Notre équipe vous contactera prochainement pour la suite administrative.\n"
            "— Intégrale Academy · Service inscriptions BTS"
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
        # 🟢 SMS PARCOURSUP – Import + Relance
        # =====================================================
        "parcoursup_import": (
            f"🎓 Intégrale Academy – BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Nous avons bien reçu votre candidature Parcoursup.\n"
            f"Merci de compléter votre pré-inscription ici 👉 {lien_espace}\n"
            "— Intégrale Academy · Service Parcoursup"
        ),

        "parcoursup_relance": (
            f"📩 Intégrale Academy – BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Nous n’avons pas encore reçu votre confirmation Parcoursup.\n"
            f"Finalisez dès que possible ici 👉 {lien_espace}\n"
            "— Intégrale Academy · Service Parcoursup"
        ),
    }

    return templates.get(template, "")


