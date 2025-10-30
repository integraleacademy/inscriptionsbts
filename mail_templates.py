# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy
# =====================================================

def mail_html(template_name, **kwargs):
    """Retourne le HTML d’un mail selon le nom du template."""

    prenom = kwargs.get("prenom", "")
    bts_label = kwargs.get("bts_label", "")
    lien_espace = kwargs.get("lien_espace", "#")

    templates = {

        # 📨 Accusé de réception
        "accuse_reception": f"""
        <h2>Intégrale Academy – Confirmation de réception</h2>
        <p>Bonjour {prenom},</p>
        <p>Nous avons bien reçu votre pré-inscription pour le <strong>{bts_label}</strong>.</p>
        <p>Notre équipe va étudier votre dossier et vous contactera rapidement.</p>
        <p>➡️ Vous pouvez suivre l’évolution de votre dossier ici : 
           <a href="{lien_espace}">{lien_espace}</a></p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # ✅ Candidature validée
        "candidature_validee": f"""
        <h2>Intégrale Academy – Candidature validée</h2>
        <p>Bonjour {prenom},</p>
        <p>Bonne nouvelle 🎉 ! Votre candidature au <strong>{bts_label}</strong> a été validée.</p>
        <p>Merci de confirmer votre inscription en cliquant sur le lien ci-dessous :</p>
        <p><a href="{lien_espace}">👉 Confirmer mon inscription</a></p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 🎓 Inscription confirmée
        "inscription_confirmee": f"""
        <h2>Intégrale Academy – Inscription confirmée</h2>
        <p>Bonjour {prenom},</p>
        <p>Votre inscription au <strong>{bts_label}</strong> est désormais confirmée ✅.</p>
        <p>Bienvenue à Intégrale Academy 🎓 !</p>
        <p>Notre équipe vous contactera prochainement pour la suite.</p>
        """,

        # 🔁 Reconfirmation demandée
        "reconfirmation_demandee": f"""
        <h2>Intégrale Academy – Reconfirmation demandée</h2>
        <p>Bonjour {prenom},</p>
        <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir.</p>
        <p>👉 Cliquez sur le lien reçu pour finaliser votre reconfirmation.</p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 📄 Documents non conformes
        "docs_non_conformes": f"""
        <h2>Intégrale Academy – Documents non conformes</h2>
        <p>Bonjour {prenom},</p>
        <p>Certains de vos documents ne sont pas conformes pour le <strong>{bts_label}</strong>.</p>
        <p>Merci de les renvoyer dès que possible via le lien suivant :</p>
        <p><a href="{lien_espace}">➡️ Envoyer mes nouvelles pièces</a></p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 💌 Reprendre plus tard
        "reprendre_plus_tard": f"""
        <h2>Intégrale Academy – Reprendre ma pré-inscription</h2>
        <p>Bonjour {prenom},</p>
        <p>Vous pouvez reprendre votre pré-inscription pour le <strong>{bts_label}</strong> à tout moment.</p>
        <p>👉 Cliquez ici pour la continuer : <a href="{lien_espace}">{lien_espace}</a></p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 📜 Certificat distanciel
        "certificat": f"""
        <h2>Intégrale Academy – Certificat de scolarité</h2>
        <p>Bonjour {prenom},</p>
        <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
        <p>Conservez-le précieusement pour vos démarches administratives.</p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 🏫 Certificat présentiel
        "certificat_presentiel": f"""
        <h2>Intégrale Academy – Certificat de scolarité (présentiel)</h2>
        <p>Bonjour {prenom},</p>
        <p>Veuillez trouver en pièce jointe votre certificat de scolarité (présentiel) pour le <strong>{bts_label}</strong>.</p>
        <p>À très bientôt sur le campus !</p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        # 🎓 Bienvenue
        "bienvenue": f"""
        <h2>Bienvenue à Intégrale Academy 🎓</h2>
        <p>Bonjour {prenom},</p>
        <p>Nous sommes ravis de vous accueillir au sein d’Intégrale Academy.</p>
        <p>Votre inscription au <strong>{bts_label}</strong> est désormais finalisée.</p>
        <p>Notre équipe vous contactera très prochainement pour la suite de votre intégration.</p>
        <p>— L’équipe Intégrale Academy</p>
        """,
    }

    return templates.get(template_name, f"<p>Modèle inconnu : {template_name}</p>")
