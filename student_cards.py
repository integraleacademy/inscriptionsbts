"""Print student cards on the original, unmodified two-sided PDF artwork."""
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from flask import abort, make_response, render_template, request, send_file
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import NameObject, DictionaryObject
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from werkzeug.exceptions import NotFound
from werkzeug.utils import secure_filename

from campaign import candidate_year
from candidate_photos import load_candidate_portrait

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'assets/student_cards/carte_etudiante_original.pdf'
FONT = 'StudentCard-LiberationSans'
# Coordinates from the supplied digital-entry model, in PDF points from top left.
FIELDS = {
    'nom': (44.15, 54.71, 160.20, 66.05),
    'prenom': (44.15, 67.92, 160.55, 79.26),
    'birth': (44.15, 80.96, 160.38, 92.30),
    'validity': (44.15, 96.60, 160.44, 107.94),
    'director': (161.99, 50.28, 237.80, 61.62),
    'website': (161.48, 73.55, 237.29, 84.89),
    'school': (63.07, 84.88, 222.55, 96.22),
    'street': (63.07, 97.09, 222.87, 107.59),
    'city': (63.07, 107.59, 222.87, 118.95),
    'phone': (63.07, 119.41, 222.21, 130.75),
}
PHOTO_BOX = (166.0, 48.2, 231.5, 139.3)
ADDRESSES = {
    'presentiel': ('54 chemin du Carreou', '83480 PUGET-SUR-ARGENS'),
    'distanciel': ('141 rue de Rivoli', '75001 PARIS'),
}


def student_card_dates(row, today=None):
    """Current school year within this student's two-year cohort, editable in UI."""
    today = today or datetime.now(ZoneInfo('Europe/Paris')).date()
    cohort = candidate_year(row)
    academic_year = today.year if today.month >= 9 else today.year - 1
    year = max(cohort, min(academic_year, cohort + 1))
    return {'start': f'{year}-09-01', 'end': f'{year+1}-08-31'}


def _date(value, label):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'Renseignez une {label} valide.') from None


def _text(drawing, key, value, height, size=7):
    """Fit names without clipping or silently truncating any part of the identity."""
    left, top, right, bottom = FIELDS[key]
    width = right - left - 2
    value = ' '.join(str(value).split())
    fitted = min(size, size * width / max(1, pdfmetrics.stringWidth(value, FONT, size)))
    if fitted < 5.5 and key in ('nom', 'prenom'):
        # The original identity slots can hold two small lines, separated from
        # the next field by the model's existing gap. Keep compound names whole.
        splits = [i for i, character in enumerate(value) if character == ' ']
        if not splits:
            splits = [len(value)//2]
        split = min(splits, key=lambda i: max(pdfmetrics.stringWidth(value[:i].strip(), FONT, 5.5),
                                             pdfmetrics.stringWidth(value[i:].strip(), FONT, 5.5)))
        lines = [value[:split].strip(), value[split:].strip()]
        if any(pdfmetrics.stringWidth(line, FONT, 5.5) > width for line in lines):
            raise ValueError('Un nom est trop long pour la carte. Vérifiez l’identité dans l’onglet Informations.')
        drawing.setFont(FONT, 5.5)
        for index, line in enumerate(lines):
            drawing.drawString(left+1, height-top-1.6-index*5.7, line)
        return
    drawing.setFont(FONT, fitted)
    drawing.drawString(left + 1, height - (top + bottom) / 2 - fitted * .34, value)


def student_card_pdf(row, photo, *, start=None, end=None, layout='a4'):
    row = dict(row)
    if layout not in ('a4', 'carte'):
        raise ValueError('Choisissez le format A4 ou le format carte.')
    if not row.get('nom') or not row.get('prenom'):
        raise ValueError('Renseignez le nom et le prénom dans l’onglet Informations.')
    birth = _date(row.get('date_naissance'), 'date de naissance')
    defaults = student_card_dates(row)
    first = _date(start if start is not None else defaults['start'], 'date de début')
    last = _date(end if end is not None else defaults['end'], 'date de fin')
    if first >= last:
        raise ValueError('La date de fin de validité doit être postérieure à la date de début.')
    if birth >= first:
        raise ValueError('Vérifiez la date de naissance et les dates de validité.')
    if row.get('mode') not in ADDRESSES:
        raise ValueError('Renseignez le parcours présentiel ou distanciel dans la fiche.')
    if photo is None:
        raise ValueError('Ajoutez une photo d’identité au dossier avant de générer la carte.')
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(ROOT / 'assets/certificates/fonts/LiberationSans-Regular.ttf')))
    street, city = ADDRESSES[row['mode']]
    values = dict(nom=row['nom'].upper(), prenom=row['prenom'], birth=birth.strftime('%d/%m/%Y'),
                  validity=f'{first:%d/%m/%Y} au {last:%d/%m/%Y}', director='Clément VAILLANT',
                  website='integraleacademy.com', school='CFA Intégrale Academy', street=street,
                  city=city, phone='04 22 47 07 68')
    source = PdfReader(TEMPLATE)
    cards = PdfWriter()
    # Recto (identity) first, verso (school) second. Keep the supplied artwork intact.
    cards.append(source, pages=[1, 0])
    for index, page in enumerate(cards.pages):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = BytesIO()
        drawing = canvas.Canvas(overlay, pagesize=(width, height), invariant=1)
        drawing.setFillColorRGB(.14, .17, .25)
        for key in (('nom', 'prenom', 'birth', 'validity') if index == 0 else
                    ('director', 'website', 'school', 'street', 'city', 'phone')):
            _text(drawing, key, values[key], height, size=6 if key in ('director', 'website', 'validity') else 7)
        if index == 0:
            left, top, right, bottom = PHOTO_BOX
            # Contain the saved portrait: never crop the face a second time to fill
            # the slightly taller original photo frame. The white margins are intentional.
            portrait = photo.convert('RGB')
            portrait.thumbnail((800, 1000))
            drawing.drawImage(ImageReader(portrait), left, height-bottom, width=right-left, height=bottom-top,
                              preserveAspectRatio=True, anchor='c')
        drawing.save()
        page.merge_page(PdfReader(BytesIO(overlay.getvalue())).pages[0])
    if layout == 'carte':
        writer = cards
    else:
        writer = PdfWriter()
        for index, card in enumerate(cards.pages):
            width, height = float(card.mediabox.width), float(card.mediabox.height)
            x, y = (A4[0]-width)/2, (A4[1]-height)/2
            page = writer.add_blank_page(width=A4[0], height=A4[1])
            page.merge_transformed_page(card, Transformation().translate(x, y))
            guide = BytesIO()
            drawing = canvas.Canvas(guide, pagesize=A4, invariant=1)
            drawing.setStrokeColorRGB(.35, .39, .45)
            drawing.setLineWidth(.3)
            for corner_x in (x, x+width):
                for corner_y in (y, y+height):
                    sx = -1 if corner_x == x else 1
                    sy = -1 if corner_y == y else 1
                    drawing.line(corner_x+sx*3, corner_y, corner_x+sx*11, corner_y)
                    drawing.line(corner_x, corner_y+sy*3, corner_x, corner_y+sy*11)
            drawing.setFillColorRGB(.18, .23, .32)
            drawing.setFont(FONT, 12)
            drawing.drawCentredString(A4[0]/2, y+height+62, 'Carte étudiante - ' + ('Recto' if index == 0 else 'Verso'))
            drawing.setFont(FONT, 9)
            for line, text in enumerate((
                'Imprimer en A4 à taille réelle (100 %), sans ajuster à la page.',
                'Recto verso : retourner sur le bord long. Découper selon les repères.',
                'Format final : 86 × 54 mm. La signature est à compléter par le titulaire.',
            )):
                drawing.drawCentredString(A4[0]/2, y-39-line*15, text)
            drawing.save()
            page.merge_page(PdfReader(BytesIO(guide.getvalue())).pages[0])
    writer.root_object[NameObject('/ViewerPreferences')] = DictionaryObject({
        NameObject('/PrintScaling'): NameObject('/None'),
        NameObject('/Duplex'): NameObject('/DuplexFlipLongEdge'),
    })
    writer.add_metadata({'/Title': f"Carte étudiante - {row['prenom']} {row['nom'].upper()}", '/Author': 'Intégrale Academy'})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def register_student_cards(app, db_connect, upload_dir, require_admin):
    @app.get('/admin/candidat/<cid>/carte-etudiante.pdf')
    def admin_candidate_student_card(cid):
        if not require_admin():
            abort(403)
        with closing(db_connect()) as conn:
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
        if not row:
            abort(404)
        row = dict(row)
        try:
            try:
                photo, _, _ = load_candidate_portrait(row, upload_dir(), db_connect)
            except NotFound:
                raise ValueError('La photo d’identité est absente ou illisible. Ajoutez une photo au dossier avant de générer la carte.') from None
            content = student_card_pdf(row, photo, start=request.args.get('debut'), end=request.args.get('fin'),
                                       layout=request.args.get('format', 'a4'))
        except ValueError as exc:
            response = make_response(render_template('student_card_error.html', row=row, error=str(exc),
                                                      title='Carte étudiante'), 400)
        else:
            name = secure_filename(f"{row['nom']}_{row['prenom']}") or cid
            response = send_file(BytesIO(content), mimetype='application/pdf',
                                 download_name=f'Carte_etudiante_{name}.pdf',
                                 as_attachment=request.args.get('download') == '1')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
