"""School documents for the authenticated student's own dossier only."""
from contextlib import closing
from functools import wraps
from io import BytesIO
from threading import Lock

from flask import abort, redirect, render_template, request, send_file
from werkzeug.exceptions import NotFound
from werkzeug.utils import secure_filename

from campaign import candidate_year
from candidate_access import get_authenticated_student
from candidate_photos import load_candidate_portrait
from certificates import certificate_pdf
from student_cards import student_card_dates, student_card_pdf

_IMAGE_RENDER_LOCK = Lock()  # PDFium must not run concurrently in Flask threads.


def enrollment_message(row):
    status = (row.get('statut') or '').lower()
    if status in ('confirmee', 'reconf_en_cours', 'reconfirmee', 'rentree'):
        return ''
    # A request to replace a document must not revoke a confirmed enrollment.
    if status == 'docs_non_conformes' and (row.get('date_confirmee') or row.get('date_reconfirmee')):
        return ''
    if status == 'annulee':
        return 'Ton inscription est annulée. Contacte l’école pour faire le point sur tes documents.'
    return 'Tes documents seront disponibles ici après la confirmation de ton inscription.'


def register_student_documents(app, db_connect, upload_dir):
    @app.after_request
    def student_document_headers(response):
        if request.path == '/espace/documents' or request.path.startswith('/espace/documents/'):
            response.headers.update({
                'Cache-Control': 'private, no-store',
                'Referrer-Policy': 'no-referrer',
                'X-Content-Type-Options': 'nosniff',
            })
            response.vary.add('Cookie')
        return response

    def student_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            identity = get_authenticated_student(app, db_connect, allow_initial=True)
            if not identity:
                return redirect('/espace/connexion')
            if identity['must_change']:
                return redirect('/espace/mot-de-passe')
            # No dossier identifier, bearer link or editable student data is
            # accepted from the URL. Recheck membership on every file request.
            if set(request.args) - {'download'} or (
                'download' in request.args and request.args.getlist('download') != ['1']
            ):
                abort(400)
            with closing(db_connect()) as conn:
                row = conn.execute('SELECT * FROM candidats WHERE id=?', (identity['candidate_id'],)).fetchone()
            if not row:
                abort(404)
            return fn(dict(row), *args, **kwargs)
        return wrapped

    def certificate_content(row):
        if not row.get('nom') or not row.get('prenom'):
            raise ValueError('Identité incomplète.')
        from pypdf import PdfReader, PdfWriter
        source = PdfReader(BytesIO(certificate_pdf(row)))
        writer = PdfWriter()
        writer.add_page(source.pages[0])
        writer.add_metadata({'/Title': 'Certificat de scolarité', '/Author': 'Intégrale Academy'})
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def card_content(row):
        try:
            photo, _, _ = load_candidate_portrait(row, upload_dir(), db_connect)
        except NotFound:
            raise ValueError('Ta photo d’identité est manquante ou illisible. Contacte l’école pour compléter ton dossier.') from None
        try:
            return student_card_pdf(row, photo)
        except ValueError:
            raise ValueError('L’équipe doit compléter tes informations avant de rendre ta carte disponible. Contacte l’école.') from None

    def availability(row):
        message = enrollment_message(row)
        certificate_error = card_error = message
        if not message:
            try:
                certificate_content(row)
            except ValueError:
                certificate_error = 'L’équipe doit compléter tes informations avant de rendre ton certificat disponible. Contacte l’école.'
            try:
                card_content(row)
            except ValueError as exc:
                card_error = str(exc)
        return certificate_error, card_error

    def documents_page(row, *, status=200):
        certificate_error, card_error = availability(row)
        dates = student_card_dates(row)
        return render_template(
            'student_documents.html', title='Mes documents · Intégrale Academy', row=row,
            year=candidate_year(row), certificate_error=certificate_error, card_error=card_error,
            card_start='/'.join(reversed(dates['start'].split('-'))),
            card_end='/'.join(reversed(dates['end'].split('-'))),
        ), status

    def file_response(content, row, title, extension, mimetype):
        name = secure_filename(f"{row['nom']}_{row['prenom']}") or 'etudiant'
        return send_file(BytesIO(content), mimetype=mimetype,
                         download_name=f'{title}_{name}.{extension}',
                         as_attachment=extension != 'pdf' and request.args.get('download') == '1', conditional=False)

    @app.get('/espace/documents')
    @student_required
    def student_documents(row):
        return documents_page(row)

    @app.get('/espace/documents/certificat-scolarite.pdf')
    @student_required
    def student_certificate(row):
        if enrollment_message(row):
            return documents_page(row, status=403)
        try:
            content = certificate_content(row)
        except ValueError:
            return documents_page(row, status=409)
        return file_response(content, row, 'Certificat_scolarite', 'pdf', 'application/pdf')

    @app.get('/espace/documents/carte-etudiante/<face>.png')
    @student_required
    def student_card_image(row, face):
        if face not in ('recto', 'verso'):
            abort(404)
        if enrollment_message(row):
            return documents_page(row, status=403)
        try:
            content = card_content(row)
        except ValueError:
            return documents_page(row, status=409)
        # Rasterize the existing print model, retaining the exact artwork,
        # identity, saved portrait crop, address and cohort-based validity.
        import pdfplumber
        output = BytesIO()
        with _IMAGE_RENDER_LOCK, pdfplumber.open(BytesIO(content)) as pdf:
            preview = pdf.pages[0 if face == 'recto' else 1].to_image(resolution=300, antialias=True)
            preview.save(output, format='PNG', quantize=False)
        return file_response(output.getvalue(), row, f'Carte_etudiante_{face}', 'png', 'image/png')
