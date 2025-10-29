# =====================================================
# 📱 Modèles SMS Intégrale Academy
# =====================================================

def sms_text(template, prenom="", bts_label="", lien_espace=""):
    """
    Retourne le message formaté selon le type de SMS demandé.
    Tous les messages utilisent Unicode (emojis et accents OK).
    """
    templates = {
        "accuse_reception": (
            f"🎓 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            f"Nous avons bien reçu votre pré-inscription pour intégrer notre BTS {bts_label}.\n"
            "Nous allons étudier votre dossier et revenir vers vous dans les meilleurs délais.\n"
            "📩 Vous recevrez notre réponse par mail et par SMS (pensez à vérifier vos SPAMS).\n"
            f"🔗 Suivez votre dossier ici : {lien_espace}\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        "candidature_validee": (
            f"✅ Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Bonne nouvelle ! Votre dossier a été validé par notre équipe.\n"
            "Merci de confirmer votre inscription via le lien reçu par mail.\n"
            "📩 Si vous ne le trouvez pas, pensez à vérifier vos SPAMS.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        "inscription_confirmee": (
            f"🎉 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre inscription est maintenant confirmée. Bienvenue à Intégrale Academy !\n"
            "Notre équipe vous contactera prochainement pour les prochaines étapes administratives.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        "reconfirmation_demandee": (
            f"📅 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Merci de reconfirmer votre inscription pour la prochaine rentrée.\n"
            "Consultez le mail reçu et cliquez sur le lien pour valider votre reconfirmation.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        "reconfirmation_validee": (
            f"🎓 Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Votre reconfirmation d’inscription a bien été prise en compte.\n"
            "À très bientôt pour la rentrée chez Intégrale Academy !\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),

        "docs_non_conformes": (
            f"⚠️ Intégrale Academy – Votre BTS {bts_label}\n"
            f"Bonjour {prenom},\n"
            "Certains documents de votre dossier doivent être renvoyés.\n"
            "Consultez le mail reçu pour les détails et renvoyez les pièces demandées.\n"
            "— Intégrale Academy · Service inscriptions BTS"
        ),
    }

    return templates.get(template, "")
