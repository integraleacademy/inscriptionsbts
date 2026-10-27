"""Presentation of structured person names; never changes stored identities."""
import re


def _clean(value):
    return ' '.join(str(value or '').split())


def last_name(value):
    return _clean(value).upper()


def first_name(value):
    return ''.join(part.capitalize() for part in re.split(r"([ '’\-‐‑‒–—])", _clean(value).lower()))


def person_name(nom, prenom):
    return ' '.join(filter(None, (first_name(prenom), last_name(nom))))


def person_initials(nom, prenom):
    return (first_name(prenom)[:1] + last_name(nom)[:1]).upper()
