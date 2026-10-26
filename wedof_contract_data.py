"""Allowlisted apprenticeship fields, adapted from Gestion Stagiaires.

WEDOF OpenAPI checked 2026-10-26. No unrestricted CERFA, NIR or banking data
is retained. Missing amounts remain unknown, never converted to zero.
"""
import datetime as dt
import hashlib
import json
import math
import re


class WedofError(ValueError):
    def __init__(self, message, code="wedof_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


WedofApiError = WedofError


FINANCERS = {"opcoCfaAkto": "AKTO", "opcoCfaEp": "OPCO EP",
             "opcoCfaOpcommerce": "L’Opcommerce", "opcoCfaMobilites": "OPCO Mobilités",
             "opcoCfaAtlas": "Atlas", "opcoCfaAfdas": "Afdas", "opcoCfaOcapiat": "OCAPIAT",
             "opcoCfaUniformation": "Uniformation", "opcoCfa2i": "OPCO 2i",
             "opcoCfaConstructys": "Constructys", "opcoCfaSante": "OPCO Santé"}
STATES = {"draft": "Brouillon", "sent": "Transmis", "pendingAcceptation": "En instruction",
          "accepted": "Engagé", "cancelled": "Annulé", "refused": "Refusé",
          "broken": "Rompu", "completed": "Soldé"}


def text(value):
    return str(value).strip()[:500] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def obj(value):
    return value if isinstance(value, dict) else {}


def identifier(value):
    value = text(value)
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise WedofApiError("Identifiant de contrat WEDOF invalide.", "invalid_working_contract")
    return value


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def date(value):
    try:
        return dt.date.fromisoformat(text(value)[:10]).isoformat()
    except ValueError:
        return ""


def nonnegative(value):
    """Keep a source zero, but never turn absent or invalid numbers into zero."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
        if math.isfinite(number) and 0 <= number <= 100000000:
            return int(number) if number.is_integer() else number
        return None
    except ValueError:
        return None


def address_fields(value, prefix):
    address = obj(value)
    line = text(address.get("adresse1")) or " ".join(filter(None, (
        text(address.get("numero")), text(address.get("voie")))))
    return {prefix + "_address": " ".join(filter(None, (line, text(address.get("adresse2") or address.get("complement"))))),
            prefix + "_postcode": text(address.get("codePostal")), prefix + "_city": text(address.get("commune"))}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def financer_label(value):
    return FINANCERS.get(value, "OPCO non communiqué")


def financer_filter(value=""):
    if not isinstance(value, str) or (value and value not in FINANCERS):
        raise WedofApiError("Choisissez un OPCO pris en charge.", "invalid_financer")
    return value or ",".join(FINANCERS)


def normalize_summary(item):
    if not isinstance(item, dict) or not isinstance(item.get("financer"), str) or item["financer"] not in FINANCERS:
        raise WedofApiError("La réponse ne correspond pas à un contrat d’un OPCO pris en charge.", "invalid_working_contract")
    key = identifier(item.get("id"))
    links = obj(item.get("_links"))
    employer, folder = obj(links.get("employer")), obj(links.get("registrationFolder"))
    # Only allowlisted useful data are persisted; never NIR, IBAN, tokens or URLs.
    result = {"working_contract_id": key, "internal_number": "", "external_number": text(item.get("externalIdTrainingOrganism")),
              "deca_number": text(item.get("externalIdDeca")), "financer": item["financer"],
              "registration_id": text(folder.get("externalId")), "state": text(item.get("state")),
              "state_label": STATES.get(text(item.get("state")), "État non communiqué"),
              "contract_type": text(item.get("type")), "contract_start": date(item.get("startDate")),
              "contract_end": date(item.get("endDate")), "contract_conclusion": date(item.get("signedDate")),
              "contract_break_date": date(item.get("breakingDate")), "amendment_date": date(item.get("amendmentDate")),
              "employer_name": text(employer.get("name")), "employer_siret": text(employer.get("siret")),
              "source_updated_at": text(item.get("lastUpdate") or item.get("updatedOn")),
              "wedof_updated_at": text(item.get("updatedOn")),
              "engagement": item.get("amount") if isinstance(item.get("amount"), (int, float)) and not isinstance(item.get("amount"), bool) else None}
    # Reject NaN/Infinity/negative engagements instead of displaying an invented zero.
    import math
    if result["engagement"] is not None and (not math.isfinite(result["engagement"]) or result["engagement"] < 0):
        result["engagement"] = None
    result["summary_hash"] = fingerprint(result)
    return result


def folder_fields(folder, expected_id):
    if (not isinstance(folder, dict) or not expected_id or text(folder.get("externalId")) != expected_id
            or folder.get("type") not in {"opcoCfa", "opco"}):
        raise WedofApiError("Le dossier lié ne correspond pas à ce contrat d’apprentissage.", "invalid_apprenticeship_folder")
    attendee = obj(folder.get("attendee"))
    address = obj(attendee.get("address"))
    training = obj(folder.get("trainingActionInfo"))
    certification = obj(obj(folder.get("_links")).get("certification"))
    return {"apprentice_first_name": text(attendee.get("firstName")), "apprentice_last_name": text(attendee.get("lastName")),
            "apprentice_email": text(attendee.get("email")), "apprentice_phone": text(attendee.get("phoneNumber")),
            "apprentice_birth_date": date(attendee.get("dateOfBirth")),
            "apprentice_address": text(attendee.get("fullAddress") or address.get("line4")),
            "apprentice_postcode": text(address.get("zipCode")), "apprentice_city": text(address.get("city")),
            "training_title": text(training.get("title")), "rncp": text(certification.get("externalId")),
            "training_start": date(training.get("sessionStartDate")), "training_end": date(training.get("sessionEndDate")),
            "training_hours": text(training.get("hoursInCenter")), "folder_type": folder.get("type"),
            "details_checked_at": stamp(), "details_error": ""}


def raw_fields(raw, contract):
    """Accept only a recognisable, matching CFA Dock dossier. Beta stays optional."""
    if not isinstance(raw, dict) or not isinstance(raw.get("cerfa"), dict):
        raise WedofApiError("Les données OPCO ne contiennent pas de dossier CFA Dock exploitable.", "raw_format_unavailable")
    cerfa = raw["cerfa"]
    number = contract.get("external_number")
    numbers = {text(cerfa.get("numeroInterne")), text(cerfa.get("numeroExterne"))} - {""}
    deca = text(cerfa.get("numeroDeca") or obj(cerfa.get("contrat")).get("noContrat"))
    if not ((number and number in numbers) or (deca and deca == contract.get("deca_number"))):
        raise WedofApiError("L’identité du dossier OPCO n’a pas pu être vérifiée.", "raw_identity_mismatch")
    apprentice, employer = obj(cerfa.get("apprenti")), obj(cerfa.get("employeur") or cerfa.get("employeurV2"))
    training, agreement, tutor = obj(cerfa.get("formation")), obj(cerfa.get("contrat")), obj(cerfa.get("maitre1"))
    # CFA Dock v1/v2 allowlist. Never persist the unrestricted CERFA (NIR, bank or health data).
    fields = {"internal_number": text(cerfa.get("numeroInterne")), "deca_number": deca,
              "contract_number": text(agreement.get("noContrat")),
              "apprentice_first_name": text(apprentice.get("prenom")), "apprentice_last_name": text(apprentice.get("nom")),
              "apprentice_email": text(apprentice.get("courriel")), "apprentice_phone": text(apprentice.get("telephone")),
              "apprentice_birth_date": date(apprentice.get("dateNaissance")),
              "employer_name": text(employer.get("denomination")) or " ".join(filter(None, (text(employer.get("prenom")), text(employer.get("nom"))))),
              "employer_siret": text(employer.get("siret")), "employer_email": text(employer.get("courriel")),
              "employer_phone": text(employer.get("telephone")),
              "tutor_name": " ".join(filter(None, (text(tutor.get("prenom")), text(tutor.get("nom"))))),
              "tutor_email": text(tutor.get("courriel")),
              "training_title": text(training.get("intituleQualification")), "rncp": text(training.get("rncp")),
              "diploma_code": text(training.get("codeDiplome")), "training_start": date(training.get("dateDebutFormation")),
              "training_end": date(training.get("dateFinFormation")), "training_hours": nonnegative(training.get("dureeFormation")),
              "remote_hours": nonnegative(training.get("nombreHeuresEnDistanciel")),
              "contract_start": date(agreement.get("dateDebutContrat")), "contract_end": date(agreement.get("dateFinContrat")),
              "contract_conclusion": date(agreement.get("dateConclusion")), "contract_break_date": date(agreement.get("dateRupture")),
              "gross_salary": nonnegative(agreement.get("salaireEmbauche")),
              **address_fields(apprentice.get("adresse"), "apprentice"), **address_fields(employer.get("adresse"), "employer")}
    fields = {key: value for key, value in fields.items() if value is not None and value != ""}
    schedules = raw.get("echeances")
    if isinstance(schedules, list) and all(isinstance(x, dict) for x in schedules):
        allowed = {"numero", "codification", "montantTotal", "montantRegle", "montantEnCoursInstruction", "dateOuverture", "dateDebut", "dateFin"}
        fields["schedules"] = [{k: (date(v) if k.startswith("date") else nonnegative(v) if k.startswith("montant") else text(v))
                                for k, v in x.items() if k in allowed} for x in schedules]
    costs = raw.get("engagementsFraisAnnexe")
    fields["extra_costs_available"] = isinstance(costs, list) and all(isinstance(x, dict) for x in costs)
    if fields["extra_costs_available"]:
        fields["extra_costs"] = [{"natureFrais": text(x.get("natureFrais")),
                                  **{key: nonnegative(x.get(key)) for key in ("quantite", "prixUnitaire", "montantTotal")}} for x in costs]
        fields["extra_costs_checked_at"] = stamp()
    details = raw.get("detailsFacturation")
    fields["billing_details_available"] = isinstance(details, dict)
    if fields["billing_details_available"]:
        fields["billing_details"] = {key: nonnegative(details.get(key)) for key in (
            "plafondFraisPremierEquipement", "plafondFraisMobilite")}
        fields["billing_details"].update({key: details[key] for key in (
            "fraisPremierEquipementRegles", "fraisMobiliteRegles") if isinstance(details.get(key), bool)})
        periods = details.get("periodesFraisAnnexes")
        if isinstance(periods, list) and all(isinstance(x, dict) for x in periods):
            fields["billing_details"]["periodesFraisAnnexes"] = [
                {"numeroEcheance": text(x.get("numeroEcheance")), "nature": text(x.get("nature"))} for x in periods]
    verified_schedules = "schedules" in fields
    fields.update(raw_attempted_at=stamp(), raw_stale=not verified_schedules,
                  raw_error="" if verified_schedules else "WEDOF ne restitue pas d’échéancier exploitable. Les éventuelles échéances précédentes restent à vérifier.")
    if verified_schedules:
        fields["raw_checked_at"] = stamp()
    return fields
