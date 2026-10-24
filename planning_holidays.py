"""French national public holidays, computed locally for every planning year.

Metropolitan national calendar (11 holidays); no department-specific additions.
Reference: https://www.service-public.gouv.fr/particuliers/vosdroits/F2405
Gregorian Easter uses the Meeus/Jones/Butcher algorithm. No network dependency
is needed to keep scheduling blocked on future years' public holidays.
"""
from datetime import date, timedelta
from functools import lru_cache
from types import MappingProxyType


@lru_cache(maxsize=128)
def french_public_holidays(year):
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        raise ValueError('Année de calendrier invalide.')
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day0 = divmod(h + l - 7 * m + 114, 31)
    easter = date(year, month, day0 + 1)
    entries = [
        (date(year, 1, 1), 'Jour de l’an'),
        (easter + timedelta(days=1), 'Lundi de Pâques'),
        (date(year, 5, 1), 'Fête du Travail'),
        (date(year, 5, 8), 'Victoire de 1945'),
        (easter + timedelta(days=39), 'Ascension'),
        (easter + timedelta(days=50), 'Lundi de Pentecôte'),
        (date(year, 7, 14), 'Fête nationale'),
        (date(year, 8, 15), 'Assomption'),
        (date(year, 11, 1), 'Toussaint'),
        (date(year, 11, 11), 'Armistice de 1918'),
        (date(year, 12, 25), 'Noël'),
    ]
    result = {}
    for day, name in sorted(entries):
        key = day.isoformat()
        result[key] = result[key] + ' · ' + name if key in result else name
    return MappingProxyType(result)



def public_holiday_name(day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return french_public_holidays(day.year).get(day.isoformat())
