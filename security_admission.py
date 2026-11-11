"""Interview invitation for validated security apprenticeship applications."""
from html import unescape
import base64
from pathlib import Path
from urllib.parse import urlencode

from branded_email import _environment, academy_logo_url
from school_email import SENDERS


# Professional contacts published in the security application receipt and guide.
ADVISER = {
    **SENDERS['aurelie'],
    'name': 'Aurélie BAYARD-CHAUSSEZ',
    'role': 'Chargée des relations clients',
    'mobile': '07 69 39 04 57',
    'mobile_link': '+33769390457',
}
BROCHURE_PATH = Path(__file__).parent / 'assets' / 'brochures' / 'parcours-securite-alternance.pdf'
BROCHURE_NAME = 'Brochure_Parcours_securite_en_alternance.pdf'


def validation_brochure():
    """Freeze the provided PDF into the preview, then send those same bytes."""
    try:
        content = BROCHURE_PATH.read_bytes()
    except OSError as exc:
        raise ValueError('La brochure du parcours sécurité est indisponible. Réessayez après sa remise en place.') from exc
    if not content.startswith(b'%PDF-'):
        raise ValueError('La brochure du parcours sécurité doit être un fichier PDF valide.')
    return {'name': BROCHURE_NAME, 'content': base64.b64encode(content).decode('ascii')}


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
    return _environment.get_template('emails/security_validation.html').render(
        first=first, adviser=ADVISER, reminder=reminder,
        email_title='Programmons votre entretien.' if reminder else 'Votre candidature est validée.',
        logo_url=logo, hero_url=logo.rsplit('/', 1)[0] + '/emails/security-journey.jpg',
        avatar_url=logo.rsplit('/', 1)[0] + '/' + ADVISER['avatar'],
        contact_url='mailto:' + ADVISER['email'] + '?' + urlencode({
            'subject': 'Entretien – Parcours sécurité en alternance',
        }))
