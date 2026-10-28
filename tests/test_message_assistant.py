"""Draft generation and shared composers: all providers and mail transports are fake."""
import json

import pytest
from bs4 import BeautifulSoup

from test_campus_workspace import campus, client, application
from planning import PlanningError
from school_email import SENDERS
import subject_references


@pytest.fixture
def ai(campus, monkeypatch):
    c, headers, deliveries = campus
    c.get('/admin/candidat/onsite')
    with c.session_transaction() as state:
        individual_headers = {'X-CSRF-Token': state['_candidate_message_csrf']}
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-secret')
    calls = []

    def provider(key, **kwargs):
        calls.append(kwargs['payload'])
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text',
            'text': json.dumps({'subject': 'Rappel de ponctualité', 'body': 'Bonjour Camille,\n\nMerci de veiller à être à l’heure en cours.\n\nBien cordialement,'})}]}]}
    monkeypatch.setattr(subject_references, 'provider', provider)
    return c, headers, individual_headers, deliveries, calls


def payload(**extra):
    return dict(instruction='Rappeler d’être à l’heure en cours.', groups=['students'], **extra)


def test_individual_draft_uses_only_minimal_server_context_and_never_sends(ai):
    c, _, headers, deliveries, calls = ai
    response = c.post('/admin/candidat/onsite/message-assistant', headers=headers,
                      json=payload(etudiant={'prenom': 'Forged'}, sender_id='aurelie'))
    assert response.status_code == 200 and response.json['subject'] == 'Rappel de ponctualité'
    assert response.headers['Cache-Control'] == 'no-store'
    assert len(calls) == 1 and not deliveries
    context = json.loads(calls[0]['input'])
    assert context['contexte'] == {'type': 'individuel', 'etudiant': {'prenom': 'Camille', 'bts': 'MCO', 'mode': 'presentiel'}}
    assert context['expediteur']['nom'] == SENDERS['aurelie']['name']
    assert 'example.test' not in calls[0]['input'] and '2000-01-01' not in calls[0]['input']
    assert calls[0]['store'] is False and 'tools' not in calls[0]
    assert calls[0]['text']['format']['strict'] is True
    with application.db() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_message_previews'").fetchone()


def test_group_draft_has_no_contact_directory_or_delivery_record(ai):
    c, headers, _, deliveries, calls = ai
    data = payload(); data['groups'] = ['students', 'trainers', 'companies']
    response = c.post('/admin/messagerie/assistant', headers=headers, json=data)
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    context = json.loads(calls[0]['input'])['contexte']
    assert context['type'] == 'groupe' and context['nombre'] == 3
    assert 'example.test' not in calls[0]['input'] and 'Camille' not in calls[0]['input']
    assert not deliveries


@pytest.mark.parametrize('individual', [True, False])
def test_ai_requires_admin_and_matching_csrf(ai, individual):
    c, group_headers, individual_headers, deliveries, calls = ai
    path = '/admin/candidat/onsite/message-assistant' if individual else '/admin/messagerie/assistant'
    headers = individual_headers if individual else group_headers
    assert c.post(path, json=payload()).status_code == 400
    assert c.post(path, json=payload(), headers={'X-CSRF-Token': 'bad'}).status_code == 400
    with c.session_transaction() as state: state['admin_ok'] = False
    assert c.post(path, json=payload(), headers=headers).status_code == 403
    assert not calls and not deliveries


@pytest.mark.parametrize('changes', [dict(instruction=''), dict(instruction='x'*4001), dict(instruction=[]),
    dict(sender_id='forged'), dict(body='x'*20001), dict(channel='sms')])
def test_invalid_draft_requests_do_not_call_provider(ai, changes):
    c, headers, _, _, calls = ai
    data = payload(); data.update(changes)
    assert c.post('/admin/messagerie/assistant', headers=headers, json=data).status_code == 400
    assert not calls


def test_missing_candidate_or_audience_does_not_call_provider(ai):
    c, headers, individual_headers, _, calls = ai
    assert c.post('/admin/candidat/missing/message-assistant', headers=individual_headers, json=payload()).status_code == 404
    data = payload(); data['groups'] = []
    assert c.post('/admin/messagerie/assistant', headers=headers, json=data).status_code == 400
    assert not calls


def test_missing_key_and_provider_failure_are_actionable(ai, monkeypatch):
    c, _, headers, deliveries, calls = ai
    monkeypatch.delenv('OPENAI_API_KEY')
    response = c.post('/admin/candidat/onsite/message-assistant', headers=headers, json=payload())
    assert response.status_code == 503 and 'Paramètres' in response.json['error']
    assert not calls
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret')
    def unavailable(*args, **kwargs): raise PlanningError('OpenAI ne répond pas pour le moment.', status=502)
    monkeypatch.setattr(subject_references, 'provider', unavailable)
    response = c.post('/admin/candidat/onsite/message-assistant', headers=headers, json=payload())
    assert response.status_code == 502 and 'OpenAI' in response.json['error']
    assert not deliveries


@pytest.mark.parametrize('result', [
    {'status': 'incomplete'}, {'status': 'completed', 'output': []},
    {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'not json'}]}]},
    {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"subject":"bad\\nheader","body":"Hello"}'}]}]},
    {'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
])
def test_invalid_or_refused_output_never_becomes_a_draft(ai, monkeypatch, result):
    c, _, headers, deliveries, _ = ai
    monkeypatch.setattr(subject_references, 'provider', lambda *args, **kwargs: result)
    response = c.post('/admin/candidat/onsite/message-assistant', headers=headers, json=payload())
    assert response.status_code == 502 and response.json['ok'] is False
    assert not deliveries


def test_rate_limit_shared_between_composers(ai):
    c, group_headers, individual_headers, deliveries, calls = ai
    for i in range(10):
        path, headers = ('/admin/messagerie/assistant', group_headers) if i % 2 else ('/admin/candidat/onsite/message-assistant', individual_headers)
        assert c.post(path, headers=headers, json=payload()).status_code == 200
    assert c.post('/admin/messagerie/assistant', headers=group_headers, json=payload()).status_code == 429
    assert len(calls) == 10 and not deliveries


@pytest.mark.parametrize('layout', ['crm', 'letter'])
@pytest.mark.parametrize('sender', ['clement', 'aurelie'])
def test_same_email_in_both_composers_and_preview_bound_delivery(ai, layout, sender):
    c, group_headers, individual_headers, deliveries, _ = ai
    data = dict(type='email', channel='email', groups=['students'], subject='À bientôt', body='Bonjour,\n\nTexte <script>test</script>',
                layout=layout, sender_id=sender, accent_title='Notre prochaine rencontre.', action_url='https://example.test/cours', action_label='Consulter')
    personal = c.post('/admin/candidat/onsite/message-preview', json=data, headers=individual_headers).json
    group = c.post('/admin/messagerie/apercu', json=data, headers=group_headers).json
    assert personal['html'] == group['html'] and personal['sender'] == group['sender']
    assert '<script>test' not in personal['html']
    for field, changed in [('layout', 'letter' if layout == 'crm' else 'crm'), ('sender_id', 'aurelie' if sender == 'clement' else 'clement'),
                           ('accent_title', 'Autre phrase'), ('action_url', 'https://example.test/autre'), ('action_label', 'Autre bouton')]:
        assert c.post('/admin/candidat/onsite/message', json={**data, field: changed, 'preview_token': personal['preview_token']}, headers=individual_headers).status_code == 400
    assert not deliveries
    assert c.post('/admin/candidat/onsite/message', json={**data, 'preview_token': personal['preview_token']}, headers=individual_headers).status_code == 200
    assert deliveries[0][1][2] == personal['html']
    assert deliveries[0][2]['sender_email'] == SENDERS[sender]['email']
    assert deliveries[0][2]['reply_to'] == SENDERS[sender]['email']


def test_both_pages_offer_shared_choices_and_assistant(ai):
    c, _, _, _, _ = ai
    for path in ['/admin/candidat/onsite', '/admin/messagerie']:
        page = BeautifulSoup(c.get(path).text, 'html.parser')
        assert [x['value'] for x in page.select('[name=sender_id]')] == ['clement', 'aurelie']
        assert [x['value'] for x in page.select('[name=layout]')] == ['crm', 'letter']
        assert len(page.select('[data-email-assistant]')) == 1
        assert len(page.select('script[src*="js/message-assistant.js"]')) == 1
