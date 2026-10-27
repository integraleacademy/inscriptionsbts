"""Read the weekly vector export produced by Yparéo; reject uncertain layouts.

Hours are recovered from the grid and the event sidebars, then reconciled with
EACH printed weekly total. No OCR, guessed subject expansion or missing-week
reconstruction. Only plain data leaves this parser.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import re
from statistics import median
import unicodedata

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 100
MAX_COURSES = 500
MONTHS = {name: index + 1 for index, name in enumerate(
    'janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre'.split())}
WEEKDAYS = 'lundi mardi mercredi jeudi vendredi samedi dimanche'.split()


class ImportPDFError(ValueError):
    pass


def normal(value):
    value = str(value or '').replace('œ', 'oe').replace('Œ', 'OE').replace('æ', 'ae')
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def _page_error(number, message):
    raise ImportPDFError(f'Page {number} : {message} Aucun cours n’a été importé.')


def parse_ypareo_pdf(content, period):
    import pdfplumber

    if not content or len(content) > MAX_BYTES or not content.startswith(b'%PDF-'):
        raise ImportPDFError('Choisissez un PDF Yparéo de 10 Mo maximum.')
    rows, weeks, source_group = [], [], None
    try:
        pdf = pdfplumber.open(BytesIO(content))
    except Exception as error:
        raise ImportPDFError('Ce PDF est illisible ou protégé. Exportez à nouveau le planning depuis Yparéo.') from error
    with pdf:
        if not 1 <= len(pdf.pages) <= MAX_PAGES:
            raise ImportPDFError('Le PDF doit contenir entre 1 et 100 pages.')
        previous = None
        for number, original in enumerate(pdf.pages, 1):
            # wkhtmltopdf simulates bold by drawing a second, offset glyph.
            page = original.dedupe_chars(tolerance=1)
            words = page.extract_words(x_tolerance=1, y_tolerance=2)
            lines = []
            for word in words:
                if not lines or abs(lines[-1][0]['top'] - word['top']) > 2:
                    lines.append([])
                lines[-1].append(word)
            header = next((' '.join(w['text'] for w in line) for line in lines
                           if 'Planning groupe' in ' '.join(w['text'] for w in line)), '')
            match = re.search(r'^Planning groupe\s*-\s*(.+?)\s+Semaine\s+S\s*(\d+)\s*-\s*(\d+(?:[.,]\d+)?)h\b', header)
            if not match:
                _page_error(number, 'le format « Planning groupe / Semaine S » n’est pas reconnu.')
            group, week_number, printed_hours = match.groups()
            if source_group is not None and source_group != group:
                _page_error(number, 'ce fichier contient plusieurs groupes. Exportez une promotion à la fois.')
            source_group = group
            printed_minutes = Decimal(printed_hours.replace(',', '.')) * 60
            headings = []
            for line in lines:
                for index, word in enumerate(line):
                    if normal(word['text']) not in WEEKDAYS or index + 2 >= len(line):
                        continue
                    day, month = line[index + 1:index + 3]
                    if not day['text'].isdigit() or normal(month['text']) not in MONTHS:
                        continue
                    headings.append(dict(weekday=WEEKDAYS.index(normal(word['text'])),
                        day=int(day['text']), month=MONTHS[normal(month['text'])],
                        center=(word['x0'] + month['x1']) / 2, top=word['top']))
            headings.sort(key=lambda h: h['center'])
            if len(headings) not in (5, 6, 7) or [h['weekday'] for h in headings] != list(range(len(headings))):
                _page_error(number, 'les colonnes des jours ne sont pas identifiables.')
            candidates = []
            start_year = date.fromisoformat(period['start_date']).year
            end_year = date.fromisoformat(period['end_date']).year
            for year in range(start_year - 1, end_year + 2):
                try:
                    first = date(year, headings[0]['month'], headings[0]['day'])
                except ValueError:
                    continue
                if first.weekday() or first.isocalendar().week != int(week_number):
                    continue
                if previous is not None and first <= previous:
                    continue
                if all((first + timedelta(days=i)).day == h['day'] and
                       (first + timedelta(days=i)).month == h['month'] for i, h in enumerate(headings)):
                    candidates.append(first)
            if len(candidates) != 1:
                _page_error(number, 'l’année des dates est ambiguë. Vérifiez l’année du planning sélectionnée.')
            first = previous = candidates[0]
            width = median(b['center'] - a['center'] for a, b in zip(headings, headings[1:]))
            left, right = headings[0]['center'] - width / 2, headings[-1]['center'] + width / 2
            clocks = [w for w in words if w['x1'] < left + width * .05 and re.fullmatch(r'\d{2}:00', w['text'])]
            if len(clocks) < 3:
                _page_error(number, 'l’échelle horaire est illisible.')
            step = median(b['top'] - a['top'] for a, b in zip(clocks, clocks[1:]))
            if step <= 0 or any(int(b['text'][:2]) != int(a['text'][:2]) + 1 or
                                abs(b['top'] - a['top'] - step) > step * .03
                                for a, b in zip(clocks, clocks[1:])):
                _page_error(number, 'l’échelle horaire n’est pas régulière.')
            grid_lines = [r for r in page.rects if 0 < r['width'] < step * .04 and
                          r['height'] >= clocks[-1]['top'] - clocks[0]['top'] and
                          abs(r['top'] - clocks[0]['top']) < step * .25]
            if not grid_lines:
                _page_error(number, 'les limites de la grille horaire sont introuvables.')
            origin = min(r['top'] for r in grid_lines)
            sidebars = [r for r in page.rects if .09 < r['width'] / step < .14 and
                        r['height'] > step * .3 and left <= r['x0'] < right and r['top'] > origin]
            page_rows = []
            for sidebar in sorted(sidebars, key=lambda r: (r['x0'], r['top'])):
                day_index = round((sidebar['x0'] - left) / width)
                if not 0 <= day_index < len(headings):
                    _page_error(number, 'un cours déborde des colonnes.')
                # Export padding is 4 CSS px, the colour stripe is 6 px.
                padding = sidebar['width'] * 2 / 3
                start_float = int(clocks[0]['text'][:2]) * 60 + (sidebar['top'] - padding - origin) / step * 60
                end_float = int(clocks[0]['text'][:2]) * 60 + (sidebar['bottom'] + padding - origin) / step * 60
                start, end = round(start_float / 5) * 5, round(end_float / 5) * 5
                if max(abs(start - start_float), abs(end - end_float)) > 1.2 or not 0 <= start < end <= 1440:
                    _page_error(number, 'un horaire ne peut pas être reconstitué avec certitude.')
                block = [w for w in words if sidebar['x1'] < w['x0'] < left + (day_index + 1) * width - 2
                         and sidebar['top'] - 1 <= w['top'] < sidebar['bottom']]
                block_lines = []
                for word in block:
                    if not block_lines or abs(word['top'] - block_lines[-1][0]['top']) > 2:
                        block_lines.append([])
                    block_lines[-1].append(word)
                texts = [' '.join(w['text'] for w in line) for line in block_lines]
                if len(texts) < 2 or not normal(texts[1]).startswith(normal(group)[:20]):
                    _page_error(number, 'le contenu d’un bloc de cours est incomplet.')
                subject = re.sub(r'\s+C$', '', texts[0]).strip()
                teacher_lines = [t for t in texts[2:] if re.match(r'^(?:M\.|Mme|Mlle)\s', t)]
                if len(teacher_lines) > 1 or len(texts) != 2 + len(teacher_lines):
                    _page_error(number, 'un bloc contient plusieurs intervenants ou des informations non reconnues.')
                trainer = teacher_lines[0] if teacher_lines else 'Formateur non indiqué'
                if len(subject) > 160 or len(trainer) > 160:
                    _page_error(number, 'un intitulé de cours est trop long.')
                page_rows.append(dict(date=(first + timedelta(days=day_index)).isoformat(),
                    start=f'{start // 60:02d}:{start % 60:02d}', end=f'{end // 60:02d}:{end % 60:02d}',
                    subject=subject, trainer=trainer, page=number, duration_minutes=end-start))
            actual_minutes = sum(r['duration_minutes'] for r in page_rows)
            if actual_minutes != printed_minutes:
                _page_error(number, f'les cours lus totalisent {actual_minutes / 60:g} h, alors que le PDF annonce {printed_hours} h. Utilisez un export plus détaillé.')
            rows.extend(page_rows)
            if len(rows) > MAX_COURSES:
                raise ImportPDFError('Importez au maximum 500 cours à la fois.')
            weeks.append(dict(start=first.isoformat(), page=number, count=len(page_rows), minutes=actual_minutes))
            original.close()
    if not rows:
        raise ImportPDFError('Ce fichier ne contient aucun cours à importer.')
    rows.sort(key=lambda row: (row['date'], row['start'], row['subject']))
    # Different clipping widths may produce two prefixes of the same title.
    subjects = sorted(set(row['subject'] for row in rows), key=lambda label: (len(normal(label)), label))
    aliases = {}
    for label in subjects:
        candidates = [key for key in aliases.values() if len(normal(key)) >= 16 and normal(label).startswith(normal(key))]
        aliases[label] = candidates[0] if len(set(candidates)) == 1 else label
    for index, row in enumerate(rows):
        row.update(key=str(index), subject_key=aliases[row['subject']])
    return dict(group=source_group, rows=rows, weeks=weeks, pages=len(weeks),
                minutes=sum(r['duration_minutes'] for r in rows),
                first_date=rows[0]['date'], last_date=rows[-1]['date'],
                first_week=weeks[0]['start'], last_week=weeks[-1]['start'])
