"""Administration-only apprenticeship workspace, documents and explicit OPCO exchanges."""
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timezone
from io import BytesIO
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3

from cryptography.fernet import InvalidToken
from flask import Blueprint, abort, jsonify, render_template, request, send_file, session
from pypdf import PdfReader

from akto_sync import secret
from opco_convergence import identity
from apprenticeship_data import (FORM_GROUPS, PROVIDERS, STATES, REMOTE_STATES, at, clean_payload, completion, document_content, project_cerfa, fields, now, seed, validate)
from apprenticeship_convergence import TransferError, connection, read, submit, trusted_url
from apprenticeship_documents import agreement_pdf, cerfa_pdf

DETAILS={'promotion':'Promotion','owner':'Responsable du dossier','job_title':'Poste de l’apprenti','missions':'Missions en entreprise',
 'nda':'Numéro de déclaration d’activité','cfa_signer':'Signataire CFA et qualité','employer_signer':'Signataire entreprise et qualité',
 'objectives':'Objectifs et programme de formation','organization':'Organisation, modalités et moyens pédagogiques',
 'assessment':'Suivi, évaluation et sanction de la formation','vat':'Régime de TVA applicable','payment_terms':'Financement, reste à charge et modalités de paiement',
 'terms':'Engagements, absences, interruption et règlement des litiges','notes':'Notes internes'}
DEFAULT_DETAILS={'nda':'93830600283','cfa_signer':'Clément VAILLANT, directeur général',
 'terms':'Le CFA assure la formation prévue au programme et le suivi pédagogique de l’apprenti. L’employeur confie des missions en lien avec le diplôme préparé et désigne un maître d’apprentissage. Les parties se communiquent les absences et tout événement affectant le contrat. En cas de rupture ou de modification, elles se rapprochent pour arrêter les prestations réalisées et informer l’OPCO. Les modalités financières sont ajustées selon les prestations réalisées et la décision de prise en charge. En cas de différend, les parties recherchent une solution amiable avant de saisir la juridiction compétente.'}


def schema(conn):
    for sql in [
      '''CREATE TABLE IF NOT EXISTS apprenticeship_dossiers (
        id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, creation_key TEXT NOT NULL UNIQUE,
        version INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
        payload BLOB NOT NULL, details BLOB NOT NULL, provider TEXT NOT NULL DEFAULT 'akto',
        environment TEXT NOT NULL DEFAULT 'recette', state TEXT NOT NULL DEFAULT 'draft',
        opco_ref TEXT, external_ref TEXT, remote BLOB, last_sync TEXT, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
      'CREATE INDEX IF NOT EXISTS apprenticeship_candidate ON apprenticeship_dossiers(candidate_id,updated_at)',
      'CREATE UNIQUE INDEX IF NOT EXISTS apprenticeship_opco_ref ON apprenticeship_dossiers(provider,environment,opco_ref) WHERE opco_ref IS NOT NULL',
      '''CREATE TABLE IF NOT EXISTS apprenticeship_documents (
        id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL,
        signed INTEGER NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL)''',
      'CREATE INDEX IF NOT EXISTS apprenticeship_docs_dossier ON apprenticeship_documents(dossier_id,revision)',
      '''CREATE TABLE IF NOT EXISTS apprenticeship_events (
        id INTEGER PRIMARY KEY, dossier_id TEXT NOT NULL, action TEXT NOT NULL, message TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL)''',
      '''CREATE TABLE IF NOT EXISTS apprenticeship_connections (
        provider TEXT NOT NULL, environment TEXT NOT NULL, credential BLOB NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(provider,environment))''',
      '''CREATE TABLE IF NOT EXISTS apprenticeship_dues (
        id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, label TEXT NOT NULL, due_date TEXT NOT NULL,
        amount_cents INTEGER NOT NULL, paid_cents INTEGER NOT NULL DEFAULT 0, payer TEXT NOT NULL,
        invoice TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1)''']:
        conn.execute(sql)
    conn.commit()


def register_apprenticeship(app,connect,require_admin):
    with closing(connect()) as conn:schema(conn)
    bp=Blueprint('apprenticeship',__name__)
    def pack(value):return secret(app).encrypt(json.dumps(value,ensure_ascii=False).encode())
    def unpack(value):return json.loads(secret(app).decrypt(value))
    def guard(mutation=False):
        if not require_admin():abort(403)
        if mutation:
            expected=session.get('_planning_csrf','');token=request.headers.get('X-CSRF-Token','')
            if not expected or not hmac.compare_digest(expected.encode(),token.encode()):abort(403)
    @bp.before_request
    def auth():guard(request.method not in ('GET','HEAD','OPTIONS'))
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    @bp.errorhandler(ValueError)
    def invalid(e):return jsonify(ok=False,message=str(e)),400
    @bp.errorhandler(InvalidToken)
    def cipher_error(e):return jsonify(ok=False,message='Le dossier ne peut plus être déchiffré. Vérifiez la clé de chiffrement du serveur.'),503
    @bp.errorhandler(sqlite3.IntegrityError)
    def conflict(e):return jsonify(ok=False,message='Ce dossier existe déjà ou vient d’être modifié. Actualisez la liste.'),409
    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict) or len(json.dumps(value))>100000:raise ValueError('Formulaire invalide ou trop volumineux.')
        return value
    def person(conn,cid):
        row=conn.execute('SELECT * FROM candidats WHERE id=?',(cid,)).fetchone()
        if not row:abort(404)
        return dict(row)
    def load(conn,did):
        row=conn.execute('SELECT * FROM apprenticeship_dossiers WHERE id=?',(did,)).fetchone()
        if not row:abort(404)
        row=dict(row);row['payload']=unpack(row['payload']);row['details']=unpack(row['details'])
        row['remote']=unpack(row['remote']) if row['remote'] else {}
        return row
    def event(conn,did,action,message):
        conn.execute('INSERT INTO apprenticeship_events(dossier_id,action,message,actor,created_at) VALUES(?,?,?,?,?)',
          (did,action,message,str(session.get('admin_name') or session.get('admin_user') or 'Administration')[:150],now()))
    def version(row,value):
        if type(value) is not int or row['version']!=value:abort(409,description='Le dossier a changé dans une autre fenêtre. Rechargez-le avant de continuer.')
    def mutable(row):
        if row['opco_ref'] or row['state'] in ('sending','uncertain','archived'):
            raise ValueError('Ce dossier est figé après transmission ou archivage. Créez un nouveau dossier pour un avenant.')
    def recoverable(row):
        return row['state']=='sending' and (datetime.now(timezone.utc)-datetime.fromisoformat(row['updated_at'])).total_seconds()>120
    def docs(conn,did):
        return [dict(r) for r in conn.execute('SELECT id,revision,kind,signed,created_at FROM apprenticeship_documents WHERE dossier_id=? ORDER BY created_at DESC',(did,))]
    def checks(row,documents):
        errors=validate(row['payload'])
        for key in ('objectives','organization','assessment','vat','payment_terms','employer_signer','nda','cfa_signer'):
            if not row['details'].get(key):errors.append(dict(path='details.'+key,label=DETAILS[key],message='À compléter pour la convention.'))
        # Attestations describe real signed documents; never manufacture affirmative values.
        for g in FORM_GROUPS:
            for f in g['fields']:
                if (f['path'].split('.')[-1].startswith(('CERFA','attestation')) or f['path']=='convention.mandatEmployeur') and at(row['payload'],f['path']) is not True:
                    errors.append(dict(path=f['path'],label=f['label'],message='À confirmer avant l’envoi.'))
        for kind in ('cerfa','convention'):
            if not any(d['revision']==row['revision'] and d['signed'] and d['kind']==kind for d in documents):
                errors.append(dict(path='documents.'+kind,label=kind.upper() if kind=='cerfa' else 'Convention',message='Ajoutez le PDF signé de cette version.'))
        return errors
    def summary(row,p=None):
        payload=row['payload'];a=at(payload,'cerfa.apprenti',{})
        return dict(id=row['id'],candidate_id=row['candidate_id'],name=' '.join(filter(None,(a.get('prenom'),a.get('nom')))),
          training=at(payload,'cerfa.formation.intituleQualification','Formation à compléter'),promotion=row['details'].get('promotion',''),
          employer=at(payload,'cerfa.employeur.denomination','Entreprise à compléter'),provider=row['provider'],environment=row['environment'],
          state=row['state'],state_label=STATES.get(row['state'],row['state']),start=at(payload,'cerfa.contrat.dateDebutContrat','')[:10],
          end=at(payload,'cerfa.contrat.dateFinContrat','')[:10],updated_at=row['updated_at'],opco_ref=row['opco_ref'],external_ref=row['external_ref'],source='local')
    def output(conn,row):
        documents=docs(conn,row['id']);errors=checks(row,documents)
        return dict(**summary(row),payload=row['payload'],details=row['details'],version=row['version'],revision=row['revision'],
          documents=documents,errors=errors,completion=completion(row['payload']),
          events=[dict(r) for r in conn.execute('SELECT action,message,actor,created_at FROM apprenticeship_events WHERE dossier_id=? ORDER BY id DESC LIMIT 60',(row['id'],))],
          last_sync=row['last_sync'],error=row['error'],remote=row['remote'],recoverable=recoverable(row),locked=bool(row['opco_ref'] or row['state'] in ('sending','uncertain','archived')))
    def insert(conn,cid,key,payload,details,provider='akto',environment='recette',remote=None):
        for _ in range(20):
            did=secrets.token_hex(3)
            if not conn.execute('SELECT 1 FROM apprenticeship_dossiers WHERE id=?',(did,)).fetchone():break
        else:raise ValueError('Impossible de créer une référence unique. Réessayez.')
        conn.execute('INSERT INTO apprenticeship_dossiers(id,candidate_id,creation_key,payload,details,provider,environment,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
          (did,cid,key,pack(payload),pack(details),provider,environment,now(),now()))
        event(conn,did,'created','Dossier créé et informations disponibles préremplies.')
        return did

    @bp.get('/admin/contrats-apprentissage')
    @bp.get('/admin/contrats-apprentissage/echeances')
    def workspace():
        session.setdefault('_planning_csrf',secrets.token_urlsafe(32))
        return render_template('apprenticeship_workspace.html',title='Contrats d’apprentissage · Intégrale Academy',
            view='dues' if request.path.endswith('/echeances') else 'folders',csrf_token=session['_planning_csrf'])

    @bp.get('/admin/apprentissage/config')
    def config():
        return jsonify(ok=True,groups=FORM_GROUPS,remuneration=fields('RemunerationAnnuelle','period'),details=DETAILS,providers=PROVIDERS,states=STATES)

    @bp.get('/admin/apprentissage/etudiants')
    def students():
        q=request.args.get('q','').strip()[:100]
        with closing(connect()) as conn:
            people=[dict(r) for r in conn.execute("SELECT id,prenom,nom,bts FROM candidats WHERE nom||' '||prenom LIKE ? OR prenom||' '||nom LIKE ? ORDER BY nom,prenom LIMIT 30",('%'+q+'%','%'+q+'%'))]
        return jsonify(ok=True,students=people)

    @bp.get('/admin/apprentissage/dossiers')
    def dossiers():
        cid=request.args.get('candidate_id','')
        with closing(connect()) as conn:
            ids=[r[0] for r in conn.execute('SELECT id FROM apprenticeship_dossiers'+(' WHERE candidate_id=?' if cid else '')+' ORDER BY updated_at DESC', (cid,) if cid else ())]
            rows=[summary(load(conn,did)) for did in ids]
            if not cid:
                # Existing read-only OPCO contracts remain visible, without creating or sending a dossier.
                from opco_contracts import records_by_student
                from wedof_contract_data import FINANCERS
                people=[dict(r) for r in conn.execute('SELECT id,nom,prenom,date_naissance,bts FROM candidats')]
                known={(r['provider'],r['opco_ref']) for r in rows if r['environment']=='production' and r['opco_ref']}
                provider_keys={'opcoCfaAkto':'akto','opcoCfaOpcommerce':'opcommerce','opcoCfaEp':'ep','opcoCfaMobilites':'mobilites'}
                roster={p['id']:p for p in people}
                for sid,records in records_by_student(conn,people).items():
                    for rec in records:
                        provider=provider_keys.get(rec.get('financer'),'akto' if rec.get('akto_record') else '')
                        ref=rec.get('internal_number') or rec.get('external_number') or rec.get('reference','')
                        if (provider,ref) in known:continue
                        p=roster[sid]
                        rows.append(dict(id=ref,candidate_id=sid,name=p['prenom']+' '+p['nom'],training=rec.get('training_name') or p['bts'],
                          promotion='',employer=rec.get('employer_name',''),provider=provider,environment='production',state=rec.get('state','pending'),
                          state_label=rec.get('state_label','Relevé OPCO'),start=rec.get('contract_start',''),end=rec.get('contract_end',''),
                          source='opco',updated_at=rec.get('checked_at',''),opco_ref=ref,external_ref=rec.get('external_number','')))
        return jsonify(ok=True,dossiers=rows)

    @bp.post('/admin/apprentissage/dossiers')
    def create():
        data=body();cid=data.get('candidate_id');key=data.get('creation_key','')
        if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,100}',key):raise ValueError('Actualisez la page avant de créer le dossier.')
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');p=person(conn,cid)
            existing=conn.execute('SELECT id,candidate_id FROM apprenticeship_dossiers WHERE creation_key=?',(key,)).fetchone()
            if existing:
                if existing['candidate_id']!=cid:abort(409)
                return jsonify(ok=True,dossier=output(conn,load(conn,existing['id'])))
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            promotion=conn.execute('SELECT p.* FROM promotions p JOIN student_promotions s ON p.id=s.promotion_id WHERE s.candidate_id=?',(cid,)).fetchone() if {'promotions','student_promotions'}<=tables else None
            company=conn.execute('SELECT c.* FROM companies c JOIN company_students s ON c.id=s.company_id WHERE s.candidate_id=?',(cid,)).fetchone() if {'companies','company_students'}<=tables else None
            details={**DEFAULT_DETAILS,'promotion':promotion['nom'] if promotion else ''}
            did=insert(conn,cid,key,seed(p,dict(promotion) if promotion else None,dict(company) if company else None),details)
            conn.commit();return jsonify(ok=True,dossier=output(conn,load(conn,did))),201

    @bp.get('/admin/apprentissage/dossiers/<did>')
    def detail(did):
        with closing(connect()) as conn:return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.put('/admin/apprentissage/dossiers/<did>')
    def save(did):
        data=body()
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');row=load(conn,did);version(row,data.get('version'));mutable(row)
            payload=clean_payload(data.get('payload'));errors=validate(payload,False)
            if errors:return jsonify(ok=False,message='Certains champs sont à corriger.',errors=errors),400
            details=data.get('details',{})
            if not isinstance(details,dict) or any(k not in DETAILS or not isinstance(v,str) or len(v)>10000 for k,v in details.items()):raise ValueError('Informations de gestion invalides.')
            provider=data.get('provider');environment=data.get('environment')
            if provider not in PROVIDERS or environment not in ('recette','production'):raise ValueError('Choisissez un OPCO et un environnement.')
            changed=payload!=row['payload'] or details!=row['details'] or provider!=row['provider'] or environment!=row['environment']
            if changed:
                revision_changed=document_content(payload,details)!=document_content(row['payload'],row['details'])
                conn.execute("UPDATE apprenticeship_dossiers SET payload=?,details=?,provider=?,environment=?,version=version+1,revision=revision+?,state='draft',error=NULL,updated_at=? WHERE id=?",(pack(payload),pack(details),provider,environment,int(revision_changed),now(),did))
                event(conn,did,'saved','Dossier enregistré.'+(' Les documents signés des versions précédentes restent archivés.' if revision_changed else ''))
                if not checks(load(conn,did),docs(conn,did)):conn.execute("UPDATE apprenticeship_dossiers SET state='ready' WHERE id=?",(did,))
            conn.commit();return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.post('/admin/apprentissage/dossiers/<did>/documents')
    def generate(did):
        data=body()
        with closing(connect()) as conn:
            row=load(conn,did);version(row,data.get('version'))
        kind=data.get('kind')
        if kind not in ('cerfa','convention'):abort(404)
        content=cerfa_pdf(row['payload']) if kind=='cerfa' else agreement_pdf(row['payload'],row['details'],did)
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');current=load(conn,did);version(current,row['version'])
            docid=secrets.token_hex(16)
            conn.execute('INSERT INTO apprenticeship_documents VALUES(?,?,?,?,?,?,?,?)',(docid,did,row['revision'],kind,0,secret(app).encrypt(content),hashlib.sha256(content).hexdigest(),now()))
            event(conn,did,'document',f'{"CERFA officiel" if kind=="cerfa" else "Convention"} généré(e), version {row["revision"]}.')
            conn.commit();return jsonify(ok=True,dossier=output(conn,current),document_url='/admin/apprentissage/documents/'+docid)

    @bp.post('/admin/apprentissage/dossiers/<did>/documents-signes')
    def upload(did):
        kind=request.form.get('kind');file=request.files.get('file')
        if kind not in ('cerfa','convention') or not file:raise ValueError('Choisissez le document PDF signé.')
        content=file.read(8_000_001)
        if len(content)>8_000_000 or not content.startswith(b'%PDF-'):raise ValueError('PDF requis, de 8 Mo maximum.')
        try:
            reader=PdfReader(BytesIO(content))
            if reader.is_encrypted or not 1<=len(reader.pages)<=80:raise ValueError()
        except Exception:raise ValueError('Ce PDF est protégé ou illisible.') from None
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');row=load(conn,did);version(row,int(request.form.get('version','0')));mutable(row)
            if request.form.get('confirmed')!='true':raise ValueError('Confirmez que le document correspond à la version enregistrée et comporte les signatures requises.')
            docid=secrets.token_hex(16)
            conn.execute('INSERT INTO apprenticeship_documents VALUES(?,?,?,?,?,?,?,?)',(docid,did,row['revision'],kind,1,secret(app).encrypt(content),hashlib.sha256(content).hexdigest(),now()))
            event(conn,did,'signed_document',f'{kind.upper()} signé ajouté pour la version {row["revision"]}.')
            conn.execute('UPDATE apprenticeship_dossiers SET version=version+1,updated_at=? WHERE id=?',(now(),did))
            current=load(conn,did)
            if not checks(current,docs(conn,did)):conn.execute("UPDATE apprenticeship_dossiers SET state='ready' WHERE id=?",(did,))
            conn.commit();return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.get('/admin/apprentissage/documents/<docid>')
    def download(docid):
        with closing(connect()) as conn:row=conn.execute('SELECT * FROM apprenticeship_documents WHERE id=?',(docid,)).fetchone()
        if not row:abort(404)
        content=secret(app).decrypt(row['content'])
        response=send_file(BytesIO(content),mimetype='application/pdf',as_attachment=request.args.get('download')=='1',download_name=f'{row["kind"]}-{row["dossier_id"]}-v{row["revision"]}.pdf')
        response.headers['Content-Security-Policy']="sandbox; default-src 'none'"
        return response

    @bp.post('/admin/apprentissage/dossiers/<did>/transmettre')
    def transmit(did):
        data=body()
        with closing(connect()) as conn:
            row=load(conn,did);version(row,data.get('version'));mutable(row)
            problems=checks(row,docs(conn,did))
            if problems:return jsonify(ok=False,message='Complétez les points bloquants avant la transmission.',errors=problems),400
            if data.get('confirm')!=did or data.get('environment')!=row['environment']:raise ValueError('Confirmez le numéro du dossier et son environnement avant l’envoi.')
            # Authenticate before marking sending: a missing credential is a definite non-send.
            base,headers=connection(app,conn,row['provider'],row['environment'])
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');current=load(conn,did);version(current,row['version']);mutable(current)
            document=conn.execute("SELECT content FROM apprenticeship_documents WHERE dossier_id=? AND revision=? AND kind='convention' AND signed=1 ORDER BY created_at DESC LIMIT 1",(did,row['revision'])).fetchone()
            signed=secret(app).decrypt(document[0])
            conn.execute("UPDATE apprenticeship_dossiers SET state='sending',version=version+1,error=NULL,updated_at=? WHERE id=?",(now(),did))
            event(conn,did,'sending',f'Transmission demandée à {PROVIDERS[row["provider"]]} en {row["environment"]}, version {row["revision"]}.')
            conn.commit()
        try:
            receipt=submit(base,headers,row['payload'],signed)
        except TransferError as e:
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                state='uncertain' if e.uncertain else 'draft'
                # A manual recovery may already have obtained the OPCO receipt.
                current=load(conn,did)
                if current['opco_ref']:return jsonify(ok=True,dossier=output(conn,current))
                conn.execute('UPDATE apprenticeship_dossiers SET state=?,error=?,version=version+1,updated_at=? WHERE id=?',(state,str(e),now(),did))
                event(conn,did,state,str(e));conn.commit()
            return jsonify(ok=False,message=str(e),uncertain=e.uncertain),502
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=load(conn,did)
            if current['opco_ref']:
                if current['opco_ref']!=receipt['numeroInterne']:raise ValueError('Deux références OPCO différentes ont été retournées. Vérifiez le résultat auprès de l’OPCO.')
                return jsonify(ok=True,dossier=output(conn,current))
            conn.execute("UPDATE apprenticeship_dossiers SET state='sent',opco_ref=?,external_ref=?,version=version+1,updated_at=? WHERE id=?",(receipt['numeroInterne'],receipt['numeroExterne'],now(),did))
            event(conn,did,'sent','Accusé de réception OPCO enregistré : '+receipt['numeroInterne'])
            conn.commit();return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.post('/admin/apprentissage/dossiers/<did>/recuperer')
    def retrieve(did):
        data=body()
        with closing(connect()) as conn:
            row=load(conn,did);version(row,data.get('version'));p=person(conn,row['candidate_id'])
            if row['state']=='sending' and not recoverable(row):raise ValueError('La transmission est en cours. Attendez son résultat. Après deux minutes, une récupération par référence OPCO sera possible en rouvrant le dossier.')
            if row['state']=='archived':raise ValueError('Ce dossier est archivé.')
            base,headers=connection(app,conn,row['provider'],row['environment'])
        raw=read(base,headers,row['opco_ref'] or str(data.get('reference','')).strip(),str(data.get('external','')).strip(),str(data.get('deca','')).strip())
        apprentice=raw['cerfa'].get('apprenti') or {}
        if not isinstance(apprentice,dict):raise ValueError('Identité du dossier OPCO illisible. Aucune donnée n’a été importée.')
        if not all(identity(p.get('nom'),p.get('prenom'),p.get('date_naissance'))) or identity(apprentice.get('nom'),apprentice.get('prenom'),apprentice.get('dateNaissance'))!=identity(p.get('nom'),p.get('prenom'),p.get('date_naissance')):
            raise ValueError('L’identité et la date de naissance du dossier OPCO ne correspondent pas à cet étudiant. Aucune donnée n’a été importée.')
        # Keep only financial/status data in the remote snapshot; no bank details or unrelated people.
        dues=raw.get('echeances')
        if dues is not None and (not isinstance(dues,list) or len(dues)>100 or not all(isinstance(d,dict) for d in dues)):raise ValueError('Échéancier OPCO invalide. Le relevé précédent est conservé.')
        for d in dues or []:
            for key in ('montantTotal','montantRegle','montantEnCoursInstruction'):
                v=d.get(key)
                if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<0):raise ValueError('Montants OPCO invalides. Le relevé précédent est conservé.')
        allowed=('numero','dateOuverture','montantTotal','montantRegle','montantEnCoursInstruction','dateDebut','dateFin','codification')
        remote=dict(engagement=raw.get('engagement'),etat=raw['cerfa'].get('etat'),echeances=[{k:v for k,v in d.items() if k in allowed} for d in dues] if dues is not None else row['remote'].get('echeances',[]),schedule_missing=dues is None)
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');current=load(conn,did);version(current,row['version'])
            state=REMOTE_STATES.get(raw['cerfa'].get('etat'),'sent')
            # First attachment imports the returned contract, while later reads preserve the local signed revision.
            if not row['opco_ref']:
                payload=deepcopy(row['payload'])
                incoming=project_cerfa(raw['cerfa'])
                def merge(target,source):
                    for k,v in source.items():
                        if isinstance(v,dict) and isinstance(target.get(k),dict):merge(target[k],v)
                        else:target[k]=v
                merge(payload.setdefault('cerfa',{}),incoming)
                if not validate(payload,False):
                    conn.execute('UPDATE apprenticeship_dossiers SET payload=?,revision=revision+1 WHERE id=?',(pack(payload),did))
            conn.execute('UPDATE apprenticeship_dossiers SET remote=?,state=?,opco_ref=?,external_ref=?,last_sync=?,error=NULL,version=version+1,updated_at=? WHERE id=?',
              (pack(remote),state,raw['cerfa']['numeroInterne'],raw['cerfa'].get('numeroExterne'),now(),now(),did))
            event(conn,did,'synchronized','Dossier retrouvé auprès de l’OPCO ; statut et échéances actualisés.' if not remote['schedule_missing'] else 'Dossier retrouvé. Échéancier non communiqué : dernier relevé conservé.')
            conn.commit();return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.post('/admin/apprentissage/dossiers/<did>/archiver')
    def archive(did):
        data=body()
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');row=load(conn,did);version(row,data.get('version'))
            if row['state'] in ('sending','uncertain'):raise ValueError('Vérifiez d’abord le résultat de la transmission.')
            conn.execute("UPDATE apprenticeship_dossiers SET state='archived',version=version+1,updated_at=? WHERE id=?",(now(),did))
            event(conn,did,'archived','Dossier archivé localement. Aucune annulation envoyée à l’OPCO.');conn.commit()
            return jsonify(ok=True,dossier=output(conn,load(conn,did)))

    @bp.get('/admin/apprentissage/connexions')
    def connections():
        with closing(connect()) as conn:
            rows=[dict(r) for r in conn.execute('SELECT provider,environment,updated_at FROM apprenticeship_connections')]
            recette=conn.execute('SELECT credential FROM akto_recette_key WHERE id=1').fetchone()
            if recette and recette[0]:rows.append(dict(provider='akto',environment='recette',updated_at='',existing=True))
            rows.extend(dict(provider=r[0],environment='production',existing=True) for r in conn.execute('SELECT provider FROM opco_accounts WHERE credential IS NOT NULL'))
        return jsonify(ok=True,connections=rows)

    @bp.post('/admin/apprentissage/connexions')
    def save_connection():
        data=body();provider=data.get('provider');environment=data.get('environment')
        if provider not in PROVIDERS or environment not in ('recette','production'):raise ValueError('Connexion inconnue.')
        if provider=='akto' and environment=='recette':raise ValueError('La clé de recette AKTO se règle dans Paramètres > AKTO Convergence.')
        config={k:str(data.get(k,'')).strip() for k in ('api','token','key','client_id','client_secret','scope','auth_mode')}
        if any(not config[k] for k in ('api','token','key','client_id','client_secret')) or any(len(v)>8192 for v in config.values()):raise ValueError('Renseignez les accès fournis par votre OPCO.')
        for key in ('api','token'):config[key]=trusted_url(provider,key,config[key])
        if config['auth_mode'] not in ('basic','body'):raise ValueError('Mode d’authentification invalide.')
        with closing(connect()) as conn:
            conn.execute('INSERT INTO apprenticeship_connections VALUES(?,?,?,?) ON CONFLICT(provider,environment) DO UPDATE SET credential=excluded.credential,updated_at=excluded.updated_at',(provider,environment,pack(config),now()))
            conn.commit()
        return jsonify(ok=True,message='Accès enregistrés et chiffrés. Ils seront utilisés pour cet environnement uniquement.')

    @bp.get('/admin/apprentissage/echeances')
    def dues():
        result=[]
        def remote_due(d,ref,name,provider,environment,did=None,cid=None):
            amount=d.get('montantTotal');paid=d.get('montantRegle');pending=d.get('montantEnCoursInstruction')
            if type(amount) not in (int,float) or not math.isfinite(amount) or amount<0:return
            if type(paid) not in (int,float) or not math.isfinite(paid) or paid<0:paid=None
            if type(pending) not in (int,float) or not math.isfinite(pending) or pending<0:pending=None
            due=str(d.get('dateOuverture') or '')[:10]
            state='paid' if isinstance(paid,(int,float)) and paid>=amount else 'pending' if isinstance(pending,(int,float)) and pending>0 else 'unknown' if paid is None else 'due' if due and due<=date.today().isoformat() else 'upcoming'
            result.append(dict(id=str(ref)+'-'+str(d.get('numero')),dossier_id=did,candidate_id=cid,reference=ref,name=name,provider=provider,environment=environment,payer='OPCO',
              due_date=due,amount=amount,paid=paid,state=state,label='Échéance n°'+str(d.get('numero','')),source='opco',start=d.get('dateDebut'),end=d.get('dateFin')))
        with closing(connect()) as conn:
            ids=[r[0] for r in conn.execute("SELECT id FROM apprenticeship_dossiers WHERE state!='archived'")];known=set()
            for did in ids:
                row=load(conn,did);s=summary(row)
                if row['opco_ref'] and row['environment']=='production':known.add((row['provider'],row['opco_ref']))
                for d in row['remote'].get('echeances',[]):remote_due(d,row['opco_ref'] or did,s['name'],row['provider'],row['environment'],did,row['candidate_id'])
                for d in conn.execute('SELECT * FROM apprenticeship_dues WHERE dossier_id=? ORDER BY due_date',(did,)):
                    result.append(dict(d,id=d['id'],dossier_id=did,reference=did,name=s['name'],provider=row['provider'],environment=row['environment'],amount=d['amount_cents']/100,paid=d['paid_cents']/100,
                      state='paid' if d['paid_cents']>=d['amount_cents'] else 'pending' if d['invoice'] else 'due' if d['due_date']<=date.today().isoformat() else 'upcoming',source='manual'))
            from opco_contracts import records_by_student
            people=[dict(r) for r in conn.execute('SELECT id,nom,prenom,date_naissance,bts FROM candidats')];roster={p['id']:p for p in people}
            keys={'opcoCfaAkto':'akto','opcoCfaOpcommerce':'opcommerce','opcoCfaEp':'ep','opcoCfaMobilites':'mobilites'}
            for cid,records in records_by_student(conn,people).items():
                for rec in records:
                    provider=keys.get(rec.get('financer'),'akto' if rec.get('akto_record') else '')
                    ref=rec.get('internal_number') or rec.get('external_number') or rec.get('reference','')
                    if (provider,ref) in known:continue
                    for d in rec.get('schedules',[]):remote_due(d,ref,roster[cid]['prenom']+' '+roster[cid]['nom'],provider,'production',cid=cid)
        return jsonify(ok=True,dues=result)

    @bp.post('/admin/apprentissage/dossiers/<did>/echeances')
    def add_due(did):
        data=body()
        try:
            due=date.fromisoformat(data.get('due_date','')).isoformat();amount=int(data.get('amount_cents'));paid=int(data.get('paid_cents',0))
        except (ValueError,TypeError):raise ValueError('Vérifiez la date et les montants.') from None
        if not 0<=paid<=amount<=100000000 or amount<=0 or data.get('payer') not in ('OPCO','Entreprise'):raise ValueError('Montant ou financeur invalide.')
        label=str(data.get('label','')).strip()[:200];invoice=str(data.get('invoice','')).strip()[:100]
        if not label:raise ValueError('Donnez un libellé à cette échéance.')
        with closing(connect()) as conn:
            conn.execute('BEGIN IMMEDIATE');row=load(conn,did)
            if row['state']=='archived':raise ValueError('Ce dossier est archivé.')
            if data.get('id'):
                changed=conn.execute('UPDATE apprenticeship_dues SET label=?,due_date=?,amount_cents=?,paid_cents=?,payer=?,invoice=?,version=version+1 WHERE id=? AND dossier_id=? AND version=?',(label,due,amount,paid,data['payer'],invoice,data['id'],did,data.get('version')))
                if not changed.rowcount:abort(409)
            else:conn.execute('INSERT INTO apprenticeship_dues(id,dossier_id,label,due_date,amount_cents,paid_cents,payer,invoice) VALUES(?,?,?,?,?,?,?,?)',(secrets.token_hex(12),did,label,due,amount,paid,data['payer'],invoice))
            event(conn,did,'due','Échéance prévisionnelle mise à jour : '+label);conn.commit()
        return jsonify(ok=True)
    app.register_blueprint(bp)
