"""Gateway isolation: no remote orders, mail or payments during these tests."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests
from bs4 import BeautifulSoup
from urllib3._collections import HTTPHeaderDict
from test_admissions_2027 import application, client
import vtc_gateway as gateway

KEY = "a" * 32 + "." + "b" * 43
PATH = "/vtc/commande/vehicule"
BASE = "https://localhost"

def upstream(body=b"ok", status=200, content_type="text/html; charset=utf-8", **headers):
    raw_headers = HTTPHeaderDict()
    raw_headers.add("Set-Cookie", "integrale_admin=signed-vtc-state; HttpOnly; Path=/; Secure; SameSite=Lax")
    return SimpleNamespace(content=body, status_code=status, headers={"Content-Type": content_type, **headers},
                           raw=SimpleNamespace(headers=raw_headers), close=Mock())

def test_shared_header_and_separate_session_survive_post(client, monkeypatch):
    html = b'<html><head></head><body><header class="top">Old</header><form method="post"><input name="csrf_token" value="original"><input name="draft" value="id"></form><img src="/static/vtc/vehicle.webp"><a href="/confidentialite">Privacy</a></body></html>'
    remote = Mock(return_value=upstream(html))
    monkeypatch.setattr(gateway.requests, "request", remote)
    with client.session_transaction() as session:
        session["gateway_isolation_marker"] = "admissions-private"
    client.set_cookie("integrale_admin", "gestion-admin-secret")
    form = client.get(PATH, base_url=BASE)
    soup = BeautifulSoup(form.data, "html.parser")
    header = BeautifulSoup(client.get("/vtc", base_url=BASE).data, "html.parser").select_one("#academy-header")
    assert soup.select_one("#academy-header") == header
    assert soup.select_one('[name="csrf_token"]')["value"] == "original"
    assert soup.select_one("img[src='/vtc/assets/vtc/vehicle.webp']")
    assert soup.select_one("a[href='https://www.integraleconnect.com/confidentialite']")
    assert remote.call_args.kwargs["cookies"] == {}
    cookie = form.headers["Set-Cookie"]
    assert cookie.startswith("vtc_checkout_session=") and "Path=/vtc" in cookie
    assert all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=Lax"))
    remote.return_value = upstream(status=303, Location=gateway.UPSTREAM+PATH+"/confirmation")
    result = client.post(PATH, data={"csrf_token":"original", "draft":"id"}, base_url=BASE,
                         headers={"Origin":BASE, "Authorization":"Bearer private"})
    options = remote.call_args.kwargs
    assert options["cookies"] == {"integrale_admin":"signed-vtc-state"}
    assert options["data"] == b"csrf_token=original&draft=id"
    assert "Authorization" not in options["headers"] and "Cookie" not in options["headers"]
    assert options["headers"]["X-Requested-With"] == "VTC-Gateway"
    assert options["allow_redirects"] is False
    assert result.status_code == 303 and result.location == PATH+"/confirmation"
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["Referrer-Policy"] == "no-referrer"
    with client.session_transaction() as session:
        assert session["gateway_isolation_marker"] == "admissions-private"

def test_provider_redirect_json_and_pdf_are_preserved(client, monkeypatch):
    remote = Mock(return_value=upstream(status=303, Location="https://pay.qonto.com/invoice/example"))
    monkeypatch.setattr(gateway.requests, "request", remote)
    path = "/vtc/suivi/" + KEY
    result = client.get(path+"/payer", base_url=BASE)
    assert result.location == "https://pay.qonto.com/invoice/example"
    assert remote.call_count == 1
    remote.return_value = upstream(b'{"state":"ready"}', content_type="application/json")
    assert client.get(path+"/etat-paiement", base_url=BASE).json == {"state":"ready"}
    pdf = b"%PDF-1.4\x00\xffbinary"
    remote.return_value = upstream(pdf, content_type="application/pdf", **{"Content-Disposition":'attachment; filename="invoice.pdf"'})
    result = client.get(path+"/invoice.pdf", base_url=BASE)
    assert result.data == pdf and result.mimetype == "application/pdf"
    assert result.headers["Content-Disposition"].endswith('"invoice.pdf"')

@pytest.mark.parametrize("path", ["/vtc/commande/admin", "/vtc/suivi/invalid", "/vtc/suivi/"+KEY+"/admin", "/vtc/assets/../app.py", "/vtc/assets/uploads/private.pdf"])
def test_gateway_cannot_access_other_backend_routes(client, monkeypatch, path):
    remote = Mock()
    monkeypatch.setattr(gateway.requests, "request", remote)
    assert client.get(path, base_url=BASE).status_code == 404
    remote.assert_not_called()

def test_cross_origin_and_oversized_submissions_are_rejected(client, monkeypatch):
    remote = Mock()
    monkeypatch.setattr(gateway.requests, "request", remote)
    assert client.post(PATH, data={"x":"y"}, base_url=BASE, headers={"Origin":"https://other.test"}).status_code == 403
    assert client.post(PATH, data={"x":"y"*65537}, base_url=BASE).status_code == 413
    assert client.post(PATH, json={"x":"y"}, base_url=BASE).status_code == 415
    remote.assert_not_called()

@pytest.mark.parametrize("path", [PATH, "/vtc/commande/formation", "/vtc/commande/cpf", "/vtc/suivi/"+KEY])
def test_native_private_form_reaches_backend_validation(client, monkeypatch, path):
    remote = Mock(return_value=upstream(status=400))
    monkeypatch.setattr(gateway.requests, "request", remote)
    client.set_cookie(gateway.COOKIE, "signed-vtc-state", path="/vtc")
    result = client.post(path, data={"csrf_token":"original", "draft":"id"}, base_url=BASE,
                         headers={"Origin":"null", "Sec-Fetch-Site":"same-origin", "Sec-Fetch-Mode":"navigate"})
    assert result.status_code == 400  # The backend's validation still decides the outcome.
    assert remote.call_args.kwargs["cookies"] == {"integrale_admin":"signed-vtc-state"}
    assert remote.call_args.kwargs["data"] == b"csrf_token=original&draft=id"
    assert result.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("origin,site,mode", [
    ("null", "cross-site", "navigate"), ("null", "same-site", "navigate"),
    ("null", None, "navigate"), ("null", "same-origin", "cors"),
    ("https://other.test", "same-origin", "navigate"),
])
def test_untrusted_form_is_rejected_before_forwarding(client, monkeypatch, origin, site, mode):
    remote = Mock()
    monkeypatch.setattr(gateway.requests, "request", remote)
    headers = {"Origin":origin, "Sec-Fetch-Mode":mode}
    if site is not None:
        headers["Sec-Fetch-Site"] = site
    assert client.post(PATH, data={"draft":"id"}, base_url=BASE, headers=headers).status_code == 403
    remote.assert_not_called()


def test_timeout_is_private_and_does_not_retry_post(client, monkeypatch):
    remote = Mock(side_effect=requests.Timeout("secret-dossier-token"))
    monkeypatch.setattr(gateway.requests, "request", remote)
    response = client.post(PATH, data={"csrf_token":"original"}, base_url=BASE)
    assert response.status_code == 503
    assert b"secret-dossier-token" not in response.data
    assert b"academy-header" in response.data
    assert remote.call_count == 1

def test_all_three_offers_link_to_same_origin(client):
    soup = BeautifulSoup(client.get("/vtc").data, "html.parser")
    assert {a['href'] for a in soup.select('a[href*="/vtc/commande/"]')} == {"/vtc/commande/"+offer for offer in ("vehicule", "formation", "cpf")}
