"""Admission notices for courses with their own calendar and prerequisites."""
from html import escape, unescape

from branded_email import render_branded_email
from training_programs import SECURITY, program_name
from security_admission import validation_notice

NOTICES = {
    'candidature_validee': ('Votre candidature est validée', 'Votre candidature a été retenue. Vous pouvez maintenant confirmer votre inscription.', 'Confirmer mon inscription'),
    'relance_candidature_validee': ('Confirmation attendue', 'Nous attendons votre confirmation pour poursuivre votre inscription.', 'Confirmer mon inscription'),
    'inscription_confirmee': ('Votre inscription est confirmée', 'Votre inscription a bien été enregistrée.', 'Ouvrir mon espace'),
    'reconfirmation': ('Reconfirmation de votre inscription', 'Merci de nous confirmer que vous souhaitez toujours suivre cette formation.', 'Reconfirmer mon inscription'),
    'relance_reconfirmation': ('Reconfirmation attendue', 'Merci de reconfirmer votre inscription pour cette formation.', 'Reconfirmer mon inscription'),
    'reconfirmation_validee': ('Votre inscription est reconfirmée', 'Nous avons bien pris en compte votre reconfirmation.', 'Ouvrir mon espace'),
    'docs_non_conformes': ('Pièces à compléter', 'Des pièces de votre dossier doivent être remplacées. Retrouvez les précisions dans votre dossier.', 'Remplacer mes pièces'),
    'relance_docs_non_conformes': ('Pièces toujours attendues', 'Nous attendons les pièces demandées pour poursuivre le traitement de votre dossier.', 'Remplacer mes pièces'),
    'certificat': ('Votre certificat de scolarité', 'Votre certificat de scolarité est joint à ce message.', ''),
    'certificat_presentiel': ('Votre certificat de scolarité', 'Votre certificat de scolarité est joint à ce message.', ''),
}


def notice(template, program, first, space, confirmation, *, sms=False):
    if program == SECURITY and template in ('candidature_validee', 'relance_candidature_validee'):
        return validation_notice(first, reminder=template == 'relance_candidature_validee', sms=sms)
    if template == 'reconfirmation_demandee':
        template = 'reconfirmation'
    subject, message, action = NOTICES[template]
    link = confirmation if template in ('candidature_validee','relance_candidature_validee') else space
    title = program_name(unescape(program))
    if sms:
        return f'Intégrale Academy · {title}\nBonjour {first}, {message}' + (f' {link}' if link and action else '')
    content = f'<p>Bonjour {escape(unescape(first or ""))},</p><p><strong>{escape(title)}</strong></p><p>{message}</p>'
    return render_branded_email(subject, content, eyebrow='INTÉGRALE ACADEMY · ADMISSIONS',
                                action_url=unescape(link) if link and action else None, action_label=action)
