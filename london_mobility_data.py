"""Resolve London documents and recipients from the student's authoritative records.

Never use the old, manually entered London employer fields or an unrelated
contract. The same resolver is used for the preview, the click and activation.
"""
from datetime import datetime
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo


def mobile(value):
    value = str(value or '').strip()
    if re.search(r'[^\d\s+()./-]', value):
        raise ValueError('Renseignez un numéro de mobile valide.')
    value = re.sub(r'[\s()./-]', '', value)
    if value.startswith('00'): value = '+' + value[2:]
    if re.fullmatch(r'0[67]\d{8}', value): value = '+33' + value[1:]
    if value.startswith('+330'): value = '+33' + value[4:]
    if not re.fullmatch(r'\+[1-9]\d{7,14}', value):
        raise ValueError('Renseignez un mobile avec son indicatif international.')
    if value.startswith('+33') and not re.fullmatch(r'\+33[67]\d{8}', value):
        raise ValueError('Un mobile français commençant par 06 ou 07 est nécessaire pour le code SMS.')
    return value


def contact_name(value):
    words = re.sub(r'^(?:M\.?|Mme|Madame|Monsieur)\s+', '', str(value or '').strip(), flags=re.I).split()
    if len(words) < 2: return '', ''
    # The company form accepts a full name; also recognise NOM Prénom.
    upper = [i for i, word in enumerate(words) if word.isupper()]
    if upper and len(upper) < len(words) and upper == list(range(len(upper))):
        return ' '.join(words[len(upper):]), ' '.join(words[:len(upper)])
    return words[0], ' '.join(words[1:])


def automatic_data(conn, row, *, convention_date=None):
    from london_mobility import contracts, current_settings, digest, snapshot, validate
    row = dict(row)
    cid = row['id']; issues = []
    student_url = '/admin/candidat/' + quote(cid, safe='') + '#informations'
    contract_url = '/admin/candidat/' + quote(cid, safe='') + '#contrat-apprentissage'
    company_url = '/admin/entreprises'
    def issue(message, url, label):
        if message not in [i['message'] for i in issues]:
            issues.append(dict(message=message, url=url, label=label))
    saved, _, _, _, _ = current_settings(conn, row)
    values = {key: saved[key] for key in ('mobility_start','mobility_end','mobility_cost')}
    values['convention_date'] = convention_date or datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    company = {}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'companies','company_students'} <= tables:
        found = conn.execute('''SELECT e.*,s.start_date AS link_start,s.end_date AS link_end
            FROM companies e JOIN company_students s ON s.company_id=e.id WHERE s.candidate_id=?''', (cid,)).fetchone()
        if found:
            company = dict(found)
            company_url += '/' + quote(company['id'], safe='')
            if not company.get('active', True):
                issue('L’entreprise rattachée est désactivée.', company_url, 'Ouvrir l’entreprise')
            if (company.get('link_start') or '') > values['mobility_start'] or (company.get('link_end') and company['link_end'] < values['mobility_end']):
                issue('Le rattachement à l’entreprise ne couvre pas les dates du séjour.', company_url, 'Vérifier le rattachement')
    linked = contracts(conn, cid)
    eligible = [c for c in linked if (not c.get('contract_start') or c['contract_start'] <= values['mobility_start'])
                and (not c.get('contract_end') or c['contract_end'] >= values['mobility_end'])]
    if company.get('siret'):
        eligible = [c for c in eligible if c.get('employer_siret') == company['siret']]
    selected = eligible[0] if len(eligible) == 1 else None
    if len(eligible) > 1:
        issue('Plusieurs contrats correspondent au séjour. Vérifiez les contrats rattachés.', contract_url, 'Ouvrir les contrats')
    elif linked and not eligible:
        issue('Aucun contrat rattaché ne correspond à l’entreprise et aux dates du séjour.', contract_url, 'Ouvrir les contrats')
    contract = selected or {}
    values.update(contract_id=contract.get('id', ''),
                  employer_name=company.get('legal_name') or company.get('name') or contract.get('employer_name',''),
                  employer_siret=company.get('siret') or contract.get('employer_siret',''),
                  employer_address=company.get('address') or contract.get('employer_address',''),
                  employer_postcode=company.get('postal_code') or contract.get('employer_postcode',''),
                  employer_city=company.get('city') or contract.get('employer_city',''),
                  guardian_first_name=row.get('resp_prenom') or '', guardian_last_name=row.get('resp_nom') or '')
    for key, label in (('employer_name','raison sociale'),('employer_siret','SIRET'),('employer_address','adresse'),('employer_postcode','code postal'),('employer_city','ville')):
        if not values[key]: issue('Entreprise : ' + label + ' à compléter.', company_url, 'Ouvrir l’entreprise')
    for key, label in (('prenom','prénom'),('nom','nom'),('date_naissance','date de naissance')):
        if not row.get(key): issue('Étudiant : ' + label + ' à compléter.', student_url, 'Ouvrir les informations')
    first, last = contact_name(company.get('contact'))
    people = [dict(role='employer',label='Entreprise',first_name=first,last_name=last,
                   email=company.get('email') or contract.get('employer_email') or '',
                   phone_number=company.get('phone') or contract.get('employer_phone') or '',source_url=company_url),
              dict(role='apprentice',label='Étudiant',first_name=row.get('prenom') or '',last_name=row.get('nom') or '',
                   email=row.get('email') or contract.get('apprentice_email') or '',
                   phone_number=row.get('tel') or contract.get('apprentice_phone') or '',source_url=student_url)]
    data = snapshot(row, values, selected)
    try:
        from london_mobility_documents import minor_at_signing
        if minor_at_signing(data):
            people.append(dict(role='guardian',label='Représentant légal',first_name=values['guardian_first_name'],
                               last_name=values['guardian_last_name'],email=row.get('resp_email') or '',
                               phone_number=row.get('resp_tel') or '',source_url=student_url))
    except ValueError:
        issue('Étudiant : date de naissance à vérifier.', student_url, 'Ouvrir les informations')
    for person in people:
        person['email'] = str(person['email']).strip()
        if not person['first_name'] or not person['last_name']:
            issue(person['label'] + ' : prénom et nom du signataire à compléter.', person['source_url'], 'Ouvrir la fiche')
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', person['email']) or len(person['email']) > 254:
            issue(person['label'] + ' : e-mail d’invitation à vérifier.', person['source_url'], 'Ouvrir la fiche')
        try: person['phone_number'] = mobile(person['phone_number'])
        except ValueError:
            issue(person['label'] + ' : mobile pour le code SMS à compléter ou corriger.', person['source_url'], 'Ouvrir la fiche')
    if len({p['email'].casefold() for p in people}) != len(people):
        issue('Chaque signataire doit avoir son propre e-mail d’invitation.', student_url, 'Vérifier les coordonnées')
    if len({p['phone_number'] for p in people}) != len(people):
        issue('Chaque signataire doit avoir son propre mobile pour le code SMS.', student_url, 'Vérifier les coordonnées')
    if row.get('mode') != 'presentiel': issue('Ce séjour est réservé aux étudiants en présentiel.', student_url, 'Ouvrir les informations')
    trip = conn.execute('SELECT statut FROM voyage_londres_inscriptions WHERE candidat_id=?',(cid,)).fetchone()
    if trip and trip['statut'] != 'active':
        issue('L’inscription au voyage est annulée.', '/admin/voyage-londres?student=' + quote(cid,safe=''), 'Ouvrir le voyage')
    try:
        clean = validate(values, row, selected, complete=True)
        values = clean; data = snapshot(row, clean, selected)
    except ValueError as error:
        if not issues: issue(str(error), contract_url, 'Vérifier la fiche et le contrat')
    return dict(values=values,snapshot=data,recipients=people,issues=issues,ready=not issues,
                fingerprint=digest({'snapshot':data,'recipients':people}),company_url=company_url,
                company_source='Fiche entreprise' if company else 'Contrat d’apprentissage')
