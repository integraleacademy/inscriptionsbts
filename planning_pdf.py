"""Readable, self-contained planning exports (weekly calendar and yearly alternance).

Input contract matches planning.get_planning_snapshot: promotion, courses, days.
Dates are inclusive ISO dates; course start/end are local HH:MM (Europe/Paris).
No database, network access, or writes are performed by this module.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
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
WHITE = colors.white
KIND_STYLES = {
    'school': ('École', '#E5EEE5', '#476B53'),
    'company': ('Entreprise', '#F2E5CA', '#87602E'),
    'holiday': ('Vacances', '#EDE8D9', '#776D47'),
    'closed': ('Fermé / férié', '#E7E9E7', '#687169'),
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
    records = []
    for source in courses or []:
        item = dict(source)
        day = _date(item['date'])
        if not start <= day <= end:
            continue
        begin, finish = _minutes(item['start']), _minutes(item['end'])
        if not 0 <= begin < finish <= 1440:
            raise ValueError('Le cours doit se terminer après son début, le même jour.')
        item.update(_day=day, _start=begin, _end=finish, _duration=finish - begin)
        records.append(item)
    records.sort(key=lambda item: (item['_day'], item['_start'], item['_end'], str(item.get('id', ''))))
    day_map = {}
    for source in days or []:
        item = dict(source)
        day = _date(item['date'])
        if start <= day <= end:
            item['kind'] = item.get('kind') if item.get('kind') in KIND_STYLES else 'unconfigured'
            day_map[day] = item
    return promotion, records, day_map, start, end


def _course_text(course, *, full=True, reference=None):
    subject = _clean(course.get('subject_name') or course.get('title') or 'Cours')
    title = _clean(course.get('title'))
    pieces = [f'<b>{_clock(course["_start"])} - {_clock(course["_end"])}</b>', '<b>' + escape(subject) + '</b>']
    if title and title != subject:
        pieces.append(escape(title))
    if full:
        pieces.append(escape(_clean(course.get('trainer_name') or 'Formateur à préciser')))
        pieces.append('Salle : ' + escape(_clean(course.get('room_name') or 'à préciser')))
    if reference:
        pieces.append('<b>Détail ' + str(reference).zfill(2) + '</b>')
    return '<br/>'.join(pieces)


def _course_color(course):
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
    weekend_offsets.extend(day.weekday() for day, info in day_map.items() if week <= day <= week + timedelta(days=6) and info.get('kind') in ('school', 'company'))
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
            content_width = max(8, width - 10)
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
                if day in course_dates:
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


def build_planning_pdf(promotion, events, days, date_start=None, date_end=None, mode='weekly', *, show_weekends=False, generated_at=None, logo_path=None):
    """Return A4-landscape PDF bytes for an inclusive weekly or annual period.

    Short slots never cause ellipses or hidden text: their complete metadata is
    placed on numbered detail pages. Unconfigured dates stay visibly distinct
    from company, school, holiday, and closed days.
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
        else:
            _draw_annual(pdf,plan,promotion,day_map,records,start,end,logo_path)
        _footer(pdf,page,len(plans),generated_at)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
