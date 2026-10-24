"""Small, cached adapters for public place suggestions; no candidate data is sent."""
import json
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import requests
from flask import jsonify, request


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if unicodedata.category(c) != 'Mn')


def _get(url, params):
    response = requests.get(url, params=params, timeout=4, headers={'User-Agent': 'IntegraleAcademy-BTS/2027'})
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=110)
def department_communes(department, time_bucket):
    return _get('https://geo.api.gouv.fr/communes', {'codeDepartement': department, 'fields': 'nom,codesPostaux,code', 'boost': 'population'})


@lru_cache(maxsize=512)
def search_places(kind, query, country, time_bucket):
    if kind == 'country':
        names = json.loads((Path(__file__).parent / 'static/admissions/countries-fr.json').read_text())
        return [dict(label=name, value=name) for name in names if normalized(query) in normalized(name)][:10]
    if kind == 'city' and country and normalized(country) not in ('france', 'fr'):
        data = _get('https://photon.komoot.io/api/', {'q': f'{query} {country}', 'lang': 'fr', 'limit': 6, 'osm_tag': ['place:city', 'place:town', 'place:village']})
        items = []
        for feature in data.get('features', []):
            prop = feature.get('properties', {})
            name = prop.get('name') or prop.get('city')
            if name:
                items.append(dict(label=f"{name} · {prop.get('country', country)}", value=name, city=name, postcode=prop.get('postcode', ''), country=prop.get('country', country)))
        return items
    if kind == 'city' or (kind == 'postcode' and re.fullmatch(r'\d{5}', query)):
        params = {'fields': 'nom,codesPostaux,code', 'limit': 8, 'boost': 'population'}
        params['nom' if kind == 'city' else 'codePostal'] = query
        data = _get('https://geo.api.gouv.fr/communes', params)
        items = []
        for row in data:
            for postcode in row.get('codesPostaux', [])[:8]:
                if kind == 'postcode' and postcode != query: continue
                items.append(dict(label=f"{row['nom']} · {postcode}", value=row['nom'] if kind == 'city' else postcode, city=row['nom'], postcode=postcode, country='France'))
        return items[:12]
    if kind == 'postcode':
        if not re.fullmatch(r'\d{2,4}', query): return []
        if query.startswith(('97', '98')) and len(query) < 3: return []
        departments = ['2A', '2B'] if query.startswith('20') else [query[:3] if query.startswith(('97', '98')) else query[:2]]
        items = []
        for department in departments:
            for row in department_communes(department, time_bucket):
                for postcode in row.get('codesPostaux', []):
                    if postcode.startswith(query):
                        items.append(dict(label=f"{postcode} · {row['nom']}", value=postcode, city=row['nom'], postcode=postcode, country='France'))
        return items[:12]
    data = _get('https://data.geopf.fr/geocodage/search', {'q': query, 'index': 'address', 'limit': 6, 'autocomplete': 1})
    return [dict(label=p.get('label', ''), value=p.get('name', ''), city=p.get('city', ''), postcode=p.get('postcode', ''), country='France') for f in data.get('features', []) if (p := f.get('properties', {})) and p.get('type') in ('housenumber', 'street', 'locality')]


def register_place_search(app):
    @app.get('/api/admission/suggestions')
    def admission_suggestions():
        kind = request.args.get('kind', '')
        query = request.args.get('q', '').strip()
        country = request.args.get('country', '').strip()[:80]
        if kind not in ('country', 'city', 'postcode', 'address') or len(query) > 140:
            return jsonify(items=[], error='Recherche invalide.'), 400
        if len(query) < (3 if kind == 'address' else 2): return jsonify(items=[])
        try:
            items = search_places(kind, query, country, int(time.time() / 300))
            return jsonify(items=items)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return jsonify(items=[], unavailable=True, message='Les suggestions sont momentanément indisponibles. Vous pouvez saisir votre réponse librement.')
