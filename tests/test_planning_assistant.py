"""Room availability and assistant operations against the live planning routes on a temporary DB."""
import json

import pytest
import planning_assistant_language as language
import subject_references
from test_planning import BASE, add, admin, app, call, client, db, setup_school
from test_planning_rooms_events import event, linked, machine, reservation
from test_room_calendar import block, seed
from test_room_reservations import reserve

ROOMS = {'page': 'salles'}
PLAN = {'page': 'planning', 'promotion_id': 'p1', 'period_id': 'p1:1'}


@pytest.fixture
def ask(monkeypatch, client):
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-only')
    monkeypatch.setattr(language, 'today', lambda: '2026-11-10')

    def send(action, context=PLAN, **fields):
        intent = {k: None for k in language.schema()['properties']}
        intent.update(action=action, weekdays=[], close_source=False, all_courses=False, whole_period=False)
        intent.update(fields)

        def provider(key, payload, read_timeout=20):
            assert key == 'fixture-only' and not payload['store']
            assert payload['text']['format']['strict']
            data = json.loads(payload['input'])
            if payload['text']['format']['name'] == 'planning_reponse':
                return {'output': []}  # Exercise the verified fallback independently of writing quality.
            assert data['page']['page'] == context['page'] and data['demande']
            assert {'salles', 'promotions'} == set(data['catalogue'])
            return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(intent)}]}]}
        monkeypatch.setattr(subject_references, 'provider', provider)
        return call(client, '/assistant', dict(message='Demande de test', history=[], context=context))
    return send


def confirm(client, preview, context=PLAN):
    return call(client, '/assistant/confirmer', dict(preview_token=preview.json['preview_token'], context=context))


def month(client, **extra):
    params = {'from': '2027-01-01', 'to': '2027-01-31', **extra}
    return client.get(BASE + '/rooms/disponibilites', query_string=params)


def test_month_merges_multiple_sources_and_excludes_inactive(client, linked, db):
    setup_school(client)
    add(client, start='08:00', end='10:00')
    reserve(client, room_id='r1', start='10:00', end='12:15')
    seed(client, slots=[dict(room_id='r1', date='2027-01-04', start='13:00', end='15:00')])
    block(client, room_id='r1', start='16:00', end='18:30')
    with db() as conn:
        conn.execute("INSERT INTO planning_rooms VALUES('r3','Salle inactive',0)")
    data = month(client).json
    rooms = {r['id']: r for r in data['rooms']}
    assert '2027-01-02' not in data['dates']
    assert rooms['r1']['days']['2027-01-04'] == dict(state='partial', free=[['12:15','13:00'], ['15:00','16:00']])
    assert rooms['r2']['free_days'] == len(data['dates']) and rooms['r3']['free_days'] == 0
    narrow = {r['id']: r for r in month(client, start='10:00', end='12:00').json['rooms']}
    assert narrow['r1']['days']['2027-01-04']['state'] == 'busy' and narrow['r2']['days']['2027-01-04']['state'] == 'free'
    feb = month(client, **{'from':'2028-02-01', 'to':'2028-02-29', 'weekdays':'0,1,2,3,4,5,6'})
    assert feb.status_code == 200 and len(feb.json['dates']) == 29
    assert month(client, weekdays='7').status_code == 400
    assert month(client, start='19:00', end='09:00').status_code == 400
    assert month(client, **{'to':'9999-12-31'}).status_code == 400


def test_availability_question_cannot_reserve_and_checks_all_dates(ask, client, db):
    reserve(client, date='2027-02-11')
    res = ask('availability', ROOMS, from_date='2027-02-10', to_date='2027-03-15')
    assert res.status_code == 200 and res.json['preview_token'] is None
    assert 'Salle r1' in res.json['message'] and 'Salle r2' not in res.json['message']
    assert 'de 8 h à 18 h' in res.json['message'] and 'journées libres' in res.json['details'][1]
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_room_reservations').fetchone()[0] == 1


def test_room_question_accounts_for_the_promotions_own_and_shared_slots(client, ask):
    setup_school(client)
    add(client, shared=[dict(promotion_id='p2', subject_id='s2')])
    add(client, date='2027-01-05', room_id=None)
    reserve(client, room_id='r2', date='2027-01-05')
    question = ask('promotion_rooms', ROOMS, promotion_id='p1', period_id='p1:1')
    assert question.json['preview_token'] is None and question.json['message'].endswith('Salle r1.')
    change = ask('assign_room', room_id='r1')
    assert '1 cours' in change.json['message'] and confirm(client, change).status_code == 200


def test_replacement_moves_source_types_and_blocks_future_only(client, db, linked, ask):
    setup_school(client)
    add(client, date='2027-01-04')
    add(client, date='2027-01-06')
    seed(client, slots=[dict(room_id='r1',date='2027-01-07',start='08:00',end='12:00')])
    reserve(client, room_id='r1', date='2027-01-08', exam=True)
    proposal = ask('replace_room', ROOMS, source_room_id='r1', room_id='r2', close_source=True, from_date='2027-01-05')
    assert proposal.status_code == 200 and len(proposal.json['details']) == 3
    with db() as conn:
        assert not conn.execute('SELECT count(*) FROM planning_room_unavailability').fetchone()[0]
    assert confirm(client, proposal, ROOMS).status_code == 200
    assert confirm(client, proposal, ROOMS).status_code == 409
    slots = client.get(BASE+'/rooms/schedule?start=2027-01-04&end=2027-01-10').json['reservations']
    assert all(r['room_id'] == 'r2' for r in slots if r['date'] > '2027-01-04' and r['source'] != 'unavailable')
    assert next(r for r in slots if r['date'] == '2027-01-04')['room_id'] == 'r1'
    assert any(r['source'] == 'unavailable' and r['end_date'] == '9999-12-31' for r in slots)
    assert reserve(client, room_id='r1',date='2038-01-12').status_code == 409
    assert machine(client, 'prepare', reservation(owner='session:future', slots=[
        dict(room_id='r1',date='2038-01-12',start='08:00',end='12:00')])).status_code == 409


def test_new_replacement_conflict_aborts_even_closure(client, db, ask):
    reserve(client, room_id='r1')
    proposal = ask('replace_room', ROOMS, source_room_id='r1', room_id='r2', close_source=True, from_date='2027-01-01')
    assert proposal.json['preview_token']
    reserve(client, room_id='r2')
    assert confirm(client, proposal, ROOMS).status_code == 409
    blocked = ask('replace_room', ROOMS, source_room_id='r1', room_id='r2', close_source=True, from_date='2027-01-01')
    assert not blocked.json['preview_token'] and '04/01/2027' in blocked.json['details'][0]
    with db() as conn:
        assert not conn.execute('SELECT count(*) FROM planning_room_unavailability').fetchone()[0]
        assert conn.execute("SELECT count(*) FROM planning_room_reservations WHERE room_id='r1'").fetchone()[0] == 1


def test_open_ended_closure_editable_in_existing_calendar(client, ask):
    proposal = ask('replace_room', ROOMS, source_room_id='r1', close_source=True, from_date='2027-01-01')
    assert confirm(client, proposal, ROOMS).status_code == 200
    saved = client.get(BASE+'/rooms/schedule?start=2028-01-04&end=2028-01-04').json['reservations'][0]
    edited = call(client, '/rooms/unavailability/'+saved['id'], dict(room_id='r1', version=saved['version'],
                  start_date='2027-01-01', end_date='2027-03-10', reason='Travaux'), 'PUT')
    assert edited.status_code == 200
    assert reserve(client, room_id='r1', date='2028-01-04').status_code == 200


def prepare_cejm(client, db):
    setup_school(client)
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET name='Culture économique, juridique et managériale' WHERE id='s1'")
    return [add(client, date=d, start='16:00', end='18:00', zoom_url='https://zoom.us/j/12345678901') for d in ('2027-01-08','2027-01-15')]


def moving(ask):
    return ask('move_courses', subject='CEJM', weekdays=[4], start='16:00', end='18:00', new_weekday=3,
               new_start='13:00', new_end='15:00')


def test_recurring_move_preserves_originals_until_confirm_and_checks_versions(client, db, ask):
    source = prepare_cejm(client, db)
    proposal = moving(ask)
    assert len(proposal.json['details']) == 2 and '07/01/2027' in proposal.json['details'][0]
    with db() as conn:
        assert [r[0] for r in conn.execute('SELECT date FROM planning_courses ORDER BY date')] == [c['date'] for c in source]
    assert confirm(client, proposal).status_code == 200
    assert confirm(client, proposal).status_code == 409
    with db() as conn:
        saved = conn.execute('SELECT * FROM planning_courses ORDER BY date').fetchall()
        assert [r['date'] for r in saved] == ['2027-01-07','2027-01-14']
        for old, new in zip(source, saved):
            assert new['id'] == old['id'] and new['zoom_url'] == old['zoom_url'] and new['version'] == 2
            assert (new['start_min'], new['end_min']) == (780, 900)


def test_one_blocked_move_never_partially_applies(client, db, ask):
    prepare_cejm(client, db)
    proposal = moving(ask)
    reserve(client, date='2027-01-14', start='14:00', end='15:00', room_id='r1')
    assert confirm(client, proposal).status_code == 409
    blocked = moving(ask)
    assert not blocked.json['preview_token'] and '14/01/2027' in blocked.json['details'][0]
    with db() as conn:
        assert {r[0] for r in conn.execute('SELECT version FROM planning_courses')} == {1}


def test_bulk_move_checks_aggregate_subject_hours_and_trainer_availability(client, db, ask):
    prepare_cejm(client, db)
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=5 WHERE id='s1'")
    too_many = ask('move_courses', subject='CEJM', new_start='15:00')
    assert not too_many.json['preview_token'] and 'volume' in too_many.json['details'][0]
    assert call(client,'/admin/formateurs/t1/indisponibilites',dict(start_date='2027-01-07', end_date='2027-01-07', weekdays=[3], times=[], reason='Absent')).status_code == 200
    blocked = moving(ask)
    assert not blocked.json['preview_token'] and 'indisponible' in blocked.json['details'][0]


def test_trainer_single_day_deletion_and_ambiguous_name(client, db, ask):
    setup_school(client)
    with db() as conn:
        conn.execute("UPDATE trainers SET prenom='Yannice' WHERE id IN ('t1','t2')")
    a = add(client)
    b = add(client, sid='s3', date='2027-01-05')
    ambiguous = ask('remove_courses', trainer='Yannice', from_date='2027-01-04', to_date='2027-01-04')
    assert ambiguous.status_code == 400 and 'Plusieurs correspondances' in ambiguous.json['message']
    request = ask('remove_courses', trainer='Yannice NOM t1', from_date='2027-01-04', to_date='2027-01-04')
    assert confirm(client, request).status_code == 200
    with db() as conn:
        assert [r[0] for r in conn.execute('SELECT id FROM planning_courses')] == [b['id']] and a['id'] != b['id']


def test_period_deletion_detaches_shared_courses_and_preserves_events(client, ask, db):
    setup_school(client)
    shared = add(client, shared=[dict(promotion_id='p2', subject_id='s2')])
    add(client, date='2027-02-05')
    untouched = event(client, date='2027-02-08').json['course']
    selection = ask('remove_courses', all_courses=True, from_date='2027-01-01', to_date='2027-06-30')
    assert len(selection.json['details']) == 2 and 'partagés' in selection.json['message']
    assert confirm(client, selection).status_code == 200
    with db() as conn:
        assert set(map(tuple, conn.execute('SELECT id,promotion_id FROM planning_courses'))) == {(shared['id'],'p2'),(untouched['id'],'p1')}


def test_confirmation_invalid_after_changed_membership_or_new_course(client, ask, db):
    setup_school(client)
    add(client)
    preview = ask('remove_courses', all_courses=True, from_date='2027-01-01', to_date='2027-03-31')
    add(client, date='2027-02-01')
    assert confirm(client, preview).status_code == 409
    with db() as conn:
        assert conn.execute('SELECT count(*) FROM planning_courses').fetchone()[0] == 2


def test_assistant_permissions_binding_scope_and_invalid_outputs(client, ask, app, monkeypatch):
    outsider = app.test_client()
    assert month(outsider).status_code == 403 and call(outsider,'/assistant',{}).status_code == 403
    assert client.post(BASE+'/assistant', json={}).status_code == 400
    setup_school(client)
    add(client)
    preview = ask('remove_courses', all_courses=True, from_date='2027-01-01', to_date='2027-01-31')
    assert confirm(admin(app, 'different-session'), preview).status_code == 409
    assert confirm(client, preview, ROOMS).status_code == 409
    assert call(client, '/assistant/confirmer', dict(context=PLAN, preview_token='untrusted')).status_code == 409
    monkeypatch.setattr(subject_references, 'provider', lambda *a,**kw:{'output':[]})
    assert call(client, '/assistant', dict(context=PLAN, message='Janvier')).status_code == 502


def test_unsynchronized_ledger_cannot_suggest_a_free_room(client, ask, monkeypatch):
    monkeypatch.setenv('SHARED_ROOMS_TOKEN','test')
    monkeypatch.setenv('SESSION_ROOMS_URL','https://sessions.example.test')
    assert month(client).status_code == 503
    res = ask('availability', ROOMS, from_date='2027-01-01', to_date='2027-01-31')
    assert res.status_code == 503 and 'synchronisation' in res.json['message']


def test_screenshot_week_is_a_conversation_with_checked_facts(client, db, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-only')
    monkeypatch.delenv('OPENAI_PLANNING_MODEL', raising=False)
    with db() as conn:
        conn.execute("UPDATE planning_rooms SET name='Salle 2B' WHERE id='r1'")
        conn.execute("UPDATE planning_rooms SET name='Atelier Modulable Paris' WHERE id='r2'")
        conn.executemany('INSERT INTO planning_rooms VALUES(?,?,1)',
                         [('dummy','SALLE À DÉFINIR'), ('r3','Salle 1B')])
    reserve(client, room_id='r3', date='2027-01-07')
    ctx = dict(page='salles')
    messages = []

    def real_contract(key, payload, read_timeout=20):
        assert payload['model'] == 'gpt-6-astra' and payload['reasoning']['effort'] == 'low'
        assert read_timeout >= 30 and payload['store'] is False
        params = json.loads(payload['input'])
        messages.append(params)
        if payload['text']['format']['name'] == 'planning_intent':
            assert 'dummy' not in {r['id'] for r in params['catalogue']['salles']}
            intent = {k:None for k in language.schema()['properties']}
            intent.update(action='availability', weekdays=[], close_source=False, all_courses=False, whole_period=False)
            if 'suivante' in params['demande']:
                assert params['dernier_contexte_verifie']['from_date'] == '2027-01-04'
                assert params['dernier_contexte_verifie']['weekdays'] == [0,1,2,3,4]
                intent.update(week_shift=1, location='Paris')
            else:
                intent.update(from_date='2027-01-04', to_date='2027-01-10')
            output = intent
        else:
            facts = params['fragments']
            if 'suivante' in params['demande']:
                assert facts['periode'] == 'du lundi 11 au vendredi 15 janvier 2027'
                assert not any('2B' in v for v in facts.values())
                output = {'reponse':'Oui, à Paris tu peux utiliser [[salle1]] [[periode]], [[horaires]].'}
            else:
                assert facts['periode'] == 'du lundi 4 au vendredi 8 janvier 2027'
                assert facts['horaires'] == 'de 8 h à 18 h'
                assert facts['salle1'] == '**Salle 2B**'
                assert facts['salle2'] == '**Atelier Modulable Paris**'
                output = {'reponse':'Oui, la [[salle1]] est libre [[periode]], [[horaires]].\n\nÀ Paris, tu as aussi l’[[salle2]] sur ces horaires.'}
        return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}]}
    monkeypatch.setattr(subject_references, 'provider', real_contract)
    result = call(client, '/assistant', {'message':"Une salle de dispo la semaine du 4 janvier 2027 ?", 'context':ctx})
    assert result.status_code == 200
    answer = result.json
    assert answer['message'].startswith('Oui, la **Salle 2B** est libre du lundi 4 au vendredi 8 janvier 2027')
    assert "À Paris" in answer['message'] and '[[salle' not in answer['message']
    assert len(answer['details']) == 3 and 'définir' not in str(answer).casefold()
    assert answer['conversation_token'] and not answer['preview_token']
    follow = call(client, '/assistant', {'message':'Et à Paris la semaine suivante ?', 'context':ctx,
                                         'conversation_token':answer['conversation_token']})
    assert follow.status_code == 200 and 'du lundi 11 au vendredi 15 janvier' in follow.json['message']
    assert len(messages) == 4 and follow.json['preview_token'] is None
    visible = month(client).json
    assert 'dummy' not in {r['id'] for r in visible['rooms']}


def test_virtual_room_is_never_recommended_and_partial_answer_gives_real_times(client, db, ask):
    setup_school(client)
    with db() as conn:
        conn.execute("UPDATE planning_rooms SET name='Salle à définir' WHERE id='r2'")
    add(client, room_id='r1', start='08:00', end='11:00')
    read = ask('availability', ROOMS, from_date='2027-01-04', to_date='2027-01-04')
    assert '11 h à 18 h' in read.json['message'] and 'définir' not in read.json['message']
    assert '04/01' not in read.json['details'][0] and 'créneau libre' in read.json['details'][0]
    assert ask('assign_room', room_id='r2').status_code == 400
    scope = ask('promotion_rooms', ROOMS, promotion_id='p1', period_id='p1:1')
    assert 'Salle à définir' not in scope.json['message']
    no_site = ask('availability', ROOMS, location='Puget', from_date='2027-01-04', to_date='2027-01-04')
    assert 'nom indique' in no_site.json['message'] and not no_site.json['preview_token']


def test_untrusted_writer_refs_or_dates_fall_back_to_verified_answer(monkeypatch):
    evidence = dict(fragments=dict(periode='le lundi 4 janvier', horaires='de 8 h à 18 h', salle1='Salle 2B'),
                    obligatoires=[['periode'],['horaires'],['salle1']])
    def provider(reply):
        return lambda *a,**kw:{'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'reponse':reply})}]}]}
    for invalid in ('Cette salle est libre.', '[[periode]] [[horaires]] [[salle1]] [[inventee]]',
                    '[[periode]] [[horaires]] [[salle1]] et la salle 9.'):
        monkeypatch.setattr(subject_references, 'provider', provider(invalid))
        assert language.compose('fake','question',[],evidence,'réponse vérifiée') == 'réponse vérifiée'


def test_followup_without_a_valid_search_cannot_invent_dates_or_apply(client, ask):
    assert ask('availability', ROOMS, week_shift=1).status_code == 400
    assert ask('remove_courses', PLAN, week_shift=1, all_courses=True).status_code == 400
