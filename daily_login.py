"""Seven weekly login scenes, selected by the calendar day in Paris."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import request

PARIS = ZoneInfo('Europe/Paris')
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
TONES = ('olive', 'ochre', 'forest', 'clay', 'graphite', 'moss', 'sepia')
SCENES = {
    'student': (
        ('Un étudiant prépare ses cours sur un ordinateur dans la médiathèque.', 'Chaque semaine, un nouveau départ.'),
        ('Deux étudiants révisent ensemble autour d’une table sur le campus.', 'Avancer ensemble.'),
        ('Une étudiante présente son projet à un petit groupe.', 'Tes idées prennent forme.'),
        ('Un étudiant suit un cours en ligne et prend des notes chez lui.', 'Ton campus, où que tu sois.'),
        ('Des étudiants travaillent ensemble sur un projet.', 'Construire, apprendre, partager.'),
        ('Une étudiante lit et prend des notes à la bibliothèque.', 'Un peu de curiosité, beaucoup de possibilités.'),
        ('Un étudiant prépare sa semaine avec une tablette et un agenda.', 'La suite commence avec toi.'),
    ),
    'trainer': (
        ('Un formateur anime un cours devant un groupe d’étudiants.', 'Transmettre et donner envie.'),
        ('Une formatrice prépare ses supports pédagogiques à son bureau.', 'Préparer les réussites de demain.'),
        ('Un formateur accompagne un étudiant dans son projet.', 'Un accompagnement qui fait la différence.'),
        ('Une formatrice anime un cours en visioconférence.', 'Garder le lien, à chaque cours.'),
        ('Deux formateurs préparent ensemble leurs prochaines séances.', 'Partager les idées, enrichir les parcours.'),
        ('Un formateur corrige des travaux et prépare ses retours.', 'Faire progresser chaque étudiant.'),
        ('Une formatrice organise sa semaine de cours.', 'Une nouvelle semaine à transmettre.'),
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
