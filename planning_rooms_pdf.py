"""A printable weekly room matrix; long room rows continue on another page."""
from datetime import date, datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from planning_pdf import _fonts, _paragraph

PALETTE={'A3P':('#e7f5eb','#236b3a'),'APS':('#eaf2ff','#2458a3'),
         'DESP':('#fff0df','#9e4b0e'),'SSIAP':('#ffeded','#aa2830'),
         'BTS':('#f2eaff','#6839a3'),'OTHER':('#eef2f6','#465568'),'UNAVAILABLE':('#eceef2','#455265')}
WEEKDAYS=('Lun.','Mar.','Mer.','Jeu.','Ven.','Sam.','Dim.')


def build_pdf(data):
    output=BytesIO();width,height=landscape(A4);margin=25;room_width=87
    day_width=(width-2*margin-room_width)/7
    pdf=canvas.Canvas(output,pagesize=(width,height));pdf.setTitle('Planning des salles - Intégrale Academy')
    regular,bold=_fonts();page=0;y=0
    first,last=map(date.fromisoformat,(data['start'],data['end']))
    generated=datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M')
    week=first-timedelta(days=first.weekday())

    def new_page(days):
        nonlocal page,y
        if page:pdf.showPage()
        page+=1
        pdf.setFillColor(colors.HexColor('#20344d'));pdf.setFont(bold,19)
        pdf.drawString(margin,height-38,'Planning des salles')
        pdf.setFont(regular,9)
        pdf.drawString(margin,height-55,f'Intégrale Academy · du {first:%d/%m/%Y} au {last:%d/%m/%Y} · heures de Paris')
        x=margin
        for code,(bg,ink) in PALETTE.items():
            label={'UNAVAILABLE':'Indisponible','OTHER':'Autre créneau'}.get(code,code)
            pdf.setFillColor(colors.HexColor(bg));pdf.roundRect(x,height-80,87,16,3,fill=1,stroke=0)
            pdf.setFillColor(colors.HexColor(ink));pdf.setFont(bold,8);pdf.drawString(x+6,height-75,label);x+=94
        pdf.setStrokeColor(colors.HexColor('#20344d'));pdf.setLineWidth(2)
        pdf.roundRect(x,height-80,87,16,3,fill=0,stroke=1)
        pdf.setFillColor(colors.HexColor('#20344d'));pdf.drawString(x+6,height-75,'EXAMEN')
        pdf.setFillColor(colors.HexColor('#657187'));pdf.setFont(regular,7)
        pdf.drawString(margin,18,'Export du '+generated+' · Les changements ultérieurs ne figurent pas dans ce document.')
        pdf.drawRightString(width-margin,18,'Page '+str(page))
        y=height-98
        pdf.setFillColor(colors.HexColor('#edf1f7'));pdf.rect(margin,y-30,width-2*margin,30,fill=1,stroke=0)
        pdf.setFillColor(colors.HexColor('#20344d'));pdf.setFont(bold,8);pdf.drawString(margin+7,y-18,'Salle')
        for i,day in enumerate(days):
            x=margin+room_width+i*day_width
            pdf.drawString(x+6,y-12,WEEKDAYS[i]);pdf.setFont(regular,8)
            pdf.drawString(x+6,y-24,day.strftime('%d/%m/%Y'));pdf.setFont(bold,8)
        y-=30

    def card(row):
        bg,ink=PALETTE.get(row.get('formation'),('#f3f5f7','#465568'))
        hours='Journée entière' if row['start']=='00:00' and row['end']=='24:00' else row['start']+'–'+row['end']
        lines=['<b>'+escape(hours)+'</b>',escape(str(row['title']))]
        if not row.get('room_id'):lines.append('<b>À AFFECTER</b>')
        if row.get('promotion_name'):lines.append(escape(row['promotion_name']))
        if row.get('presence_start'):lines.append('Présentiel dès le '+date.fromisoformat(row['presence_start']).strftime('%d/%m/%Y'))
        if row.get('exam'):lines.append('<b>EXAMEN'+(' · journée réservée' if row.get('exam_full_day') and row.get('room_id') else '')+'</b>')
        if row.get('conflict'):lines.append('<b>CONFLIT À CORRIGER</b>')
        if row.get('pending'):lines.append('Confirmation en cours')
        paragraph,h=_paragraph('<br/>'.join(lines),day_width-17,size=7.1,color=colors.HexColor(ink),leading=9.3)
        return paragraph,h+12,bg,row.get('conflict'),row.get('exam'),ink

    while week<=last:
        days=[week+timedelta(days=i) for i in range(7)];new_page(days)
        for room in data['rooms']:
            columns=[]
            for day in days:
                rows=sorted((r for r in data['reservations'] if r['room_id']==room['id'] and r['date']==day.isoformat()),key=lambda r:r['start_min'])
                columns.append([card(r) for r in rows])
            continued=False
            while True:
                chunks=[]
                for column in columns:
                    chunk=[];used=0
                    while column and used+column[0][1]+5<=350:
                        item=column.pop(0);chunk.append(item);used+=item[1]+5
                    chunks.append(chunk)
                # Titles have a bounded length; no card may silently disappear.
                if any(columns[i] and not chunks[i] for i in range(7)):
                    raise ValueError('Un intitulé de réservation est trop long pour le PDF.')
                label=escape(room['name'])+(' (suite)' if continued else '')
                name,nh=_paragraph('<b>'+label+'</b>',room_width-12,size=8)
                row_height=max(45,nh+14,max((sum(c[1]+5 for c in col)+10 for col in chunks),default=0))
                if y-row_height<38:new_page(days)
                pdf.setStrokeColor(colors.HexColor('#dce2ea'));pdf.setLineWidth(.5)
                pdf.setFillColor(colors.HexColor('#f7f8fb'));pdf.rect(margin,y-row_height,room_width,row_height,fill=1,stroke=1)
                name.drawOn(pdf,margin+6,y-7-nh)
                for i,chunk in enumerate(chunks):
                    x=margin+room_width+i*day_width
                    pdf.setStrokeColor(colors.HexColor('#dce2ea'));pdf.setLineWidth(.5)
                    pdf.rect(x,y-row_height,day_width,row_height,fill=0,stroke=1)
                    top=y-5
                    for para,h,bg,conflict,exam,ink in chunk:
                        pdf.setFillColor(colors.HexColor(bg));pdf.setStrokeColor(colors.HexColor('#b42338' if conflict else ink if exam else bg))
                        pdf.setLineWidth(2 if exam else 1 if conflict else .5)
                        pdf.roundRect(x+4,top-h,day_width-8,h,3,fill=1,stroke=1)
                        para.drawOn(pdf,x+8,top-h+6);top-=h+5
                    if not chunk and not continued:
                        pdf.setFillColor(colors.HexColor('#87918e'));pdf.setFont(regular,7)
                        pdf.drawString(x+7,y-18,('—' if room.get('unassigned') else 'Libre') if first<=days[i]<=last else 'Hors période')
                y-=row_height;continued=True
                if not any(columns):break
        week+=timedelta(days=7)
    pdf.save();return output.getvalue()
