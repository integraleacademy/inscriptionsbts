"""Seven weekly login scenes, selected by the calendar day in Paris."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import request

PARIS = ZoneInfo('Europe/Paris')
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
TONES = ('olive', 'ochre', 'forest', 'clay', 'graphite', 'moss', 'sepia')
SCENES = {
    'student': (
        ('Une étudiante prépare ses cours dans son carnet, sur un campus lumineux.', 'Chaque semaine, un nouveau départ.'),
        ('Un étudiant travaille sur son ordinateur dans une salle de cours.', 'Tes idées prennent forme.'),
        ('Deux étudiants préparent un projet avec un carnet et un ordinateur.', 'Avancer ensemble.'),
        ('Une étudiante présente son travail devant un tableau.', 'Prendre la parole, partager ses idées.'),
        ('Un étudiant suit un cours en ligne avec un casque.', 'Ton campus, où que tu sois.'),
        ('Une étudiante révise avec ses fiches de cours.', 'Un peu de curiosité, beaucoup de possibilités.'),
        ('Trois étudiants construisent un projet autour d’un tableau.', 'Construire, apprendre, partager.'),
    ),
    'trainer': (
        ('Un formateur anime un cours devant un groupe d’étudiants.', 'Transmettre et donner envie.'),
        ('Une formatrice prépare ses supports pédagogiques à son bureau.', 'Préparer les réussites de demain.'),
        ('Un formateur accompagne une étudiante dans son projet.', 'Un accompagnement qui fait la différence.'),
        ('Une formatrice anime un cours en visioconférence.', 'Garder le lien, à chaque cours.'),
        ('Trois formateurs préparent ensemble leurs prochaines séances.', 'Partager les idées, enrichir les parcours.'),
        ('Une formatrice corrige des travaux et prépare ses retours.', 'Faire progresser chaque étudiant.'),
        ('Un formateur organise sa semaine de cours.', 'Une nouvelle semaine à transmettre.'),
    ),
}


def login_scene(role, now=None):
    if role not in SCENES:
        raise ValueError('Unknown login role')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    day = current.astimezone(PARIS).weekday()
    alt, caption = SCENES[role][day]
    return dict(role=role, day=DAYS[day], tone=TONES[(day + (3 if role == 'trainer' else 0)) % 7],
                image=f'admissions/daily/{role}-{DAYS[day]}.webp', alt=alt, caption=caption)


def register_daily_login(app):
    @app.context_processor
    def daily_login_context():
        role = {'candidate_login': 'student', 'trainer_login': 'trainer'}.get(request.endpoint)
        return {'daily_login': login_scene(role) if role else None}
