"""Read-only portal rendering must preserve privacy and work without JavaScript."""
from pathlib import Path
from flask import Flask, render_template

ROOT = Path(__file__).resolve().parents[1]


def render(template, **context):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.secret_key = 'portal-template-fixture'
    with app.test_request_context('/espace/planning'):
        return render_template(template, **context)


def course(**changes):
    result = dict(id='course1', date='2026-11-12', date_label='jeudi 12 novembre', start='08:00', end='12:00',
                  subject_name='Culture générale', trainer_name='Alex Exemple', room_name='', title='',
                  promotion_names=['BTS MOS première année'], is_shared=False, incomplete=True,
                  warning_labels=['Salle à confirmer.'])
    result.update(changes)
    return result


def test_legacy_login_prompt_never_renders_supplied_private_classes():
    html = render('_portal_today.html', portal_today=dict(role='student', requires_login=True,
        planning_url='/espace/connexion', today_label='', courses=[course(subject_name='Private lesson secret')],
        next_courses=[course(subject_name='Another private secret')]))
    assert 'Me connecter pour voir mon planning' in html
    assert 'Private lesson secret' not in html
    assert 'Another private secret' not in html
    assert 'data-portal-course' not in html


def test_today_courses_and_missing_room_are_readable_without_javascript_and_escaped():
    html = render('_portal_today.html', portal_today=dict(role='student', today='2026-11-12',
        today_label='jeudi 12 novembre', planning_url='/espace/planning', requires_login=False,
        day_kind='school', day_label='À l’école', courses=[course(subject_name='<script>alert(1)</script>')],
        next_courses=[course(date='2026-11-13', date_label='vendredi 13 novembre')], empty_message=''))
    assert '08:00' in html and '12:00' in html and 'Salle à confirmer.' in html
    assert 'is-incomplete' in html and 'Informations à confirmer' in html
    assert 'vendredi 13 novembre' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_week_is_server_rendered_with_date_navigation_holiday_and_protected_pdf_links():
    item = course()
    schedule = dict(role='student', home_url='/espace/mon-dossier', planning_url='/espace/planning',
        pdf_url='/espace/planning.pdf?date=2026-11-09', week_label='Du 9 novembre au 15 novembre 2026',
        previous_url='/espace/planning?date=2026-11-02', next_url='/espace/planning?date=2026-11-16',
        today_url='/espace/planning', date_input='2026-11-09', today='2026-11-12',
        promotion_label='BTS MOS première année', summary=dict(courses=1, minutes=240), courses=[item], empty_message='',
        days=[dict(date='2026-11-11',label='mercredi 11 novembre',short_label='mer. 11',kind='public_holiday',
                   day_label='Armistice',public_holiday=True,courses=[]),
              dict(date='2026-11-12',label='jeudi 12 novembre',short_label='jeu. 12',kind='school',
                   day_label='À l’école',public_holiday=False,courses=[item])])
    html = render('portal_planning.html', portal_planning=schedule)
    assert 'Culture générale' in html and '4 h cette semaine' in html
    assert 'Armistice' in html and 'is-public-holiday' in html
    assert 'method="get"' in html and 'name="date"' in html
    assert '/espace/planning?date=2026-11-16' in html
    assert 'target="_blank" rel="noopener"' in html
    assert '/espace/planning.pdf?date=2026-11-09' in html
    assert '/admin/planning' not in html


def test_home_course_live_status_is_server_rendered_without_javascript():
    html = render('_portal_today.html', portal_today=dict(role='trainer', today='2026-11-12',
        today_label='jeudi 12 novembre', planning_url='/formateur/planning', requires_login=False,
        day_kind='school', day_label='À l’école', courses=[course(live_state='ongoing'),
        course(start='14:00', end='16:00', live_state='upcoming'),
        course(start='07:00', end='08:00', live_state='')], next_courses=[], empty_message=''))
    assert 'data-live-state="ongoing"' in html and 'data-live-state="upcoming"' in html
    assert 'data-course-live>En cours</span>' in html
    assert 'data-course-live>À venir</span>' in html
    assert html.count('data-course-live hidden') == 1


def test_trainer_home_does_not_show_other_days_even_if_supplied_as_upcoming():
    html = render('_portal_today.html', portal_today=dict(role='trainer', today='2026-11-12',
        today_label='jeudi 12 novembre', planning_url='/formateur/planning', requires_login=False,
        day_kind='school', courses=[], next_courses=[course(subject_name='Cours de demain')],
        empty_message='Aucun cours prévu aujourd’hui.'))
    assert 'Pas de cours aujourd’hui.' in html and 'Voir mon planning' in html
    assert 'Cours de demain' not in html and 'portal-next-courses' not in html
