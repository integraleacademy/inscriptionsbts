"""CRM-inspired school mail layouts and the two authorized sender identities."""
from branded_email import _environment, academy_logo_url
from person_names import person_name


# Public professional details already used by the academy's assistance site.
# Assets: existing admissions memoji (Aurélie) and integraleconnect.com (Clément).
SENDERS = {
    'clement': dict(id='clement', name=person_name('VAILLANT', 'Clément'), role='Directeur · Intégrale Academy',
                    email='clement@integraleacademy.com', phone='04 22 47 07 68',
                    phone_link='+33422470768', avatar='messaging/clement.png'),
    'aurelie': dict(id='aurelie', name=person_name('CHAUSSEZ', 'Aurélie'), role='Responsable des BTS · Relations clients',
                    email='aurelie@integraleacademy.com', phone='04 87 83 06 15',
                    phone_link='+33487830615', avatar='messaging/aurelie.png'),
}
LAYOUTS = {'crm': 'Signature CRM', 'letter': 'Courrier personnel'}
DEFAULT_ACCENT = 'On avance avec vous.'


def render_school_email(subject, body, sender_id='clement', layout='crm', *, action_url='', action_label='', accent_title=DEFAULT_ACCENT):
    if not isinstance(sender_id, str) or sender_id not in SENDERS:
        raise ValueError('Choisissez Clément VAILLANT ou Aurélie CHAUSSEZ comme expéditeur.')
    if not isinstance(layout, str) or layout not in LAYOUTS:
        raise ValueError('Choisissez une présentation proposée.')
    if not isinstance(accent_title, str) or len(accent_title)>120 or any(ord(c)<32 for c in accent_title):
        raise ValueError('La phrase en italique doit tenir sur une ligne de 120 caractères maximum.')
    sender = dict(SENDERS[sender_id])
    logo = academy_logo_url()
    html = _environment.get_template('school_email.html').render(
        subject=subject, paragraphs=body.split('\n\n'), preview_text=body.replace('\n', ' ')[:160],
        sender=sender, layout=layout, logo_url=logo, accent_title=accent_title.strip(),
        avatar_url=logo.rsplit('/', 1)[0] + '/' + sender['avatar'],
        action_url=action_url, action_label=action_label)
    return html, sender
