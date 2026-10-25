"""Personalise legacy Word templates without changing their run formatting."""
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
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
    name = f"{row.get('prenom') or ''} {row.get('nom') or ''}".strip().upper()
    course = BTS_LABELS.get((row.get('bts') or '').upper(), row.get('bts') or '')
    personalize_certificate(doc, {'{{NOM_PRENOM}}':name, '{{FORMATION}}':course,
        '{{DATE_AUJOURDHUI}}':datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y'),
        '{{ANNEE_DEBUT}}':str(year), '{{ANNEE_FIN}}':str(year+2)}, year)
    return doc


def certificate_pdf(row):
    """A one-page certificate using the appropriate existing signed model.

    The original Word bundles remain available in the repository. Their first
    page provides the institution details, wording, stamp and signature; the
    old welcome/marketing annexes are not part of the certificate PDF.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    from campaign import candidate_year
    from utils import BTS_LABELS

    mode = row.get('mode')
    root = Path(__file__).resolve().parent
    doc = certificate_word(row)
    year = candidate_year(row)
    date = datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y')
    name = f"{row.get('prenom') or ''} {row.get('nom') or ''}".strip().upper()
    course = BTS_LABELS.get((row.get('bts') or '').upper(), row.get('bts') or '')
    # Extract only the original certificate's text and images, before its annex.
    paragraphs, seals = [], []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip() == 'Confirmation d’inscription':
            break
        value = paragraph.text.strip()
        if value:
            paragraphs.append(value)
        for blip in paragraph._p.iter(qn('a:blip')):
            seals.append(doc.part.related_parts[blip.get(qn('r:embed'))].blob)
    navy, blue = colors.HexColor('#142d56'), colors.HexColor('#3565d9')
    # Embed the fonts bundled with ReportLab for consistent rendering on Render
    # and on computers without Helvetica. No system font dependency is needed.
    if 'CertificateSans' not in pdfmetrics.getRegisteredFontNames():
        fonts = Path(reportlab.__file__).parent / 'fonts'
        pdfmetrics.registerFont(TTFont('CertificateSans', str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('CertificateSans-Bold', str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('CertificateSans', normal='CertificateSans', bold='CertificateSans-Bold')
    normal = ParagraphStyle('CertificateBody', fontName='CertificateSans', fontSize=10, leading=15, textColor=navy)
    center = ParagraphStyle('CertificateCenter', parent=normal, alignment=TA_CENTER)
    heading = ParagraphStyle('CertificateHeading', parent=center, fontName='CertificateSans-Bold', fontSize=21, leading=28)
    name_size = max(12, min(17, 17 * (164*mm) / max(1,pdfmetrics.stringWidth(name, 'CertificateSans-Bold', 17))))
    bold = ParagraphStyle('CertificateName', parent=center, fontName='CertificateSans-Bold', fontSize=name_size, leading=20)
    right = ParagraphStyle('CertificateSign', parent=normal, alignment=TA_RIGHT, fontSize=9, leading=14)
    out = BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=A4, rightMargin=23*mm, leftMargin=23*mm,
                            topMargin=18*mm, bottomMargin=20*mm, title='Certificat de scolarité', author='Intégrale Academy')
    logo = Image(str(root / 'static' / 'academy-official-logo.png'))
    logo.drawWidth, logo.drawHeight = 72*mm, 72*mm*logo.imageHeight/logo.imageWidth
    header_text = ParagraphStyle('CertificateHeader', parent=right, textColor=colors.white, fontSize=8)
    header = Table([[logo, Paragraph('SERVICE SCOLARITÉ<br/>Centre de formation<br/>des apprentis', header_text)]], colWidths=[83*mm, 81*mm])
    header.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND',(0,0),(-1,0),navy),
                               ('LINEBELOW',(0,0),(-1,0),2,blue), ('TOPPADDING',(0,0),(-1,0),10),
                               ('BOTTOMPADDING',(0,0),(-1,0),10),('LEFTPADDING',(0,0),(-1,0),10),('RIGHTPADDING',(0,0),(-1,0),12)]))
    story = [header, Spacer(1,8*mm), Paragraph('Certificat de scolarité', heading),
             Spacer(1,3*mm), Paragraph(f'Promotion {year}-{year+2}', center), Spacer(1,8*mm)]
    for value in paragraphs[1:5]:
        story.append(Paragraph(escape(value), normal))
    story.extend([Spacer(1,6*mm), Paragraph('certifie que :', center), Spacer(1,4*mm),
                  Paragraph(escape(name), bold), Spacer(1,5*mm),
                  Paragraph('est inscrit(e) dans notre établissement pour suivre la formation :', center), Spacer(1,5*mm)])
    mode_label = 'En présentiel à Puget-sur-Argens' if mode == 'presentiel' else 'À distance, en visioconférence'
    training = Table([[Paragraph('<b>' + escape(course) + '</b><br/>' + mode_label, center)]], colWidths=[164*mm])
    training.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f4fc')), ('BOX',(0,0),(-1,-1),.5,colors.HexColor('#d8e2f4')), ('TOPPADDING',(0,0),(-1,-1),10), ('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story.extend([training, Spacer(1,6*mm), Paragraph(f'Du 01/09/{year} au 31/07/{year+2}.', center),
                  Spacer(1,9*mm), Paragraph('Pour servir et faire valoir ce que de droit.', normal), Spacer(1,7*mm)])
    location = 'Puget-sur-Argens' if mode == 'presentiel' else 'Paris'
    story.extend([Paragraph(f'Fait à {location}, le {date}', right), Spacer(1,4*mm),
                  Paragraph('Monsieur Clément VAILLANT<br/>Directeur général CFA Intégrale Academy<br/>Intégrale Sécurité Formations', right)])
    if seals:
        images = []
        for blob in seals[:2]:
            image = Image(BytesIO(blob))
            ratio = min(48*mm/image.imageWidth, 21*mm/image.imageHeight)
            image.drawWidth, image.drawHeight = image.imageWidth*ratio, image.imageHeight*ratio
            images.append(image)
        stamps = Table([images], hAlign='RIGHT')
        stamps.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        story.extend([Spacer(1,3*mm), stamps])
    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d8e2f4'))
        canvas.line(23*mm,18*mm,187*mm,18*mm)
        canvas.setFont('CertificateSans',8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(23*mm,13*mm,'Intégrale Academy · 04 22 47 07 68 · ecole@integraleacademy.com')
        canvas.drawRightString(187*mm,13*mm, str(row.get('numero_dossier') or ''))
        canvas.restoreState()
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
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
