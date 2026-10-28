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


def pdf_bytes(monday=date(2027, 1, 4), declared=2, subject='Matiere s1', teacher='M. NOM t1 P.', empty=False, shift=0, badge=None,
              group='APP BTS MOS 2026-2028', course_group=None):
    """Synthetic vector export: no student's file or real trainer data in git."""
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=(842, 595))
    c.setFont('Helvetica', 8)
    c.drawString(40, 559, f'Planning groupe - {group} Semaine S {monday.isocalendar().week:02d} - {0 if empty else declared}h')
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
        if badge:
            label_y = 595-(70+32+2.4+shift)-6
            c.setFillColorRGB(.51, .74, .89)
            c.rect(202, label_y-1, 14, 10, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.drawString(204, label_y, badge)
            c.setFillColorRGB(0, 0, 0)
        c.setFont('Helvetica', 6)
        c.drawString(89, 595-(70+32+2.4+shift)-18, group if course_group is None else course_group)
        c.setFont('Helvetica', 8)
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


@pytest.mark.parametrize('bts,partner', [('CI', 'PI'), ('PI', 'CI')])
@pytest.mark.parametrize('subject', [
    'ANGLAIS', 'Culture générale et expression',
    'CULTURE GENERALE ET EXPRESS…', 'Culture generale et expr...',
])
def test_ci_pi_common_subjects_accept_the_other_group(bts, partner, subject):
    group = f'APP BTS {bts} 1ERE ANNEE 2026-2028'
    parsed = parse_ypareo_pdf(pdf_bytes(
        group=group, course_group=f'APP BTS {partner} 1ERE ANNEE 2026-2028 C…',
        subject=subject, badge='C' if subject == 'ANGLAIS' else None), PERIOD)
    assert parsed['group'] == group
    assert parsed['minutes'] == 120
    row, = parsed['rows']
    assert (row['date'], row['start'], row['end'], row['subject'], row['trainer']) == (
        '2027-01-04', '09:00', '11:00', subject, 'M. NOM t1 P.')


@pytest.mark.parametrize('course_group,subject', [
    ('APP BTS PI 1ERE ANNEE 2026-2028', 'Commerce international'),
    ('APP BTS MOS 1ERE ANNEE 2026-2028', 'ANGLAIS'),
    ('APP BTS PI 2EME ANNEE 2026-2028', 'ANGLAIS'),
    ('APP BTS PI 1ERE ANNEE 2025-2027', 'ANGLAIS'),
    ('APP BTS PI 1ERE ANNEE 2026-20280', 'ANGLAIS'),
    ('APP BTS PI 1ERE ANNEE 2026-2028', 'Culture générale…'),
    ('APP BTS PI 1ERE ANNEE 2026-2028', 'Culture generale et expr'),
    ('', 'ANGLAIS'),
])
def test_shared_group_exception_rejects_other_subjects_groups_and_cohorts(course_group, subject):
    with pytest.raises(ImportPDFError, match='groupe indiqué.*Aucun cours'):
        parse_ypareo_pdf(pdf_bytes(group='APP BTS CI 1ERE ANNEE 2026-2028',
                                  course_group=course_group, subject=subject), PERIOD)


def test_shared_subject_still_requires_a_matching_weekly_total():
    with pytest.raises(ImportPDFError, match='totalisent 2 h.*annonce 3 h'):
        parse_ypareo_pdf(pdf_bytes(group='APP BTS CI 1ERE ANNEE 2026-2028',
                                  course_group='APP BTS PI 1ERE ANNEE 2026-2028',
                                  subject='ANGLAIS', declared=3), PERIOD)


def test_common_subjects_do_not_allow_mixing_planning_groups_in_one_pdf():
    writer, stream = PdfWriter(), BytesIO()
    for monday, bts in [(date(2027, 1, 4), 'CI'), (date(2027, 1, 11), 'PI')]:
        content = pdf_bytes(monday=monday, group=f'APP BTS {bts} 1ERE ANNEE 2026-2028', subject='ANGLAIS')
        writer.add_page(PdfReader(BytesIO(content)).pages[0])
    writer.write(stream)
    with pytest.raises(ImportPDFError, match='plusieurs groupes'):
        parse_ypareo_pdf(stream.getvalue(), PERIOD)


@pytest.mark.parametrize('badge', ['C', 'T', 'TD'])
def test_boxed_session_markers_do_not_split_the_same_subject(badge):
    writer, stream = PdfWriter(), BytesIO()
    for content in [pdf_bytes(subject='Culture generale et expr...', badge=badge),
                    pdf_bytes(monday=date(2027,1,11), subject='Culture generale et expression')]:
        writer.add_page(PdfReader(BytesIO(content)).pages[0])
    writer.write(stream)
    parsed = parse_ypareo_pdf(stream.getvalue(), PERIOD)
    assert parsed['minutes'] == 240 and len(parsed['rows']) == 2
    assert len({r['subject_key'] for r in parsed['rows']}) == 1
    assert [r['subject'] for r in parsed['rows']] == ['Culture generale et expr...', 'Culture generale et expression']


@pytest.mark.parametrize('letter', ['C', 'T'])
def test_unboxed_letter_is_preserved_as_part_of_a_subject_title(letter):
    label = 'Enseignement option ' + letter
    parsed = parse_ypareo_pdf(pdf_bytes(subject=label), PERIOD)
    assert parsed['rows'][0]['subject'] == label


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


def test_common_pi_courses_import_into_the_selected_ci_promotion(client, db):
    with db() as conn:
        conn.execute("UPDATE promotions SET bts='CI' WHERE id='p1'")
        conn.execute("UPDATE promotions SET bts='PI' WHERE id='p2'")
        conn.execute("UPDATE planning_subjects SET name='Anglais' WHERE id='s1'")
        conn.execute("UPDATE planning_subjects SET name='Culture générale et expression' WHERE id='s3'")
    writer, stream = PdfWriter(), BytesIO()
    for monday, subject in [(date(2027, 1, 4), 'ANGLAIS'),
                            (date(2027, 1, 11), 'CULTURE GENERALE ET EXPRESS…')]:
        content = pdf_bytes(monday=monday, group='APP BTS CI 1ERE ANNEE 2026-2028',
                            course_group='APP BTS PI 1ERE ANNEE 2026-2028 C…', subject=subject)
        writer.add_page(PdfReader(BytesIO(content)).pages[0])
    writer.write(stream)
    extraction = analyze(client, stream.getvalue())
    assert extraction.status_code == 200, extraction.json
    assert count(db) == 0
    mappings = extraction.json['mappings']
    assert mappings['subjects'] == {'ANGLAIS': 's1', 'CULTURE GENERALE ET EXPRESS…': 's3'}
    result = preview(client, extraction.json['source_token'], mappings=mappings)
    assert result.status_code == 200, result.json
    assert result.json['summary']['ready'] == 2
    assert count(db) == 0
    saved = commit(client, result.json['preview_token'], ['0', '1'])
    assert saved.status_code == 200 and saved.json['count'] == 2, saved.json
    with db() as conn:
        assert [tuple(row) for row in conn.execute(
            'SELECT promotion_id,subject_id FROM planning_courses ORDER BY date')] == [('p1', 's1'), ('p1', 's3')]
        assert conn.execute("SELECT COUNT(*) FROM planning_course_groups WHERE promotion_id='p2'").fetchone()[0] == 0


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


def assigned(db, trainer='unassigned', promotion='p1'):
    with db() as conn:
        return bool(conn.execute('SELECT 1 FROM trainer_promotions WHERE trainer_id=? AND promotion_id=?', (trainer, promotion)).fetchone())


def test_active_trainer_can_be_matched_and_assigned_only_when_import_is_confirmed(client, db):
    with db() as conn:
        conn.execute("UPDATE trainers SET nom='EXEMPLE',prenom='Frédérique' WHERE id='unassigned'")
        conn.execute("INSERT INTO trainer_promotions VALUES('unassigned','p2')")
        conn.execute('CREATE TABLE trainer_access_tokens(id TEXT,trainer_id TEXT,consumed INTEGER)')
        conn.execute("INSERT INTO trainer_access_tokens VALUES('token','unassigned',0)")
    extracted = analyze(client, pdf_bytes(teacher='Mme EXEMPLE F.')).json
    trainers = {t['id']: t for t in extracted['trainers']}
    assert trainers['unassigned']['prenom'] == 'Frédérique' and trainers['unassigned']['assigned'] == 0
    assert trainers['t1']['assigned'] == 1 and 'inactive' not in trainers
    assert extracted['mappings']['subject_trainers']['Matiere s1'] == 'unassigned'
    assert not assigned(db)
    # The old client does not approve granting access to another promotion.
    assert preview(client, extracted['source_token'], mappings=extracted['mappings']).json['summary']['blocked'] == 1
    result = preview(client, extracted['source_token'], mappings=extracted['mappings'], assign_trainers=True).json
    assert result['summary']['ready'] == 1 and [t['id'] for t in result['trainer_assignments']] == ['unassigned']
    assert not assigned(db) and count(db) == 0
    with db() as conn:
        assert conn.execute("SELECT version FROM trainers WHERE id='unassigned'").fetchone()[0] == 1
        assert conn.execute('SELECT consumed FROM trainer_access_tokens').fetchone()[0] == 0
    assert commit(client, result['preview_token']).json['count'] == 1
    assert assigned(db) and assigned(db, promotion='p2')
    repeated = commit(client, result['preview_token']).json
    assert repeated['count'] == 0 and repeated['duplicates'] == 1
    with db() as conn:
        assert conn.execute("SELECT version FROM trainers WHERE id='unassigned'").fetchone()[0] == 2
        assert conn.execute('SELECT consumed FROM trainer_access_tokens').fetchone()[0] == 1


def test_deselected_courses_do_not_assign_their_trainer(client, db):
    extracted = analyze(client, two_weeks(subject='Matiere s3')).json
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'unassigned', 'Matiere s3':'t2'})
    result = preview(client, extracted['source_token'], mappings=mappings, assign_trainers=True).json
    assert result['summary']['ready'] == 2 and len(result['trainer_assignments']) == 1
    assert commit(client, result['preview_token'], ['1']).json['count'] == 1
    assert not assigned(db)
    assert commit(client, result['preview_token'], ['0']).json['count'] == 1
    assert assigned(db)


def test_trainer_assignment_is_rolled_back_if_course_insert_fails(client, db):
    extracted = analyze(client).json
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'unassigned'})
    result = preview(client, extracted['source_token'], mappings=mappings, assign_trainers=True).json
    with db() as conn:
        conn.execute("CREATE TRIGGER reject_course BEFORE INSERT ON planning_courses BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    assert commit(client, result['preview_token']).status_code == 409
    assert not assigned(db) and count(db) == 0
    with db() as conn:
        assert conn.execute("SELECT version FROM trainers WHERE id='unassigned'").fetchone()[0] == 1
        assert not conn.execute('SELECT 1 FROM planning_day_exceptions').fetchone()


def test_removed_assignment_cannot_be_restored_without_being_in_the_preview(client, db):
    extracted = analyze(client).json
    result = preview(client, extracted['source_token'], assign_trainers=True).json
    assert result['trainer_assignments'] == []
    with db() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    assert commit(client, result['preview_token']).status_code == 409
    assert not assigned(db, 't1') and count(db) == 0


def test_disabled_trainer_cannot_be_assigned_from_an_old_preview(client, db):
    extracted = analyze(client).json
    mappings = dict(extracted['mappings'], subject_trainers={'Matiere s1':'unassigned'})
    result = preview(client, extracted['source_token'], mappings=mappings, assign_trainers=True).json
    with db() as conn:
        conn.execute("UPDATE trainers SET active=0 WHERE id='unassigned'")
    assert commit(client, result['preview_token']).status_code == 409
    assert not assigned(db) and count(db) == 0


def test_normal_course_endpoint_cannot_grant_trainer_access(client, db):
    body = dict(promotion_id='p1', subject_id='s1', trainer_id='unassigned', date='2027-01-04', start='09:00', end='11:00',
                assign_trainers=True, pending_trainer_assignments=[['unassigned','p1']])
    assert call(client, '/courses', body).status_code == 400
    assert not assigned(db) and count(db) == 0
