"""Opt-in release check. Use the configured provider on fictional room data only."""
from contextlib import closing
import json
from threading import Thread

import planning_assistant_language as language
from planning_assistant import resolve_relative_week
from planning_assistant_replies import availability_answer
from subject_references import api_key


def verify(key):
    question = 'Est-ce qu’il y a une salle de dispo la semaine du 4 janvier 2027 ?'
    page = dict(page='salles', promotion_id=None, period_id=None)
    inventory = dict(salles=[dict(id='a', name='Salle 2B', active=1),
                             dict(id='b', name='Atelier Modulable Paris', active=1)], promotions=[])
    intent = language.interpret(key, question, [], inventory, page)
    if (intent['action'] != 'availability' or intent['from_date'] != '2027-01-04'
            or intent['to_date'] not in ('2027-01-08','2027-01-09','2027-01-10')):
        raise ValueError('période initiale mal interprétée')
    dates = [f'2027-01-{n:02d}' for n in range(4, 9)]
    schedule = dict(dates=dates, weekdays=[0,1,2,3,4], start='08:00', end='18:00')
    rooms = [dict(r, days={d:dict(state='free',free=[['08:00','18:00']]) for d in dates}, free_days=5)
             for r in inventory['salles']]
    answer = availability_answer(schedule, rooms)
    reply = language.write_reply(key, question, [], answer.evidence)
    follow = language.interpret(key, 'Et la semaine suivante ?', [{'role':'user','text':question},
                                {'role':'assistant','text':reply}], inventory, page, intent)
    follow = resolve_relative_week(follow, intent)
    if (follow['action'] != 'availability' or follow['from_date'] != '2027-01-11'
            or follow['to_date'] not in ('2027-01-15','2027-01-16','2027-01-17')):
        raise ValueError('relance mal interprétée')
    return reply


def start_release_check(app, connect, revision):
    def run():
        model = language.model_name()
        prefix = f'planning-chat-check {revision[:12]} {model}'
        try:
            with closing(connect()) as conn:
                # Werkzeug's reloader and multiple workers may start together. Claim this exact
                # opt-in release/model once before any billable request; no production bookings are read.
                claim = conn.execute('INSERT OR IGNORE INTO planning_reference_settings(name,value) VALUES(?,?)',
                                     (f'planning_chat_check:{revision}:{model}', 'claimed'))
                conn.commit()
                if not claim.rowcount:
                    return
                key = api_key(app, conn)
            print(f'{prefix} started', flush=True)
            reply = verify(key)
            print(f'{prefix} passed {json.dumps(reply, ensure_ascii=False)}', flush=True)
        except ValueError as exc:
            print(f'{prefix} failed: {exc}', flush=True)
        except Exception as exc:
            print(f'{prefix} failed: {type(exc).__name__}', flush=True)

    Thread(target=run, name='planning-chat-release-check', daemon=True).start()
