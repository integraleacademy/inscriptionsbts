from cyclades_pieces import parse_detail


def test_detail_read_only_observation_identified_and_complete():
    record = {"details": {"N° de candidat": "123456789", "N° d’inscription": "001", "Version": "3"}}
    screen = """N° candidat : 0123456789   N° inscription : 001 Version : 3
    Code Etab : 1234567A
    Pièces justificatives conformes : 0 / 2
    A déposer en ligne entre le vendredi 09 octobre 2026 15:00 et le jeudi 12 novembre 2026 23:59 (heure/Paris)
    CINSIG03 : Confirmation d’inscription signée
    Aucun fichier par le candidat
    Aucun fichier par le gestionnaire
    PJ-CONTROLE En attente de contrôle
    IDENT01 : Document justifiant l’identité
    Déposé le 01/11/2026 10:45 (heure/Paris) par le candidat
    Aucun fichier par le gestionnaire
    PJ-CONTROLE Non conforme
    """
    result = parse_detail(screen, record, "1234567A")
    assert result["requested"] == 2 and result["conforming"] == 0
    first, second = result["documents"]
    assert first["review"] == "En attente de contrôle" and first["deposit"] == first["manager"] == "Non déposée"
    assert first["deadline"] == "12/11/2026 à 23h59"
    assert second["deposit"] == "Déposée" and second["review"] == "Non conforme"
    assert parse_detail(screen.replace("0 / 2", "0 / 4"), record, "1234567A") is None
    assert parse_detail(screen.replace("001 Version", "002 Version"), record, "1234567A") is None
    assert parse_detail(screen, record, "0234567A") is None


def test_activity_reads_each_matched_registration_in_both_academies(monkeypatch):
    import os
    import pytest
    from playwright.sync_api import sync_playwright
    from cyclades_data import ACADEMIES, Report
    from cyclades_portal import read_pieces

    executable = os.getenv("CYCLADES_CHROMIUM_EXECUTABLE")
    if not executable:
        pytest.skip("Requires the test Chromium executable")
    root = "https://cyclades.education.gouv.fr/cycetablissement/"
    with sync_playwright() as driver, driver.chromium.launch(executable_path=executable) as browser:
        for key in ACADEMIES:
            academy, uai, *_ = ACADEMIES[key]
            label = f"BTS - 2027 - ACADÉMIE DE {academy.upper()}"
            numbers = ["123456789", "234567890"]
            records = [{"details": {"N° de candidat": n, "N° d’inscription": "001", "Version": "3"}} for n in numbers]
            def serve(route):
                path = route.request.url
                if path.endswith("accueil"):
                    body = '<a id="ETABLISSEMENT_INSCRIPTION">Inscription</a><a href="suivre_retours_pj/list">Suivre les retours de pièces justificatives</a>'
                elif path.endswith("/list"):
                    rows = "".join(f'<tr><td><a href="{n}">{n}</a></td></tr>' for n in numbers)
                    if key == "paris":
                        rows = "".join(f'<tr><td ondblclick="location.href=this.innerText">{n}</td></tr>' for n in numbers)
                    body = f'<select id="selectContexte"><option>{label}</option></select><table>{rows}</table>'
                else:
                    n = path.rsplit("/", 1)[-1]
                    body = f"""<p>N° candidat : {n} N° inscription : 001 Version : 3</p><p>Code Etab : {uai}</p>
                    <p>Pièces justificatives conformes : 0 / 1</p><div>CINSIG03 : Confirmation signée</div>
                    <div>Aucun fichier par le candidat</div><div>Aucun fichier par le gestionnaire</div>
                    <select><option>En attente de contrôle</option><option>Conforme</option></select>
                    <div style="display:none">IDENT01 : Identité ancienne
                    <select><option>Conforme</option></select></div>"""
                route.fulfill(content_type="text/html; charset=utf-8", body=body)
            with browser.new_context() as context:
                context.route("**/*", serve)
                page = context.new_page()
                page.goto(root + "accueil")
                read_pieces(page, key, label, Report(2027, 0, [], True), records)
                for record in records:
                    assert record["documents"][0]["review"] == "En attente de contrôle"
                    assert record["documents"][0]["deposit"] == "Non déposée"


def test_summary_can_be_verified_without_treating_incomplete_rows_as_a_full_read():
    from cyclades_pieces import verified_counts
    rec = {"details": {"N° de candidat": "12", "N° d’inscription": "001", "Version": "2"}}
    screen = ("N° candidat : 00012N° inscription : 001 Version : 2\nCode Etab : 1234567A\n"
              "Pièces justificatives conformes : 1 / 3\nCODE1 : Confirmation signée\nPJ-CONTROLE Conforme")
    assert verified_counts(screen, rec, "1234567A") == {"conforming": 1, "requested": 3}
    assert parse_detail(screen, rec, "1234567A") is None
    assert verified_counts(screen, rec, "1234567B") is None
    assert verified_counts(screen.replace("Version : 2", "Version : 3"), rec, "1234567A") is None


def test_partial_observation_keeps_explicit_rows_without_claiming_a_complete_read():
    record = {"details": {"N° de candidat": "12", "N° d’inscription": "1", "Version": "3"}}
    screen = ("N° candidat : 12 N° inscription : 1 Version : 3\nCode Etab : 1234567A\n"
              "Pièces justificatives conformes : 0 / 3\nNATIDE06 : Identité\n"
              "Aucun fichier par le candidat\nPJ-CONTROLE En attente de contrôle\n"
              "PJ-CFA : Attestation\nPJ-CONTROLE Non conforme")
    assert parse_detail(screen, record, "1234567A") is None
    read = parse_detail(screen, record, "1234567A", allow_partial=True)
    assert [doc["review"] for doc in read["documents"]] == ["En attente de contrôle", "Non conforme"]
    assert read["documents"][1]["deposit"] is None and read["requested"] == 3


def test_file_evidence_belongs_to_the_uploader_in_the_same_row():
    record = {"details": {"N° de candidat": "12", "N° d’inscription": "1", "Version": "3"}}
    screen = ("N° candidat : 12 N° inscription : 1 Version : 3\nCode Etab : 1234567A\n"
              "Pièces justificatives conformes : 0 / 2\nNATIDE06 : Identité\n"
              "scan.pdf\npar le candidat\nAucun fichier par le gestionnaire\n"
              "PJ-CONTROLE En attente de contrôle\nCINSIG03 : Confirmation\n"
              "Aucun fichier par le candidat\nPJ-FICHIER par le gestionnaire\nPJ-CONTROLE Conforme")
    a, b = parse_detail(screen, record, "1234567A")["documents"]
    assert (a["deposit"], a["manager"]) == ("Déposée", "Non déposée")
    assert (b["deposit"], b["manager"]) == ("Non déposée", "Déposée")
    assert "scan.pdf" not in str(a)
