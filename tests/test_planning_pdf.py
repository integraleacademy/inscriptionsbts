"""Planning PDF contract, readable long metadata, inclusive dates, and pagination."""
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
import pytest

from planning_pdf import build_planning_pdf, PAGE_W, PAGE_H


PROMOTION = {'id':'fake-promo','nom':'BTS MOS - 1re année 2026-2028','bts':'MOS','niveau':1,'rentree_annee':2026,
             'date_debut':'2026-09-01','date_fin':'2027-08-31'}
EDITED = datetime(2026,10,24,21,30)


def course(day='2026-10-19', start='09:00', end='12:00', **values):
    item={'id':'test-course','date':day,'start':start,'end':end,'subject_name':'Culture générale et expression',
          'trainer_name':'Camille Exemple','room_name':'Salle Olivier','title':'','color':'#5F7662'}
    item.update(values)
    return item


def pdf(events=(), days=(), start='2026-10-19',end='2026-10-25',**kwargs):
    return PdfReader(BytesIO(build_planning_pdf(PROMOTION, events, days, start,end,generated_at=EDITED,**kwargs)))


def content(reader):
    return '\n'.join(page.extract_text() for page in reader.pages)


def test_weekly_calendar_is_landscape_with_complete_course_metadata_and_hours():
    reader=pdf([course()])
    assert len(reader.pages)==1
    page=reader.pages[0]
    assert abs(float(page.mediabox.width)-PAGE_W)<.01
    assert abs(float(page.mediabox.height)-PAGE_H)<.01
    text=' '.join(content(reader).split())
    for value in ['BTS MOS - 1re année 2026-2028','Semaine 43','19 octobre 2026','3 h de cours',
                  '09:00 - 12:00','Culture générale et expression','Camille Exemple','Salle Olivier','1 / 1']:
        assert value in text
    assert 'Samedi' not in text and 'Dimanche' not in text


def test_multiple_weeks_include_empty_weeks_and_correct_page_numbers():
    reader=pdf([course(),course('2026-11-02',start='10:00',end='11:30')],end='2026-11-08')
    assert len(reader.pages)==3
    texts=[page.extract_text() for page in reader.pages]
    assert '3 h de cours' in texts[0]
    assert 'Aucun cours programmé' in texts[1]
    assert '1 h 30 de cours' in texts[2]
    assert '1 / 3' in texts[0] and '3 / 3' in texts[2]


def test_weekend_is_shown_when_there_is_a_sunday_course():
    reader=pdf([course('2026-10-25',start='09:15',end='11:45')])
    text=content(reader)
    assert 'Samedi' in text and 'Dimanche' in text
    assert '09:15 - 11:45' in text and '2 h 30 de cours' in text


def test_unconfigured_weekend_does_not_widen_the_week():
    days=[{'date':'2026-10-24','kind':'unconfigured'},{'date':'2026-10-25','kind':'closed'}]
    assert 'Dimanche' not in content(pdf(days=days))
    assert 'Dimanche' in content(pdf(days=days,show_weekends=True))


def test_long_course_names_are_complete_on_detail_pages_without_ellipsis():
    subject='Préparation et mise en œuvre d’une prestation de sécurité dans un environnement professionnel complexe'
    trainer='Alexandra Exemple - Intervenante en stratégie et prévention des risques professionnels'
    room='Salle de simulation opérationnelle - bâtiment pédagogique - deuxième étage'
    reader=pdf([course(start='09:00',end='09:30',subject_name=subject,trainer_name=trainer,room_name=room,
                       title='Étude de cas : coordination des équipes et adaptation aux exigences du client')])
    assert len(reader.pages)==2
    text=content(reader)
    assert 'Détail 01' in text and '2 / 2' in text
    flattened=' '.join(text.split())
    assert subject in flattened and trainer in flattened and room in flattened
    assert '…' not in text and '...' not in text
    assert '09:00 - 09:30' in text


def test_overlap_never_loses_either_course_and_dense_details_paginate():
    events=[]
    for index in range(18):
        day=date(2026,10,19)+timedelta(days=index%5)
        events.append(course(day.isoformat(),start='09:00',end='09:30',id=str(index),
                             subject_name=f'Sujet distinct {index:02d} - Communication et organisation détaillée des prestations professionnelles',
                             trainer_name=f'Formateur numéro {index:02d}'))
    reader=pdf(events)
    assert len(reader.pages)>=3
    text=' '.join(content(reader).split())
    for index in range(18):
        assert f'Sujet distinct {index:02d}' in text and f'Formateur numéro {index:02d}' in text
    assert '9 h de cours' in text


def test_html_like_strings_are_rendered_as_text_not_reportlab_markup():
    reader=pdf([course(subject_name='Sécurité <script> & prévention',trainer_name='Nom <b>inconnu</b>')])
    text=' '.join(content(reader).split())
    assert 'Sécurité <script> & prévention' in text
    assert 'Nom <b>inconnu</b>' in text


def test_company_holiday_and_closed_labels_and_unconfigured_dates_are_explicit():
    days=[{'date':'2026-10-19','kind':'company','label':'Entreprise : mise en pratique'},
          {'date':'2026-10-20','kind':'holiday','label':'Vacances pédagogiques'},
          {'date':'2026-10-21','kind':'closed','label':'Fermeture exceptionnelle'},
          {'date':'2026-10-22','kind':'unconfigured'}]
    text=' '.join(content(pdf(days=days)).split())
    for label in ['Entreprise : mise en pratique','Vacances pédagogiques','Fermeture exceptionnelle','Non défini']:
        assert label in text


def test_annual_calendar_uses_12_months_per_page_and_total_hours():
    reader=pdf([course()],start='2026-09-01',end='2028-08-31',mode='annual')
    assert len(reader.pages)==2
    first,second=[page.extract_text() for page in reader.pages]
    assert 'Septembre 2026' in first and 'Août 2027' in first
    assert 'Septembre 2027' in second and 'Août 2028' in second
    assert 'Calendrier d’alternance'.upper() in first
    assert '3 h de cours sur la période' in first
    assert '2 / 2' in second


def test_export_range_is_inclusive_and_hours_are_computed_not_trusted():
    reader=pdf([course('2026-10-18'),course('2026-10-19',duration_minutes=99999),course('2026-10-20')],end='2026-10-19')
    text=content(reader)
    assert '3 h de cours' in text and text.count('Camille Exemple')==1


@pytest.mark.parametrize('updates',[
    {'start':'12:00','end':'09:00'}, {'start':'25:00','end':'26:00'}, {'start':'12:60','end':'13:00'}])
def test_invalid_event_times_are_rejected(updates):
    with pytest.raises(ValueError):
        pdf([course(**updates)])


def test_invalid_ranges_and_modes_are_rejected():
    with pytest.raises(ValueError):pdf(start='2026-10-25',end='2026-10-19')
    with pytest.raises(ValueError):pdf(start='2026-01-01',end='2030-01-01')
    with pytest.raises(ValueError):pdf(mode='unknown')
