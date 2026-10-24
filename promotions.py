"""Explicit teaching groups, student placement and bounded legacy migration.

Intake identifies the student's entry cohort. It is independent from the dates
and first/second-year level of a promotion. No academic dates are inferred.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import hmac
import secrets
import sqlite3

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

BTS_LABELS = {
    'MOS': 'BTS Management opérationnel de la sécurité',
    'MCO': 'BTS Management commercial opérationnel',
    'NDRC': 'BTS Négociation et digitalisation de la relation client',
    'PI': 'BTS Professions immobilières',
    'CI': 'BTS Commerce international',
    'CG': 'BTS Comptabilité et gestion',
}
_MIGRATION = 'explicit-promotions-v1'


def ensure_promotion_schema(conn):
    """Atomic, idempotent migration, safe both inside and outside a transaction."""
    conn.execute('SAVEPOINT promotions_schema')
    try:
        for sql in (
            '''CREATE TABLE IF NOT EXISTS promotions (
                id TEXT PRIMARY KEY,nom TEXT NOT NULL,bts TEXT NOT NULL,niveau INTEGER,
                rentree_annee INTEGER NOT NULL,date_debut TEXT,date_fin TEXT,
                active INTEGER NOT NULL DEFAULT 1,needs_setup INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS student_promotions (
                candidate_id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,assigned_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS student_promotion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id TEXT NOT NULL,
                previous_promotion_id TEXT,promotion_id TEXT,changed_at TEXT NOT NULL,reason TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS trainer_promotions (
                trainer_id TEXT NOT NULL,promotion_id TEXT NOT NULL,
                PRIMARY KEY(trainer_id,promotion_id))''',
            '''CREATE TABLE IF NOT EXISTS promotion_migrations (name TEXT PRIMARY KEY,completed_at TEXT NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS student_promotions_group ON student_promotions(promotion_id)',
            'CREATE INDEX IF NOT EXISTS trainer_promotions_group ON trainer_promotions(promotion_id)',
        ):
            conn.execute(sql)
        if not conn.execute('SELECT 1 FROM promotion_migrations WHERE name=?',(_MIGRATION,)).fetchone():
            now=datetime.now(timezone.utc).isoformat()
            tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'trainer_assignments','trainers'}.issubset(tables):
                legacy=conn.execute('''SELECT DISTINCT upper(trim(a.bts)),a.rentree_annee
                    FROM trainer_assignments a JOIN trainers t ON t.id=a.trainer_id''').fetchall()
                for bts,year in legacy:
                    if bts not in BTS_LABELS or not isinstance(year,int):
                        continue
                    promotion_id=secrets.token_urlsafe(24)
                    conn.execute('''INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,needs_setup,created_at,updated_at)
                        VALUES(?,?,?,NULL,?,NULL,NULL,1,?,?)''',(promotion_id,f'BTS {bts} · rentrée {year} · À compléter',bts,year,now,now))
                    conn.execute('''INSERT OR IGNORE INTO trainer_promotions(trainer_id,promotion_id)
                        SELECT a.trainer_id,? FROM trainer_assignments a JOIN trainers t ON t.id=a.trainer_id
                        WHERE upper(trim(a.bts))=? AND a.rentree_annee=?''',(promotion_id,bts,year))
                    if 'candidats' in tables:
                        columns={row[1] for row in conn.execute('PRAGMA table_info(candidats)')}
                        if {'id','bts','rentree_annee'}.issubset(columns):
                            candidates=conn.execute('''SELECT c.id FROM candidats c WHERE upper(trim(c.bts))=?
                                AND COALESCE(c.rentree_annee,2026)=? AND NOT EXISTS
                                (SELECT 1 FROM student_promotions s WHERE s.candidate_id=c.id)''',(bts,year)).fetchall()
                            for candidate in candidates:
                                conn.execute('INSERT OR IGNORE INTO student_promotions(candidate_id,promotion_id,assigned_at) VALUES(?,?,?)',(candidate[0],promotion_id,now))
                                conn.execute('INSERT INTO student_promotion_history(candidate_id,promotion_id,changed_at,reason) VALUES(?,?,?,?)',(candidate[0],promotion_id,now,'Migration des groupes existants'))
            # Revoke old sessions/links once; preserve passwords, emails and invitation metadata.
            if 'trainers' in tables:
                conn.execute('UPDATE trainers SET version=version+1')
            if 'trainer_access_tokens' in tables:
                conn.execute('UPDATE trainer_access_tokens SET consumed=1')
            conn.execute('INSERT INTO promotion_migrations(name,completed_at) VALUES(?,?)',(_MIGRATION,now))
        conn.execute('RELEASE SAVEPOINT promotions_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT promotions_schema')
        conn.execute('RELEASE SAVEPOINT promotions_schema')
        raise


# Public plural alias retained for app initialization and maintenance callers.
ensure_promotions_schema = ensure_promotion_schema

def _promotion_dict(row):
    if not row:
        return None
    result=dict(row)
    result['active']=bool(result['active'])
    result['needs_setup']=bool(result['needs_setup'])
    return result


def list_promotions(conn,bts=None,rentree_annee=None,active_only=False):
    ensure_promotion_schema(conn)
    sql='''SELECT p.*,
        (SELECT COUNT(*) FROM student_promotions s JOIN candidats c ON c.id=s.candidate_id WHERE s.promotion_id=p.id) AS student_count,
        (SELECT COUNT(*) FROM trainer_promotions a WHERE a.promotion_id=p.id) AS trainer_count
        FROM promotions p WHERE 1=1'''
    args=[]
    if bts:
        sql+=' AND p.bts=?';args.append(str(bts).strip().upper())
    if rentree_annee is not None:
        sql+=' AND p.rentree_annee=?';args.append(int(rentree_annee))
    if active_only:
        sql+=' AND p.active=1'
    sql+=' ORDER BY p.active DESC,p.rentree_annee DESC,p.bts,COALESCE(p.niveau,0),p.nom'
    return [_promotion_dict(row) for row in conn.execute(sql,args)]


def get_candidate_promotion(conn,candidate_id):
    ensure_promotion_schema(conn)
    row=conn.execute('SELECT p.* FROM promotions p JOIN student_promotions s ON s.promotion_id=p.id WHERE s.candidate_id=?',(candidate_id,)).fetchone()
    return _promotion_dict(row)


def get_trainer_promotions(conn,trainer_id):
    ensure_promotion_schema(conn)
    return [_promotion_dict(row) for row in conn.execute('''SELECT p.* FROM promotions p
        JOIN trainer_promotions a ON a.promotion_id=p.id WHERE a.trainer_id=?
        ORDER BY p.active DESC,p.rentree_annee DESC,p.bts,COALESCE(p.niveau,0),p.nom''',(trainer_id,))]


def replace_trainer_promotions(conn,trainer_id,promotion_ids):
    """Validate all IDs before changing links; existing archived grants may be retained."""
    ensure_promotion_schema(conn)
    existing={row[0] for row in conn.execute('SELECT promotion_id FROM trainer_promotions WHERE trainer_id=?',(trainer_id,))}
    for promotion_id in promotion_ids:
        row=conn.execute('SELECT active FROM promotions WHERE id=?',(promotion_id,)).fetchone()
        if not row or (not row[0] and promotion_id not in existing):
            raise ValueError('Choisissez des promotions existantes et actives. Une promotion archivée déjà attribuée peut être conservée.')
    conn.execute('DELETE FROM trainer_promotions WHERE trainer_id=?',(trainer_id,))
    conn.executemany('INSERT INTO trainer_promotions(trainer_id,promotion_id) VALUES(?,?)',[(trainer_id,promotion_id) for promotion_id in promotion_ids])


def _revoke_promotion_trainers(conn,promotion_id):
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'trainers' in tables:
        conn.execute('UPDATE trainers SET version=version+1 WHERE id IN (SELECT trainer_id FROM trainer_promotions WHERE promotion_id=?)',(promotion_id,))
    if 'trainer_access_tokens' in tables:
        conn.execute('UPDATE trainer_access_tokens SET consumed=1 WHERE trainer_id IN (SELECT trainer_id FROM trainer_promotions WHERE promotion_id=?)',(promotion_id,))


def assign_candidate_promotion(conn,candidate_id,promotion_id):
    """Caller owns the transaction. Returns the current placement after validation."""
    ensure_promotion_schema(conn)
    candidate=conn.execute('SELECT id,bts,rentree_annee FROM candidats WHERE id=?',(candidate_id,)).fetchone()
    if not candidate:
        raise LookupError('Dossier introuvable.')
    previous=conn.execute('SELECT promotion_id FROM student_promotions WHERE candidate_id=?',(candidate_id,)).fetchone()
    old_id=previous[0] if previous else None
    promotion_id=promotion_id or None
    if promotion_id:
        promotion=conn.execute('SELECT * FROM promotions WHERE id=?',(promotion_id,)).fetchone()
        if not promotion or (not promotion['active'] and old_id!=promotion_id):
            raise ValueError('Choisissez une promotion existante et active.')
        if str(candidate['bts'] or '').strip().upper()!=promotion['bts'] or int(candidate['rentree_annee'] or 2026)!=promotion['rentree_annee']:
            raise ValueError('La promotion doit correspondre au BTS et à la rentrée d’origine de cet étudiant.')
    if old_id!=promotion_id:
        now=datetime.now(timezone.utc).isoformat()
        conn.execute('DELETE FROM student_promotions WHERE candidate_id=?',(candidate_id,))
        if promotion_id:
            conn.execute('INSERT INTO student_promotions(candidate_id,promotion_id,assigned_at) VALUES(?,?,?)',(candidate_id,promotion_id,now))
        conn.execute('INSERT INTO student_promotion_history(candidate_id,previous_promotion_id,promotion_id,changed_at,reason) VALUES(?,?,?,?,?)',(candidate_id,old_id,promotion_id,now,'Affectation administrative'))
    return get_candidate_promotion(conn,candidate_id)


def register_promotions(app,db_connect,require_admin):
    def csrf():
        if '_promotion_csrf' not in session:
            session['_promotion_csrf']=secrets.token_urlsafe(32)
        return session['_promotion_csrf']

    def check_csrf():
        data=request.get_json(silent=True) if request.is_json else request.form
        value=request.headers.get('X-CSRF-Token') or (data.get('csrf_token','') if data else '')
        expected=session.get('_promotion_csrf','')
        if not isinstance(value,str) or not expected or not hmac.compare_digest(value.encode(),expected.encode()):
            abort(400,'La page a expiré. Rechargez-la avant de réessayer.')

    def guard():
        if not require_admin():
            abort(403)

    def response(ok,message,status=200,**extra):
        if request.is_json or 'application/json' in request.headers.get('Accept',''):
            result=app.make_response((jsonify(ok=ok,message=message,**extra),status))
        else:
            flash(message,'success' if ok else 'error')
            result=redirect(url_for('admin_promotions'),code=303)
        result.headers['Cache-Control']='no-store'
        return result

    def fields():
        data=request.get_json(silent=True) if request.is_json else request.form
        if not data or not all(isinstance(data.get(key,''),str) for key in ('nom','bts','date_debut','date_fin')):
            raise ValueError('Vérifiez les informations de la promotion.')
        nom=data.get('nom','').strip()
        bts=data.get('bts','').strip().upper()
        try:
            level=int(data.get('niveau',''))
            year=int(data.get('rentree_annee',''))
            beginning=date.fromisoformat(data.get('date_debut',''))
            end=date.fromisoformat(data.get('date_fin',''))
        except (ValueError,TypeError):
            raise ValueError('Renseignez le niveau, la rentrée d’origine et deux dates valides.')
        if not nom or len(nom)>140 or any(ord(c)<32 for c in nom) or bts not in BTS_LABELS or level not in (1,2) or not 2000<=year<=datetime.now().year+5:
            raise ValueError('Vérifiez le nom, le BTS, le niveau et la rentrée d’origine.')
        if end<beginning:
            raise ValueError('La date de fin doit être postérieure ou égale à la date de début.')
        return nom,bts,level,year,beginning.isoformat(),end.isoformat()

    @app.context_processor
    def promotion_context():
        return dict(promotion_csrf_token=csrf())

    @app.route('/admin/promotions',methods=['GET','POST'])
    def admin_promotions():
        if request.method=='GET' and not require_admin() and 'login' in app.view_functions:
            return redirect(url_for('login',next=request.full_path.rstrip('?')))
        guard()
        if request.method=='POST':
            check_csrf()
            try:
                values=fields()
            except ValueError as error:
                return response(False,str(error),400)
            promotion_id=secrets.token_urlsafe(24)
            now=datetime.now(timezone.utc).isoformat()
            with closing(db_connect()) as conn:
                ensure_promotion_schema(conn)
                conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,date_debut,date_fin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(promotion_id,*values,now,now))
                conn.commit()
            return response(True,'Promotion créée. Vous pouvez maintenant y affecter les étudiants et les formateurs.',201,promotion_id=promotion_id)
        with closing(db_connect()) as conn:
            promotions=list_promotions(conn)
        years=sorted({2026,2027,*range(datetime.now().year,datetime.now().year+3),*[p['rentree_annee'] for p in promotions]})
        selected_bts=request.args.get('bts','').upper()
        if selected_bts not in BTS_LABELS:selected_bts=''
        try:selected_year=int(request.args.get('rentree',datetime.now().year+1))
        except ValueError:selected_year=datetime.now().year+1
        if selected_year not in years:selected_year=datetime.now().year+1
        result=app.make_response(render_template('promotions_admin.html',title='Promotions · Plateforme de gestion des BTS',promotions=promotions,bts_labels=BTS_LABELS,years=years,selected_bts=selected_bts,selected_year=selected_year,csrf_token=csrf()))
        result.headers['Cache-Control']='no-store'
        return result

    @app.post('/admin/promotions/<promotion_id>/update')
    def admin_promotion_update(promotion_id):
        guard();check_csrf()
        try:values=fields()
        except ValueError as error:return response(False,str(error),400)
        with closing(db_connect()) as conn:
            ensure_promotion_schema(conn);conn.execute('BEGIN IMMEDIATE')
            previous=conn.execute('SELECT * FROM promotions WHERE id=?',(promotion_id,)).fetchone()
            if not previous:abort(404)
            nom,bts,level,year,beginning,end=values
            from planning import validate_promotion_change
            planning_conflicts=validate_promotion_change(conn,promotion_id,dict(date_debut=beginning,date_fin=end))
            if planning_conflicts:
                return response(False,'Ces dates rendraient le planning incohérent. Ajustez d’abord les cours et les périodes concernés.',409,conflicts=planning_conflicts)
            mismatch=conn.execute('''SELECT 1 FROM student_promotions s JOIN candidats c ON c.id=s.candidate_id
                WHERE s.promotion_id=? AND (upper(trim(COALESCE(c.bts,'')))<>? OR COALESCE(c.rentree_annee,2026)<>?) LIMIT 1''',(promotion_id,bts,year)).fetchone()
            if mismatch:return response(False,'Cette promotion contient des étudiants d’un autre BTS ou d’une autre rentrée. Réaffectez-les avant de modifier ces informations.',409)
            previous_fields=tuple(previous[key] for key in ('nom','bts','niveau','rentree_annee','date_debut','date_fin'))
            if values!=previous_fields or previous['needs_setup']:
                conn.execute('UPDATE promotions SET nom=?,bts=?,niveau=?,rentree_annee=?,date_debut=?,date_fin=?,needs_setup=0,updated_at=? WHERE id=?',(*values,datetime.now(timezone.utc).isoformat(),promotion_id))
                _revoke_promotion_trainers(conn,promotion_id)
            conn.commit()
        return response(True,'Promotion mise à jour.')

    @app.post('/admin/promotions/<promotion_id>/status')
    def admin_promotion_status(promotion_id):
        guard();check_csrf()
        data=request.get_json(silent=True) if request.is_json else request.form
        active=data.get('active') if data else None
        if active not in (0,1,'0','1',False,True):return response(False,'Choisissez un état valide.',400)
        active=1 if active in (1,'1',True) else 0
        with closing(db_connect()) as conn:
            ensure_promotion_schema(conn);conn.execute('BEGIN IMMEDIATE')
            previous=conn.execute('SELECT active FROM promotions WHERE id=?',(promotion_id,)).fetchone()
            if not previous:abort(404)
            if previous[0]!=active:
                conn.execute('UPDATE promotions SET active=?,updated_at=? WHERE id=?',(active,datetime.now(timezone.utc).isoformat(),promotion_id))
                _revoke_promotion_trainers(conn,promotion_id)
            conn.commit()
        return response(True,'Promotion réactivée.' if active else 'Promotion archivée. Les affectations sont conservées ; elle n’est plus accessible aux formateurs.')

    @app.post('/admin/candidat/<candidate_id>/promotion')
    def admin_candidate_promotion(candidate_id):
        guard();check_csrf()
        data=request.get_json(silent=True) if request.is_json else request.form
        promotion_id=data.get('promotion_id','') if data else ''
        if not isinstance(promotion_id,str) or len(promotion_id)>128:return response(False,'Choisissez une promotion valide.',400)
        try:
            with closing(db_connect()) as conn:
                ensure_promotion_schema(conn);conn.execute('BEGIN IMMEDIATE')
                promotion=assign_candidate_promotion(conn,candidate_id,promotion_id.strip())
                conn.commit()
        except LookupError:abort(404)
        except ValueError as error:return response(False,str(error),400)
        return response(True,'Étudiant affecté à la promotion.' if promotion else 'Affectation retirée.',promotion=promotion)
