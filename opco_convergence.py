"""Read-only CFA Convergence client. Never persist a raw CERFA or a payment account."""
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

import requests

from akto_portal import START_DATE, norm
from wedof_contract_data import FINANCERS, STATES, WedofError, date, nonnegative, obj, raw_fields, stamp, text

PROVIDERS = {
    'opcommerce': ('opcoCfaOpcommerce', 'lopcommerce.com', 'https://partenaire.lopcommerce.com/'),
    'mobilites': ('opcoCfaMobilites', 'opcomobilites.fr', 'https://mgestion.opcomobilites.fr/'),
    'ep': ('opcoCfaEp', 'opcoep.fr', 'https://cfa.opcoep.fr/#/visitor/auth'),
}
STATE_CODES = {'TRANSMIS': 'sent', 'EN_COURS_INSTRUCTION': 'pendingAcceptation', 'ENGAGE': 'accepted',
               'ANNULE': 'cancelled', 'REFUSE': 'refused', 'RUPTURE': 'broken', 'RUTPURE': 'broken', 'SOLDE': 'completed'}


class ReadError(ValueError):
    pass


def endpoint(provider, field, value):
    # An operator can pin the exact URL supplied at onboarding for a hosted gateway.
    pinned = os.environ.get(f'OPCO_{provider.upper()}_{field.upper()}_URL')
    url = (pinned or value or '').strip().rstrip('/')
    try:
        parts = urlsplit(url)
        host, domain = (parts.hostname or '').lower(), PROVIDERS[provider][1]
        trusted = host == domain or host.endswith('.' + domain)
        if field == 'token' and host == 'login.microsoftonline.com':
            trusted = bool(re.fullmatch(r'/[a-zA-Z0-9.-]+/oauth2/(v2\.0/)?token', parts.path))
        if (not (trusted or pinned) or parts.scheme != 'https' or not host or
                parts.port not in (None, 443) or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError
    except ValueError:
        raise ReadError('Vérifiez les adresses HTTPS de production fournies par cet OPCO.') from None
    return url


def paged(read, path, key, params):
    seen, number = 0, 1
    while True:
        data = read(path, {**params, 'numeroPage': number})
        if isinstance(data, list) and len(data) == 1:
            data = data[0]  # Some invoice implementations wrap the page in an array.
        if not isinstance(data, dict):
            raise ReadError('Format de page Convergence inattendu.')
        rows = data.get(key, data.get(key[0].lower() + key[1:]))
        total = data.get('total')
        if rows is None and total == 0:
            rows = []
        if (not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows) or
                type(total) is not int or total < 0 or data.get('page') != number or
                data.get('count') != len(rows) or seen + len(rows) > total or (not rows and seen < total)):
            raise ReadError('La liste reçue est incomplète. Relancez la lecture.')
        yield from rows
        seen += len(rows)
        if seen == total:
            return
        number += 1


class Client:
    def __init__(self, provider, config):
        self.base = endpoint(provider, 'api', config.get('api'))
        self.token_url = endpoint(provider, 'token', config.get('token'))
        self.config, self.bearer, self.expires = config, '', 0

    @staticmethod
    def json_request(method, url, **kwargs):
        try:
            with requests.request(method, url, timeout=(5, 30), allow_redirects=False, stream=True, **kwargs) as response:
                if response.status_code == 401:
                    raise ReadError('Accès refusé. Vérifiez les identifiants techniques et leur validité.')
                if response.status_code == 403:
                    raise ReadError('Lecture refusée. Vérifiez la clé CFA et les habilitations Convergence.')
                if response.status_code != 200:
                    raise ReadError(f'Le service de lecture a répondu HTTP {response.status_code}.')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 12_000_000:
                        raise ReadError('Réponse trop volumineuse.')
                result = json.loads(data)
                if isinstance(result, dict) and result.get('status') == 'error':
                    raise ReadError('La demande de lecture a été refusée par l’OPCO.')
                return result
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            if isinstance(exc, ReadError):
                raise
            raise ReadError('Réponse Convergence inaccessible ou illisible.') from None

    def read(self, path, params):
        if time.monotonic() >= self.expires:
            payload = {'grant_type': 'client_credentials', 'client_id': self.config['client_id'],
                       'client_secret': self.config['client_secret']}
            if self.config.get('scope'):
                payload['scope'] = self.config['scope']
            token = self.json_request('POST', self.token_url, data=payload)
            self.bearer = obj(token).get('access_token')
            if not isinstance(self.bearer, str) or not self.bearer:
                raise ReadError('Le serveur d’authentification n’a pas délivré de jeton.')
            self.expires = time.monotonic() + max(1, int(token.get('expires_in', 3600)) - 60)
        headers = {'Authorization': 'Bearer ' + self.bearer, 'X-Api-Key': self.config['key'],
                   'EDITEUR': 'Integrale Academy', 'LOGICIEL': 'Inscriptions BTS', 'VERSION': '1.0', 'Accept': 'application/json'}
        return self.json_request('GET', self.base + path, params=params, headers=headers)


def identity(last, first, birth):
    return norm(last), norm(first), date(birth)


def dossier(provider, raw, ref):
    cerfa = obj(obj(raw).get('cerfa'))
    if text(cerfa.get('numeroInterne')) != ref:
        raise ReadError('Le numéro du dossier reçu ne correspond pas à la référence demandée.')
    start = date(obj(cerfa.get('contrat')).get('dateDebutContrat'))
    if not start:
        raise ReadError('Date de début du contrat indisponible.')
    if start < START_DATE:
        return None
    fields = raw_fields(raw, {'external_number': ref})
    state = STATE_CODES.get(cerfa.get('etat'), 'unknown')
    fields.update(source='convergence', financer=PROVIDERS[provider][0], state=state,
                  state_label=STATES.get(state, 'État non communiqué'), engagement=nonnegative(raw.get('engagement')),
                  external_number=text(cerfa.get('numeroExterne')) or ref, checked_at=stamp(),
                  working_contract_id=provider + '-' + hashlib.sha256(ref.encode()).hexdigest()[:24],
                  contract_type=text(obj(cerfa.get('contrat')).get('typeContratApp')))
    if fields['raw_stale']:
        fields['raw_error'] = 'Cet OPCO n’a pas fourni d’échéancier exploitable lors de cette lecture.'
    return fields


def invoices(client, ref):
    result = {}
    for invoice in paged(client.read, '/v2/factures/etats', 'factures', {'numeroInterneDossier': ref}):
        lines = invoice.get('dossiers')
        matching = [line for line in (lines or []) if isinstance(line, dict) and text(line.get('numeroInterneDossier')) == ref]
        key = text(invoice.get('numeroInterneFacture')) or text(invoice.get('referenceFactureCFA'))
        if not key or len(matching) != 1 or key in result:
            raise ReadError('Facture non identifiable pour ce dossier.')
        result[key] = {'reference': text(invoice.get('referenceFactureCFA')) or key, 'state': text(invoice.get('etatFacture')),
                       'amount': nonnegative(matching[0].get('montant')), 'paid_on': date(invoice.get('dateReglement'))}
    return list(result.values())


def read_contracts(provider, config, people, since, previous, client_factory=Client):
    client = client_factory(provider, config)
    roster = {}
    names = set()
    for p in people:
        key = identity(p['nom'], p['prenom'], p['date_naissance'])
        names.add(key[:2])
        if all(key):
            roster.setdefault(key, []).append(p['id'])
    refs = {}
    for entry in paged(client.read, '/v2/dossiers/etats', 'EtatDossierResult', {'dateModification': since or START_DATE}):
        ref = text(entry.get('numeroInterne'))
        if not ref or ref in refs:
            raise ReadError('Index des dossiers incomplet ou en double.')
        refs[ref] = True
    # Refresh attached contracts even if only a payment changed in the OPCO system.
    active = list(dict.fromkeys([*refs, *previous]))
    results, failed = {}, set()
    for i in range(0, len(active), 30):
        batch = active[i:i+30]
        response = client.read('/v1/dossiers/liste', {'numerosInternes': ','.join(batch)})
        if not isinstance(response, dict) or not isinstance(response.get('dossiers'), list):
            raise ReadError('Lecture groupée des dossiers incomplète.')
        returned = set()
        for raw in response['dossiers']:
            ref = text(obj(obj(raw).get('cerfa')).get('numeroInterne'))
            if ref not in batch or ref in returned:
                raise ReadError('Une référence de la lecture groupée ne correspond pas.')
            returned.add(ref)
            try:
                item = dossier(provider, raw, ref)
                if item is None:
                    continue
                key = identity(item.get('apprentice_last_name'), item.get('apprentice_first_name'), item.get('apprentice_birth_date'))
                candidates = roster.get(key, [])
                if (not all(key) and (key[:2] in names or ref in previous)) or len(candidates) > 1:
                    failed.add(ref)
                    continue
                if not candidates:
                    if key[:2] in names:
                        failed.add(ref)
                    continue
                if provider != 'ep':
                    try:
                        item['invoices'] = invoices(client, ref)
                    except ReadError:
                        item['invoice_error'] = 'Détail des factures indisponible lors de cette lecture.'
                        failed.add(ref)
                results[ref] = (candidates[0], item)
                if item['raw_stale']:
                    failed.add(ref)
            except (ReadError, WedofError):
                failed.add(ref)
        failed.update(set(batch) - returned)
    return results, failed, set(active)
