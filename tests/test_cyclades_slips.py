"""Fictitious access slips: never expose a cohort PDF or another candidate's password."""
import io
import json
import os

import pytest
from playwright.sync_api import sync_playwright
from reportlab.pdfgen.canvas import Canvas

from cyclades import cipher
from cyclades_data import apply_report, parse_report
from cyclades_slips import read_slips, slip_key
from test_admissions_2027 import application, auth, client, seed
from test_cyclades import export, student

LOGIN = "camille.test01"
REF = ("1234", "1", LOGIN)
SAMPLE = ("0001234", "001", LOGIN, "Demo<&:0.9")
OTHER = ("0009999", "001", "autre.test", "Unrelated!Value")


def document(*slips):
    data = io.BytesIO()
    doc = Canvas(data)
    doc.drawString(20, 800, "Accès au service en ligne des examens")
    for i, (candidate, registration, login, password) in enumerate(slips):
        y = 700 - i * 140
        doc.drawString(20, y, f"N° candidat : {candidate} - Inscription n° : {registration}")
        doc.drawString(20, y-30, "Votre identifiant de connexion : " + login)
        doc.drawString(20, y-60, "Votre mot de passe (*) : " + password)
    doc.save()
    return data.getvalue()


def test_pdf_matching_uses_the_entire_registration_and_rejects_conflicting_slips():
    assert read_slips(document(OTHER, SAMPLE), {REF}) == {REF: SAMPLE[-1]}
    assert not read_slips(document(SAMPLE, (*SAMPLE[:-1], "Different")), {REF})
    for changed in (("999", *SAMPLE[1:]), (SAMPLE[0], "002", *SAMPLE[2:]), (*SAMPLE[:2], "other", SAMPLE[3])):
        assert not read_slips(document(changed), {REF})


def test_only_an_admin_can_reveal_a_matched_slip_after_import(student):
    auth(student)
    record_url = "/admin/candidat/student/cyclades"
    url = record_url + "/paris/2027/acces"
    with application.db() as conn:
        apply_report(conn, "paris", parse_report(export(), "paris"), "auto")
    student.get("/admin/candidat/student")
    with student.session_transaction() as state:
        token = state["_planning_csrf"]
    data = dict(candidate=SAMPLE[0], registration=SAMPLE[1], csrf_token=token)
    assert student.post(url, data=dict(data, csrf_token="wrong")).status_code == 403
    assert application.app.test_client().post(url, data=data).status_code == 403
    assert student.post(url, data=dict(data, action="import", slip=(io.BytesIO(document(OTHER)), "test.pdf"))).status_code == 303
    response = student.post(url, data=dict(data, action="import", slip=(io.BytesIO(document(OTHER, SAMPLE)), "test.pdf")))
    assert response.status_code == 200 and "no-store" in response.headers["Cache-Control"]
    assert "Demo&lt;&amp;:0.9" in response.text and OTHER[3] not in response.text
    with application.db() as conn:
        serialized = conn.execute("SELECT records FROM cyclades_students WHERE candidate_id='student'").fetchone()[0]
        assert SAMPLE[3] not in serialized and OTHER[3] not in serialized
        sealed = json.loads(serialized)[0]["sealed_slip"]
        apply_report(conn,"paris",parse_report(export(issued="04/11/2026 08:10"),"paris"),"auto")
    assert "Demo&lt;&amp;:0.9" in student.post(url, data=data).text
    fragment = student.get(record_url).text
    assert "Afficher l’identifiant et le mot de passe provisoire" in fragment
    assert SAMPLE[3] not in fragment and "Demo&lt;&amp;:0.9" not in fragment and sealed not in fragment
    assert student.post(url, data=dict(data, registration="002")).status_code == 404
    with application.db() as conn:
        apply_report(conn,"paris",parse_report(export(issued="05/11/2026 08:10").replace(LOGIN.encode(), b"changed.login"),"paris"),"auto")
    assert student.post(url, data=data).status_code == 303
    with application.db() as conn:
        apply_report(conn,"paris",parse_report(export(issued="06/11/2026 08:10", empty=True),"paris"),"auto")
    assert student.post(url, data=data).status_code == 404


@pytest.mark.parametrize("archived", [False, True])
def test_existing_official_report_is_downloaded_without_creating_accounts(student, archived):
    from cyclades_slip_portal import read_account_slips
    binary = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
    if not binary:
        pytest.skip("Requires test Chromium")
    session = "BTS - 2027 - ACADEMIE DE PARIS"
    origin = "https://cyclades.education.gouv.fr"
    record = parse_report(export(), "paris").records[0][-1]
    assert slip_key(record) == REF
    landing = '<h1>BTS 0756548K</h1><div hidden><span onclick="location.href=\'/accounts\'">Générer les comptes Cyclades de mes élèves</span></div>'
    accounts = '<select id="selectContexte"><option>Choisir</option><option>BTS – JUIN 2027 – Académie de Paris</option></select><a href="/confirmed">Valider</a>'
    confirmed = f'<h2>{session}</h2><button onclick="location.href=\'/forbidden\'">Générer</button><a href="/results">Afficher le compte rendu</a>'
    results = '<a href="/file">papillonsInformationsConnexionCyclades</a>'
    existing = confirmed
    if archived:
        nav = '<a href="/existing">Regénérer le mot de passe d’un compte d’un élève</a>'
        landing += nav
        confirmed = f'<h2>{session}</h2><p>Tous vos élèves possèdent un compte Cyclades.</p>{nav}'
        results = '<a href="/file">Papillon de connexion</a>'
    requests = []
    with sync_playwright() as pw, pw.chromium.launch(executable_path=binary) as browser:
        with browser.new_context(accept_downloads=True) as ctx:
            def serve(route):
                path = route.request.url.removeprefix(origin)
                requests.append(path)
                if path == "/file":
                    return route.fulfill(content_type="application/pdf", body=document(OTHER, SAMPLE),
                                         headers={"Content-Disposition": "attachment; filename=papillons.pdf"})
                route.fulfill(content_type="text/html; charset=utf-8", body={"/cycetablissement/": landing, "/accounts":accounts, "/confirmed":confirmed, "/existing":existing, "/results":results}.get(path, ""))
            ctx.route("**/*", serve)
            page = ctx.new_page()
            page.goto(origin+"/cycetablissement/")
            read_account_slips(page, "paris", session, [record], cipher(application.app))
    if archived:
        assert "/existing" in requests
    assert "/forbidden" not in requests
    assert cipher(application.app).decrypt(record["sealed_slip"].encode()).decode() == SAMPLE[-1]


def test_shell_selects_session_again_after_the_account_page_opens():
    from cyclades_slip_portal import select_account_context
    binary = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
    if not binary:
        pytest.skip("Requires test Chromium")
    session = "BTS - 2027 - ACADEMIE DE PARIS"
    html = f'<span><select id="selectContexte"><option value="">Choisir</option><option value="2027">{session}</option></select></span>'
    with sync_playwright() as pw, pw.chromium.launch(executable_path=binary) as browser:
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8",body=html))
        attempted, observed = {}, set()
        for path in ("lister_candidature", "creation_compte_candidat"):
            page.goto("https://cyclades.education.gouv.fr/cycetablissement/portal/"+path)
            assert page.locator("select").input_value() == ""
            assert select_account_context(page.main_frame, session, "paris", attempted, observed)
            assert page.locator("select").input_value() == "2027"


@pytest.mark.parametrize("ajax", [False, True])
def test_validated_portlet_can_reset_the_context_switch_without_reloading(student, ajax):
    from cyclades_slip_portal import read_account_slips
    binary = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
    if not binary:
        pytest.skip("Requires test Chromium")
    origin = "https://cyclades.education.gouv.fr"
    route = "/cycetablissement/portal/creation_compte_candidat"
    session = "BTS - 2027 - ACADEMIE DE PARIS"
    validated = route + "/validerContexte/true"
    switch = f"""<span><select id="selectContexte" onchange="location.href='{validated}'">
        <option value="">Session</option><option value="26">BTS 2026 PARIS</option><option value="27">{session}</option>
        </select></span>"""
    pages = {
        "/cycetablissement/":f'<a href="{route}">Générer les comptes Cyclades de mes élèves</a>',
        route:switch,
        validated:switch+'''<button id="summary" hidden onclick="location.href='/edition'">Afficher le compte rendu</button>
            <script>setTimeout(()=>document.querySelector('#summary').hidden=false,350)</script>''',
        "/edition":'<a href="/fichier">Papillon de connexion</a>',
    }
    if ajax:
        pages[route] = f"""<span><select id="selectContexte" onchange="fetch('{validated}')">
            <option value="">Choisir</option><option value="27">{session}</option></select></span>"""
        pages[validated] = '<a href="/edition">Afficher le compte rendu</a>'
    calls = []
    record = parse_report(export(), "paris").records[0][-1]
    with sync_playwright() as pw, pw.chromium.launch(executable_path=binary) as browser:
        with browser.new_context(accept_downloads=True) as ctx:
            def serve(req):
                path = req.request.url.removeprefix(origin)
                calls.append(path)
                if path == "/fichier":
                    return req.fulfill(content_type="application/pdf",body=document(SAMPLE),
                                       headers={"Content-Disposition":"attachment; filename=papillons.pdf"})
                req.fulfill(content_type="text/html; charset=utf-8",body=pages.get(path,""))
            ctx.route("**/*",serve)
            page = ctx.new_page()
            page.goto(origin+"/cycetablissement/")
            assert read_account_slips(page,"paris",session,[record],cipher(application.app))
    assert calls[:calls.index("/edition")].count(validated) == 1, calls
    assert record["slip_sync"] == "found"


def test_context_validation_keeps_the_tab_issued_by_the_portal(student):
    from urllib.parse import urlsplit, parse_qs
    from cyclades_slip_portal import read_account_slips, tabbed_activity_url
    binary = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
    if not binary:
        pytest.skip("Requires test Chromium")
    origin = "https://cyclades.education.gouv.fr"
    route = "/cycetablissement/portal/creation_compte_candidat"
    session_label = "BTS - 2027 - ACADEMIE DE PARIS"
    tab = "1234567890"
    assert tabbed_activity_url("https://unrelated.example/"+route, {route:tab}) == "https://unrelated.example/"+route
    switch = f"""<span><select id="selectContexte"
        onchange="fetch('{route}',{{method:'POST',body:new URLSearchParams({{OngletID:'{tab}',cleSelected:this.value,choixContexte:'true'}})}}).then(()=>location.assign('{route}'))">
        <option value="">Choisir</option><option value="tab-session">{session_label}</option></select></span>"""
    views = []
    record = parse_report(export(), "paris").records[0][-1]
    with sync_playwright() as pw, pw.chromium.launch(executable_path=binary) as browser:
        with browser.new_context(accept_downloads=True) as ctx:
            def serve(request):
                u = urlsplit(request.request.url)
                views.append((u.path,parse_qs(u.query).get("OngletID")))
                if u.path == route and request.request.method == "POST":
                    return request.fulfill(status=200,content_type="application/json",body="{}")
                if u.path.startswith(route):
                    page_html = (f'<h2>{session_label}</h2><a href="/edition">Afficher le compte rendu</a>'
                                 if parse_qs(u.query).get("OngletID") == [tab] else switch)
                elif u.path == "/edition":
                    page_html = '<a href="/file">Papillon de connexion</a>'
                elif u.path == "/file":
                    return request.fulfill(body=document(SAMPLE),content_type="application/pdf",
                                           headers={"Content-Disposition":"attachment; filename=papillons.pdf"})
                else:
                    page_html = f'<a href="{route}">Générer les comptes Cyclades de mes élèves</a>'
                request.fulfill(content_type="text/html; charset=utf-8",body=page_html)
            ctx.route("**/*",serve)
            page = ctx.new_page()
            page.goto(origin+"/cycetablissement/")
            assert read_account_slips(page,"paris",session_label,[record],cipher(application.app))
    assert any(path.startswith(route) and value==[tab] for path,value in views)
    assert record["slip_sync"] == "found"
