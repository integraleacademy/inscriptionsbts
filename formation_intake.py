"""Public applications join the same candidate records and promotion workflow as BTS."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
import re
import secrets
import threading
from uuid import uuid4
from zoneinfo import ZoneInfo

from campaign import campaign_is_open
from flask import abort, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

from candidate_creation import insert_candidate
from promotions import assign_candidate_promotion
from security_intake import PUBLIC_URL, SITUATIONS, SLOTS, TIMELINE, YEAR, today, validate
from training_programs import SECURITY, professional_titles, program_name

STATUS_MAP = {'new': 'preinscription', 'contacted': 'preinscription', 'interview': 'preinscription',
              'accepted': 'validee', 'declined': 'annulee', 'archived': 'annulee'}
STATUS_NAMES = {'new': 'Nouvelle', 'contacted': 'À recontacter', 'interview': 'Entretien prévu',
                'accepted': 'Retenue', 'declined': 'Non retenue', 'archived': 'Archivée'}
TRANSFER_SCOPE = b'parcours-securite-import-v1'


def accepts_title_applications(code):
    return code.casefold() != 'tp agent de sûreté et de sécurité privée'


def open_title_promotions(conn, promotion_id=None):
    # A fresh installation may not have opened the promotions module yet.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='promotions'").fetchone():
        return []
    sql = """SELECT id, nom, bts, rentree_annee, date_debut, date_fin FROM promotions
             WHERE bts GLOB 'TP *' AND active=1 AND needs_setup=0
             AND date_debut IS NOT NULL AND date_fin >= ?"""
    args = [today().isoformat()]
    if promotion_id is not None:
        sql += ' AND id=?'
        args.append(promotion_id)
    rows = conn.execute(sql + ' ORDER BY date_debut, nom, id', args)
    return [row for row in rows if accepts_title_applications(row['bts'])]


def admission_titles(conn):
    offers = {code: dict(code=code, name=name, promotions=[]) for code, name in professional_titles(conn).items()
              if accepts_title_applications(code)}
    for row in open_title_promotions(conn):
        code = row['bts']
        if code not in offers:
            offers[code] = dict(code=code, name=code[3:].capitalize(), promotions=[])
        offers[code]['promotions'].append(row)
    return offers.values()


def ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS formation_submissions (
            candidate_id TEXT PRIMARY KEY, request_key TEXT UNIQUE, dedupe TEXT UNIQUE NOT NULL,
            legacy_ref TEXT UNIQUE, details TEXT NOT NULL, received_at TEXT NOT NULL, created_dossier INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS formation_receipts (
            candidate_id TEXT, recipient TEXT, tries INTEGER NOT NULL DEFAULT 0, retry_at INTEGER NOT NULL DEFAULT 0,
            sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(candidate_id,recipient));
        CREATE TABLE IF NOT EXISTS formation_rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
        CREATE TRIGGER IF NOT EXISTS formation_cleanup AFTER DELETE ON candidats BEGIN
            DELETE FROM formation_submissions WHERE candidate_id=OLD.id;
            DELETE FROM formation_receipts WHERE candidate_id=OLD.id;
        END;
    """)


def register_formation_intake(app, connect, send_mail, require_admin, validate_application, attach_title_dossier,
                              save_application_draft, admissions_available):
    app.extensions['formation_connect'] = connect
    tokens = URLSafeTimedSerializer(app.secret_key, salt='formation-intake-v1')

    def csrf():
        return session.setdefault('formation_csrf', secrets.token_urlsafe(32))

    def credentials(scope):
        return dict(csrf=csrf(), submission_token=tokens.dumps([scope, uuid4().hex]))

    def check_request(data, scope):
        if not isinstance(data, dict) or data.get('website'):
            raise ValueError('Le formulaire est invalide.')
        expected, supplied = session.get('formation_csrf'), data.get('csrf')
        if not expected or not isinstance(supplied, str) or not secrets.compare_digest(expected.encode(), supplied.encode()):
            raise ValueError('Le formulaire a expiré. Recharge la page pour recommencer.')
        try:
            bound_scope, key = tokens.loads(data.get('submission_token') or '', max_age=86400)
            if bound_scope != scope:
                raise ValueError
        except (BadData, TypeError, ValueError):
            raise ValueError('Le formulaire a expiré. Recharge la page pour recommencer.') from None
        return key

    def rate_allowed():
        now = datetime.now(timezone.utc)
        ip = request.remote_addr or 'unknown'
        if request.access_route:
            ip = request.access_route[-1]
        key = hmac.new(app.secret_key.encode(), f'{now.date()}:{ip}'.encode(), sha256).hexdigest()
        with closing(connect()) as conn, conn:
            conn.execute('DELETE FROM formation_rate_limits WHERE expires<?', (int(now.timestamp()),))
            conn.execute('INSERT INTO formation_rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                         (key, int(now.timestamp()) + 86400))
            return conn.execute('SELECT count FROM formation_rate_limits WHERE key=?', (key,)).fetchone()[0] <= 30

    def save(conn, clean, program, year, *, key=None, promotion=None, legacy_ref=None, received_at=None, status='preinscription', notes='', legacy_status=''):
        identity = (program, year, clean['email'], clean['birth_date'], clean['last_name'].casefold(), clean['first_name'].casefold())
        dedupe = sha256(json.dumps(identity).encode()).hexdigest()
        original = conn.execute('SELECT candidate_id,legacy_ref FROM formation_submissions WHERE dedupe=? OR legacy_ref=?',
                                (dedupe, legacy_ref)).fetchone()
        if original:
            if legacy_ref and not original['legacy_ref']:
                conn.execute('UPDATE formation_submissions SET legacy_ref=? WHERE candidate_id=?', (legacy_ref, original['candidate_id']))
                conn.execute('INSERT INTO logs(id,candidat_id,type,payload,created_at) VALUES(?,?,?,?,?)',
                             (uuid4().hex, original['candidate_id'], 'REPRISE_PARCOURS', json.dumps({'reference':legacy_ref, 'statut':legacy_status, 'notes':notes}, ensure_ascii=False), datetime.now().isoformat()))
            return original['candidate_id'], False
        fields = dict(nom=clean['last_name'].upper(), prenom=clean['first_name'], date_naissance=clean['birth_date'],
                      email=clean['email'], tel=clean['phone'], ville=clean.get('city',''), cp=clean.get('postcode',''),
                      bts=program, mode='presentiel', statut=status, rentree_annee=year, projet_pourquoi=clean.get('motivation',''),
                      consent=1, commentaires=notes)
        if program == SECURITY:
            fields['permis_b'] = 1
        matches = [dict(r) for r in conn.execute('SELECT * FROM candidats WHERE bts=? AND rentree_annee=? AND lower(trim(email))=? AND date_naissance=?',
                   (program, year, clean['email'], clean['birth_date']))
                   if (r['nom'] or '').casefold() == clean['last_name'].casefold() and (r['prenom'] or '').casefold() == clean['first_name'].casefold()]
        if len(matches) == 1:
            row = matches[0]
            if conn.execute('SELECT 1 FROM formation_submissions WHERE candidate_id=?', (row['id'],)).fetchone():
                return row['id'], False
            # A pre-existing administrative record keeps its decision, contacts and group.
            conn.execute("UPDATE candidats SET projet_pourquoi=coalesce(nullif(projet_pourquoi,''),?), commentaires=coalesce(nullif(commentaires,''),?) WHERE id=?",
                         (fields['projet_pourquoi'], notes, row['id']))
        else:
            row = insert_candidate(conn, fields, date.fromisoformat(clean['birth_date']), received_at=received_at)
        if promotion and not conn.execute('SELECT 1 FROM student_promotions WHERE candidate_id=?', (row['id'],)).fetchone():
            assign_candidate_promotion(conn, row['id'], promotion['id'])
        details = {k: clean[k] for k in ('available_year','license_b','mobile_departments','privacy_consent','situation','contact_slot','vehicle','privacy_version') if k in clean}
        if legacy_status:
            details['legacy_status'] = STATUS_NAMES[legacy_status]
        conn.execute('INSERT INTO formation_submissions VALUES(?,?,?,?,?,?,?)',
                     (row['id'], key, dedupe, legacy_ref, json.dumps(details, ensure_ascii=False), (received_at or datetime.now()).isoformat(), int(len(matches) != 1)))
        conn.execute('INSERT INTO logs(id,candidat_id,numero_dossier,type,payload,created_at) VALUES(?,?,?,?,?,?)',
                     (uuid4().hex, row['id'], row['numero_dossier'], 'REPRISE_PARCOURS' if legacy_ref else 'CANDIDATURE_RECUE',
                      json.dumps({'formation': program_name(program), 'reference': legacy_ref}, ensure_ascii=False), row['created_at']))
        if not legacy_ref:
            conn.executemany('INSERT INTO formation_receipts(candidate_id,recipient) VALUES(?,?)',
                             [(row['id'], 'candidate'), (row['id'], 'staff')])
        return row['id'], True

    def deliver(cid, recipient):
        now = int(datetime.now(timezone.utc).timestamp())
        with closing(connect()) as conn, conn:
            claimed = conn.execute('UPDATE formation_receipts SET tries=tries+1,retry_at=? WHERE candidate_id=? AND recipient=? AND sent=0 AND tries<5 AND retry_at<=?',
                (now+300,cid,recipient,now)).rowcount
            if not claimed:
                return
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not row:
            return
        staff = recipient == 'staff'
        subject = 'Nouvelle candidature · ' + program_name(row['bts']) if staff else 'Ta candidature est bien reçue · Intégrale Academy'
        content = app.jinja_env.get_template('formation_receipt.html').render(row=dict(row), staff=staff,
                    program=program_name(row['bts']), security=row['bts']==SECURITY, public_url=PUBLIC_URL,
                    admin_url='https://inscriptionsbts.onrender.com/admin/candidat/'+cid)
        sent = send_mail('clement@integraleacademy.com' if staff else row['email'], subject, content,
                         copy_admin=False, reply_to=row['email'] if staff else 'aurelie@integraleacademy.com')
        if sent:
            with closing(connect()) as conn, conn:
                conn.execute('UPDATE formation_receipts SET sent=1 WHERE candidate_id=? AND recipient=?', (cid,recipient))

    def receipt(conn, cid):
        row = conn.execute("""SELECT c.numero_dossier,r.sent FROM candidats c LEFT JOIN formation_receipts r
                           ON r.candidate_id=c.id AND r.recipient='candidate' WHERE c.id=?""", (cid,)).fetchone()
        return dict(ok=True, reference=row['numero_dossier'], email_sent=bool(row['sent']))

    def store_public(clean, key, program, year, promotion=None, dossier_form=None):
        written = []
        try:
            with closing(connect()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                if promotion:
                    promotion = active_title_promotion(conn, promotion['id'])
                    if (promotion['bts'], promotion['rentree_annee']) != (program, year):
                        raise ValueError('La session a changé. Recharge la page pour vérifier la formation.')
                previous = conn.execute('SELECT candidate_id FROM formation_submissions WHERE request_key=?', (key,)).fetchone()
                if previous:
                    return receipt(conn, previous[0]), 200
                cid, inserted = save(conn, clean, program, year, key=key, promotion=promotion)
                if inserted and dossier_form is not None:
                    attach_title_dossier(conn, cid, dossier_form, written)
        except Exception:
            for path in written:
                if os.path.exists(path):
                    os.unlink(path)
            raise
        if not inserted:
            return dict(ok=True, reference='', already_received=True), 200
        for recipient in ('candidate','staff'):
            try:
                deliver(cid, recipient)
            except Exception:
                app.logger.exception('Formation receipt pending for %s (%s)', cid, recipient)
        with closing(connect()) as conn:
            return receipt(conn, cid), 201

    def security_form(preview=False):
        return render_template('parcours_alternance/application.html', preview=preview, timeline=TIMELINE,
                               situations=SITUATIONS, slots=SLOTS, public_url=PUBLIC_URL, server_date=today().isoformat(),
                               **({} if preview else credentials(SECURITY)))

    @app.get('/parcoursalternance/candidature/apercu')
    def security_application_preview():
        if not require_admin():
            return redirect(url_for('login', next=request.path))
        return security_form(preview=True)

    @app.route('/parcoursalternance/candidature', methods=['GET','POST'])
    def security_application():
        if request.method == 'GET':
            return security_form()
        if request.content_length and request.content_length > 20000:
            return jsonify(ok=False, error='Le formulaire est trop volumineux.'), 413
        data = request.get_json(silent=True)
        try:
            key = check_request(data, SECURITY)
            if not rate_allowed():
                return jsonify(ok=False, error='Trop de tentatives. Réessaie plus tard.'), 429
            return store_public(validate(data), key, SECURITY, YEAR)
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400

    def active_title_promotion(conn, pid):
        rows = open_title_promotions(conn, pid)
        if not rows:
            if request.method == 'POST':
                abort(app.make_response((jsonify(ok=False, success=False, error='Cette session n’est plus ouverte aux candidatures.'), 404)))
            abort(404)
        return rows[0]

    def title_intake_notice():
        return ('Les candidatures pour les titres professionnels ouvrent le 1er décembre 2026 à 10 h.'
                if not campaign_is_open() else 'Les candidatures pour les titres professionnels sont momentanément fermées.')

    def title_form(code=None, promotion=None, *, preview=False, saved_data=None):
        with closing(connect()) as conn:
            offers = list(admission_titles(conn))
        labels = {offer['code']: offer['name'] for offer in offers}
        if code is not None and code not in labels:
            abort(404)
        intake_open = admissions_available()
        if saved_data is not None:
            saved_data = dict(saved_data, mode='presentiel')
            saved_data.pop('cherche_idf', None)
        session_tokens = {} if preview or not intake_open else {
            group['id']: credentials(group['id'])['submission_token']
            for offer in offers for group in offer['promotions']
        }
        return render_template('index.html', title='Choisir un titre professionnel · Intégrale Academy',
                               title_offers=offers, title_code=code, title_label=labels.get(code), promotion=promotion,
                               preview=preview, saved_data=saved_data, csrf=None if preview else csrf(),
                               session_tokens=session_tokens, intake_open=intake_open, intake_notice=title_intake_notice(),
                               submission_token=session_tokens.get(promotion['id']) if promotion else None)

    @app.get('/titres-professionnels/apercu')
    def title_application_preview():
        if not require_admin():
            return redirect(url_for('login', next=request.full_path))
        code = request.args.get('formation', '')
        pid = request.args.get('promotion')
        with closing(connect()) as conn:
            promotion = active_title_promotion(conn, pid) if pid else None
        if promotion and promotion['bts'] != code:
            abort(404)
        return title_form(code, promotion, preview=True)

    @app.route('/titres-professionnels/candidature/<promotion_id>', methods=['GET','POST'])
    def title_application(promotion_id):
        with closing(connect()) as conn:
            promotion = active_title_promotion(conn, promotion_id)
        if request.method == 'GET':
            return title_form(promotion['bts'], promotion)
        if not admissions_available():
            return jsonify(ok=False, error=title_intake_notice()), 403
        form = request.form
        if form.get('admin_preview') == '1':
            return jsonify(ok=False, error='Cet aperçu ne permet pas de déposer un dossier.'), 403
        try:
            key = check_request(form.to_dict(), promotion_id)
            if not rate_allowed():
                return jsonify(ok=False, error='Trop de tentatives. Réessaie plus tard.'), 429
            error = validate_application(form, request.files, title_code=promotion['bts'])
            if error:
                raise ValueError(error)
            clean = dict(last_name=' '.join(form['nom'].split()).upper(), first_name=' '.join(form['prenom'].split()).title(),
                         email=form['email'].strip().lower(), phone=form['tel'], birth_date=form['date_naissance'],
                         motivation=form['projet_pourquoi'], privacy_consent=True)
            store_public(clean, key, promotion['bts'], promotion['rentree_annee'], promotion, form)
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400
        # Identity matches across independent submissions must not reveal a private dossier link.
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=True, redirect=url_for('candidate_login'))
        return redirect(url_for('title_application_received'), code=303)

    @app.post('/titres-professionnels/candidature/<promotion_id>/brouillon')
    def title_application_draft(promotion_id):
        if not admissions_available():
            return jsonify(success=False, error=title_intake_notice()), 403
        with closing(connect()) as conn:
            promotion = active_title_promotion(conn, promotion_id)
        data = request.get_json(silent=True) or {}
        form = data.get('full_form') if isinstance(data, dict) else None
        try:
            check_request(form, promotion_id)
            if form.get('bts') != promotion['bts']:
                raise ValueError('Le titre doit correspondre à la session choisie.')
        except ValueError as error:
            return jsonify(success=False, error=str(error)), 400
        draft = dict(form, title_promotion_id=promotion_id, mode='presentiel')
        draft.pop('cherche_idf', None)
        return save_application_draft(draft, promotion['rentree_annee'])

    @app.get('/titres-professionnels/candidature-recue')
    def title_application_received():
        return render_template('title_application.html', received=True)

    @app.post('/api/admissions/reprise-parcours-securite')
    def import_security_application():
        secret = os.getenv('BTS_IMPORT_API_KEY', '').strip()
        if len(secret) < 32:
            abort(503)
        signature = request.headers.get('X-Parcours-Signature', '')
        if request.content_length is None or request.content_length > 24000:
            abort(413)
        body = request.get_data()
        transfer_key = hmac.digest(secret.encode(), TRANSFER_SCOPE, 'sha256')
        if not hmac.compare_digest(signature.encode(), hmac.new(transfer_key, body, sha256).hexdigest().encode()):
            abort(401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not re.fullmatch(r'ALT-[A-F0-9]{12}', str(data.get('id',''))) or data.get('status') not in STATUS_MAP:
            abort(400)
        try:
            received = datetime.fromisoformat(data['created_at']).astimezone(timezone.utc)
            if not datetime.now(timezone.utc)-timedelta(days=365) <= received <= datetime.now(timezone.utc)+timedelta(minutes=5):
                abort(400)
            clean = validate(data['payload'], day=received.astimezone(ZoneInfo('Europe/Paris')).date(), imported=True)
        except (KeyError, ValueError, TypeError):
            abort(400)
        with closing(connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            cid, _ = save(conn, clean, SECURITY, YEAR, legacy_ref=data['id'], received_at=received,
                          status=STATUS_MAP[data['status']], notes=str(data.get('notes') or '')[:5000], legacy_status=data['status'])
        return jsonify(ok=True, candidate_id=cid)

    @app.after_request
    def private_formation_response(response):
        if request.endpoint in ('security_application','security_application_preview','title_application','title_application_draft','title_application_preview','title_application_received','import_security_application'):
            response.headers.update({'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','X-Content-Type-Options':'nosniff'})
        if request.endpoint in ('security_application','security_application_preview'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'"
        return response

    def maintain():
        while True:
            try:
                now = datetime.now(timezone.utc)
                with app.app_context(), closing(connect()) as conn, conn:
                    expired = (now-timedelta(days=365)).isoformat()
                    # Enrollment has its own retention policy. Remove abandoned intake dossiers and their intake metadata.
                    conn.execute("""DELETE FROM candidats WHERE statut IN ('preinscription','validee','annulee','docs_non_conformes')
                        AND bts='PARCOURS-SECURITE' AND id IN (SELECT candidate_id FROM formation_submissions WHERE received_at<? AND created_dossier=1)
                        AND coalesce(date_confirmee,'')='' AND NOT EXISTS (SELECT 1 FROM student_promotions WHERE candidate_id=candidats.id)""", (expired,))
                    conn.execute('DELETE FROM formation_submissions WHERE received_at<?', (expired,))
                    conn.execute('DELETE FROM formation_rate_limits WHERE expires<?', (int(now.timestamp()),))
                    due = conn.execute('SELECT candidate_id,recipient FROM formation_receipts WHERE sent=0 AND tries<5 AND retry_at<=? LIMIT 10',
                                       (int(now.timestamp()),)).fetchall()
                for cid, recipient in due:
                    with app.app_context():
                        deliver(cid, recipient)
            except Exception:
                app.logger.exception('Formation intake maintenance failed')
            threading.Event().wait(300)

    worker_lock = threading.Lock()

    @app.before_request
    def start_formation_maintenance():
        if app.testing or os.getenv('FORMATION_MAINTENANCE_DISABLED')=='1' or app.extensions.get('formation_maintenance'):
            return
        with worker_lock:
            if not app.extensions.get('formation_maintenance'):
                thread = threading.Thread(target=maintain, name='formation-intake', daemon=True)
                app.extensions['formation_maintenance'] = thread
                thread.start()

    return title_form
