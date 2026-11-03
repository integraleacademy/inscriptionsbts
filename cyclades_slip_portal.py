"""Open the existing account-edition report; never submit a generation form."""
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error

from cyclades_data import ACADEMIES, MAX_BYTES, CycladesError, words
from cyclades_slips import read_slips, slip_key

ACTIVITY = re.compile(r"^G[ée]n[ée]rer\s+les comptes\s+(?:CYCLADES\s+)?(?:de mes|des)\s+[ée]l[èe]ves$", re.I)
SUMMARY = re.compile(r"^(?:Afficher|Consulter|Voir)\s+(?:le |les )?comptes?[\s-]*rendus?(?:\s+du traitement)?$", re.I)
DOCUMENT = re.compile(r"papillons?\s*(?:d['’]\s*)?informations?\s*(?:de\s*)?connexion\s*(?:cyclades)?", re.I)


def open_accounts_menu(shell):
    # CYCLADES can pre-render the activity link in a collapsed aside, or
    # populate its sub-menu only after the parent activity is expanded.
    def activity():
        for frame in shell.frames:
            if urlsplit(frame.url).hostname != urlsplit(shell.url).hostname:
                continue
            # Legacy shell links can be hidden and have no accessible name
            # until the tree is expanded. Use only the exact navigation label.
            labels = frame.get_by_text(ACTIVITY)
            for label in labels.all():
                if label.evaluate("e => !e.closest('button,input[type=submit]') && (!e.closest('form') || e.closest('nav,aside,a,li,[role=menuitem],[id^=ACTV_],[id^=ETABLISSEMENT_]'))"):
                    # An accessible label can be a span inside the actual shell link.
                    link = label.locator("xpath=ancestor-or-self::a[1]")
                    action = link if link.count() == 1 else label
                    if action.is_visible():
                        action.click()
                    else:
                        action.evaluate("e => e.click()")
                    return True
        return False

    if activity():
        return
    parent = shell.get_by_text(re.compile(r"^Mon [ée]tablissement$", re.I)).filter(visible=True)
    if parent.count():
        parent.first.click()
    group = shell.get_by_text(re.compile(r"^(?:G[ée]rer|Gestion) (?:les |des )?comptes(?: CYCLADES)?(?: (?:de mes|des) [ée]l[èe]ves)?$", re.I)).filter(visible=True)
    if not activity():
        if group.count():
            group.first.click()
        if not activity():
            shell.get_by_text(ACTIVITY).filter(visible=True).first.click()


CONFIRM_CONTEXT = re.compile(r"^\s*(?:valider|confirmer|continuer|sélectionner|appliquer|ok|accéder|choisir|suivant|ouvrir)(?:\s+(?:(?:la|le|ce|cette|mon|ma)\s+)?(?:session|contexte|choix|sélection)(?: de travail)?)?[!.]?\s*$", re.I)


def select_account_context(frame, session, academy, attempted, observed):
    from cyclades_portal import select_report_context
    control = frame.locator("#selectContexte:visible")
    if control.count() != 1:
        return False
    options = [v.strip() for v in control.locator("option").all_text_contents()]
    year = re.search(r"\b20\d{2}\b", session).group()
    labels = [words(v).split() for v in options]
    observed.update("-".join(t for t in tokens if t in ("bts","paris","nice") or re.fullmatch(r"20\d{2}",t)) or "autre" for tokens in labels)
    exact = [v for v in options if words(v) == words(session)]
    by_year = [v for v,t in zip(options,labels) if year in t and "bts" in t and not (set(t) & ({"paris","nice"} - {academy}))]
    intermediate = [v for v,t in zip(options,labels) if "bts" in t and not any(re.fullmatch(r"20\d{2}",x) for x in t)
                    and not (set(t) & ({"paris","nice"} - {academy}))]
    school = [v for v,t in zip(options,labels) if ACADEMIES[academy][1].lower() in t]
    choices = exact or by_year or intermediate or school
    if len(choices) != 1:
        return False
    choice = choices[0]
    if (frame, choice) in attempted:
        return False
    scoped_year = bool(exact or by_year)
    if select_report_context(frame, choice):
        attempted.add((frame,choice))
        return scoped_year
    control.select_option(index=options.index(choice))
    attempted.add((frame,choice))
    # Some versions use a link or styled span instead of a submit button in
    # the context dialog. Never submit an account-generation form.
    if control.is_visible():
        confirm = frame.get_by_role("button",name=CONFIRM_CONTEXT).or_(frame.get_by_role("link",name=CONFIRM_CONTEXT)).filter(visible=True)
        if not confirm.count():
            confirm = frame.get_by_text(CONFIRM_CONTEXT).filter(visible=True)
        if confirm.count() == 1 and confirm.is_enabled():
            confirm.click()
    return scoped_year


def read_account_slips(page, academy, session, records, cipher):
    from cyclades_portal import CENTRAL, navigate, official

    wanted = {key for record in records if (key := slip_key(record))}
    if not wanted:
        return
    context = page.context
    existing = set(context.pages)
    previous = {frame: frame.url for tab in existing for frame in tab.frames}
    shell = context.new_page()
    shell.set_default_timeout(6000)
    downloads, responses = [], []

    def watch(window):
        window.on("download", lambda item: downloads.append(item))

    def pdf_response(response):
        if (official(response.url) and response.ok
                and "application/pdf" in response.headers.get("content-type", "").lower()
                and "attachment" not in response.headers.get("content-disposition", "").lower()
                and previous.get(response.frame) != response.frame.url):
            responses.append(response)

    def frames():
        return [f for window in context.pages for f in window.frames if previous.get(f) != f.url and (
                official(f.url) or (f.url in ("about:blank", "about:srcdoc") and f.parent_frame and official(f.parent_frame.url)))]

    def visible_control(frame, pattern):
        return frame.get_by_role("button", name=pattern).or_(frame.get_by_role("link", name=pattern)).filter(visible=True)

    phase = "menu établissement"
    context_seen = False
    selected_session = False
    attempted, observed = set(), set()
    context.on("page", watch)
    context.on("response", pdf_response)
    watch(shell)
    try:
        entry = page.url if urlsplit(page.url).hostname == CENTRAL else ACADEMIES[academy][3]
        navigate(shell, entry)
        if urlsplit(shell.url).hostname != CENTRAL:
            raise CycladesError("Espace établissement inaccessible.")
        # The connected tab was already verified for the academy's UAI. The
        # new tab uses that same session, as does the official PJ worklist.
        phase = "chargement du menu"
        shell.locator("#ETABLISSEMENT_INSCRIPTION").or_(shell.get_by_role("heading", level=1).filter(
            has_text=ACADEMIES[academy][1])).first.wait_for(state="attached", timeout=20000)
        phase = "activité comptes élèves"
        open_accounts_menu(shell)
        phase = "compte rendu existant"
        deadline = time.monotonic() + 16
        summary = None
        while time.monotonic() < deadline and summary is None:
            for frame in frames():
                if frame.locator("#selectContexte:visible").count():
                    context_seen = True
                if select_account_context(frame, session, academy, attempted, observed):
                    selected_session = True
                    break
                button = visible_control(frame, SUMMARY)
                if not button.count():
                    button = frame.get_by_text(SUMMARY).filter(visible=True)
                if button.count() == 1 and button.is_enabled():
                    # The activity displays the selected BTS context above its parameters.
                    text = frame.locator("body").inner_text(timeout=1500)
                    target_year = re.search(r"\b20\d{2}\b",session).group()
                    if selected_session or (target_year in words(text).split() and "bts" in words(text).split()
                            and academy in words(text).split()):
                        summary = button
                        break
            if summary is None:
                shell.wait_for_timeout(200)
        if summary is None:
            raise CycladesError("Compte rendu indisponible.")
        summary.click()
        phase = "document du compte rendu"
        deadline = time.monotonic() + 12
        clicked = False
        while time.monotonic() < deadline and not (downloads or responses):
            for frame in frames() if not clicked else ():
                labels = frame.get_by_text(DOCUMENT).filter(visible=True)
                for label in labels.all():
                    caption = label.inner_text(timeout=1200)
                    if len(caption) > 180 or re.search(r"2\s*(?:par|/)|deux", caption, re.I):
                        continue
                    # Only the download of this edition, never a generic submit button.
                    control = label.locator("xpath=ancestor-or-self::a[1]")
                    if not control.count():
                        row = label.locator("xpath=ancestor::*[self::tr or self::li][1]")
                        control = row.locator("a:visible,button[title*='charg' i]:visible,img[title*='charg' i]:visible")
                        if not control.count():
                            holder = label.locator("xpath=ancestor::*[.//*[self::a or self::button or self::img]][1]")
                            if holder.count() and holder.get_by_text(DOCUMENT).count() <= 1:
                                control = holder.locator("a:visible,button[title*='charg' i]:visible,img[title*='charg' i]:visible,img[alt*='charg' i]:visible,img[src*='disquette' i]:visible")
                        if not control.count() and label.get_attribute("onclick"):
                            control = label
                    if control.count() == 1:
                        control.click()
                        clicked = True
                        break
                if clicked:
                    break
            shell.wait_for_timeout(200)
        phase = "lecture du PDF"
        raw = b""
        if downloads:
            item = downloads[0]
            if official(item.url.removeprefix("blob:")) and (path := item.path()) and Path(path).stat().st_size <= MAX_BYTES:
                raw = Path(path).read_bytes()
        elif responses:
            response = responses[0]
            size = response.headers.get("content-length", "")
            if not size.isdecimal() or int(size) <= MAX_BYTES:
                raw = response.body()
        if not raw:
            phase = "téléchargement du PDF" if clicked else "lien du PDF"
            raise CycladesError("PDF indisponible.")
        found = read_slips(raw, wanted)
        for record in records:
            password = found.get(slip_key(record))
            if password:
                record["sealed_slip"] = cipher.encrypt(password.encode()).decode()
        logging.getLogger(__name__).warning("CYCLADES %s papillons : %d/%d accès rattachés", academy, len(found), len(wanted))
    except (Error, CycladesError, OSError, ValueError):
        # Keep navigation identifiers only, never page text or candidate data.
        structure = []
        ids = set()
        controls = set()
        for frame in frames():
            try:
                # Log structural facts from the menu only. Never values, URLs or PDF text.
                nodes = frame.get_by_text(ACTIVITY)
                if nodes.count():
                    structure.extend(nodes.evaluate_all("""els => els.slice(0,4).map(e => {
                        const tags=[]; for(let n=e; n && tags.length<5; n=n.parentElement) {
                            tags.push(n.tagName + (n.hasAttribute('onclick')?'*':'') +
                                (n.tagName==='A' && n.getAttribute('href')?'(link)':''));
                        } return tags.join('/');
                    })"""))
                for flag, pattern in (("générer",re.compile("^Générer$",re.I)),
                                      ("choix",re.compile("choisir.*session",re.I)),
                                      ("aucune édition",re.compile("aucun(?:e)? (?:édition|compte.rendu|traitement)",re.I))):
                    if frame.get_by_text(pattern).count():
                        controls.add(flag)
                if frame.locator("#selectContexte:visible").count():
                    controls.add("sélecteur")
                ids.update(frame.locator('[id^="ACTV_"],[id^="ETABLISSEMENT_"]').evaluate_all(
                    "(els) => els.map(e => e.id).filter(s => /^(ACTV|ETABLISSEMENT)_[A-Z_]{1,90}$/.test(s) && /COMPTE|ETABLISSEMENT_|PAPILLON/.test(s))"))
                for name, pattern in (("activité", ACTIVITY), ("compte-rendu", SUMMARY), ("document", DOCUMENT)):
                    if frame.get_by_text(pattern).count():
                        controls.add(name)
            except Error:
                continue
        logging.getLogger(__name__).warning("CYCLADES %s papillons : lecture indisponible (%s), structure %s, contexte %s/%s [%s], contrôles %s, menu %s",
            academy, phase, ",".join(structure) or "—", context_seen, selected_session if phase not in
            ("menu établissement","chargement du menu","activité comptes élèves") else False, ",".join(sorted(observed)), ",".join(sorted(controls)) or "—", ",".join(sorted(ids)) or "—")
    finally:
        context.remove_listener("response", pdf_response)
        context.remove_listener("page", watch)
        for window in context.pages:
            if window not in existing:
                window.close()
