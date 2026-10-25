"""Independent synchronization race and private-scope regressions."""
import re

import planning_portal
from test_planning_portal import portal_db, portal_app, login
from test_planning_sync import synced_app, revision


def test_change_between_view_read_and_template_render_is_detected_next_poll(
        synced_app, portal_db, monkeypatch):
    """An old HTML snapshot must never be stamped with the new revision."""
    original = planning_portal.get_portal_week
    changed = False

    def read_then_concurrent_change(conn, role, identity, day=None):
        nonlocal changed
        snapshot = original(conn, role, identity, day)
        if not changed:
            changed = True
            with portal_db() as writer:
                writer.execute("UPDATE planning_courses SET title='Cours modifié pendant le rendu',version=version+1 WHERE id='common'")
        return snapshot

    monkeypatch.setattr(planning_portal, 'get_portal_week', read_then_concurrent_change)
    client = login(synced_app)
    page = client.get('/espace/planning?date=2026-10-26')
    assert page.status_code == 200
    assert changed and 'Cours modifié pendant le rendu' not in page.text
    initial = re.search(r'data-planning-sync-revision="([a-f0-9]{64})"', page.text)
    assert initial is not None
    assert revision(client) != initial.group(1), 'The pending course change became invisible to the polling client'


def test_student_fingerprint_does_not_change_when_other_trainer_rate_changes(synced_app, portal_db):
    import trainer_workload
    client = login(synced_app)
    before = revision(client)
    with portal_db() as conn:
        trainer_workload.ensure_workload_schema(conn)
        trainer_workload.save_hourly_rate(conn, 't2', '2026-09-01', '77.25', 0)
    assert revision(client) == before


def test_trainer_fingerprint_does_not_change_when_own_hourly_rate_changes(synced_app, portal_db):
    import trainer_workload
    client = login(synced_app, 'trainer', 't1')
    before = revision(client, 'trainer')
    with portal_db() as conn:
        trainer_workload.ensure_workload_schema(conn)
        trainer_workload.save_hourly_rate(conn, 't1', '2026-09-01', '77.25', 0)
    assert revision(client, 'trainer') == before


def test_admin_rate_change_refreshes_workload_fiche(synced_app, portal_db):
    import trainer_workload
    client = login(synced_app)
    with client.session_transaction() as auth:
        auth['admin_ok'] = True
    before = revision(client, 'admin', 'admin', None)
    with portal_db() as conn:
        trainer_workload.ensure_workload_schema(conn)
        trainer_workload.save_hourly_rate(conn, 't1', '2026-09-01', '77.25', 0)
    assert revision(client, 'admin', 'admin', None) != before
