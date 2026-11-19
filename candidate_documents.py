"""Private dossier documents and browser previews without automatic downloads."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import base64
import json
import os
import re
import zipfile

from flask import abort, jsonify, make_response, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from werkzeug.utils import secure_filename

from candidate_messages import _equal

DOC_FIELDS = {
    "ci": ("fichiers_ci", "🪪 Carte d’identité / Passeport"),
    "photo": ("fichiers_photo", "📸 Photo d’identité"),
    "carte_vitale": ("fichiers_carte_vitale", "💳 Carte Vitale"),
    "cv": ("fichiers_cv", "📄 CV"),
    "lm": ("fichiers_lm", "🖋️ Lettre de motivation"),
    "autre": ("fichiers_autres", "📎 Autre document"),
}
DOCUMENT_FIELDS = tuple(column for column, _ in DOC_FIELDS.values())
DOCUMENT_LIMIT = 8 * 1024 * 1024
ADMIN_DOCUMENT_NAME = re.compile(r'^Depot-(?:ci|carte_vitale|cv|lm|autre)-[0-9a-f]{32}-(.+)$')


def document_name(filename):
    match = ADMIN_DOCUMENT_NAME.fullmatch(filename)
    return match.group(1) if match else filename


def _stage_upload(upload, kind, staging):
    name = secure_filename(upload.filename)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    allowed = {'.pdf', '.jpg', '.jpeg', '.png'}
    if kind in ('cv', 'lm', 'autre'):
        allowed.add('.docx')
    if ext not in allowed:
        raise ValueError('Format non accepté pour cette catégorie de document.')
    content = upload.stream.read(DOCUMENT_LIMIT + 1)
    if not content or len(content) > DOCUMENT_LIMIT:
        raise ValueError('Chaque fichier doit être non vide et peser au maximum 8 Mo.')
    if ext == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise ValueError('Le fichier sélectionné n’est pas un PDF lisible.')
    elif ext == '.docx':
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if (len(entries) > 2000 or sum(item.file_size for item in entries) > 60 * 1024 * 1024
                        or not {'word/document.xml', '[Content_Types].xml'} <= set(archive.namelist())):
                    raise ValueError
        except (zipfile.BadZipFile, ValueError):
            raise ValueError('Le document Word est illisible ou trop volumineux.') from None
    else:
        try:
            with Image.open(BytesIO(content)) as picture:
                expected = 'PNG' if ext == '.png' else 'JPEG'
                if picture.format != expected or picture.width * picture.height > 40_000_000:
                    raise ValueError
                picture.verify()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            raise ValueError('Choisissez une image JPG ou PNG lisible de 40 mégapixels maximum.') from None

    digest = sha256(content).hexdigest()[:32]
    path = staging / f'Depot-{kind}-{digest}-{stem[:120]}{ext}'
    path.write_bytes(content)
    return path


def _attach_uploads(conn, cid, folder, kind, staged):
    column, label = DOC_FIELDS[kind]
    conn.execute('BEGIN IMMEDIATE')
    row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
    if row is None or folder.resolve() != folder:
        abort(404)
    row = dict(row)
    paths = json.loads(row.get(column) or '[]')
    if not isinstance(paths, list):
        raise ValueError('La liste des pièces de ce dossier est illisible.')
    names = {os.path.basename(path) for path in paths if isinstance(path, str)}
    checks = load_verif_docs(row)
    stored = []
    added = []
    try:
        for source in staged:
            target = folder / source.name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                abort(404)
            if not target.exists():
                source.replace(target)
                stored.append(target)
            if target.name in names:
                continue
            paths.append(str(target))
            names.add(target.name)
            checks[target.name] = {'etat': 'en_attente', 'label': label}
            added.append(document_name(target.name))
        if added:
            now = datetime.now().isoformat()
            conn.execute(f'UPDATE candidats SET {column}=?, verif_docs=?, updated_at=? WHERE id=?',
                         (json.dumps(paths), json.dumps(checks, ensure_ascii=False), now, cid))
            conn.execute('INSERT INTO logs (id,candidat_id,numero_dossier,type,payload,created_at) VALUES (?,?,?,?,?,?)',
                         (uuid4().hex, cid, row.get('numero_dossier'), 'DOCUMENTS_AJOUTES',
                          json.dumps({'pièces': ', '.join(added)}, ensure_ascii=False), now))
        conn.commit()
    except Exception:
        for path in stored:
            path.unlink(missing_ok=True)
        raise
    return len(added)


def load_verif_docs(row):
    try:
        checks = json.loads(row.get('verif_docs') or '{}')
    except (TypeError, ValueError):
        return {}
    return checks if isinstance(checks, dict) else {}


def _private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _inside(directory, path):
    return os.path.commonpath((directory, path)) == directory and path != directory


def _resolve_document(row, filename, upload_dir):
    if filename != os.path.basename(filename) or filename in ('.', '..') or '\\' in filename:
        abort(404)
    root = os.path.realpath(upload_dir)
    directory = os.path.realpath(os.path.join(root, row['id']))
    if directory != os.path.abspath(os.path.join(root, row['id'])) or not _inside(root, directory):
        abort(404)
    path = os.path.realpath(os.path.join(directory, filename))
    if _inside(directory, path) and os.path.isfile(path):
        return path
    # Historical flat uploads are accepted only when this dossier explicitly
    # lists the filename and its deterministic name contains this exact ID.
    names = set()
    for field in DOCUMENT_FIELDS:
        try:
            entries = json.loads(row.get(field) or '[]')
            if isinstance(entries, list):
                names.update(os.path.basename(item) for item in entries if isinstance(item, str))
        except (TypeError, ValueError):
            pass
    owns_flat_name = re.fullmatch(
        r'(?:CI|Photo|PhotoIdentite|CarteVitale|CV|LettreMotivation)_' + re.escape(row['id']) + r'(?:_\d+)?\.[A-Za-z0-9]+',
        filename, re.IGNORECASE,
    )
    legacy_path = os.path.realpath(os.path.join(root, filename))
    if filename in names and owns_flat_name and os.path.dirname(legacy_path) == root and os.path.isfile(legacy_path):
        return legacy_path
    abort(404)


def _image_content(path):
    try:
        with Image.open(path) as source:
            fmt = source.format
            source.verify()
        mime = {'JPEG': 'image/jpeg', 'MPO': 'image/jpeg', 'PNG': 'image/png', 'GIF': 'image/gif', 'WEBP': 'image/webp', 'BMP': 'image/bmp'}.get(fmt)
        if mime:
            return path, mime
        if fmt == 'TIFF':
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((2400, 2400))
                out = BytesIO()
                image.convert('RGB').save(out, format='JPEG', quality=92)
                out.seek(0)
            return out, 'image/jpeg'
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        pass
    return None


def _docx_blocks(path):
    """Extract readable text, tables and embedded raster pictures; never HTML."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(item.file_size for item in entries) > 60 * 1024 * 1024:
            raise ValueError('Document trop volumineux pour son aperçu.')
    doc = Document(path)
    blocks = []
    seen_images = set()

    def extract(element, parent):
        for child in element.iterchildren():
            if child.tag == qn('w:p'):
                paragraph = Paragraph(child, parent)
                if paragraph.text.strip():
                    blocks.append({'kind': 'paragraph', 'text': paragraph.text, 'heading': (paragraph.style.name or '').startswith(('Heading', 'Title', 'Titre'))})
                for node in child.iter(qn('a:blip')):
                    relationship = node.get(qn('r:embed'))
                    image_key = (str(parent.part.partname), relationship)
                    if not relationship or image_key in seen_images or relationship not in parent.part.related_parts:
                        continue
                    seen_images.add(image_key)
                    blob = parent.part.related_parts[relationship].blob
                    if len(blob) > 5 * 1024 * 1024:
                        continue
                    try:
                        with Image.open(BytesIO(blob)) as source:
                            picture = ImageOps.exif_transpose(source)
                            picture.thumbnail((1200, 1200))
                            out = BytesIO()
                            picture.convert('RGB').save(out, format='JPEG', quality=85)
                        blocks.append({'kind': 'image', 'src': 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode('ascii')})
                    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                        continue
            elif child.tag == qn('w:tbl'):
                table = Table(child, parent)
                blocks.append({'kind': 'table', 'rows': [[cell.text for cell in row.cells] for row in table.rows]})
    # Include the first section's branding and footer when present.
    section = doc.sections[0]
    header = section.first_page_header if section.different_first_page_header_footer else section.header
    footer = section.first_page_footer if section.different_first_page_header_footer else section.footer
    extract(header._element, header)
    extract(doc.element.body, doc)
    extract(footer._element, footer)
    return blocks


def document_preview_response(path, *, title=None, download_url=None):
    """Used after an authenticated certificate generator, or the private route."""
    filename = os.path.basename(path)
    blocks = []
    error = None
    if filename.lower().endswith('.docx'):
        try:
            blocks = _docx_blocks(path)
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, PackageNotFoundError, XMLSyntaxError):
            error = 'L’aperçu de ce document n’est pas disponible. Vous pouvez ouvrir le fichier original après l’avoir téléchargé.'
    else:
        error = 'Ce format ne dispose pas d’un aperçu dans le navigateur. Le téléchargement reste disponible ci-dessous.'
    response = make_response(render_template(
        'document_preview.html', title=title or filename, filename=filename,
        blocks=blocks, error=error, download_url=download_url or request.path + '?download=1',
    ))
    response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    return _private(response)


def register_candidate_documents(app, db_connect, upload_dir, require_admin):
    """upload_dir is a callable so runtime/test directory changes are respected."""
    @app.post('/admin/candidat/<cid>/documents')
    def admin_candidate_documents_upload(cid):
        if not require_admin():
            abort(403)
        if not _equal(request.headers.get('X-CSRF-Token'), session.get('_candidate_message_csrf')):
            return jsonify(ok=False, error='La session a expiré. Rechargez la fiche.'), 400
        kind = request.form.get('category')
        if kind not in DOC_FIELDS or kind == 'photo':
            return jsonify(ok=False, error='Choisissez une catégorie de document.'), 400
        uploads = request.files.getlist('documents')
        if not uploads or any(not file.filename for file in uploads):
            return jsonify(ok=False, error='Sélectionnez au moins un fichier.'), 400
        root = Path(upload_dir()).resolve()
        folder = root / cid
        if folder.parent != root or folder.resolve() != folder:
            abort(404)
        with closing(db_connect()) as conn:
            if not conn.execute('SELECT 1 FROM candidats WHERE id=?', (cid,)).fetchone():
                abort(404)
            folder.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=folder) as temporary:
                try:
                    staged = [_stage_upload(file, kind, Path(temporary)) for file in uploads]
                    added = _attach_uploads(conn, cid, folder, kind, staged)
                except ValueError as exc:
                    return jsonify(ok=False, error=str(exc)), 400
        return _private(jsonify(ok=True, added=added))

    @app.get('/admin/candidat/<cid>/document/<filename>')
    def admin_candidate_document(cid, filename):
        if not require_admin():
            abort(403)
        with closing(db_connect()) as conn:
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not row:
            abort(404)
        path = _resolve_document(dict(row), filename, upload_dir())
        if request.args.get('download') == '1':
            return _private(send_file(path, as_attachment=True, download_name=document_name(filename)))
        with open(path, 'rb') as source:
            signature = source.read(5)
        if signature == b'%PDF-':
            return _private(send_file(path, mimetype='application/pdf', as_attachment=False, download_name=filename))
        image = _image_content(path)
        if image:
            content, mime = image
            return _private(send_file(content, mimetype=mime, as_attachment=False, download_name=filename))
        return document_preview_response(path, download_url=url_for('admin_candidate_document', cid=cid, filename=filename, download=1))
