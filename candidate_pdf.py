"""Presentation data for the private, printable BTS application."""
from base64 import b64encode
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, render_template
from werkzeug.exceptions import NotFound

from admission_options import profile_answers
from campaign import candidate_year
from candidate_documents import DOC_FIELDS, _resolve_document, load_verif_docs
from candidate_photos import load_candidate_portrait


MOS_PATHS = {
    'bac_ms': 'Bac pro Métiers de la sécurité obtenu',
    'bac_ms_en_cours': 'Bac pro Métiers de la sécurité en préparation',
    'bac_pro_ms': 'Bac pro Métiers de la sécurité obtenu',
    'bac_pro_ms_en_cours': 'Bac pro Métiers de la sécurité en préparation',
    'carte_cnaps': 'Carte professionnelle CNAPS valide',
    'autre': 'Autre situation',
}


def answer(value):
    """Distinguish an explicit negative from an unanswered or nonstandard legacy value."""
    text = str(value).strip() if value is not None else ''
    normalized = text.casefold()
    if normalized in ('oui', '1', 'true', 'on', 'yes'):
        return 'Oui'
    if normalized in ('non', '0', 'false', 'off', 'no'):
        return 'Non'
    return text


def _portrait(row, upload_dir, db_connect):
    try:
        image, _, _ = load_candidate_portrait(row, upload_dir, db_connect)
    except NotFound:
        return None
    with image:
        image.thumbnail((480, 600))
        buffer = BytesIO()
        image.save(buffer, 'JPEG', quality=88)
    return 'data:image/jpeg;base64,' + b64encode(buffer.getvalue()).decode('ascii')


def _documents(row, upload_dir, inventory):
    """Count actual dossier files; a refused/deleted file is not a received attachment."""
    groups = {kind: Counter() for kind in DOC_FIELDS}
    labels = {kind: label.split(' ', 1)[-1] for kind, (_, label) in DOC_FIELDS.items()}
    known = {item['filename'] for item in inventory}
    for item in inventory:
        kind = item['category']
        if kind not in groups:
            # Extra uploads outside the five requested categories retain their own name.
            kind = ('extra', item['filename'])
            groups[kind] = Counter()
            labels[kind] = item['filename']
        try:
            _resolve_document(row, item['filename'], upload_dir)
        except NotFound:
            state = 'Indisponible'
        else:
            state = 'Nouveau dépôt' if item['type'] == 'nouveau' else {
                'conforme': 'Conforme', 'non_conforme': 'Non conforme',
            }.get(item['status'], 'À contrôler')
        groups[kind][state] += 1

    categories = {label: kind for kind, (_, label) in DOC_FIELDS.items()}
    for name, info in load_verif_docs(row).items():
        if name in known or not isinstance(info, dict) or info.get('etat') != 'non_conforme':
            continue
        kind = categories.get(str(info.get('label') or ''))
        if kind:
            groups[kind]['Refus antérieur'] += 1

    result = []
    for kind, states in groups.items():
        count = sum(states.values()) - states['Refus antérieur'] - states['Indisponible']
        result.append(dict(label=labels[kind], count=count, checks=states))
    return result


def application_pdf(row, *, status, promotion, upload_dir, db_connect, inventory):
    from weasyprint import HTML

    profile = profile_answers(row)
    has_project = any(profile.values()) or any(row.get(key) for key in (
        'projet_pourquoi', 'projet_objectif', 'projet_passions'))
    original_bac = row.get('bac_status')
    mos_path = row.get('mos_parcours') or (
        original_bac if row.get('bts') == 'MOS' and original_bac in MOS_PATHS else '')
    bac = row.get('baccalaureat') or (original_bac if original_bac != mos_path else '')
    bac_detail = original_bac if original_bac not in (bac, mos_path) else ''
    html = render_template(
        'pdf_fiche.html', row=row, status=status, promotion=promotion, year=candidate_year(row),
        profile=profile, has_project=has_project, answer=answer,
        bac=bac, bac_detail=bac_detail, mos_path=MOS_PATHS.get(mos_path, mos_path),
        # For current MOS submissions, the APS question is only asked for "autre".
        show_aps=(not mos_path or mos_path == 'autre' or answer(row.get('aps_souhaitee')) == 'Oui'
                  or row.get('raison_aps') or row.get('aps_session')),
        portrait=_portrait(row, upload_dir, db_connect),
        documents=_documents(row, upload_dir, inventory),
        issued=datetime.now(ZoneInfo('Europe/Paris')),
    )
    # All images are bundled artwork or a validated, embedded portrait. The renderer
    # never needs an admin cookie or a network request back to the service.
    static_root = Path(current_app.static_folder).as_uri() + '/'
    return HTML(string=html, base_url=static_root).write_pdf(dpi=200)
