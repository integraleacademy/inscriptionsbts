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
            methods = {"select_option": "sélection du filtre", "get_attribute": "lecture de la commande",
                       "inner_text": "lecture du libellé", "click": "activation de la commande",
                       "set_checked": "sélection de l’état", "wait_for": "attente de l’écran"}
            action = re.search(r"Locator\.([a-z_]+):", str(exc))
            detail = methods.get(action[1]) if action else None
            reason = f"délai dépassé ({detail})" if detail else "délai dépassé"
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


def open_list_menu(page):
    parent = page.locator("#ETABLISSEMENT_INSCRIPTION")
    activity = page.locator("#ACTV_EDITION_LISTE_CAND_INSCRIPTION")
    report = page.get_by_role("link", name=REPORT_LINK, exact=True)
    visible = activity.or_(report).filter(visible=True).first
    for attempt in range(3):
        if report.is_visible():
            return True
        try:
            # The shell can restore an expanded menu after it paints the header.
            if not activity.is_visible():
                try:
                    visible.wait_for(state="visible", timeout=1400)
                except BrowserTimeout:
                    parent.click(timeout=3500)
                    visible.wait_for(state="visible", timeout=4000)
            if report.is_visible():
                return True
            if attempt == 1 and activity.evaluate("e => e.matches('a,button,[role=menuitem]')"):
                activity.press("Enter", timeout=3500)
            else:
                activity.click(timeout=3500)
            report.wait_for(state="visible", timeout=4000)
            return True
        except BrowserTimeout:
            continue
    return False


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
        portal_url = re.compile(r"^https://" + re.escape(urlsplit(portal).hostname) + r"(?=[:/])")
        try:
            page.wait_for_url(portal_url, wait_until="domcontentloaded", timeout=45000)
        except BrowserTimeout:
            if academy != "nice" or official(page.url):
                raise
            # A dropped redirect can leave Chromium on its network-error document.
            # Check the existing SSO session once, without resubmitting credentials.
            navigate(page, portal)
            page.wait_for_url(portal_url, wait_until="domcontentloaded", timeout=12000)
            page.get_by_role("heading", name=re.compile("Je me connecte", re.I)).first.wait_for(
                state="hidden", timeout=2500)
            if urlsplit(page.url).hostname != urlsplit(portal).hostname:
                raise CycladesError("Nice demande une nouvelle authentification après une interruption réseau.")
    for _ in range(2):
        with portal_step(page, "L’espace établissement CYCLADES ne s’est pas ouvert"):
            navigate(page, hub)
            header = page.get_by_role("heading", level=1).filter(has_text=uai)
            header.wait_for(state="visible")
            if urlsplit(page.url).hostname != CENTRAL or "brevet de technicien superieur" not in words(header.inner_text()):
                raise CycladesError("L’établissement ou l’examen ouvert dans CYCLADES ne correspond pas au BTS attendu.")
        with portal_step(page, "Le menu d’édition des listes d’inscription n’est pas accessible"):
            if open_list_menu(page):
                return
    raise CycladesError("Le menu d’édition des listes d’inscription ne s’est pas ouvert dans l’espace BTS.")


def filter_structure(page):
    # Only static widget types and known filter vocabulary. No values, candidate or account data.
    return page.evaluate("""() => {
        const clean = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
        const vocab = ['etat','critere','valeur','selection','inscrit','egal','session','recherche','liste','operateur','csv','edition','eleves','generer','editer','epreuves','valider','confirm','choi','continu','appliquer','contexte','fermer','ouvrir','ok','consulter','acceder','etape','suivant','reinitialiser'];
        const nodes = [...document.querySelectorAll('fieldset,legend,[role=group],label,button,select,a,[role=button],[role=combobox],[role=listbox],[role=option],input[type=checkbox],input[type=button],input[type=submit]')];
        return nodes.filter(e => e.getClientRects().length).map(e => {
            const label = clean([e.getAttribute('aria-label'),e.getAttribute('title'),e.matches('button,input[type=submit],input[type=button]') ? e.getAttribute('value') : '',
                e.labels?.[0]?.textContent,e.matches('fieldset,[role=group]') ? e.querySelector('legend')?.textContent : e.innerText].filter(Boolean).join(' '));
            const tokens = vocab.filter(t => label.includes(t)).join('+');
            return [e.tagName,e.getAttribute('role'),tokens].filter(Boolean).join('/');
        }).filter((s,i,a) => a.indexOf(s) === i).slice(0,60).join(' ');
    }""")


def select_report_context(frame, label):
    control = frame.locator("#selectContexte:visible")
    if not control.count():
        return False
    labels = [v.strip() for v in control.locator("option").all_text_contents()]
    if label not in labels:
        return False
    if control.locator("option:checked").inner_text().strip() != label:
        control.select_option(index=labels.index(label))
    # This is the session chooser for an edition, never a candidate record.
    confirm = re.compile(r"^\s*(?:valider|confirmer|continuer|sélectionner|appliquer|ok|accéder|choisir|suivant)(?:\s+(?:(?:la|le|ce|cette|mon)\s+)?(?:session|contexte|choix|sélection))?\s*[!.]?\s*$", re.I)
    scope = control.locator("xpath=ancestor::*[self::form or self::fieldset or @role='dialog' or "
                            "contains(@class,'modal-content')][1]")
    if not scope.count() or not scope.get_by_role("button", name=confirm).count():
        scope = control.locator("xpath=ancestor::*[not(self::html or self::body) and "
            "(.//button or .//input[@type='submit'] or .//*[@role='button'])][1]")
    if (not scope.count() or scope.locator("select:visible").count() != 1 or scope.locator(
            "textarea:visible,input[type=password]:visible,input[type=checkbox]:visible").count()):
        return False
    buttons = scope.get_by_role("button", name=confirm)
    if buttons.count() == 1 and buttons.is_visible() and buttons.is_enabled():
        buttons.click(timeout=5000)
        return True
    return False


def csv_control(frame):
    by_id = frame.locator("#editionCSV")
    if by_id.count():
        return by_id
    name = re.compile(r"\bCSV\b", re.I)
    return frame.get_by_role("button", name=name).or_(frame.get_by_role("link", name=name))


def report_frame(shell, title, academy, label=None, already_open=False):
    """A context selector belongs to the shell. Wait for the actual edition form."""
    existing = list(shell.context.pages)
    if not already_open:
        with portal_step(shell, "Le lien d’édition de la liste ne s’est pas ouvert"):
            shell.get_by_role("link", name=title, exact=True).click()
    confirmed = set()
    deadline = time.monotonic() + 25
    while True:
        windows = shell.context.pages
        ordered = [w for w in windows if w not in existing] + [shell] + [w for w in windows if w != shell and w in existing]
        frames = [frame for window in ordered for frame in window.frames if
                  official(frame.url) or (frame.url in ("about:blank","about:srcdoc")
                     and frame.parent_frame and official(frame.parent_frame.url))]
        for frame in frames:
            try:
                if label and frame not in confirmed and select_report_context(frame, label):
                    logging.getLogger(__name__).info("CYCLADES %s contexte de session validé", academy)
                    confirmed.add(frame)
                    continue
                csv = csv_control(frame)
                if csv.count() == 1 and csv.is_visible():
                    return frame
            except Error:
                continue  # The official application is replacing the frame.
        if time.monotonic() >= deadline:
            break
        shell.wait_for_timeout(200)
    logging.getLogger(__name__).warning("CYCLADES %s édition | %d fenêtre(s), documents %s", academy,
        len(ordered), [urlsplit(f.url).hostname or urlsplit(f.url).scheme for w in ordered for f in w.frames])
    for frame in frames:
        if not frame.is_detached():
            logging.getLogger(__name__).warning("CYCLADES %s édition | %s | %s", academy,
                urlsplit(frame.url).hostname or "document intégré", filter_structure(frame))
    raise CycladesError("CYCLADES a ouvert la session mais le formulaire d’édition CSV n’est pas apparu.")


def state_field(page):
    name = re.compile(r"(?:^|[^\w])[ée]tat(?:$|[^\w])", re.I)
    legend = page.locator("fieldset > legend").filter(has_text=name)
    field = legend.locator("..").or_(page.get_by_role("group", name=name)).filter(visible=True)
    tab_name = re.compile(r"crit[eè]res? de s[ée]lection", re.I)
    tab = page.get_by_role("link", name=tab_name).or_(page.get_by_role("tab", name=tab_name)).or_(
        page.get_by_role("button", name=tab_name)).filter(visible=True)
    # The export button appears before the selection panel is ready.
    # Some sessions open on the parameters tab, others already show their criteria.
    opened = False
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if field.count() == 1:
            return field
        if not opened and tab.count() == 1 and tab.is_enabled():
            if tab.get_attribute("aria-expanded") != "true" and tab.get_attribute("aria-selected") != "true":
                tab.click(timeout=5000)
            opened = True
        page.wait_for_timeout(250)
    raise CycladesError("Le panneau « Critères de sélection » n’a pas affiché le filtre État.")


def choose_states(page, exam_details, *, use_widget=False):
    field = state_field(page)
    required = {"inscrit", "pre inscrit"} if exam_details else ALL_STATES
    native = field.locator("select[multiple]")
    if not use_widget and native.count() == 1:
        options = native.locator("option").all_text_contents()
        names = {words(v) for v in options if v.strip()}
        if not ALL_STATES.issubset(names):
            raise CycladesError("Le filtre État ne propose pas tous les états attendus.")
        selected = required if exam_details else names
        # The custom menu can hide the underlying HTML select. Its normal input/change
        # events still apply the filter; the official CSV independently confirms it.
        native.select_option(index=[i for i,v in enumerate(options) if words(v) in selected],
                             force=not native.is_visible(), timeout=5000)
        actual = {words(v) for v in native.locator("option:checked").all_text_contents()}
        if actual != selected:
            raise CycladesError("La sélection des états dans le formulaire CYCLADES a échoué.")
        return selected
    button = field.get_by_role("button", name=re.compile("valeur recherchée", re.I))
    if button.count() != 1:
        button = field.locator('[aria-haspopup="listbox"],[aria-haspopup="menu"],[role=combobox],button').filter(visible=True)
    if button.count() != 1:
        raise CycladesError("La commande de sélection des états est introuvable.")
    button.click(timeout=9000)
    # Several CYCLADES skins attach the popup to the document, outside its fieldset.
    items = page.locator('[role=option]:visible,[role=menuitemcheckbox]:visible')
    labels = page.locator('label:visible').filter(has=page.locator('input[type=checkbox]'))
    try:
        items.or_(labels).first.wait_for(state="visible", timeout=9000)
    except BrowserTimeout:
        raise CycladesError("Le filtre État s’est ouvert sans afficher de choix.") from None
    if not items.count():
        items = labels
    selected_names, seen = set(), set()
    for item in items.all():
        text = item.get_attribute("aria-label", timeout=3000) or item.inner_text(timeout=3000)
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
            if inner.count() == 1 and inner.is_visible():
                try:
                    inner.set_checked(desired, timeout=2500)
                except BrowserTimeout:
                    if checked() != desired:
                        item.click(timeout=5000)
            else:
                item.click(timeout=5000)
            if checked() != desired:
                raise CycladesError("CYCLADES n’a pas appliqué la sélection des états.")
        if desired:
            selected_names.add(state)
    if not ALL_STATES.issubset(seen):
        missing = ", ".join(sorted(ALL_STATES - seen))
        raise CycladesError(f"Le filtre État n’a pas proposé tous les états attendus. Choix manquants : {missing}.")
    button.click(timeout=6000)
    return selected_names


def export_csv(page, academy, year, expected_states):
    try:
        with page.page.expect_download(timeout=45000) as download:
            csv_control(page).click()
        item = download.value
        with TemporaryDirectory() as temp:
            path = Path(temp) / "export.csv"
            item.save_as(str(path))
            if path.stat().st_size > MAX_BYTES:
                raise CycladesError("L’export CYCLADES dépasse la taille admise.")
            return parse_report(path.read_bytes(), academy, expected_year=year, expected_states=expected_states)
    except CycladesError:
        raise
    except Exception:
        raise CycladesError(f"CYCLADES n’a pas fourni la liste détaillée pour la session {year}.") from None


def download_session(shell, label, academy, year, *, exam_details=False, already_open=False):
    title = "Liste détaillée avec épreuves" if exam_details else REPORT_LINK
    page = report_frame(shell, title, academy, label, already_open)
    try:
        expected_states = choose_states(page, exam_details)
        report = export_csv(page, academy, year, expected_states)
        if not report.complete and state_field(page).locator("select[multiple]:not(:visible)").count() == 1:
            # Some widgets keep their own selection. Repeat through the visible menu
            # only when the first downloaded CSV disproves the native selection.
            expected_states = choose_states(page, exam_details, use_widget=True)
            report = export_csv(page, academy, year, expected_states)
        if not report.complete:
            raise CycladesError("La liste téléchargée ne couvre pas tous les états attendus.")
        return report
    except (CycladesError, Error):
        logging.getLogger(__name__).warning("CYCLADES %s filtre %d | %s", academy, year, filter_structure(page))
        raise


PJ_TITLE = "Suivre les retours de pièces justificatives"


def read_pieces(page, academy, label, report, records):
    """Open the read-only worklist in its own tab so the CSV editions stay open."""
    from cyclades_pieces import number, parse_detail
    from datetime import datetime
    from cyclades_data import PARIS

    # Return only non-confidential aggregate diagnostics to the service log.
    expected = {}
    for record in records:
        details = record["details"]
        if all(
                details.get(k) for k in ("N° de candidat", "N° d’inscription", "Version")):
            expected.setdefault(number(details["N° de candidat"]), []).append(record)
    if not expected:
        return
    existing = set(page.context.pages)
    shell = page.context.new_page()
    shell.set_default_timeout(7000)
    phase = "menu"
    observed = 0
    try:
        navigate(shell, ACADEMIES[academy][3])
        shell.get_by_role("heading", level=1).filter(has_text=ACADEMIES[academy][1]).wait_for()
        target = shell.get_by_text(PJ_TITLE, exact=True).filter(visible=True)
        group = shell.get_by_text("Gérer les pièces justificatives", exact=True).filter(visible=True)
        phase = "menu inscription"
        if not target.count() and not group.count():
            shell.locator("#ETABLISSEMENT_INSCRIPTION").click()
        phase = "menu gérer les pièces"
        if not target.count():
            group.first.click()
        phase = "menu suivre les retours"
        target.first.click()
        phase = "session"
        def frames():
            return [f for w in page.context.pages if w not in existing for f in w.frames
                    if urlsplit(f.url).hostname == CENTRAL]
        # Contexts of older print editions can coexist. Use the PJ activity only.
        end = time.monotonic() + 24
        session_ok = False
        while time.monotonic() < end:
            for frame in frames():
                if frame.page != shell and "suivre_retours_pj" not in frame.url:
                    continue
                control = frame.locator("#selectContexte:visible")
                if control.count() and label in [v.strip() for v in control.locator("option").all_text_contents()]:
                    confirmed = select_report_context(frame, label)
                    if confirmed:
                        session_ok = True
                    elif control.count() and words(control.locator("option:checked").inner_text()) == words(label):
                        session_ok = True
                if session_ok and any("suivre_retours_pj" in f.url for f in frames()):
                    break
            if session_ok and any("suivre_retours_pj" in f.url for f in frames()):
                break
            shell.wait_for_timeout(250)
        if not session_ok:
            return
        phase = "recherche"
        def active():
            return [f for f in frames() if "suivre_retours_pj" in f.url or (
                f.parent_frame and "suivre_retours_pj" in f.parent_frame.url)]
        def lookup():
            for frame in active():
                button = frame.get_by_role("button", name=re.compile(r"^Rechercher$", re.I)).filter(visible=True)
                if button.count() == 1:
                    button.click()
                    return True
            return False
        did_search = lookup()
        for _ in range(30):
            if any(f.get_by_role("link", name=re.compile(r"^\s*0*\d{8,12}\s*$")).count() for f in active()):
                break
            if any(f.get_by_text(re.compile(r"Pièces justificatives conformes\s*:")).count() for f in active()):
                break
            shell.wait_for_timeout(200)
        logging.getLogger(__name__).info("CYCLADES %s PJ : %d cadres de suivi, %d tableaux, %d liens candidats, recherche %s",
            academy, len(active()), sum(f.locator("table:visible").count() for f in active()),
            sum(f.get_by_role("link", name=re.compile(r"^\s*0*\d{8,12}\s*$")).count() for f in active()), did_search)
        phase = "dossiers"
        stamp = datetime.now(PARIS).strftime("%d/%m/%Y à %Hh%M")
        def consume(frame, records):
            text = frame.locator("body").evaluate("""body => {
                const copy = body.cloneNode(true);
                const originals = [...body.querySelectorAll('select')];
                [...copy.querySelectorAll('select')].forEach((s,i) => {
                    const value = originals[i].selectedOptions[0]?.textContent.trim() || '';
                    s.replaceWith(document.createTextNode('\\nPJ-CONTROLE ' + value + '\\n'));
                });
                copy.querySelectorAll('script,style,input,textarea,[hidden]').forEach(e => e.remove());
                copy.querySelectorAll('br').forEach(e=>e.replaceWith('\\n'));
                copy.querySelectorAll('div,p,tr,fieldset,legend,h1,h2,h3,h4,b,strong,label').forEach(e=>{
                    e.prepend('\\n'); e.append('\\n');
                });
                return copy.textContent;
            }""")
            for record in records:
                result = parse_detail(text, record, ACADEMIES[academy][1])
                if result is not None:
                    record.update(result, documents_checked=stamp)
                    return 1
            return 0
        counter = re.compile(r"Pièces justificatives conformes\s*:")
        next_name = re.compile(r"^(?:page )?suivant(?:e)?$", re.I)
        targets = [r for items in expected.values() for r in items]

        def next_control(frame):
            return frame.get_by_role("link", name=next_name).or_(
                frame.get_by_role("button", name=next_name)).filter(visible=True)

        # Some selections lead directly to the detail navigator.
        detail = next((f for f in active() if f.get_by_text(counter).count()), None)
        if detail:
            previous = set()
            while detail:
                header = detail.get_by_text(re.compile(r"N[°º]\s*candidat", re.I)).first
                signature = header.inner_text() if header.count() else ""
                body = detail.locator("body")
                identity_line = re.search(r"N[°º]\s*candidat\s*:\s*\d+\s+N[°º]\s*inscription\s*:\s*\d+", body.inner_text(), re.I)
                signature = identity_line[0] if identity_line else signature
                if not signature or signature in previous:
                    break
                previous.add(signature)
                observed += consume(detail, targets)
                nxt = next_control(detail)
                if observed == len(targets) or nxt.count() != 1 or not nxt.is_enabled():
                    break
                nxt.click()
                shell.wait_for_timeout(250)
                detail = next((f for f in active() if f.get_by_text(counter).count()), None)
            return

        seen_pages = set()
        while observed < len(targets):
            # Restrict navigation to rows containing a known candidate number.
            visible = []
            for f in active():
                cells = f.locator("tr:visible").get_by_text(re.compile(r"^\s*\d{8,12}\s*$"))
                visible.extend(number(value) for value in cells.all_text_contents())
            signature = tuple(visible)
            if not signature or signature in seen_pages:
                break
            seen_pages.add(signature)
            for candidate in dict.fromkeys(visible):
                records = expected.get(candidate)
                if not records:
                    continue
                for frame in active():
                    cells = frame.locator("tr:visible").get_by_text(re.compile(r"^\s*0*" + re.escape(candidate) + r"\s*$"))
                    row_count = cells.count()
                    if not row_count:
                        continue
                    for index in range(row_count):
                        ident = cells.nth(index)
                        row = ident.locator("xpath=ancestor::tr[1]")
                        links = row.get_by_role("link")
                        link = ident if ident.evaluate("e=>e.matches('a')") else links
                        if link.count() != 1:
                            continue
                        window = frame.page
                        pages_before = set(page.context.pages)
                        link.click()
                        for _ in range(36):
                            detail = next((f for f in active() if f.get_by_text(counter).count()), None)
                            if detail:
                                unread = [r for r in records if "documents_checked" not in r]
                                observed += consume(detail, unread)
                                break
                            shell.wait_for_timeout(200)
                        if detail and detail.page not in pages_before:
                            detail.page.close()
                        elif detail:
                            window.go_back(wait_until="domcontentloaded", timeout=7000)
                        if all("documents_checked" in r for r in records):
                            break
                    break
            advanced = False
            for frame in active():
                nxt = next_control(frame)
                if nxt.count() == 1 and nxt.is_enabled():
                    nxt.click()
                    shell.wait_for_timeout(250)
                    advanced = True
                    break
            if not advanced:
                break
    except (Error, CycladesError) as exc:
        logging.getLogger(__name__).warning("CYCLADES %s PJ : %s (%s)", academy, phase, type(exc).__name__)
    finally:
        logging.getLogger(__name__).warning("CYCLADES %s PJ %d : étape %s, %d dossiers vérifiés",
                                           academy, report.year, phase, observed)
        if not shell.is_closed():
            shell.close()


def read_academy(academy, credentials, matched_records):
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
                failures = set()
                def resource_failure(req, reason):
                    if req.resource_type in ("script","document","xhr","fetch"):
                        host = urlsplit(req.url).hostname or "document local"
                        key = (host, req.resource_type, reason)
                        if key not in failures and len(failures) < 12:
                            failures.add(key)
                            logging.getLogger(__name__).warning("CYCLADES %s ressource | %s %s %s", academy, *key)
                def route_official(route):
                    if official(route.request.url):
                        route.continue_()
                    else:
                        resource_failure(route.request, "domaine externe")
                        route.abort()
                context.route("**/*", route_official)
                context.on("response", lambda r: resource_failure(r.request, "HTTP " + str(r.status)) if r.status >= 400 else None)
                def request_failed(req):
                    reason = re.search(r"\bERR_[A-Z_]+\b", req.failure or "")
                    resource_failure(req, reason.group(0) if reason else "requête interrompue")
                context.on("requestfailed", request_failed)
                page = context.new_page()
                page.set_default_timeout(45000)
                # Refusals on a redirected main document otherwise look like a missing HTML field.
                def inspect_document(response):
                    if (response.status >= 400 and response.request.is_navigation_request()
                            and response.frame == page.main_frame and official(response.url)):
                        logging.getLogger(__name__).warning("CYCLADES %s HTTP %d sur %s",
                            academy, response.status, urlsplit(response.url).hostname)
                page.on("response", inspect_document)
                try:
                    open_establishment(page, academy, credentials)
                except CycladesError:
                    # Restart the official SSO flow once after a dropped login document.
                    # Never retry an explicit credential rejection or an interactive challenge.
                    idp = f"login.ac-{academy}.fr"
                    dropped = any(host == idp and kind == "document" and reason in (
                        "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_TIMED_OUT")
                        for host, kind, reason in failures)
                    if not dropped or screen_hint(page) in ("authentification refusée", "validation supplémentaire",
                                                            "vérification interactive", "accès refusé"):
                        raise
                    page.close()
                    page = context.new_page()
                    page.set_default_timeout(45000)
                    open_establishment(page, academy, credentials)
                select = page.locator("#selectContexte")
                with portal_step(page, "La liste des sessions BTS ne s’est pas affichée"):
                    page.get_by_role("link", name=REPORT_LINK, exact=True).click()
                    select.wait_for(state="visible")
                    labels = select.locator("option").all_text_contents()
                area = "PARIS" if academy == "paris" else "NICE"
                sessions = [(label.strip(), int(m[1])) for label in labels
                            if (m := re.match(r"^\s*BTS\s*-\s*(20\d\d)\s*-", label)) and area in label.upper()]
                if not sessions:
                    raise CycladesError("Aucune session BTS de cette académie n’est accessible à l’établissement.")
                for index, (label, year) in enumerate(sorted(sessions, key=lambda item: -item[1])):
                    try:
                        with portal_step(page, f"Les critères de la liste des élèves pour {year} ne sont pas accessibles"):
                            report = download_session(page, label, academy, year, already_open=index == 0)
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
                    records = matched_records(report)
                    read_pieces(page, academy, label, report, records)
                    checked = sum("documents_checked" in record for record in records)
                    yield report
                    logging.getLogger(__name__).warning("CYCLADES %s PJ %d : %d/%d inscriptions lues",
                                                        academy, year, checked, len(records))
                    if checked < len(records):
                        yield CycladesError(f"Session {year} : justificatifs lus pour {checked}/{len(records)} inscriptions rattachées.")
        except Error:
            raise CycladesError("Le navigateur de synchronisation s’est interrompu.") from None
        finally:
            browser.close()
