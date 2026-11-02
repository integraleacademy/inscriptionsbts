"""Course identifiers shared by admission, enrollment and promotion screens."""
import re
import unicodedata

BTS_LABELS = {
    'MOS': 'BTS Management opérationnel de la sécurité',
    'MCO': 'BTS Management commercial opérationnel',
    'NDRC': 'BTS Négociation et digitalisation de la relation client',
    'PI': 'BTS Professions immobilières',
    'CI': 'BTS Commerce international',
    'CG': 'BTS Comptabilité et gestion',
}
SECURITY = 'PARCOURS-SECURITE'
SECURITY_LABEL = 'Parcours sécurité en alternance'


def is_professional_title(code):
    return isinstance(code, str) and code.startswith('TP ')


def program_name(code):
    if code == SECURITY:
        return SECURITY_LABEL
    if is_professional_title(code):
        return 'TP · ' + code[3:].capitalize()
    return 'BTS ' + code if code in BTS_LABELS else (code or '')


def catalog(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS professional_titles (code TEXT PRIMARY KEY, name TEXT NOT NULL)')
    titles = conn.execute('SELECT code,name FROM professional_titles ORDER BY name COLLATE NOCASE')
    return {**BTS_LABELS, SECURITY: SECURITY_LABEL, **{code: 'TP · ' + name for code, name in titles}}


def professional_title(value):
    name = ' '.join(unicodedata.normalize('NFC', value).split())
    if not 2 <= len(name) <= 100 or not any(c.isalpha() for c in name) or not re.fullmatch(r"[\w ’'(),.\-/&+]+", name):
        raise ValueError('Indiquez l’intitulé du titre professionnel (2 à 100 caractères).')
    return 'TP ' + name.upper(), name
