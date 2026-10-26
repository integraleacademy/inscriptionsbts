"""Administrative dossier creation, independent of the public admission window."""
from contextlib import closing
from datetime import date, datetime
import re
import uuid

from flask import abort, flash, redirect, render_template, request, session, url_for

from campaign import ADMISSION_YEAR
from candidate_messages import _csrf_token, _equal
from promotions import BTS_LABELS, assign_candidate_promotion, list_promotions
from utils import dossier_number


def register_candidate_creation(app, connect, require_admin, normalize_names, log_event):
    @app.route('/admin/candidat/ajouter', methods=['GET', 'POST'])
    def admin_candidate_create():
        if not require_admin():
            if request.method == 'POST':
                abort(403)
            return redirect(url_for('login', next=request.path))
        with closing(connect()) as conn:
            promotions = list_promotions(conn, active_only=True)
        years = sorted({2026, ADMISSION_YEAR, *(p['rentree_annee'] for p in promotions)}, reverse=True)
        values = dict(nom='', prenom='', email='', tel='', date_naissance='', bts='', mode='presentiel',
                      rentree_annee=request.args.get('rentree', str(ADMISSION_YEAR)),
                      statut='preinscription', promotion_id='', commentaires='')
        if values['rentree_annee'] not in {str(year) for year in years}:
            values['rentree_annee'] = str(ADMISSION_YEAR)
        if request.args.get('bts') in BTS_LABELS:
            values['bts'] = request.args['bts']
        error, duplicate = '', None
        if request.method == 'POST':
            if not _equal(request.form.get('csrf_token'), session.get('_candidate_message_csrf')):
                abort(400, description='La session a expiré. Rechargez le formulaire.')
            values = {key: request.form.get(key, '').strip() for key in values}
            normalize_names(values)
            values['email'] = values['email'].lower()
            values['tel'] = re.sub(r'[\s.()-]', '', values['tel'])
            if values['tel'].startswith('+33'):
                values['tel'] = '0' + values['tel'][3:]
            if any(not values[key] or len(values[key]) > 100 for key in ('nom', 'prenom')):
                error = 'Renseignez le nom et le prénom (100 caractères maximum chacun).'
            elif len(values['email']) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
                error = 'Renseignez une adresse e-mail valide.'
            elif values['tel'] and not re.fullmatch(r'0[1-9]\d{8}', values['tel']):
                error = 'Vérifiez le téléphone : 10 chiffres, ou un numéro commençant par +33.'
            elif values['bts'] not in BTS_LABELS or values['mode'] not in ('presentiel', 'distanciel'):
                error = 'Choisissez le BTS et son mode de suivi.'
            elif values['rentree_annee'] not in {str(year) for year in years}:
                error = 'Choisissez une rentrée proposée dans la liste.'
            elif values['statut'] not in ('preinscription', 'validee', 'confirmee'):
                error = 'Choisissez un statut proposé dans la liste.'
            elif len(values['commentaires']) > 5000:
                error = 'Limitez la note interne à 5 000 caractères.'
            birth = None
            if not error and values['date_naissance']:
                try:
                    birth = date.fromisoformat(values['date_naissance'])
                    if not date(1900, 1, 1) <= birth <= date.today():
                        raise ValueError
                except ValueError:
                    error = 'Vérifiez la date de naissance.'
            if not error:
                with closing(connect()) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    duplicate = conn.execute('SELECT id FROM candidats WHERE lower(trim(email))=? AND rentree_annee=? LIMIT 1',
                                             (values['email'], int(values['rentree_annee']))).fetchone()
                    if duplicate:
                        error = 'Un dossier utilise déjà cet e-mail pour cette rentrée. Ouvrez sa fiche pour le compléter.'
                    else:
                        now = datetime.now()
                        counter = conn.execute('SELECT COUNT(*) FROM candidats WHERE date(created_at)=?', (now.date().isoformat(),)).fetchone()[0] + 1
                        number = dossier_number(now, counter, int(values['rentree_annee']))
                        while conn.execute('SELECT 1 FROM candidats WHERE numero_dossier=?', (number,)).fetchone():
                            counter += 1
                            number = dossier_number(now, counter, int(values['rentree_annee']))
                        row = {key: value for key, value in values.items() if key != 'promotion_id'}
                        row.update(id=str(uuid.uuid4()), numero_dossier=number, rentree_annee=int(values['rentree_annee']),
                                   created_at=now.isoformat(), updated_at=now.isoformat(), slug_public=uuid.uuid4().hex,
                                   est_mineur=int(now.year - birth.year - ((now.month, now.day) < (birth.month, birth.day)) < 18) if birth else 0,
                                   verif_docs='{}', replace_meta='{}', nouveau_doc=0)
                        for key in ('ci', 'photo', 'carte_vitale', 'cv', 'lm'):
                            row['fichiers_' + key] = '[]'
                        if row['statut'] in ('validee', 'confirmee'):
                            row['date_' + row['statut']] = now.isoformat()
                        conn.execute('INSERT INTO candidats (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
                        try:
                            if values['promotion_id']:
                                assign_candidate_promotion(conn, row['id'], values['promotion_id'])
                            conn.commit()
                        except ValueError as exc:
                            conn.rollback()
                            error = str(exc)
                if not error:
                    log_event(row, 'CREATION_MANUELLE', {'statut': row['statut'], 'promotion_id': values['promotion_id']})
                    flash('Étudiant ajouté. Vous pouvez maintenant compléter sa fiche.', 'success')
                    return redirect(url_for('admin_candidate_sheet', cid=row['id'], rentree=row['rentree_annee']), code=303)
        response = app.make_response((render_template('candidate_create.html', title='Ajouter un étudiant · Intégrale Academy',
                                      values=values, years=years, diplomas=BTS_LABELS, promotions=promotions,
                                      error=error, duplicate=duplicate, csrf_token=_csrf_token()), 400 if error else 200))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
