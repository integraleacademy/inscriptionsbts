"""Non-destructive, dossier-scoped portrait adjustments."""
import hashlib
import io
import json
import math
import os
from contextlib import closing

from flask import abort, jsonify, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError

from candidate_documents import _resolve_document
from candidate_messages import _equal


def _schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS candidate_photo_crops (
        candidate_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, crop TEXT NOT NULL
    )''')
    conn.commit()


def load_photo(row, upload_dir):
    from werkzeug.exceptions import NotFound
    try:
        entries = json.loads(row.get('fichiers_photo') or '[]')
    except (TypeError, ValueError):
        entries = []
    for stored in entries if isinstance(entries, list) else []:
        if not isinstance(stored, str):
            continue
        try:
            path = _resolve_document(row, os.path.basename(stored), upload_dir)
            with open(path, 'rb') as handle:
                content = handle.read(25 * 1024 * 1024 + 1)
            if len(content) > 25 * 1024 * 1024:
                continue
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 40_000_000:
                    continue
                photo = ImageOps.exif_transpose(image).convert('RGB')
            return photo, hashlib.sha256(content).hexdigest()
        except (NotFound, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            continue
    abort(404)


def validate_crop(data, image):
    if not isinstance(data, dict):
        raise ValueError('Cadrage invalide.')
    rotation = data.get('rotation', 0)
    if isinstance(rotation, bool) or rotation not in (0, 90, 180, 270):
        raise ValueError('Rotation invalide.')
    if data.get('version') == 2:
        values = {}
        for key in ('cx', 'cy', 'width', 'height', 'straighten'):
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Cadrage invalide.')
            values[key] = float(value)
        iw, ih = image.size
        w, h = values['width'] * iw, values['height'] * ih
        if not -45 <= values['straighten'] <= 45 or w < 20 or h < 20 or abs(w / h - .8) > .02:
            raise ValueError('Angle ou dimensions du cadrage invalides.')
        angle = math.radians(rotation + values['straighten'])
        half_w = (abs(math.cos(angle)) * w + abs(math.sin(angle)) * h) / 2
        half_h = (abs(math.sin(angle)) * w + abs(math.cos(angle)) * h) / 2
        cx, cy = values['cx'] * iw, values['cy'] * ih
        if cx < half_w - .01 or cx > iw - half_w + .01 or cy < half_h - .01 or cy > ih - half_h + .01:
            raise ValueError('Le cadre doit rester dans la photo.')
        return dict(version=2, rotation=rotation, **values)
    values = []
    for key in ('x', 'y', 'width', 'height'):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Cadrage invalide.')
        values.append(float(value))
    x, y, w, h = values
    iw, ih = image.size if rotation in (0, 180) else image.size[::-1]
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError('Le cadre doit rester dans la photo.')
    if w * iw < 20 or h * ih < 20 or abs((w * iw) / (h * ih) - .8) > .02:
        raise ValueError('Le cadrage doit être un portrait suffisamment grand.')
    return dict(x=x, y=y, width=w, height=h, rotation=rotation)


def render_crop(photo, crop):
    if crop.get('version') != 2:
        photo = photo.rotate(-crop['rotation'], expand=True)
        w, h = photo.size
        return photo.crop((round(crop['x'] * w), round(crop['y'] * h),
                           round((crop['x'] + crop['width']) * w), round((crop['y'] + crop['height']) * h)))
    iw, ih = photo.size
    w, h = crop['width'] * iw, crop['height'] * ih
    out_h = max(20, round(min(600, h)))
    out_w = round(out_h * .8)
    angle = math.radians(crop['rotation'] + crop['straighten'])
    a, b = math.cos(angle) * w / out_w, math.sin(angle) * h / out_h
    d, e = -math.sin(angle) * w / out_w, math.cos(angle) * h / out_h
    c = crop['cx'] * iw - a * out_w / 2 - b * out_h / 2
    f = crop['cy'] * ih - d * out_w / 2 - e * out_h / 2
    return photo.transform((out_w, out_h), Image.Transform.AFFINE, (a,b,c,d,e,f),
                           resample=Image.Resampling.BICUBIC, fillcolor='white')


def load_candidate_portrait(row, upload_dir, db_connect, *, original=False):
    """Share the current, source-checked crop with the sheet and printed cards."""
    if not row:
        abort(404)
    row = dict(row)
    photo, source_hash = load_photo(row, upload_dir)
    with closing(db_connect()) as conn:
        _schema(conn)
        saved = conn.execute('SELECT * FROM candidate_photo_crops WHERE candidate_id=?', (row['id'],)).fetchone()
    crop = None
    if saved and saved['source_hash'] == source_hash:
        try:
            crop = validate_crop(json.loads(saved['crop']), photo)
        except (ValueError, TypeError, KeyError):
            pass
    if crop and not original:
        try:
            photo = render_crop(photo, crop)
        except (ValueError, TypeError, KeyError):
            pass
    return photo, source_hash, crop


def photo_response(row, upload_dir, db_connect, *, original=False):
    photo, source_hash, crop = load_candidate_portrait(row, upload_dir, db_connect, original=original)
    photo.thumbnail((2400, 2400) if original else (600, 600))
    out = io.BytesIO()
    photo.save(out, 'JPEG', quality=92)
    out.seek(0)
    response = send_file(out, mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Photo-Source'] = source_hash
    if original and crop:
        response.headers['X-Photo-Crop'] = json.dumps(crop)
    return response


def register_candidate_photos(app, db_connect, upload_dir, require_admin, log_event):
    @app.post('/admin/candidat/<cid>/photo-crop')
    def admin_candidate_photo_crop(cid):
        if not require_admin():
            abort(403)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not _equal(request.headers.get('X-CSRF-Token'), session.get('_candidate_message_csrf')):
            return jsonify(ok=False, error='La session a expiré. Rechargez la fiche.'), 400
        with closing(db_connect()) as conn:
            _schema(conn)
            row = conn.execute('SELECT * FROM candidats WHERE id=?', (cid,)).fetchone()
            if not row:
                abort(404)
            photo, source_hash = load_photo(dict(row), upload_dir())
            if not _equal(data.get('source_hash'), source_hash):
                return jsonify(ok=False, error='La photo a changé. Rouvrez le recadrage.'), 409
            if data.get('reset') is True:
                conn.execute('DELETE FROM candidate_photo_crops WHERE candidate_id=?', (cid,))
            else:
                try:
                    crop = validate_crop(data, photo)
                except ValueError as exc:
                    return jsonify(ok=False, error=str(exc)), 400
                conn.execute('INSERT OR REPLACE INTO candidate_photo_crops VALUES(?,?,?)', (cid, source_hash, json.dumps(crop)))
            conn.commit()
        log_event(dict(row), 'PHOTO_RECADREE', {'original_retabli': data.get('reset') is True})
        return jsonify(ok=True)
