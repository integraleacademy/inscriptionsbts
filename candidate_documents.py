"""Private dossier documents and browser previews without automatic downloads."""
from contextlib import closing
from io import BytesIO
import base64
import json
import os
import re
import zipfile

from flask import abort, make_response, render_template, request, send_file, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError

DOCUMENT_FIELDS = ('fichiers_ci', 'fichiers_photo', 'fichiers_carte_vitale', 'fichiers_cv', 'fichiers_lm')


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
            return _private(send_file(path, as_attachment=True, download_name=filename))
        with open(path, 'rb') as source:
            signature = source.read(5)
        if signature == b'%PDF-':
            return _private(send_file(path, mimetype='application/pdf', as_attachment=False, download_name=filename))
        image = _image_content(path)
        if image:
            content, mime = image
            return _private(send_file(content, mimetype=mime, as_attachment=False, download_name=filename))
        return document_preview_response(path, download_url=url_for('admin_candidate_document', cid=cid, filename=filename, download=1))
