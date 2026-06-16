"""Client YPAREO NEO.

Tous les secrets et identifiants fonctionnels proviennent exclusivement des
variables d'environnement Render. Ce module ne journalise jamais les jetons.
"""

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
        raise YpareoError(f"BTS non reconnu pour YPAREO : {training or 'non renseigné'}", 400)
    return f"YPAREO_ID_FORMATION_BTS_{match.group(1)}"


def id_formation_ypareo(session_obj):
    return _env(_ypareo_formation_environment_name(session_obj))


def _id_situation_avant_apprentissage(candidat=None):
    bac_type = _normalize_text(_first(candidat or {}, "bac_type", "type_bac"))
    if "general" in bac_type:
        return 21
    if "professionnel" in bac_type or bac_type == "pro":
        return 31

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


def _extract_id_affectation_module(data):
    return _extract_id(
        data,
        "id_affectation_module",
        "idAffectationModule",
        "idAffectationModuleFormation",
        "idModuleAffectation",
        "idInscription",
    )


def _get_ypareo(url, access_token, operation):
    try:
        response = requests.get(url, headers=ypareo_headers(access_token), timeout=30)
    except requests.RequestException as exc:
        raise YpareoError(f"Erreur réseau pendant {operation} : {exc}") from exc
    if not response.ok:
        detail = _safe_response_message(response)
        logger.error("Réponse YPAREO complète en cas d’erreur (%s): %s", operation, response.text)
        raise YpareoError(f"Erreur API YPAREO {response.status_code} pendant {operation} : {detail}")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise YpareoError(f"Réponse YPAREO invalide pendant {operation} (JSON attendu).") from exc


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


def _recuperer_id_affectation_module(id_personne, cursus_id, cursus_response, cursus_url, access_token):
    id_affectation_module = _extract_id_affectation_module(cursus_response)
    if id_affectation_module is not None:
        logger.info("id_affectation_module récupéré depuis la création du cursus : %s", id_affectation_module)
        return id_affectation_module

    detail_endpoint = _env("YPAREO_CURSUS_DETAIL_ENDPOINT", required=False)
    if detail_endpoint:
        detail_url = (
            _url(detail_endpoint)
            .replace("{IdPersonne}", str(id_personne))
            .replace("{id_personne}", str(id_personne))
            .replace("{IdCursus}", str(cursus_id))
            .replace("{id_cursus}", str(cursus_id))
        )
    else:
        detail_url = f"{cursus_url.rstrip('/')}/{cursus_id}"

    detail = _get_ypareo(
        detail_url,
        access_token,
        "la récupération du détail du cursus BTS MOS",
    )
    id_affectation_module = _extract_id_affectation_module(detail)
    if id_affectation_module is None:
        raise YpareoError(
            "YPAREO a créé le cursus BTS MOS mais l’id_affectation_module est introuvable.",
            personne_id=id_personne,
        )
    logger.info("id_affectation_module récupéré depuis le détail du cursus : %s", id_affectation_module)
    return id_affectation_module


def inscrire_bts_mos_a_action_formation(id_affectation_module, access_token=None):
    if access_token is None:
        access_token = get_ypareo_access_token()
    url = _url(f"/api/inscription/{id_affectation_module}/participation")
    payload = [
        {
            "dateDebut": YPAREO_BTS_MOS_ACTION_FORMATION_DATE_DEBUT,
            "dateFin": YPAREO_BTS_MOS_ACTION_FORMATION_DATE_FIN,
            "id": None,
            "idActionFormation": YPAREO_BTS_MOS_ACTION_FORMATION_ID,
        }
    ]

    response = requests.put(url, json=payload, headers=ypareo_headers(access_token), timeout=30)

    print("YPAREO BTS MOS - URL:", url)
    print("YPAREO BTS MOS - Payload:", payload)
    print("YPAREO BTS MOS - Status:", response.status_code)
    print("YPAREO BTS MOS - Response:", response.text)
    logger.info("URL appelée pour l’action de formation BTS MOS : %s", url)
    logger.info("Payload envoyé pour l’action de formation BTS MOS : %s", payload)
    logger.info("Status code action de formation BTS MOS : %s", response.status_code)

    if not response.ok:
        logger.error("Réponse YPAREO complète en cas d’erreur : %s", response.text)
    response.raise_for_status()
    return response.json() if response.text else None


def creer_cursus_ypareo(id_personne, session_obj, access_token, candidat=None):
    endpoint = _env("YPAREO_CURSUS_ENDPOINT")
    url = _url(endpoint).replace("{IdPersonne}", str(id_personne)).replace(
        "{id_personne}", str(id_personne)
    )
    if "{IdPersonne}" not in endpoint and "{id_personne}" not in endpoint:
        url = f"{url.rstrip('/')}/{id_personne}/cursus"
    data = _post_ypareo(
        url, construire_payload_cursus(session_obj, candidat), access_token, "la création du cursus"
    )
    cursus_id = _extract_id(data, "idCursus", "IdCursus", "id", "Id")
    if cursus_id is None:
        raise YpareoError(
            "YPAREO a créé le cursus mais n’a retourné aucun id cursus.",
            personne_id=id_personne,
        )
    result = {"id": cursus_id, "response": data}
    if _is_bts_mos(session_obj):
        result["id_affectation_module"] = _recuperer_id_affectation_module(
            id_personne, cursus_id, data, url, access_token
        )
    return result


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
        logger.info("idPersonne créé : %s", personne_id)
        logger.info("Personne YPAREO créée pour le candidat %s", candidat.get("id", ""))
    try:
        cursus = creer_cursus_ypareo(personne_id, session_obj, access_token, candidat)
    except YpareoError as exc:
        exc.personne_id = personne_id
        raise
    logger.info("idCursus créé : %s", cursus["id"])
    if _is_bts_mos(session_obj):
        logger.info("id_affectation_module récupéré : %s", cursus["id_affectation_module"])
        inscrire_bts_mos_a_action_formation(cursus["id_affectation_module"], access_token)
    logger.info("Cursus YPAREO créé pour le candidat %s", candidat.get("id", ""))
    return {
        "personne_id": personne_id,
        "personne_response": personne_data,
        "cursus_id": cursus["id"],
        "cursus_response": cursus["response"],
        "id_affectation_module": cursus.get("id_affectation_module"),
    }
