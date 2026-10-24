"""Readable, self-contained planning exports (weekly calendar and yearly alternance).

Input contract matches planning.get_planning_snapshot: promotion, courses, days.
Dates are inclusive ISO dates; course start/end are local HH:MM (Europe/Paris).
No database, network access, or writes are performed by this module.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 27
INK = colors.HexColor('#293B33')
MUTED = colors.HexColor('#637168')
LINE = colors.HexColor('#D5DDD5')
PAPER = colors.HexColor('#F7F7F2')
OCHRE = colors.HexColor('#AB7D2F')
OLIVE = colors.HexColor('#5F7662')
WARNING = colors.HexColor('#B76518')
HOLIDAY_RED = colors.HexColor('#A53535')
WHITE = colors.white
KIND_STYLES = {
    'school': ('École', '#E5EEE5', '#476B53'),
    'company': ('Entreprise', '#F2E5CA', '#87602E'),
    'holiday': ('Vacances', '#EDE8D9', '#776D47'),
    'closed': ('Fermé', '#E7E9E7', '#687169'),
    'public_holiday': ('Jour férié', '#F7DDDB', '#A53535'),
    'unconfigured': ('Non défini', '#FFFFFF', '#899188'),
}
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')
WEEKDAYS = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')


@lru_cache(maxsize=1)
def _fonts():
    root = Path('/usr/share/fonts/truetype/dejavu')
    if (root / 'DejaVuSans.ttf').exists() and (root / 'DejaVuSans-Bold.ttf').exists():
        for name, filename in (('PlanningSans', 'DejaVuSans.ttf'), ('PlanningSans-Bold', 'DejaVuSans-Bold.ttf')):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(root / filename)))
        pdfmetrics.registerFontFamily('PlanningSans', normal='PlanningSans', bold='PlanningSans-Bold', italic='PlanningSans', boldItalic='PlanningSans-Bold')
        return 'PlanningSans', 'PlanningSans-Bold'
    # Standard PDF fonts support French accents and require no runtime font install.
    return 'Helvetica', 'Helvetica-Bold'


def _clean(value):
    return str(value or '').replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', '-').replace('\u00a0', ' ')


def _paragraph(text, width, *, size=8.1, bold=False, color=INK, leading=None):
    regular, heavy = _fonts()
    style = ParagraphStyle('planning', fontName=heavy if bold else regular, fontSize=size,
                           leading=leading or size * 1.28, textColor=color, spaceAfter=0,
                           alignment=TA_LEFT, splitLongWords=1, allowWidows=0, allowOrphans=0)
    paragraph = Paragraph(text, style)
    _, height = paragraph.wrap(max(1, width), 10000)
    return paragraph, height


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _minutes(value):
    if isinstance(value, int):
        return value
    match = re.fullmatch(r'(\d{1,2}):(\d{2})(?::\d{2})?', str(value or ''))
    if not match:
        raise ValueError('Horaire de cours invalide.')
    hour, minute = map(int, match.groups())
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise ValueError('Horaire de cours invalide.')
    return hour * 60 + minute


def _clock(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _hours(minutes):
    hours, remainder = divmod(int(minutes), 60)
    return f'{hours} h' + (f' {remainder:02d}' if remainder else '')


def _date_label(day, year=False):
    return f'{day.day} {MONTHS[day.month - 1]}' + (f' {day.year}' if year else '')


def _normalise(promotion, courses, days, start, end):
    promotion = dict(promotion)
    start = _date(start or promotion.get('date_debut'))
    end = _date(end or promotion.get('date_fin'))
    if end < start or (end - start).days > 1095:
        raise ValueError('La période d’export doit être comprise entre un jour et trois ans.')
    records, seen = [], set()
    promotion_id = str(promotion.get('id') or '')
    for source in courses or []:
        item = dict(source)
        groups = [dict(group) for group in (item.get('groups') or []) if isinstance(group, dict)]
        participants = {str(value) for value in (item.get('promotion_ids') or []) if value}
        participants.update(str(group.get('promotion_id')) for group in groups if group.get('promotion_id'))
        if participants and promotion_id and promotion_id not in participants:
            continue
        local_group = next((group for group in groups if str(group.get('promotion_id')) == promotion_id), {})
        item['subject_name'] = local_group.get('subject_name') or item.get('display_subject_name') or item.get('subject_name')
        item['subject_id'] = local_group.get('subject_id') or item.get('subject_id')
        item['color'] = local_group.get('color') or item.get('display_color') or item.get('color')
        item['_shared_count'] = len(participants) if len(participants) > 1 else (2 if item.get('is_shared') or item.get('shared') else 0)
        day = _date(item['date'])
        if not start <= day <= end:
            continue
        begin, finish = _minutes(item['start']), _minutes(item['end'])
        if not 0 <= begin < finish <= 1440:
            raise ValueError('Le cours doit se terminer après son début, le même jour.')
        # A physical session can occur once in a joined snapshot for each member
        # promotion. Count its duration once for the promotion being exported.
        identity = (str(item['id']), day, begin, finish) if item.get('id') else None
        if identity is not None and identity in seen:
            continue
        if identity is not None:
            seen.add(identity)
        item.update(_day=day, _start=begin, _end=finish, _duration=finish - begin)
        records.append(item)
    records.sort(key=lambda item: (item['_day'], item['_start'], item['_end'], str(item.get('id', ''))))
    day_map = {}
    for source in days or []:
        item = dict(source)
        day = _date(item['date'])
        if start <= day <= end:
            item['kind'] = 'public_holiday' if item.get('public_holiday') is True else item.get('kind') if item.get('kind') in KIND_STYLES else 'unconfigured'
            day_map[day] = item
    for item in records:
        warnings = _course_warnings(item)
        holiday = day_map.get(item['_day'], {})
        if holiday.get('kind') == 'public_holiday' and not any(warning.get('code') == 'public_holiday' for warning in item.get('warnings') or [] if isinstance(warning, dict)):
            warnings.append('Jour férié : ' + _clean(holiday.get('label') or 'jour non planifiable') + ' - cours à déplacer.')
        item['_warning_labels'] = list(dict.fromkeys(warnings))
    return promotion, records, day_map, start, end


def _course_warnings(course):
    labels = []
    for warning in course.get('warnings') or []:
        message = warning.get('message') if isinstance(warning, dict) else warning if isinstance(warning, str) else None
        if message:
            labels.append(_clean(message))
    labels.extend(_clean(label) for label in course.get('warning_labels') or [] if isinstance(label, str) and label.strip())
    if not course.get('room_name') and not any('salle' in label.lower() for label in labels):
        labels.append('Salle non affectée')
    if not course.get('trainer_name') and not any('formateur' in label.lower() for label in labels):
        labels.append('Formateur à préciser')
    if not (course.get('subject_name') or course.get('title')) and not any('matière' in label.lower() for label in labels):
        labels.append('Matière à préciser')
    if course.get('incomplete') and not labels:
        labels.append('Données du cours à compléter')
    return list(dict.fromkeys(labels))


def _course_text(course, *, full=True, reference=None):
    subject = _clean(course.get('subject_name') or course.get('title') or 'Cours')
    title = _clean(course.get('title'))
    pieces = [f'<b>{_clock(course["_start"])} - {_clock(course["_end"])}</b>', '<b>' + escape(subject) + '</b>']
    if title and title != subject:
        pieces.append(escape(title))
    if full:
        pieces.append(escape(_clean(course.get('trainer_name') or 'Formateur à préciser')))
        pieces.append('Salle : ' + escape(_clean(course.get('room_name') or 'à préciser')))
        if course.get('_shared_count'):
            pieces.append('Cours commun - ' + str(course['_shared_count']) + ' promotions')
        if course.get('_promotion_labels'):
            pieces.append('Promotion' + ('s' if len(course['_promotion_labels']) > 1 else '') + ' : ' + escape(' / '.join(course['_promotion_labels'])))
        if course.get('_warning_labels'):
            pieces.append('<b>Attention : ' + escape(' ; '.join(course['_warning_labels'])) + '</b>')
    if reference:
        pieces.append('<b>Détail ' + str(reference).zfill(2) + '</b>')
    return '<br/>'.join(pieces)


def _course_color(course):
    if course.get('_warning_labels'):
        return WARNING
    color = str(course.get('color') or '')
    return colors.HexColor(color) if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else OLIVE


def _tint(color, white=.9):
    return colors.Color(color.red * (1-white) + white, color.green * (1-white) + white, color.blue * (1-white) + white)


def _lanes(records):
    """Keep overlapping entries readable instead of painting one on another."""
    groups, current, latest_end = [], [], -1
    for item in sorted(records, key=lambda value: (value['_start'], value['_end'])):
        if current and item['_start'] >= latest_end:
            groups.append(current)
            current = []
        current.append(item)
        latest_end = max(latest_end, item['_end']) if len(current) > 1 else item['_end']
    if current:
        groups.append(current)
    output = []
    for group in groups:
        endings, allocated = [], []
        for item in group:
            lane = next((index for index, end in enumerate(endings) if end <= item['_start']), len(endings))
            if lane == len(endings):
                endings.append(item['_end'])
            else:
                endings[lane] = item['_end']
            allocated.append((item, lane))
        output.extend((item, lane, len(endings)) for item, lane in allocated)
    return output


def _week_geometry(week, records, day_map, start, end, show_weekends):
    weekend_offsets = [item['_day'].weekday() for item in records]
    weekend_offsets.extend(day.weekday() for day, info in day_map.items() if week <= day <= week + timedelta(days=6) and info.get('kind') in ('school', 'company', 'public_holiday'))
    count = 7 if show_weekends or 6 in weekend_offsets else 6 if 5 in weekend_offsets else 5
    begin = min([480] + [item['_start'] // 60 * 60 for item in records])
    finish = max([1080] + [((item['_end'] + 59) // 60) * 60 for item in records])
    left, top, bottom = MARGIN + 40, PAGE_H - 151, 79
    width = PAGE_W - MARGIN - left
    return {'left': left, 'top': top, 'bottom': bottom, 'width': width, 'column': width/count,
            'count': count, 'begin': begin, 'finish': finish, 'scale': (top-bottom)/(finish-begin)}


def _week_plan(week, records, day_map, start, end, show_weekends):
    geometry = _week_geometry(week, records, day_map, start, end, show_weekends)
    by_day = defaultdict(list)
    for index, item in enumerate(records, 1):
        item = dict(item, _reference=index)
        by_day[item['_day']].append(item)
    blocks, details = [], []
    for day, items in by_day.items():
        for item, lane, total in _lanes(items):
            width = geometry['column'] / total - 4
            height = (item['_end'] - item['_start']) * geometry['scale'] - 3
            content_width = max(8, width - (22 if item.get('_warning_labels') else 10))
            paragraph, text_height = _paragraph(_course_text(item), content_width, size=8)
            if text_height > height - 8:
                paragraph, text_height = _paragraph(_course_text(item), content_width, size=7.3, leading=8.6)
            if text_height > height - 6:
                # The full text is retained on an explicitly referenced detail page.
                details.append(item)
                paragraph, text_height = _paragraph(_course_text(item, full=False, reference=item['_reference']), content_width, size=7.7)
                if text_height > height - 6:
                    concise = f'<b>Cours {item["_reference"]:02d}</b><br/>{_clock(item["_start"])} - {_clock(item["_end"])}<br/>Voir détail {item["_reference"]:02d}'
                    paragraph, text_height = _paragraph(concise, content_width, size=7.4)
                if text_height > height - 3:
                    # For tiny blocks the reference is still exact and never truncated.
                    paragraph, text_height = _paragraph(f'<b>{item["_reference"]:02d}</b>', content_width, size=7.2)
            blocks.append({'course': item, 'lane': lane, 'lanes': total, 'width': width,
                           'height': height, 'paragraph': paragraph, 'text_height': text_height})
    return {'kind': 'week', 'week': week, 'records': records, 'geometry': geometry, 'blocks': blocks, 'details': details}


def _detail_pages(week, details):
    if not details:
        return []
    width = PAGE_W - MARGIN * 2 - 26
    limit = PAGE_H - 151 - 75
    pages, current, used = [], [], 0
    for item in sorted(details, key=lambda value: value['_reference']):
        heading = f'<b>Détail {item["_reference"]:02d} - {WEEKDAYS[item["_day"].weekday()]} {_date_label(item["_day"], True)} - {_hours(item["_duration"])}</b>'
        paragraph, height = _paragraph(heading + '<br/>' + _course_text(item), width, size=9.1)
        parts = [paragraph]
        while parts:
            part = parts.pop(0)
            _, part_height = part.wrap(width, 10000)
            if part_height > limit - 22:
                split = part.split(width, limit - 22)
                if len(split) < 2:
                    raise ValueError('Le contenu de ce cours est trop long pour être exporté.')
                parts = split + parts
                continue
            card_height = part_height + 22
            if current and used + card_height + 8 > limit:
                pages.append({'kind': 'details', 'week': week, 'cards': current})
                current, used = [], 0
            current.append((part, card_height, _course_color(item)))
            used += card_height + 8
    if current:
        pages.append({'kind': 'details', 'week': week, 'cards': current})
    return pages


def _header(pdf, promotion, page_title, subtitle, *, logo_path):
    regular, bold = _fonts()
    pdf.setFillColor(INK)
    pdf.rect(0, PAGE_H-6, PAGE_W, 6, stroke=0, fill=1)
    pdf.setFillColor(OCHRE)
    pdf.rect(0, PAGE_H-6, PAGE_W*.24, 6, stroke=0, fill=1)
    logo = Path(logo_path) if logo_path else Path(__file__).resolve().parent / 'static/academy-official-logo.png'
    if logo.exists():
        pdf.setFillColor(INK)
        pdf.roundRect(MARGIN-3, PAGE_H-79, 162, 62, 7, fill=1, stroke=0)
        pdf.drawImage(str(logo), MARGIN, PAGE_H-71, width=154, height=46, preserveAspectRatio=True, anchor='c', mask='auto')
    else:
        pdf.setFont(bold, 13)
        pdf.drawString(MARGIN, PAGE_H-43, 'INTÉGRALE')
        pdf.setFont(regular, 11)
        pdf.drawString(MARGIN, PAGE_H-59, 'ACADEMY')
    heading_x = MARGIN + 178
    pdf.setFont(bold, 9)
    pdf.setFillColor(OLIVE)
    pdf.drawString(heading_x, PAGE_H-33, page_title.upper())
    paragraph, height = _paragraph(escape(_clean(promotion.get('nom') or 'Planning de formation')), PAGE_W-heading_x-MARGIN, size=13, bold=True)
    paragraph.drawOn(pdf, heading_x, PAGE_H-45-height)
    pdf.setFont(regular, 9)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN, PAGE_H-98, subtitle)
    pdf.setStrokeColor(LINE)
    pdf.line(MARGIN, PAGE_H-109, PAGE_W-MARGIN, PAGE_H-109)


def _legend(pdf, y=51):
    regular, _ = _fonts()
    x = MARGIN
    for kind, (label, fill, text) in KIND_STYLES.items():
        pdf.setFillColor(colors.HexColor(fill))
        pdf.setStrokeColor(colors.HexColor(text))
        pdf.roundRect(x, y-2, 9, 9, 2, fill=1, stroke=1)
        pdf.setFillColor(MUTED)
        pdf.setFont(regular, 7.3)
        pdf.drawString(x+15, y, label)
        x += pdfmetrics.stringWidth(label, regular, 7.3)+34


def _warning_triangle(pdf, x, y, size=10):
    """Vector mark keeps the exclamation visible with the built-in PDF fonts."""
    _, bold = _fonts()
    path = pdf.beginPath()
    path.moveTo(x, y)
    path.lineTo(x+size, y)
    path.lineTo(x+size/2, y+size*.87)
    path.close()
    pdf.setFillColor(WARNING)
    pdf.drawPath(path, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont(bold, size*.63)
    pdf.drawCentredString(x+size/2, y+size*.13, '!')


def _footer(pdf, page, total, generated_at):
    regular, _ = _fonts()
    pdf.setFont(regular, 7)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN, 23, 'Édité le ' + generated_at.strftime('%d/%m/%Y à %H:%M') + ' (heure de Paris) - sous réserve de modification.')
    pdf.drawRightString(PAGE_W-MARGIN, 23, f'{page} / {total}')


def _draw_week(pdf, plan, promotion, day_map, start, end, logo_path):
    week, geometry = plan['week'], plan['geometry']
    regular, bold = _fonts()
    last_day = week + timedelta(days=geometry['count']-1)
    subtitle = f'Semaine {week.isocalendar().week:02d}  |  Du {_date_label(max(start, week), True)} au {_date_label(min(end, last_day), True)}'
    _header(pdf, promotion, 'Planning de formation', subtitle, logo_path=logo_path)
    total = sum(item['_duration'] for item in plan['records'])
    pdf.setFillColor(INK)
    pdf.setFont(bold, 9)
    pdf.drawRightString(PAGE_W-MARGIN, PAGE_H-98, _hours(total) + ' de cours')
    x0, top, bottom, column = geometry['left'], geometry['top'], geometry['bottom'], geometry['column']
    day_labels = []
    for offset in range(geometry['count']):
        day = week+timedelta(days=offset)
        x = x0+offset*column
        in_range = start <= day <= end
        info = day_map.get(day, {})
        kind = info.get('kind', 'unconfigured')
        fill = colors.HexColor(KIND_STYLES[kind][1]) if in_range else colors.HexColor('#F0F1ED')
        pdf.setFillColor(fill)
        pdf.rect(x, bottom, column, top-bottom, fill=1, stroke=0)
        pdf.setFillColor(INK if in_range else MUTED)
        pdf.setFont(bold, 8.3)
        pdf.drawCentredString(x+column/2, top+18, WEEKDAYS[offset])
        pdf.setFont(regular, 7.5)
        pdf.drawCentredString(x+column/2, top+6, _date_label(day))
        if in_range and kind != 'unconfigured':
            label = _clean(info.get('label') or KIND_STYLES[kind][0])
            if kind == 'public_holiday':
                label += ' - non planifiable'
            # Day labels are shown above the grid in full in a compact paragraph.
            if kind != 'school' or not any(item['_day'] == day for item in plan['records']):
                paragraph, height = _paragraph(escape(label), column-14, size=8.8, bold=True, color=colors.HexColor(KIND_STYLES[kind][2]))
                day_labels.append((paragraph, height, x, fill))
        pdf.setStrokeColor(LINE)
        pdf.line(x, bottom, x, top+27)
    pdf.line(x0+geometry['width'], bottom, x0+geometry['width'], top+27)
    pdf.setFillColor(MUTED)
    pdf.setFont(regular, 7)
    pdf.drawString(MARGIN, top+10, 'Heures')
    for minute in range(geometry['begin'], geometry['finish']+1, 30):
        y = top-(minute-geometry['begin'])*geometry['scale']
        pdf.setStrokeColor(LINE if minute%60 == 0 else colors.HexColor('#E7ECE5'))
        pdf.setLineWidth(.55 if minute%60 == 0 else .3)
        pdf.line(x0, y, x0+geometry['width'], y)
        if minute%60 == 0:
            pdf.setFillColor(MUTED)
            pdf.setFont(regular, 7.3)
            pdf.drawRightString(x0-8, y-3, _clock(minute))
    for paragraph, height, x, fill in day_labels:
        pdf.setFillColor(fill)
        pdf.roundRect(x+4, top-18-height, column-8, height+10, 3, fill=1, stroke=0)
        paragraph.drawOn(pdf, x+7, top-14-height)
    for block in plan['blocks']:
        item = block['course']
        x = x0+item['_day'].weekday()*column+block['lane']*(column/block['lanes'])+2
        y = top-(item['_end']-geometry['begin'])*geometry['scale']+1.5
        color = _course_color(item)
        pdf.setFillColor(_tint(color))
        pdf.setStrokeColor(_tint(color,.5))
        pdf.roundRect(x, y, block['width'], max(.5,block['height']), 3, fill=1, stroke=1)
        pdf.setFillColor(color)
        pdf.rect(x, y+1, 2.5, max(.5,block['height']-2), fill=1, stroke=0)
        if item.get('_warning_labels'):
            size = min(9, max(5, block['height']-3))
            _warning_triangle(pdf, x+block['width']-size-2, y+block['height']-size-2, size)
        # An exceptionally short event is represented by a reference in its slot;
        # its complete subject/trainer/room/time remains on the following page.
        if block['text_height'] <= block['height']-2:
            block['paragraph'].drawOn(pdf, x+6, y+block['height']-4-block['text_height'])
        else:
            pdf.setFont(bold, 6)
            pdf.setFillColor(INK)
            pdf.drawString(x+5, y+1, f'{item["_reference"]:02d}')
    if not plan['records']:
        pdf.setFont(regular, 8.2)
        pdf.setFillColor(MUTED)
        pdf.drawString(x0, 65, 'Aucun cours programmé pour cette semaine.')
    elif plan['details']:
        pdf.setFont(regular, 7.2)
        pdf.setFillColor(MUTED)
        pdf.drawString(x0, 65, 'Les cours repérés par un numéro sont détaillés sur les pages suivantes, sans texte tronqué.')
    _legend(pdf)


def _draw_details(pdf, plan, promotion, logo_path):
    week = plan['week']
    _header(pdf, promotion, 'Détail des cours', f'Semaine {week.isocalendar().week:02d}  |  À partir du {_date_label(week, True)}', logo_path=logo_path)
    y = PAGE_H-126
    for paragraph, height, color in plan['cards']:
        pdf.setFillColor(_tint(color,.95))
        pdf.setStrokeColor(LINE)
        pdf.roundRect(MARGIN, y-height, PAGE_W-2*MARGIN, height, 5, fill=1, stroke=1)
        pdf.setFillColor(color)
        pdf.rect(MARGIN, y-height+4, 3, height-8, fill=1, stroke=0)
        _, text_height = paragraph.wrap(PAGE_W-2*MARGIN-26,10000)
        paragraph.drawOn(pdf, MARGIN+13, y-11-text_height)
        y -= height+8


def _months_between(start, end):
    current = date(start.year, start.month, 1)
    output=[]
    while current <= end:
        output.append(current)
        current = date(current.year+1,1,1) if current.month==12 else date(current.year,current.month+1,1)
    return output


def _draw_annual(pdf, plan, promotion, day_map, records, start, end, logo_path):
    months = plan['months']
    _header(pdf, promotion, 'Calendrier d’alternance', f'Du {_date_label(start, True)} au {_date_label(end, True)}', logo_path=logo_path)
    regular, bold = _fonts()
    course_dates = {item['_day'] for item in records}
    totals = defaultdict(int)
    for item in records:
        totals[(item['_day'].year,item['_day'].month)] += item['_duration']
    gap_x, gap_y = 15, 14
    width = (PAGE_W-MARGIN*2-gap_x*3)/4
    height = 123
    for index, month in enumerate(months):
        col,row = index%4,index//4
        x = MARGIN+col*(width+gap_x)
        y = PAGE_H-126-row*(height+gap_y)
        pdf.setFillColor(PAPER)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(x,y-height,width,height,6,fill=1,stroke=1)
        pdf.setFillColor(INK)
        pdf.setFont(bold,9)
        pdf.drawString(x+9,y-15,MONTHS[month.month-1].capitalize()+' '+str(month.year))
        month_total=totals[(month.year,month.month)]
        if month_total:
            pdf.setFont(regular,6.9)
            pdf.drawRightString(x+width-9,y-15,_hours(month_total))
        cell_w=(width-14)/7
        for weekday,letter in enumerate(('L','M','M','J','V','S','D')):
            pdf.setFillColor(MUTED)
            pdf.setFont(bold,6.9)
            pdf.drawCentredString(x+7+(weekday+.5)*cell_w,y-31,letter)
        offset=month.weekday()
        for number in range(1,monthrange(month.year,month.month)[1]+1):
            day=date(month.year,month.month,number)
            position=offset+number-1
            cell_x=x+7+(position%7)*cell_w
            cell_y=y-45-(position//7)*12
            if start<=day<=end:
                kind=day_map.get(day,{}).get('kind','unconfigured')
                if day in course_dates and kind != 'public_holiday':
                    kind='school'
                fill=colors.HexColor(KIND_STYLES[kind][1])
                tone=colors.HexColor(KIND_STYLES[kind][2])
            else:
                fill=colors.HexColor('#F2F3EF');tone=colors.HexColor('#B3B8AF')
            pdf.setFillColor(fill)
            pdf.roundRect(cell_x+1,cell_y-3,cell_w-2,11,2,fill=1,stroke=0)
            pdf.setFillColor(tone)
            pdf.setFont(bold if day in course_dates else regular,7)
            pdf.drawCentredString(cell_x+cell_w/2,cell_y, str(number))
    _legend(pdf,52)
    pdf.setFont(regular,7)
    pdf.setFillColor(MUTED)
    pdf.drawRightString(PAGE_W-MARGIN,52,_hours(sum(item['_duration'] for item in records))+' de cours sur la période')


def _holiday_pages(day_map):
    days = [(day, _clean(info.get('label') or 'Jour férié')) for day, info in sorted(day_map.items()) if info.get('kind') == 'public_holiday']
    return [dict(kind='public_holidays', days=days[index:index+24]) for index in range(0, len(days), 24)]


def _draw_holidays(pdf, plan, promotion, start, end, logo_path):
    _header(pdf, promotion, 'Jours fériés - non planifiables',
            f'Du {_date_label(start, True)} au {_date_label(end, True)}', logo_path=logo_path)
    regular, bold = _fonts()
    note, height = _paragraph('Ces journées sont bloquées dans le planning. Les cours déjà présents sur ces dates doivent être déplacés.', PAGE_W-2*MARGIN, size=9, color=HOLIDAY_RED)
    note.drawOn(pdf, MARGIN, PAGE_H-123-height)
    gap, width = 14, (PAGE_W-2*MARGIN-14)/2
    rows = max(1, (len(plan['days'])+1)//2)
    height = min(48, (PAGE_H-153-70)/rows-6)
    for index, (day, label) in enumerate(plan['days']):
        column, row = index//rows, index%rows
        x, top = MARGIN+column*(width+gap), PAGE_H-153-row*(height+6)
        pdf.setFillColor(colors.HexColor(KIND_STYLES['public_holiday'][1]))
        pdf.setStrokeColor(colors.HexColor('#E4B9B5'))
        pdf.roundRect(x, top-height, width, height, 4, fill=1, stroke=1)
        pdf.setFillColor(HOLIDAY_RED)
        pdf.setFont(bold, 8.2)
        if height >= 38:
            pdf.drawString(x+11, top-14, day.strftime('%d/%m/%Y'))
            paragraph, text_height = _paragraph(escape(label), width-22, size=10.6, bold=True, color=HOLIDAY_RED)
            paragraph.drawOn(pdf, x+11, top-23-text_height)
        else:
            pdf.drawString(x+9, top-16, day.strftime('%d/%m/%Y'))
            paragraph, text_height = _paragraph(escape(label), width-97, size=8.8, color=HOLIDAY_RED)
            paragraph.drawOn(pdf, x+87, top-(height-text_height)/2-text_height)


def _budget_minutes(value, *, positive=False):
    """Hours from SQLite/API to whole minutes; missing values remain unknown."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        return None
    return int((number * 60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _budget_pages(subjects):
    rows, seen = [], set()
    for source in subjects:
        item = dict(source)
        identity = item.get('id')
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        planned = _budget_minutes(item.get('planned_hours'), positive=True)
        if item.get('budget_configured') is False:
            planned = None
        scheduled = _budget_minutes(item.get('scheduled_hours'))
        subject = escape(_clean(item.get('name') or item.get('subject_name') or 'Matière'))
        trainer = escape(_clean(item.get('trainer_name') or 'Formateur à préciser'))
        paragraph, text_height = _paragraph('<b>' + subject + '</b><br/>' + trainer, 331, size=8.5, leading=10.6)
        if planned is None:
            status, tone = 'Volume à définir', OCHRE
        elif scheduled is None:
            status, tone = 'Planification non disponible', MUTED
        elif scheduled > planned:
            status, tone = '-' + _hours(scheduled-planned) + ' (dépassement)', colors.HexColor('#9B4E36')
        elif scheduled == planned:
            status, tone = 'Objectif atteint', OLIVE
        else:
            status, tone = 'À programmer : ' + _hours(planned-scheduled), MUTED
        status_paragraph, status_height = _paragraph(escape(status), 147, size=8.2, color=tone)
        rows.append(dict(paragraph=paragraph, text_height=text_height, planned=planned, scheduled=scheduled,
                         status=status_paragraph, status_height=status_height, height=max(36,text_height+15,status_height+15)))
    summary = dict(planned=sum(row['planned'] or 0 for row in rows),
                   scheduled=sum(row['scheduled'] or 0 for row in rows),
                   missing=sum(row['planned'] is None for row in rows),
                   unknown=sum(row['scheduled'] is None for row in rows), count=len(rows),
                   pending=sum(max(0,row['planned']-row['scheduled']) for row in rows if row['planned'] is not None and row['scheduled'] is not None),
                   over=sum(row['scheduled']>row['planned'] for row in rows if row['planned'] is not None and row['scheduled'] is not None))
    # Keep all subject names and teacher names; longer rows move to a new page.
    plans, current, used = [], [], 0
    limit = PAGE_H-219-72
    for row in rows:
        if row['height'] > limit:
            raise ValueError('Le libellé de cette matière est trop long pour être exporté.')
        if current and used+row['height'] > limit:
            plans.append(dict(kind='budget', rows=current, summary=summary))
            current, used = [], 0
        current.append(row)
        used += row['height']
    if current:
        plans.append(dict(kind='budget', rows=current, summary=summary))
    return plans


def _draw_budget(pdf, plan, promotion, logo_path):
    _header(pdf, promotion, 'Volumes annuels par matière',
            'Heures planifiées sur l’ensemble de la promotion, indépendamment de la période du calendrier.', logo_path=logo_path)
    regular, bold = _fonts()
    summary = plan['summary']
    gap, card_width = 12, (PAGE_W-MARGIN*2-24)/3
    pending = summary['pending']
    cards = [
        ('OBJECTIF ANNUEL', _hours(summary['planned']), f"{summary['missing']} volume(s) à définir" if summary['missing'] else f"{summary['count']} matière(s) renseignée(s)"),
        ('HEURES PLANIFIÉES', _hours(summary['scheduled']), 'Données incomplètes' if summary['unknown'] else 'Une séance commune comptée une fois par matière'),
        ('RESTE À PROGRAMMER', 'À compléter' if summary['missing'] or summary['unknown'] else _hours(pending), f"{summary['over']} dépassement(s) à vérifier" if summary['over'] else 'Consulter le solde de chaque matière ci-dessous'),
    ]
    top = PAGE_H-121
    for index, (label, number, detail) in enumerate(cards):
        x = MARGIN+index*(card_width+gap)
        pdf.setFillColor(PAPER if index != 0 else colors.HexColor('#F5ECD9'))
        pdf.setStrokeColor(LINE)
        pdf.roundRect(x,top-58,card_width,58,5,fill=1,stroke=1)
        pdf.setFillColor(MUTED);pdf.setFont(bold,6.9);pdf.drawString(x+11,top-14,label)
        pdf.setFillColor(INK);pdf.setFont(bold,14);pdf.drawString(x+11,top-33,number)
        paragraph,height=_paragraph(escape(detail),card_width-22,size=6.5,leading=8)
        paragraph.drawOn(pdf,x+11,top-42-height)
    widths = [347,109,109,PAGE_W-MARGIN*2-565]
    columns = [MARGIN]
    for width in widths:
        columns.append(columns[-1]+width)
    y=PAGE_H-196
    pdf.setFillColor(INK)
    pdf.roundRect(MARGIN,y-23,PAGE_W-MARGIN*2,23,4,fill=1,stroke=0)
    pdf.setFillColor(WHITE);pdf.setFont(bold,7.8)
    for index,label in enumerate(('Matière / formateur','Objectif annuel','Planifié','Solde')):
        pdf.drawString(columns[index]+8,y-15,label)
    y-=23
    for index,row in enumerate(plan['rows']):
        height=row['height']
        pdf.setFillColor(WHITE if index%2 else colors.HexColor('#F7F8F4'))
        pdf.rect(MARGIN,y-height,PAGE_W-MARGIN*2,height,fill=1,stroke=0)
        pdf.setStrokeColor(LINE);pdf.setLineWidth(.5)
        pdf.line(MARGIN,y-height,PAGE_W-MARGIN,y-height)
        row['paragraph'].drawOn(pdf,MARGIN+8,y-7-row['text_height'])
        pdf.setFont(bold,8.8);pdf.setFillColor(INK)
        pdf.drawString(columns[1]+8,y-17,_hours(row['planned']) if row['planned'] is not None else 'À définir')
        pdf.drawString(columns[2]+8,y-17,_hours(row['scheduled']) if row['scheduled'] is not None else 'Non disponible')
        row['status'].drawOn(pdf,columns[3]+8,y-7-row['status_height'])
        y-=height
    pdf.setFont(regular,7)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN,50,'Les heures communes sont attribuées à chacune des matières participantes, sans doubler la durée de la séance.')


def build_planning_pdf(promotion, events, days, date_start=None, date_end=None, mode='weekly', *, show_weekends=False, generated_at=None, logo_path=None, subjects=None):
    """Return A4-landscape PDF bytes for an inclusive weekly or annual period.

    Short slots never cause ellipses or hidden text: their complete metadata is
    placed on numbered detail pages. Unconfigured dates stay visibly distinct
    from company, school, holiday, and closed days. Annual mode can append subject
    budgets: scheduled_hours must cover the full promotion, not the export range.
    """
    promotion, records, day_map, start, end = _normalise(promotion, events, days, date_start, date_end)
    if mode not in ('weekly','annual','year','alternance'):
        raise ValueError('Mode d’export inconnu.')
    if generated_at is None:
        generated_at = datetime.now(ZoneInfo('Europe/Paris'))
    elif generated_at.tzinfo is not None:
        generated_at = generated_at.astimezone(ZoneInfo('Europe/Paris'))
    plans=[]
    if mode=='weekly':
        week=start-timedelta(days=start.weekday())
        while week<=end:
            selected=[item for item in records if week<=item['_day']<=week+timedelta(days=6)]
            plan=_week_plan(week,selected,day_map,start,end,show_weekends)
            plans.append(plan)
            plans.extend(_detail_pages(week,plan['details']))
            week+=timedelta(days=7)
    else:
        months=_months_between(start,end)
        plans=[{'kind':'annual','months':months[index:index+12]} for index in range(0,len(months),12)]
        plans.extend(_holiday_pages(day_map))
        if subjects:
            plans.extend(_budget_pages(subjects))
    buffer=BytesIO()
    pdf=canvas.Canvas(buffer,pagesize=(PAGE_W,PAGE_H),pageCompression=1)
    pdf.setTitle(_clean(promotion.get('nom') or 'Planning')+' - '+('Calendrier d’alternance' if mode!='weekly' else 'Planning de formation'))
    pdf.setAuthor('Intégrale Academy')
    pdf.setSubject('Planning de formation - heures locales Europe/Paris')
    for page,plan in enumerate(plans,1):
        if plan['kind']=='week':
            _draw_week(pdf,plan,promotion,day_map,start,end,logo_path)
        elif plan['kind']=='details':
            _draw_details(pdf,plan,promotion,logo_path)
        elif plan['kind']=='budget':
            _draw_budget(pdf,plan,promotion,logo_path)
        elif plan['kind']=='public_holidays':
            _draw_holidays(pdf,plan,promotion,start,end,logo_path)
        else:
            _draw_annual(pdf,plan,promotion,day_map,records,start,end,logo_path)
        _footer(pdf,page,len(plans),generated_at)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def build_portal_planning_pdf(portal_week, *, generated_at=None):
    """Export a pre-authorized portal week, without annual budgets or identity data.

    The caller must filter records to the authenticated person before calling.
    Explicitly selecting printable fields also prevents accidental use of an
    administrative snapshot's roster, notes, e-mail addresses or subject budgets.
    """
    role = portal_week.get('role')
    if role not in ('trainer', 'student'):
        raise ValueError('Rôle du planning invalide.')
    start, end = _date(portal_week['week_start']), _date(portal_week['week_end'])
    if not 0 <= (end-start).days <= 6:
        raise ValueError('L’export de l’espace personnel couvre une semaine au maximum.')
    allowed = ('id', 'date', 'start', 'end', 'title', 'subject_name', 'trainer_name',
               'room_name', 'is_shared', 'incomplete', 'warnings', 'warning_labels', 'color')
    records = []
    for source in portal_week.get('courses') or []:
        item = {key: source[key] for key in allowed if key in source}
        item['groups'] = [{key: group[key] for key in ('promotion_id', 'promotion_name', 'subject_name') if key in group}
                          for group in source.get('groups') or [] if isinstance(group, dict)]
        if role == 'trainer':
            names = source.get('promotion_names') or [group.get('promotion_name') for group in item['groups']]
            item['_promotion_labels'] = list(dict.fromkeys(_clean(name) for name in names if name))
        records.append(item)
    days = []
    for source in portal_week.get('days') or []:
        item = {key: source[key] for key in ('date', 'kind', 'label', 'public_holiday') if key in source}
        # Portal display labels contain the weekday/date; day_label carries the
        # official holiday or alternance label needed in the PDF calendar.
        item['label'] = source.get('day_label') or source.get('label') or ''
        days.append(item)
    heading = portal_week.get('heading') or ('Mon planning' if role == 'student' else 'Planning formateur')
    if role == 'student' and portal_week.get('promotion_label') and portal_week['promotion_label'] not in heading:
        heading += ' · ' + portal_week['promotion_label']
    return build_planning_pdf({'nom': heading}, records, days, start, end, mode='weekly',
                              generated_at=generated_at, show_weekends=True)
