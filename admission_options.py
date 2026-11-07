"""Original application choices, shared by the form and candidate records."""
import json


PROFILE_GROUPS = [{'name': 'qualites',
  'title': 'Tes principales qualités',
  'options': [('rigoureux', 'Rigueur'),
              ('organise', 'Organisation'),
              ('autonome', 'Autonomie'),
              ('communication', 'Communication'),
              ('esprit_equipe', 'Esprit d’équipe'),
              ('curieux', 'Curiosité'),
              ('leadership', 'Leadership'),
              ('creatif', 'Créativité'),
              ('empathique', 'Empathie'),
              ('serieux', 'Sérieux')]},
 {'name': 'motivation',
  'title': 'Ce qui te motive dans tes études ou ton futur métier',
  'options': [('reussite', 'La réussite personnelle et professionnelle'),
              ('stabilite', 'La stabilité et la sécurité de l’emploi'),
              ('utilite', 'Être utile et aider les autres'),
              ('defis', 'Les défis et les responsabilités'),
              ('contact', 'Le contact humain et le travail d’équipe'),
              ('innovation', 'L’innovation et les nouvelles technologies'),
              ('evolution', 'Les perspectives d’évolution'),
              ('apprentissage', 'L’envie d’apprendre et de me perfectionner')]},
 {'name': 'valeurs',
  'title': 'Ce que tu recherches dans ton futur métier',
  'options': [('salaire', 'Un bon salaire et des avantages'),
              ('sens', 'Un métier qui a du sens'),
              ('contact', 'Être en contact avec le public'),
              ('mobilite', 'Pouvoir bouger et voyager'),
              ('stabilite', 'La stabilité et la sécurité de l’emploi'),
              ('responsabilite', 'Des responsabilités importantes'),
              ('autonomie', 'Travailler de manière autonome'),
              ('equipe', 'Un bon esprit d’équipe')]},
 {'name': 'travail',
  'title': 'Ta manière de travailler',
  'options': [('methodique', 'Je suis méthodique et j’aime planifier'),
              ('pratique', 'J’apprends mieux en pratiquant'),
              ('collaboratif', 'J’aime travailler en groupe'),
              ('independant', 'Je préfère travailler seul(e)'),
              ('creatif', 'J’aime proposer des idées nouvelles'),
              ('objectif', 'Je me fixe des objectifs précis')]}]


PROFILE_COLUMNS = {'qualites': 'projet_qualites', 'motivation': 'projet_motivation',
                   'valeurs': 'projet_recherche', 'travail': 'projet_travail'}


def profile_fields(form):
    answers = {}
    for group in PROFILE_GROUPS:
        selected = form.getlist(group['name'] + '[]')
        if not selected or any(value not in dict(group['options']) for value in selected):
            raise ValueError('Sélectionne au moins une réponse dans la rubrique « ' + group['title'] + ' ».')
        answers[PROFILE_COLUMNS[group['name']]] = ', '.join(dict.fromkeys(selected))
    return answers


def profile_answers(row):
    """Use the form labels for both historical JSON lists and current CSV answers."""
    answers = {}
    for group in PROFILE_GROUPS:
        raw = (row.get(PROFILE_COLUMNS[group['name']]) or '').strip()
        try:
            values = json.loads(raw)
        except ValueError:
            values = None
        if not isinstance(values, list):
            values = raw.split(',')
        labels = dict(group['options'])
        choices = (value.strip() for value in values if isinstance(value, str))
        answers[group['name']] = [labels.get(value.lower(), value) for value in choices if value]
    return answers
