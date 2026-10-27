"""Availability mail uses an atomic outbox and exact, independently retried recipients."""
from contextlib import closing
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from flask import Flask
from jinja2 import DictLoader
import pytest

import trainer_availability as availability
import trainer_notifications as notifications
from test_planning_portal_security import portal_db
from test_trainer_availability import logged, preview, commit


@pytest.fixture
def mail_app(portal_db,monkeypatch):
    monkeypatch.setattr(availability,'_now_paris',lambda:datetime(2026,10,25,10,tzinfo=ZoneInfo('Europe/Paris')))
    app=Flask(__name__)
    app.secret_key='notification-tests-only'
    app.config.update(TESTING=True,TRAINER_NOTIFICATIONS_SYNC=True)
    app.jinja_loader=DictLoader({'trainer_availability.html':'{{ availability|tojson }}'})
    app.add_url_rule('/formateur/connexion','trainer_login',lambda:'Login')
    app.add_url_rule('/formateur','trainer_dashboard',lambda:'Dashboard')
    app.add_url_rule('/formateur/planning','trainer_planning',lambda:'Planning')
    calls=[]
    def send(recipient,subject,html):
        # Separate connection proves the scheduling transaction already committed.
        with closing(portal_db()) as conn:
            assert conn.execute('SELECT COUNT(*) FROM trainer_availability_notifications').fetchone()[0]>0
            jobs=conn.execute('SELECT COUNT(*) FROM trainer_availability_deliveries').fetchone()[0]
            assert jobs>=2
        calls.append(dict(recipient=recipient,subject=subject,html=html))
        value=app.config.get('DELIVERY_RESULTS',{}).get(recipient,'fake-provider-id')
        if isinstance(value,Exception):raise value
        return value
    availability.register_trainer_availability(app,portal_db,send)
    return app,calls,send


def deliveries(db):
    with closing(db()) as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM trainer_availability_deliveries ORDER BY recipient')]


def test_preview_and_cancel_never_queue_or_send(mail_app,portal_db):
    app,calls,_=mail_app
    result=preview(logged(app))
    assert result.status_code==200 and result.json['requires_confirmation']
    assert calls==[] and deliveries(portal_db)==[]


def test_commit_sends_exactly_two_branded_messages_with_full_deleted_class(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    token=preview(client).json['preview_token']
    response=commit(client,token,confirm_delete=True)
    assert response.status_code==200 and response.json['notification_queued']
    assert {c['recipient'] for c in calls}==set(notifications.RECIPIENTS)
    assert len(calls)==2
    for call in calls:
        assert 'FORMATEUR T1 Camille' in call['subject']
        html=call['html']
        for value in ('academy-official-logo.png','font-style:italic','5 janvier 2027','09:00','11:00','Cours shared','PROMOTION LOCALE','PROMOTION AUTRE','Salle locale','2 h','tab=availability'):
            assert value in html
        assert 'secret-social-number' not in html
        assert 'gestion@integraleacademy.com' not in html
    assert all(row['status']=='sent' for row in deliveries(portal_db))
    with closing(portal_db()) as conn:
        assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone() is None


def test_confirmation_and_stale_failure_do_not_notify(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    token=preview(client).json['preview_token']
    assert commit(client,token).status_code==409
    with portal_db() as conn:conn.execute("UPDATE planning_courses SET version=version+1 WHERE id='shared'")
    assert commit(client,token,confirm_delete=True).status_code==409
    assert not calls and deliveries(portal_db)==[]


def test_replayed_commit_never_sends_again(mail_app,portal_db):
    app,calls,send=mail_app;client=logged(app)
    token=preview(client).json['preview_token']
    assert commit(client,token,confirm_delete=True).status_code==200
    assert commit(client,token,confirm_delete=True).status_code==409
    notifications.dispatch_pending_notifications(app,portal_db,send,now=9999999999)
    assert len(calls)==2 and all(row['attempts']==1 for row in deliveries(portal_db))


def test_noop_personal_removal_does_not_notify(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    token=preview(client,['2027-01-07'],action='available').json['preview_token']
    response=commit(client,token)
    assert response.status_code==200 and response.json['notification_queued'] is False
    assert calls==[] and deliveries(portal_db)==[]


def test_repeat_existing_unavailability_without_change_does_not_notify(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    first=preview(client,['2027-01-07']).json['preview_token']
    assert commit(client,first).status_code==200
    second=preview(client,['2027-01-07']).json['preview_token']
    assert commit(client,second).json['notification_queued'] is False
    assert len(calls)==2


def test_removing_personal_dates_notifies_and_does_not_recreate_courses(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    assert commit(client,preview(client).json['preview_token'],confirm_delete=True).status_code==200
    token=preview(client,action='available').json['preview_token']
    assert commit(client,token).status_code==200
    assert len(calls)==4
    assert all('Disponibilités rétablies' in call['subject'] for call in calls[2:])
    assert all('Aucun cours n’est recréé automatiquement' in call['html'] for call in calls[2:])
    with closing(portal_db()) as conn:assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone() is None


@pytest.mark.parametrize('failure',[False,RuntimeError('provider failed')])
def test_one_failed_recipient_retries_without_resending_success(mail_app,portal_db,failure):
    app,calls,send=mail_app;client=logged(app)
    app.config['DELIVERY_RESULTS']={'clement@integraleacademy.com':failure}
    response=commit(client,preview(client).json['preview_token'],confirm_delete=True)
    assert response.status_code==200
    rows={row['recipient']:row for row in deliveries(portal_db)}
    assert rows['ecole@integraleacademy.com']['status']=='sent'
    assert rows['clement@integraleacademy.com']['status']=='pending'
    due=rows['clement@integraleacademy.com']['next_attempt']
    app.config['DELIVERY_RESULTS']={}
    assert notifications.dispatch_pending_notifications(app,portal_db,send,now=due-1)==0
    assert notifications.dispatch_pending_notifications(app,portal_db,send,now=due+1)==1
    assert [c['recipient'] for c in calls].count('ecole@integraleacademy.com')==1
    assert [c['recipient'] for c in calls].count('clement@integraleacademy.com')==2
    assert all(row['status']=='sent' for row in deliveries(portal_db))


def test_queue_survives_when_sender_not_running_then_resumes(mail_app,portal_db):
    app,calls,send=mail_app;app.config['TRAINER_NOTIFICATIONS_SYNC']=False;client=logged(app)
    assert commit(client,preview(client).json['preview_token'],confirm_delete=True).status_code==200
    assert calls==[] and len(deliveries(portal_db))==2
    notifications.dispatch_pending_notifications(app,portal_db,send)
    assert len(calls)==2 and all(row['status']=='sent' for row in deliveries(portal_db))


def test_claim_lease_prevents_parallel_duplicate_and_recovers_after_crash(mail_app,portal_db):
    app,calls,send=mail_app;app.config['TRAINER_NOTIFICATIONS_SYNC']=False;client=logged(app)
    commit(client,preview(client).json['preview_token'],confirm_delete=True)
    first=notifications._claim(portal_db,now=1000)
    assert first is not None
    notifications.dispatch_pending_notifications(app,portal_db,send,now=1001)
    assert len(calls)==1 and calls[0]['recipient']!=first['recipient']
    assert notifications.dispatch_pending_notifications(app,portal_db,send,now=1299)==0
    assert notifications.dispatch_pending_notifications(app,portal_db,send,now=1301)==1
    assert len(calls)==2 and set(c['recipient'] for c in calls)==set(notifications.RECIPIENTS)


def test_render_escapes_user_text_and_includes_only_fixed_admin_recipients(mail_app,portal_db):
    app,calls,_=mail_app;client=logged(app)
    with portal_db() as conn:conn.execute("UPDATE planning_courses SET title='<script>steal()</script>' WHERE id='shared'")
    token=preview(client,reason='<img src=x onerror=steal()>').json['preview_token']
    assert commit(client,token,confirm_delete=True).status_code==200
    assert all('<script>' not in call['html'] and '<img src=x' not in call['html'] for call in calls)
    assert '&lt;script&gt;' in calls[0]['html'] and '&lt;img src=x' in calls[0]['html']


def test_notification_status_scoped_and_excludes_provider_and_payload_details(mail_app,portal_db):
    app,_,_=mail_app;client=logged(app)
    commit(client,preview(client).json['preview_token'],confirm_delete=True)
    with closing(portal_db()) as conn:
        result=notifications.notification_status(conn,'t1')
        assert notifications.notification_status(conn,'t2')==[]
    assert len(result)==1 and result[0]['complete']
    assert result[0]['course_count']==1
    assert 'provider_id' not in json.dumps(result) and 'payload_json' not in json.dumps(result)


def test_outbox_rolls_back_with_scheduling_transaction(mail_app,portal_db,monkeypatch):
    app,calls,_=mail_app;client=logged(app)
    original=availability.enqueue_availability_notification
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise availability.PlanningError('Fixture transaction interrupted',status=409)
    monkeypatch.setattr(availability,'enqueue_availability_notification',interrupted)
    response=commit(client,preview(client).json['preview_token'],confirm_delete=True)
    assert response.status_code==409 and not calls
    with closing(portal_db()) as conn:
        assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone()
        assert conn.execute('SELECT COUNT(*) FROM trainer_availability_deliveries').fetchone()[0]==0
