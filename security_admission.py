"""Interview invitation for validated security apprenticeship applications."""
from html import unescape
from urllib.parse import urlencode

from branded_email import _environment, academy_logo_url, render_branded_email
from school_email import SENDERS


# Professional contacts published in the security application receipt and guide.
ADVISER = {
    **SENDERS['aurelie'],
    'name': 'Aurélie BAYARD-CHAUSSEZ',
    'role': 'Chargée des relations clients',
    'mobile': '07 69 39 04 57',
    'mobile_link': '+33769390457',
}


def validation_subject(*, reminder=False):
    if reminder:
        return 'Parcours sécurité en alternance · Pensez à programmer votre entretien'
    return 'Votre candidature est validée · Parcours sécurité en alternance'


def validation_notice(first, *, reminder=False, sms=False):
    first = unescape(first or '')
    if sms:
        return (f'Intégrale Academy · Bonjour {first}, votre candidature au parcours sécurité en alternance est validée. '
                f'Contactez Aurélie pour un entretien : {ADVISER["phone"]} ou {ADVISER["mobile"]}. '
                'Retrouvez ses coordonnées dans le mail reçu.')
    logo = academy_logo_url()
    content = _environment.get_template('emails/security_validation.html').render(
        first=first, adviser=ADVISER, reminder=reminder,
        avatar_url=logo.rsplit('/', 1)[0] + '/' + ADVISER['avatar'],
        contact_url='mailto:' + ADVISER['email'] + '?' + urlencode({
            'subject': 'Entretien – Parcours sécurité en alternance',
        }))
    return render_branded_email(
        'Programmons votre entretien.' if reminder else 'Votre candidature est validée.',
        content, eyebrow='PARCOURS SÉCURITÉ · ALTERNANCE', accent_title='Rencontrons-nous.',
        preview_text='Contactez Aurélie pour convenir de votre entretien et préparer la suite de votre parcours.')
