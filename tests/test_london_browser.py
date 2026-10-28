"""Exercise the real HTML form and JS in Chromium, against a temporary Flask app."""
import os
from pathlib import Path
import threading

import pytest
from werkzeug.serving import make_server

from test_london_signatures import application, auth, client, seed, london, signing

pytestmark = pytest.mark.skipif(os.getenv('RUN_LONDON_BROWSER_TESTS') != '1', reason='Chromium is run by the London CI workflow')


@pytest.mark.parametrize('width,minor', [(1440,False),(390,True)])
def test_generate_and_send_from_london_tab(london, signing, width, minor, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    if minor:
        with application.db() as conn: conn.execute("UPDATE candidats SET date_naissance='2010-03-12' WHERE id='london'")
    server=make_server('127.0.0.1',0,application.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':width,'height':1000})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
            cookie=london.get_cookie(application.app.config.get('SESSION_COOKIE_NAME','session'))
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
            page=context.new_page(); errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(origin+'/admin/candidat/london#londres',wait_until='domcontentloaded')
            panel=page.locator('#panel-londres'); expect(panel).to_be_visible()
            form=panel.locator('.mobility-card form')
            for name,value in dict(employer_name='Entreprise Exemple',employer_siret='test',employer_address='12 rue des Écoles',employer_postcode='75001',employer_city='Paris').items():
                form.locator('[name='+name+']').fill(value)
            if minor:
                form.locator('.mobility-guardian summary').click() if not form.locator('[name=guardian_first_name]').is_visible() else None
                form.locator('[name=guardian_first_name]').fill('Charlie')
                form.locator('[name=guardian_last_name]').fill('EXEMPLE')
            # The real form.action is shadowed by its action buttons in Chromium.
            assert form.evaluate('f => String(f.action)') == '[object RadioNodeList]'
            form.get_by_role('button',name='Générer la convention',exact=True).click()
            expect(form.locator('[data-mobility-message]')).to_have_text('Le SIRET doit comporter 14 chiffres.')
            form.locator('[name=employer_siret]').fill('12345678901234')
            form.get_by_role('button',name='Générer la convention',exact=True).click()
            expect(panel.get_by_role('heading',name='Version actuelle',exact=True)).to_be_visible()
            assert not signing.calls
            sendform=panel.locator('form').filter(has=page.locator('[name=employer_email]'))
            expect(sendform.get_by_role('button',name='Envoyer en signature électronique',exact=True)).to_be_enabled()
            sendform.locator('[name=employer_first_name]').fill('Alex')
            sendform.locator('[name=employer_last_name]').fill('EXEMPLE')
            sendform.locator('[name=employer_email]').fill('alex@entreprise.example')
            if minor: sendform.locator('[name=guardian_email]').fill('parent@famille.example')
            sendform.get_by_role('button',name='Envoyer en signature électronique',exact=True).click()
            assert not signing.calls  # Native required confirmation prevents submission.
            sendform.locator('[name=reviewed]').check()
            sendform.get_by_role('button',name='Envoyer en signature électronique',exact=True).click()
            expect(panel.get_by_role('heading',name='Signature électronique · Signatures en cours',exact=True)).to_be_visible()
            assert len(signing.latest['signers']) == (3 if minor else 2)
            expect(panel.get_by_role('button',name='Relancer l’entreprise',exact=True)).to_be_visible()
            artifacts=Path(os.getenv('LONDON_BROWSER_ARTIFACTS',tmp_path));artifacts.mkdir(parents=True,exist_ok=True)
            panel.locator('.mobility-documents').screenshot(path=str(artifacts/f'london-signatures-{width}.png'))
            signing.complete()
            panel.get_by_role('button',name='Actualiser le suivi des signatures',exact=True).click()
            expect(panel.get_by_role('link',name='Voir la convention signée',exact=True)).to_be_visible()
            expect(panel.get_by_role('heading',name='Signature électronique · Convention signée',exact=True)).to_be_visible()
            assert len([c for c in signing.calls if c[1].endswith('/activate')]) == 1
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown();thread.join(timeout=5)
