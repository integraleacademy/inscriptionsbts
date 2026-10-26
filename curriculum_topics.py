"""Structured journal topics, kept separate from descriptive teaching prose.

The MOS U4 defaults reproduce the introductory competency table of the
arrêté du 2 mars 2020. Explicit diploma-specific catalogue topics take priority.
"""
import re
import unicodedata

MOS_SOURCE = 'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000041728741'
MOS_U4 = (
    'Mettre en œuvre la veille réglementaire et technologique',
    'Préparer une prestation de sécurité',
    'Proposer une prestation dans le respect d’une démarche qualité, de traçabilité et de protection des données',
)
MOS_BLOCKS = (
    ('U4', 1, 'preparation et mise en oeuvre d une prestation de securite', MOS_U4),
    ('U51', 2, 'management des ressources humaines', (
        'Organiser le service', 'Gérer le personnel', 'Gérer les relations sociales')),
    ('U52', 3, 'gestion de la relation client', (
        'Préparer l’offre commerciale', 'Gérer la prestation', 'Suivre et pérenniser la relation client')),
    ('U6', 4, 'participation a la securite globale', (
        'Prévenir les risques en relation avec les partenaires institutionnels',
        'Gérer les incidents, accidents, événements et crises avec les partenaires institutionnels')),
)


def normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold().replace('œ', 'oe'))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).split())


def curriculum_labels(name, diploma, details):
    """Return deliberate topic labels; never split a narrative into sentences."""
    explicit = details.get('curriculum_topics')
    if isinstance(explicit, str) and explicit.strip():
        labels = list(dict.fromkeys(line.strip(' \t\r•–-') for line in explicit.splitlines() if line.strip(' \t\r•–-')))
        return labels[:120], details.get('source_url', ''), details.get('source_label') or 'Thèmes du référentiel enregistrés par l’école'
    unit = normalize(details.get('exam_unit') or '')
    title = normalize(name)
    if diploma == 'MOS':
        for code, block, name_key, labels in MOS_BLOCKS:
            number = code[1:]
            unit_pattern = r'^[ue]\s*' + r'\s*'.join(number) + r'(\s|$)'
            if title == name_key or re.match(unit_pattern, unit):
                return list(labels), MOS_SOURCE, f'Annexe introductive · Bloc de compétences {block} · Unité {code}'
    return [], '', ''
