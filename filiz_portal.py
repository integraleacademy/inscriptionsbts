"""Read the school's FILIZ contract lists and dossier tabs. No changes to FILIZ."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import re
import logging
import subprocess
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout, expect
from portal_browser import persistent_playwright, launch_chromium
from akto_portal import START_DATE, norm
from opco_convergence import ReadError, identity
from training_programs import BTS_LABELS
from wedof_contract_data import FINANCERS, stamp

HOME = 'https://app.filiz.io'
CATALOG = HOME + '/school/folder'
AUTH_HOST = 'filizio.eu.auth0.com'
CARDS = 'a[href*="/school/folder/"][href$="#trackingFolder"]'
MONTHS = {'jan':1,'fev':2,'mar':3,'avr':4,'mai':5,'juin':6,'juil':7,'aou':8,
          'sep':9,'oct':10,'nov':11,'dec':12}
DAY = r'\d{1,2}\s+[A-Za-zÀ-ÿ.]+\s+\d{4}'
AMOUNT = r'\d[\d\s]*(?:,\d{2})?\s*€'
STATUS = {'engage':'accepted', 'dossier refuse':'refused', 'refuse':'refused', 'rompu':'broken',
          'rupture':'broken', 'rupture validee':'broken', 'analyse opco':'pendingAcceptation',
          'solde':'completed', 'annule':'cancelled', 'en instruction':'pendingAcceptation'}
FINANCER_ALIASES = {norm(v).replace(' ',''): k for k,v in FINANCERS.items()}
FINANCER_ALIASES.update({'opcommerce':'opcoCfaOpcommerce','opcodelaproximite':'opcoCfaEp',
                         'opcoep':'opcoCfaEp', 'opcodesentreprisesdeproximite':'opcoCfaEp'})


def iso(value):
    value = (value or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    parts = norm(value).split()
    if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
        month = next((n for label,n in MONTHS.items() if parts[1].startswith(label)), None)
        if month:
            try:
                return datetime(int(parts[2]),month,int(parts[0])).date().isoformat()
            except ValueError:
                pass
    return ''


def money(value):
    if not value or not re.fullmatch(AMOUNT, value.strip()):
        return None
    return float(Decimal(''.join(value.strip()[:-1].split()).replace(',','.')))


def lines(value):
    return [s.strip() for s in value.splitlines() if s.strip()]


def labeled_amount(values, label):
    for i,line in enumerate(values[:-1]):
        if line == label:
            return money(values[i+1])
    return None


def due_row(summary, detail):
    values = lines(summary)
    number = re.fullmatch(r'Échéance N°\s*(\d+)', values[0], re.I) if values else None
    if not number or len(values)<3 or money(values[1]) is None:
        raise ReadError('Format d’échéance FILIZ non reconnu.')
    state = values[2]
    state_code = 'unknown'
    for label, code in [('payee','paid'),('a venir','upcoming'),('en attente de paiement','pending'),
                        ('a facturer','open'),('a enregistrer','open'),('en instruction','pending')]:
        if norm(state).startswith(label):
            state_code = code
            break
    dates = re.search(r'(?:Du|À partir du) (' + DAY + r')(?: au ('+DAY+r'))?', summary, re.I)
    paid = labeled_amount(values, 'Payé OPCO')
    row = {'numero':number[1], 'montantTotal':money(values[1]), 'montantRegle':paid,
           'filiz_label':state, 'filiz_code':state_code}
    if dates:
        row.update(dateDebut=iso(dates[1]),dateFin=iso(dates[2]))
    invoices = []
    for label, value in re.findall(r'(Facture [^\n]+? n°\s*[^\n]+)\n+('+AMOUNT+')', detail, re.I):
        invoices.append({'reference':label,'amount':money(value),'state':'','paid_on':''})
    return row, invoices


def consent(page):
    for name in ('Fermer sans accepter les cookies','Fermer le widget sans consentement'):
        btn = page.get_by_role('button',name=name,exact=True)
        if btn.is_visible():
            btn.click(timeout=3000)
            break
    for phrase in ('La gestion des droits évolue','Certains chiffres partent'):
        dialog = page.get_by_role('dialog').filter(has_text=phrase)
        if dialog.count() and dialog.first.is_visible():
            close = dialog.first.get_by_role('button',name='Fermer',exact=True)
            (close.last if close.count() else dialog.first.get_by_role('button').first).click()


class InactiveLoginForm(ReadError):
    """No submission took place; a stale browser session may be discarded."""


def fill_login_form(page, config, host, address, password, submit):
    if address.is_visible():
        if address.is_editable():
            address.fill(config['email'])
            address.press('Tab')
        elif address.input_value().casefold() != config['email'].casefold():
            raise ReadError('FILIZ présente un autre compte que le compte école configuré.')
    if password.is_visible() and host == AUTH_HOST:
        password.fill(config['password'])
    try:
        expect(submit).to_be_enabled(timeout=2500)
        return
    except AssertionError:
        pass

    # A remounted/controlled input can lose an early fill. Re-enter only before any submit.
    if host == 'app.filiz.io' and address.is_visible() and address.is_editable():
        address.fill('')
        address.press_sequentially(config['email'], delay=35)
        address.press('Tab')
    try:
        expect(submit).to_be_enabled(timeout=8000)
    except AssertionError:
        value_kept = address.is_visible() and address.input_value().casefold() == config['email'].casefold()
        logging.getLogger(__name__).warning('FILIZ : formulaire inactif avant soumission, origine=%s, adresse conservée=%s.',
                                            host, value_kept)
        raise InactiveLoginForm('Le formulaire de connexion FILIZ ne s’est pas activé après la saisie.') from None


def login(page, config):
    visited = set()
    school = page.locator('a[href$="/school/folder"]').first
    logger = logging.getLogger(__name__)
    def login_response(response):
        host = urlsplit(response.url).hostname
        if response.status >= 400 and host in ('app.filiz.io', AUTH_HOST):
            logger.warning('FILIZ : accès école, HTTP %d (%s).', response.status, host)
    page.on('response', login_response)
    page.goto(HOME+'/school', wait_until='commit', timeout=45000)
    for _ in range(4):
        # FILIZ may restore SSO without ever presenting the Auth0 password form.
        page.wait_for_function(r"""() => [...document.querySelectorAll(
            'a[href$="/school/folder"],input[name=email],input[name=username],input[name=password],[role=alert],input[aria-invalid=true]')]
            .some(e=>e.offsetWidth && (e.getAttribute('role') !== 'alert' || e.textContent.trim())) ||
            /captcha|multi.factor|\/mfa|\/challenge/i.test(location.pathname)""", timeout=35000)
        host = urlsplit(page.url).hostname
        if host == 'app.filiz.io' and school.count() and school.is_visible():
            page.remove_listener('response', login_response)
            return
        if host not in ('app.filiz.io', AUTH_HOST):
            raise ReadError('Mode de connexion FILIZ non reconnu.')
        challenge = page.locator('input[autocomplete=one-time-code], iframe[title*="captcha" i]').first
        if host == AUTH_HOST and (challenge.is_visible() or
                re.search('captcha|multi.factor|/mfa|/challenge', urlsplit(page.url).path, re.I)):
            raise ReadError('FILIZ demande une vérification interactive du compte école.')
        consent(page)
        password = page.locator('input[name=password]:visible').first
        address = page.locator('input[name=email]:visible' if host == 'app.filiz.io' else 'input[name=username]:visible').first
        has_password = host == AUTH_HOST and password.is_visible()
        step = (host, has_password)
        logger.warning('FILIZ : identification, formulaire %s.', 'mot de passe' if has_password else 'adresse école')
        if step in visited or not (has_password or address.is_visible()):
            alert = page.locator('[role=alert]').filter(has_text=re.compile(r'\S')).first
            invalid = page.locator('input[aria-invalid=true]').first
            if alert.is_visible() or invalid.is_visible():
                raise ReadError('FILIZ a refusé la connexion ou demande une vérification du compte école.')
            if host == 'app.filiz.io' and (AUTH_HOST, True) in visited:
                # The OAuth callback may leave the school login screen mounted.
                try:
                    # Leave the application time to exchange the OAuth callback before navigating away.
                    school.wait_for(state='visible', timeout=15000)
                except BrowserTimeout:
                    page.goto(HOME+'/school', wait_until='commit', timeout=45000)
                try:
                    school.wait_for(state='visible', timeout=15000)
                except BrowserError:
                    if page.locator('input[name=email]').first.is_visible():
                        raise ReadError('Après identification, FILIZ renvoie à la page de connexion sans ouvrir l’espace école.') from None
                    raise
            else:
                school.wait_for(state='visible', timeout=20000)
            page.remove_listener('response', login_response)
            return
        visited.add(step)
        submit = page.get_by_role('button', name='Continuer', exact=True)
        fill_login_form(page, config, host, address, password, submit)
        try:
            submit.click(timeout=12000, no_wait_after=True)
        except BrowserError as exc:
            if 'intercepts pointer events' not in str(exc):
                raise
            consent(page)
            submit.click(timeout=6000, no_wait_after=True)
        # Do not confuse the already submitted form with the next screen.
        page.wait_for_function(r"""([host, pwd]) => location.hostname !== host ||
            [...document.querySelectorAll('a[href$="/school/folder"]')].some(e=>e.offsetWidth) ||
            [...document.querySelectorAll('[role=alert]')].some(e=>e.offsetWidth && e.textContent.trim()) ||
            [...document.querySelectorAll('input[aria-invalid=true]')].some(e=>e.offsetWidth) ||
            /captcha|multi.factor|\/mfa|\/challenge/i.test(location.pathname) ||
            (!pwd && [...document.querySelectorAll('input[name=password]')].some(e=>e.offsetWidth))""",
            arg=[host, has_password], timeout=35000)
    raise ReadError('Mode de connexion FILIZ non reconnu.')


def catalogue(page):
    page.goto(CATALOG, wait_until='domcontentloaded')
    page.locator('[role=tab]').filter(has_text='Alternance').wait_for(state='attached')
    consent(page)
    search = page.get_by_placeholder('Rechercher...')
    if search.input_value():
        search.fill('')
    # FILIZ remembers pagination between visits, including our previous scan's last page.
    page.locator(CARDS).first.wait_for(state='attached', timeout=30000)
    first = page.get_by_role('button', name='Go to page 1', exact=True)
    if first.count() and first.is_visible():
        old = page.locator(CARDS).first.get_attribute('href')
        first.click()
        page.get_by_role('button', name='page 1', exact=True).wait_for(state='visible')
        page.wait_for_function('([selector, old]) => { const a = document.querySelector(selector); return a && a.getAttribute("href") !== old }',
                               arg=[CARDS, old])
    # Never mistake a loader or a filtered catalogue for a completed scan.
    page.locator(CARDS).first.wait_for(state='attached',timeout=30000)
    expected = re.search(r'\d+',page.get_by_role('tab',name=re.compile('Alternance')).inner_text())
    records = {}
    while True:
        cards = page.locator(CARDS).evaluate_all("""els=>els.map(a=>({href:a.getAttribute('href'),
            text:a.innerText, paragraphs:[...a.querySelectorAll('p')].map(x=>x.innerText),
            opco:a.querySelector('img[alt]')?.alt}))""")
        before = len(records)
        for card in cards:
            m = re.fullmatch(r'/school/folder/([a-zA-Z0-9_-]+)#trackingFolder',card['href'])
            if not m or m[1] in records:
                raise ReadError('Pagination FILIZ incohérente. Dernier relevé conservé.')
            records[m[1]] = card
        if len(records) == before:
            raise ReadError('Liste FILIZ incomplète.')
        nxt = page.get_by_role('button',name='Go to next page')
        if not nxt.count() or nxt.is_disabled():
            break
        old = cards[0]['href']
        nxt.click()
        page.wait_for_function("""([selector,old])=>{let a=document.querySelector(selector);
            return a && a.getAttribute('href')!==old}""",arg=[CARDS,old])
    if not expected or len(records) != int(expected[0]):
        raise ReadError('Le nombre de dossiers lus diffère du compteur FILIZ. Relancez la synchronisation.')
    return records


def fields(page, names):
    return page.evaluate("""names=>Object.fromEntries(names.map(n=>[n,
        document.querySelector('[role=tabpanel] input[name="'+n+'"]')?.value?.trim()||'']))""",names)


def summary_values(page):
    return page.locator('[role=tabpanel]').first.evaluate("""root=>{
        let result={};
        for(let e of root.querySelectorAll('span')){
          let k=e.textContent.trim();
          if(['Contrat','Formation','Type d’alternance',"Type d'alternance",'N° DECA','N° dossier OPCO',
              'N° interne OPCO',"Maître d'apprentissage",'OPCO'].includes(k) && !e.children.length)
            result[k]=k==='OPCO'?e.parentElement.querySelector('img')?.alt:e.nextElementSibling?.textContent.trim();
        }
        let company=[...root.querySelectorAll('h6')].find(e=>e.parentElement.parentElement.innerText.includes('Entreprise'));
        result.company=company?.textContent.trim();
        return result;
    }""")


def switch_tab(page, title, anchor):
    tab = page.get_by_role('heading',name=title,exact=True).first
    for attempt in range(2):
        tab.click()
        try:
            page.wait_for_url('**#'+anchor,timeout=5000)
            return
        except BrowserError:
            if attempt:
                raise
            consent(page)


def finance(page, item):
    switch_tab(page,'Comptabilité','invoice')
    heading = page.get_by_role('heading', name='Facture OPCO', exact=True)
    waiting = page.get_by_role('heading', name='Échéancier en cours de récupération', exact=True)
    heading.or_(waiting).first.wait_for(state='visible', timeout=12000)
    if waiting.is_visible():
        item['schedule_notice'] = 'FILIZ indique que l’échéancier est en cours de récupération.'
        item['raw_checked_at'] = stamp()
        return
    panel = page.get_by_role('tabpanel').filter(has=heading).last
    portal_lines = lines(panel.inner_text())
    item['filiz_paid'] = labeled_amount(portal_lines, 'Payé')
    item['engagement'] = labeled_amount(portal_lines,'Montant total de la facture OPCO')
    item['filiz_pending'] = labeled_amount(portal_lines,'En attente de paiement')
    item['filiz_updated'] = next((x for x in portal_lines if x.startswith('Actualisé le ')), '')
    dues = panel.get_by_role('button',name=re.compile(r'^Échéance N°\s*\d+'))
    if not dues.count():
        raise ReadError('Échéancier FILIZ indisponible.')
    rows, invoices = [], []
    for due in dues.all():
        summary = due.inner_text()
        detail = ''
        more = due.get_by_text('Afficher les détails',exact=True)
        if more.is_visible():
            more.click()
            detail = due.locator('xpath=../..').inner_text()
        row, bills = due_row(summary, detail)
        rows.append(row)
        invoices.extend(bills)
    if len({r['numero'] for r in rows}) != len(rows):
        raise ReadError('Numéros d’échéances FILIZ en double.')
    # Where the displayed paid amounts account for the complete FILIZ paid total,
    # future lines without an amount carry zero paid. Otherwise preserve unknowns.
    stated = item.get('filiz_paid')
    allocated = sum((Decimal(str(r['montantRegle'])) for r in rows if r['montantRegle'] is not None),Decimal(0))
    if stated is not None and Decimal(str(stated)) == allocated:
        for r in rows:
            if r['filiz_code']=='upcoming' and r['montantRegle'] is None:
                r['montantRegle'] = 0
    item.update(schedules=rows, invoices=invoices, raw_checked_at=stamp())
    extras = []
    for name in ('Premier équipement','Hébergement','Restauration'):
        val = labeled_amount(portal_lines,name)
        if val is not None:
            extras.append({'natureFrais':name,'montantTotal':val})
    if extras:
        item.update(extra_costs_available=True,extra_costs=extras)


def read_item(page, ref, card, people):
    page.goto(CATALOG+'/'+ref+'#trackingFolder',wait_until='domcontentloaded')
    page.get_by_role('heading',name='Avancée du dossier').wait_for()
    consent(page)
    summary = summary_values(page)
    period = (summary.get('Contrat') or '').split(' - ')
    if len(period)!=2 or not iso(period[0]):
        raise ReadError('Date de début FILIZ non confirmée.')
    if iso(period[0]) < START_DATE:
        return None
    card_lines = lines(card['text'])
    provider = norm(summary.get('OPCO') or card.get('opco') or '').replace(' ','')
    financer = FINANCER_ALIASES.get(provider)
    deca = summary.get('N° DECA') or ''
    external = summary.get('N° dossier OPCO') or ''
    if not financer or not any(v and v.lower() not in ('n/a','-','non renseigné') for v in (deca,external)):
        return None  # A school draft without an OPCO reference is not an OPCO contract.
    switch_tab(page,'Étudiant','student')
    page.locator('input[name=birthDate]').wait_for(state='attached')
    person = fields(page,['firstName','lastName','birthDate','mailAddress','phoneNumber','address','postalCode','city'])
    birth = iso(person['birthDate'])
    key = identity(person['lastName'],person['firstName'],birth)
    matched = [p for p in people if all(key) and key == identity(p['nom'],p['prenom'],p['date_naissance'])]
    if len(matched)!=1:
        raise ReadError('Identité FILIZ non confirmée.')
    title = norm(next(iter(card['paragraphs']),''))
    expected = matched[0]['bts'].strip().upper()
    if not (norm(BTS_LABELS[expected]).removeprefix('bts ') in title or
            expected.lower() in title.split() or any(re.search(r'\bbts '+expected.lower()+r'\b', norm(p)) for p in card['paragraphs'])):
        raise ReadError('Filière BTS FILIZ à vérifier.')
    item = {'source':'filiz','working_contract_id':'filiz-'+ref,'filiz_id':ref,'financer':financer,
        'external_number':external or deca,'internal_number':summary.get('N° interne OPCO'), 'deca_number':deca,
        'training_title':next(iter(card['paragraphs']),''),'employer_name':summary.get('company'),
        'tutor_name':summary.get("Maître d'apprentissage"),'contract_start':iso(period[0]),'contract_end':iso(period[1]),
        'apprentice_birth_date':birth,'apprentice_last_name':person['lastName'],'apprentice_first_name':person['firstName'],
        'apprentice_email':person['mailAddress'],'apprentice_phone':person['phoneNumber'],'apprentice_address':person['address'],
        'apprentice_postcode':person['postalCode'],'apprentice_city':person['city'],'checked_at':stamp(),
        'state':STATUS.get(norm(card_lines[3]),'unknown'),'state_label':card_lines[3]}
    training = (summary.get('Formation') or '').split(' - ')
    if len(training)==2:
        item.update(training_start=iso(training[0]),training_end=iso(training[1]))
    switch_tab(page,'Contrat','contract')
    page.locator('input[name=contractStartDate]').wait_for(state='attached')
    # A disabled date input can be present before FILIZ loads its value.
    try:
        page.wait_for_function("""() => Array.from(document.querySelectorAll('input[name=contractStartDate]'))
            .some(input => input.offsetWidth && /[0-9]/.test(input.value))""", timeout=4000)
    except BrowserError:
        pass
    contract = fields(page,['contractStartDate','contractEndDate','contractClosingDate','MonthlySalaryAmount'])
    form_start = iso(contract['contractStartDate'])
    if form_start and form_start < START_DATE:
        return None
    if form_start != item['contract_start']:
        shown = re.search('('+DAY+r')\s*-\s*('+DAY+')', card['text'])
        if not shown or iso(shown[1]) != item['contract_start']:
            raise ReadError('Les dates du contrat FILIZ diffèrent.')
        # The dossier summary and catalogue agree. Preserve the discrepancy in the contract view.
        if form_start:
            item['details_error'] = ('Le catalogue et le suivi FILIZ indiquent le ' +
                datetime.fromisoformat(item['contract_start']).strftime('%d/%m/%Y') +
                ', le formulaire Contrat indique le ' + datetime.fromisoformat(form_start).strftime('%d/%m/%Y') + '.')
        else:
            item['details_error'] = 'Date de début confirmée dans le catalogue et le suivi. Le formulaire Contrat ne la précise pas.'
    item.update(contract_conclusion=iso(contract['contractClosingDate']),gross_salary=contract['MonthlySalaryAmount'] or None)
    switch_tab(page,'Entreprise','company')
    page.locator('input[name=apeCode]').wait_for(state='attached')
    company = fields(page,['address','postalCode','city'])
    heading = page.locator('[role=tabpanel] h5').first
    if heading.count():
        item['employer_name'] = heading.inner_text().strip()
    item.update(employer_address=company['address'],employer_postcode=company['postalCode'],employer_city=company['city'])
    for attempt in range(2):
        try:
            finance(page,item)
            break
        except ReadError as exc:
            item.update(raw_stale=True, raw_error=str(exc))
            break
        except BrowserError:
            if attempt:
                item.update(raw_stale=True, raw_error='L’onglet comptable FILIZ n’a pas pu être lu.')
            else:
                consent(page)
    return matched[0]['id'], item


@contextmanager
def school_browser(config, stored_session):
    with persistent_playwright() as pw:
        try:
            browser = launch_chromium(pw)
        except (BrowserError, OSError, subprocess.SubprocessError) as exc:
            logging.getLogger(__name__).warning('FILIZ : lancement Chromium : %.1200s', str(exc))
            raise ReadError('Chromium n’a pas pu démarrer depuis le cache des portails.') from None
        try:
            for state in ([stored_session, None] if stored_session else [None]):
                with browser.new_context(locale='fr-FR', storage_state=state, service_workers='block') as ctx:
                    # The login page and password form use different origins.
                    login_pending = True
                    blocked_origins = set()
                    def guard(route):
                        url = urlsplit(route.request.url)
                        if route.request.method == 'POST' and not (url.scheme == 'https' and
                                (url.hostname in (AUTH_HOST, 'filiz.io') or (url.hostname or '').endswith('.filiz.io'))):
                            if login_pending and url.hostname and url.hostname not in blocked_origins:
                                blocked_origins.add(url.hostname)
                                logging.getLogger(__name__).warning('FILIZ : POST tiers filtré pendant la connexion (%s).',
                                                                    url.hostname)
                            return route.abort()
                        route.continue_()
                    ctx.route('**/*', guard)
                    page = ctx.new_page()
                    page.set_default_timeout(20000)
                    try:
                        login(page, config)
                        login_pending = False
                    except InactiveLoginForm:
                        if state is None:
                            raise
                        logging.getLogger(__name__).warning('FILIZ : formulaire inactif, nouvelle session avant toute soumission.')
                        continue
                    except BrowserError as exc:
                        host = urlsplit(page.url).hostname
                        stage = 'FILIZ' if host == 'app.filiz.io' else 'authentification' if host == AUTH_HOST else 'redirection'
                        route_name = urlsplit(page.url).path.split('/')[1:2]
                        section = next((part for part in route_name if part in ('school','login','u','authorize')), 'autre')
                        operation = re.match(r'[A-Za-z.]+', str(exc))
                        controls = []
                        if not page.is_closed():
                            for field in ('email','username','password'):
                                if page.locator('input[name='+field+']').first.is_visible():
                                    controls.append(field)
                        reason = next((label for token, label in (
                            ('intercepts pointer events','fenêtre devant le bouton'),('element is not enabled','bouton désactivé'),
                            ('element is not visible','élément masqué')) if token in str(exc)), 'chargement')
                        logging.getLogger(__name__).warning(
                            'FILIZ : délai à l’étape %s/%s (%s, %s), formulaire=%s, session restaurée=%s.',
                            stage, section, operation[0] if operation else type(exc).__name__, reason,
                            ','.join(controls) or 'aucun', bool(state))
                        if state is None:
                            raise
                        # Expired browser storage must not prevent a new login with the configured account.
                        logging.getLogger(__name__).warning('FILIZ : session enregistrée interrompue, nouvel essai sans cache.')
                        continue
                    yield page, ctx
                    return
        finally:
            browser.close()


def eligible_card(card, names):
    values = lines(card['text'])
    if len(values) < 4 or norm(values[0]) not in names or norm(values[2]) != 'apprentissage':
        return False
    period = re.search('('+DAY+r')\s*-\s*('+DAY+')', card['text'])
    start = iso(period[1]) if period else ''
    return not start or start >= START_DATE


def read_group(config, stored_session, group, cards, people):
    results, failed, reasons = {}, set(), Counter()
    with school_browser(config, stored_session) as (page, ctx):
        for ref in group:
            try:
                try:
                    entry = read_item(page, ref, cards[ref], people)
                except BrowserError:
                    entry = read_item(page, ref, cards[ref], people)
                if entry:
                    results[ref] = entry
                    if entry[1].get('raw_stale'):
                        failed.add(ref)
                        reasons[entry[1]['raw_error']] += 1
            except (BrowserError, ReadError) as exc:
                failed.add(ref)
                # ReadError messages from read_item are fixed labels. Browser errors may contain private page data.
                reasons[str(exc) if isinstance(exc, ReadError) else 'navigation du dossier'] += 1
        stored_session = ctx.storage_state()

    return results, failed, reasons, stored_session


def read_filiz(config, people, stored_session, save_session, completed, save_batch):
    logger = logging.getLogger(__name__)
    with school_browser(config, stored_session) as (page, ctx):
        logger.warning('FILIZ : Chromium démarré, espace école ouvert.')
        for attempt in range(3):
            try:
                cards = catalogue(page)
                break
            except (ReadError, BrowserError) as exc:
                message = str(exc) if isinstance(exc, ReadError) else 'Chargement du catalogue incomplet.'
                logger.warning('FILIZ : catalogue, essai %d : %s', attempt + 1, message)
                if attempt == 2:
                    if isinstance(exc, BrowserError):
                        raise
                    raise ReadError(message) from None
        stored_session = ctx.storage_state()
        save_session(stored_session)
    names = {norm(p['prenom']+' '+p['nom']) for p in people}
    eligible = [ref for ref, card in cards.items() if eligible_card(card, names)]
    remaining = [ref for ref in eligible if ref not in completed]
    done = len(eligible) - len(remaining)
    logger.warning('FILIZ : catalogue complet (%d dossiers), %d à examiner, %d déjà traités.',
                   len(cards), len(eligible), done)
    # Retire Chromium and its driver regularly to release portal rendering memory.
    size = 3
    for offset in range(0, len(remaining), size):
        group = remaining[offset:offset + size]
        for attempt in range(3):
            try:
                results, failed, reasons, stored_session = read_group(config, stored_session, group, cards, people)
                save_session(stored_session)
                break
            except BrowserError:
                logger.warning('FILIZ : ouverture du groupe interrompue, essai %d/3.', attempt + 1)
                if attempt == 2:
                    raise
        done += len(group)
        save_batch(group, results, failed, done, len(eligible))
        logger.warning('FILIZ : %d/%d examinés. Groupe : %d rattachés, %d à vérifier. %s',
                       done, len(eligible), len(results), len(failed), dict(reasons) if reasons else '')
    return set(eligible)
