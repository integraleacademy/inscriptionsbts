"""Public company information from the French government business directory.

Only an exact SIRET match can be imported. Registry information never supplies
login credentials or contact details. The signed preview is saved on form submit.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import re

import requests
from itsdangerous import BadData, URLSafeTimedSerializer

SEARCH_URL = 'https://recherche-entreprises.api.gouv.fr/search'
SOURCE = 'Annuaire des entreprises · données publiques'
NOMENCLATURES = json.loads((Path(__file__).parent/'reference_data/company_nomenclatures.json').read_text(encoding='utf-8'))
EDITABLE_FIELDS = (
    ('legal_name', 'Raison sociale', 300),
    ('trade_name', 'Nom commercial / enseigne', 300),
    ('address', 'Adresse complète de l’établissement', 500),
    ('postal_code', 'Code postal', 20),
    ('city', 'Commune', 150),
    ('legal_form', 'Forme juridique', 200),
    ('activity_code', 'Code APE / NAF de l’établissement', 10),
    ('activity_label', 'Activité principale de l’établissement', 300),
)
EFFECTIFS = {
    'NN': 'Unité non employeuse', '00': '0 salarié', '01': '1 à 2 salariés',
    '02': '3 à 5 salariés', '03': '6 à 9 salariés', '11': '10 à 19 salariés',
    '12': '20 à 49 salariés', '21': '50 à 99 salariés', '22': '100 à 199 salariés',
    '31': '200 à 249 salariés', '32': '250 à 499 salariés', '41': '500 à 999 salariés',
    '42': '1 000 à 1 999 salariés', '51': '2 000 à 4 999 salariés',
    '52': '5 000 à 9 999 salariés', '53': '10 000 salariés et plus',
}


class RegistryError(ValueError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def clean(value, maximum=2000):
    return ' '.join(value.split())[:maximum] if isinstance(value, str) else ''


def normalize_siret(value):
    # Accept spaces in pasted numbers; do not silently strip arbitrary letters.
    siret = re.sub(r'\s+', '', value or '')
    if not re.fullmatch(r'[0-9]{14}', siret):
        raise RegistryError('Saisissez un SIRET composé de 14 chiffres.', 400)
    return siret


def joined(value):
    return ', '.join(filter(None, (clean(item, 300) for item in value[:100]))) if isinstance(value, list) else ''


def workforce(item):
    code = clean(item.get('tranche_effectif_salarie'))
    if not code:
        return ''
    year = clean(item.get('annee_tranche_effectif_salarie'))
    return EFFECTIFS.get(code, 'Tranche INSEE '+code) + (' ('+year+')' if year else '')


def project_company(payload, siret):
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        raise RegistryError('La réponse de l’annuaire est invalide. Réessayez dans quelques instants.')
    for company in payload['results']:
        if not isinstance(company, dict) or company.get('siren') != siret[:9]:
            continue
        headquarters = company.get('siege') if isinstance(company.get('siege'), dict) else {}
        matches = company.get('matching_etablissements')
        establishments = [headquarters] + (matches if isinstance(matches, list) else [])
        establishment = next((e for e in establishments if isinstance(e, dict) and e.get('siret') == siret), None)
        if not establishment:
            continue
        if company.get('statut_diffusion') != 'O' or establishment.get('statut_diffusion_etablissement') != 'O':
            raise RegistryError('Les données de cet établissement ne sont pas librement diffusables. Vous pouvez compléter la fiche manuellement.', 404)
        legal_name = clean(company.get('nom_raison_sociale') or company.get('nom_complet'), 300)
        if not legal_name:
            raise RegistryError('L’annuaire ne fournit pas de dénomination exploitable pour cet établissement.', 404)
        fields = {
            'name': clean(company.get('nom_complet') or legal_name, 150),
            'siret': siret, 'legal_name': legal_name,
            'trade_name': clean(establishment.get('nom_commercial') or joined(establishment.get('liste_enseignes')), 300),
            'address': clean(establishment.get('adresse'), 500),
            'postal_code': clean(establishment.get('code_postal'), 20),
            'city': clean(establishment.get('libelle_commune') or establishment.get('libelle_commune_etranger'), 150),
            'legal_form': clean(company.get('nature_juridique'), 200),
            'activity_code': clean(establishment.get('activite_principale'), 10),
        }
        # Labels are bundled from the official directory, without another API call.
        naf = NOMENCLATURES['naf_2025' if datetime.now(timezone.utc).year >= 2027 else 'naf_rev2']
        fields['activity_label'] = clean(naf.get(fields['activity_code']), 300)
        if fields['legal_form']:
            code = fields['legal_form']
            label = NOMENCLATURES['legal_forms'].get(code)
            fields['legal_form'] = clean(label+' ('+code+')' if label else code+' (code INSEE)', 200)
        details = []

        def add(label, value):
            value = clean(value)
            if value:
                details.append({'label': label, 'value': value})

        add('SIREN', siret[:9])
        add('SIRET de l’établissement', siret)
        add('Type d’établissement', 'Siège social' if establishment.get('est_siege') is True else 'Établissement secondaire')
        add('État de l’établissement', {'A': 'Actif', 'F': 'Fermé'}.get(establishment.get('etat_administratif'), 'Non renseigné'))
        add('État de l’entreprise', {'A': 'Active', 'C': 'Cessée'}.get(company.get('etat_administratif'), 'Non renseigné'))
        add('Sigle', company.get('sigle'))
        add('Création de l’établissement', establishment.get('date_creation'))
        add('Création de l’entreprise', company.get('date_creation'))
        add('Fermeture de l’établissement', establishment.get('date_fermeture'))
        add('Cessation de l’entreprise', company.get('date_fermeture'))
        add('Effectif de l’établissement', workforce(establishment))
        add('Effectif de l’entreprise', workforce(company))
        add('Catégorie d’entreprise', company.get('categorie_entreprise'))
        add('Caractère employeur de l’établissement', {'O': 'Oui', 'N': 'Non'}.get(establishment.get('caractere_employeur')))
        add('Code APE / NAF de l’entreprise', company.get('activite_principale'))
        add('Activité principale de l’entreprise', naf.get(company.get('activite_principale')))
        add('Nature juridique · code INSEE', company.get('nature_juridique'))
        add('Code NAF 2025 de l’établissement', establishment.get('activite_principale_naf25'))
        add('Numéro(s) de TVA', joined(company.get('tva')))
        add('Convention(s) collective(s) · IDCC', joined(establishment.get('liste_idcc')))
        add('Enseigne(s)', joined(establishment.get('liste_enseignes')))
        if headquarters.get('siret') != siret and headquarters.get('statut_diffusion_etablissement') == 'O':
            add('SIRET du siège social', headquarters.get('siret'))
            add('Adresse du siège social', headquarters.get('adresse'))
        leaders = company.get('dirigeants')
        if isinstance(leaders, list):
            for leader in leaders[:50]:
                if not isinstance(leader, dict):
                    continue
                name = clean(leader.get('denomination')) or ' '.join(filter(None, [clean(leader.get('prenoms')), clean(leader.get('nom'))]))
                quality = clean(leader.get('qualite'))
                if name:
                    add('Dirigeant · '+quality if quality else 'Dirigeant', name)
        extras = company.get('complements')
        if isinstance(extras, dict):
            add('Identifiant association (RNA)', extras.get('identifiant_association'))
            add('N° de déclaration d’activité', joined(extras.get('liste_id_organisme_formation')))
            if extras.get('est_organisme_formation'):
                add('Organisme de formation', 'Oui')
                if isinstance(extras.get('est_qualiopi'), bool):
                    add('Certification Qualiopi', 'Oui' if extras['est_qualiopi'] else 'Non')
        add('Mise à jour de l’entreprise dans l’annuaire', company.get('date_mise_a_jour'))
        add('Mise à jour de l’établissement (INSEE)', establishment.get('date_mise_a_jour_insee'))
        warnings = []
        if establishment.get('etat_administratif') == 'F':
            warnings.append('Cet établissement est signalé comme fermé. Vérifiez le SIRET avant de l’importer.')
        if company.get('etat_administratif') == 'C':
            warnings.append('Cette entreprise est signalée comme cessée.')
        return dict(fields=fields, details=details, warnings=warnings, source=SOURCE,
                    source_url='https://annuaire-entreprises.data.gouv.fr/etablissement/'+siret,
                    fetched_at=datetime.now(timezone.utc).isoformat())
    raise RegistryError('Aucun établissement public trouvé pour ce SIRET. Vérifiez les 14 chiffres ou complétez la fiche manuellement.', 404)


def lookup_company(siret):
    siret = normalize_siret(siret)
    try:
        # Fixed host, no redirects, timeout and bounded body. Only SIRET is sent.
        with requests.get(SEARCH_URL, params={'q': siret, 'per_page': 1},
                          headers={'Accept': 'application/json', 'User-Agent': 'IntegraleAcademy-BTS/1.0 (https://inscriptionsbts.onrender.com)'},
                          timeout=(8, 12), allow_redirects=False, stream=True) as response:
            if response.status_code == 429:
                raise RegistryError('L’annuaire reçoit trop de demandes. Patientez une minute avant de réessayer.', 429)
            if response.status_code != 200:
                raise RegistryError('L’annuaire est momentanément indisponible. Réessayez ou complétez la fiche manuellement.')
            body = bytearray()
            for chunk in response.iter_content(16384):
                body.extend(chunk)
                if len(body) > 512_000:
                    raise RegistryError('La réponse de l’annuaire est trop volumineuse. Réessayez plus tard.')
            payload = json.loads(body)
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, RegistryError):
            raise
        raise RegistryError('Impossible de joindre l’annuaire pour le moment. Vos informations saisies sont conservées.') from exc
    try:
        return project_company(payload, siret)
    except (TypeError, KeyError, AttributeError) as exc:
        raise RegistryError('La réponse de l’annuaire est invalide. Réessayez dans quelques instants.') from exc


def preview_token(secret, data):
    return URLSafeTimedSerializer(secret, salt='company-registry-preview-v1').dumps(data)


def read_preview(secret, token, siret):
    try:
        if len(token) > 40_000:
            raise BadData('oversized')
        data = URLSafeTimedSerializer(secret, salt='company-registry-preview-v1').loads(token, max_age=7200)
        if not isinstance(data, dict) or data.get('fields', {}).get('siret') != siret:
            raise BadData('mismatched siret')
        return data
    except BadData as exc:
        raise ValueError('L’aperçu de l’annuaire a expiré ou ne correspond plus au SIRET. Relancez la recherche puis l’import.') from exc


def saved_registry(value):
    try:
        data = json.loads(value or '{}')
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}
