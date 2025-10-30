# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy
# =====================================================

def mail_html(template_name, **kwargs):
    """Retourne le HTML d’un mail selon le nom du template."""

    prenom = kwargs.get("prenom", "")
    bts_label = kwargs.get("bts_label", "")
    lien_espace = kwargs.get("lien_espace", "#")

    templates = {
        "accuse_reception": f"""
        <p>Bonjour {prenom},</p>
        <p>Nous avons bien reçu votre pré-inscription pour le <strong>{bts_label}</strong>.</p>
        <p>Notre équipe va étudier votre dossier et vous contactera rapidement.</p>
        <p>➡️ Vous pouvez suivre l’évolution de votre dossier ici : <a href="{lien_espace}">{lien_espace}</a></p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        "candidature_validee": f"""
        <p>Bonjour {prenom},</p>
        <p>Bonne nouvelle 🎉 ! Votre candidature au <strong>{bts_label}</strong> a été validée.</p>
        <p>Merci de confirmer votre inscription en cliquant sur le lien reçu par mail.</p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        "inscription_confirmee": f"""
        <p>Bonjour {prenom},</p>
        <p>Votre inscription au <strong>{bts_label}</strong> est désormais confirmée ✅.</p>
        <p>Bienvenue à Intégrale Academy 🎓 !</p>
        """,

        "reconfirmation_demandee": f"""
        <p>Bonjour {prenom},</p>
        <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir en suivant les instructions reçues.</p>
        <p>— L’équipe Intégrale Academy</p>
        """,

        "docs_non_conformes": f"""
        <p>Bonjour {prenom},</p>
        <p>Certains de vos documents ne sont pas conformes pour le <strong>{bts_label}</strong>.</p>
        <p>Merci de les renvoyer dès que possible via le lien reçu par mail.</p>
        """,
    }

    return templates.get(template_name, f"<p>Modèle inconnu : {template_name}</p>")
