"""Read the two official establishment lists in separate, short-lived browser contexts."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlsplit

from cyclades_data import ACADEMIES, MAX_BYTES, CycladesError, parse_report, with_exams, words

CENTRAL = "cyclades.education.gouv.fr"
REPORT_LINK = "Liste détaillée de mes élèves"


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
    page.goto(portal, wait_until="domcontentloaded")
    username = page.locator('input[name="j_username"]')
    username.wait_for(state="visible")
    submit_login(page, idp, {"j_username": credentials["username"], "j_password": credentials["password"]})
    # Nice can ask for an additional personal verification after the password.
    if academy == "nice":
        page.wait_for_function("""() => location.hostname !== 'login.ac-nice.fr'
            || document.querySelector('h1')?.innerText.toLowerCase().includes('date de naissance')
            || document.querySelector('[role=alert]')?.innerText.trim()""")
        if urlsplit(page.url).hostname == idp and page.get_by_role("heading", name=re.compile("date de naissance", re.I)).count():
            if not credentials.get("birthdate"):
                raise CycladesError("Nice demande la date de vérification du titulaire du compte.")
            submit_login(page, idp, {"j_password": credentials["birthdate"]})
    try:
        page.wait_for_url(re.compile(r"^https://" + re.escape(urlsplit(portal).hostname) + r"(?=[:/])"),
                          wait_until="domcontentloaded", timeout=25000)
    except Exception:
        raise CycladesError("Connexion académique à vérifier. Un identifiant ou une validation interactive est demandé.") from None
    page.goto(hub, wait_until="domcontentloaded")
    header = page.get_by_role("heading", level=1).filter(has_text=uai)
    header.wait_for(state="visible")
    if urlsplit(page.url).hostname != CENTRAL or "brevet de technicien superieur" not in words(header.inner_text()):
        raise CycladesError("L’établissement ou l’examen ouvert dans CYCLADES ne correspond pas au BTS attendu.")
    page.locator("#ETABLISSEMENT_INSCRIPTION").click()
    page.locator("#ACTV_EDITION_LISTE_CAND_INSCRIPTION").click()
    page.get_by_role("link", name=REPORT_LINK, exact=True).click()


def download_session(page, label, academy, year, *, exam_details=False):
    select = page.locator("#selectContexte")
    if select.locator("option:checked").inner_text().strip() != label:
        # The old form remains briefly in the page when changing sessions.
        # Confirm the year again inside the downloaded CSV before accepting it.
        select.select_option(label=label)
    state = page.get_by_role("group", name=re.compile(r"^Configurer le critère [ÉE]tat$", re.I))
    states_button = state.get_by_role("button", name=re.compile("Valeur recherchée", re.I))
    states_button.click()
    choices = state.get_by_role("checkbox")
    choices.first.wait_for(state="attached")
    expected_states = set()
    for option in state.get_by_role("option").all():
        name = words(option.inner_text())
        selected = not exam_details or name in {"inscrit", "pre inscrit"}
        checkbox = option.get_by_role("checkbox")
        checkbox.set_checked(selected)
        if checkbox.is_checked() != selected:
            raise CycladesError("CYCLADES n’a pas appliqué les critères d’état.")
        if selected:
            expected_states.add(name)
    if not expected_states:
        raise CycladesError("Le filtre des états de CYCLADES est indisponible.")
    states_button.click()
    try:
        with page.expect_download(timeout=45000) as download:
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
    from playwright.sync_api import Error, sync_playwright

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
                page.set_default_timeout(25000)
                open_establishment(page, academy, credentials)
                select = page.locator("#selectContexte")
                select.wait_for(state="visible")
                labels = select.locator("option").all_text_contents()
                area = "PARIS" if academy == "paris" else "NICE"
                sessions = [(label.strip(), int(m[1])) for label in labels
                            if (m := re.match(r"^\s*BTS\s*-\s*(20\d\d)\s*-", label)) and area in label.upper()]
                if not sessions:
                    raise CycladesError("Aucune session BTS de cette académie n’est accessible à l’établissement.")
                for label, year in sorted(sessions, key=lambda item: -item[1]):
                    try:
                        page.get_by_role("link", name=REPORT_LINK, exact=True).click()
                        report = download_session(page, label, academy, year)
                    except (CycladesError, Error):
                        yield CycladesError(f"Liste indisponible pour la session {year}.")
                        continue
                    if any(words(row[-1]["status"]) in {"inscrit", "pre inscrit"} for row in report.records):
                        try:
                            page.get_by_role("link", name="Liste détaillée avec épreuves", exact=True).click()
                            supplement = download_session(page, label, academy, year, exam_details=True)
                            with_exams(report, supplement)
                        except (CycladesError, Error):
                            yield CycladesError(f"Détail des épreuves indisponible pour la session {year}.")
                    yield report
        except Error:
            raise CycladesError("Le parcours académique ou l’accès à la liste BTS doit être vérifié.") from None
        finally:
            browser.close()
