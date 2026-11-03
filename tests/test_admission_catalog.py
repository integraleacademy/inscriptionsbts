from urllib.parse import urlencode

from bs4 import BeautifulSoup
from test_admissions_2027 import application, auth, client
from test_formation_intake import promotion
from training_programs import ACADEMY_TITLES


def page(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_preview_starts_with_preparation_then_offers_bts_and_titles_without_submission(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: False)
    monkeypatch.setattr(application, 'send_mail', lambda *a, **k: (_ for _ in ()).throw(AssertionError('preview mail')))
    auth(client)
    guest = application.app.test_client()
    preview = page(client, '/candidature?preview=1')
    catalog = preview.select_one('#choix-formation')
    guide = preview.select_one('#application-guide')
    assert guide.select_one('#start-application') and not guide.select_one('.route-option')
    assert catalog.has_attr('hidden') and guide.find_next_sibling('section') == catalog
    assert catalog.select_one('#start-bts') and catalog.select_one('a#choose-titles')
    shared_fields = {field['name'] for field in preview.select('#application-form [name]')}
    shared_fields -= {'mos_parcours', 'aps_souhaitee', 'raison_aps', 'admin_preview', 'cherche_idf'}
    public = page(guest, '/').select_one('#choix-formation')
    assert public.select_one('a[href="#inscriptions-bts"]')
    assert not preview.select('.catalog-title-list') and not public.select('.catalog-title-list')
    preview_link = catalog.select_one('#choose-titles')['href']
    assert guest.get(preview_link).status_code == 302
    title_page = page(client, preview_link)
    public_titles = page(guest, public.select_one('#titres-professionnels')['href'])
    for form in (public_titles, title_page):
        assert {h.get_text(strip=True) for h in form.select('#titres-professionnels label b')} == set(ACADEMY_TITLES)
        assert shared_fields <= {field['name'] for field in form.select('#application-form [name]')}
        assert len(form.select('#step-navigation button')) == 7
        assert form.select_one('#next-step') and form.select_one('#application-progress')
        assert form.select_one('#application-form')['data-title-journey'] == 'true'
    assert public_titles.select_one('#title-intake-notice')
    assert not public_titles.select('[name=cherche_idf], [name=mode][value=distanciel]')
    assert len(public_titles.select('[data-training-info]')) == len(ACADEMY_TITLES)
    assert not public_titles.select('[data-token]')
    assert not title_page.select('#titres-professionnels input[disabled]')
    assert title_page.select_one('button[type=submit][disabled]')
    assert not title_page.select('[name=submission_token]')
    for name in ACADEMY_TITLES:
        code = 'TP ' + name.upper()
        link = '/titres-professionnels/apercu?' + urlencode({'formation': code})
        assert guest.get(link).status_code == 302
        form = page(client, link)
        assert form.select_one('input[name=bts][checked]')['value'] == code
        assert client.post(link, data={'email': 'test@example.test'}).status_code == 405
    security = catalog.select_one('a[href*="parcoursalternance"]')['href']
    assert public.select_one('a[href="/parcoursalternance/candidature"]')
    assert guest.get(security).status_code == 302
    sample = page(client, security).select_one('#application-form')
    assert sample.get('data-preview-return') and not sample.get('data-token') and not sample.get('data-endpoint')
    assert len(sample.select('.question')) == 17
    assert client.post(security, json={}).status_code == 405
    assert client.post('/parcoursalternance/candidature', json={}).status_code == 400
    assert client.get('/titres-professionnels/apercu?formation=MCO').status_code == 404
    with application.db() as conn:
        assert not conn.execute('SELECT 1 FROM candidats').fetchone()
        assert not conn.execute('SELECT 1 FROM formation_receipts').fetchone()


def test_catalog_tracks_promotions_in_public_and_admin_views(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: True)
    auth(client)
    guest = application.app.test_client()
    admin = page(client, '/admin/promotions')
    options = {o.get('value') for o in admin.select('#promotion-form [name=bts] option')}
    assert {'TP ' + name.upper() for name in ACADEMY_TITLES} <= options
    with client.session_transaction() as session:
        csrf = session['_promotion_csrf']
    code = 'TP NOUVEAU MÉTIER'
    assert client.post('/admin/promotions/titres-professionnels', data={'csrf_token': csrf, 'name': 'Nouveau métier'}).status_code == 303
    first = promotion(client, code)
    second = promotion(client, code)
    inactive = promotion(client, code)
    incomplete = promotion(client, code)
    ended = promotion(client, code)
    with application.db() as conn:
        conn.execute('UPDATE promotions SET active=0 WHERE id=?', (inactive,))
        conn.execute('UPDATE promotions SET needs_setup=1 WHERE id=?', (incomplete,))
        conn.execute("UPDATE promotions SET date_fin='2020-01-01' WHERE id=?", (ended,))
    for path in ('/', '/candidature'):
        choices = page(guest, path)
        link = choices.select_one('#choose-titles, a#titres-professionnels')['href']
        form = page(guest, link)
        assert 'Nouveau métier' in form.select_one('#titres-professionnels').get_text()
        assert {o['data-submit'] for o in form.select('#title-session option[data-title]')} == {'/titres-professionnels/candidature/' + pid for pid in (first, second)}
    sample = page(client, '/titres-professionnels?preview=1')
    assert {o['value'] for o in sample.select('#title-session option[data-title]')} == {first, second}
    assert not sample.select('[name=submission_token], [data-token]')
    wrong = urlencode({'formation': 'TP GESTIONNAIRE DE PAIE', 'promotion': first})
    assert client.get('/titres-professionnels/apercu?' + wrong).status_code == 404
    for pid in (inactive, incomplete, ended):
        assert guest.get('/titres-professionnels/candidature/' + pid).status_code == 404


def test_existing_title_spelling_keeps_its_promotion_and_is_listed_once(client):
    auth(client)
    page(client, '/admin/promotions')
    name = "Chargé d'accueil et de gestion administrative"
    code = 'TP ' + name.upper()
    with application.db() as conn:
        conn.execute('INSERT INTO professional_titles(code,name) VALUES(?,?)', (code, name))
    pid = promotion(client, code)
    with client.session_transaction() as session:
        csrf = session['_promotion_csrf']
    client.post('/admin/promotions/titres-professionnels', data={'csrf_token': csrf, 'name': name.replace("'", "’")})
    form = page(client, '/titres-professionnels')
    assert len(form.select('#titres-professionnels label')) == len(ACADEMY_TITLES)
    assert form.select_one('#title-session option[data-title]')['value'] == pid
    assert form.select_one('#title-session option[data-title]')['data-title'] == code



def test_security_agent_title_is_unavailable_even_with_an_existing_promotion(client):
    auth(client)
    pid = promotion(client, 'TP GESTIONNAIRE DE PAIE')
    name = 'Agent de sûreté et de sécurité privée'
    code = 'TP ' + name.upper()
    with application.db() as conn:
        conn.execute('INSERT INTO professional_titles(code,name) VALUES(?,?)', (code, name))
        conn.execute('UPDATE promotions SET bts=? WHERE id=?', (code, pid))
    for path in ('/titres-professionnels', '/titres-professionnels?preview=1'):
        listing = page(client, path).select_one('#titres-professionnels').get_text()
        assert name not in listing
        assert 'Opérateur en vidéoprotection et en télésurveillance' in listing
    assert client.get('/titres-professionnels/apercu?' + urlencode({'formation': code})).status_code == 404
    assert client.get('/titres-professionnels/candidature/' + pid).status_code == 404
