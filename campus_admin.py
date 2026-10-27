"""Enrollment directory, contextual student records and administration search."""
from contextlib import closing
from datetime import datetime, timezone
import json
import secrets
import unicodedata
from zoneinfo import ZoneInfo

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from candidate_messages import _equal
from promotions import assign_candidate_promotion, list_promotions
from teaching import schema as teaching_schema

ENROLLED = ('confirmee', 'reconfirmee')


def key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold()) if not unicodedata.combining(c))


def csrf():
    if not session.get('_campus_csrf'):
        session['_campus_csrf'] = secrets.token_urlsafe(32)
    return session['_campus_csrf']


def enrolled_rows(conn):
    rows = [dict(r) for r in conn.execute('''SELECT c.id,c.nom,c.prenom,c.bts,c.mode,c.email,c.tel,c.statut,
        c.rentree_annee,c.numero_dossier,c.label_carte_etudiante,p.id AS promotion_id,p.nom AS promotion_name,p.active AS promotion_active
        FROM candidats c LEFT JOIN student_promotions s ON s.candidate_id=c.id
        LEFT JOIN promotions p ON p.id=s.promotion_id WHERE c.statut IN (?,?) ORDER BY c.nom,c.prenom''', ENROLLED)]
    contracts = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='student_wedof_contracts'").fetchone():
        for r in conn.execute('SELECT candidate_id,payload,checked_at FROM student_wedof_contracts ORDER BY checked_at'):
            try:
                data = json.loads(r['payload'])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                contracts.setdefault(r['candidate_id'], []).append(data)
    today = datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    for row in rows:
        linked = contracts.get(row['id'], [])
        current = [c for c in linked if c.get('state') == 'accepted'
                   and (not c.get('contract_break_date') or str(c['contract_break_date'])[:10] > today)
                   and (not c.get('contract_end') or str(c['contract_end'])[:10] >= today)]
        row['contract'] = 'yes' if current else 'linked' if linked else 'no'
        row['contract_label'] = {'yes':'Contrat d’apprentissage', 'linked':'Contrat à vérifier', 'no':'Aucun contrat rattaché'}[row['contract']]
    from candidate_statuses import annotate_candidate_statuses
    annotate_candidate_statuses(conn,rows)
    return rows


def sheet_context(conn, cid):
    teaching_schema(conn)
    conn.commit()
    events = [dict(r) for r in conn.execute('SELECT * FROM student_attendance WHERE candidate_id=? AND deleted=0 ORDER BY date DESC,start_min DESC', (cid,))]
    submissions = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='absence_requests'").fetchone():
        submissions = [dict(r) for r in conn.execute('SELECT id,status,submitted_at FROM absence_requests WHERE candidate_id=? ORDER BY submitted_at DESC', (cid,))]
    grades = [dict(r) for r in conn.execute('''SELECT h.id,h.title,h.evaluation_date,h.due_date,h.scale,h.coefficient,h.published,
        g.score,g.status,g.comment,
        (SELECT group_concat(DISTINCT s.name) FROM teaching_homework_groups hg
         JOIN planning_subject_catalog s ON s.id=hg.subject_id WHERE hg.homework_id=h.id) AS subject_name
        FROM teaching_homework h LEFT JOIN teaching_grades g ON g.homework_id=h.id AND g.candidate_id=?
        WHERE g.candidate_id IS NOT NULL OR EXISTS (SELECT 1 FROM teaching_homework_groups hg
            JOIN student_promotions sp ON sp.promotion_id=hg.promotion_id WHERE hg.homework_id=h.id AND sp.candidate_id=?)
        ORDER BY h.evaluation_date DESC,h.created_at DESC''', (cid, cid))]
    assessed = [g for g in grades if g['status']=='graded' and g['score'] is not None and g['scale']>0 and g['coefficient']>0]
    weight = sum(g['coefficient'] for g in assessed)
    average = round(sum(g['score']/g['scale']*20*g['coefficient'] for g in assessed)/weight,2) if weight else None
    trip = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='voyage_londres_inscriptions'").fetchone():
        trip = conn.execute('SELECT * FROM voyage_londres_inscriptions WHERE candidat_id=?', (cid,)).fetchone()
    return dict(attendance_events=events, absence_submissions=submissions, student_grades=grades,
                student_average=average, london_trip=dict(trip) if trip else None,
                absence_minutes=sum(e['end_min']-e['start_min'] for e in events if e['kind']=='absence'),
                lateness_count=sum(e['kind']=='late' for e in events))


FUNCTIONS = [
    ('Candidatures', '/admin', 'Dossiers, admissions, documents'),
    ('Inscriptions', '/admin/inscriptions', 'Étudiants inscrits, contrat, affectation à une promotion'),
    ('Messagerie', '/admin/messagerie', 'Envoyer des mails et SMS aux étudiants, formateurs, entreprises'),
    ('Promotions', '/admin/promotions', 'Classes, groupes et années'),
    ('Plannings', '/admin/planning', 'Cours, Zoom, salles, calendrier'),
    ('Matières', '/admin/matieres', 'Référentiels et programmes'),
    ('Salles', '/admin/salles', 'Salles de cours'),
    ('Formateurs', '/admin/formateurs', 'Enseignants et accès'),
    ('Entreprises', '/admin/entreprises', 'Employeurs et alternants'),
    ('Assiduité', '/admin/assiduite', 'Absences, retards, présence'),
    ('Justificatifs', '/admin/assiduite/justificatifs', 'Demandes à traiter'),
    ('Voyage à Londres', '/admin/voyage-londres', 'Passeport, convention, transport, hébergement'),
    ('Paramètres', '/admin/parametres', 'WEDOF, OpenAI, configuration'),
]


def register_campus_admin(app, db_connect, require_admin):
    def guard(write=False):
        if not require_admin(): abort(403)
        if write and not _equal(request.headers.get('X-CSRF-Token') or request.form.get('csrf_token'), session.get('_campus_csrf')):
            abort(400, 'La page a expiré. Rechargez-la.')

    @app.context_processor
    def campus_context():
        return dict(campus_csrf=csrf)

    @app.get('/admin/inscriptions')
    def admin_enrollments():
        if not require_admin(): return redirect('/login')
        with closing(db_connect()) as conn:
            promotions = list_promotions(conn, active_only=True)
            rows = enrolled_rows(conn)
        total = len(rows)
        filters = {name:request.args.get(name,'').strip() for name in ('q','bts','mode','promotion','contract','rentree','carte_etudiante_manquante')}
        for name, value in filters.items():
            if not value: continue
            if name == 'q': rows = [r for r in rows if all(word in key(' '.join(str(r.get(k) or '') for k in ('nom','prenom','email','numero_dossier'))) for word in key(value).split())]
            elif name == 'promotion': rows = [r for r in rows if (not r['promotion_id'] if value=='none' else r['promotion_id']==value)]
            elif name == 'rentree': rows = [r for r in rows if str(r['rentree_annee'] or 2026)==value]
            elif name == 'carte_etudiante_manquante': rows = [r for r in rows if r['label_carte_etudiante'] not in (1,'1',True,'true','True','on','yes')]
            else: rows = [r for r in rows if r.get(name)==value]
        return render_template('enrollments.html', rows=rows, promotions=promotions, filters=filters, total=total, title='Inscriptions · Intégrale Academy')

    @app.post('/admin/inscriptions/affecter')
    def admin_enrollments_assign():
        guard(True)
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict): abort(400)
        ids, pid = data.get('ids'), data.get('promotion_id')
        if not isinstance(ids,list) or not ids or len(ids)>500 or not all(isinstance(i,str) for i in ids) or not isinstance(pid,str) or not pid:
            return jsonify(ok=False,error='Sélectionnez des étudiants et une promotion.'),400
        try:
            with closing(db_connect()) as conn:
                list_promotions(conn)
                conn.commit()
                conn.execute('BEGIN IMMEDIATE')
                for cid in set(ids):
                    row = conn.execute('SELECT statut FROM candidats WHERE id=?',(cid,)).fetchone()
                    if not row or row['statut'] not in ENROLLED:
                        raise ValueError('Un dossier sélectionné n’est plus une inscription confirmée. Actualisez la page.')
                    assign_candidate_promotion(conn,cid,pid)
                conn.commit()
        except (ValueError,LookupError) as error:
            return jsonify(ok=False,error=str(error)),400
        return jsonify(ok=True,count=len(set(ids)))

    @app.get('/admin/recherche')
    def admin_global_search():
        guard()
        query=key(request.args.get('q','')[:160]).strip()
        results=[]
        if query:
            with closing(db_connect()) as conn:
                for r in conn.execute('SELECT id,nom,prenom,bts,mode,rentree_annee,email,numero_dossier FROM candidats ORDER BY nom,prenom'):
                    if all(w in key(' '.join(str(r[k] or '') for k in ('nom','prenom','bts','email','numero_dossier'))) for w in query.split()):
                        results.append(dict(label=f"{r['prenom']} {r['nom']}", detail=f"BTS {r['bts']} · {r['rentree_annee'] or 2026}", mode=r['mode'], url='/admin/candidat/'+r['id'],kind='Étudiant'))
                        if len(results)>=15: break
        for label,url,detail in FUNCTIONS:
            if not query or all(w in key(label+' '+detail) for w in query.split()):
                results.append(dict(label=label,url=url,detail=detail,kind='Fonction'))
        response=jsonify(results=results)
        response.headers['Cache-Control']='private, no-store'
        return response

    @app.post('/admin/candidat/<cid>/londres')
    def admin_candidate_london(cid):
        guard(True)
        with closing(db_connect()) as conn:
            student=conn.execute('SELECT mode FROM candidats WHERE id=?',(cid,)).fetchone()
            if not student: abort(404)
            if student['mode']!='presentiel': abort(400,'Le voyage est réservé au présentiel.')
            now=datetime.now(timezone.utc).isoformat()
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM voyage_londres_inscriptions WHERE candidat_id=?',(cid,)).fetchone()
            if old and old['updated_at'] != request.form.get('version'):
                abort(409,'Le suivi a changé. Rechargez la fiche.')
            convention=request.form.get('convention','À faire')
            if convention not in ('À faire','Éditée','Signée','Transmise OPCO'): abort(400)
            values=[int(request.form.get(k)=='on') for k in ('opco','billet','hebergement','immigration')]
            if old:
                conn.execute('UPDATE voyage_londres_inscriptions SET convention=?,opco=?,billet=?,hebergement=?,immigration=?,updated_at=? WHERE candidat_id=?',(convention,*values,now,cid))
            else:
                conn.execute('INSERT INTO voyage_londres_inscriptions(id,candidat_id,convention,opco,billet,hebergement,immigration,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(secrets.token_hex(16),cid,convention,*values,now,now))
            conn.commit()
        flash('Suivi du voyage enregistré.','success')
        return redirect('/admin/candidat/'+cid+'#londres',code=303)

    @app.after_request
    def private_campus(response):
        if request.path.startswith(('/admin/inscriptions', '/admin/recherche', '/admin/candidat/')):
            response.headers['Cache-Control'] = 'private, no-store'
        return response
