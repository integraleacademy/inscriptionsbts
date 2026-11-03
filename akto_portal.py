"""Read-only AKTO provider portal. Nothing is submitted except authentication."""
import re
import logging
from contextlib import contextmanager, suppress
import shutil
import os
import time
import subprocess
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pdfplumber
from playwright.sync_api import Error, sync_playwright

ROOT = 'https://monespace.akto.fr'
DOSSIERS = ROOT + '/prestataire/formations/dossiers'
LOGIN = 'https://aktoext.ciamlogin.com'
PARIS = ZoneInfo('Europe/Paris')
DATE = r'\d{2}/\d{2}/\d{4}'


START_DATE = '2025-06-01'


class BeforeCutoff(Exception):
    pass


class PortalError(Exception):
    pass


@contextmanager
def stage(page, label):
    try:
        yield
    except Error as exc:
        host=urlsplit(page.url).hostname or "navigation"
        reason=re.search(r'net::ERR_[A-Z_]+',str(exc))
        detail=reason[0] if reason else type(exc).__name__
        logging.getLogger(__name__).warning('AKTO MOS : %s | %s | %s',label,host,detail)
        raise PortalError(f"{label} : {detail} ({host}).") from None


def norm(value):
    return ' '.join(re.findall('[a-z0-9]+', unicodedata.normalize('NFKD', (value or '').replace('’', ' ')).encode('ascii', 'ignore').decode().lower()))


def money(value):
    return Decimal(value.replace('€', '').replace(' ', '').replace('\xa0','').replace('\u202f','').replace(',', '.').strip())


def iso(value):
    return datetime.strptime(value, '%d/%m/%Y').date().isoformat()


def notice(path, record, person):
    with pdfplumber.open(path) as doc:
        first = doc.pages[0].extract_text() or ''
        ref = re.search(r'Numéro de dossier\s*:\s*(\w+)', first)
        ident = re.search(r'Bénéficiaire\s*:\s*(.*?)\s+né\(e\) le (' + DATE + ')', first, re.I)
        if not ref or ref[1] != record['reference'] or not ident or norm(ident[1]) != norm(person['prenom']+' '+person['nom']):
            raise PortalError('Identité ou référence du courrier à vérifier.')
        if person.get('date_naissance') and iso(ident[2]) != person['date_naissance']:
            raise PortalError('Date de naissance différente sur le courrier AKTO.')
        dates = re.search(r'Dates de contrat\s*:\s*Du ('+DATE+') au ('+DATE+')', first, re.I)
        if not dates:
            raise PortalError('Date de début du contrat non confirmée dans le courrier AKTO.')
        record.update(contract_start=iso(dates[1]), contract_end=iso(dates[2]))
        if record['contract_start'] < START_DATE:
            raise BeforeCutoff
        rncp = re.search(r'RNCP\s*(\d{4,6})', first)
        if rncp:
            record['rncp'] = 'RNCP' + rncp[1]
        remote = re.search(r'dont\s+(\d+)\s+heures? en distanciel', first)
        if remote:
            record['remote_hours'] = int(remote[1])
        schedules, fees = [], []
        for page in doc.pages:
            for table in page.extract_tables():
                header = norm(' '.join(filter(None, table[0])))
                if 'montant accorde ht' in header and 'date de l echeance' in header:
                    for cells in table[1:]:
                        if len(cells) >= 5 and cells[2] and re.fullmatch(DATE,cells[2].strip()):
                            schedules.append(dict(dateOuverture=iso(cells[2].strip()), montantTotal=float(money(cells[4]))))
                for cells in table:
                    if len(cells)==2 and (cells[0] or '').startswith('Frais annexes :') and cells[1]:
                        vals=re.findall(r'[\d\s]+[,.]\d{2}\s*€', cells[1])
                        total=sum((money(x) for x in vals),Decimal(0))
                        if total:
                            fees.append(dict(natureFrais=cells[0].partition(':')[2].strip(), montantTotal=float(total)))
        if schedules:
            record['schedules'] = schedules
        if fees:
            record['extra_costs'] = fees


def sign_in(page, email, password):
    with stage(page,'Ouverture de Mon Espace AKTO'):
        page.goto(ROOT, wait_until='domcontentloaded')
        page.get_by_role('button',name='Se connecter',exact=True).click()
    # The Microsoft screen may be localized independently of the AKTO portal.
    with stage(page,'Ouverture du formulaire Microsoft'):
        field = page.locator('input[name="username"],input[name="loginfmt"],input[autocomplete="username webauthn"]').first
        field.wait_for(timeout=45000)
        if not page.url.startswith(LOGIN+'/'):
            raise PortalError('Domaine de connexion Microsoft inattendu.')
        field.fill(email)
        field.press('Enter')
    with stage(page,'Passage au mot de passe Microsoft'):
        pwd = page.locator('input[type=password]').first
        pwd.wait_for(timeout=30000)
        if not page.url.startswith(LOGIN+'/'):
            raise PortalError('Domaine de connexion Microsoft inattendu.')
        pwd.fill(password)
        pwd.press('Enter')
    keep = page.get_by_role('button',name=re.compile('^(Oui|Yes)$',re.I))
    provider = page.get_by_role('button',name='Profil Prestataire')
    try:
        keep.or_(provider).first.wait_for(timeout=45000)
        if keep.is_visible() and page.url.startswith(LOGIN+'/'):
            keep.click()
        provider.wait_for(timeout=45000)
    except Error:
        raise PortalError('Connexion AKTO non confirmée. Vérifiez les identifiants, le profil prestataire et toute validation Microsoft requise.') from None
    if not page.url.startswith(ROOT+'/'):
        raise PortalError('Retour vers Mon Espace AKTO non confirmé.')


def catalogue(page):
    # Navigate within the signed-in app so its prestataire context is retained.
    page.get_by_role('link',name='Dossiers',exact=True).click()
    counter=page.locator('.pagination__span').filter(has_text=re.compile(r'^\s*\d[\d\s]*\s+résultats?\s*$',re.I)).first
    with stage(page,'Lecture du compteur de dossiers'):
        counter.wait_for()
    total=int(''.join(re.findall(r'\d',counter.inner_text())))
    logging.getLogger(__name__).warning('AKTO MOS : catalogue ouvert, %d dossiers.',total)
    if not total:
        return []
    cards=page.locator('.mobileCardWrapper')
    found={}
    first_cards=set()
    for number in range(1,total+1):
        cards.first.locator('.headerSubtitle').wait_for(state='attached')
        # AKTO can append a company alias after the reference, e.g. "… (SAMSIC EVENT)".
        batch=cards.evaluate_all("""cards => cards.map(c => {
            const txt = s => c.querySelector(s)?.textContent?.trim() || '';
            const foot = [...c.querySelectorAll('.footerElem')].find(e =>
                e.querySelector('.footerTitle')?.textContent.trim() === 'Stagiaire(s)');
            return { title:txt('.headerTitle'), subtitle:txt('.headerSubtitle'),
                     status:txt('.badge__label'), name:foot?.querySelector('.footerSubtitle')?.textContent.trim() || '',
                     text:c.textContent };
        })""")
        first=batch[0]['subtitle'] if batch else ''
        if not first or first in first_cards:
            break
        first_cards.add(first)
        for card in batch:
            ref=re.match(r'^([A-Z0-9][A-Z0-9-]{4,40})(?=\s|$)',card['subtitle'],re.I)
            if not ref:
                raise PortalError(f'Référence de dossier illisible sur la page {number} du catalogue AKTO.')
            key=ref[1]
            found[key]=[card['title'],key,card['status'],card['text'],'Stagiaire(s)',card['name']]
        if len(found)==total:
            return list(found.values())
        if len(found)>total:
            break
        next_page=page.get_by_role('button',name=str(number+1),exact=True)
        if next_page.count()!=1:
            break
        next_page.click()
        page.wait_for_function("""prev => {const el=document.querySelector('.mobileCardWrapper .headerSubtitle');
            return el && el.textContent.trim() && el.textContent.trim() !== prev}""",arg=first)
    raise PortalError(f'Catalogue AKTO incomplet ({len(found)}/{total} dossiers). Relevés précédents conservés.')


def dossier(page, lines, person):
    ref=lines[1]
    page.goto(DOSSIERS+'/'+ref,wait_until='domcontentloaded')
    page.get_by_text("Contrat d'apprentissage N° "+ref, exact=True).wait_for()
    record={'reference':ref}
    docs=page.locator('.documentsMobileElemWrapper').filter(has_text=re.compile(r"Courrier d'accord de prise en charge \(prestataire\)",re.I))
    if docs.count():
        def issued(row):
            date_match=re.search("Date d'envoi : ("+DATE+")",row.inner_text())
            return iso(date_match[1]) if date_match else ''
        latest=max(docs.all(),key=issued)
        control=latest.get_by_role('button',name='Télécharger',exact=True)
        if control.count()!=1:
            raise PortalError('Téléchargement du courrier AKTO ambigu.')
        with page.expect_download(timeout=35000) as download:
            control.click()
        path=download.value.path()
        if not path or Path(path).stat().st_size>20_000_000:
            raise PortalError('Courrier AKTO indisponible.')
        notice(path,record,person)
        record['document']="Courrier d’accord de prise en charge (prestataire)"
        if not record.get('schedules') and lines[2]=='Accordé':
            raise PortalError('Échéancier non reconnu dans le courrier AKTO.')
    if not record.get('contract_start'):
        raise PortalError('Aucun courrier confirmant la date de début du contrat.')
    page.get_by_role('button',name='Voir le détail',exact=True).click()
    body=page.locator('main').inner_text()
    key=norm(person['prenom']+' '+person['nom'])
    if not any(norm(l)==key for l in body.splitlines()):
        raise PortalError('Identité du dossier AKTO non confirmée.')
    totals=re.search(r'Demandé\s*\*?\s*\n([^\n]+)\nAccordé\s*\n([^\n]+)\nRéglé\s*\n([^\n]+)\nSolde\s*\n([^\n]+)',body)
    if not totals:
        raise PortalError('Totaux AKTO indisponibles.')
    def euros(v):
        return str(money(v.replace('.','') if ',' in v else v))
    dates=re.search(r'Du ('+DATE+') au ('+DATE+')',body)
    employer=re.search(r'^(.+?)\s+(\d{14})\s*$',body,re.M)
    code=re.search(r'Numéro de contrat DGEFP\s*:\s*(\w+)',body)
    module=re.search(r'Modules?\s*\(\d+\)\s*\n([^\n]+)\n([^\n]+)\n([^\n]+)',body)
    record.update(status=lines[2],checked=datetime.now(PARIS).strftime('%d/%m/%Y'),
        employer=employer[1] if employer else None,siret=employer[2] if employer else None,
        training=module[1] if module else '',provider=module[2] if module else '',hours=module[3] if module else '',
        dgefp=code[1] if code else None,period=' au '.join(dates.groups()) if dates else '',
        funding=euros(totals[2]),paid=euros(totals[3]),balance=euros(totals[4]))
    if 'Eligible subrogation : Oui' in body:
        record['subrogation']='Oui'
    piece=re.search(r'Convention\s*\n(CONFORME|NON CONFORME)\s*\n(REÇU|ATTENDU)',body)
    if piece:
        record['evidence']='Convention · '+' · '.join(piece.groups())
    invoices=page.get_by_role('button',name='Voir la facture / DR',exact=True)
    if invoices.count()==1:
        invoices.click()
        page.get_by_role('heading',name='Détail de la facture').wait_for()
        invoice=page.locator('main').inner_text()
        match=re.search(r'Facture n°\s*([^\n]+)',invoice)
        when=re.search(r"Date d'émission\s*\n("+DATE+')',invoice)
        payment=re.search(r'Payé le\s*:\s*('+DATE+')',invoice)
        if match and when and payment and ref in invoice.splitlines():
            record.update(invoice=match[1].strip(),invoice_date=when[1],payment_date=payment[1])
    # Attribute payment only when all pedagogical fees are paid or the single
    # paid invoice matches the one due installment and the pedagogical payment.
    dues=record.get('schedules',[])
    pedagogical=re.search(r'Montant CP\s*\n.*?Payé \(HT\)\s*\n([^\n]+)',body,re.S)
    if pedagogical and dues:
        paid=money(euros(pedagogical[1]))
        due_total=sum((Decimal(str(d['montantTotal'])) for d in dues),Decimal(0))
        if paid==0 or paid==due_total:
            for due in dues:
                due['montantRegle']=due['montantTotal'] if paid else 0
        elif record.get('payment_date') and money(record['paid'])==paid:
            matches=[d for d in dues if Decimal(str(d['montantTotal']))==paid and d['dateOuverture']<=iso(record['payment_date'])]
            if len(matches)==1:
                for due in dues:
                    due['montantRegle']=float(paid) if due is matches[0] else 0
    return record


def read_portal(email,password,people,save,excluded=None,remember=None):
    by_name={}
    for p in people:
        by_name.setdefault(norm(p['prenom']+' '+p['nom']),[]).append(p)
    with sync_playwright() as pw:
        exe=shutil.which('chromium') or os.getenv('CYCLADES_CHROMIUM_EXECUTABLE')
        try:
            browser=pw.chromium.launch(executable_path=exe)
        except Error as exc:
            # No account data has been used during browser setup.
            logging.getLogger(__name__).warning('AKTO initialisation Chromium : %.500s',str(exc))
            if not exe and "Executable doesn't exist" in str(exc):
                try:
                    subprocess.run([sys.executable,'-m','playwright','install','--only-shell','chromium'],check=True,timeout=180,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                except (OSError,subprocess.SubprocessError):
                    raise PortalError('Installation de Chromium indisponible sur le serveur.') from None
            # On Render the first launch can race browser installation at boot.
            time.sleep(2)
            try:
                browser=pw.chromium.launch(executable_path=exe)
            except Error as retry:
                logging.getLogger(__name__).warning('AKTO lancement Chromium : %.600s',str(retry))
                raise PortalError('Le serveur ne peut pas démarrer Chromium pour AKTO.') from None
        try:
            with browser.new_context(locale='fr-FR',accept_downloads=True,service_workers='block',viewport={'width':1280,'height':900}) as ctx:
                # Never submit login form data to a host outside the portal / its IdP.
                def guard(route):
                    u=urlsplit(route.request.url)
                    if route.request.method=='POST' and (u.scheme!='https' or (u.hostname not in ('aktoext.ciamlogin.com','monespace.akto.fr') and not (u.scheme=='https' and (u.hostname or '').endswith('.akto.fr')))):
                        return route.abort()
                    route.continue_()
                ctx.route('**/*',guard)
                page=ctx.new_page()
                page.set_default_timeout(30000)
                def navigation_failed(req):
                    if req.is_navigation_request():
                        code=re.search(r'ERR_[A-Z_]+',req.failure or '')
                        logging.getLogger(__name__).warning('AKTO navigation : %s | %s', urlsplit(req.url).hostname,code[0] if code else 'interrompue')
                page.on('requestfailed',navigation_failed)
                sign_in(page,email,password)
                page.set_viewport_size({'width':800,'height':800})
                with stage(page,'Lecture du catalogue prestataire'):
                    cards=catalogue(page)
                matches={}
                for lines in cards:
                    if lines[0]!='CAPP' or 'Stagiaire(s)' not in lines:
                        continue
                    if lines.index('Stagiaire(s)')+1 >= len(lines):
                        continue
                    if not any('management operationnel de la securite' in norm(x) or 'bts mos' in norm(x) for x in lines):
                        continue
                    name=norm(lines[lines.index('Stagiaire(s)')+1])
                    if name in by_name:
                        matches.setdefault(name,[]).append(lines)
                logging.getLogger(__name__).warning('AKTO MOS : catalogue complet, %d contrats MOS à examiner pour %d identités.',sum(map(len,matches.values())),len(matches))
                errors=0
                for name,persons in by_name.items():
                    if len(persons)>1:
                        for person in persons:
                            save(person,None,'Homonyme dans la plateforme : vérification manuelle nécessaire.')
                        errors+=1
                        continue
                    person=persons[0]
                    records, unavailable = [], []
                    for lines in matches.get(name,[]):
                        if excluded and lines[1] in excluded:
                            continue
                        try:
                            records.append(dossier(page,lines,person))
                        except BeforeCutoff:
                            if remember:
                                remember(lines[1])
                        except (PortalError,Error,ValueError,ArithmeticError,OSError) as exc:
                            logging.getLogger(__name__).warning('AKTO MOS dossier : %s',str(exc) if isinstance(exc,PortalError) else type(exc).__name__)
                            unavailable.append(lines[1])
                    if unavailable:
                        errors+=1
                        save(person,records,'Lecture incomplète : date ou courrier à vérifier. Les relevés vérifiés restent disponibles.',unavailable)
                    else:
                        save(person,records,'')
                logging.getLogger(__name__).info('AKTO MOS : %d dossiers en catalogue, %d fiches examinées, %d à vérifier.',len(cards),len(people),errors)
                return errors
        finally:
            # A secondary close error must not mask the original failing step.
            with suppress(Error):
                browser.close()
