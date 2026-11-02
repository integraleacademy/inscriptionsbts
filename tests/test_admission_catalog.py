from urllib.parse import urlencode

from bs4 import BeautifulSoup
from test_admissions_2027 import application, auth, client
from test_formation_intake import promotion
from training_programs import ACADEMY_TITLES


def page(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_preview_shows_each_title_before_bts_and_cannot_submit(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: False)
    monkeypatch.setattr(application, 'send_mail', lambda *a, **k: (_ for _ in ()).throw(AssertionError('preview mail')))
    auth(client)
    guest = application.app.test_client()
    preview = page(client, '/candidature?preview=1')
    catalog = preview.select_one('#choix-formation')
    assert catalog.find_next(id='application-guide')
    assert catalog.select_one('a[href="#application-guide"]')
    public = page(guest, '/').select_one('#choix-formation')
    assert public.select_one('a[href="#inscriptions-bts"]')
    for listing in (public, catalog):
        assert {h.get_text(strip=True) for h in listing.select('li h3')} == set(ACADEMY_TITLES)
    assert not public.select('.catalog-session a')
    for li in catalog.select('.catalog-title-list li'):
        link = li.a['href']
        assert guest.get(link).status_code == 302
        form = page(client, link)
        assert form.h1.get_text() == li.h3.get_text()
        assert form.select_one('a[href^="/admin/promotions?bts="]')
        assert form.select_one('button[type=submit][disabled]')
        assert not form.select('[name=submission_token]')
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
        listing = page(guest, path).select_one('#titres-professionnels')
        assert 'Nouveau métier' in listing.get_text()
        assert {a['href'] for a in listing.select('a')} == {'/titres-professionnels/candidature/' + pid for pid in (first, second)}
    for a in page(client, '/candidature?preview=1').select('#titres-professionnels a[href*="promotion="]'):
        sample = page(client, a['href'])
        assert sample.h1.get_text() == 'Nouveau métier' and '2027' in sample.select_one('.create-heading').get_text()
        assert not sample.select('[name=submission_token]')
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
    listing = page(client, '/').select_one('#titres-professionnels')
    assert len(listing.select('li')) == len(ACADEMY_TITLES)
    assert listing.find('h3', string=name).find_parent('li').a['href'].endswith('/' + pid)
