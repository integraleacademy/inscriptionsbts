"""Read the two official establishment lists in separate, short-lived browser contexts."""
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error, TimeoutError as BrowserTimeout

from cyclades_data import ACADEMIES, ALL_STATES, MAX_BYTES, CycladesError, parse_report, with_exams, words

CENTRAL = "cyclades.education.gouv.fr"
REPORT_LINK = "Liste détaillée de mes élèves"


def screen_hint(page):
    # Return only fixed screen categories. Page titles and portal messages may identify a person.
    try:
        return page.evaluate("""() => {
            const http = performance.getEntriesByType('navigation')[0]?.responseStatus;
            if (http >= 400) return 'HTTP ' + http;
            const titles = [...document.querySelectorAll('h1,h2,[role=alert],.fr-alert--error')]
                .map(el => el.innerText).join(' ').toLowerCase();
            if (/captcha|vérifi.{0,20}humain|verify.{0,20}human/.test(titles)) return 'vérification interactive';
            if (/accès refusé|access denied|forbidden/.test(titles)) return 'accès refusé';
            if (/incorrect|invalide|échec de l.authentification/.test(titles)) return 'authentification refusée';
            if (/date de naissance/.test(titles)) return 'confirmation de la date de naissance';
            if (/code à usage|code de sécurité|authentification forte/.test(titles)) return 'validation supplémentaire';
            if (document.querySelector('input[name="j_username"]')) return 'formulaire d’identification';
            if (document.querySelector('input[name="shib_idp_ls_supported"]')) return 'chargement de session';
            if (document.querySelector('#selectContexte')) return 'choix de la session';
            if (/choix|sélection|choisir/.test(titles)) return 'écran de sélection';
            return '';
        }""")
    except Error:
        return ""


@contextmanager
def portal_step(page, label):
    """Report a fixed step and safe technical evidence, never the raw browser exception."""
    try:
        yield
    except Error as exc:
        host = urlsplit(page.url).hostname
        site = host if host and official(page.url) else "navigateur"
        network = re.search(r"net::(ERR_[A-Z_]+)", str(exc))
        if network:
            reason = network[1]
        elif isinstance(exc, BrowserTimeout):
            reason = "délai dépassé"
        elif "strict mode violation" in str(exc):
            reason = "plusieurs éléments correspondent"
        else:
            reason = "navigation interrompue"
        hint = screen_hint(page)
        detail = ", ".join(filter(None, (site, reason, hint)))
        raise CycladesError(f"{label} ({detail}).") from None


def navigate(page, url):
    # Shibboleth immediately posts its session-storage form into a new document.
    # Wait for the intended control at the call site, rather than the intermediary.
    response = page.goto(url, wait_until="commit")
    if response and response.status >= 400:
        raise CycladesError(f"Le portail {urlsplit(url).hostname} a répondu HTTP {response.status}.")


def official(url):
    dest = urlsplit(url)
    host = dest.hostname or ""
    return dest.scheme == "https" and dest.port in (443, None) and any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ("ac-paris.fr", "ac-nice.fr", "education.gouv.fr", "education.fr", "examens-concours.gouv.fr")
    )


def submit_login(page, host, fields):
    # Never type the establishment's secrets on a redirected or replaced form.
    if urlsplit(page.url).hostname != host or not official(page.url):
        raise CycladesError("Le portail a changé de page d’authentification.")
    submit = page.locator('button[name="_eventId_proceed"]')
    form = submit.locator("xpath=ancestor::form[1]")
    target = urljoin(page.url, form.get_attribute("action") or page.url)
    if urlsplit(target).hostname != host or not official(target):
        raise CycladesError("Le formulaire d’authentification n’a pas été reconnu.")
    for name, value in fields.items():
        form.locator(f'input[name="{name}"]').fill(value)
    submit.click()


def open_establishment(page, academy, credentials):
    _, uai, portal, hub = ACADEMIES[academy]
    idp = f"login.ac-{academy}.fr"
    with portal_step(page, "Ouverture du portail académique impossible"):
        navigate(page, portal)
    with portal_step(page, "Le portail n’a pas affiché le formulaire de connexion"):
        page.locator('input[name="j_username"]').wait_for(state="visible")
    with portal_step(page, "Le formulaire d’identification académique n’a pas pu être transmis"):
        submit_login(page, idp, {"j_username": credentials["username"], "j_password": credentials["password"]})
    # Nice can ask for an additional personal verification after the password.
    with portal_step(page, "L’authentification académique ne s’est pas terminée"):
        if academy == "nice":
            page.wait_for_function("""() => location.hostname !== 'login.ac-nice.fr'
                || [...document.querySelectorAll('h1,h2')].some(h => /date de naissance/i.test(h.innerText))
                || document.querySelector('[role=alert]')?.innerText.trim()""")
            if urlsplit(page.url).hostname == idp and page.get_by_role("heading", name=re.compile("date de naissance", re.I)).count():
                if not credentials.get("birthdate"):
                    raise CycladesError("Nice demande la date de vérification du titulaire du compte.")
                submit_login(page, idp, {"j_password": credentials["birthdate"]})
        page.wait_for_url(re.compile(r"^https://" + re.escape(urlsplit(portal).hostname) + r"(?=[:/])"),
                          wait_until="domcontentloaded", timeout=45000)
    with portal_step(page, "L’espace établissement CYCLADES ne s’est pas ouvert"):
        navigate(page, hub)
        header = page.get_by_role("heading", level=1).filter(has_text=uai)
        header.wait_for(state="visible")
        if urlsplit(page.url).hostname != CENTRAL or "brevet de technicien superieur" not in words(header.inner_text()):
            raise CycladesError("L’établissement ou l’examen ouvert dans CYCLADES ne correspond pas au BTS attendu.")
    with portal_step(page, "La rubrique Inscription de l’établissement n’est pas accessible"):
        page.locator("#ETABLISSEMENT_INSCRIPTION").click()
    with portal_step(page, "Le menu d’édition des listes d’inscription n’est pas accessible"):
        page.locator("#ACTV_EDITION_LISTE_CAND_INSCRIPTION").click()
    with portal_step(page, "La liste détaillée des élèves n’est pas accessible"):
        page.get_by_role("link", name=REPORT_LINK, exact=True).wait_for(state="visible")


def filter_structure(page):
    # Only static widget types and known filter vocabulary. No values, candidate or account data.
    return page.evaluate("""() => {
        const clean = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
        const vocab = ['etat','critere','valeur','selection','inscrit','egal','session','recherche','liste','operateur','csv','edition','eleves','generer','editer','epreuves'];
        const nodes = [...document.querySelectorAll('fieldset,legend,[role=group],label,button,select,a,[role=button],[role=combobox],[role=listbox],[role=option],input[type=checkbox],input[type=button],input[type=submit]')];
        return nodes.filter(e => e.getClientRects().length).map(e => {
            const label = clean([e.getAttribute('aria-label'),e.getAttribute('title'),
                e.labels?.[0]?.textContent,e.matches('fieldset,[role=group]') ? e.querySelector('legend')?.textContent : e.innerText].filter(Boolean).join(' '));
            const tokens = vocab.filter(t => label.includes(t)).join('+');
            return [e.tagName,e.getAttribute('role'),tokens].filter(Boolean).join('/');
        }).filter((s,i,a) => a.indexOf(s) === i).slice(0,60).join(' ');
    }""")


def report_frame(shell, title, academy):
    """A context selector belongs to the shell. Wait for the actual edition form."""
    existing = list(shell.context.pages)
    with portal_step(shell, "Le lien d’édition de la liste ne s’est pas ouvert"):
        shell.get_by_role("link", name=title, exact=True).click()
    deadline = time.monotonic() + 25
    while True:
        windows = shell.context.pages
        ordered = [w for w in windows if w not in existing] + [shell] + [w for w in windows if w != shell and w in existing]
        frames = [frame for window in ordered for frame in window.frames if
                  official(frame.url) or (frame.url in ("about:blank","about:srcdoc")
                     and frame.parent_frame and official(frame.parent_frame.url))]
        for frame in frames:
            try:
                csv = frame.locator("#editionCSV")
                if csv.count() and (csv.first.is_visible() or frame.get_by_role("group",name=re.compile("[ée]tat",re.I)).count()):
                    return frame
            except Error:
                continue  # The official application is replacing the frame.
        if time.monotonic() >= deadline:
            break
        shell.wait_for_timeout(200)
    for frame in frames:
        if not frame.is_detached():
            logging.getLogger(__name__).warning("CYCLADES %s édition | %s | %s", academy,
                urlsplit(frame.url).hostname or "document intégré", filter_structure(frame))
    raise CycladesError("CYCLADES a ouvert la session mais le formulaire d’édition CSV n’est pas apparu.")


def choose_states(page, exam_details):
    name = re.compile(r"(?:^|[\s«:])[ée]tat(?:\s|$|[»:.])", re.I)
    field = page.get_by_role("group", name=name)
    if field.count() != 1:
        field = page.get_by_text(re.compile(r"^\s*[ée]tat\s*[:*]?\s*$",re.I)).locator(
            "xpath=ancestor::*[.//button or .//select or .//*[@aria-haspopup]][1]")
    if field.count() != 1:
        raise CycladesError("La rubrique du filtre État est introuvable.")
    required = {"inscrit", "pre inscrit"} if exam_details else ALL_STATES
    native = field.locator("select[multiple]")
    if native.count() == 1:
        options = native.locator("option").all_text_contents()
        names = {words(v) for v in options if v.strip()}
        if not ALL_STATES.issubset(names):
            raise CycladesError("Le filtre État ne propose pas tous les états attendus.")
        native.select_option(index=[i for i,v in enumerate(options) if words(v) in required or (not exam_details and v.strip())])
        return required if exam_details else names
    button = field.get_by_role("button", name=re.compile("valeur recherchée", re.I))
    if button.count() != 1:
        button = field.locator('[aria-haspopup="listbox"],[aria-haspopup="menu"],[role=combobox],button').filter(visible=True)
    if button.count() != 1:
        raise CycladesError("La commande de sélection des états est introuvable.")
    button.click(timeout=9000)
    # Several CYCLADES skins attach the popup to the document, outside its fieldset.
    items = page.locator('[role=option]:visible,[role=menuitemcheckbox]:visible')
    if not items.count():
        items = page.locator('label:visible').filter(has=page.locator('input[type=checkbox]'))
    selected_names, seen = set(), set()
    for item in items.all():
        text = item.get_attribute("aria-label") or item.inner_text()
        state = words(text)
        if state not in ALL_STATES:
            continue
        seen.add(state)
        desired = state in required
        inner = item.locator('input[type=checkbox],[role=checkbox]')
        def checked():
            if inner.count() == 1:
                return inner.is_checked()
            return (item.get_attribute("aria-selected") or item.get_attribute("aria-checked")) == "true"
        if checked() != desired:
            item.click(timeout=5000)
            if checked() != desired:
                raise CycladesError("CYCLADES n’a pas appliqué la sélection des états.")
        if desired:
            selected_names.add(state)
    if not ALL_STATES.issubset(seen):
        raise CycladesError("Le menu État ne présente pas les cinq états de la liste BTS.")
    button.click(timeout=6000)
    return selected_names


def download_session(shell, label, academy, year, *, exam_details=False):
    select = shell.locator("#selectContexte")
    with portal_step(shell, f"La sélection de la session {year} a échoué"):
        if select.locator("option:checked").inner_text().strip() != label:
            labels = [value.strip() for value in select.locator("option").all_text_contents()]
            if label not in labels:
                raise CycladesError(f"Session {year} introuvable.")
            select.select_option(index=labels.index(label))
    title = "Liste détaillée avec épreuves" if exam_details else REPORT_LINK
    page = report_frame(shell, title, academy)
    try:
        expected_states = choose_states(page, exam_details)
    except (CycladesError, Error):
        logging.getLogger(__name__).warning("CYCLADES %s filtre %d | %s", academy, year, filter_structure(page))
        raise
    try:
        with page.page.expect_download(timeout=45000) as download:
            page.locator("#editionCSV").click()
        item = download.value
        with TemporaryDirectory() as temp:
            path = Path(temp) / "export.csv"
            item.save_as(str(path))
            if path.stat().st_size > MAX_BYTES:
                raise CycladesError("L’export CYCLADES dépasse la taille admise.")
            report = parse_report(path.read_bytes(), academy, expected_year=year, expected_states=expected_states)
            if not report.complete:
                raise CycladesError("La liste téléchargée ne couvre pas tous les états attendus.")
            return report
    except CycladesError:
        raise
    except Exception:
        raise CycladesError(f"CYCLADES n’a pas fourni la liste détaillée pour la session {year}.") from None


def read_academy(academy, credentials):
    from playwright.sync_api import sync_playwright

    # Render services with an existing pip-only build command install the pinned
    # headless shell on first connection. The shared disk also survives deploys.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(os.getenv("DATA_DIR", "/data")) / "cyclades-browser"))
    with sync_playwright() as playwright:
        executable = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE") or shutil.which("chromium")
        try:
            browser = playwright.chromium.launch(executable_path=executable)
        except Error as exc:
            if executable or "Executable doesn't exist" not in str(exc):
                raise CycladesError("Le navigateur de synchronisation ne peut pas démarrer sur le serveur.") from None
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
                               check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                browser = playwright.chromium.launch()
            except (subprocess.SubprocessError, OSError, Error):
                raise CycladesError("Le navigateur de synchronisation doit être installé sur le serveur.") from None
        try:
            with browser.new_context(accept_downloads=True, locale="fr-FR", service_workers="block") as context:
                context.route("**/*", lambda route: route.continue_() if official(route.request.url) else route.abort())
                page = context.new_page()
                page.set_default_timeout(45000)
                # Refusals on a redirected main document otherwise look like a missing HTML field.
                def inspect_document(response):
                    if (response.status >= 400 and response.request.is_navigation_request()
                            and response.frame == page.main_frame and official(response.url)):
                        logging.getLogger(__name__).warning("CYCLADES %s HTTP %d sur %s",
                            academy, response.status, urlsplit(response.url).hostname)
                page.on("response", inspect_document)
                open_establishment(page, academy, credentials)
                select = page.locator("#selectContexte")
                with portal_step(page, "La liste des sessions BTS ne s’est pas affichée"):
                    if not select.is_visible():
                        page.get_by_role("link", name=REPORT_LINK, exact=True).click()
                    select.wait_for(state="visible")
                    labels = select.locator("option").all_text_contents()
                area = "PARIS" if academy == "paris" else "NICE"
                sessions = [(label.strip(), int(m[1])) for label in labels
                            if (m := re.match(r"^\s*BTS\s*-\s*(20\d\d)\s*-", label)) and area in label.upper()]
                if not sessions:
                    raise CycladesError("Aucune session BTS de cette académie n’est accessible à l’établissement.")
                for label, year in sorted(sessions, key=lambda item: -item[1]):
                    try:
                        with portal_step(page, f"Les critères de la liste des élèves pour {year} ne sont pas accessibles"):
                            report = download_session(page, label, academy, year)
                    except CycladesError as error:
                        yield error
                        continue
                    if any(words(row[-1]["status"]) in {"inscrit", "pre inscrit"} for row in report.records):
                        try:
                            with portal_step(page, f"Le détail des épreuves pour {year} n’est pas accessible"):
                                supplement = download_session(page, label, academy, year, exam_details=True)
                            with_exams(report, supplement)
                        except CycladesError as error:
                            yield error
                    yield report
        except Error:
            raise CycladesError("Le navigateur de synchronisation s’est interrompu.") from None
        finally:
            browser.close()
