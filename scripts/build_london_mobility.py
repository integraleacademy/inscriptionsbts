"""Compile the preserved Word model; run locally when its content changes.

Requires LibreOffice, PyMuPDF and python-docx. Production only needs pypdf and
ReportLab. The generated PDFs contain no candidate data.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import fitz
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from london_mobility_documents import ASSETS, MODEL, word_document


def build():
    manifest = {'source_sha256': hashlib.sha256(MODEL.read_bytes()).hexdigest()}
    values = dict(apprentice_first_name='Camille', apprentice_last_name='EXEMPLE',
                  apprentice_birth_date='1990-01-01', apprentice_sex='Femme',
                  employer_name='Entreprise exemple', employer_address='1 rue Exemple',
                  employer_postcode='75001', employer_city='Paris', employer_siret='12345678901234',
                  convention_date='2026-10-28', mobility_start='2027-11-08', mobility_end='2027-11-12',
                  guardian_first_name='Alex', guardian_last_name='EXEMPLE')
    with tempfile.TemporaryDirectory(prefix='london-model-') as folder:
        folder = Path(folder)
        for variant, birth in [('adult', '1990-01-01'), ('minor', '2010-01-01')]:
            values['apprentice_birth_date'] = birth
            content = word_document(values, compile_fields=True)
            word = folder / f'{variant}.docx'; word.write_bytes(content)
            profile = folder / ('profile-' + variant); profile.mkdir()
            subprocess.run([os.environ.get('SOFFICE', 'libreoffice'), '-env:UserInstallation=' + profile.as_uri(),
                            '--invisible', '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', str(folder), str(word)], check=True, timeout=90)
            doc = Document(BytesIO(content))
            right = (doc.sections[0].page_width - doc.sections[0].right_margin) / 12700
            left = doc.sections[0].left_margin / 12700
            pdf = fitz.open(word.with_suffix('.pdf'))
            fields = []
            for index, page in enumerate(pdf):
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        for span in line['spans']:
                            if not span['text'].startswith('LONDONFIELD_'): continue
                            key = span['text'][12:].strip().lower()
                            x = left if key == 'beneficiary' else span['origin'][0]
                            # Signatures occupy the left half of the source page.
                            width = (right - left) / 2 - 14 if key in {'company_signature', 'beneficiary_signature', 'guardian'} else right - x
                            fields.append(dict(name=key, page=index, x=x,
                                               baseline=span['origin'][1], size=span['size'],
                                               width=width, leading=span['size'] * 1.25,
                                               align='center' if key == 'beneficiary' else 'left',
                                               lines=1 if key in {'siret', 'issue'} else 2))
                            page.add_redact_annot(span['bbox'], fill=False)
                page.apply_redactions(images=0, graphics=0)
            expected = {'company','address','city','siret','beneficiary','period','issue','company_signature','beneficiary_signature'}
            if variant == 'minor': expected.add('guardian')
            assert {f['name'] for f in fields} == expected, fields
            filename = variant + '.pdf'
            pdf.save(ASSETS / filename, garbage=4, deflate=True)
            manifest[variant] = dict(file=filename, pages=len(pdf), fields=fields)
            print(variant, len(pdf), 'pages', len(fields), 'fields')
    (ASSETS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    build()
