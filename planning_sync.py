"""Private change fingerprints for open timetable screens.

All displayed totals remain derived from the canonical course rows. The browser
only receives an HMAC, never another user's records or administrator settings.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import abort, g, jsonify, request
from candidate_access import get_authenticated_student
from trainer_access import get_authenticated_trainer
from planning import ensure_planning_schema, _has_table
from planning_portal import get_portal_week, get_portal_today

_ADMIN_TABLES = {
    'planning_courses': '*', 'planning_course_groups': '*',
    'planning_subjects': '*', 'planning_rooms': '*',
    'planning_calendar_rules': '*', 'planning_day_exceptions': '*',
    'planning_trainer_unavailability': '*',
    'promotions': '*', 'trainer_promotions': '*',
    'trainers': 'id,nom,prenom,active,version',
    'trainer_hourly_rates': '*', 'trainer_workload_versions': '*',
}


def _stable(value):
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key not in ('live_state', 'live_label')}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def register_planning_sync(app, db_connect, require_admin):
    def identity(scope):
        if scope == 'admin':
            return 'admin' if require_admin() else None
        if scope == 'trainer':
            person = get_authenticated_trainer(app, db_connect)
            return person['id'] if person else None
        if scope == 'student':
            person = get_authenticated_student(app, db_connect)
            return person['candidate_id'] if person else None
        return None

    def fingerprint(scope, who, view, selected_date=None):
        with closing(db_connect()) as conn:
            ensure_planning_schema(conn)
            conn.execute('BEGIN')
            if scope == 'admin':
                payload = {}
                for table, columns in _ADMIN_TABLES.items():
                    if _has_table(conn, table):
                        payload[table] = sorted([dict(row) for row in conn.execute(f'SELECT {columns} FROM {table}')], key=lambda row: json.dumps(row, sort_keys=True))
                payload['today'] = datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
            elif view == 'week':
                payload = get_portal_week(conn, scope, who, selected_date)
            else:
                payload = get_portal_today(conn, scope, who)
        raw = json.dumps([scope, who, _stable(payload)], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        secret = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
        return hmac.new(secret, raw, hashlib.sha256).hexdigest()

    @app.get('/planning/sync')
    def planning_sync():
        if set(request.args) - {'scope', 'view', 'date'} or any(len(values) != 1 for _, values in request.args.lists()):
            abort(400)
        scope = request.args.get('scope')
        view = request.args.get('view')
        if scope not in ('admin', 'trainer', 'student') or view not in ('week', 'today', 'admin'):
            abort(400)
        if (scope == 'admin') != (view == 'admin') or ('date' in request.args and view != 'week'):
            abort(400)
        who = identity(scope)
        if not who:
            response = app.make_response((jsonify(error='Connexion requise.'), 401))
        else:
            try:
                revision = fingerprint(scope, who, view, request.args.get('date'))
            except ValueError:
                abort(400)
            response = app.make_response(jsonify(revision=revision))
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.vary.add('Cookie')
        return response

    @app.before_request
    def capture_planning_revision():
        # Capture BEFORE the controller reads the displayed data. A later write
        # then always differs from this baseline on the next poll, even if it
        # occurred between rendering the schedule and running context processors.
        g.planning_sync_config = None
        endpoint = request.endpoint
        if endpoint in ('planning_admin', 'admin_trainer_detail'):
            scope, view = 'admin', 'admin'
        elif endpoint in ('trainer_planning', 'student_planning'):
            scope, view = ('trainer' if endpoint == 'trainer_planning' else 'student'), 'week'
        elif endpoint == 'trainer_dashboard':
            scope, view = 'trainer', 'today'
        elif endpoint in ('espace_candidat', 'student_dashboard'):
            person = get_authenticated_student(app, db_connect)
            if not person or (endpoint == 'espace_candidat' and person.get('slug_public') != (request.view_args or {}).get('slug')):
                return None
            scope, view = 'student', 'today'
        else:
            return None
        who = identity(scope)
        if not who:
            return None
        args = dict(scope=scope, view=view)
        if view == 'week' and request.args.get('date'):
            args['date'] = request.args['date']
        try:
            g.planning_sync_config = dict(url='/planning/sync?' + urlencode(args), revision=fingerprint(scope, who, view, args.get('date')))
        except ValueError:
            # Let the page controller return its normal invalid-date response.
            pass

    @app.context_processor
    def planning_sync_context():
        return dict(planning_sync_config=getattr(g, 'planning_sync_config', None))
