"""Client YPAREO NEO.

Tous les secrets et identifiants fonctionnels proviennent exclusivement des
variables d'environnement Render. Ce module ne journalise jamais les jetons.
"""

import logging
import os
import re
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


def _safe_response_message(response):
    """Retourne un message API utile sans exposer un éventuel jeton."""
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("error_description") or payload.get("error") or payload
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
        raise YpareoError(f"Erreur réseau pendant l’authentification YPAREO : {exc}") from exc

    if not response.ok:
        raise YpareoError(
            f"Erreur authentification YPAREO ({response.status_code}) : "
            f"{_safe_response_message(response)}",
            502,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise YpareoError("Réponse d’authentification YPAREO invalide (JSON attendu).") from exc
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
        return [nettoyer_payload(item) for item in value if item not in (None, "", [], {})]
    return value


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
        if not any(adresse.get(key) for key in ("ligne1", "ligne2", "ligne3", "ligne4")):
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


def construire_payload_apprenant(candidat):
    email = _first(candidat, "email")
    telephone = _normaliser_telephone_ypareo(
        _first(candidat, "telephone", "tel", "phone")
    )
    return nettoyer_payload(
        {
            "nom": str(_first(candidat, "nom", "last_name")).upper(),
            "prenom": _first(candidat, "prenom", "first_name"),
            "emails": [{"adresse": email, "isDefault": True}] if email else [],
            "telephones": [
                {
                    "indicatif": "+33",
                    "isDefaultAppel": True,
                    "isDefaultSms": True,
                    "numero": telephone,
                }
            ]
            if telephone
            else [],
            "adresse": _construire_adresse_ypareo(candidat),
            "dateNaissance": _normaliser_date(
                _first(candidat, "date_naissance", "birth_date")
            ),
        }
    )


def _ypareo_formation_environment_name(session_obj):
    training = str(_first(session_obj, "training_type", "name")).upper().strip()
    match = re.search(r"\b(MOS|MCO|NDRC|PI|CI)\b", training)
    if not match:
        raise YpareoError(f"BTS non reconnu pour YPAREO : {training or 'non renseigné'}", 400)
    return f"YPAREO_ID_FORMATION_BTS_{match.group(1)}"


def id_formation_ypareo(session_obj):
    return _env(_ypareo_formation_environment_name(session_obj))


def construire_payload_cursus(session_obj):
    payload = {
        "idFormation": id_formation_ypareo(session_obj),
        "idOrganisme": _env("YPAREO_ID_ORGANISME", required=False),
        "nom": _first(session_obj, "nom", "name", "training_type"),
    }
    situation_id = _env("YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE", required=False)
    if situation_id:
        try:
            payload["idSituationAvantApprentissage"] = int(situation_id)
        except ValueError as exc:
            raise YpareoError(
                "Variable Render invalide : "
                "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE doit contenir un "
                "identifiant numérique YPAREO, ou rester vide.",
                503,
            ) from exc
    return nettoyer_payload(payload)


def _extract_id(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    for container in ("data", "personne", "cursus"):
        nested = data.get(container)
        if isinstance(nested, dict):
            found = _extract_id(nested, *keys)
            if found is not None:
                return found
    return None


def _post_ypareo(url, payload, access_token, operation):
    try:
        response = requests.post(
            url, json=payload, headers=ypareo_headers(access_token), timeout=30
        )
    except requests.RequestException as exc:
        raise YpareoError(f"Erreur réseau pendant {operation} : {exc}") from exc
    if not response.ok:
        detail = _safe_response_message(response)
        if response.status_code == 401:
            detail = f"accès refusé ou jeton expiré. {detail}"
        elif response.status_code == 422:
            detail = f"données refusées par YPAREO. {detail}"
        raise YpareoError(f"Erreur API YPAREO {response.status_code} pendant {operation} : {detail}")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise YpareoError(f"Réponse YPAREO invalide pendant {operation} (JSON attendu).") from exc


def creer_cursus_ypareo(id_personne, session_obj, access_token):
    endpoint = _env("YPAREO_CURSUS_ENDPOINT")
    url = _url(endpoint).replace("{IdPersonne}", str(id_personne)).replace(
        "{id_personne}", str(id_personne)
    )
    if "{IdPersonne}" not in endpoint and "{id_personne}" not in endpoint:
        url = f"{url.rstrip('/')}/{id_personne}/cursus"
    data = _post_ypareo(
        url, construire_payload_cursus(session_obj), access_token, "la création du cursus"
    )
    cursus_id = _extract_id(data, "idCursus", "IdCursus", "id", "Id")
    if cursus_id is None:
        raise YpareoError(
            "YPAREO a créé le cursus mais n’a retourné aucun id cursus.",
            personne_id=id_personne,
        )
    return {"id": cursus_id, "response": data}


def creer_apprenant_ypareo(candidat, session_obj):
    """Crée la personne puis son cursus et retourne les deux résultats."""
    access_token = get_ypareo_access_token()
    personne_id = candidat.get("ypareo_id")
    personne_data = {}
    if not personne_id:
        logger.info("Création de la personne YPAREO pour le candidat %s", candidat.get("id", ""))
        personne_data = _post_ypareo(
            _url(_env("YPAREO_APPRENANTS_ENDPOINT")),
            construire_payload_apprenant(candidat),
            access_token,
            "la création de la personne",
        )
        personne_id = _extract_id(
            personne_data, "idPersonne", "IdPersonne", "id", "Id"
        )
        if personne_id is None:
            raise YpareoError("YPAREO a créé la personne mais n’a retourné aucun id personne.")
        logger.info("Personne YPAREO créée pour le candidat %s", candidat.get("id", ""))
    try:
        cursus = creer_cursus_ypareo(personne_id, session_obj, access_token)
    except YpareoError as exc:
        exc.personne_id = personne_id
        raise
    logger.info("Cursus YPAREO créé pour le candidat %s", candidat.get("id", ""))
    return {
        "personne_id": personne_id,
        "personne_response": personne_data,
        "cursus_id": cursus["id"],
        "cursus_response": cursus["response"],
    }
