"""One click, real Chromium, synthetic data and a fake signing provider."""
import os
from pathlib import Path
import threading
import pytest
from werkzeug.serving import make_server
from test_london_automatic import automatic, application, auth, client, seed, london, signing

pytestmark=pytest.mark.skipif(os.getenv('RUN_LONDON_BROWSER_TESTS')!='1',reason='Chromium is run by the London CI workflow')


@pytest.mark.parametrize('width,minor',[(1440,False),(390,True)])
def test_one_click_from_london_tab(automatic,signing,width,minor,tmp_path,monkeypatch):
    from playwright.sync_api import sync_playwright,expect
    monkeypatch.setitem(application.app.config,'LONDON_AUTOMATIC_DEFER',False)
    if minor:
        with application.db() as conn:conn.execute("UPDATE candidats SET date_naissance='2010-03-12' WHERE id='london'")
    release=threading.Event();original=signing.perform
    def hold_activation(method,path,**kwargs):
        if path.endswith('/activate'):release.wait(timeout=15)
        return original(method,path,**kwargs)
    signing.perform=hold_activation
    server=make_server('127.0.0.1',0,application.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    artifacts=Path(os.getenv('LONDON_BROWSER_ARTIFACTS',tmp_path));artifacts.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':1000},reduced_motion='reduce')
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            cookie=automatic.get_cookie(application.app.config.get('SESSION_COOKIE_NAME','session'))
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/admin/candidat/london#londres',wait_until='domcontentloaded')
            panel=page.locator('#panel-londres');expect(panel).to_be_visible()
            assert panel.locator('input:not([type=hidden]):not([type=checkbox]),select,textarea').count()==0
            expect(page.locator('.sheet-side-column')).to_be_hidden()
            panel.scroll_into_view_if_needed()
            panel.screenshot(path=str(artifacts/f'london-ready-{width}.png'))
            panel.get_by_role('button',name='Préparer et envoyer la convention',exact=True).click()
            dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
            expect(dialog.get_by_role('heading',name='Convention Londres en cours de transmission')).to_be_visible()
            dialog.screenshot(path=str(artifacts/f'london-modal-{width}.png'))
            release.set()
            expect(dialog.get_by_role('heading',name='La convention a été transmise')).to_be_visible(timeout=20000)
            assert len(signing.requests)==1 and len(signing.latest['signers'])==(3 if minor else 2)
            assert all(x['signature_authentication_mode']=='otp_sms' for x in signing.latest['signers'])
            dialog.get_by_role('button',name='Voir le suivi des signatures').click()
            expect(panel.get_by_role('heading',name='Signatures en cours',exact=True)).to_be_visible()
            expect(panel.get_by_role('button',name='Relancer l’entreprise',exact=True)).to_be_visible()
            panel.get_by_role('tab',name='Le séjour',exact=True).click()
            expect(panel.get_by_role('heading',name='Le séjour à Londres')).to_be_visible()
            panel.get_by_role('tab',name='Documents').click()
            expect(panel.get_by_role('link',name='PDF original ↗')).to_be_visible()
            panel.get_by_role('tab',name='Convention',exact=True).click()
            signing.complete()
            panel.get_by_role('button',name='Actualiser le suivi des signatures',exact=True).click()
            expect(panel.get_by_role('link',name='Voir la convention signée ↗',exact=True)).to_be_visible()
            expect(page.locator('[data-london-notification-count]')).to_have_text('1')
            panel.screenshot(path=str(artifacts/f'london-signed-{width}.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.goto(origin+'/admin/voyage-londres',wait_until='domcontentloaded')
            notification=page.locator('[data-london-notifications]');expect(notification).to_be_visible()
            expect(notification.get_by_role('link',name='Camille TEST',exact=True)).to_be_visible()
            notification.screenshot(path=str(artifacts/f'london-notification-{width}.png'))
            notification.get_by_role('button',name='Marquer comme lu',exact=True).click()
            expect(notification).to_be_hidden()
            assert len([c for c in signing.calls if c[1].endswith('/activate')])==1
            assert not errors,errors
            browser.close()
    finally:
        release.set();server.shutdown();thread.join(timeout=5)
