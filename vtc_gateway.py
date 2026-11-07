"""Serve only the public VTC journey on Admissions; management stays in Gestion."""
import re
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

import requests
from flask import Blueprint, Response, abort, render_template, request

bp = Blueprint("vtc_gateway", __name__)
UPSTREAM = "https://gestionstagiaires-r5no.onrender.com"
PUBLIC = "https://admissions.integraleconnect.com"
COOKIE = "vtc_checkout_session"
UPSTREAM_COOKIE = "integrale_admin"
ASSETS = {"css/vtc-orders.css", "js/vtc-payment.js", "vtc/vehicle.webp", "parcours-alternance/logo.png"}
KEY = re.compile(r"[a-f0-9]{32}\.[A-Za-z0-9_-]{43}\Z")


def forward(path):
    if request.method == "POST":
        # Backend still checks its signed session, CSRF token and submission ID.
        origin = request.headers.get("Origin")
        # no-referrer makes native form navigations send Origin: null.
        # Only trust that opaque value when the browser confirms a local navigation.
        same_origin_form = (
            origin == "null"
            and request.headers.get("Sec-Fetch-Site") == "same-origin"
            and request.headers.get("Sec-Fetch-Mode") == "navigate"
        )
        if origin and origin != "https://" + request.host and not same_origin_form:
            abort(403)
        if request.mimetype != "application/x-www-form-urlencoded":
            abort(415)
        if request.content_length and request.content_length > 65536:
            abort(413)
    data = request.stream.read(65537) if request.method == "POST" else None
    if data and len(data) > 65536:
        abort(413)
    # This is a server gateway, not a browser on the management origin.
    # Keep origin-specific browser integrations (e.g. service workers) upstream.
    headers = {"X-VTC-Gateway": "admissions", "X-Requested-With": "VTC-Gateway",
               "Accept": request.headers.get("Accept", "*/*")}
    if request.method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    # Never pass either application's login cookie, Authorization or proxy headers.
    cookies = {UPSTREAM_COOKIE: request.cookies[COOKIE]} if request.cookies.get(COOKIE) else {}
    try:
        upstream = requests.request(
            request.method, UPSTREAM + path, params=request.args,
            data=data,
            headers=headers, cookies=cookies, allow_redirects=False, timeout=(5, 35),
        )
    except requests.RequestException:
        # Do not log URLs: dossier links contain private access tokens.
        return Response(render_template("vtc_gateway_unavailable.html"), status=503,
                        content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})
    try:
        body = upstream.content
        content_type = upstream.headers.get("Content-Type", "application/octet-stream")
        if "text/html" in content_type:
            html = body.decode("utf-8")
            # Rewrite controlled backend asset paths before injecting Admissions' header.
            for asset in ASSETS:
                html = html.replace('/static/' + asset, '/vtc/assets/' + asset)
            html = re.sub(r'<header class="top">.*?</header>',
                          lambda _: render_template("vtc_gateway_header.html"), html, count=1, flags=re.S)
            html = html.replace('</head>', '<link rel="stylesheet" href="/static/css/academy-header.css?v=1"></head>', 1)
            html = html.replace('</body>', '<script src="/static/js/academy-header.js?v=2" defer></script></body>', 1)
            html = html.replace('href="/confidentialite"', 'href="https://www.integraleconnect.com/confidentialite"')
            body = html.encode("utf-8")
        response = Response(body, status=upstream.status_code, content_type=content_type)
        for name in ("Content-Disposition", "Retry-After"):
            if name in upstream.headers:
                response.headers[name] = upstream.headers[name]
        location = upstream.headers.get("Location")
        if location:
            # Relative VTC redirects stay local; provider redirects remain external.
            if location.startswith(UPSTREAM + "/vtc/") or location.startswith(PUBLIC + "/vtc/"):
                parsed = urlsplit(location)
                location = parsed.path + ("?" + parsed.query if parsed.query else "")
            response.headers["Location"] = location
        for raw in upstream.raw.headers.getlist("Set-Cookie"):
            jar = SimpleCookie()
            jar.load(raw)
            if UPSTREAM_COOKIE in jar:
                cookie = jar[UPSTREAM_COOKIE]
                response.set_cookie(COOKIE, cookie.value, path="/vtc", secure=True,
                                    httponly=True, samesite="Lax",
                                    max_age=int(cookie["max-age"]) if cookie["max-age"] else None,
                                    expires=cookie["expires"] or None)
        return response
    finally:
        upstream.close()


@bp.after_request
def private_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/vtc/commande/<offer>", methods=["GET", "POST"])
@bp.get("/vtc/commande/<offer>/confirmation")
def checkout(offer):
    if offer not in {"vehicule", "formation", "cpf"}:
        abort(404)
    return forward(request.path)


@bp.route("/vtc/suivi/<key>", methods=["GET", "POST"])
@bp.get("/vtc/suivi/<key>/<action>")
def dossier(key, action=None):
    if not KEY.fullmatch(key) or action not in {None, "payer", "etat-paiement", "vehicle.pdf",
                                              "invoice.pdf", "convention.pdf", "signed.pdf", "completion.pdf"}:
        abort(404)
    return forward(request.path)


@bp.get("/vtc/assets/<path:asset>")
def asset(asset):
    if asset not in ASSETS:
        abort(404)
    return forward("/static/" + asset)
