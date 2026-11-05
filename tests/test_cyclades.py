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
            "Code établissement inscription", "Etat", "Mesures pour Handicap", "Identifiant de connexion", "Mot de passe"]
    vals = ["0001234", "001", "2", "TÉST", "Camille Marie", "03/02/2005", uai, status, "private-medical", "camille.test01", "private-password"]
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
    from akto_sync import schema as akto_schema
    from opco_sync import schema as opco_schema
    from wedof_daily_sync import schema as wedof_schema
    with application.db() as conn:
        akto_schema(conn)
        opco_schema(conn)
        wedof_schema(conn)
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
    assert "Identifiant de connexion Cyclades" in page and "camille.test01" in page
    with application.db() as conn:
        stored = conn.execute("SELECT records FROM cyclades_students WHERE candidate_id='student'").fetchone()[0]
    for sensitive in ("private-password", "private-medical"):
        assert sensitive not in stored and sensitive not in page
    fragment = "/admin/candidat/student/cyclades"
    assert "camille.test01" in client.get(fragment).text
    assert application.app.test_client().get(fragment).status_code == 403
    assert "camille.test01" not in client.get("/admin/inscriptions").text
    with pytest.raises(CycladesError):
        parse_report(export("nice"), "paris")
    with pytest.raises(CycladesError):
        parse_report(export(), "paris", expected_year=2028)


@pytest.mark.parametrize("academy", ["nice", "paris"])
def test_only_the_matched_students_official_login_is_displayed(student, academy):
    auth(student)
    seed(2025, "another")
    with application.db() as conn:
        conn.execute("UPDATE candidats SET nom='Autre',date_naissance='2005-02-03' WHERE id='another'")
    fragment = "/admin/candidat/student/cyclades"
    for value, label in ((b"camille.test01", "camille.test01"),
                         (b"Pas de compte candidat Cyclades", "Pas de compte candidat Cyclades"),
                         (b"-", "Indisponible dans ce relevé")):
        report = parse_report(export(academy).replace(b"camille.test01", value), academy)
        with application.db() as conn:
            apply_report(conn, academy, report, "auto")
        page = student.get(fragment).text
        assert label in page
        if value != b"camille.test01":
            assert "camille.test01" not in page
        assert "Identifiant de connexion Cyclades" not in student.get("/admin/candidat/another/cyclades").text


def test_exam_export_can_supply_a_missing_login_for_the_same_registration():
    supplement = parse_report(export(exams=True), "paris")
    for original, expected in ((b"-", "camille.test01"), (b"updated.login", "updated.login")):
        primary = parse_report(export().replace(b"camille.test01", original), "paris")
        record = with_exams(primary, supplement).records[0][-1]
        assert record["details"]["Identifiant de connexion"] == expected


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
        assert result["state"] == "matched" and result["partial"]
        assert [(item["academy"], item["status"]) for item in result["matches"]] == [("Paris", "Pré-inscrit")]


def test_settings_manual_check_and_daily_schedule_are_independent(student, tmp_path):
    path = "/admin/parametres/cyclades/paris/connexion"
    assert student.post(path, data={"action": "retry"}).status_code == 403
    auth(student)
    student.get("/admin/parametres")
    with student.session_transaction() as state:
        token = state["_planning_csrf"]
    def request_check():
        response = student.post(path, data={"action": "retry", "csrf_token": token})
        assert response.status_code == 303
        assert response.location.endswith("#cyclades-paris")
    assert student.post(path, data={"action": "retry", "csrf_token": "wrong"}).status_code == 403
    request_check()
    assert "Enregistrez les accès" in student.get("/admin/parametres").get_data(as_text=True)

    calls = []
    def fetch(key, credentials):
        calls.append(key)
        yield parse_report(export(key), key)
    def tick(hour):
        run_due(application.app, application.db, tmp_path,
                now=datetime(2026, 11, 3, hour, tzinfo=PARIS), fetch=fetch)

    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=?,day='2026-11-02',status='ok'",
                     (cipher(application.app).encrypt(b'{"username":"example","password":"unused"}'),))
    tick(6)
    assert not calls
    request_check()
    request_check()
    tick(7)
    assert calls == ["paris"]
    tick(8)
    assert calls == ["paris", "paris", "nice"]
    request_check()
    tick(12)
    tick(13)
    assert calls == ["paris", "paris", "nice", "paris"]


def test_candidate_search_shows_only_personal_results_and_preserves_history(student):
    client = student
    auth(client)
    path = "/admin/candidat/student/cyclades"
    def content():
        return client.get(path).get_data(as_text=True)
    with application.db() as conn:
        for key in ACADEMIES:
            apply_report(conn, key, parse_report(export(key, empty=True), key), "auto")
    empty = content()
    assert empty.count("Aucun dossier trouvé") == 1
    assert all(value not in empty for value in ("Paris", "Nice", "Session 2027", "Ouvrir le portail"))
    with application.db() as conn:
        apply_report(conn, "nice", parse_report(export("nice", issued="03/11/2026 09:00"), "nice"), "import")
    matched = content()
    assert "Académie de Nice" in matched and "Session 2027" in matched and "Pré-inscrit" in matched
    assert "Paris" not in matched and "Aucun dossier trouvé" not in matched
    with application.db() as conn:
        apply_report(conn, "nice", parse_report(export("nice", empty=True, issued="04/11/2026 09:00"), "nice"), "auto")
    history = content()
    assert "Aucun dossier trouvé" in history
    assert history.index('<details class="cy-history">') < history.index("Académie de Nice")


def test_candidate_search_queues_once_and_does_not_confuse_unchecked_with_missing(student):
    client = student
    path = "/admin/candidat/student/cyclades"
    assert client.get(path).status_code == client.post(path).status_code == 403
    auth(client)
    client.get("/admin/candidat/student")
    with client.session_transaction() as state:
        token = state["_planning_csrf"]
    assert client.post(path, data={"csrf_token":"incorrect"}).status_code == 403
    headers = {"X-Cyclades-Fragment": "1"}
    def post(mode):
        return client.post(path, data={"csrf_token":token, "mode":mode}, headers=headers).get_data(as_text=True)
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=?,status='ok',attempted=?",
                     (b"fixture", datetime.now(PARIS).timestamp()))
        apply_report(conn, "paris", parse_report(export(empty=True), "paris"), "auto")
    assert 'data-initial="1"' in client.get(path).get_data(as_text=True)
    assert "Recherche en cours" in post("initial")
    assert "Recherche en cours" in post("initial")
    with application.db() as conn:
        assert dict(conn.execute("SELECT academy,status FROM cyclades_accounts")) == {"paris":"ok","nice":"pending"}
        apply_report(conn, "nice", parse_report(export("nice", empty=True), "nice"), "auto")
        conn.execute("UPDATE cyclades_accounts SET status='ok' WHERE academy='nice'")
    assert "moins de cinq minutes" in post("manual")
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET status='error' WHERE academy='nice'")
    partial = client.get(path).get_data(as_text=True)
    assert "Recherche incomplète" in partial and "Aucun dossier trouvé" not in partial
    assert "Nice" not in partial and "Paris" not in partial
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET attempted=0")
    assert 'data-busy="1"' in post("manual")
    with application.db() as conn:
        assert {r[0] for r in conn.execute("SELECT status FROM cyclades_accounts")} == {"pending"}
        conn.execute("UPDATE candidats SET date_naissance=NULL WHERE id='student'")
    assert "Identité à compléter" in post("manual")
    assert client.get("/admin/candidat/inexistant/cyclades").status_code == 404


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
            from cyclades_portal import open_list_menu
            page.set_content('''<button id="ETABLISSEMENT_INSCRIPTION" onclick="document.body.dataset.closed='yes'">Inscription</button>
                <button id="ACTV_EDITION_LISTE_CAND_INSCRIPTION" hidden onclick="document.querySelector('a').hidden=false">Listes</button>
                <a href="#edition" hidden>Liste détaillée de mes élèves</a>
                <script>setTimeout(() => document.querySelector('[hidden]').hidden = false, 250)</script>''')
            assert open_list_menu(page)
            assert open_list_menu(page)
            assert page.locator("body").get_attribute("data-closed") is None
            page.set_content('<fieldset><legend>État</legend><select multiple>' +
                             ''.join(f'<option>{label}</option>' for label in labels) + '</select></fieldset>')
            assert choose_states(page, False) == ALL_STATES
            assert page.locator("option:checked").count() == 5
            page.locator("select").evaluate("""el => {
                el.hidden = true;
                el.addEventListener('change', () => document.body.dataset.changed = 'yes');
            }""")
            assert choose_states(page, True) == {"inscrit", "pre inscrit"}
            assert page.locator("option:checked").all_text_contents() == ["Inscrit", "Pré-inscrit"]
            assert page.locator("body").get_attribute("data-changed") == "yes"
            page.set_content('''<input id="editionCSV" type="button" value="Exporter en CSV">
                <a href="#criteres" onclick="setTimeout(() => document.querySelector('fieldset').hidden = false, 100)">
                Critères de sélection</a><fieldset hidden><legend>Configurer le critère « État »</legend>
                <button onclick="document.querySelector('ul').hidden=!document.querySelector('ul').hidden">
                Valeur recherchée</button><ul role="listbox" hidden>''' +
                ''.join(f'<li role="option"><label><input type="checkbox">{v}</label></li>' for v in labels) +
                '</ul></fieldset>')
            assert choose_states(page, False) == ALL_STATES
            assert page.locator("input:checked").count() == 5
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
            page.set_content('''<fieldset><legend>Session</legend><select id="selectContexte">
                <option>BTS 2026</option><option>BTS 2027</option></select>
                <button onclick="this.parentElement.hidden=true; document.getElementById('editionCSV').hidden=false">Valider</button>
                </fieldset><button id="editionCSV" hidden>Exporter en CSV</button>
                <button onclick="document.body.dataset.invalid='yes'">Valider l’inscription</button>''')
            assert report_frame(page, REPORT_LINK, "paris", "BTS 2027", already_open=True) == page.main_frame
            assert page.locator("option:checked").inner_text() == "BTS 2027"
            assert page.locator("body").get_attribute("data-invalid") is None


def test_document_fields_are_independent_from_enrolment_and_candidate_validation(student):
    auth(student)
    source = list(csv.reader(io.StringIO(export().decode('utf-8-sig')), delimiter=';'))
    source[-2].extend(["Pièce justificative demandée", "PJ déposée par candidat ON",
                       "PJ validée par candidat ON", "Statut PJ"])
    source[-1].extend(["Confirmation signée", "Oui", "Oui", "Non conforme"])
    source.append([*source[-1][:-4], "Document d’identité", "Non", "Non", "En attente de contrôle"])
    content = io.StringIO()
    csv.writer(content, delimiter=';').writerows(source)
    with application.db() as conn:
        apply_report(conn, "paris", parse_report(content.getvalue().encode(), "paris"), "import")
    html = student.get("/admin/candidat/student/cyclades").get_data(as_text=True)
    assert html.count('class="cy-record"') == 1
    assert all(v in html for v in ("Confirmation signée", "Déposée", "Non conforme", "Non déposée", "En attente de contrôle"))
    from cyclades_data import document_status
    piece = document_status({"Pièce justificative demandée": "Attestation", "Etat": "Inscrit",
                             "PJ validée par candidat ON": "Oui"})
    assert piece["review"] is None and piece["deposit"] is None


def test_piece_statement_provenance_and_replacement(student):
    auth(student)
    path = "/admin/candidat/student/cyclades"
    with application.db() as conn:
        apply_report(conn, "nice", parse_report(export("nice"), "nice"), "auto")
    student.get("/admin/candidat/student")
    with student.session_transaction() as session:
        token = session["_planning_csrf"]
    statement = ("BTS - 2027 - ACADÉMIE DE NICE\nN° candidat : 0001234 N° inscription : 001 Version : 2\n"
                 "Code Etab : 0831774C\nPièces justificatives conformes : 0 / 1\n"
                 "TEST01 : Justificatif test\nAucun fichier par le candidat\nAucun fichier par le gestionnaire\n"
                 "Traitement administratif : Statut : En attente de contrôle")
    data = dict(csrf_token=token, observed="2026-11-02T08:24", statement=statement)
    url = path + "/nice/2027/releve-pieces"
    assert student.post(url, data=dict(data, csrf_token="wrong")).status_code == 403
    student.post(url, data=dict(data, statement=statement.replace("Version : 2", "Version : 9")))
    assert "Justificatif test" not in student.get(path).get_data(as_text=True)
    assert student.post(url, data=data).status_code == 303
    with application.db() as conn:
        newer = parse_report(export("nice", issued="04/11/2026 08:10"), "nice")
        apply_report(conn, "nice", newer, "auto")
    html = student.get(path).get_data(as_text=True)
    assert "Relevé manuel" in html and "Justificatif test" in html and "En attente de contrôle" in html
    with application.db() as conn:
        latest = parse_report(export("nice", issued="05/11/2026 08:10"), "nice")
        latest.records[0][-1].update(documents=[], requested=0, conforming=0, documents_checked="05/11/2026 à 08h10")
        apply_report(conn, "nice", latest, "auto")
    html = student.get(path).get_data(as_text=True)
    assert "Relevé manuel" not in html and "Justificatif test" not in html


def test_new_students_eligible_in_both_academies_without_a_previous_sync(student, tmp_path, monkeypatch):
    import cyclades
    clock = datetime(2026, 11, 3, 8, tzinfo=PARIS)
    captured = []
    def read(academy, credentials, matched_records, slip_cipher):
        for year in (2026, 2027):
            raw = export(academy).decode("utf-8-sig").replace("2027", str(year), 1)
            report = parse_report(raw.encode(), academy)
            matches = matched_records(report)
            assert matches == [report.records[0][-1]]
            captured.append((academy, year))
            yield report
    monkeypatch.setattr(cyclades, "read_academy", read)
    credential = cipher(application.app).encrypt(b'{"username":"example","password":"unused"}')
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=?", (credential,))
    run_due(application.app, application.db, tmp_path, now=clock)
    run_due(application.app, application.db, tmp_path, now=clock + timedelta(minutes=1))
    assert captured == [("paris", 2026), ("paris", 2027), ("nice", 2026), ("nice", 2027)]


def test_interrupted_connection_retries_once_in_the_same_slot(student, tmp_path):
    from cyclades_data import CycladesNetworkError
    clock = datetime(2026, 11, 3, 8, tzinfo=PARIS)
    credential = cipher(application.app).encrypt(b'{"username":"example","password":"unused"}')
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=? WHERE academy='nice'", (credential,))
    calls = []
    def fetch(key, credentials):
        calls.append(key)
        raise CycladesNetworkError("Connexion interrompue.")
        yield
    for minutes in (0, 12, 30, 31, 90):
        run_due(application.app, application.db, tmp_path, now=clock + timedelta(minutes=minutes), fetch=fetch)
    assert calls == ["nice", "nice"]


def test_interrupted_nice_redirect_uses_verified_bts_session_before_another_login(monkeypatch):
    from unittest.mock import Mock
    import cyclades_portal as portal
    page, context = Mock(), Mock()
    failed = {("login.ac-nice.fr", "document", "ERR_CONNECTION_RESET")}
    login = Mock(side_effect=CycladesError("Délai dépassé"))
    resume = Mock()
    monkeypatch.setattr(portal, "open_establishment", login)
    monkeypatch.setattr(portal, "open_bts_menu", resume)
    monkeypatch.setattr(portal, "screen_hint", lambda _: "formulaire d’identification")
    assert portal.connect_portal(context, page, "nice", {}, failed) is context.new_page.return_value
    assert login.call_count == resume.call_count == 1


def test_interrupted_login_explains_network_error_but_does_not_retry_challenges(monkeypatch):
    from unittest.mock import Mock
    import cyclades_portal as portal
    page, context, failed = Mock(), Mock(), set()
    def login(*args):
        failed.add(("login.ac-nice.fr", "document", "ERR_CONNECTION_RESET"))
        raise CycladesError("Authentification interrompue")
    monkeypatch.setattr(portal, "open_establishment", login)
    monkeypatch.setattr(portal, "open_bts_menu", Mock(side_effect=CycladesError("Session indisponible")))
    monkeypatch.setattr(portal, "screen_hint", lambda _: "formulaire d’identification")
    with pytest.raises(portal.CycladesNetworkError, match="coupée pendant l’identification"):
        portal.connect_portal(context, page, 'nice', {}, failed)
    context.reset_mock()
    monkeypatch.setattr(portal, "screen_hint", lambda _: "validation supplémentaire")
    with pytest.raises(CycladesError, match="Authentification interrompue"):
        portal.connect_portal(context, page, 'nice', {}, failed)
    context.new_page.assert_not_called()


def test_enrollment_indicator_requires_explicit_deposits_and_consistent_reviews():
    from cyclades_data import registration_indicator
    docs = [{"deposit": "Déposée", "review": "Conforme"},
            {"manager": "Déposée", "review": "En attente de contrôle"}]
    record = dict(status="Inscrit", requested=2, conforming=1, documents=docs)
    assert registration_indicator(record)[0] == "orange"
    docs[1]["review"] = "Conforme"
    assert registration_indicator(record)[0] == "red"  # Counter still reports 1/2.
    record["conforming"] = 2
    assert registration_indicator(record)[0] == "green"
    for override in [dict(status="Pré-inscrit"), dict(requested=3),
                     dict(piece_summary={"checked": "plus récent", "requested": 2, "conforming": 2})]:
        assert registration_indicator(dict(record, **override))[0] == "red"
    # A conforming piece is received even if the uploader was not reported.
    assert registration_indicator(dict(record, documents=[dict(docs[0], deposit=None), docs[1]]))[0] == "green"
    for change in [dict(deposit="Non déposée", manager="Non déposée"), dict(review="Non conforme")]:
        assert registration_indicator(dict(record, documents=[dict(docs[0], **change), docs[1]]))[0] == "red"
    assert registration_indicator(dict(status="Inscrit"))[0] == "red"
    assert registration_indicator(dict(status="Inscrit", requested=0, conforming=0))[0] == "green"


def test_enrollments_list_and_filtered_refresh_show_same_cyclades_dot(student):
    auth(student)
    now = datetime.now(PARIS)
    year = now.year + (now.month >= 9)
    with application.db() as conn:
        report = parse_report(export("nice", status="Inscrit"), "nice")._replace(year=year)
        report.records[0][-1].update(requested=1, conforming=0,
                                     documents=[dict(deposit="Déposée", review="En attente de contrôle")])
        apply_report(conn, "nice", report, "auto")
    page = student.get("/admin/inscriptions?bts=MCO").text
    rows = student.get("/admin/inscriptions/donnees?bts=MCO").json["rows_html"]
    for html in (page, rows):
        assert 'class="cyclades-dot cyclades-dot-orange"' in html.split('data-enrollment-id=')[-1] and '#cyclades' in html
    with application.db() as conn:
        conn.execute("UPDATE cyclades_students SET outcome='missing' WHERE academy='nice'")
    assert 'cyclades-dot-red' in student.get("/admin/inscriptions/donnees?bts=MCO").json['rows_html']

def test_four_conforming_pieces_with_unknown_uploader_in_sheet_and_directory(student):
    auth(student)
    now = datetime.now(PARIS)
    year = now.year + (now.month >= 9)
    report = parse_report(export("nice", status="Inscrit"), "nice")._replace(year=year)
    docs = [dict(label=f"Justificatif {i}", review="Conforme", deposit=None, manager=None) for i in range(4)]
    report.records[0][-1].update(requested=4, conforming=4, documents=docs, documents_checked="03/11/2026 à 12h38")
    with application.db() as conn:
        apply_report(conn, "nice", report, "auto")
    html = student.get("/admin/candidat/student/cyclades").text
    assert html.count("Auteur du dépôt non précisé") == 4 and html.count(">Reçue<") == 4
    assert "4/4 conformes" in html and "Non communiqué" not in html
    listing = student.get("/admin/inscriptions/donnees?bts=MCO").json["rows_html"]
    assert "cyclades-dot-green" in listing


def test_optional_editions_do_not_hide_search_results(student, tmp_path):
    from cyclades_data import DetailWarning

    auth(student)
    clock = datetime(2026, 11, 5, 8, tzinfo=PARIS)
    credential = cipher(application.app).encrypt(b'{"username":"test","password":"test"}')
    with application.db() as conn:
        conn.execute("UPDATE cyclades_accounts SET credential=? WHERE academy='nice'", (credential,))

    attempts = []
    def read(key, credentials):
        attempts.append(key)
        yield parse_report(export(key, empty=True), key)
        yield DetailWarning("Session 2027 : justificatifs lus pour 9/10 inscriptions rattachées.")
        yield DetailWarning("Session 2027 : lecture des papillons provisoirement indisponible.", retryable=True)

    for minutes in (0, 15, 30, 60):
        run_due(application.app, application.db, tmp_path, now=clock + timedelta(minutes=minutes), fetch=read)
    assert attempts == ["nice", "nice"]
    path = "/admin/candidat/student/cyclades"
    assert 'data-state="empty"' in student.get(path).text
    settings = student.get("/admin/parametres").text
    assert "Listes d’inscription vérifiées" in settings and "9/10" in settings
    with student.session_transaction() as state:
        token = state["_planning_csrf"]
    assert student.post(path, data={"csrf_token": token}, headers={"X-Cyclades-Fragment": "1"}).status_code == 200
    with application.db() as conn:
        assert conn.execute("SELECT status FROM cyclades_accounts WHERE academy='nice'").fetchone()[0] == "pending"

    def incomplete(key, credentials):
        yield from read(key, credentials)
        yield CycladesError("Liste de la session 2026 indisponible.")
    run_due(application.app, application.db, tmp_path, now=clock + timedelta(hours=1), fetch=incomplete)
    assert 'data-state="partial"' in student.get(path).text
