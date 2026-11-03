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
SUMMARY = re.compile(r"^Afficher le compte[ -]rendu$", re.I)
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
                    label.dispatch_event("click")
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


def read_account_slips(page, academy, session, records, cipher):
    from cyclades_portal import CENTRAL, navigate, official, select_report_context

    wanted = {key for record in records if (key := slip_key(record))}
    if not wanted:
        return
    context = page.context
    existing = set(context.pages)
    shell = context.new_page()
    shell.set_default_timeout(6000)
    downloads, responses = [], []

    def watch(window):
        window.on("download", lambda item: downloads.append(item))

    def pdf_response(response):
        if (official(response.url) and response.ok
                and "application/pdf" in response.headers.get("content-type", "").lower()
                and "attachment" not in response.headers.get("content-disposition", "").lower()
                and response.frame.page not in existing):
            responses.append(response)

    def frames():
        return [f for window in context.pages if window not in existing for f in window.frames
                if urlsplit(f.url).hostname == CENTRAL]

    def visible_control(frame, pattern):
        return frame.get_by_role("button", name=pattern).or_(frame.get_by_role("link", name=pattern)).filter(visible=True)

    phase = "menu établissement"
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
        selected_session = False
        while time.monotonic() < deadline and summary is None:
            for frame in frames():
                if select_report_context(frame, session):
                    selected_session = True
                    break
                button = visible_control(frame, SUMMARY)
                if not button.count():
                    button = frame.get_by_text(SUMMARY).filter(visible=True)
                if button.count() == 1 and button.is_enabled():
                    # The activity displays the selected BTS context above its parameters.
                    text = frame.locator("body").inner_text(timeout=1500)
                    if selected_session or words(session) in words(text):
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
        ids = set()
        controls = set()
        for frame in frames():
            try:
                ids.update(frame.locator('[id^="ACTV_"],[id^="ETABLISSEMENT_"]').evaluate_all(
                    "(els) => els.map(e => e.id).filter(s => /^(ACTV|ETABLISSEMENT)_[A-Z_]{1,90}$/.test(s) && /COMPTE|ETABLISSEMENT_|PAPILLON/.test(s))"))
                for name, pattern in (("activité", ACTIVITY), ("compte-rendu", SUMMARY), ("document", DOCUMENT)):
                    if frame.get_by_text(pattern).count():
                        controls.add(name)
            except Error:
                continue
        logging.getLogger(__name__).warning("CYCLADES %s papillons : lecture indisponible (%s), menu %s, contrôles %s",
            academy, phase, ",".join(sorted(ids)) or "—", ",".join(sorted(controls)) or "—")
    finally:
        context.remove_listener("response", pdf_response)
        context.remove_listener("page", watch)
        for window in context.pages:
            if window not in existing:
                window.close()
