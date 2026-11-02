"""Regression cases for establishment identity, daily runs and the BTS candidate sheet."""
import csv
import io
import json
import threading
from contextlib import closing
from datetime import datetime, timedelta

import pytest

from cyclades import cipher, run_due, sheet_status
from cyclades_data import ACADEMIES, PARIS, CycladesError, apply_report, parse_report, with_exams
from test_admissions_2027 import application, auth, client, seed


def export(academy="paris", status="Pré-inscrit", *, issued="02/11/2026 08:10", exams=False, empty=False):
    uai = ACADEMIES[academy][1]
    text = io.StringIO()
    writer = csv.writer(text, delimiter=";")
    states = "Inscrit, Pré-inscrit" if exams else "Anomalie, Inscrit, Non inscrit, Pré-inscrit, Redoublant"
    for line in ("2027", "Listes détaillées", f"CFA ({uai})", "Type d'édition : Liste détaillée",
                 "Edité le " + issued, "Critères de recherche : Etat Egal " + states):
        writer.writerow([line])
    head = ["N° Candidat", "N° inscription", "N° version", "Nom de famille", "Prénom(s)", "Date de naissance",
            "Code établissement inscription", "Etat", "Mesures pour Handicap", "Identifiant de connexion"]
    vals = ["0001234", "001", "2", "TÉST", "Camille Marie", "03/02/2005", uai, status, "private-medical", "private-login"]
    if exams:
        head.append("31213 : E1 - P - Langue vivante")
        vals.append("Inscrit - Anglais")
    writer.writerow(head)
    if not empty:
        writer.writerow(vals)
    return text.getvalue().encode("utf-8-sig")


@pytest.fixture
def student(client, monkeypatch):
    monkeypatch.setenv("CYCLADES_SYNC_DISABLED", "1")
    monkeypatch.setattr(application.app, "secret_key", "a-long-test-secret-for-cyclades")
    seed(2025, "student")
    with application.db() as conn:
        conn.execute("UPDATE candidats SET date_naissance='2005-02-03' WHERE id='student'")
    return client


def test_real_csv_shape_secure_link_and_admin_only(student):
    client = student
    url = "/admin/parametres/cyclades/paris/import"
    assert client.get("/admin/candidat/student").status_code == 302
    assert client.post(url).status_code == 403
    auth(client)
    assert client.get("/admin/parametres").status_code == 200
    with client.session_transaction() as state:
        token = state["_planning_csrf"]
    assert client.post(url, data={"csrf_token": "other"}).status_code == 403
    response = client.post(url, data={"csrf_token": token, "export": (io.BytesIO(export()), "liste.csv"),
                                "exams": (io.BytesIO(export(exams=True)), "examens.csv")})
    assert response.status_code == 303
    page = client.get("/admin/candidat/student?return_to=/admin/inscriptions").get_data(as_text=True)
    for expected in ('id="tab-cyclades"', 'id="panel-cyclades"', "Pré-inscrit", "Inscrit - Anglais", "Import manuel", "08h10"):
        assert expected in page
    for sensitive in ("private-login", "private-medical"):
        assert sensitive not in page
    with pytest.raises(CycladesError):
        parse_report(export("nice"), "paris")
    with pytest.raises(CycladesError):
        parse_report(export(), "paris", expected_year=2028)


def test_ambiguous_identity_missing_and_newer_data(student):
    with closing(application.db()) as conn:
        def apply(data, origin="auto"):
            with conn:
                return apply_report(conn, "paris", parse_report(data, "paris"), origin)
        def snapshot(cid="student"):
            return dict(conn.execute("SELECT * FROM cyclades_students WHERE candidate_id=?", (cid,)).fetchone())

        assert apply(export())
        assert snapshot()["outcome"] == "matched"
        partial = parse_report(export(exams=True), "paris")
        assert not partial.complete
        assert with_exams(parse_report(export(), "paris"), partial).records[0][-1]["exams"]
        assert apply(export(issued="03/11/2026 08:10", empty=True))
        assert snapshot()["outcome"] == "missing" and "Pré-inscrit" in snapshot()["records"]
        assert not apply(export(), "import")
        seed(2025, "homonyme")
        conn.execute("UPDATE candidats SET date_naissance='2005-02-03' WHERE id='homonyme'")
        assert apply(export(issued="04/11/2026 08:10"))
        assert all(snapshot(cid)["outcome"] == "ambiguous" and json.loads(snapshot(cid)["records"]) == []
                   for cid in ("student", "homonyme"))
        conn.execute("UPDATE candidats SET date_naissance='2006-02-03' WHERE id='homonyme'")
        assert not apply(export())
        assert apply(export(issued="05/11/2026 08:10"))
        assert snapshot()["outcome"] == "matched"
        assert snapshot("homonyme")["outcome"] == "missing"


def test_daily_runs_restart_concurrency_and_one_academy_down(student, tmp_path):
    app = application.app
    clock = datetime(2026, 11, 2, 9, tzinfo=PARIS)
    secret = cipher(app).encrypt(b'{"username":"example","password":"unused"}')
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=?", (secret,))
    calls, started, release = [], threading.Event(), threading.Event()

    def fetch(academy, credentials):
        calls.append(academy)
        if academy == "paris":
            started.set()
            assert release.wait(8)
            yield parse_report(export(), academy)
        else:
            raise CycladesError("Accès à renouveler.")

    def tick(at):
        run_due(app, application.db, tmp_path, now=at, fetch=fetch)
    worker = threading.Thread(target=tick, args=(clock,))
    worker.start()
    assert started.wait(8)
    try:
        tick(clock)
        assert calls == ["paris"]
    finally:
        release.set()
        worker.join(8)
    tick(clock + timedelta(hours=3))
    tick(clock + timedelta(days=1, hours=-2))
    assert calls == ["paris", "nice"]
    tick(clock + timedelta(days=1))
    assert calls == ["paris", "nice", "paris", "nice"]
    with application.db() as conn:
        local = dict(conn.execute("SELECT * FROM candidats WHERE id='student'").fetchone())
        result = sheet_status(conn, local)
        assert result["paris"]["status"] == "ok"
        assert result["nice"]["status"] == "error"
        assert result["paris"]["sessions"][0]["records"][0]["status"] == "Pré-inscrit"
        assert result["nice"]["sessions"] == []


def test_config_is_encrypted_and_never_redisplayed(student):
    client = student
    auth(client)
    client.get("/admin/parametres")
    with client.session_transaction() as state:
        token = state["_planning_csrf"]
    url = "/admin/parametres/cyclades/nice/connexion"
    response = client.post(url, data=dict(csrf_token=token, action="save", username="test-private-login",
                                          password="private-secret", birthdate="01012000"))
    assert response.status_code == 303
    with application.db() as conn:
        stored = conn.execute("SELECT credential FROM cyclades_accounts WHERE academy='nice'").fetchone()[0]
        assert b"private" not in stored
        assert json.loads(cipher(application.app).decrypt(stored))["password"] == "private-secret"
    assert b"private-secret" not in client.get("/admin/parametres").data
    assert client.post(url, data=dict(csrf_token=token, action="remove")).status_code == 303
    with application.db() as conn:
        assert conn.execute("SELECT credential FROM cyclades_accounts WHERE academy='nice'").fetchone()[0] is None


def test_recover_saved_connection_after_reader_fix_and_manual_retry(student, tmp_path):
    from cyclades import READER_VERSION
    clock = datetime(2026, 11, 2, 17, 30, tzinfo=PARIS)
    credential = cipher(application.app).encrypt(b'{"username":"test","password":"unchanged"}')
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=?,day=?,status='ok'", (credential,clock.date().isoformat()))
        conn.execute("UPDATE cyclades_accounts SET status='error' WHERE academy='paris'")
    calls = []
    def unavailable(key, credentials):
        calls.append(key)
        yield CycladesError("La liste est indisponible.")
    def check():
        run_due(application.app, application.db, tmp_path, now=clock, fetch=unavailable)
    check()
    check()
    assert calls == ["paris"]
    client = student
    auth(client)
    assert "Relancer la vérification" in client.get("/admin/parametres").get_data(as_text=True)
    with client.session_transaction() as state:
        token = state["_planning_csrf"]
    for _ in range(2):
        assert client.post("/admin/parametres/cyclades/paris/connexion", data={"action":"retry","csrf_token":token}).status_code == 303
    check()
    check()
    assert calls == ["paris","paris"]
    with application.db() as conn:
        row = conn.execute("SELECT credential,reader_version FROM cyclades_accounts WHERE academy='paris'").fetchone()
        assert row["credential"] == credential and row["reader_version"] == READER_VERSION


def test_portal_diagnostic_discards_browser_exception_details():
    from playwright.sync_api import TimeoutError as BrowserTimeout
    from cyclades_portal import portal_step
    class Page:
        url = "https://login.ac-paris.fr/idp?token=confidentiel"
        def evaluate(self, _):
            return "chargement de session"
    with pytest.raises(CycladesError) as caught:
        with portal_step(Page(), "Connexion interrompue"):
            raise BrowserTimeout("confidentiel")
    assert str(caught.value) == "Connexion interrompue (login.ac-paris.fr, délai dépassé, chargement de session)."


def test_state_filter_in_detached_listbox_and_native_select():
    import os
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from cyclades_data import ALL_STATES
    from cyclades_portal import choose_states

    labels = ["Inscrit", "Non inscrit", "Pré-inscrit", "Redoublant", "Anomalie"]
    with sync_playwright() as engine:
        path = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
        if not path and not Path(engine.chromium.executable_path).exists():
            pytest.skip("Chromium requis pour le test des filtres CYCLADES")
        with engine.chromium.launch(executable_path=path) as browser:
            page = browser.new_page()
            page.set_content('<fieldset><legend>État</legend><select multiple>' +
                             ''.join(f'<option>{label}</option>' for label in labels) + '</select></fieldset>')
            assert choose_states(page, False) == ALL_STATES
            assert page.locator("option:checked").count() == 5
            page.set_content('<fieldset><legend>Configurer le critère État</legend>'
                '<button onclick="document.querySelector(\'ul\').hidden=!document.querySelector(\'ul\').hidden">Valeur recherchée</button></fieldset>'
                '<ul role="listbox" hidden>' + ''.join(
                f'<li role="option" aria-selected="false" onclick="this.ariaSelected=this.ariaSelected===\'true\'?\'false\':\'true\'">{label}</li>'
                for label in labels) + '</ul>')
            assert choose_states(page, False) == ALL_STATES
            assert choose_states(page, True) == {"inscrit", "pre inscrit"}
            assert page.locator('[aria-selected=true]').all_text_contents() == ["Inscrit","Pré-inscrit"]

            # The shell can display the session picker before loading the report in an iframe.
            from cyclades_portal import REPORT_LINK, report_frame
            origin = "https://cyclades.education.gouv.fr"
            def serve_fixture(route):
                body = ('<fieldset><legend>État</legend><select multiple>' +
                        ''.join(f'<option>{v}</option>' for v in labels) +
                        '</select></fieldset><button id="editionCSV">CSV</button>')
                if route.request.url.endswith("/shell"):
                    body = ('<select id="selectContexte"><option>BTS</option></select>'
                            '<a href="/edition" target="edition">' + REPORT_LINK + '</a>'
                            '<iframe name="edition"></iframe>')
                route.fulfill(content_type="text/html; charset=utf-8", body=body)
            page.route(origin + "/**", serve_fixture)
            page.goto(origin + "/shell")
            frame = report_frame(page, REPORT_LINK, "paris")
            assert frame != page.main_frame
            assert choose_states(frame, False) == ALL_STATES
