"""The trainer's absence editor keeps destructive changes explicit and text safe."""
from pathlib import Path

from flask import Flask, render_template

ROOT = Path(__file__).resolve().parents[1]


def test_annual_calendar_exposes_review_dialog_and_escaped_initial_state():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.secret_key = 'template-only-fixture'
    app.add_url_rule('/formateur/indisponibilites', 'trainer_availability', lambda: '')
    config = dict(year=2027, csrf_token='fixture-token', home_url='/formateur', planning_url='/formateur/planning',
                  state_url='/formateur/indisponibilites/api/state', preview_url='/formateur/indisponibilites/api/preview',
                  commit_url='/formateur/indisponibilites/api/commit',
                  state=dict(year=2027, days=[dict(date='2027-01-04', reason='</script><script>alert("XSS")</script>')]))
    with app.test_request_context('/formateur/indisponibilites'):
        html = render_template('trainer_availability.html', availability=config, trainer={'prenom': 'Exemple'})
    assert 'Mes <em>indisponibilités.</em>' in html
    assert 'id="ta-confirm-dialog"' in html and 'aria-labelledby="ta-confirm-title"' in html
    assert 'Les cours déjà programmés vous seront signalés avant toute suppression.' in html
    assert 'Cette suppression concerne aussi les cours communs à plusieurs promotions.' in html
    assert 'id="ta-confirm"' in html and 'id="ta-cancel-dialog"' in html
    assert 'css/trainer-availability.css' in html and 'js/trainer-availability.js' in html
    assert '</script><script>alert("XSS")</script>' not in html
    assert '\\u003c/script\\u003e' in html
    assert 'Désactiver' not in html


def test_editor_uses_scoped_full_width_and_respects_reduced_motion():
    css = (ROOT / 'static/css/trainer-availability.css').read_text()
    assert '.academy-ui.trainer-availability-page #main-content' in css
    assert 'max-width:none!important;width:100%!important' in css
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '.ta-dialog::backdrop' in css
