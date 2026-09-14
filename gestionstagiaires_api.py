"""Narrow server-to-server, read-only access for the BTS administration workspace.

The shared key is dedicated to this integration. Login tokens, public portal
slugs and YPAREO internals are never exposed. Search returns only a shortlist;
the selected candidate is fetched separately.
"""
import hashlib
import hmac
import json
import os
import re
import unicodedata
from functools import wraps
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file


FIELDS = tuple("""id numero_dossier created_at updated_at nom prenom sexe
date_naissance ville_naissance cp_naissance pays_naissance nationalite num_secu
email tel adresse cp ville bts mode bac_status bac_type bac_autre baccalaureat
permis_b est_mineur resp_nom resp_prenom resp_email resp_tel mos_parcours
aps_souhaitee aps_session projet_pourquoi projet_objectif projet_passions
projet_qualites projet_motivation projet_recherche projet_travail statut
label_aps label_aut_ok label_cheque_ok label_carte_etudiante commentaires
date_validee date_confirmee date_reconfirmee entreprise_trouvee
recherches_commencees souhaite_accompagnement""".split())
FILE_FIELDS = {"fichiers_ci": "Pièce d’identité", "fichiers_photo": "Photo",
               "fichiers_carte_vitale": "Carte Vitale", "fichiers_cv": "CV",
               "fichiers_lm": "Lettre de motivation"}
SEARCH_FIELDS = ("id", "numero_dossier", "nom", "prenom", "email", "bts", "mode", "statut")


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or ""))
                   if not unicodedata.combining(c)).casefold()


def documents(row, upload_dir):
    root = Path(upload_dir).resolve()
    candidate_root = (root / row["id"]).resolve()
    if candidate_root.parent != root:
        return []
    found = []
    seen = set()
    for field, label in FILE_FIELDS.items():
        try:
            items = json.loads(row.get(field) or "[]")
        except (ValueError, TypeError):
            items = []
        for raw in items if isinstance(items, list) else []:
            if not isinstance(raw, str):
                continue
            name = Path(raw).name
            path = (candidate_root / name).resolve()
            if path.parent != candidate_root or not path.is_file() or name in seen:
                continue
            seen.add(name)
            found.append({"id": hashlib.sha256(name.encode()).hexdigest(), "name": name,
                          "label": label, "path": path})
    return found


def register_gestionstagiaires_api(app, connect, upload_dir):
    bp = Blueprint("gestionstagiaires_api", __name__, url_prefix="/api/gestionstagiaires")

    def authorized(fn):
        @wraps(fn)
        def checked(*args, **kwargs):
            expected = os.environ.get("BTS_IMPORT_API_KEY", "").strip()
            if len(expected) < 32:
                return jsonify(error="Connexion à Gestion Stagiaires non configurée."), 503
            supplied = request.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + expected):
                abort(401)
            return fn(*args, **kwargs)
        return checked

    def candidate(cid):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cid):
            abort(404)
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM candidats WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
        if not row:
            abort(404)
        return dict(row)

    @bp.post("/candidats/rechercher")
    @authorized
    def search():
        q = str((request.get_json(silent=True) or {}).get("q") or "").strip()
        if not 2 <= len(q) <= 100:
            return jsonify(items=[])
        terms = normalized(q).split()[:8]
        conn = connect()
        try:
            conn.create_function("bts_normalized", 1, normalized)
            haystack = "bts_normalized(COALESCE(nom,'') || ' ' || COALESCE(prenom,'') || ' ' || COALESCE(email,'') || ' ' || COALESCE(numero_dossier,''))"
            query = "SELECT " + ",".join(SEARCH_FIELDS) + " FROM candidats WHERE "
            query += " AND ".join("instr(" + haystack + ", ?) > 0" for _ in terms)
            rows = conn.execute(query + " ORDER BY nom,prenom,id LIMIT 21", terms).fetchall()
        finally:
            conn.close()
        return jsonify(items=[dict(r) for r in rows[:20]], more=len(rows) > 20)

    @bp.get("/candidats/<cid>")
    @authorized
    def detail(cid):
        row = candidate(cid)
        result = {key: row.get(key) for key in FIELDS if key in row}
        result["documents"] = [{k: v for k, v in d.items() if k != "path"}
                               for d in documents(row, upload_dir)]
        return jsonify(candidate=result)

    @bp.get("/candidats/<cid>/documents/<document_id>")
    @authorized
    def download(cid, document_id):
        doc = next((d for d in documents(candidate(cid), upload_dir) if d["id"] == document_id), None)
        if not doc:
            abort(404)
        return send_file(doc["path"], as_attachment=True, download_name=doc["name"],
                         conditional=False, max_age=0)

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    app.register_blueprint(bp)
