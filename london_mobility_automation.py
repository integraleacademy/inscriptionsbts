"""One explicit click prepares an immutable convention and authorizes its delivery."""
from contextlib import closing
import json
import secrets
import threading

from flask import abort, jsonify, request, session, url_for
from london_mobility_data import automatic_data
from london_mobility_signatures import ACTIVE, SignatureError, public_state, now


def register_automation(app, connect, guard, store_file, log_event):
    service = app.extensions['london_signatures']

    def result(state=None):
        response = jsonify(ok=True, signature=public_state(state) if state else None)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def latest(conn, cid):
        record = conn.execute('SELECT payload FROM london_mobility_signatures WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1',(cid,)).fetchone()
        return json.loads(record[0]) if record else None

    def run(cid, vid, aid):
        with app.app_context():
            try:
                with service.lock(cid):
                    state = service.load(cid, vid, aid)
                    try:
                        if state.get('pending'): service.refresh(state)
                        if state['status'] in {'preparing','draft'} and not state.get('pending'):
                            service.send(state)
                    except SignatureError as error:
                        service.record_error(state, error)
                    except Exception:
                        service.record_error(state, SignatureError('La transmission a été interrompue. Actualisez le suivi pour reprendre sans doublon.'))
                        app.logger.warning('London automatic delivery interrupted; request checkpoint retained')
            except SignatureError:
                pass  # Another worker owns the same candidate.

    app.extensions['london_automatic_run'] = run

    @app.get('/admin/candidat/<cid>/londres/signature-status')
    def london_automatic_status(cid):
        guard()
        with closing(connect()) as conn:
            if not conn.execute('SELECT id FROM candidats WHERE id=?',(cid,)).fetchone(): abort(404)
            return result(latest(conn, cid))

    @app.post('/admin/candidat/<cid>/londres/preparer-et-envoyer')
    def london_automatic_send(cid):
        guard(True)
        from london_mobility import schema, encoded, digest, pdf_document, word_document
        paths = []
        try:
            with service.lock(cid):
                service.api()  # Fail before generation when the connection is absent.
                with closing(connect()) as conn:
                    schema(conn); conn.commit(); conn.execute('BEGIN IMMEDIATE')
                    row = conn.execute('SELECT * FROM candidats WHERE id=?',(cid,)).fetchone()
                    if not row: abort(404)
                    if row['mode'] != 'presentiel': raise SignatureError('Le séjour est réservé au présentiel.')
                    existing = latest(conn, cid)
                    if existing and existing['status'] in ACTIVE | {'completed'}:
                        return result(existing)  # Double click, page retry or already signed: no second invitation.
                    resolved = automatic_data(conn, row)
                    if not resolved['ready']:
                        return jsonify(ok=False,error='Certaines informations sont à compléter dans les fiches sources.',issues=resolved['issues']),422
                    data, created = resolved['snapshot'], now()
                    trip = conn.execute('SELECT id FROM voyage_londres_inscriptions WHERE candidat_id=?',(cid,)).fetchone()
                    version = conn.execute('SELECT * FROM london_mobility_versions WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1',(cid,)).fetchone()
                    if version and version['signed_id']:
                        raise SignatureError('La convention est déjà signée et conservée dans les documents.')
                    if version and version['fingerprint'] == digest(data):
                        vid = version['id']
                    else:
                        pdf, word = pdf_document(data), word_document(data)
                        iid = trip['id'] if trip else secrets.token_hex(16)
                        if not trip:
                            conn.execute('INSERT INTO voyage_londres_inscriptions(id,candidat_id,created_at,updated_at) VALUES(?,?,?,?)',(iid,cid,created,created))
                        vid = secrets.token_hex(16)
                        label = 'Convention_Londres_' + created[:10]
                        pid, phash = store_file(conn,iid,pdf,'pdf','Convention de mobilité',label,created,paths)
                        wid, whash = store_file(conn,iid,word,'docx','Convention de mobilité',label,created,paths)
                        conn.execute('''INSERT INTO london_mobility_versions(id,candidate_id,snapshot,fingerprint,created_at,pdf_id,docx_id,pdf_hash,docx_hash)
                            VALUES(?,?,?,?,?,?,?,?,?)''',(vid,cid,encoded(data),digest(data),created,pid,wid,phash,whash))
                    conn.execute('''INSERT INTO london_mobility_settings VALUES(?,?,1,?) ON CONFLICT(candidate_id)
                        DO UPDATE SET payload=excluded.payload,revision=revision+1,updated_at=excluded.updated_at''',
                                 (cid,encoded(resolved['values']),created))
                    conn.execute("UPDATE voyage_londres_inscriptions SET convention='Éditée',updated_at=? WHERE candidat_id=?",(created,cid))
                    conn.commit(); paths.clear()
                state = service.begin(cid,vid,{},automatic=True)
            log_event(cid,'Convention Londres préparée pour envoi automatique avec code SMS',{'version_id':vid})
            # Persisted state is the durable queue. Polling recovers an interrupted worker.
            if not app.config.get('LONDON_AUTOMATIC_DEFER', False):
                threading.Thread(target=run,args=(cid,vid,state['id']),name='london-send',daemon=True).start()
            return result(state),202
        except SignatureError as error:
            return jsonify(ok=False,error=str(error)),409
        except (OSError,RuntimeError,ValueError):
            app.logger.warning('London preparation failed before delivery')
            return jsonify(ok=False,error='La préparation a été interrompue. Réessayez ; les conventions déjà enregistrées sont conservées.'),503
        finally:
            for path in paths: path.unlink(missing_ok=True)

    def unread(conn):
        return [dict(r) for r in conn.execute('''SELECT n.version_id,n.candidate_id,n.created_at,c.prenom,c.nom
            FROM london_mobility_notifications n JOIN candidats c ON c.id=n.candidate_id
            WHERE n.read_at IS NULL ORDER BY n.created_at DESC''')]

    @app.context_processor
    def london_notification_context():
        if not session.get('admin_ok'): return {}
        with closing(connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='london_mobility_notifications'").fetchone(): return {'london_notification_count':0}
            count = conn.execute('SELECT count(*) FROM london_mobility_notifications WHERE read_at IS NULL').fetchone()[0]
        return {'london_notification_count':count}

    @app.get('/admin/voyage-londres/notifications')
    def london_notifications():
        guard()
        with closing(connect()) as conn:
            from london_mobility_signatures import signature_schema
            signature_schema(conn); conn.commit()
            rows = unread(conn)
        from person_names import person_name
        for item in rows:
            item['name'] = person_name(item.pop('nom'),item.pop('prenom'))
            item['url'] = url_for('admin_candidate_sheet',cid=item['candidate_id']) + '#londres'
            item['document_url'] = url_for('london_mobility_download',cid=item['candidate_id'],vid=item['version_id'],kind='signed')
        response = jsonify(ok=True,count=len(rows),notifications=rows)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.post('/admin/voyage-londres/notifications/<vid>/lue')
    def london_notification_read(vid):
        guard(True)
        with closing(connect()) as conn:
            conn.execute('UPDATE london_mobility_notifications SET read_at=? WHERE version_id=? AND read_at IS NULL',(now(),vid))
            conn.commit()
        return jsonify(ok=True)
