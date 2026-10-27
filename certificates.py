"""Personalise legacy Word templates without changing their run formatting."""
from person_names import person_name
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from docx.oxml.ns import qn


def certificate_word(row):
    """Keep the original Word bundle available, using the current dossier mode."""
    from docx import Document
    from campaign import candidate_year
    from utils import BTS_LABELS
    mode = row.get('mode')
    if mode not in ('presentiel', 'distanciel'):
        raise ValueError('Renseignez le parcours présentiel ou distanciel avant de générer le certificat.')
    root = Path(__file__).resolve().parent
    filename = 'certificat_scolarite_presentiel.docx' if mode == 'presentiel' else 'certificat de scolarité 2026.docx'
    doc = Document(root / 'static' / 'templates' / filename)
    year = candidate_year(row)
    name = person_name(row.get('nom'),row.get('prenom'))
    course = BTS_LABELS.get((row.get('bts') or '').upper(), row.get('bts') or '')
    personalize_certificate(doc, {'{{NOM_PRENOM}}':name, '{{FORMATION}}':course,
        '{{DATE_AUJOURDHUI}}':datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y'),
        '{{ANNEE_DEBUT}}':str(year), '{{ANNEE_FIN}}':str(year+2)}, year)
    return doc


def certificate_pdf(row):
    """Fill PDFs exported from the original Word models, including their annexes.

    Course text is rendered by Office during template compilation to retain its
    wrapping and formatting. Runtime overlays only the name, date and years.
    """
    import hashlib
    import json
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from campaign import candidate_year

    mode = row.get('mode')
    if mode not in ('presentiel', 'distanciel'):
        raise ValueError('Renseignez le parcours présentiel ou distanciel avant de générer le certificat.')
    root = Path(__file__).resolve().parent
    folder = root / 'assets/certificates'
    manifest = json.loads((folder/'manifest.json').read_text())
    source = manifest['sources'][mode]
    if hashlib.sha256((root/source['path']).read_bytes()).hexdigest() != source['sha256']:
        raise RuntimeError('The certificate Word model changed; rebuild its PDF templates before deploying.')
    year = candidate_year(row)
    bts = (row.get('bts') or '').strip().upper()
    key = f"{mode}-{bts}-{2026 if year < 2027 else 2027}"
    if key not in manifest['templates']:
        raise ValueError('Renseignez un diplôme BTS valide sur la fiche avant de générer le certificat.')
    template = manifest['templates'][key]
    for style in ('Regular', 'Bold', 'Italic'):
        font = 'CertificateOriginal-' + style
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, str(folder/'fonts'/f'LiberationSans-{style}.ttf')))
    values = dict(name=person_name(row.get('nom'),row.get('prenom')),
                  date=datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y'),
                  year=str(year), end_year=str(year+2))
    reader = PdfReader(folder/template['file'])
    writer = PdfWriter()
    writer.append(reader, pages=list(range(template['start'], template['start']+template['pages'])))
    for index, page in enumerate(writer.pages):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = BytesIO()
        drawing = canvas.Canvas(overlay, pagesize=(width, height))
        for field in template['fields']:
            if field['page'] != index:
                continue
            value = (field['text'].replace('__YEAR__', values['year']).replace('__END_YEAR__', values['end_year'])
                     if field['field'] == 'text' else values[field['field']])
            font, size = 'CertificateOriginal-' + field['style'], field['size']
            if field['field'] == 'name':
                size = min(size, size * 450 / max(1, pdfmetrics.stringWidth(value, font, size)))
            drawing.setFont(font, size)
            if field['field'] == 'name':
                drawing.drawCentredString(field['x']+field['width']/2, height-field['y'], value)
            elif field['field'] == 'text':
                # Retain the original justification of the source Word spans.
                value = value.replace('\u00a0', ' ')
                word_space = (field['width'] - pdfmetrics.stringWidth(value, font, size)) / max(1, value.count(' '))
                drawing.drawString(field['x'], height-field['y'], value, wordSpace=word_space)
            else:
                drawing.drawString(field['x'], height-field['y'], value)
        drawing.save(); overlay.seek(0)
        page.merge_page(PdfReader(overlay).pages[0])
    writer.add_metadata({'/Title':'Certificat de scolarité', '/Author':'Intégrale Academy'})
    out = BytesIO(); writer.write(out)
    return out.getvalue()


def _replace(paragraph, replacements):
    nodes = list(paragraph.iter(qn("w:t")))
    for old, new in replacements.items():
        text = "".join(node.text or "" for node in nodes)
        # Right-to-left edits preserve the offsets of earlier matches, including
        # placeholders Word has split over several formatted runs.
        for match in reversed(list(re.finditer(re.escape(old), text))):
            start, end = match.span()
            offset = 0
            inserted = False
            for node in nodes:
                value = node.text or ""
                left, right = offset, offset + len(value)
                offset = right
                if right <= start or left >= end:
                    continue
                prefix = value[:max(0, start - left)]
                suffix = value[max(0, end - left):]
                node.text = prefix + (str(new) if not inserted else "") + suffix
                node.set(qn("xml:space"), "preserve")
                inserted = True


def personalize_certificate(doc, replacements, year):
    parts = [doc.part, *[rel.target_part for rel in doc.part.rels.values()
                        if not rel.is_external and hasattr(rel.target_part, "element")]]
    for part in parts:
        for paragraph in part.element.iter(qn("w:p")):
            if year >= 2027:
                # Apply template years before inserting the actual issue date.
                _replace(paragraph, {"2026": str(year), "2028": str(year + 2)})
                text = "".join(node.text or "" for node in paragraph.iter(qn("w:t")))
                if "6000€" in text:
                    obsolete = "et n'hésitez pas à mettre en avant l'aide de 6000€ que verse l’État à toute entreprise qui recrute un alternant avant le 31 décembre 2025."
                    _replace(paragraph, {obsolete: "notre équipe peut accompagner l’entreprise dans les démarches liées au contrat d’apprentissage."})
            _replace(paragraph, replacements)
