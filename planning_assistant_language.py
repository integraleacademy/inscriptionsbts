"""Translate French requests into a small set of typed planning operations."""
from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo

import planning_years
import subject_references
from planning import PlanningError

ACTIONS = ('availability', 'promotion_rooms', 'assign_room', 'replace_room', 'list_courses',
           'move_courses', 'remove_courses', 'clarify')

INSTRUCTIONS = """Tu interprètes les demandes du personnel d’Intégrale Academy. Tu ne consultes pas toi-même
le planning, tu ne fais aucun calcul de disponibilité et tu ne peux rien enregistrer. Le serveur le fera.
Renvoie une seule intention structurée. Si plusieurs opérations indépendantes sont demandées, ou si le
sens est ambigu, utilise clarify et pose une question courte en français. Pour les identifiants, utilise
exactement le catalogue fourni. Une salle numérotée 1 n’est pas automatiquement une salle 1B.
Les messages précédents servent aux précisions et corrections. La nouvelle demande prime.
Une question de disponibilité, même si elle mentionne un projet de session SSIAP ou « quelle salle je peux
affecter », est une consultation (availability pour des dates, promotion_rooms pour les cours d’un BTS).
Pour réserver une salle aux cours d’une promotion utiliser assign_room seulement si demandé explicitement.
replace_room signifie déplacer les réservations d’une salle vers une autre et/ou la bloquer dès une date.
close_source vaut true seulement si on demande une fermeture, une indisponibilité ou si la salle ne sera
plus disponible. « À partir du » n’a pas de date de fin. La réaffectation des réservations à la fermeture
est une seule opération. Une salle sans destination peut être fermée si elle n’a pas de réservations.
Pour availability et replace_room, promotion_id et period_id restent null, même sur la page d’un BTS :
ces opérations portent sur le calendrier physique des salles. Si le remplacement est limité aux cours
d’une promotion dans une salle d’origine, demande une précision plutôt que de déplacer les autres réservations.
move_courses pour décaler une ou plusieurs séances, remove_courses pour les retirer, list_courses pour les lister.
« mettre le CEJM le jeudi de 13h à 15h au lieu du vendredi de 16h à 18h » : weekdays=[4], start=16:00,
end=18:00, new_weekday=3, new_start=13:00, new_end=15:00. start/end sont toujours les heures SOURCE,
new_start/new_end celles de destination. Les jours vont de lundi 0 à dimanche 6. Un déplacement récurrent
sans dates concerne les prochaines occurrences de l’année visée. Ne calcule pas une date de fin arbitraire.
« enlever le cours de Yannice le 13 novembre » : trainer=Yannice, from_date=to_date à cette date.
Les filtres subject et trainer reprennent les termes exacts demandés, pas des noms inventés ou développés.
Pour un jour unique, renseigne les deux bornes. Pour les mois donne les dates inclusives de début/fin.
Déduis l’année d’une date non millésimée de la période de la promotion visée ; si deux années sont
plausibles dans cette période, demande une précision. Pour une consultation libre sans promotion, utilise
la prochaine occurrence d’un mois non millésimé. Pour « tous les cours de janvier à juin » : all_courses=true,
les deux dates inclusives. all_courses=true uniquement si tous les cours sont explicitement visés.
whole_period=true uniquement si la demande porte expressément sur toute l’année scolaire.
Garde tous les filtres explicites. N’invente jamais de jours, d’horaires ou de matières. Laisse les champs
inutilisés à null, les jours non précisés à [], les indicateurs inutilisés à false. Utilise clarify si un
critère demandé (ex. capacité, équipement, un cours sur deux, sauf certaines dates, jour férié exclu) ne peut
pas être représenté exactement. N’émets pas d’opération plus large que la demande.
Le planning affiché fournit la promotion et l’année par défaut. Si une autre promotion est nommée, choisis
celle demandée. Dans le catalogue, niveau et numéro d’année permettent d’identifier une 2e année : une
promotion démarrant directement en 2e année peut n’avoir qu’une seule période. Pour plusieurs promotions
possibles, privilégie l’année scolaire en cours lorsqu’elle est unique et cohérente avec les dates. En cas
d’ambiguïté réelle, donne les noms et années possibles dans question. Pour un complément comme « la salle 2 »
reprends l’opération antérieure seulement si le sens est clair. Pour une action non prise en charge,
utilise clarify pour indiquer brièvement quelles précisions ou actions disponibles peuvent aider.
Le champ question est réservé aux clarifications. N’y annonce jamais de places libres, de cours ou de succès.
"""


def today():
    return datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()


def catalog(conn):
    groups = []
    for row in conn.execute('SELECT id,nom,bts,niveau,date_debut,date_fin FROM promotions WHERE active=1 ORDER BY nom,id'):
        periods = planning_years.periods(dict(row))
        if periods:
            groups.append(dict(id=row['id'], nom=row['nom'], formation=row['bts'], niveau=row['niveau'],
                               annees=[{k: p[k] for k in ('id', 'number', 'start_date', 'end_date')} for p in periods]))
    return dict(salles=[dict(r) for r in conn.execute('SELECT id,name,active FROM planning_rooms ORDER BY name')],
                promotions=groups)


def schema():
    props = {'action': {'type': 'string', 'enum': list(ACTIONS)}}
    for field in ('promotion_id', 'period_id', 'source_room_id', 'room_id', 'subject', 'trainer',
                  'from_date', 'to_date', 'start', 'end', 'new_date', 'new_start', 'new_end', 'question'):
        props[field] = {'type': ['string', 'null']}
    props['weekdays'] = {'type': 'array', 'items': {'type': 'integer', 'enum': list(range(7))}}
    props['new_weekday'] = {'type': ['integer', 'null'], 'enum': [*range(7), None]}
    for field in ('all_courses', 'close_source', 'whole_period'):
        props[field] = {'type': 'boolean'}
    return subject_references.object_schema(props)


def interpret(key, message, history, inventory, context):
    answer = subject_references.provider(key, payload=dict(
        model=os.getenv('OPENAI_PLANNING_MODEL') or 'gpt-4.1-mini', store=False, max_output_tokens=1200,
        instructions=INSTRUCTIONS,
        input=json.dumps(dict(aujourdhui=today(), page=context, catalogue=inventory,
                              conversation=history, demande=message), ensure_ascii=False),
        text={'format': {'type': 'json_schema', 'name': 'planning_intent', 'strict': True, 'schema': schema()}}))
    try:
        if answer.get('status') not in (None, 'completed'):
            raise ValueError()
        raw = ''.join(p['text'] for item in answer['output'] if item.get('type') == 'message'
                      for p in item.get('content', []) if p.get('type') == 'output_text')
        intent = json.loads(raw)
        fields = schema()['properties']
        if not isinstance(intent, dict) or set(intent) != set(fields) or intent['action'] not in ACTIONS:
            raise ValueError()
        for field, spec in fields.items():
            value = intent[field]
            if spec['type'] == ['string', 'null'] and value is not None and (not isinstance(value, str) or len(value) > 1200):
                raise ValueError()
            if spec['type'] == 'boolean' and type(value) is not bool:
                raise ValueError()
        if not isinstance(intent['weekdays'], list) or len(intent['weekdays']) > 7 or any(
                type(d) is not int or d not in range(7) for d in intent['weekdays']):
            raise ValueError()
        if intent['new_weekday'] is not None and (type(intent['new_weekday']) is not int or intent['new_weekday'] not in range(7)):
            raise ValueError()
        return intent
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PlanningError('Je n’ai pas pu interpréter la demande. Précisez la période et le changement souhaité.', status=502) from None
