"""Admission rules and calendar of the existing 2027 security apprenticeship."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

YEAR = 2027
PUBLIC_URL = "https://www.integraleconnect.com/parcoursalternance"
SITUATIONS = ("En études", "En emploi", "En recherche d’emploi", "En reconversion", "Autre situation")
SLOTS = ("Le matin", "L’après-midi", "Peu importe")
TIMELINE = (
    {"period": "Janvier → février", "title": "Tu prépares l’APS", "detail": "175 h de formation, examen puis demande de carte professionnelle CNAPS.", "kind": "aps"},
    {"period": "Mars → juin", "title": "Tu passes à l’action en entreprise", "detail": "Tes premières missions de sécurité, après obtention des autorisations nécessaires.", "kind": "work"},
    {"period": "Juin → juillet", "title": "Tu prépares l’A3P", "detail": "328 h pour apprendre la protection physique des personnes et le travail en équipe.", "kind": "a3p"},
    {"period": "Juillet → décembre", "title": "Tu développes ton expérience", "detail": "Une nouvelle période en entreprise pour gagner en autonomie.", "kind": "work"},
    {"period": "Décembre", "title": "Tu complètes avec le SSIAP 1", "detail": "70 h de formation en sécurité incendie, puis l’examen.", "kind": "ssiap"},
)


def today():
    return dt.datetime.now(ZoneInfo("Europe/Paris")).date()


def age_on(birth, day):
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def validate(payload, day=None, *, imported=False):
    if not isinstance(payload, dict):
        raise ValueError("Le formulaire est invalide.")
    day = day or today()
    try:
        birth = dt.date.fromisoformat(str(payload.get("birth_date", "")))
    except ValueError:
        raise ValueError("Indique une date de naissance valide.") from None
    if birth >= day or age_on(birth, day) > 120:
        raise ValueError("Vérifie ta date de naissance.")
    if age_on(birth, day) >= 26:
        raise ValueError("Malheureusement, tu ne peux pas candidater à ce parcours sécurité en alternance : il est réservé aux personnes de moins de 26 ans au moment de leur candidature.")
    if payload.get("available_year") is not True:
        raise ValueError("Tu dois être disponible de janvier à décembre 2027 pour candidater à ce parcours.")
    if not imported and payload.get("judicial_clear") is not True:
        raise ValueError("Malheureusement, tu ne peux pas poursuivre cette candidature en ligne. Contacte notre équipe pour faire le point sur ta situation et les démarches CNAPS. Seul le CNAPS décide de la délivrance de ses autorisations.")
    if payload.get("license_b") is not True:
        raise ValueError("Le permis B est nécessaire pour ce parcours. Contacte-nous pour préparer une future candidature.")
    if payload.get("mobile_departments") is not True:
        raise ValueError("Tu dois pouvoir te déplacer en entreprise dans le Var et les Alpes-Maritimes, notamment à Cannes.")
    if payload.get("privacy_consent") is not True:
        raise ValueError("Confirme que tu as lu l’information sur tes données et que tu souhaites être recontacté pour ta candidature.")
    clean = {}
    for field, label, minimum, maximum in (
        ("last_name", "ton nom", 1, 100), ("first_name", "ton prénom", 1, 100),
        ("city", "ta ville", 2, 120), ("motivation", "ta motivation (30 caractères minimum)", 30, 2000),
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            raise ValueError(f"Vérifie {label}.")
        clean[field] = value.strip()
    for field in ("last_name", "first_name", "city"):
        clean[field] = " ".join(clean[field].split())
    clean["last_name"] = clean["last_name"].upper()
    email = str(payload.get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s<>@\x00-\x1f]+@[^\s<>@\x00-\x1f]+\.[^\s<>@\x00-\x1f]+", email):
        raise ValueError("Vérifie ton adresse e-mail.")
    phone = re.sub(r"[ .()\-]", "", str(payload.get("phone", "")))
    if not re.fullmatch(r"(?:0[1-9]\d{8}|\+[1-9]\d{7,14})", phone):
        raise ValueError("Vérifie ton numéro de téléphone, par exemple 06 12 34 56 78.")
    postcode = str(payload.get("postcode", "")).strip()
    if not re.fullmatch(r"\d{5}", postcode):
        raise ValueError("Indique un code postal à 5 chiffres.")
    situation, slot, vehicle = payload.get("situation"), payload.get("contact_slot"), payload.get("vehicle")
    if situation not in SITUATIONS or slot not in SLOTS or vehicle not in ("yes", "no", "planned"):
        raise ValueError("Complète ta situation, ton moyen de transport et ton créneau de contact.")
    clean.update(birth_date=birth.isoformat(), email=email, phone=phone, postcode=postcode,
                 situation=situation, contact_slot=slot, vehicle=vehicle, campaign=YEAR,
                 available_year=True, license_b=True, mobile_departments=True, privacy_consent=True,
                 privacy_version="2026-10-22", age_at_submission=age_on(birth, day))
    # Do not persist criminal-history answers, failed applications or arbitrary fields.
    return clean
