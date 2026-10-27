"""Real parser geometry + signed admin workflow, annual isolation and atomicity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import planning
from planning_import_pdf import ImportPDFError, parse_ypareo_pdf
from planning_import import suggest_subject, suggest_trainer
from test_planning import db, app, client, admin, call, BASE

PERIOD = dict(start_date='2026-09-01', end_date='2027-07-01')


def pdf_bytes(monday=date(2027, 1, 4), declared=2, subject='Matiere s1', teacher='M. NOM t1 P.', empty=False, shift=0):
    """Synthetic vector export: no student's file or real trainer data in git."""
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=(842, 595))
    c.setFont('Helvetica', 8)
    c.drawString(40, 559, f'Planning groupe - APP BTS MOS 2026-2028 Semaine S {monday.isocalendar().week:02d} - {0 if empty else declared}h')
    months = 'janvier février mars avril mai juin juillet août septembre octobre novembre décembre'.split()
    for i, wd in enumerate(['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi']):
        day = monday + timedelta(days=i)
        c.drawCentredString(150 + i*140, 535, f'{wd} {day.day} {months[day.month-1]}')
    for hour in range(8, 18):
        c.drawString(50, 595-70-(hour-8)*32-6, f'{hour:02d}:00')
    for x in range(80, 781, 140):
        c.rect(x, 595-390, .6, 320, fill=1, stroke=0)
    if not empty:
        # 09:00–11:00, padding 4 px, stripe width 6 px at a 0.6 scale.
        c.rect(82.4, 595-(70+3*32-2.4+shift), 3.6, 2*32-4.8, fill=1, stroke=0)
        c.drawString(89, 595-(70+32+2.4+shift)-6, subject)
        c.drawString(89, 595-(70+32+2.4+shift)-18, 'APP BTS MOS 2026-2028')
        c.drawString(89, 595-(70+32+2.4+shift)-30, teacher)
    c.save()
    return stream.getvalue()


def test_vector_pdf_reads_dates_times_subjects_and_totals():
    parsed = parse_ypareo_pdf(pdf_bytes(), PERIOD)
    assert parsed['minutes'] == 120 and parsed['pages'] == 1
    assert len(parsed['rows']) == 1
    row = parsed['rows'][0]
    assert (row['date'], row['start'], row['end'], row['subject'], row['trainer']) == (
        '2027-01-04', '09:00', '11:00', 'Matiere s1', 'M. NOM t1 P.')


@pytest.mark.parametrize('content', [b'not a pdf', pdf_bytes(declared=3), pdf_bytes(shift=1.5), pdf_bytes(empty=True)])
def test_unreliable_files_do_not_silently_import(content):
    with pytest.raises(ImportPDFError):
        parse_ypareo_pdf(content, PERIOD)


def test_year_rollover_and_leap_date_are_determined_by_calendar():
    parsed = parse_ypareo_pdf(pdf_bytes(monday=date(2026, 12, 28)), PERIOD)
    assert parsed['first_date'] == '2026-12-28'
    parsed = parse_ypareo_pdf(pdf_bytes(monday=date(2028, 2, 28)), dict(start_date='2027-09-01', end_date='2028-07-01'))
    assert parsed['first_date'] == '2028-02-28'


def test_subject_prefix_and_teacher_initial_require_unique_match():
    subjects = [dict(id='s1', name='Préparation et mise en œuvre de la sécurité')]
    assert suggest_subject('PREPARATION ET MISE EN OEU…', subjects) == 's1'
    assert not suggest_subject('PREPARATION ET MISE EN OEU…', subjects + [dict(id='s2',name=subjects[0]['name'])])
    trainers = [dict(id='t1', nom='EXEMPLE', prenom='Paul')]
    assert suggest_trainer('M. EXEMPLE P.', trainers) == 't1'
    assert not suggest_trainer('M. EXEMPLE P.', trainers + [dict(id='t2',nom='EXEMPLE',prenom='Pierre')])


def analyze(client, content=None, period='p1:1', **extra):
    return client.post(BASE+'/import/analyze', data={
        'promotion_id':'p1','period_id':period,'file':(BytesIO(content or pdf_bytes()),'planning.pdf'), **extra},
        headers={'X-CSRF-Token':'csrf-test'}, content_type='multipart/form-data')


def preview(client, token, **extra):
    data = dict(source_token=token,
        mappings=dict(subjects={'Matiere s1':'s1'},subject_trainers={'Matiere s1':'t1'}),
        room_id=None,school_days=True)
    return call(client, '/import/preview', dict(data, **extra))


def commit(client, token, keys=None):
    return call(client, '/import/commit', dict(preview_token=token,selected_keys=keys or ['0']))


def count(db):
    with db() as conn:
        return conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0]


def test_analyze_and_preview_do_not_write_then_commit_adds_only_the_course_day(client, db):
    extraction = analyze(client)
    assert extraction.status_code == 200, extraction.json
    assert extraction.json['mappings']['subjects']['Matiere s1'] == 's1'
    assert extraction.json['mappings']['subject_trainers']['Matiere s1'] == 't1'
    assert count(db) == 0
    result = preview(client, extraction.json['source_token'])
    assert result.status_code == 200, result.json
    assert result.json['summary'] == dict(ready=1,blocked=0,duplicate=0,total=1,minutes=120,school_days=1)
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_day_exceptions').fetchone()[0] == 0
    saved = commit(client, result.json['preview_token'])
    assert saved.status_code == 200 and saved.json['count'] == 1, saved.json
    with db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT promotion_id,date,kind FROM planning_day_exceptions')] == [('p1','2027-01-04','school')]
        assert conn.execute("SELECT planned_hours FROM planning_subjects WHERE id='s1'").fetchone()[0] == 30
    repeated = commit(client, result.json['preview_token'])
    assert repeated.status_code == 200 and repeated.json['count'] == 0 and repeated.json['duplicates'] == 1
    assert count(db) == 1
    again = preview(client, extraction.json['source_token'])
    assert again.json['summary']['duplicate'] == 1


def test_permissions_csrf_invalid_and_expired_tokens(app, client):
    anon = app.test_client()
    assert analyze(anon).status_code == 403
    assert anon.get('/admin/planning/import?promotion_id=p1&period_id=p1:1').status_code == 403
    assert client.post(BASE+'/import/analyze').status_code == 400
    assert preview(client,'tampered').status_code == 409
    token = analyze(client).json['source_token']
    foreign = admin(app,token='another-session')
    assert preview(foreign,token).status_code == 409
    assert commit(client,token).status_code == 409  # extraction is not approval
    with patch('itsdangerous.timed.time.time', return_value=99999999999):
        assert preview(admin(app),token).status_code == 409


def test_annual_isolation_and_wrong_year_subject(client, db):
    with db() as conn:
        conn.execute("UPDATE promotions SET date_debut='2026-09-01',date_fin='2028-07-01' WHERE id='p1'")
    extracted = analyze(client).json
    blocked = analyze(client,period='p1:2').json
    result = preview(client,blocked['source_token'])
    assert result.json['summary']['blocked'] == 1
    assert not result.json['calendar_changes']
    with db() as conn:
        sid = conn.execute("SELECT subject_id FROM planning_subject_periods WHERE period_id='p1:2' LIMIT 1").fetchone()[0]
    data = dict(source_token=extracted['source_token'],school_days=True,room_id=None,
                mappings=dict(subjects={'Matiere s1':sid},subject_trainers={'Matiere s1':'t1'}))
    result = call(client,'/import/preview',data)
    assert result.json['summary']['blocked'] == 1
    assert count(db) == 0


def test_holiday_unavailability_budget_and_calendar_are_enforced(client, db):
    extracted = analyze(client).json
    data = dict(source_token=extracted['source_token'],school_days=False,room_id=None,
                mappings=dict(subjects={'Matiere s1':'s1'},subject_trainers={'Matiere s1':'t1'}))
    assert call(client,'/import/preview',data).json['summary']['blocked'] == 1
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=1 WHERE id='s1'")
    assert preview(client,extracted['source_token']).json['summary']['blocked'] == 1
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=30 WHERE id='s1'")
        conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                     ('u','t1','2027-01-04','2027-01-04','[0]','[]','Indisponible'))
    assert preview(client,extracted['source_token']).json['summary']['blocked'] == 1
    # 2027-03-29 is Easter Monday and falls within p1's date range.
    holiday = analyze(client,pdf_bytes(monday=date(2027,3,29))).json
    assert preview(client,holiday['source_token']).json['summary']['blocked'] == 1
    assert count(db) == 0


def test_concurrent_planning_changes_abort_whole_commit(client, db):
    extracted = analyze(client).json
    result = preview(client,extracted['source_token']).json
    with db() as conn:
        conn.execute("UPDATE planning_subjects SET planned_hours=1 WHERE id='s1'")
    assert commit(client,result['preview_token']).status_code == 409
    assert count(db) == 0
    with db() as conn:
        assert not conn.execute('SELECT 1 FROM planning_day_exceptions').fetchone()
        conn.execute("UPDATE planning_subjects SET planned_hours=30 WHERE id='s1'")
        conn.execute("INSERT INTO planning_day_exceptions VALUES('p1','2027-01-04','closed','Fermeture décidée après aperçu')")
    assert commit(client,result['preview_token']).status_code == 409
    assert count(db) == 0


def test_empty_selection_unreviewed_selection_and_wrong_room_cannot_write(client, db):
    extracted = analyze(client).json
    result = preview(client,extracted['source_token']).json
    assert call(client,'/import/commit',dict(preview_token=result['preview_token'],selected_keys=[])).status_code == 400
    assert commit(client,result['preview_token'],['123']).status_code == 400
    data = dict(source_token=extracted['source_token'],school_days=True,room_id=['bad'],
                mappings=dict(subjects={'Matiere s1':'s1'},subject_trainers={'Matiere s1':'t1'}))
    assert call(client,'/import/preview',data).status_code == 400
    assert count(db) == 0


def test_concurrent_double_submission_creates_one_copy(app, client, db):
    result = preview(client,analyze(client).json['source_token']).json
    token = result['preview_token']
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _:commit(admin(app),token), range(2)))
    assert sorted(r.json['count'] for r in responses) == [0,1]
    assert count(db) == 1


def two_weeks(**second_week):
    writer, stream = PdfWriter(), BytesIO()
    for content in (pdf_bytes(), pdf_bytes(monday=date(2027, 1, 11), **second_week)):
        writer.add_page(PdfReader(BytesIO(content)).pages[0])
    writer.write(stream)
    return stream.getvalue()


def test_subjects_with_same_pdf_trainer_can_import_different_trainers(client, db):
    extracted = analyze(client, two_weeks(subject='Matiere s3')).json
    assert extracted['mappings']['subject_trainers'] == {'Matiere s1':'t1', 'Matiere s3':'t1'}
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'t2', 'Matiere s3':'t1'})
    result = preview(client, extracted['source_token'], mappings=mappings)
    assert result.json['summary']['ready'] == 2, result.json
    assert [r['trainer_id'] for r in result.json['items']] == ['t2', 't1']
    saved = commit(client, result.json['preview_token'], ['0','1'])
    assert saved.json['count'] == 2, saved.json
    with db() as conn:
        assert [tuple(r) for r in conn.execute('SELECT subject_id,trainer_id FROM planning_courses ORDER BY date')] == [('s1','t2'),('s3','t1')]
        assert conn.execute("SELECT trainer_id FROM planning_subjects WHERE id='s1'").fetchone()[0] == 't1'
    repeated = commit(client, result.json['preview_token'], ['0','1'])
    assert repeated.json['count'] == 0 and repeated.json['duplicates'] == 2


def test_several_pdf_trainers_for_one_subject_require_an_explicit_choice(client):
    extracted = analyze(client, two_weeks(teacher='M. NOM t2 P.')).json
    assert extracted['mappings']['subject_trainers'] == {'Matiere s1':''}
    assert preview(client, extracted['source_token'], mappings=extracted['mappings']).json['summary']['blocked'] == 2
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'t2'})
    result = preview(client, extracted['source_token'], mappings=mappings).json
    assert result['summary']['ready'] == 2
    assert [r['trainer_id'] for r in result['items']] == ['t2', 't2']


@pytest.mark.parametrize('trainer', ['', None, [], {}, 'unassigned', 'inactive'])
def test_invalid_subject_trainer_does_not_fall_back_to_pdf_mapping(client, db, trainer):
    extracted = analyze(client).json
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':trainer})
    assert preview(client, extracted['source_token'], mappings=mappings).json['summary']['blocked'] == 1
    assert count(db) == 0


def test_chosen_subject_trainer_is_checked_again_at_commit(client, db):
    extracted = analyze(client).json
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'t2'})
    result = preview(client, extracted['source_token'], mappings=mappings).json
    assert result['summary']['ready'] == 1
    with db() as conn:
        conn.execute('INSERT INTO planning_trainer_unavailability VALUES(?,?,?,?,?,?,?)',
                     ('u','t2','2027-01-04','2027-01-04','[0]','[]','Indisponible'))
    assert commit(client, result['preview_token']).status_code == 409
    assert count(db) == 0


def test_pages_opened_before_subject_mapping_update_remain_usable(client, db):
    extracted = analyze(client).json
    mappings = dict(subjects=extracted['mappings']['subjects'], trainers=extracted['mappings']['trainers'])
    result = preview(client, extracted['source_token'], mappings=mappings).json
    assert result['summary']['ready'] == 1
    assert commit(client, result['preview_token']).json['count'] == 1
