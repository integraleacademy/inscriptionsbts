"""Reference previews: permissions, provenance, atomic imports and API isolation."""
import copy
import json
import time
from unittest.mock import patch

import pytest

import subject_references as refs
from planning import PlanningError
from test_planning import db, app, client, call, admin, BASE

URL = refs.MOS_URL
KEY = 'sk-test-only-' + 'x' * 32


def provider_result():
    data = {'qualification': 'BTS MOS', 'reference_title': 'Arrêté du 2 mars 2020',
        'reference_version': 'Exemple de test uniquement', 'warnings': ['Vérifier la session.'],
        'subjects': [dict(name='Culture générale et expression', exam_unit='U1', coefficient=3, optional=False,
            weekly_hours_first=2, weekly_hours_second=2, objectives='Lire et argumenter.\nCommuniquer.',
            pedagogical_content='Analyse et expression.', exam_format='Écrit', source_url=URL,
            source_label='Annexe II c', evidence='U1 – coefficient 3', review_note='')]
    }
    return {'id': 'resp_test', 'status': 'completed', 'output': [
        {'type': 'web_search_call', 'action': {'sources': [{'url': URL}]}},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(data)}]}]}


def ready_job(client, app, monkeypatch, db, response=None, pid='p1'):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    with patch.object(refs, 'provider', return_value={'id': 'resp_test', 'status': 'queued'}):
        start = call(client, '/references/analyze', {'promotion_id': pid, 'qualification': 'BTS MOS', 'exam_year': 2028, 'source_url': URL})
    assert start.status_code == 202, start.json
    jid = start.json['job_id']
    with patch.object(refs, 'provider', return_value=response or provider_result()):
        result = client.get(BASE + '/references/' + jid)
    assert result.status_code == 200, result.json
    return jid, result.json


def test_permissions_and_csrf(app, client):
    anon = app.test_client()
    for endpoint in ('/settings', '/latest', '/unknown'):
        assert anon.get(BASE+'/references'+endpoint).status_code == 403
    for endpoint in ('/settings', '/analyze', '/unknown/import'):
        method = 'PUT' if endpoint == '/settings' else 'POST'
        assert anon.open(BASE+'/references'+endpoint, method=method, json={}).status_code == 403
        assert client.open(BASE+'/references'+endpoint, method=method, json={}).status_code == 400


def test_key_encryption_and_no_echo(client, app, db, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    saved = call(client, '/references/settings', {'api_key': KEY}, 'PUT')
    assert saved.status_code == 200
    assert saved.json['configured'] and KEY not in saved.text
    assert KEY not in client.get(BASE+'/references/settings').text
    with db() as conn:
        value = conn.execute('SELECT value FROM planning_reference_settings').fetchone()[0]
        assert KEY not in value and refs.api_key(app, conn) == KEY
    assert call(client, '/references/settings', method='DELETE').json['configured'] is False


def test_server_key_cannot_be_overridden(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    assert client.get(BASE+'/references/settings').json['managed_by_server']
    assert call(client, '/references/settings', {'api_key': KEY}, 'PUT').status_code == 409
    assert call(client, '/references/settings', method='DELETE').json['configured']


def test_missing_key_is_actionable_no_job(client, db, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    response = call(client, '/references/analyze', dict(promotion_id='p1', exam_year=2028))
    assert response.status_code == 503 and 'Paramètres' in response.json['message']
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_reference_jobs').fetchone()[0] == 0


@pytest.mark.parametrize('url', ['http://www.legifrance.gouv.fr/test', 'https://localhost/', 'https://127.0.0.1/',
    'https://legifrance.gouv.fr.attacker.test/', 'https://legifrance.gouv.fr@attacker.test/',
    'https://www.legifrance.gouv.fr:8080/', 'javascript:alert(1)', 'https://www.legifrance.gouv.fr/\nfoo'])
def test_unofficial_or_unsafe_urls_rejected(url):
    with pytest.raises(PlanningError): refs.official_url(url)


@pytest.mark.parametrize('url', [URL, 'https://eduscol.education.gouv.fr/document/1/download', 'https://pedagogie.ac-montpellier.fr/referentiel'])
def test_official_url_allowed(url):
    assert refs.official_url(url) == url


def test_no_sources_no_importable_preview():
    response = provider_result(); response['output'] = response['output'][1:]
    with pytest.raises(PlanningError, match='document officiel'): refs.extract_preview(response)


def test_invented_source_is_not_importable():
    response = provider_result()
    data = json.loads(response['output'][1]['content'][0]['text'])
    data['subjects'][0]['source_url'] = 'https://www.education.gouv.fr/invented'
    response['output'][1]['content'][0]['text'] = json.dumps(data)
    preview = refs.extract_preview(response)
    assert preview['subjects'][0]['importable'] is False
    assert preview['subjects'][0]['source_issue']


def test_background_retrieval_requests_full_sources(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    calls = []
    def request(method, url, **kwargs):
        calls.append(method)
        if method == 'POST':
            data = {'id': 'resp_test', 'status': 'queued'}
        else:
            assert url == refs.API_URL + '/resp_test'
            assert kwargs['params'] == {'include[]': 'web_search_call.action.sources'}
            data = provider_result()
        return type('Response', (), {'status_code': 200, 'json': lambda self: data})()
    with patch.object(refs.requests, 'request', side_effect=request):
        job = call(client, '/references/analyze', dict(promotion_id='p1', exam_year=2028, source_url=URL)).json
        preview = client.get(BASE+'/references/'+job['job_id']).json
    assert preview['status'] == 'ready'
    assert preview['preview']['subjects'][0]['importable'] is True
    assert calls == ['POST', 'GET']


@pytest.mark.parametrize('cited', [
    URL + '/#annexe',
    URL.replace('www.', '') + '?utm_source=chatgpt.com',
    URL.replace('.fr/', '.fr:443/'),
])
def test_same_source_url_variants_are_recognised(cited):
    response = provider_result()
    data = json.loads(response['output'][1]['content'][0]['text'])
    data['subjects'][0]['source_url'] = cited
    response['output'][1]['content'][0]['text'] = json.dumps(data)
    item = refs.extract_preview(response)['subjects'][0]
    assert item['importable'] is True and item['source_url'] == URL


def test_document_versions_are_not_conflated():
    assert refs.canonical_url(URL+'?dateVersion=2020-01-01') != refs.canonical_url(URL+'?dateVersion=2026-01-01')
    assert refs.canonical_url(URL+'?b=2&a=1') == refs.canonical_url(URL+'?a=1&b=2&utm_source=test')


def test_one_unconfirmed_row_does_not_block_confirmed_rows(client, app, db, monkeypatch):
    response = provider_result()
    data = json.loads(response['output'][1]['content'][0]['text'])
    data['subjects'].append({**data['subjects'][0], 'name': 'Non sourcée', 'source_url': 'https://www.education.gouv.fr/invented'})
    response['output'][1]['content'][0]['text'] = json.dumps(data)
    jid, job = ready_job(client, app, monkeypatch, db, response)
    assert job['status'] == 'ready'
    assert [r['importable'] for r in job['preview']['subjects']] == [True, False]
    assert call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1'), dict(row_id='2', importable=True, source_url=URL)])).status_code == 422
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_subjects').fetchone()[0] == 4
    result = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1')]))
    assert result.status_code == 200 and result.json['count'] == 1


def test_previous_source_failure_recovers_without_new_analysis(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db)
    with db() as conn:
        conn.execute("UPDATE planning_reference_jobs SET status='failed',preview=NULL,error=?,created_at=? WHERE id=?", (refs.LEGACY_SOURCE_ERRORS[0], time.time()-1800, jid))
    assert client.get(BASE+'/references/latest').json['job']['recoverable']
    assert client.post(BASE+'/references/'+jid+'/recover', json={}).status_code == 400
    with patch.object(refs, 'provider', return_value=provider_result()) as provider:
        recovered = call(client, '/references/'+jid+'/recover')
    assert recovered.json['status'] == 'ready' and not recovered.json['recoverable']
    provider.assert_called_once_with(KEY, 'GET', 'resp_test')
    with patch.object(refs, 'provider') as provider:
        assert call(client, '/references/'+jid+'/recover').json['status'] == 'ready'
        provider.assert_not_called()


def test_coefficient_requires_evidence():
    response = provider_result(); data = json.loads(response['output'][1]['content'][0]['text'])
    data['subjects'][0]['evidence'] = ''
    response['output'][1]['content'][0]['text'] = json.dumps(data)
    assert refs.extract_preview(response)['subjects'][0]['coefficient'] is None


def test_preview_does_not_write_subjects_and_sends_no_private_data(client, app, db, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    with patch.object(refs, 'provider', return_value={'id':'resp_test'}) as mock:
        response = call(client, '/references/analyze', dict(promotion_id='p1', exam_year=2028, source_url=URL))
    data = mock.call_args.kwargs['payload']
    assert data['background'] and data['tools'][0]['type'] == 'web_search'
    assert data['include'] == ['web_search_call.action.sources']
    for private in ['t1@example.test', 'Prénom', 'p1', 'secret']:
        assert private not in data['input']
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_subjects').fetchone()[0] == 4
    assert response.status_code == 202


def test_pending_analysis_reused(client, app, db, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    with patch.object(refs, 'provider', return_value={'id':'resp_test'}) as mock:
        a = call(client, '/references/analyze', dict(promotion_id='p1', exam_year=2028))
        b = call(client, '/references/analyze', dict(promotion_id='p1', exam_year=2028))
    assert a.json['job_id'] == b.json['job_id'] and mock.call_count == 1


def test_selected_edited_import_without_teacher_or_hours(client, app, db, monkeypatch):
    jid, preview = ready_job(client, app, monkeypatch, db)
    assert preview['status'] == 'ready'
    result = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1', name='Expression et culture', coefficient=4, objectives='Adapté par le responsable.')]))
    assert result.status_code == 200, result.json
    sid = result.json['subject_ids'][0]
    item = next(s for s in client.get(BASE+'/catalog').json['subjects'] if s['id'] == sid)
    assert item['trainer_id'] == '' and item['planned_hours'] is None and not item['budget_configured']
    assert item['name'] == 'Expression et culture' and item['coefficient'] == 4
    assert item['objectives'] == 'Adapté par le responsable.' and item['source_url'] == URL
    assert item['original']['coefficient'] == 3
    again = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1')]))
    assert again.json['subject_ids'] == [sid]
    # Metadata remains editable even while assignments are incomplete.
    update = call(client, '/subjects/'+sid, dict(objectives='Objectif corrigé', coefficient=2), 'PUT')
    assert update.status_code == 200, update.json
    assert update.json['subject']['objectives'] == 'Objectif corrigé'
    assert update.json['subject']['coefficient'] == 2


def test_preview_bound_to_admin_session(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db)
    other = admin(app, 'another-session')
    assert other.get(BASE+'/references/'+jid).status_code == 404
    assert call(other, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1')])).status_code == 404


def test_atomic_reject_of_duplicate_and_invalid_selection(client, app, db, monkeypatch):
    response = provider_result(); data = json.loads(response['output'][1]['content'][0]['text'])
    data['subjects'].append({**data['subjects'][0], 'name':'Autre enseignement'})
    response['output'][1]['content'][0]['text'] = json.dumps(data)
    jid, _ = ready_job(client, app, monkeypatch, db, response)
    bad = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1'), dict(row_id='2', name='  MATIERE s1 ')]))
    assert bad.status_code == 409, bad.json
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_subjects').fetchone()[0] == 4
        assert conn.execute('SELECT count(*) FROM planning_subject_details').fetchone()[0] == 0
    for selected in ([], [dict(row_id='x')], [dict(row_id='1'),dict(row_id='1')]):
        assert call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=selected)).status_code == 400


def test_review_required_and_foreign_trainer_rejected(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db)
    assert call(client, '/references/'+jid+'/import', dict(subjects=[dict(row_id='1')])).status_code == 400
    assert call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1', trainer_id='unassigned')])).status_code == 400


def test_import_to_undated_promotion_and_assign_later(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db, pid='undated')
    result = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1', planned_hours=120, trainer_id='t1')]))
    assert result.status_code == 200
    sid = result.json['subject_ids'][0]
    assert call(client, '/subjects/'+sid, dict(coefficient=4), 'PUT').status_code == 200


def test_invalid_numbers_rejected_and_rollback(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db)
    for value in (float('nan'), float('inf'), True, -1, 101):
        res = call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1', coefficient=value)]))
        assert res.status_code == 400
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_subjects').fetchone()[0] == 4


def test_expired_job_cannot_import(client, app, db, monkeypatch):
    jid, _ = ready_job(client, app, monkeypatch, db)
    with db() as conn:
        conn.execute('UPDATE planning_reference_jobs SET created_at=? WHERE id=?', (time.time()-90000,jid))
    assert client.get(BASE+'/references/'+jid).status_code == 410
    assert call(client, '/references/'+jid+'/import', dict(reviewed=True, subjects=[dict(row_id='1')])).status_code == 410


def test_provider_errors_do_not_expose_credentials():
    fake = type('Response', (), {'status_code': 401})()
    with patch.object(refs.requests, 'request', return_value=fake) as request:
        with pytest.raises(PlanningError) as failure: refs.provider(KEY)
        assert KEY not in str(failure.value)
        assert request.call_args.kwargs['allow_redirects'] is False
    with pytest.raises(PlanningError): refs.provider(KEY, 'GET', '../../secrets')


def test_failed_provider_job_has_actionable_error(client, app, db, monkeypatch):
    jid, result = ready_job(client, app, monkeypatch, db, {'status':'incomplete','output':[]})
    assert result['status'] == 'failed' and 'relancez' in result['message']


def test_existing_manual_subject_can_save_metadata(client):
    result = call(client, '/subjects/s1', dict(coefficient=3, objectives='Objectif\nCompétence', exam_unit='U1'), 'PUT')
    assert result.status_code == 200, result.json
    assert result.json['subject']['coefficient'] == 3
    assert result.json['subject']['planned_hours'] == 30


def test_schema_reentrant_and_no_destructive_column_change(db):
    with db() as conn:
        refs.schema(conn); refs.schema(conn)
        assert len(conn.execute('PRAGMA table_info(planning_subjects)').fetchall()) == 6
        assert conn.execute('SELECT count(*) FROM planning_subjects').fetchone()[0] == 4
