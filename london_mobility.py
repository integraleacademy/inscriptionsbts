"""Candidate-owned London conventions, revisions and manually signed copies."""
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
from zoneinfo import ZoneInfo

from flask import abort, flash, jsonify, redirect, request, send_file, session, url_for
from candidate_messages import _equal
from london_mobility_documents import VERSION, minor_at_signing, pdf_document, word_document
from london_mobility_signatures import active_signature, register_signatures, signature_context, signature_schema

FIELDS = (
    ('convention_date', 'Date de la convention', 'date'),
    ('mobility_start', 'Début du séjour', 'date'),
    ('mobility_end', 'Fin du séjour', 'date'),
    ('mobility_cost', 'Budget prévisionnel de mobilité (€)', 'text'),
    ('employer_name', 'Raison sociale', 'text'),
    ('employer_siret', 'SIRET', 'text'),
    ('employer_address', 'Adresse de l’entreprise', 'text'),
    ('employer_postcode', 'Code postal', 'text'),
    ('employer_city', 'Ville', 'text'),
    ('guardian_first_name', 'Prénom du représentant légal', 'text'),
    ('guardian_last_name', 'Nom du représentant légal', 'text'),
)
EMPLOYER_FIELDS = [name for name, _, _ in FIELDS if name.startswith('employer_')]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def schema(conn):
    signature_schema(conn)
    # Idempotent also for restored databases that predate the voyage module.
    for sql in (
        """CREATE TABLE IF NOT EXISTS voyage_londres_inscriptions (
        id TEXT PRIMARY KEY, candidat_id TEXT NOT NULL UNIQUE,
        statut TEXT NOT NULL DEFAULT 'active' CHECK(statut IN ('active','annulee')),
        convention TEXT NOT NULL DEFAULT 'À faire', opco INTEGER NOT NULL DEFAULT 0,
        billet INTEGER NOT NULL DEFAULT 0, hebergement INTEGER NOT NULL DEFAULT 0,
        passeport INTEGER NOT NULL DEFAULT 0, numero_passeport TEXT,
        passeport_delivrance TEXT, passeport_expiration TEXT, immigration INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT,
        FOREIGN KEY(candidat_id) REFERENCES candidats(id) ON DELETE RESTRICT)""",
        """CREATE TABLE IF NOT EXISTS voyage_londres_documents (
        id TEXT PRIMARY KEY, inscription_id TEXT NOT NULL, categorie TEXT NOT NULL,
        nom_original TEXT NOT NULL, nom_stockage TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL,
        taille INTEGER NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(inscription_id) REFERENCES voyage_londres_inscriptions(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS london_mobility_settings (
        candidate_id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL,
        updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS london_mobility_versions (
        id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, snapshot TEXT NOT NULL,
        fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, pdf_id TEXT NOT NULL,
        docx_id TEXT NOT NULL, pdf_hash TEXT NOT NULL, docx_hash TEXT NOT NULL,
        signed_id TEXT, signed_hash TEXT, signed_at TEXT)""",
        'CREATE INDEX IF NOT EXISTS london_mobility_candidate ON london_mobility_versions(candidate_id,created_at)',
    ):
        conn.execute(sql)


def contracts(conn, cid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='student_wedof_contracts'").fetchone(): return []
    result = []
    for row in conn.execute('SELECT contract_id,payload FROM student_wedof_contracts WHERE candidate_id=? ORDER BY linked_at DESC', (cid,)):
        item = json.loads(row['payload'])
        if item.get('state') not in {'cancelled', 'broken', 'refused'}:
            result.append({'id': row['contract_id'], **{k: v for k, v in item.items() if k != 'id'}})
    return result


def source_values(conn, row, contract_id=''):
    linked = contracts(conn, row['id'])
    selected = next((c for c in linked if c['id'] == contract_id), None)
    if contract_id and selected is None:
        raise ValueError('Ce contrat n’est pas rattaché à ce candidat ou n’est plus actif.')
    values = {k: '' for k in EMPLOYER_FIELDS}
    # A linked company is useful even before an OPCO contract is available.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'companies', 'company_students'} <= tables:
        company = conn.execute('''SELECT e.name,e.siret FROM companies e JOIN company_students s ON e.id=s.company_id
            WHERE s.candidate_id=?''', (row['id'],)).fetchone()
        if company: values.update(employer_name=company['name'], employer_siret=company['siret'])
    if selected:
        values.update({k: selected.get(k) or values[k] for k in EMPLOYER_FIELDS})
    values.update(guardian_first_name=row.get('resp_prenom') or '', guardian_last_name=row.get('resp_nom') or '')
    return values, selected


def current_settings(conn, row):
    stored = conn.execute('SELECT * FROM london_mobility_settings WHERE candidate_id=?', (row['id'],)).fetchone()
    saved = json.loads(stored['payload']) if stored else {}
    linked = contracts(conn, row['id'])
    chosen = saved.get('contract_id', linked[0]['id'] if len(linked) == 1 else '')
    warning = ''
    try:
        values, selected = source_values(conn, row, chosen)
    except ValueError as error:
        values, selected = source_values(conn, row)
        chosen, warning = '', str(error)
    values.update(convention_date=datetime.now(ZoneInfo('Europe/Paris')).date().isoformat(),
                  mobility_start='2027-11-08', mobility_end='2027-11-12', mobility_cost='1500.00', contract_id=chosen)
    values.update(saved)
    # A formerly attached contract must never be used silently.
    values['contract_id'] = chosen
    return values, stored['revision'] if stored else 0, linked, selected, warning


def snapshot(row, values, selected):
    return {**values, 'version': VERSION, 'candidate_id': row['id'],
            'apprentice_first_name': row.get('prenom') or '', 'apprentice_last_name': row.get('nom') or '',
            'apprentice_birth_date': row.get('date_naissance') or '', 'apprentice_sex': row.get('sexe') or '',
            'mode': row.get('mode'), 'training_start': (selected or {}).get('training_start') or '',
            'training_end': (selected or {}).get('training_end') or ''}


def source_fingerprint(conn, row):
    values, _ = source_values(conn, row)
    identity = {k: row.get(k) for k in ('id','prenom','nom','mode','date_naissance','sexe','resp_nom','resp_prenom','email','resp_email')}
    return digest({'candidate': identity, 'contracts': contracts(conn, row['id']), 'company': values})


def validate(raw, row, selected, complete=False):
    values = {}
    for key, label, kind in FIELDS:
        value = str(raw.get(key) or '').strip()
        if len(value) > (200 if key == 'employer_address' else 140): raise ValueError(f'Le champ « {label} » est trop long.')
        if value and kind == 'date':
            try: date.fromisoformat(value)
            except ValueError: raise ValueError(f'Vérifiez la date « {label} ».') from None
        values[key] = value
    values['contract_id'] = str(raw.get('contract_id') or '')
    values['employer_siret'] = re.sub(r'\s', '', values['employer_siret'])
    if values['employer_siret'] and not re.fullmatch(r'\d{14}', values['employer_siret']):
        raise ValueError('Le SIRET doit comporter 14 chiffres.')
    if values['mobility_cost']:
        try:
            amount = Decimal(values['mobility_cost'].replace(' ', '').replace(',', '.'))
            if not amount.is_finite() or amount < 0 or amount > 100000 or amount.as_tuple().exponent < -2: raise InvalidOperation
            values['mobility_cost'] = format(amount, '.2f')
        except InvalidOperation: raise ValueError('Renseignez un budget valide, avec deux décimales au maximum.') from None
    start, end = values['mobility_start'], values['mobility_end']
    if start and end and not 1 <= (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 <= 28:
        raise ValueError('La convention doit couvrir entre 1 et 28 jours, dans l’ordre chronologique.')
    training = selected or {}
    if start and training.get('training_start') and start < training['training_start']:
        raise ValueError('Le séjour doit commencer pendant la formation du contrat sélectionné.')
    if end and training.get('training_end') and end > training['training_end']:
        raise ValueError('Le séjour doit se terminer pendant la formation du contrat sélectionné.')
    if complete:
        required = {k: label for k, label, _ in FIELDS if not k.startswith('guardian_')}
        missing = [label for k, label in required.items() if not values[k]]
        if not row.get('nom') or not row.get('prenom'): missing.append('identité du candidat dans Informations')
        try:
            born = date.fromisoformat(row.get('date_naissance') or '')
            if born > date.fromisoformat(values['convention_date']): raise ValueError
        except ValueError: missing.append('date de naissance du candidat dans Informations')
        if missing: raise ValueError('À compléter : ' + ', '.join(missing) + '.')
        data = snapshot(row, values, selected)
        if minor_at_signing(data) and (not values['guardian_first_name'] or not values['guardian_last_name']):
            raise ValueError('Renseignez le prénom et le nom du représentant légal de l’apprenti mineur.')
    return values


def london_context(conn, row):
    schema(conn)
    values, revision, linked, selected, warning = current_settings(conn, row)
    versions = [dict(r) for r in conn.execute('SELECT * FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC', (row['id'],))]
    current_hash = digest(snapshot(row, values, selected))
    for item in versions:
        data = json.loads(item.pop('snapshot'))
        item.update(mobility_start=data['mobility_start'], mobility_end=data['mobility_end'],
                    stale=item['fingerprint'] != current_hash, signing_snapshot=data)
    signing = signature_context(conn, row, versions)
    return dict(values=values, revision=revision, fields=FIELDS, contracts=linked, versions=versions,
                source_fingerprint=source_fingerprint(conn, row), warning=warning, signing=signing)


def has_mobility_archive(conn, *, candidate_id=None, document_id=None):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='london_mobility_versions'").fetchone():
        return False
    if document_id is not None:
        return bool(conn.execute('SELECT 1 FROM london_mobility_versions WHERE pdf_id=? OR docx_id=? OR signed_id=? LIMIT 1',
                                 (document_id, document_id, document_id)).fetchone())
    return bool(conn.execute('SELECT 1 FROM london_mobility_versions WHERE candidate_id=? LIMIT 1', (candidate_id,)).fetchone())


def register_london_mobility(app, connect, directory, require_admin, log_event):
    def guard(write=False):
        if not require_admin(): abort(403)
        if write and not _equal(request.form.get('csrf_token'), session.get('_campus_csrf')):
            abort(400, 'La page a expiré. Rechargez-la.')

    def answer(cid, message, status=200):
        target = url_for('admin_candidate_sheet', cid=cid) + '#londres'
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=status == 200, message=message, error=message if status != 200 else None, redirect_url=target), status
        flash(message, 'success' if status == 200 else 'error')
        return redirect(target, code=303)

    def candidate(conn, cid, write=False):
        found = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not found: abort(404)
        row = dict(found)
        if write and row.get('mode') != 'presentiel':
            raise ValueError('La convention de mobilité est réservée au présentiel.')
        return row

    def store_file(conn, iid, content, extension, category, label, created, paths):
        root = Path(directory()); root.mkdir(parents=True, exist_ok=True)
        did = secrets.token_hex(16)
        storage = did + '.' + extension
        path = root / storage
        with path.open('xb') as handle: handle.write(content)
        path.chmod(0o600); paths.append(path)
        mime = 'application/pdf' if extension == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        conn.execute('INSERT INTO voyage_londres_documents VALUES(?,?,?,?,?,?,?,?)',
                     (did, iid, category, label + '.' + extension, storage, mime, len(content), created))
        return did, hashlib.sha256(content).hexdigest()

    @app.post('/admin/candidat/<cid>/londres/convention')
    def london_mobility_save(cid):
        guard(True)
        paths = []
        try:
            with closing(connect()) as conn:
                schema(conn); conn.commit(); conn.execute('BEGIN IMMEDIATE')
                row = candidate(conn, cid, True)
                saved, revision, _, _, _ = current_settings(conn, row)
                if request.form.get('revision') != str(revision) or request.form.get('source_fingerprint') != source_fingerprint(conn, row):
                    return answer(cid, 'La fiche ou la convention a changé. Rechargez-la avant de continuer.', 409)
                action = request.form.get('action', 'save')
                if action not in {'save', 'generate', 'prefill'}: abort(400)
                if action == 'generate' and active_signature(conn, cid):
                    raise ValueError('Une signature électronique est en cours. Annulez cette demande avant de générer une autre convention.')
                prefills, selected = source_values(conn, row, request.form.get('contract_id', ''))
                raw = dict(request.form)
                if action == 'prefill': raw.update(prefills)
                values = validate(raw, row, selected, complete=action == 'generate')
                trip = conn.execute('SELECT * FROM voyage_londres_inscriptions WHERE candidat_id=?', (cid,)).fetchone()
                if action == 'generate' and trip and trip['statut'] != 'active':
                    raise ValueError('L’inscription au voyage est annulée. Réactivez-la avant de générer une convention.')
                created = stamp()
                data = snapshot(row, values, selected)
                pdf = word = None
                latest = conn.execute('SELECT fingerprint FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1', (cid,)).fetchone()
                generate = action == 'generate' and (not latest or latest['fingerprint'] != digest(data))
                if generate:
                    pdf, word = pdf_document(data), word_document(data)
                conn.execute('''INSERT INTO london_mobility_settings VALUES(?,?,?,?) ON CONFLICT(candidate_id)
                    DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated_at=excluded.updated_at''',
                             (cid, encoded(values), revision + 1, created))
                if generate:
                    iid = trip['id'] if trip else secrets.token_hex(16)
                    if not trip:
                        conn.execute('INSERT INTO voyage_londres_inscriptions(id,candidat_id,created_at,updated_at) VALUES(?,?,?,?)', (iid,cid,created,created))
                    vid = secrets.token_hex(16)
                    pdf_id, pdf_hash = store_file(conn, iid, pdf, 'pdf', 'Convention de mobilité', 'Convention_mobilite_Londres_' + created[:10], created, paths)
                    docx_id, docx_hash = store_file(conn, iid, word, 'docx', 'Convention de mobilité', 'Convention_mobilite_Londres_' + created[:10], created, paths)
                    conn.execute('''INSERT INTO london_mobility_versions(id,candidate_id,snapshot,fingerprint,created_at,pdf_id,docx_id,pdf_hash,docx_hash)
                        VALUES(?,?,?,?,?,?,?,?,?)''', (vid,cid,encoded(data),digest(data),created,pdf_id,docx_id,pdf_hash,docx_hash))
                    conn.execute("UPDATE voyage_londres_inscriptions SET convention='Éditée',updated_at=? WHERE candidat_id=?", (created,cid))
                conn.commit()
            paths.clear()
            if generate:
                log_event(row, 'Convention mobilité Londres générée', {'version_id': vid, 'debut': values['mobility_start'], 'fin': values['mobility_end']})
            message = ('Convention générée et conservée dans ce dossier.' if generate else
                       'Cette version existe déjà : elle reste disponible ci-dessous.' if action == 'generate' else
                       'Informations préremplies depuis le contrat sélectionné.' if action == 'prefill' else 'Paramètres de la convention enregistrés.')
            return answer(cid, message)
        except ValueError as error:
            return answer(cid, str(error), 400)
        except (OSError, RuntimeError):
            app.logger.exception('London mobility generation failed')
            return answer(cid, 'La convention n’a pas pu être générée. Aucun document précédent n’a été modifié.', 503)
        finally:
            for path in paths: path.unlink(missing_ok=True)

    @app.get('/admin/candidat/<cid>/londres/conventions/<vid>/<kind>')
    def london_mobility_download(cid, vid, kind):
        guard()
        if kind not in {'pdf', 'docx', 'signed'}: abort(404)
        with closing(connect()) as conn:
            schema(conn); candidate(conn, cid)
            version = conn.execute('SELECT * FROM london_mobility_versions WHERE id=? AND candidate_id=?', (vid,cid)).fetchone()
            if not version or not version[kind + '_id']: abort(404)
            document = conn.execute('SELECT * FROM voyage_londres_documents WHERE id=?', (version[kind + '_id'],)).fetchone()
            if not document: abort(404)
        path = Path(directory()) / document['nom_stockage']
        if path.name != document['nom_stockage'] or not path.is_file(): abort(404)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != version[kind + '_hash']: abort(409, 'Le document enregistré a changé.')
        response = send_file(BytesIO(content), mimetype=document['mime_type'], download_name=document['nom_original'],
                             as_attachment=kind == 'docx' or request.args.get('download') == '1')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.post('/admin/candidat/<cid>/londres/conventions/<vid>/signee')
    def london_mobility_upload_signed(cid, vid):
        guard(True)
        paths = []
        try:
            upload = request.files.get('document')
            if not upload or request.form.get('signed_confirmed') != 'yes':
                raise ValueError('Ajoutez le PDF signé et confirmez la présence des signatures.')
            content = upload.stream.read(15 * 1024 * 1024 + 1)
            if len(content) > 15 * 1024 * 1024 or not content.startswith(b'%PDF-'):
                raise ValueError('Ajoutez un fichier PDF de 15 Mo maximum.')
            from pypdf import PdfReader
            try:
                reader = PdfReader(BytesIO(content))
                if reader.is_encrypted or not 1 <= len(reader.pages) <= 60: raise ValueError
            except Exception: raise ValueError('Le fichier PDF est illisible ou protégé par un mot de passe.') from None
            with closing(connect()) as conn:
                schema(conn); conn.commit(); conn.execute('BEGIN IMMEDIATE')
                candidate(conn, cid, True)
                version = conn.execute('SELECT * FROM london_mobility_versions WHERE id=? AND candidate_id=?', (vid,cid)).fetchone()
                if not version: abort(404)
                if active_signature(conn, cid):
                    raise ValueError('Une signature électronique est en cours. Actualisez son suivi ou annulez-la avant de déposer une copie signée.')
                if version['signed_id']: return answer(cid, 'Une copie signée est déjà conservée pour cette version.', 409)
                trip = conn.execute('SELECT * FROM voyage_londres_inscriptions WHERE candidat_id=?', (cid,)).fetchone()
                if not trip or trip['statut'] != 'active': raise ValueError('L’inscription au voyage doit être active.')
                created = stamp()
                did, sha = store_file(conn, trip['id'], content, 'pdf', 'Convention signée', 'Convention_mobilite_Londres_signee_' + created[:10], created, paths)
                conn.execute('UPDATE london_mobility_versions SET signed_id=?,signed_hash=?,signed_at=? WHERE id=?', (did,sha,created,vid))
                latest = conn.execute('SELECT id FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1', (cid,)).fetchone()
                if latest['id'] == vid:
                    conn.execute("UPDATE voyage_londres_inscriptions SET convention=CASE WHEN convention='Transmise OPCO' THEN convention ELSE 'Signée' END,updated_at=? WHERE candidat_id=?", (created,cid))
                conn.commit()
            paths.clear()
            log_event(cid, 'Convention mobilité Londres signée déposée', {'version_id': vid})
            return answer(cid, 'Convention signée déposée et conservée dans ce dossier.')
        except ValueError as error:
            return answer(cid, str(error), 400)
        finally:
            for path in paths: path.unlink(missing_ok=True)

    register_signatures(app, connect, directory, guard, answer, store_file, log_event)
