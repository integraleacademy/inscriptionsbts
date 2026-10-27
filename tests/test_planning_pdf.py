"""Planning PDF contract, readable long metadata, inclusive dates, and pagination."""
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
import pytest

from planning_pdf import build_planning_pdf, build_portal_planning_pdf, PAGE_W, PAGE_H


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


def shared_course(**updates):
    groups=[
        {'promotion_id':'fake-promo','promotion_name':PROMOTION['nom'],'subject_id':'mos-english','subject_name':'Anglais - métiers de la sécurité','color':'#5F7662'},
        {'promotion_id':'other-promo','promotion_name':'BTS MCO - 1re année','subject_id':'mco-english','subject_name':'Anglais - commerce et relation client','color':'#AB7D2F'},
    ]
    return course(start='09:00',end='13:00',id='shared-session',promotion_id='other-promo',subject_id='mco-english',
                  subject_name='Anglais principal',groups=groups,promotion_ids=['fake-promo','other-promo'],is_shared=True,**updates)


def test_shared_session_is_counted_once_with_local_subject_for_each_promotion():
    session=shared_course()
    first=pdf([session,dict(session)])
    first_text=' '.join(content(first).split())
    assert len(first.pages)==1
    assert '4 h de cours' in first_text and '8 h de cours' not in first_text
    assert first_text.count('Camille Exemple')==1
    assert 'Anglais - métiers de la sécurité' in first_text
    assert 'Anglais - commerce et relation client' not in first_text
    assert 'Cours commun - 2 promotions' in first_text
    other={**PROMOTION,'id':'other-promo','nom':'BTS MCO - 1re année'}
    second=PdfReader(BytesIO(build_planning_pdf(other,[session,dict(session)],[], '2026-10-19','2026-10-25',generated_at=EDITED)))
    second_text=' '.join(content(second).split())
    assert '4 h de cours' in second_text and 'Anglais - commerce et relation client' in second_text
    assert 'Anglais - métiers de la sécurité' not in second_text
    assert second_text.count('Camille Exemple')==1


def test_shared_session_not_exported_for_non_participant_and_display_alias_supported():
    foreign=shared_course()
    foreign['promotion_ids']=['other-promo']
    foreign['groups']=[foreign['groups'][1]]
    assert 'Aucun cours programmé' in content(pdf([foreign]))
    local=course(display_subject_name='Matière locale au groupe',display_color='#AB7D2F')
    text=' '.join(content(pdf([local])).split())
    assert 'Matière locale au groupe' in text and 'Culture générale' not in text


def test_annual_shared_hours_and_budgets_use_full_promotion_totals():
    subjects=[{'id':'mos-english','name':'Anglais - métiers de la sécurité','trainer_name':'Camille Exemple',
               'planned_hours':80,'scheduled_hours':35.5,'remaining_hours':44.5,'budget_configured':True}]
    reader=pdf([shared_course(),shared_course()],start='2026-10-01',end='2026-10-31',mode='annual',subjects=subjects)
    assert len(reader.pages)==2
    calendar=reader.pages[0].extract_text()
    budget=' '.join(reader.pages[1].extract_text().split())
    assert '4 h de cours sur la période' in calendar
    assert 'VOLUMES ANNUELS PAR MATIÈRE' in budget
    assert '80 h' in budget and '35 h 30' in budget and 'À programmer : 44 h 30' in budget
    assert 'indépendamment de la période du calendrier' in budget
    assert budget.count('Anglais - métiers de la sécurité')==1
    assert '2 / 2' in budget


def test_missing_and_exceeded_budgets_are_explicit_not_false_zero():
    subjects=[
        {'id':'missing','name':'Matière à compléter','planned_hours':None,'scheduled_hours':2,'budget_configured':False},
        {'id':'over','name':'Matière dépassée','planned_hours':10,'scheduled_hours':12.5,'budget_configured':True},
        {'id':'remaining','name':'Matière à programmer','planned_hours':20,'scheduled_hours':1,'budget_configured':True},
    ]
    text=' '.join(content(pdf(mode='annual',subjects=subjects)).split())
    assert 'Volume à définir' in text and '1 volume(s) à définir' in text
    assert '-2 h 30 (dépassement)' in text and 'À programmer : 19 h' in text
    assert 'Données incomplètes' not in text


def test_annual_budget_long_subjects_paginate_without_truncation_or_duplicate_rows():
    subjects=[{'id':str(index),'name':f'Matière {index:02d} - Préparation et organisation des prestations dans un environnement professionnel complexe',
               'trainer_name':'Alexandra Exemple - Intervenante spécialisée en stratégie et prévention',
               'planned_hours':30.25,'scheduled_hours':12.75,'budget_configured':True} for index in range(18)]
    reader=pdf(mode='annual',subjects=subjects+[dict(subjects[0])])
    assert len(reader.pages)>=4
    text=' '.join(content(reader).split())
    for index in range(18):
        assert text.count(f'Matière {index:02d}')==1
    assert '30 h 15' in text and '12 h 45' in text and 'À programmer : 17 h 30' in text
    assert '…' not in text


def test_missing_annual_scheduled_hours_are_not_filled_with_selected_period_hours():
    subjects=[{'id':'subject','name':'Culture générale','planned_hours':80,'budget_configured':True}]
    text=' '.join(content(pdf([course()],mode='annual',subjects=subjects)).split())
    assert 'Données incomplètes' in text and 'Planification non disponible' in text
    assert 'À programmer : 77 h' not in text


@pytest.mark.parametrize('view', ['weekly', 'annual'])
def test_flask_export_for_secondary_promotion_uses_local_subject_and_full_year_budget(tmp_path, view):
    """Actual SQL snapshot + Flask route + PDF, using a private synthetic database."""
    import sqlite3
    from flask import Flask, session
    from planning import ensure_planning_schema, register_planning

    database = tmp_path / 'shared-export.sqlite'

    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection

    with connect() as connection:
        connection.execute('CREATE TABLE candidats(id TEXT PRIMARY KEY)')
        ensure_planning_schema(connection)
        connection.execute('CREATE TABLE trainers(id TEXT PRIMARY KEY,nom TEXT,prenom TEXT,email TEXT,active INTEGER,version INTEGER)')
        connection.execute('INSERT INTO trainers VALUES(?,?,?,?,?,?)', ('trainer', 'Exemple', 'Camille', 'camille@example.test', 1, 1))
        connection.execute('INSERT INTO planning_rooms VALUES(?,?,?)', ('room', 'Salle Acacia', 1))
        for pid, code, sid, name, target in [
            ('primary', 'MCO', 'primary-subject', 'Anglais commercial', 80),
            ('secondary', 'MOS', 'secondary-subject', 'Anglais des métiers de la sécurité', 60),
        ]:
            connection.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (pid, 'BTS '+code+' - 1re année', code, 1, 2026, '2027-01-01', '2027-03-31', 1, '2026-10-01', '2026-10-01'))
            connection.execute('INSERT INTO trainer_promotions VALUES(?,?)', ('trainer', pid))
            connection.execute('INSERT INTO planning_subjects VALUES(?,?,?,?,?,?)', (sid, pid, name, 'trainer', '#5F7662', target))
    application = Flask(__name__)
    application.secret_key = 'pdf-integration-test-only'
    application.config['TESTING'] = True
    register_planning(application, connect, lambda: bool(session.get('admin_ok')))
    client = application.test_client()
    url = '/admin/planning/export.pdf?promotion_id=secondary&start=2027-01-04&end=2027-01-10&view='+view
    assert client.get(url).status_code == 403
    with client.session_transaction() as state:
        state['admin_ok'] = True
        state['_planning_csrf'] = 'export-test'
    headers = {'X-CSRF-Token': 'export-test'}
    for pid in ('primary', 'secondary'):
        response = client.post('/admin/planning/api/calendar/rules', headers=headers, json={
            'promotion_id': pid, 'start_date': '2027-01-01', 'end_date': '2027-03-31',
            'weekdays': [0,1,2,3,4], 'kind': 'school', 'label': 'École',
        })
        assert response.status_code == 200, response.json
    for day in ('2027-01-04', '2027-01-11'):
        response = client.post('/admin/planning/api/courses', headers=headers, json={
            'promotion_id': 'primary', 'subject_id': 'primary-subject', 'room_id': 'room',
            'date': day, 'start': '09:00', 'end': '12:00',
            'shared': [{'promotion_id': 'secondary', 'subject_id': 'secondary-subject'}],
        })
        assert response.status_code == 200, response.json
    response = client.get(url)
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    assert response.headers['Content-Disposition'].startswith('inline;')
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    reader = PdfReader(BytesIO(response.data))
    text = ' '.join(content(reader).split())
    assert 'BTS MOS - 1re année' in text
    assert 'Anglais commercial' not in text
    assert text.count('Anglais des métiers de la sécurité') == 1
    if view == 'weekly':
        assert len(reader.pages) == 1
        assert '3 h de cours' in text and '6 h de cours' not in text
        assert text.count('EXEMPLE Camille') == 1
        assert 'Salle : Salle Acacia' in text and 'Cours commun - 2 promotions' in text
    else:
        assert len(reader.pages) == 2  # annual calendar followed by the subject budget
        assert '3 h de cours sur la période' in text
        assert 'VOLUMES ANNUELS PAR MATIÈRE' in text
        assert '60 h' in text and '6 h' in text and 'À programmer : 54 h' in text
        assert 'À programmer : 57 h' not in text  # outside-export course still consumes annual budget
    with connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0] == 2
        assert connection.execute('SELECT COUNT(*) FROM planning_course_groups').fetchone()[0] == 4


def test_public_holiday_is_red_blocked_and_named_in_weekly_pdf():
    day = {'date': '2026-11-11', 'kind': 'public_holiday', 'label': 'Armistice 1918', 'public_holiday': True}
    reader = pdf(days=[day], start='2026-11-09', end='2026-11-15')
    text = ' '.join(content(reader).split())
    assert 'Armistice 1918 - non planifiable' in text
    assert 'Jour férié' in text
    operators = reader.pages[0].get_contents().get_data().decode('latin1')
    assert '.968627 .866667 .858824 rg' in operators
    assert '.647059 .207843 .207843 rg' in operators


def test_annual_holiday_stays_red_even_with_legacy_course_and_lists_exact_name():
    day = {'date': '2026-11-11', 'kind': 'public_holiday', 'label': 'Armistice 1918'}
    reader = pdf([course('2026-11-11')], days=[day], start='2026-11-01', end='2026-11-30', mode='annual')
    assert len(reader.pages) == 2
    text = ' '.join(content(reader).split())
    assert 'JOURS FÉRIÉS - NON PLANIFIABLES' in text
    assert '11/11/2026' in text and 'Armistice 1918' in text
    assert 'Les cours déjà présents sur ces dates doivent être déplacés.' in text
    operators = reader.pages[0].get_contents().get_data().decode('latin1')
    # One red day cell plus the red legend: an existing course must not turn it green.
    assert operators.count('.968627 .866667 .858824 rg') >= 2
    assert '3 h de cours sur la période' in text


def test_weekend_public_holiday_is_visible_and_legacy_course_is_flagged():
    day = {'date': '2026-11-01', 'kind': 'public_holiday', 'label': 'Toussaint'}
    reader = pdf([course('2026-11-01', start='08:00', end='12:00')], days=[day], start='2026-10-26', end='2026-11-01')
    text = ' '.join(content(reader).split())
    assert 'Dimanche' in text and 'Toussaint - non planifiable' in text
    assert 'cours à déplacer' in text
    assert text.count('Camille Exemple') == 1


def test_missing_room_course_is_orange_with_vector_warning_and_reason():
    reader = pdf([course(start='08:00', end='12:00', room_name=None)])
    text = ' '.join(content(reader).split())
    assert 'Attention : Salle non affectée' in text
    assert '!' in text
    operators = reader.pages[0].get_contents().get_data().decode('latin1')
    assert operators.count('.717647 .396078 .094118 rg') >= 2
    assert '4 h de cours' in text


def test_incomplete_shared_course_keeps_all_reasons_in_numbered_detail():
    warnings = [{'code': 'trainer_inactive', 'message': 'Formateur inactif : réaffectez le cours'},
                {'code': 'room_inactive', 'message': 'Salle indisponible <à confirmer>'},
                {'code': 'annual_hours_missing', 'message': 'Volume annuel à définir'}]
    item = shared_course(incomplete=True, warnings=warnings)
    item.update(start='09:00', end='09:30')
    reader = pdf([item])
    text = ' '.join(content(reader).split())
    assert len(reader.pages) >= 2
    for warning in warnings:
        assert warning['message'] in text
    assert 'Cours commun - 2 promotions' in text and 'Détail 01' in text
    assert 'Anglais - métiers de la sécurité' in text


def portal_week(role='trainer'):
    return {'role': role, 'heading': 'Planning de Camille Exemple' if role == 'trainer' else 'Mon planning · BTS MOS',
            'week_start': '2026-11-09', 'week_end': '2026-11-15',
            'days': [{'date': '2026-11-11', 'kind': 'public_holiday', 'label': 'Armistice 1918'}],
            'courses': [course('2026-11-10', start='08:00', end='12:00', subject_name='Anglais local',
                               promotion_names=['BTS MOS', 'BTS MCO'],
                               groups=[{'promotion_id': 'one', 'promotion_name': 'BTS MOS', 'subject_name': 'Anglais MOS'},
                                       {'promotion_id': 'two', 'promotion_name': 'BTS MCO', 'subject_name': 'Anglais MCO'}],
                               is_shared=True, email='private@example.test', note='PRIVATE_NOTE',
                               students=[{'nom': 'PRIVATE_STUDENT'}])],
            'subjects': [{'name': 'PRIVATE_BUDGET', 'planned_hours': 123, 'scheduled_hours': 15}]}


@pytest.mark.parametrize('role', ['trainer', 'student'])
def test_portal_export_is_weekly_scoped_and_never_prints_admin_data(role):
    reader = PdfReader(BytesIO(build_portal_planning_pdf(portal_week(role), generated_at=EDITED)))
    text = ' '.join(content(reader).split())
    assert portal_week(role)['heading'].replace('·', '·') in text
    assert 'Anglais local' in text and '4 h de cours' in text
    assert 'Armistice 1918 - non planifiable' in text
    for private in ['private@example.test', 'PRIVATE_NOTE', 'PRIVATE_STUDENT', 'PRIVATE_BUDGET', 'VOLUMES ANNUELS']:
        assert private not in text
    if role == 'trainer':
        assert 'Promotions : BTS MOS / BTS MCO' in text
    else:
        assert 'BTS MCO' not in text


def test_portal_export_rejects_unknown_role_or_multiweek_payload():
    data = portal_week()
    data['role'] = 'admin'
    with pytest.raises(ValueError):build_portal_planning_pdf(data)
    data = portal_week()
    data['week_end'] = '2026-11-30'
    with pytest.raises(ValueError):build_portal_planning_pdf(data)


def test_portal_export_uses_holiday_label_and_student_promotion_from_real_snapshot_shape():
    snapshot = portal_week('student')
    snapshot.update(heading='Mon planning', promotion_label='BTS MOS · 1re année')
    snapshot['days'][0].update(label='Mercredi 11 novembre 2026', day_label='Armistice 1918')
    reader = PdfReader(BytesIO(build_portal_planning_pdf(snapshot, generated_at=EDITED)))
    text = ' '.join(content(reader).split())
    assert 'Mon planning · BTS MOS · 1re année' in text
    assert 'Armistice 1918 - non planifiable' in text
    assert 'Mercredi 11 novembre 2026 - non planifiable' not in text
