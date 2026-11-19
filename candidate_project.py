"""Editable answers on a candidate's administrative record."""
from contextlib import closing
from datetime import datetime
import json

from flask import abort, jsonify, request, session

from admission_options import MOS_PATHS, PROFILE_COLUMNS, PROFILE_GROUPS, answer, profile_answers
from campaign import candidate_year
from candidate_messages import _equal
from security_intake import SITUATIONS, SLOTS
from training_programs import SECURITY


YES_NO = {'oui': 'Oui', 'non': 'Non'}
SECURITY_CHOICES = {
    'available_year': YES_NO,
    'mobile_departments': YES_NO,
    'situation': {value: value for value in SITUATIONS},
    'vehicle': {'yes': 'Oui', 'no': 'Autre organisation', 'planned': 'Prévu pour la rentrée'},
    'contact_slot': {value: value for value in SLOTS},
}
PROJECT_TEXT = {'bac_autre', 'projet_pourquoi', 'projet_objectif', 'projet_passions'}


def project_choices(row):
    preparing = f'Prévu en {candidate_year(row)}'
    choices = {
        'baccalaureat': {'Oui': 'Obtenu', preparing: preparing, 'Non': 'Non'},
        'bac_type': {value: value for value in ('Général', 'Technologique', 'Professionnel', 'Autre')},
        'entreprise_trouvee': YES_NO, 'recherches_commencees': YES_NO,
        'cherche_idf': YES_NO, 'souhaite_accompagnement': YES_NO, 'permis_b': YES_NO,
    }
    if row.get('bts') == 'MOS':
        choices['mos_parcours'] = {key: MOS_PATHS[key] for key in ('bac_pro_ms', 'bac_pro_ms_en_cours', 'carte_cnaps', 'autre')}
        choices['aps_souhaitee'] = YES_NO
    if row.get('bts') == SECURITY:
        choices.update(SECURITY_CHOICES)
    return choices


def project_context(row, intake):
    values = dict(row)
    historical = row.get('bac_status')
    if row.get('bts') == 'MOS' and historical in MOS_PATHS:
        values['mos_parcours'] = row.get('mos_parcours') or historical
    else:
        values['baccalaureat'] = row.get('baccalaureat') or historical
    legacy_paths = {'bac_ms': 'bac_pro_ms', 'bac_ms_en_cours': 'bac_pro_ms_en_cours'}
    if values.get('mos_parcours') in legacy_paths:
        values['mos_parcours'] = legacy_paths[values['mos_parcours']]
    if row.get('bts') == SECURITY:
        values.update({**intake, **json.loads(row.get('infos_parcours_securite') or '{}')})
    choices = project_choices(row)
    for key, options in choices.items():
        if options is YES_NO:
            values[key] = answer(values.get(key)).lower()
    return dict(project_values=values, project_choices=choices, profile_display=profile_answers(row))


def _project_changes(row, data):
    choices = project_choices(row)
    text_fields = PROJECT_TEXT | ({'raison_aps', 'aps_session'} if row['bts'] == 'MOS' else set())
    changes = {}
    security = {}
    old_profile = profile_answers(row)
    for group in PROFILE_GROUPS:
        key = group['name']
        if key not in data:
            continue
        values = data[key]
        allowed = {code for code, _ in group['options']} | set(old_profile[key])
        if not isinstance(values, list) or any(not isinstance(v, str) or v not in allowed for v in values):
            raise ValueError('Vérifiez les réponses du profil.')
        selected = list(dict.fromkeys(values))
        changes[PROFILE_COLUMNS[key]] = (json.dumps(selected, ensure_ascii=False) if any(',' in v for v in selected)
                                         else ', '.join(selected))
    for key, value in data.items():
        if key in PROFILE_COLUMNS:
            continue
        if key not in choices and key not in text_fields:
            raise ValueError('Cette information ne fait pas partie du parcours.')
        if not isinstance(value, str) or len(value) > 5000:
            raise ValueError('Limitez chaque réponse à 5 000 caractères.')
        value = value.strip()
        if key in choices and value and value not in choices[key]:
            raise ValueError('Choisissez une valeur proposée pour le parcours.')
        if key in SECURITY_CHOICES:
            security[key] = value
        elif key in ('permis_b', 'aps_souhaitee'):
            changes[key] = {'oui': 1, 'non': 0, '': None}[value]
        else:
            changes[key] = value
    if security:
        overrides = json.loads(row.get('infos_parcours_securite') or '{}')
        changes['infos_parcours_securite'] = json.dumps({**overrides, **security}, ensure_ascii=False)
    # Older dossiers used bac_status for either the bac or the MOS pathway.
    historical = row.get('bac_status')
    alias = 'mos_parcours' if row['bts'] == 'MOS' and historical in MOS_PATHS else 'baccalaureat'
    if alias in changes and historical and (not row.get(alias) or row[alias] == historical):
        changes['bac_status'] = changes[alias]
    return {key: value for key, value in changes.items() if row.get(key) != value}


def register_candidate_project(app, connect, require_admin, log_event):
    @app.post('/admin/candidat/<cid>/projet')
    def admin_candidate_project(cid):
        if not require_admin():
            abort(403)
        if not _equal(request.headers.get('X-CSRF-Token'), session.get('_candidate_message_csrf')):
            return jsonify(ok=False, error='La session a expiré. Rechargez la fiche.'), 400
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(ok=False, error='Données du parcours invalides.'), 400
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
            if not row:
                abort(404)
            row = dict(row)
            try:
                changes = _project_changes(row, data)
            except ValueError as exc:
                return jsonify(ok=False, error=str(exc)), 400
            if changes:
                assignments = ', '.join(key + '=?' for key in changes)
                conn.execute(f'UPDATE candidats SET {assignments}, updated_at=? WHERE id=?',
                             [*changes.values(), datetime.now().isoformat(), cid])
                conn.commit()
        if changes:
            log_event(row, 'FICHE_MODIFIEE', {'champs': list(data)})
        return jsonify(ok=True)
