"""CRM-inspired school mail layouts and the two authorized sender identities."""
from branded_email import _environment, academy_logo_url
from person_names import person_name
from urllib.parse import urlsplit


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


def email_options(data):
    """One validated set of options for individual and group messages."""
    options = {key: data.get(key, default) for key, default in (
        ('sender_id', 'clement'), ('layout', 'crm'), ('accent_title', DEFAULT_ACCENT),
        ('action_url', ''), ('action_label', ''))}
    if not isinstance(options['sender_id'], str) or options['sender_id'] not in SENDERS:
        raise ValueError('Choisissez Clément VAILLANT ou Aurélie CHAUSSEZ comme expéditeur.')
    if not isinstance(options['layout'], str) or options['layout'] not in LAYOUTS:
        raise ValueError('Choisissez une présentation proposée.')
    accent = options['accent_title']
    if not isinstance(accent, str) or len(accent) > 120 or any(ord(c) < 32 for c in accent):
        raise ValueError('La phrase en italique doit tenir sur une ligne de 120 caractères maximum.')
    options['accent_title'] = accent.strip()
    for field in ('action_url', 'action_label'):
        if not isinstance(options[field], str):
            raise ValueError('Vérifiez le texte et le lien du bouton.')
        options[field] = options[field].strip()
    url, label = options['action_url'], options['action_label']
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or len(url) > 2000 or any(ord(c) < 33 for c in url):
            raise ValueError('Le bouton doit mener vers une adresse https:// valide.')
        if not label or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError('Nommez le bouton (80 caractères maximum sur une ligne).')
    else:
        options['action_label'] = ''
    return options


def render_school_email(subject, body, sender_id='clement', layout='crm', *, action_url='', action_label='', accent_title=DEFAULT_ACCENT, security_note=''):
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
        action_url=action_url, action_label=action_label, security_note=security_note)
    return html, sender
