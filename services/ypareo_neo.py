"""Client YPAREO NEO.

Tous les secrets et identifiants fonctionnels proviennent exclusivement des
variables d'environnement Render. Ce module ne journalise jamais les jetons.
"""

import json
import logging
import os
import re
import unicodedata
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

YPAREO_ADRESSE_KEYS = (
    "ligne1",
    "ligne2",
    "ligne3",
    "ligne4",
    "codePostal",
    "ville",
    "paysAlpha",
)

YPAREO_STATUT_PREMIERE_ANNEE = "Stagiaire formation pro 3 mois"
YPAREO_ETAT_CURSUS = "Inscrit"
YPAREO_REFERENT_PEDAGOGIQUE = "Clément VAILLANT"
YPAREO_BTS_MOS_ACTION_FORMATION_ID = 42
YPAREO_BTS_MOS_ACTION_FORMATION_DATE_DEBUT = "2026-07-27"
YPAREO_BTS_MOS_ACTION_FORMATION_DATE_FIN = "2027-07-25"


class YpareoError(Exception):
    """Erreur fonctionnelle ou HTTP présentable dans l'administration."""

    def __init__(self, message, status_code=502, personne_id=None):
        super().__init__(message)
        self.status_code = status_code
        self.personne_id = personne_id


def _env(name, required=True):
    value = (os.getenv(name) or "").strip()
    if required and not value:
        raise YpareoError(f"Variable Render manquante : {name}", 503)
    return value


def _url(endpoint):
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"{_env('YPAREO_API_URL').rstrip('/')}/{endpoint.lstrip('/')}"


def _business_url(endpoint):
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    base = _env("YPAREO_BUSINESS_API_BASE", required=False).rstrip("/")
    if not base:
        base = (
            "https://api-business.ypareo-neo.com/"
            "a1969eb1-2ee5-4591-84d8-22c2ab1224ff/api"
        )
    return f"{base}/{endpoint.lstrip('/')}"


def _safe_response_message(response):
    """Retourne un message API utile sans exposer un éventuel jeton."""
    try:
        payload = response.json()
        message = (
            payload.get("message")
            or payload.get("error_description")
            or payload.get("error")
            or payload
        )
    except ValueError:
        message = response.text or response.reason
    text = str(message)
    for secret_name in ("YPAREO_AUTH_TOKEN",):
        secret = os.getenv(secret_name)
        if secret:
            text = text.replace(secret, "***")
    return text[:1000]


def get_ypareo_access_token():
    auth_token = _env("YPAREO_AUTH_TOKEN")
    if auth_token.lower().startswith("bearer "):
        raise YpareoError(
            "Variable Render invalide : YPAREO_AUTH_TOKEN doit contenir uniquement "
            "le token brut, sans préfixe « Bearer ».",
            503,
        )
    auth_endpoint = _env("YPAREO_AUTH_ENDPOINT")
    try:
        response = requests.post(
            _url(auth_endpoint),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"token": auth_token},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise YpareoError(
            f"Erreur réseau pendant l’authentification YPAREO : {exc}"
        ) from exc

    if not response.ok:
        raise YpareoError(
            f"Erreur authentification YPAREO ({response.status_code}) : "
            f"{_safe_response_message(response)}",
            502,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise YpareoError(
            "Réponse d’authentification YPAREO invalide (JSON attendu)."
        ) from exc
    token = data.get("access_token") or data.get("accessToken") or data.get("token")
    if not token:
        raise YpareoError("L’authentification YPAREO n’a retourné aucun access_token.")
    return token


def ypareo_headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def nettoyer_payload(value):
    """Retire récursivement les valeurs vides, sans supprimer 0 ou False."""
    if isinstance(value, dict):
        return {
            key: nettoyer_payload(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            nettoyer_payload(item) for item in value if item not in (None, "", [], {})
        ]
    return value


def _normalize_text(value):
    value = str(value or "").strip().lower()
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _first(obj, *names):
    for name in names:
        value = obj.get(name)
        if value not in (None, ""):
            return value
    return ""


def _normaliser_telephone_ypareo(value):
    """Retourne un numéro français national à 10 chiffres accepté avec +33."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0033"):
        digits = digits[4:]
    elif digits.startswith("33"):
        digits = digits[2:]
    if len(digits) == 9 and not digits.startswith("0"):
        digits = f"0{digits}"
    if len(digits) != 10 or not digits.startswith("0"):
        return ""
    return digits


def _construire_adresse_ypareo(candidat):
    """Construit exclusivement une adresse candidat au format YPAREO."""
    adresse_source = _first(candidat, "adresse", "address")
    if isinstance(adresse_source, dict):
        adresse = {
            key: adresse_source.get(key)
            for key in YPAREO_ADRESSE_KEYS
            if adresse_source.get(key) not in (None, "")
        }
        if not any(
            adresse.get(key) for key in ("ligne1", "ligne2", "ligne3", "ligne4")
        ):
            return None
        adresse.setdefault(
            "codePostal", _first(candidat, "code_postal", "cp", "zip_code")
        )
        adresse.setdefault("ville", _first(candidat, "ville", "city"))
    elif isinstance(adresse_source, str) and adresse_source.strip():
        adresse = {
            "ligne1": adresse_source.strip(),
            "codePostal": _first(candidat, "code_postal", "cp", "zip_code"),
            "ville": _first(candidat, "ville", "city"),
        }
    else:
        return None

    adresse.setdefault("paysAlpha", "FR")
    return nettoyer_payload(adresse)


def _normaliser_code_pays(value):
    """Retourne un code pays ISO alpha-2 pour les champs YPAREO qui l’attendent."""
    value = str(value or "").strip()
    if not value:
        return ""
    upper = value.upper()
    aliases = {
        "FRANCE": "FR",
        "FRANCAIS": "FR",
        "FRANÇAIS": "FR",
        "FRANCAISE": "FR",
        "FRANÇAISE": "FR",
        "BELGIQUE": "BE",
        "BELGE": "BE",
        "SUISSE": "CH",
        "ESPAGNE": "ES",
        "ESPAGNOL": "ES",
        "ESPAGNOLE": "ES",
        "ITALIE": "IT",
        "ITALIEN": "IT",
        "ITALIENNE": "IT",
        "ALLEMAGNE": "DE",
        "ALLEMAND": "DE",
        "ALLEMANDE": "DE",
        "PORTUGAL": "PT",
        "PORTUGAIS": "PT",
        "PORTUGAISE": "PT",
    }
    if re.fullmatch(r"[A-Z]{2}", upper):
        return upper
    return aliases.get(upper, value)


def _normaliser_date(value):
    value = str(value or "").strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def _mot_cle_mode_formation(candidat):
    mode = _normalize_text(
        _first(candidat, "mode", "mode_formation", "formation_mode", "form_mode")
    )
    if "dist" in mode:
        return "distanciel"
    if "presentiel" in mode or "pres" in mode or "puget" in mode:
        return "présentiel"
    return ""


def construire_payload_apprenant(candidat):
    email = _first(candidat, "email")
    telephone = _normaliser_telephone_ypareo(
        _first(candidat, "telephone", "tel", "phone")
    )
    pays_naissance = _normaliser_code_pays(
        _first(candidat, "pays_naissance", "birth_country")
    )
    nationalite = _normaliser_code_pays(
        _first(candidat, "nationalite", "nationalité", "nationality")
    )
    mot_cle_mode = _mot_cle_mode_formation(candidat)
    return nettoyer_payload(
        {
            "nom": str(_first(candidat, "nom", "last_name")).upper(),
            "prenom": _first(candidat, "prenom", "first_name"),
            "emails": [{"adresse": email, "isDefault": True}] if email else [],
            "telephones": (
                [
                    {
                        "indicatif": "+33",
                        "isDefaultAppel": True,
                        "isDefaultSms": True,
                        "numero": telephone,
                    }
                ]
                if telephone
                else []
            ),
            "adresse": _construire_adresse_ypareo(candidat),
            "dateNaissance": _normaliser_date(
                _first(candidat, "date_naissance", "birth_date")
            ),
            "paysNaissanceAlpha": pays_naissance,
            "communeNaissance": _first(candidat, "ville_naissance", "birth_city"),
            "nationaliteAlpha": nationalite,
            "motsCles": [mot_cle_mode] if mot_cle_mode else [],
        }
    )


def _ypareo_formation_environment_name(session_obj):
    training = str(_first(session_obj, "training_type", "name")).upper().strip()
    match = re.search(r"\b(MOS|MCO|NDRC|PI|CI)\b", training)
    if not match:
        raise YpareoError(
            f"BTS non reconnu pour YPAREO : {training or 'non renseigné'}", 400
        )
    return f"YPAREO_ID_FORMATION_BTS_{match.group(1)}"


def id_formation_ypareo(session_obj):
    return _env(_ypareo_formation_environment_name(session_obj))


def _id_situation_avant_apprentissage(candidat=None):
    situation_id = _env("YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE", required=False)
    if not situation_id:
        return None
    try:
        return int(situation_id)
    except ValueError as exc:
        raise YpareoError(
            "Variable Render invalide : "
            "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE doit contenir un "
            "identifiant numérique YPAREO, ou rester vide.",
            503,
        ) from exc


def construire_payload_cursus(session_obj, candidat=None):
    payload = {
        "idFormation": id_formation_ypareo(session_obj),
        "idOrganisme": _env("YPAREO_ID_ORGANISME", required=False),
        "nom": _first(session_obj, "nom", "name", "training_type"),
        "statutPremiereAnnee": YPAREO_STATUT_PREMIERE_ANNEE,
        "etat": YPAREO_ETAT_CURSUS,
        "referentPedagogique": YPAREO_REFERENT_PEDAGOGIQUE,
    }
    situation_id = _id_situation_avant_apprentissage(candidat)
    if situation_id is not None:
        payload["idSituationAvantApprentissage"] = situation_id
    return nettoyer_payload(payload)


def _extract_id(data, *keys):
    if isinstance(data, list):
        for item in data:
            found = _extract_id(item, *keys)
            if found is not None:
                return found
        return None
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    for nested in data.values():
        if isinstance(nested, (dict, list)):
            found = _extract_id(nested, *keys)
            if found is not None:
                return found
    return None


def _is_bts_mos(session_obj):
    training = _normalize_text(_first(session_obj, "training_type", "name", "nom"))
    return bool(re.search(r"\bbts\b", training) and re.search(r"\bmos\b", training))


def _format_ypareo_payload(data):
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(data)


def _liste_inscriptions_cursus(cursus_response):
    if not isinstance(cursus_response, dict):
        return []
    data = cursus_response.get("data")
    if isinstance(data, dict) and isinstance(data.get("inscriptions"), list):
        return data["inscriptions"]
    if isinstance(cursus_response.get("inscriptions"), list):
        return cursus_response["inscriptions"]
    return []


def _extract_id_inscription_bts_mos_premiere_annee(cursus_response):
    """Retourne l’ID inscription BTS MOS 1ère année depuis la réponse cursus."""
    inscriptions = _liste_inscriptions_cursus(cursus_response)
    logger.info(
        "Liste des inscriptions reçues : %s", _format_ypareo_payload(inscriptions)
    )
    print(
        "YPAREO BTS MOS - Liste des inscriptions reçues:",
        _format_ypareo_payload(inscriptions),
    )

    selected = None
    for inscription in inscriptions:
        if not isinstance(inscription, dict):
            continue
        annee = inscription.get("anneeInscription") or {}
        if isinstance(annee, dict) and annee.get("ordre") == 1:
            selected = inscription
            break

    if selected is None:
        for inscription in inscriptions:
            if not isinstance(inscription, dict):
                continue
            annee = inscription.get("anneeInscription") or {}
            nom = annee.get("nom") if isinstance(annee, dict) else None
            if isinstance(nom, str) and _normalize_text(nom) == "1ere annee":
                selected = inscription
                break

    logger.info(
        "Inscription sélectionnée : %s", _format_ypareo_payload(selected)
    )
    print(
        "YPAREO BTS MOS - Inscription sélectionnée:",
        _format_ypareo_payload(selected),
    )
    if not selected or selected.get("id") in (None, ""):
        raise YpareoError(
            "YPAREO a créé le cursus BTS MOS mais l’id_inscription de 1ère année est introuvable. "
            f"Réponse création cursus : {_format_ypareo_payload(cursus_response)}"
        )

    id_inscription = selected["id"]
    logger.info("id_inscription utilisé : %s", id_inscription)
    print("YPAREO BTS MOS - id_inscription utilisé:", id_inscription)
    return id_inscription


def _get_ypareo(url, access_token, operation):
    try:
        response = requests.get(url, headers=ypareo_headers(access_token), timeout=30)
    except requests.RequestException as exc:
        raise YpareoError(f"Erreur réseau pendant {operation} : {exc}") from exc
    if operation == "la création de la personne":
        logger.info("Réponse création personne : %s", response.text)
    if operation == "la création du cursus":
        print("YPAREO création cursus - réponse complète :", response.text)
        logger.info("Réponse création cursus : %s", response.text)
    if not response.ok:
        detail = _safe_response_message(response)
        logger.error(
            "Réponse YPAREO complète en cas d’erreur (%s): %s", operation, response.text
        )
        raise YpareoError(
            f"Erreur API YPAREO {response.status_code} pendant {operation} : {detail}"
        )
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise YpareoError(
            f"Réponse YPAREO invalide pendant {operation} (JSON attendu)."
        ) from exc


def _post_ypareo(url, payload, access_token, operation):
    if operation == "la création de la personne":
        logger.info("API utilisée pour création personne : %s", url)
    if operation == "la création du cursus":
        logger.info("API utilisée pour création cursus : %s", url)
    try:
        response = requests.post(
            url, json=payload, headers=ypareo_headers(access_token), timeout=30
        )
    except requests.RequestException as exc:
        raise YpareoError(f"Erreur réseau pendant {operation} : {exc}") from exc
    if operation == "la création de la personne":
        logger.info("Réponse création personne : %s", response.text)
    if operation == "la création du cursus":
        print("YPAREO création cursus - réponse complète :", response.text)
        logger.info("Réponse création cursus : %s", response.text)
    if not response.ok:
        detail = _safe_response_message(response)
        if response.status_code == 401:
            detail = f"accès refusé ou jeton expiré. {detail}"
        elif response.status_code == 422:
            detail = f"données refusées par YPAREO. {detail}"
        raise YpareoError(
            f"Erreur API YPAREO {response.status_code} pendant {operation} : {detail}"
        )
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise YpareoError(
            f"Réponse YPAREO invalide pendant {operation} (JSON attendu)."
        ) from exc


def _recuperer_id_inscription_bts_mos(cursus_response):
    return _extract_id_inscription_bts_mos_premiere_annee(cursus_response)


def _extract_numeric_inscription_id(data, public_inscription_guid=None):
    if isinstance(data, list):
        for item in data:
            found = _extract_numeric_inscription_id(item, public_inscription_guid)
            if found is not None:
                return found
        return None
    if not isinstance(data, dict):
        if isinstance(data, str):
            patterns = [r"/module/affectation/(\d+)", r"/inscription/(\d+)"]
            for pattern in patterns:
                match = re.search(pattern, data)
                if match:
                    return int(match.group(1))
        return None

    if public_inscription_guid and data.get("id") == public_inscription_guid:
        for key in (
            "idInterne",
            "idInterneInscription",
            "idInscription",
            "idAffectation",
            "idAffectationModule",
            "id",
        ):
            value = data.get(key)
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                return int(value)

    for key in (
        "idInterneInscription",
        "idInscriptionInterne",
        "idAffectation",
        "idAffectationModule",
        "idInscription",
    ):
        value = data.get(key)
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            return int(value)

    for nested in data.values():
        found = _extract_numeric_inscription_id(nested, public_inscription_guid)
        if found is not None:
            return found
    return None


def rechercher_id_numerique_inscription_bts_mos(
    id_personne, cursus_id, id_inscription_public_guid, access_token
):
    logger.info("Recherche ID numérique interne")
    print("YPAREO BTS MOS - Recherche ID numérique interne")
    if isinstance(id_inscription_public_guid, int) or (
        isinstance(id_inscription_public_guid, str)
        and id_inscription_public_guid.isdigit()
    ):
        return int(id_inscription_public_guid)

    endpoints = []
    configured_endpoint = _env(
        "YPAREO_BUSINESS_INSCRIPTION_DIAGNOSTIC_ENDPOINT", required=False
    )
    if configured_endpoint:
        endpoints.append(configured_endpoint)
    endpoints.extend(
        [
            "/personne/{id_personne}/cursus/{id_cursus}/module/affectation",
            "/personne/{id_personne}/cursus/{id_cursus}/module",
            "/personne/{id_personne}/cursus/{id_cursus}",
        ]
    )

    for endpoint in endpoints:
        url = (
            _business_url(endpoint)
            .replace("{id_personne}", str(id_personne))
            .replace("{IdPersonne}", str(id_personne))
            .replace("{id_cursus}", str(cursus_id))
            .replace("{IdCursus}", str(cursus_id))
            .replace("{id_inscription}", str(id_inscription_public_guid or ""))
            .replace("{IdInscription}", str(id_inscription_public_guid or ""))
        )
        logger.info("URL business appelée : %s", url)
        print("YPAREO BTS MOS - URL business appelée:", url)
        try:
            response = requests.get(
                url, headers=ypareo_headers(access_token), timeout=30
            )
        except requests.RequestException as exc:
            logger.warning("Erreur réseau diagnostic business YPAREO : %s", exc)
            continue
        logger.info(
            "Réponse business reçue (%s) : %s", response.status_code, response.text
        )
        print("YPAREO BTS MOS - Réponse business reçue:", response.status_code, response.text)
        if not response.ok or not response.content:
            continue
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        found = _extract_numeric_inscription_id(payload, id_inscription_public_guid)
        if found is not None:
            logger.info("ID numérique interne trouvé : %s", found)
            return found
    logger.warning("ID numérique interne d’inscription introuvable")
    return None



def _endpoint_business_configure(name, message):
    endpoint = _env(name, required=False)
    if not endpoint:
        raise YpareoError(message, status_code=503)
    return endpoint


def _build_business_url(endpoint, **params):
    url = _business_url(endpoint)
    for key, value in params.items():
        url = url.replace("{" + key + "}", str(value or ""))
        url = url.replace("{" + key[0].upper() + key[1:] + "}", str(value or ""))
    return url


def _get_business_json(url, access_token, log_label):
    logger.info("URL appelée (%s) : %s", log_label, url)
    try:
        response = requests.get(url, headers=ypareo_headers(access_token), timeout=30)
    except requests.RequestException as exc:
        raise YpareoError(f"Erreur réseau pendant {log_label} : {exc}") from exc
    logger.info("Réponse %s (%s) : %s", log_label, response.status_code, response.text)
    if not response.ok:
        raise YpareoError(
            f"Erreur API business YPAREO {response.status_code} pendant {log_label} : {_safe_response_message(response)}"
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text


def _iter_dicts(data):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _iter_dicts(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_dicts(item)


def _numeric_value(obj, *keys):
    for key in keys:
        value = obj.get(key)
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            return int(value)
    return None


def _matches_candidate_business(obj, candidat, id_personne_guid=None):
    email = _normalize_text(_first(candidat, "email", "mail"))
    nom = _normalize_text(_first(candidat, "nom", "last_name", "lastname"))
    prenom = _normalize_text(_first(candidat, "prenom", "first_name", "firstname"))
    date_naissance = _normaliser_date(_first(candidat, "date_naissance", "birth_date", "dateNaissance"))
    serialized = _normalize_text(_format_ypareo_payload(obj))
    if id_personne_guid and str(id_personne_guid) in _format_ypareo_payload(obj):
        return True
    score = 0
    if email and email in serialized:
        score += 3
    if nom and nom in serialized:
        score += 1
    if prenom and prenom in serialized:
        score += 1
    if date_naissance and date_naissance in _format_ypareo_payload(obj):
        score += 1
    return score >= 3 or (score >= 2 and not email)


def rechercher_personne_business_par_email(email, access_token=None, candidat=None, id_personne_guid=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    logger.info("Recherche business personne par email : %s", email)
    endpoint = _endpoint_business_configure(
        "YPAREO_BUSINESS_PERSONNE_SEARCH_ENDPOINT",
        "Personne et cursus créés, mais impossible de retrouver automatiquement l’ID numérique business YPAREO. Vérifier l’endpoint de recherche personne business.",
    )
    url = _build_business_url(endpoint, email=email, q=email, search=email)
    payload = _get_business_json(url, access_token, "recherche business personne")
    logger.info("Réponse business personne : %s", _format_ypareo_payload(payload))
    candidat = candidat or {"email": email}
    for obj in _iter_dicts(payload):
        if not _matches_candidate_business(obj, candidat, id_personne_guid):
            continue
        numeric_id = _numeric_value(
            obj,
            "idPersonneNumerique",
            "idPersonneInterne",
            "idPersonne",
            "idIndividu",
            "id",
        )
        if numeric_id is not None:
            logger.info("ID numérique personne trouvé : %s", numeric_id)
            return numeric_id
    raise YpareoError(
        "Personne et cursus créés, mais impossible de retrouver automatiquement l’ID numérique business YPAREO. Vérifier l’endpoint de recherche personne business.",
        status_code=404,
    )


def recuperer_cursus_business(id_personne_numerique, access_token=None, id_cursus_guid=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    logger.info("Recherche business cursus")
    endpoint = _env("YPAREO_BUSINESS_CURSUS_ENDPOINT", required=False) or "/personne/{id_personne}/cursus"
    url = _build_business_url(endpoint, id_personne=id_personne_numerique, IdPersonne=id_personne_numerique)
    payload = _get_business_json(url, access_token, "recherche business cursus")
    logger.info("Réponse business cursus : %s", _format_ypareo_payload(payload))
    for obj in _iter_dicts(payload):
        serialized = _normalize_text(_format_ypareo_payload(obj))
        guid_match = id_cursus_guid and str(id_cursus_guid) in _format_ypareo_payload(obj)
        mos_match = "bts mos" in serialized or "management operationnel de la securite" in serialized
        if not (guid_match or mos_match):
            continue
        numeric_id = _numeric_value(
            obj,
            "idCursusNumerique",
            "idCursusInterne",
            "idCursus",
            "id",
        )
        if numeric_id is not None:
            logger.info("ID numérique cursus trouvé : %s", numeric_id)
            return numeric_id
    raise YpareoError(
        "Personne et cursus créés, mais impossible de retrouver automatiquement l’ID numérique cursus business YPAREO.",
        status_code=404,
    )


def recuperer_id_affectation_business(id_personne_numerique, id_cursus_numerique, access_token=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    logger.info("Recherche affectation AF")
    endpoint = _env("YPAREO_BUSINESS_AFFECTATION_ENDPOINT", required=False) or "/personne/{id_personne}/cursus/{id_cursus}/module/affectation"
    url = _build_business_url(
        endpoint,
        id_personne=id_personne_numerique,
        IdPersonne=id_personne_numerique,
        id_cursus=id_cursus_numerique,
        IdCursus=id_cursus_numerique,
    )
    payload = _get_business_json(url, access_token, "recherche affectation AF")
    logger.info("Réponse affectation : %s", _format_ypareo_payload(payload))
    found = _extract_numeric_inscription_id(payload)
    if found is not None:
        logger.info("ID numérique affectation trouvé : %s", found)
        return found
    raise YpareoError(
        "Personne et cursus créés, mais impossible de retrouver automatiquement l’ID numérique d’affectation business YPAREO.",
        status_code=404,
    )


def retrouver_ids_numeriques_business_ypareo(candidat, id_personne_guid, id_cursus_guid, access_token=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    id_personne_numerique = rechercher_personne_business_par_email(
        _first(candidat, "email", "mail"),
        access_token,
        candidat=candidat,
        id_personne_guid=id_personne_guid,
    )
    id_cursus_numerique = recuperer_cursus_business(
        id_personne_numerique,
        access_token,
        id_cursus_guid=id_cursus_guid,
    )
    id_affectation_numerique = recuperer_id_affectation_business(
        id_personne_numerique,
        id_cursus_numerique,
        access_token,
    )
    return {
        "id_personne_numerique": id_personne_numerique,
        "id_cursus_numerique": id_cursus_numerique,
        "id_affectation_numerique": id_affectation_numerique,
    }


def rattacher_bts_mos_action_formation_automatiquement(candidat, id_personne_guid, id_cursus_guid, access_token=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    ids = retrouver_ids_numeriques_business_ypareo(
        candidat, id_personne_guid, id_cursus_guid, access_token
    )
    logger.info("PUT participation final")
    participation_response = inscrire_bts_mos_a_action_formation(
        ids["id_affectation_numerique"], access_token
    )
    return ids, participation_response

def construire_payload_participation_bts_mos():
    return [
        {
            "dateDebut": YPAREO_BTS_MOS_ACTION_FORMATION_DATE_DEBUT,
            "dateFin": YPAREO_BTS_MOS_ACTION_FORMATION_DATE_FIN,
            "id": None,
            "idActionFormation": YPAREO_BTS_MOS_ACTION_FORMATION_ID,
        }
    ]


def extraire_id_numerique_affectation_ypareo(value):
    matches = re.findall(r"(\d+)(?!.*\d)", str(value or ""))
    return int(matches[-1]) if matches else None


def inscrire_bts_mos_a_action_formation(id_inscription_ypareo, access_token=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    url = _business_url(f"/inscription/{id_inscription_ypareo}/participation")
    payload = construire_payload_participation_bts_mos()

    response = requests.put(
        url, json=payload, headers=ypareo_headers(access_token), timeout=30
    )

    print("YPAREO BTS MOS - URL PUT participation:", url)
    print("YPAREO BTS MOS - Payload PUT participation:", payload)
    print("YPAREO BTS MOS - Status code:", response.status_code)
    print("YPAREO BTS MOS - Réponse YPAREO:", response.text)
    logger.info("URL PUT participation appelée : %s", url)
    logger.info("Payload envoyé pour l’action de formation BTS MOS : %s", payload)
    logger.info("Status code action de formation BTS MOS : %s", response.status_code)
    logger.info("Réponse YPAREO action de formation BTS MOS : %s", response.text)

    if not response.ok:
        logger.error("Réponse YPAREO complète en cas d’erreur : %s", response.text)
        if response.status_code == 404:
            raise YpareoError(
                "ID numérique interne d’inscription introuvable. Vérifier que l’URL business et l’ID numérique interne sont utilisés.",
                status_code=404,
            )
        raise YpareoError(
            f"Erreur YPAREO participation ({response.status_code}) : {_safe_response_message(response)}"
        )
    return response.json() if response.text else None


def creer_cursus_ypareo(id_personne, session_obj, access_token, candidat=None):
    endpoint = _env("YPAREO_CURSUS_ENDPOINT")
    url = (
        _url(endpoint)
        .replace("{IdPersonne}", str(id_personne))
        .replace("{id_personne}", str(id_personne))
    )
    if "{IdPersonne}" not in endpoint and "{id_personne}" not in endpoint:
        url = f"{url.rstrip('/')}/{id_personne}/cursus"
    data = _post_ypareo(
        url,
        construire_payload_cursus(session_obj, candidat),
        access_token,
        "la création du cursus",
    )
    cursus_id = _extract_id(data, "idCursus", "IdCursus", "id", "Id")
    if cursus_id is None:
        raise YpareoError(
            "YPAREO a créé le cursus mais n’a retourné aucun id cursus.",
            personne_id=id_personne,
        )
    logger.info("ID cursus public GUID : %s", cursus_id)
    result = {"id": cursus_id, "response": data}
    if _is_bts_mos(session_obj):
        id_inscription_guid = _recuperer_id_inscription_bts_mos(data)
        result["id_inscription_ypareo"] = id_inscription_guid
        result["id_inscription_public_guid"] = id_inscription_guid
        result["id_inscription_numerique_interne"] = None
    return result


def creer_apprenant_ypareo(candidat, session_obj):
    """Crée la personne puis son cursus et retourne les deux résultats."""
    access_token = get_ypareo_access_token()
    personne_id = candidat.get("ypareo_id") or candidat.get("ypareo_id_personne")
    personne_data = {}
    if not personne_id:
        logger.info(
            "Création de la personne YPAREO pour le candidat %s", candidat.get("id", "")
        )
        personne_data = _post_ypareo(
            _url(_env("YPAREO_APPRENANTS_ENDPOINT")),
            construire_payload_apprenant(candidat),
            access_token,
            "la création de la personne",
        )
        personne_id = _extract_id(personne_data, "idPersonne", "IdPersonne", "id", "Id")
        if personne_id is None:
            raise YpareoError(
                "YPAREO a créé la personne mais n’a retourné aucun id personne."
            )
        logger.info("idPersonne créé : %s", personne_id)
        logger.info("ID personne public GUID : %s", personne_id)
        logger.info("Personne YPAREO créée pour le candidat %s", candidat.get("id", ""))
    if personne_id:
        logger.info("idPersonne créé ou réutilisé : %s", personne_id)
    try:
        cursus = creer_cursus_ypareo(personne_id, session_obj, access_token, candidat)
    except YpareoError as exc:
        exc.personne_id = personne_id
        raise
    logger.info("idCursus créé : %s", cursus["id"])
    participation_warning = ""
    participation_response = None
    if _is_bts_mos(session_obj):
        logger.info(
            "ID inscription public GUID : %s", cursus.get("id_inscription_public_guid")
        )
        id_guid = cursus.get("id_inscription_public_guid")
        logger.info("Tentative PUT participation avec GUID")
        logger.info("id_inscription GUID utilisé : %s", id_guid)
        try:
            participation_response = inscrire_bts_mos_a_action_formation(
                id_guid, access_token
            )
        except YpareoError as exc:
            if getattr(exc, "status_code", None) == 404:
                try:
                    ids_business, participation_response = rattacher_bts_mos_action_formation_automatiquement(
                        candidat, personne_id, cursus["id"], access_token
                    )
                    cursus["id_personne_numerique_business"] = ids_business.get("id_personne_numerique")
                    cursus["id_cursus_numerique_business"] = ids_business.get("id_cursus_numerique")
                    cursus["id_inscription_numerique_interne"] = ids_business.get("id_affectation_numerique")
                except YpareoError as business_exc:
                    participation_warning = (
                        "Personne et cursus créés, mais impossible de retrouver automatiquement l’ID numérique business YPAREO. "
                        "Vérifier l’endpoint de recherche personne business."
                    )
                    logger.warning("Si 404 : passage en statut AF en attente")
                    logger.warning("Automatisation business YPAREO échouée : %s", business_exc)
                    logger.warning(participation_warning)
            else:
                participation_warning = str(exc)
                logger.warning(
                    "Inscription à l’action de formation non effectuée : %s", exc
                )
    logger.info("Cursus YPAREO créé pour le candidat %s", candidat.get("id", ""))
    return {
        "personne_id": personne_id,
        "personne_response": personne_data,
        "cursus_id": cursus["id"],
        "cursus_response": cursus["response"],
        "id_inscription_ypareo": cursus.get("id_inscription_ypareo"),
        "id_inscription_public_guid": cursus.get("id_inscription_public_guid"),
        "id_inscription_numerique_interne": cursus.get(
            "id_inscription_numerique_interne"
        ),
        "id_personne_numerique_business": cursus.get("id_personne_numerique_business"),
        "id_cursus_numerique_business": cursus.get("id_cursus_numerique_business"),
        "participation_response": participation_response,
        "participation_warning": participation_warning,
    }
