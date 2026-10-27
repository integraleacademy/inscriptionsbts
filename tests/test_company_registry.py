"""Exact registry matching, error handling and durable, explicit admin imports."""
import json
from unittest.mock import Mock

import pytest
import requests

import company_portal as portal
import company_registry as registry
from test_company_portal import env, admin, logged, post

SIRET = '12345678900022'
HEADQUARTERS = '12345678900014'


@pytest.fixture
def payload():
    return {'results': [{
        'siren': '123456789', 'nom_complet': 'NOVA SERVICES', 'nom_raison_sociale': 'NOVA SERVICES SAS',
        'sigle': 'NS', 'statut_diffusion': 'O', 'nature_juridique': '5710', 'activite_principale': '62.01Z',
        'etat_administratif': 'A', 'date_creation': '2016-04-01', 'date_mise_a_jour': '2026-10-24',
        'tranche_effectif_salarie': '12', 'annee_tranche_effectif_salarie': '2024',
        'siege': {'siret': HEADQUARTERS, 'adresse': '10 RUE DU SIEGE 75001 PARIS',
                  'statut_diffusion_etablissement': 'O', 'est_siege': True, 'etat_administratif': 'A'},
        'matching_etablissements': [{
            'siret': SIRET, 'adresse': '20 RUE DES APPRENTIS 83480 PUGET-SUR-ARGENS',
            'code_postal': '83480', 'libelle_commune': 'PUGET-SUR-ARGENS', 'nom_commercial': 'Nova Côte d’Azur',
            'est_siege': False, 'statut_diffusion_etablissement': 'O', 'etat_administratif': 'A',
            'activite_principale': '85.59A', 'date_creation': '2020-08-01', 'tranche_effectif_salarie': '02',
            'annee_tranche_effectif_salarie': '2024', 'liste_idcc': ['1486'], 'caractere_employeur': 'O',
        }],
        'dirigeants': [{'nom': 'MARTIN', 'prenoms': 'Camille', 'qualite': 'Présidente',
                       'date_de_naissance': '1970-01', 'nationalite': 'Française'}],
        'tva': ['FR00123456789'], 'complements': {'est_organisme_formation': True, 'est_qualiopi': True},
        'email': 'do-not-use@example.test', 'phone': 'do-not-use',
    }]}


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.headers = {}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_content(self, size):
        yield self.body


def stub_http(monkeypatch, payload, status=200):
    mock = Mock(return_value=Response(json.dumps(payload).encode(), status))
    monkeypatch.setattr(registry.requests, 'get', mock)
    return mock


def test_lookup_selects_requested_branch_not_headquarters_and_excludes_contact_birth_data(payload, monkeypatch):
    http = stub_http(monkeypatch, payload)
    result = registry.lookup_company('123 456 789 00022')
    assert result['fields']['siret'] == SIRET
    assert result['fields']['address'].startswith('20 RUE DES APPRENTIS')
    assert result['fields']['activity_code'] == '85.59A'
    assert result['fields']['activity_label'] == 'Formation continue d’adultes'
    assert 'simplifiée' in result['fields']['legal_form']
    serialized = json.dumps(result, ensure_ascii=False)
    assert 'Camille MARTIN' in serialized and '3 à 5 salariés (2024)' in serialized
    assert '1970' not in serialized and 'Française' not in serialized and 'do-not-use' not in serialized
    assert not {'email', 'phone', 'contact'} & result['fields'].keys()
    args, options = http.call_args
    assert args == (registry.SEARCH_URL,) and options['params'] == {'q': SIRET, 'per_page': 1}
    assert options['timeout'] == (8, 12) and options['allow_redirects'] is False


def test_exact_headquarters_lookup_and_partial_optional_values(payload):
    company = payload['results'][0]
    company.update(dirigeants=None, complements=None, tva=None)
    company['siege'].update(activite_principale=None, date_creation=None, liste_enseignes=None)
    result = registry.project_company(payload, HEADQUARTERS)
    assert result['fields']['address'].startswith('10 RUE DU SIEGE')
    assert result['fields']['activity_label'] == ''
    assert {'label': 'Type d’établissement', 'value': 'Siège social'} in result['details']


@pytest.mark.parametrize('mutation', ['other_branch', 'other_siren', 'empty', 'private_company', 'private_branch'])
def test_no_fuzzy_or_non_public_match_is_imported(payload, mutation):
    if mutation == 'empty': payload['results'] = []
    elif mutation == 'other_siren': payload['results'][0]['siren'] = '999999999'
    elif mutation == 'other_branch': payload['results'][0]['matching_etablissements'][0]['siret'] = '12345678900999'
    elif mutation == 'private_company': payload['results'][0]['statut_diffusion'] = 'P'
    else: payload['results'][0]['matching_etablissements'][0]['statut_diffusion_etablissement'] = 'P'
    with pytest.raises(registry.RegistryError) as error:
        registry.project_company(payload, SIRET)
    assert error.value.status == 404


def test_closed_establishment_remains_exact_and_shows_warning(payload):
    payload['results'][0]['matching_etablissements'][0]['etat_administratif'] = 'F'
    result = registry.project_company(payload, SIRET)
    assert result['fields']['siret'] == SIRET and 'fermé' in result['warnings'][0]


@pytest.mark.parametrize('value', ['', '123456789', 'x12345678900022', '1234567890002A', '１２３４５６７８９０００２２'])
def test_bad_input_never_reaches_provider(monkeypatch, value):
    http = Mock()
    monkeypatch.setattr(registry.requests, 'get', http)
    with pytest.raises(registry.RegistryError) as error: registry.lookup_company(value)
    assert error.value.status == 400
    http.assert_not_called()


@pytest.mark.parametrize('status', [301, 403, 429, 500, 503])
def test_http_failures_have_actionable_messages(monkeypatch, payload, status):
    stub_http(monkeypatch, payload, status)
    with pytest.raises(registry.RegistryError) as error: registry.lookup_company(SIRET)
    assert error.value.status == (429 if status == 429 else 503)


@pytest.mark.parametrize('body', [b'not json', b'{}', b'null', b'x' * 512_001])
def test_malformed_and_large_payloads_are_rejected(monkeypatch, body):
    monkeypatch.setattr(registry.requests, 'get', Mock(return_value=Response(body)))
    with pytest.raises(registry.RegistryError) as error: registry.lookup_company(SIRET)
    assert error.value.status == 503


def test_timeout_is_recoverable(monkeypatch):
    monkeypatch.setattr(registry.requests, 'get', Mock(side_effect=requests.Timeout))
    with pytest.raises(registry.RegistryError, match='conservées'): registry.lookup_company(SIRET)


def test_registry_endpoint_is_admin_only_and_does_not_create_or_email(env, payload, monkeypatch):
    lookup = Mock(return_value=registry.project_company(payload, SIRET))
    monkeypatch.setattr(portal, 'lookup_company', lookup)
    path = '/admin/entreprises/recherche-siret?siret='+SIRET
    assert env[0].test_client().get(path).status_code == 403
    assert logged(env).get(path).status_code == 403
    lookup.assert_not_called()
    response = admin(env).get(path)
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    assert response.json['token']
    assert not env[2]
    with env[1]() as conn: assert conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 2


def test_registry_endpoint_validation_and_provider_error(env, monkeypatch):
    lookup = Mock(side_effect=registry.RegistryError('Indisponible', 429))
    monkeypatch.setattr(portal, 'lookup_company', lookup)
    client = admin(env)
    assert client.get('/admin/entreprises/recherche-siret?siret='+SIRET+'&siret='+SIRET).status_code == 400
    assert client.get('/admin/entreprises/recherche-siret?siret=123').status_code == 400
    lookup.assert_not_called()
    response = client.get('/admin/entreprises/recherche-siret?siret='+SIRET)
    assert response.status_code == 429 and response.json['error'] == 'Indisponible'


def imported_form(env, payload):
    data = registry.project_company(payload, SIRET)
    return dict(data['fields'], registry_token=registry.preview_token(env[0].secret_key, data),
                contact='Contact choisi', email='selected@example.test', phone='0102030405')


def test_import_is_persisted_after_explicit_save_and_can_be_edited(env, payload):
    client = admin(env)
    fields = imported_form(env, payload)
    response = post(client, '/admin/entreprises', **fields)
    assert response.status_code == 303
    location = response.headers['Location']
    page = client.get(location)
    assert 'NOVA SERVICES SAS' in page.text and 'Camille MARTIN' in page.text
    assert '1970' not in page.text and 'data-registry-saved' in page.text
    with env[1]() as conn:
        row = dict(conn.execute('SELECT * FROM companies WHERE email=?', (fields['email'],)).fetchone())
    assert row['contact'] == 'Contact choisi' and row['phone'] == '0102030405'
    assert row['postal_code'] == '83480' and row['registry_data'] and row['password_hash'] is None
    edited = dict(name='Nom personnalisé',contact='Autre contact',email=fields['email'],siret=SIRET,version='1')
    assert post(client, location, **edited).status_code == 303
    with env[1]() as conn:
        current = dict(conn.execute('SELECT * FROM companies WHERE id=?', (row['id'],)).fetchone())
    assert current['registry_data'] == row['registry_data'] and current['address'] == row['address']
    assert not env[2]


def test_failed_validation_preserves_input_and_import_token(env, payload):
    fields = imported_form(env, payload)
    fields['contact'] = ''
    response = post(admin(env), '/admin/entreprises', **fields)
    assert response.status_code == 400
    assert fields['registry_token'] in response.text and fields['address'] in response.text
    fields['contact'] = 'Contact complété'
    assert post(admin(env), '/admin/entreprises', **fields).status_code == 303


@pytest.mark.parametrize('tamper', ['signature', 'different_siret', 'expired'])
def test_untrusted_preview_cannot_be_saved(env, payload, monkeypatch, tamper):
    fields = imported_form(env, payload)
    if tamper == 'signature': fields['registry_token'] = fields['registry_token'][:-10]+'corruption'
    elif tamper == 'different_siret': fields['siret'] = HEADQUARTERS
    else:
        import itsdangerous.timed
        original = itsdangerous.timed.TimestampSigner.get_timestamp
        monkeypatch.setattr(itsdangerous.timed.TimestampSigner, 'get_timestamp', lambda self: original(self)+7201)
    response = post(admin(env), '/admin/entreprises', **fields)
    assert response.status_code == 400
    with env[1]() as conn: assert conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 2


def test_edit_import_preserves_password_grants_and_invalidates_old_snapshot_on_new_siret(env, payload):
    client = admin(env)
    with env[1]() as conn:
        previous = dict(conn.execute("SELECT * FROM companies WHERE id='e1'").fetchone())
    fields = imported_form(env, payload)
    fields.update(version='1',email=previous['email'])
    assert post(client, '/admin/entreprises/e1', **fields).status_code == 303
    with env[1]() as conn:
        current = dict(conn.execute("SELECT * FROM companies WHERE id='e1'").fetchone())
        assert current['password_hash'] == previous['password_hash']
        assert current['registry_data']
        assert conn.execute("SELECT COUNT(*) FROM company_students WHERE company_id='e1'").fetchone()[0] == 1
    fields.update(version='2',siret=HEADQUARTERS,registry_token='')
    assert post(client, '/admin/entreprises/e1', **fields).status_code == 303
    with env[1]() as conn:
        assert conn.execute("SELECT registry_data FROM companies WHERE id='e1'").fetchone()[0] == ''


def test_additive_migration_preserves_existing_data_and_is_idempotent(env):
    with env[1]() as conn:
        # Simulate the pre-registry schema using SQLite's supported DROP COLUMN.
        for name in [f[0] for f in registry.EDITABLE_FIELDS] + ['registry_data']:
            conn.execute(f'ALTER TABLE companies DROP COLUMN {name}')
        before = [tuple(row) for row in conn.execute('SELECT id,email,password_hash,version FROM companies')]
        portal.ensure_company_schema(conn)
        portal.ensure_company_schema(conn)
        assert before == [tuple(row) for row in conn.execute('SELECT id,email,password_hash,version FROM companies')]
        assert conn.execute('SELECT COUNT(*) FROM company_students').fetchone()[0] == 2


def test_company_auth_uses_shared_daily_design_and_illustration(env):
    for path in ['/entreprise/connexion', '/entreprise/mot-de-passe-oublie', '/entreprise/mot-de-passe']:
        response = env[0].test_client().get(path)
        assert response.status_code == 200
        for marker in ['daily-login-page', 'daily-role-company', 'trainer-login-shell', 'trainer-login-visual', 'css/daily-login.css', 'company-space-illustration.webp']:
            assert marker in response.text
        assert 'co-auth-story' not in response.text and 'css/company-space.css' not in response.text
