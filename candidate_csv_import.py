"""Silent import of confirmed BTS enrolments from a class roster."""
import csv
import io
import json
import re
import uuid
from collections import Counter
from contextlib import closing
from datetime import date, datetime

from flask import abort, redirect, render_template, request, session, url_for

from candidate_creation import insert_candidate
from candidate_messages import _csrf_token, _equal
from training_programs import BTS_LABELS

REQUIRED = {'nom_famille', 'prenoms', 'adresse_mail', 'date_naissance', 'division_classe'}


def parse_roster(raw, normalize_names):
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('cp1252')
    reader = csv.DictReader(io.StringIO(content, newline=''), delimiter=';', strict=True)
    if not REQUIRED.issubset(reader.fieldnames or ()) or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('Vérifiez les en-têtes du CSV et le séparateur point-virgule.')
    records = []
    for line in reader:
        if not any(line.values()):
            continue
        number = reader.line_num
        if None in line or None in line.values():
            raise ValueError(f'Ligne {number} : nombre de colonnes incorrect.')
        line = {key: value.strip() for key, value in line.items()}
        division = line['division_classe'].upper()
        match = re.fullmatch(r'([A-Z]+)[12][A-Z](\d{2})\d*', division)
        if not match or match[1] not in BTS_LABELS:
            raise ValueError(f'Ligne {number} : division BTS inconnue ({division}).')
        try:
            birth = datetime.strptime(line['date_naissance'], '%d/%m/%Y').date()
            if not date(1900,1,1) <= birth <= date.today():
                raise ValueError
        except ValueError:
            raise ValueError(f'Ligne {number} : date de naissance incorrecte.') from None
        email = line['adresse_mail'].lower()
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email) or not line['nom_famille'] or not line['prenoms']:
            raise ValueError(f'Ligne {number} : vérifiez le nom, les prénoms et l’adresse e-mail.')
        fields = dict(nom=line['nom_famille'], prenom=line['prenoms'], email=email, date_naissance=birth.isoformat(),
                      sexe={'M':'Homme','F':'Femme'}.get(line.get('civilite'),''),
                      tel=re.sub(r'[\s.()-]', '', line.get('telephone_mobile','')), ville=line.get('localite',''),
                      adresse=' '.join(filter(None,(line.get('adresse_'+str(i)) for i in range(1,5)))),
                      cp=line.get('code_postal',''), ville_naissance=line.get('commune_naissance',''),
                      pays_naissance='France' if line.get('pays_naissance')=='100' else line.get('pays_naissance',''),
                      nationalite='Française' if line.get('nationalite')=='100' else line.get('nationalite',''),
                      bts=match[1], rentree_annee=2000+int(match[2]), mode='presentiel', statut='confirmee')
        normalize_names(fields)
        records.append((number, division, birth, fields))
    if not records:
        raise ValueError('Le tableau ne contient aucun étudiant.')
    return records


def process_import(conn, records, apply):
    counts, classes, conflicts = Counter(), Counter(), []
    seen = set()
    for number, division, birth, row in records:
        classes[(division, row['bts'], row['rentree_annee'])] += 1
        key = (row['rentree_annee'], row['email'])
        if key in seen:
            raise ValueError(f'Ligne {number} : adresse e-mail répétée pour la même rentrée dans le CSV.')
        seen.add(key)
        matches = conn.execute("""SELECT * FROM candidats WHERE rentree_annee=? AND
            (lower(trim(email))=? OR date_naissance=?)""", (key[0], key[1],row['date_naissance'])).fetchall()
        def same_name(existing):
            return all(str(existing[k] or '').strip().casefold()==row[k].casefold() for k in ('nom','prenom'))
        matches = [r for r in matches if str(r['email'] or '').strip().lower()==key[1] or same_name(r)]
        if matches:
            old = matches[0]
            if (len(matches)!=1 or not same_name(old) or old['bts']!=row['bts']
                    or old['date_naissance'] not in (None,'',row['date_naissance'])
                    or str(old['email'] or '').strip().lower()!=key[1]
                    or old['statut'] not in ('preinscription','validee','confirmee','reconfirmee')):
                conflicts.append(number)
                continue
            if old['statut'] in ('confirmee','reconfirmee'):
                counts['existing'] += 1
                continue
            counts['confirmed'] += 1
            if apply:
                now = datetime.now().isoformat()
                conn.execute("""UPDATE candidats SET statut='confirmee',date_confirmee=?,updated_at=?,
                    token_confirm=NULL,token_confirm_exp=NULL WHERE id=?""", (now,now,old['id']))
                result = old
        else:
            counts['created'] += 1
            if apply:
                result = insert_candidate(conn, row, birth)
        if apply:
            conn.execute('INSERT INTO logs(id,candidat_id,numero_dossier,type,payload,created_at) VALUES(?,?,?,?,?,?)',
                         (str(uuid.uuid4()),result['id'],result['numero_dossier'],'IMPORT_INSCRIPTION',
                          json.dumps({'division':division,'statut':'confirmee'}),datetime.now().isoformat()))
    return counts, classes, conflicts


def register_candidate_import(app, connect, require_admin, normalize_names):
    @app.route('/admin/candidatures/importer', methods=['GET','POST'])
    def admin_candidate_import():
        if not require_admin():
            if request.method=='POST':
                abort(403)
            return redirect(url_for('login', next=request.path))
        if request.method=='GET':
            return render_template('candidate_import.html', csrf_token=_csrf_token())
        if not _equal(request.form.get('csrf_token'), session.get('_candidate_message_csrf')):
            abort(400)
        apply = request.form.get('action')=='import'
        try:
            upload = request.files.get('csv')
            raw = upload.read(2_000_001) if upload else b''
            if len(raw)>2_000_000:
                raise ValueError('Le fichier dépasse 2 Mo.')
            records = parse_roster(raw, normalize_names)
            with closing(connect()) as conn:
                conn.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
                counts, classes, conflicts = process_import(conn, records, apply)
                conn.commit()
        except (ValueError, csv.Error) as exc:
            return render_template('_candidate_import_result.html', error=str(exc)), 400
        return render_template('_candidate_import_result.html', counts=counts, classes=classes, conflicts=conflicts, applied=apply)
