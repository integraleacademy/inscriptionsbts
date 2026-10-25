"""Independent post-commit delivery, per-recipient retry and safe-mail audit."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

import trainer_availability
import trainer_notifications as notifications
from test_planning_portal_security import portal_db
from test_trainer_availability import logged, preview, commit


@pytest.fixture
def notification_app(portal_db,monkeypatch):
    monkeypatch.setattr(trainer_availability,'_now_paris',lambda:datetime(2026,10,25,10,tzinfo=ZoneInfo('Europe/Paris')))
    app=Flask(__name__)
    app.secret_key='notification-audit-only'
    app.config.update(TESTING=True,TRAINER_NOTIFICATIONS_SYNC=True)
    attempted=[]
    state={'reject':set()}
    def sender(to,subject,html):
        with portal_db() as conn:
            # Transport must never run while the original shared class still exists.
            assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone() is None
            assert conn.execute('SELECT COUNT(*) FROM trainer_availability_notifications').fetchone()[0]>0
        attempted.append((to,subject,html))
        return False if to in state['reject'] else 'mock-provider-id'
    trainer_availability.register_trainer_availability(app,portal_db,sender)
    return app,attempted,state,sender


def test_mail_only_follows_confirmed_committed_change_and_replay_is_silent(notification_app,portal_db):
    app,sent,state,_=notification_app
    client=logged(app)
    result=preview(client).json
    assert sent==[]
    assert commit(client,result['preview_token']).status_code==409
    assert sent==[]
    response=commit(client,result['preview_token'],confirm_delete=True)
    assert response.status_code==200 and response.json['notification_queued']
    assert {to for to,_,_ in sent}=={'ecole@integraleacademy.com','clement@integraleacademy.com'}
    assert len(sent)==2
    for to,subject,html in sent:
        assert 'academy-official-logo.png' in html
        assert 'PROMOTION LOCALE' in html and 'PROMOTION AUTRE' in html
        assert result['courses'][0]['start'] in html and result['courses'][0]['end'] in html
        assert 'Aucun cours' not in html
    assert commit(client,result['preview_token'],confirm_delete=True).status_code==409
    assert len(sent)==2


def test_partial_delivery_retries_only_failed_recipient(notification_app,portal_db):
    app,sent,state,sender=notification_app
    state['reject'].add('clement@integraleacademy.com')
    client=logged(app)
    token=preview(client).json['preview_token']
    assert commit(client,token,confirm_delete=True).status_code==200
    with portal_db() as conn:
        deliveries={row['recipient']:row['status'] for row in conn.execute('SELECT * FROM trainer_availability_deliveries')}
    assert deliveries=={'ecole@integraleacademy.com':'sent','clement@integraleacademy.com':'pending'}
    state['reject'].clear()
    notifications.dispatch_pending_notifications(app,portal_db,sender,now=9999999999)
    assert [to for to,_,_ in sent].count('ecole@integraleacademy.com')==1
    assert [to for to,_,_ in sent].count('clement@integraleacademy.com')==2
    with portal_db() as conn:
        assert all(row['status']=='sent' for row in conn.execute('SELECT * FROM trainer_availability_deliveries'))
    assert notifications.dispatch_pending_notifications(app,portal_db,sender,now=9999999999)==0


def test_stale_cancellation_never_emits_or_queues_notification(notification_app,portal_db):
    app,sent,_,_=notification_app
    client=logged(app)
    token=preview(client).json['preview_token']
    with portal_db() as conn:
        conn.execute("UPDATE planning_courses SET version=version+1 WHERE id='shared'")
    assert commit(client,token,confirm_delete=True).status_code==409
    assert sent==[]
    with portal_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM trainer_availability_notifications').fetchone()[0]==0
        assert conn.execute("SELECT 1 FROM planning_courses WHERE id='shared'").fetchone()


def test_notification_render_escapes_details_and_never_embeds_student_or_rate_data():
    snapshot=dict(trainer_id='t1',prenom='<script>bad</script>',nom='AUDIT',email='trainer@example.test',
        action='unavailable',dates=['2027-01-05'],courses=[dict(date='2027-01-05',start='08:00',end='10:00',
        title='<img src=x onerror=bad>',subject_name='Test',promotion_names=['<b>group</b>'],room_name='',shared=True,duration_minutes=120)],
        reason='<iframe src="bad"></iframe>',created_at='2026-10-25T05:30:00+00:00',revision=1)
    subject,html=notifications.render_availability_notification(snapshot)
    assert '<script>bad</script>' not in html
    assert '&lt;script&gt;bad&lt;/script&gt;' in html
    assert '<iframe src=' not in html
    assert '<img src=x onerror=bad>' not in html
    assert 'tarif' not in html.lower()
