"""Read-only admin access to the real student views, scoped to one tab's URL."""
from contextlib import closing

from flask import abort, g, request, url_for

PREVIEW_ROOT = '/consultation-etudiant'
PREFIX = PREVIEW_ROOT + '/<preview_cid>'

# Only these student reads can receive the admin's per-request identity.
# Account activation, password recovery, and student submissions stay separate.
READ_ENDPOINTS = {
    'student_documents', 'student_certificate', 'student_card_image',
    'student_planning', 'student_planning_month', 'student_planning_pdf',
    'teaching_index', 'teaching_course', 'teaching_download', 'gradebook_index',
    'student_absences', 'student_absence_guide', 'student_absence_bulk',
    'student_absence_detail', 'absence_document', 'student_company',
    'student_change_password', 'planning_sync',
}


def register_student_preview(app, db_connect, require_admin):
    # Reuse each original controller, including its data filters and file checks.
    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint in READ_ENDPOINTS and (rule.rule.startswith('/espace/') or rule.endpoint == 'planning_sync'):
            app.add_url_rule(PREFIX + rule.rule, endpoint=rule.endpoint, methods=['GET'])
    app.add_url_rule(PREFIX + '/espace/mon-dossier', endpoint='espace_candidat',
                     defaults={'slug': None}, methods=['GET'])

    @app.url_value_preprocessor
    def resolve_preview(endpoint, values):
        if not values or 'preview_cid' not in values:
            return
        cid = values.pop('preview_cid')
        if not require_admin():
            abort(403)
        if not app.secret_key or app.secret_key in ('change-me', b'change-me'):
            abort(503)
        if endpoint == 'planning_sync' and request.args.get('scope') != 'student':
            abort(403)
        with closing(db_connect()) as conn:
            person = conn.execute('SELECT id,nom,prenom FROM candidats WHERE id=?', (cid,)).fetchone()
            if not person:
                abort(404)
            # Accounts and memberships are created lazily at the first real login.
            member = None
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_account_members'").fetchone():
                member = conn.execute('SELECT account_id FROM student_account_members WHERE candidate_id=?', (cid,)).fetchone()
        g.student_preview = dict(candidate_id=person['id'], nom=person['nom'], prenom=person['prenom'],
                                 account_id=member[0] if member else None, must_change=False)
        home = url_for('espace_candidat', preview_cid=cid)
        g.student_preview_prefix = home.removesuffix('/espace/mon-dossier')
        g.student_portal_path = request.path.removeprefix(f'{PREVIEW_ROOT}/{cid}')

    @app.url_defaults
    def keep_preview(endpoint, values):
        if getattr(g, 'student_preview', None) and endpoint in READ_ENDPOINTS:
            values.setdefault('preview_cid', g.student_preview['candidate_id'])

    @app.after_request
    def private_preview(response):
        if request.path.startswith(PREVIEW_ROOT + '/'):
            response.headers.update({'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer',
                                     'X-Content-Type-Options': 'nosniff'})
            response.vary.add('Cookie')
        return response
