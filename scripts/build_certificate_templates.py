"""Compile the original Word bundles once; production needs no Office process.

Run with python-docx, PyMuPDF and LibreOffice installed. The original DOCX files
are never modified. PDFs retain their text, graphics, tables, signatures and
annexes. Only name, issue date and cohort years become dynamic overlay fields.
"""
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from certificates import personalize_certificate
BTS_LABELS = next(ast.literal_eval(node.value) for node in ast.parse((ROOT/'utils.py').read_text()).body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'BTS_LABELS' for target in node.targets))


def compile_templates(output=ROOT / 'assets/certificates'):
    sources = {'presentiel':'certificat_scolarite_presentiel.docx',
               'distanciel':'certificat de scolarité 2026.docx'}
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'version':1, 'sources':{}, 'templates':{}}
    with tempfile.TemporaryDirectory(prefix='certificate-models-') as folder:
        folder = Path(folder)
        pdf_dir = folder / 'pdf'; pdf_dir.mkdir()
        paths = []
        for mode, filename in sources.items():
            source = ROOT / 'static/templates' / filename
            manifest['sources'][mode] = {'path':str(source.relative_to(ROOT)), 'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            for year in (2026, 2027):
                for bts, course in BTS_LABELS.items():
                    key = f'{mode}-{bts}-{year}'
                    doc = Document(source)
                    personalize_certificate(doc, {'{{FORMATION}}':course, '{{DATE_AUJOURDHUI}}':'00/00/0000'}, year)
                    # Explicit section starts avoid headings stranded in the
                    # preceding page's footer when fonts have different metrics.
                    for paragraph in doc.paragraphs:
                        if paragraph.text.strip() in ('Confirmation d’inscription', 'Contrat d’apprentissage'):
                            paragraph.paragraph_format.page_break_before = True
                    path = folder / (key+'.docx'); doc.save(path); paths.append(path)
        result = subprocess.run([shutil.which('soffice'), '-env:UserInstallation='+ (folder/'office').as_uri(),
            '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', str(pdf_dir), *map(str, paths)],
            capture_output=True, text=True, timeout=240)
        if result.returncode or len(list(pdf_dir.glob('*.pdf'))) != len(paths):
            raise RuntimeError(result.stdout+'\n'+result.stderr)
        bundle = fitz.open()
        for path in paths:
            key = path.stem
            base_year = int(key.rsplit('-',1)[1])
            tokens = {'{{NOM_PRENOM}}':'name', '00/00/0000':'date'}
            pdf = fitz.open(pdf_dir / (key+'.pdf'))
            if len(pdf) != 3:
                raise RuntimeError(f'{key}: expected 3 original sections, got {len(pdf)} pages')
            fields = []
            for index, page in enumerate(pdf):
                for block in page.get_text('rawdict')['blocks']:
                    for line in block.get('lines', []):
                        # Whole spans keep dates / cohort ranges searchable as
                        # contiguous text instead of appending isolated digits.
                        for span in line['spans']:
                            value = ''.join(char['c'] for char in span['chars'])
                            if str(base_year) not in value and str(base_year+2) not in value:
                                continue
                            rect = fitz.Rect(span['bbox'])
                            style = 'Bold' if 'Bold' in span['font'] else 'Italic' if 'Italic' in span['font'] else 'Regular'
                            fields.append(dict(page=index, field='text', text=value.replace(str(base_year),'__YEAR__').replace(str(base_year+2),'__END_YEAR__'),
                                               x=span['origin'][0], y=span['origin'][1], width=rect.width, size=span['size'], style=style))
                            page.add_redact_annot(rect, fill=None, cross_out=False)
                        chars = [(char,span) for span in line['spans'] for char in span['chars']]
                        text = ''.join(char['c'] for char,span in chars)
                        for token, field in tokens.items():
                            for match in re.finditer(re.escape(token), text):
                                selected = chars[match.start():match.end()]
                                rect = fitz.Rect(selected[0][0]['bbox'])
                                for char,span in selected[1:]: rect |= fitz.Rect(char['bbox'])
                                char,span = selected[0]
                                style = 'Bold' if 'Bold' in span['font'] else 'Italic' if 'Italic' in span['font'] else 'Regular'
                                fields.append(dict(page=index, field=field, x=char['origin'][0], y=char['origin'][1],
                                                   width=rect.width, size=span['size'], style=style))
                                page.add_redact_annot(rect, fill=None, cross_out=False)
                page.apply_redactions(images=0, graphics=0)
            if sum(f['field']=='name' for f in fields) != 1 or sum(f['field']=='date' for f in fields) != 2:
                raise RuntimeError(f'{key}: missing dynamic fields')
            start = len(bundle)
            bundle.insert_pdf(pdf)
            manifest['templates'][key] = {'file':'models.pdf', 'start':start, 'pages':len(pdf), 'fields':fields}
            print(key, len(fields), 'fields', flush=True)
        # Deduplicate shared original images/fonts across the 24 variants.
        bundle.save(output/'models.pdf', garbage=4, deflate=True)
        for path in paths:
            (output/(path.stem+'.pdf')).unlink(missing_ok=True)
        (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    compile_templates()
