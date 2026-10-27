"""Propose missing trainer records, then validate them without writing."""
import re
import secrets

import planning as p
from person_names import first_name, last_name
from planning_import_pdf import normal


def source_name(label):
    text = re.sub(r'^(?:M\.|Mme|Mlle)\s+', '', label).strip()
    parts = text.rsplit(' ', 1)
    return dict(nom=last_name(parts[0]), prenom=first_name(parts[1].rstrip('.')) if len(parts) == 2 else '')


def same_person(first, second):
    a, b = normal(first['prenom']), normal(second['prenom'])
    return normal(first['nom']) == normal(second['nom']) and bool(a and b) and (
        a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b)))


def propose(labels, existing):
    drafts, matches, warnings = [], {}, []
    for label in labels:
        identity = source_name(label)
        text = normal(re.sub(r'^(?:M\.|Mme|Mlle)\s+', '', label))
        candidates = [t for t in existing if text in {normal(t['nom'] + ' ' + t['prenom']), normal(t['prenom'] + ' ' + t['nom'])}]
        if not candidates:
            candidates = [t for t in existing if same_person(identity, t)]
        if candidates:
            if len(candidates) == 1 and candidates[0]['active']:
                matches[label] = candidates[0]['id']
            else:
                warnings.append(label + ' : plusieurs fiches correspondent ou une fiche est désactivée. Choisissez la bonne fiche active pour éviter un doublon.')
            continue
        candidates = [t for t in drafts if same_person(identity, t)]
        if len(candidates) == 1:
            draft = candidates[0]
            if len(normal(draft['prenom'])) == 1 and len(normal(identity['prenom'])) > 1:
                draft['prenom'] = identity['prenom']
        else:
            draft = dict(identity, id='import-' + secrets.token_hex(16), source=label, email='', assigned=0, new=True)
            drafts.append(draft)
        matches[label] = draft['id']
    return drafts, matches, warnings


def prepare(conn, source, supplied, used_ids):
    allowed = {t['id'] for t in source.get('trainer_drafts', [])}
    if not isinstance(supplied, list) or len(supplied) > len(allowed):
        raise p.PlanningError('Vérifiez les fiches des formateurs à créer.')
    values = {}
    for value in supplied:
        if not isinstance(value, dict) or not isinstance(value.get('id'), str) or value['id'] not in allowed or value['id'] in values:
            raise p.PlanningError('Une fiche à créer ne correspond pas à ce PDF. Relancez l’analyse.')
        values[value['id']] = value
    existing = [dict(r) for r in conn.execute('SELECT id,nom,prenom,email,active FROM trainers')]
    pending = {}
    for tid in sorted(allowed & used_ids):
        if any(t['id'] == tid for t in existing):
            continue  # Replay: use the actual record, without overwriting its identity.
        raw = values.get(tid)
        if not raw or any(not isinstance(raw.get(k, ''), str) for k in ('nom', 'prenom', 'email')):
            raise p.PlanningError('Complétez les fiches des formateurs à créer.')
        nom, prenom, email = last_name(raw.get('nom')), first_name(raw.get('prenom')), raw.get('email', '').strip().lower()
        if not nom or not prenom or max(len(nom), len(prenom)) > 100 or any(ord(c) < 32 for c in raw['nom'] + raw['prenom']):
            raise p.PlanningError('Indiquez le nom et le prénom ou l’initiale du formateur (100 caractères maximum).')
        if email and (len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
            raise p.PlanningError('L’adresse e-mail du nouveau formateur est invalide. Vous pouvez la laisser vide.')
        trainer = dict(id=tid, nom=nom, prenom=prenom, email=email or None, assigned=0, new=True)
        if any(same_person(trainer, t) or (email and email == (t.get('email') or '').lower()) for t in existing + list(pending.values())):
            raise p.PlanningError('Une fiche correspond déjà à ' + prenom + ' ' + nom + '. Relancez l’analyse et utilisez la fiche existante.', status=409)
        pending[tid] = trainer
    return pending
