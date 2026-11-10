"""Build compact, verifiable facts for the conversation and the room-by-room detail."""
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json

from babel.dates import format_date

from planning import _minutes
from planning_import_pdf import normal


@dataclass
class Answer:
    message: str
    details: list = field(default_factory=list)
    stamps: list = field(default_factory=list)
    confirm_label: str = ''
    apply: object = None
    evidence: dict = field(default_factory=dict)
    detail_label: str = 'Voir les créneaux concernés'

    def digest(self):
        data = [self.message, self.details, self.stamps, self.confirm_label]
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def joined(items):
    if len(items) < 2:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' et ' + items[-1]


def display_time(clock):
    hour, minute = clock.split(':')
    return f'{int(hour)} h' + (f' {minute}' if minute != '00' else '')


def day_label(iso, pattern='EEEE d MMMM'):
    return format_date(date.fromisoformat(iso), pattern, locale='fr_FR')


def checked_period(dates, weekdays):
    first, last = dates[0], dates[-1]
    if first == last:
        return 'le ' + day_label(first, 'EEEE d MMMM y')
    pattern = 'EEEE d' if first[:7] == last[:7] else 'EEEE d MMMM' if first[:4] == last[:4] else 'EEEE d MMMM y'
    span = f"du {day_label(first, pattern)} au {day_label(last, 'EEEE d MMMM y')}"
    calendar_days = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    if len(dates) != calendar_days:
        if weekdays == [0, 1, 2, 3, 4]:
            span += ' en semaine'
        else:
            names = ['lundis', 'mardis', 'mercredis', 'jeudis', 'vendredis', 'samedis', 'dimanches']
            span += ' (les ' + joined([names[i] for i in weekdays]) + ')'
    return span


def at_location(rooms, location):
    if not location:
        return rooms
    words = normal(location).split()
    return [r for r in rooms if words and set(words) <= set(normal(r['name']).split())]


def room_options(rooms):
    # Prefer the numbered teaching rooms for an unqualified request; keep explicitly named sites visible.
    return sorted(rooms, key=lambda r: (not normal(r['name']).startswith('salle '), normal(r['name'])))


def room_detail(room, dates, hours):
    days = room['days']
    if room['free_days'] == len(dates):
        return 'libre sur toute la période', None
    full = [d for d in dates if days[d]['state'] == 'free']
    partial = [(d, a, b) for d in dates if days[d]['state'] == 'partial' for a, b in days[d]['free']]
    parts = []
    example = None
    if full:
        sample = ', '.join(day_label(d, 'EEE d MMM') for d in full[:4])
        if len(full) > 4:
            sample += f' et {len(full)-4} autre(s) jour(s)'
        parts.append(f'journées libres ({sample})')
        example = f"{room['name']} est libre le {day_label(full[0])}, {hours}"
    if partial:
        day, start, end = max(partial, key=lambda item: _minutes(item[2], end=True) - _minutes(item[1]))
        window = f"le {day_label(day)}, de {display_time(start)} à {display_time(end)}"
        parts.append('créneau libre ' + window)
        if not example:
            example = f"{room['name']} est libre {window}"
    return (' · '.join(parts) if parts else 'aucun créneau libre sur les horaires demandés'), example


def availability_answer(data, rooms, location=None):
    dates = data['dates']
    period = checked_period(dates, data['weekdays'])
    hours = f"de {display_time(data['start'])} à {display_time(data['end'])}"
    if not rooms:
        if location:
            return Answer(f"Je ne trouve aucune salle dont le nom indique « {location} ». Quel nom porte-t-elle dans le répertoire ?")
        return Answer("Le répertoire ne contient aucune salle active à proposer.")
    ranked = sorted(room_options(rooms), key=lambda r: -r['free_days'])
    free = [r['name'] for r in ranked if r['free_days'] == len(dates)]
    fragments = {'periode': period, 'horaires': hours}
    required = [['periode'], ['horaires']]
    details, alternatives = [], []
    for room in ranked:
        detail, alternative = room_detail(room, dates, hours)
        details.append(f"{room['name']} — {detail}.")
        if alternative:
            alternatives.append(alternative)
    if free:
        names = joined([f'**{name}**' for name in free[:3]])
        verb = 'est libre' if len(free[:3]) == 1 else 'sont libres'
        default = f"Oui. {names} {verb} {period}, {hours}."
        if len(free) > 3:
            default += f" Le détail présente les {len(free)} salles disponibles."
        for i, name in enumerate(free[:8], 1):
            fragments[f'salle{i}'] = f'**{name}**'
        refs = [k for k in fragments if k.startswith('salle')]
        required.extend([[k] for k in refs] if len(free) <= 2 else [refs])
        outcome = 'Ces salles sont entièrement libres sur tous les jours et horaires vérifiés.'
    else:
        if len(rooms) == 1:
            fragments['cible'] = f"**{rooms[0]['name']}**"
            required.append(['cible'])
            default = f"Non, **{rooms[0]['name']}** ne couvre pas tout le créneau {period}, {hours}."
        else:
            default = f"Aucune salle n’est libre sur tous les créneaux demandés {period}, {hours}."
        outcome = 'Aucune salle ne couvre tous les jours et horaires. Les options éventuelles sont seulement partielles.'
        for i, option in enumerate(alternatives[:3], 1):
            fragments[f'option{i}'] = option
        if alternatives:
            required.append([k for k in fragments if k.startswith('option')])
            default += '\n\n' + alternatives[0] + '.'
    facts = dict(resultat=outcome, ouverture='oui' if free else 'non', fragments=fragments, obligatoires=required)
    return Answer(default, details, evidence=facts, detail_label='Comparer les disponibilités par salle')
