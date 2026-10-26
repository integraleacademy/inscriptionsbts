"""Private student attendance, evidence review, and linked employer information."""
from contextlib import closing
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import hmac
import secrets
import time

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from werkzeug.utils import secure_filename

from absence_reasons import GUIDE_URL, LAW_URL, REASON_MAP
from candidate_access import get_authenticated_student
from company_portal import ensure_company_schema, now_iso, today, month_bounds

FILE_LIMIT = 10 * 1024 * 1024
TOTAL_LIMIT = 20 * 1024 * 1024
FILE_COUNT = 5
STATES = {'pending': 'En cours de traitement', 'accepted': 'Justifiée',
          'rejected': 'Refusée', 'needs_info': 'À compléter'}


def ensure_workspace_schema(conn):
    # Serialize additive schema work on the same persistent SQLite database.
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    ensure_company_schema(conn)
    for sql in (
        '''CREATE TABLE IF NOT EXISTS absence_requests (
            id TEXT PRIMARY KEY, attendance_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            reason TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','needs_info')),
            version INTEGER NOT NULL DEFAULT 1, submitted_at TEXT NOT NULL,
            reviewed_at TEXT, reviewer_comment TEXT NOT NULL DEFAULT '',
            UNIQUE(attendance_id,candidate_id))''',
        '''CREATE TABLE IF NOT EXISTS absence_files (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL, filename TEXT NOT NULL,
            storage_name TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, mime TEXT NOT NULL,
            created_at TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS absence_files_request ON absence_files(request_id)',
        '''CREATE TABLE IF NOT EXISTS absence_history (
            id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, action TEXT NOT NULL,
            actor TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS absence_history_request ON absence_history(request_id,id)',
    ):
        conn.execute(sql)


def display_date(value):
    if not value:
        return 'Non renseignée'
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo('Europe/Paris'))
        return parsed.strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return value


def state_for(event, submission):
    # Administrative qualification remains authoritative for older records.
    if event['justification'] == 'justified':
        return 'accepted', 'Justifié' if event['kind'] == 'late' else STATES['accepted']
    if submission:
        label = STATES[submission['status']]
        if event['kind'] == 'late' and submission['status'] in ('accepted', 'rejected'):
            label = label[:-1]
        return submission['status'], label
    if event['justification'] == 'unjustified':
        return 'unjustified', 'Non justifié' if event['kind'] == 'late' else 'Non justifiée'
    return 'missing', 'À justifier'


def own_company(conn, candidate_id):
    row = conn.execute('''SELECT e.name,e.legal_name,e.trade_name,e.siret,e.address,
        e.postal_code,e.city,e.contact,e.email,e.phone,e.activity_label,
        s.start_date,s.end_date,s.tutor FROM company_students s
        JOIN companies e ON e.id=s.company_id WHERE s.candidate_id=?''', (candidate_id,)).fetchone()
    if not row:
        return None
    company = dict(row)
    day = today().isoformat()
    company['period_label'] = ('À venir' if company['start_date'] > day else
                               'Rattachement terminé' if company['end_date'] and company['end_date'] < day else 'En cours')
    return company


def student_home_summary(conn, identity):
    ensure_workspace_schema(conn)
    rows = student_events(conn, identity['account_id'])
    conn.commit()
    return dict(company=own_company(conn, identity['candidate_id']),
                absences=sum(r['kind'] == 'absence' for r in rows),
                to_justify=sum(r['state'] in ('missing', 'unjustified', 'needs_info', 'rejected') for r in rows),
                pending=sum(r['state'] == 'pending' for r in rows))


def student_events(conn, account_id):
    rows = []
    for row in conn.execute('''SELECT a.*,c.bts FROM student_attendance a
        JOIN student_account_members m ON m.candidate_id=a.candidate_id
        JOIN candidats c ON c.id=a.candidate_id
        WHERE m.account_id=? AND a.deleted=0 ORDER BY a.date DESC,a.start_min DESC,a.id''', (account_id,)):
        item = dict(row)
        submission = conn.execute('SELECT * FROM absence_requests WHERE attendance_id=? AND candidate_id=?',
                                  (item['id'], item['candidate_id'])).fetchone()
        item['state'], item['state_label'] = state_for(item, submission)
        item.update(date_label=display_date(item['date']), start=f"{item['start_min']//60:02}:{item['start_min']%60:02}",
                    end=f"{item['end_min']//60:02}:{item['end_min']%60:02}", minutes=item['end_min']-item['start_min'])
        rows.append(item)
    return rows


def synchronize_attendance_edit(conn, current, candidate_id, day, begin, finish, kind, justification):
    """Keep an administrative correction consistent with an existing evidence review."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='absence_requests'").fetchone():
        return justification
    submitted = conn.execute('SELECT * FROM absence_requests WHERE attendance_id=? AND candidate_id=?',
                             (current['id'], current['candidate_id'])).fetchone()
    if not submitted:
        return justification
    if candidate_id != current['candidate_id']:
        raise ValueError('Cet événement possède un justificatif. Créez un autre événement pour un autre étudiant.')
    if justification != current['justification']:
        raise ValueError('Traitez le justificatif depuis « Justificatifs étudiants » pour informer l’étudiant de la décision.')
    if (day, begin, finish, kind) != (current['date'], current['start_min'], current['end_min'], current['kind']):
        message = 'L’équipe a corrigé la période ou le type d’absence. Le justificatif sera réexaminé.'
        conn.execute("UPDATE absence_requests SET status='pending',version=version+1,reviewed_at=NULL,reviewer_comment=? WHERE id=?", (message, submitted['id']))
        conn.execute('INSERT INTO absence_history(request_id,action,actor,message,created_at) VALUES(?,?,?,?,?)',
                     (submitted['id'], 'Période corrigée', 'Équipe pédagogique', message, now_iso()))
        return 'pending'
    return justification


def validated_files(files):
    result, total = [], 0
    for upload in files:
        if not upload.filename:
            continue
        if len(result) >= FILE_COUNT:
            raise ValueError('Tu peux déposer au maximum 5 documents par demande.')
        name = secure_filename(upload.filename)[:180]
        extension = Path(name).suffix.lower()
        data = upload.stream.read(FILE_LIMIT + 1)
        total += len(data)
        if not data or len(data) > FILE_LIMIT or total > TOTAL_LIMIT:
            raise ValueError('Chaque document doit faire entre 1 octet et 10 Mo, avec 20 Mo maximum par demande.')
        if extension == '.pdf':
            try:
                if not data.startswith(b'%PDF-'):
                    raise ValueError()
                pdf = PdfReader(BytesIO(data))
                if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 100:
                    raise ValueError()
            except Exception:
                raise ValueError('Le PDF est illisible, protégé ou contient plus de 100 pages.') from None
            mime = 'application/pdf'
        elif extension in ('.jpg', '.jpeg', '.png', '.webp'):
            try:
                with Image.open(BytesIO(data)) as picture:
                    fmt = picture.format
                    if picture.width * picture.height > 25_000_000:
                        raise ValueError()
                    picture.verify()
                expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}[extension]
                if fmt != expected:
                    raise ValueError()
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                raise ValueError('L’image est illisible ou trop grande. Utilise un PDF, JPEG, PNG ou WebP.') from None
            mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[fmt]
        else:
            raise ValueError('Formats acceptés : PDF, JPEG, PNG et WebP.')
        result.append(dict(filename=name, content=data, size=len(data), mime=mime,
                           id=secrets.token_urlsafe(24), storage_name=secrets.token_hex(24)+extension))
    return result


def register_student_workspace(app, db_connect, uploads_dir, require_admin):
    app.jinja_env.filters['student_date'] = display_date

    def connect():
        conn = db_connect()
        ensure_workspace_schema(conn)
        conn.commit()
        return conn

    def private(response):
        response = app.make_response(response)
        response.headers.update({'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
        response.vary.add('Cookie')
        return response

    @app.after_request
    def private_headers(response):
        if request.path.startswith(('/espace/absences', '/espace/entreprise', '/admin/assiduite/justificatifs')):
            return private(response)
        return response

    def student_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            identity = get_authenticated_student(app, db_connect, allow_initial=True)
            if not identity:
                return private(redirect('/espace/connexion'))
            if identity['must_change']:
                return private(redirect('/espace/mot-de-passe'))
            return fn(identity, *args, **kwargs)
        return wrapped

    def csrf(admin=False, check=False):
        key = '_company_csrf' if admin else '_candidate_access_csrf'
        if check:
            expected = session.get(key, '')
            if not expected or not hmac.compare_digest(expected.encode(), request.form.get('csrf_token', '').encode()):
                abort(400, 'La page a expiré. Recharge-la avant de réessayer.')
        session.setdefault(key, secrets.token_urlsafe(32))
        return session[key]

    def current_identity(conn, identity):
        row = conn.execute('SELECT version,must_change FROM student_accounts WHERE id=?', (identity['account_id'],)).fetchone()
        if not row or row['version'] != identity['version'] or row['must_change'] or session.get('_student_auth', {}).get('expires_at', 0) <= time.time():
            abort(403, 'Reconnecte-toi à ton espace étudiant.')

    def event_for(conn, event_id, identity=None):
        event = conn.execute('SELECT * FROM student_attendance WHERE id=? AND deleted=0', (event_id,)).fetchone()
        if not event:
            abort(404)
        if identity and not conn.execute('SELECT 1 FROM student_account_members WHERE candidate_id=? AND account_id=?',
                                        (event['candidate_id'], identity['account_id'])).fetchone():
            abort(404)
        return dict(event)

    def submission_for(conn, event):
        row = conn.execute('SELECT * FROM absence_requests WHERE attendance_id=? AND candidate_id=?', (event['id'], event['candidate_id'])).fetchone()
        return dict(row) if row else None

    def version_check(value, expected):
        if str(value) != str(expected):
            abort(409, 'Cette demande a changé. Recharge la page avant de réessayer.')

    def page(template, **context):
        return private(render_template(template, reasons=REASON_MAP, states=STATES,
                                       guide_url=GUIDE_URL, law_url=LAW_URL, **context))

    def evidence_context(conn, event, submission):
        files = [dict(r) for r in conn.execute('SELECT id,filename,size FROM absence_files WHERE request_id=? ORDER BY created_at,id', (submission['id'],))] if submission else []
        history = [dict(r) for r in conn.execute('SELECT action,actor,message,created_at FROM absence_history WHERE request_id=? ORDER BY id DESC', (submission['id'],))] if submission else []
        state, state_label = state_for(event, submission)
        return dict(event=event, submission=submission, files=files, history=history, state=state, state_label=state_label)

    @app.get('/espace/absences')
    @student_required
    def student_absences(identity):
        with closing(connect()) as conn:
            rows = student_events(conn, identity['account_id'])
        summary = dict(count=sum(r['kind']=='absence' for r in rows), minutes=sum(r['minutes'] for r in rows if r['kind']=='absence'),
                       late=sum(r['kind']=='late' for r in rows), pending=sum(r['state']=='pending' for r in rows),
                       missing=sum(r['state'] in ('missing','unjustified','needs_info','rejected') for r in rows))
        month, state = request.args.get('month', ''), request.args.get('status', '')
        if month:
            try:
                month_bounds(month)
            except ValueError:
                abort(400)
        if state not in ('', 'missing', 'pending', 'accepted', 'rejected', 'needs_info', 'unjustified'):
            abort(400)
        visible = [r for r in rows if (not month or r['date'].startswith(month)) and (not state or r['state']==state)]
        return page('student_absences.html', title='Mes absences · Espace étudiant', rows=visible, total=len(rows),
                    summary=summary, month=month, selected_state=state)

    @app.route('/espace/absences/<event_id>', methods=['GET', 'POST'])
    @student_required
    def student_absence_detail(identity, event_id):
        error, prepared, written = '', [], []
        with closing(connect()) as conn:
            event = event_for(conn, event_id, identity)
            submission = submission_for(conn, event)
            if request.method == 'POST':
                csrf(check=True)
                try:
                    if request.content_length and request.content_length > TOTAL_LIMIT + 100000:
                        raise ValueError('La demande dépasse 20 Mo.')
                    reason, message = request.form.get('reason', ''), request.form.get('message', '').strip()
                    if reason not in REASON_MAP or len(message) > 3000 or (reason == 'other' and len(message) < 10):
                        raise ValueError('Choisis un motif et précise ta situation si tu sélectionnes « Autre situation ». Le message est limité à 3 000 caractères.')
                    prepared = validated_files(request.files.getlist('documents'))
                    conn.execute('BEGIN IMMEDIATE')
                    current_identity(conn, identity)
                    event = event_for(conn, event_id, identity)
                    submission = submission_for(conn, event)
                    version_check(request.form.get('event_version'), event['version'])
                    version_check(request.form.get('version'), submission['version'] if submission else 0)
                    if event['justification'] == 'justified' or (submission and submission['status']=='accepted'):
                        abort(409, 'Cette absence est déjà justifiée.')
                    existing = conn.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM absence_files WHERE request_id=?', (submission['id'] if submission else '',)).fetchone()
                    if existing[0]+len(prepared) == 0:
                        raise ValueError('Ajoute au moins un justificatif avant d’envoyer ta demande.')
                    if existing[0]+len(prepared) > FILE_COUNT or existing[1]+sum(f['size'] for f in prepared) > TOTAL_LIMIT:
                        raise ValueError('La demande est limitée à 5 documents et 20 Mo au total.')
                    request_id = submission['id'] if submission else secrets.token_urlsafe(24)
                    stamp = now_iso()
                    conn.execute('''INSERT INTO absence_requests(id,attendance_id,candidate_id,reason,message,status,submitted_at)
                        VALUES(?,?,?,?,?,'pending',?) ON CONFLICT(attendance_id,candidate_id) DO UPDATE SET
                        reason=excluded.reason,message=excluded.message,status='pending',version=absence_requests.version+1,
                        submitted_at=excluded.submitted_at,reviewed_at=NULL,reviewer_comment='' ''',
                        (request_id, event_id, event['candidate_id'], reason, message, stamp))
                    directory = Path(uploads_dir()).resolve().parent / 'absence-justifications'
                    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if directory.is_symlink():
                        raise OSError('Invalid evidence directory')
                    for item in prepared:
                        path = directory / item['storage_name']
                        with path.open('xb') as output:
                            written.append(path)
                            output.write(item['content'])
                        path.chmod(0o600)
                        conn.execute('INSERT INTO absence_files VALUES(?,?,?,?,?,?,?)',
                                     (item['id'],request_id,item['filename'],item['storage_name'],item['size'],item['mime'],stamp))
                    conn.execute("UPDATE student_attendance SET justification='pending',version=version+1,updated_at=? WHERE id=?", (stamp,event_id))
                    conn.execute('INSERT INTO absence_history(request_id,action,actor,message,created_at) VALUES(?,?,?,?,?)',
                                 (request_id,'Complément envoyé' if submission else 'Justificatif envoyé','Étudiant',REASON_MAP[reason]['label']+' — '+message,stamp))
                    conn.commit()
                    flash('Justificatif envoyé. Ta demande est en cours de traitement par l’équipe.', 'success')
                    return private(redirect(url_for('student_absence_detail',event_id=event_id),code=303))
                except ValueError as exc:
                    conn.rollback()
                    error = str(exc)
                except Exception:
                    conn.rollback()
                    for path in written:
                        path.unlink(missing_ok=True)
                    raise
            context = evidence_context(conn, event_for(conn,event_id,identity), submission_for(conn,event_for(conn,event_id,identity)))
        return page('student_absence_detail.html', title='Justifier mon absence · Espace étudiant',
                    csrf_token=csrf(), error=error, **context), 400 if error else 200

    @app.get('/espace/entreprise')
    @student_required
    def student_company(identity):
        with closing(connect()) as conn:
            company = own_company(conn, identity['candidate_id'])
        return page('student_company.html', title='Mon entreprise · Espace étudiant', company=company)

    @app.get('/admin/assiduite/justificatifs')
    def admin_absence_requests():
        if not require_admin():
            abort(403)
        status = request.args.get('status', 'pending')
        if status not in ('all', *STATES):
            abort(400)
        with closing(connect()) as conn:
            rows = [dict(r) for r in conn.execute('''SELECT r.id,r.attendance_id,r.status,r.reason,r.submitted_at,
                a.date,a.kind,c.nom,c.prenom,c.bts FROM absence_requests r
                JOIN student_attendance a ON a.id=r.attendance_id AND a.candidate_id=r.candidate_id AND a.deleted=0
                JOIN candidats c ON c.id=r.candidate_id ORDER BY r.submitted_at DESC''')]
        counts = {key:sum(r['status']==key for r in rows) for key in STATES}
        return page('admin_absence_requests.html', title='Justificatifs étudiants · Administration',
                    rows=[r for r in rows if status=='all' or r['status']==status], counts=counts, selected_status=status)

    @app.route('/admin/assiduite/justificatifs/<request_id>', methods=['GET','POST'])
    def admin_absence_review(request_id):
        if not require_admin():
            abort(403)
        error = ''
        with closing(connect()) as conn:
            if request.method == 'POST':
                csrf(admin=True,check=True)
                conn.execute('BEGIN IMMEDIATE')
            submission = conn.execute('SELECT * FROM absence_requests WHERE id=?', (request_id,)).fetchone()
            if not submission:
                abort(404)
            submission = dict(submission)
            event = event_for(conn,submission['attendance_id'])
            if event['candidate_id'] != submission['candidate_id']:
                abort(404)
            if request.method == 'POST':
                version_check(request.form.get('version'),submission['version'])
                version_check(request.form.get('event_version'),event['version'])
                if submission['status'] != 'pending':
                    abort(409, 'Cette demande a déjà été traitée.')
                decision, comment = request.form.get('decision',''),request.form.get('comment','').strip()
                if decision not in ('accepted','rejected','needs_info') or len(comment)>3000 or (decision!='accepted' and len(comment)<5):
                    conn.rollback()
                    error='Choisissez une décision. Précisez le motif du refus ou le complément attendu (5 à 3 000 caractères).'
                else:
                    stamp=now_iso()
                    conn.execute('UPDATE absence_requests SET status=?,version=version+1,reviewed_at=?,reviewer_comment=? WHERE id=?', (decision,stamp,comment,request_id))
                    conn.execute('UPDATE student_attendance SET justification=?,version=version+1,updated_at=? WHERE id=?',
                                 ({'accepted':'justified','rejected':'unjustified','needs_info':'pending'}[decision],stamp,event['id']))
                    conn.execute('INSERT INTO absence_history(request_id,action,actor,message,created_at) VALUES(?,?,?,?,?)',
                                 (request_id,STATES[decision],'Équipe pédagogique',comment,stamp))
                    conn.execute('INSERT INTO company_audit(action,target_id,actor,created_at) VALUES(?,?,?,?)', ('absence_review_'+decision,event['id'],'admin',stamp))
                    conn.commit()
                    flash('Décision enregistrée. Le suivi étudiant et entreprise est à jour.', 'success')
                    return private(redirect(url_for('admin_absence_review',request_id=request_id),code=303))
            person=dict(conn.execute('SELECT nom,prenom,bts FROM candidats WHERE id=?', (event['candidate_id'],)).fetchone())
            context=evidence_context(conn,event,submission)
        return page('admin_absence_review.html',title='Examiner un justificatif · Administration',person=person,
                    csrf_token=csrf(admin=True),error=error,**context),400 if error else 200

    @app.get('/espace/absences/documents/<file_id>')
    @app.get('/admin/assiduite/justificatifs/documents/<file_id>')
    def absence_document(file_id):
        admin=request.path.startswith('/admin/')
        identity=None
        if admin:
            if not require_admin():
                abort(403)
        else:
            identity=get_authenticated_student(app,db_connect)
            if not identity:
                abort(403)
        with closing(connect()) as conn:
            row=conn.execute('''SELECT f.*,r.attendance_id,r.candidate_id FROM absence_files f
                JOIN absence_requests r ON r.id=f.request_id WHERE f.id=?''',(file_id,)).fetchone()
            if not row:
                abort(404)
            event=event_for(conn,row['attendance_id'],identity)
            if event['candidate_id']!=row['candidate_id']:
                abort(404)
        root=Path(uploads_dir()).resolve().parent/'absence-justifications'
        path=root/row['storage_name']
        if root.is_symlink() or path.is_symlink() or path.resolve().parent!=root.resolve() or not path.is_file():
            abort(404)
        response=private(send_file(path,mimetype=row['mime'],as_attachment=True,download_name=row['filename']))
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        return response
