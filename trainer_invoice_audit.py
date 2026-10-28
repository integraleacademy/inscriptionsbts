"""Conservative, deterministic invoice checks. AI extracts; Python reconciles.

All money is represented as integer cents. Unknowns remain unknown. A planning
match is never an authorization to pay, nor proof of the trainer's attendance.
"""
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import unicodedata


class InvoiceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalized(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ''.join(
        c for c in unicodedata.normalize('NFD', value.lower())
        if not unicodedata.combining(c))).split())


def cents(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,9}(?:\.\d{1,2})?', value):
        raise InvoiceError('Un montant extrait est invalide. Relancez l’analyse.', 422)
    try:
        return int(Decimal(value) * 100)
    except (InvalidOperation, ValueError):
        raise InvoiceError('Un montant extrait est illisible.', 422) from None


def rounded(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def extraction_schema():
    text = {'type': 'string'}
    optional = {'type': ['string', 'null']}
    line = object_schema(dict(
        description=text, subject=optional, promotions={'type': 'array', 'items': text}, kind={'type': 'string', 'enum': ['teaching', 'expense', 'discount', 'other']},
        service_date=optional, start=optional, end=optional,
        minutes={'type': ['integer', 'null']}, rate_ht=optional, rate_ttc=optional,
        amount_ht=optional, amount_ttc=optional, vat_rate=optional,
        course_ids={'type': 'array', 'items': text},
        evidence=text, confidence={'type': 'string', 'enum': ['high', 'medium', 'low']}))
    return object_schema(dict(
        document_type={'type': 'string', 'enum': ['invoice', 'credit', 'other']},
        document_count={'type': 'integer'}, number=text, issuer=text, recipient=text,
        currency=text, issue_date=optional, period_start=optional, period_end=optional,
        total_ht=optional, total_vat=optional, total_ttc=optional,
        complete_month={'type': 'boolean'}, lines={'type': 'array', 'items': line},
        summary=text, warnings={'type': 'array', 'items': text}))


def validate_extraction(value):
    """Validate again locally: a structured-output response is still untrusted."""
    if not isinstance(value, dict) or set(value) != set(extraction_schema()['properties']):
        raise InvoiceError('L’IA n’a pas renvoyé une lecture complète. Réessayez.', 422)
    if value['document_type'] not in ('invoice', 'credit', 'other') or type(value['document_count']) is not int:
        raise InvoiceError('Le type de document extrait est invalide.', 422)
    if value['document_count'] != 1:
        raise InvoiceError('Ce fichier ne contient pas une facture unique identifiable. Séparez les factures en fichiers distincts.', 422)
    for key in ('number', 'issuer', 'recipient', 'currency', 'summary'):
        if not isinstance(value[key], str) or len(value[key]) > 5000 or '\x00' in value[key]:
            raise InvoiceError('Un texte extrait est invalide.', 422)
    if type(value['complete_month']) is not bool:
        raise InvoiceError('La période extraite est invalide.', 422)
    for key in ('total_ht', 'total_vat', 'total_ttc'):
        cents(value[key])
    def day(v):
        if v is not None:
            if not isinstance(v, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
                raise InvoiceError('Une date extraite est invalide.', 422)
            try:
                date.fromisoformat(v)
            except ValueError:
                raise InvoiceError('Une date extraite est invalide.', 422) from None
    for key in ('issue_date', 'period_start', 'period_end'):
        day(value[key])
    if (not isinstance(value['warnings'], list) or len(value['warnings']) > 40
            or any(not isinstance(x, str) or len(x) > 2000 for x in value['warnings'])):
        raise InvoiceError('Les réserves de l’analyse sont illisibles.', 422)
    if not isinstance(value['lines'], list) or len(value['lines']) > 150:
        raise InvoiceError('La facture contient trop de lignes. Importez un document de 150 lignes maximum.', 422)
    expected = set(extraction_schema()['properties']['lines']['items']['properties'])
    for line in value['lines']:
        if not isinstance(line, dict) or set(line) != expected:
            raise InvoiceError('Une ligne de facture est incomplète.', 422)
        for key in ('description', 'evidence'):
            if not isinstance(line[key], str) or len(line[key]) > 3000 or '\x00' in line[key]:
                raise InvoiceError('Une ligne de facture est illisible.', 422)
        if line['kind'] not in ('teaching', 'expense', 'discount', 'other') or line['confidence'] not in ('high', 'medium', 'low'):
            raise InvoiceError('Une catégorie extraite est invalide.', 422)
        if line['subject'] is not None and (not isinstance(line['subject'], str) or len(line['subject']) > 500):
            raise InvoiceError('La matière extraite est invalide.', 422)
        if not isinstance(line['promotions'], list) or len(line['promotions']) > 20 or any(not isinstance(v, str) or len(v) > 300 for v in line['promotions']):
            raise InvoiceError('Les promotions extraites sont invalides.', 422)
        day(line['service_date'])
        for key in ('start', 'end'):
            if line[key] is not None and (not isinstance(line[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', line[key])):
                raise InvoiceError('Un horaire extrait est invalide.', 422)
        if line['minutes'] is not None and (type(line['minutes']) is not int or not -60000 <= line['minutes'] <= 60000):
            raise InvoiceError('Une durée extraite est invalide.', 422)
        for key in ('rate_ht', 'rate_ttc', 'amount_ht', 'amount_ttc', 'vat_rate'):
            cents(line[key])
        if line['vat_rate'] is not None and not 0 <= Decimal(line['vat_rate']) <= 100:
            raise InvoiceError('Un taux de TVA extrait est invalide.', 422)
        if (not isinstance(line['course_ids'], list) or len(line['course_ids']) > 300
                or any(not isinstance(x, str) or not 1 <= len(x) <= 128 for x in line['course_ids'])):
            raise InvoiceError('Les correspondances proposées sont invalides.', 422)
    return value


def snapshot(conn, trainer_id, month):
    from trainer_workload import get_trainer_workload
    workload = get_trainer_workload(conn, trainer_id, month)
    trainer = conn.execute('SELECT nom,prenom FROM trainers WHERE id=?', (trainer_id,)).fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    courses = []
    for row in workload['courses']:
        item = {key: row[key] for key in ('id', 'date', 'start', 'end', 'title', 'minutes',
                'promotions', 'is_shared', 'rate_cents', 'amount_cents', 'incomplete')}
        item.update(rollcall_at=None, journal_at=None)
        if 'teaching_rollcalls' in tables:
            record = conn.execute('SELECT completed_at FROM teaching_rollcalls WHERE course_id=? AND trainer_id=?',
                                  (row['id'], trainer_id)).fetchone()
            item['rollcall_at'] = record[0] if record else None
        if 'teaching_journals' in tables:
            record = conn.execute("SELECT updated_at FROM teaching_journals WHERE course_id=? AND trainer_id=? AND (trim(content)<>'' OR topics<>'[]')",
                                  (row['id'], trainer_id)).fetchone()
            item['journal_at'] = record[0] if record else None
        courses.append(item)
    data = dict(month=month, trainer_name=' '.join((trainer['prenom'], trainer['nom'])),
                courses=courses, minutes=workload['total_minutes'],
                expected_cents=workload['estimated_cents'] if workload['all_priced'] else None,
                unpriced_minutes=workload['unpriced_minutes'])
    data['fingerprint'] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    data['now'] = datetime.now(ZoneInfo('Europe/Paris')).strftime('%Y-%m-%dT%H:%M')
    return data


def reconcile(data, context, basis):
    """A match needs local date/time evidence; model IDs alone are suggestions."""
    issues, rows = [], []
    def issue(code, message, level='review', line=None):
        item = dict(code=code, message=message, level=level, line=line)
        issues.append(item)
        return item
    courses = {c['id']: c for c in context['courses']}
    totals = {k: cents(data[k]) for k in ('total_ht', 'total_vat', 'total_ttc')}
    if data['document_type'] != 'invoice':
        issue('document_type', 'Avoir ou document autre qu’une facture : traitement manuel nécessaire.')
    if data['currency'].strip().upper() not in ('EUR', '€'):
        issue('currency', 'La devise euro n’est pas établie : les montants ne sont pas comparables.', 'error')
    if not data['number'].strip():
        issue('number', 'Numéro de facture non identifié.')
    if not data['issuer'].strip():
        issue('issuer', 'Émetteur de la facture non identifié.')
    else:
        names = normalized(context['trainer_name']).split()
        if not names or not all(n in normalized(data['issuer']).split() for n in names):
            issue('issuer', 'L’émetteur ne reprend pas le nom complet du formateur. Vérifiez le lien avec sa société.')
    if 'integrale' not in normalized(data['recipient']).split():
        issue('recipient', 'Destinataire à vérifier : Intégrale n’est pas clairement identifié.')
    if not data['issue_date']:
        issue('issue_date', 'Date d’émission non identifiée.')
    if data['period_start'] and data['period_end'] and data['period_start'] > data['period_end']:
        issue('period_order', 'La période de prestation est incohérente.', 'error')
    for key in ('period_start', 'period_end'):
        if data[key] and data[key][:7] != context['month']:
            issue('period', 'La période facturée dépasse le mois sélectionné.', 'error')
            break
    if all(v is not None for v in totals.values()):
        if abs(totals['total_ht'] + totals['total_vat'] - totals['total_ttc']) > 2:
            issue('vat_total', 'Le total HT + la TVA ne correspond pas au total TTC.', 'error')
    else:
        issue('totals_missing', 'Total HT, TVA ou TTC manquant : vérification arithmétique incomplète.')
    if any(v is not None and v < 0 for v in totals.values()):
        issue('credit', 'Montant négatif : vérifiez l’avoir ou la correction associée.')
    if context['unpriced_minutes']:
        issue('missing_rates', 'Des séances du mois n’ont pas de tarif applicable. Aucun total théorique complet ne peut être établi.')
    if not data['lines']:
        issue('no_lines', 'Aucune ligne de prestation exploitable : comparaison impossible.')
    for warning in data['warnings']:
        issue('ai_warning', warning)
    used = Counter()
    taught_minutes = 0
    hours_complete = True
    billed_teaching, expenses = 0, 0
    money_complete = True
    for number, line in enumerate(data['lines'], 1):
        before = len(issues)
        def flag(code, message, level='review'):
            return issue(code, message, level, number)
        amounts = {k: cents(line[k]) for k in ('rate_ht', 'rate_ttc', 'amount_ht', 'amount_ttc')}
        for base in ('ht', 'ttc'):
            if line['minutes'] is not None and amounts['rate_'+base] is not None and amounts['amount_'+base] is not None:
                expected = rounded(Decimal(line['minutes']) * amounts['rate_'+base] / 60)
                if abs(expected - amounts['amount_'+base]) > 2:
                    flag('line_math', 'Durée × tarif ne correspond pas au montant '+base.upper()+'.', 'error')
        if line['vat_rate'] is not None and amounts['amount_ht'] is not None and amounts['amount_ttc'] is not None:
            expected = rounded(Decimal(amounts['amount_ht']) * (1 + Decimal(line['vat_rate']) / 100))
            if abs(expected - amounts['amount_ttc']) > 2:
                flag('line_vat', 'Le montant TTC ne correspond pas au HT et au taux de TVA indiqués.', 'error')
        if line['confidence'] != 'high' or not line['evidence'].strip():
            flag('readability', 'Lecture du document à confirmer sur l’original.')
        selected, exact = [], False
        if line['kind'] == 'teaching':
            if line['minutes'] is None:
                hours_complete = False
                flag('hours_missing', 'Durée facturée non précisée : aucun nombre d’heures n’est inventé.')
            elif line['minutes'] <= 0:
                flag('nonpositive_hours', 'Durée nulle ou négative : vérifiez la correction ou l’avoir.')
                taught_minutes += line['minutes']
            else:
                taught_minutes += line['minutes']
            if amounts['amount_'+basis] is None:
                money_complete = False
                flag('amount_missing', 'Montant '+basis.upper()+' de la prestation non établi.')
            else:
                billed_teaching += amounts['amount_'+basis]
            if line['service_date'] and line['service_date'][:7] != context['month']:
                flag('outside_month', 'Cette prestation est datée en dehors du mois contrôlé.', 'error')
            candidates = [c for c in courses.values() if c['date'] == line['service_date']]
            if line['service_date'] and line['start'] and line['end']:
                candidates = [c for c in candidates if c['start'] == line['start'] and c['end'] == line['end']]
                if len(candidates) == 1:
                    selected, exact = candidates, True
                else:
                    flag('not_planned', 'Aucune séance unique à cette date et à ces horaires dans le planning actuel.', 'error')
            elif line['service_date'] and len(candidates) == 1:
                selected = candidates
                flag('missing_times', 'Rapprochement par date seulement : horaires non précisés sur la facture.')
            else:
                proposed = list(dict.fromkeys(line['course_ids']))
                valid = [courses[cid] for cid in proposed if cid in courses and
                         (not line['service_date'] or courses[cid]['date'] == line['service_date'])]
                if proposed and len(valid) == len(proposed):
                    selected = valid
                    flag('suggested_match', 'Rapprochement proposé par l’IA, à confirmer : détail daté ou horaires insuffisants.')
                else:
                    flag('unmatched', 'Prestation non rapprochée d’une séance du mois. Demandez un détail daté.')
            if selected:
                planned = sum(c['minutes'] for c in selected)
                if context.get('now') and any(c['date']+'T'+c['end'] > context['now'] for c in selected):
                    flag('future_course', 'Certaines séances facturées ne sont pas encore terminées à la date du contrôle.')
                if line['subject']:
                    subject = normalized(line['subject'])
                    if any(subject not in normalized(c['title']) and normalized(c['title']) not in subject for c in selected):
                        flag('subject', 'L’intitulé de matière diffère du planning : vérifiez les abréviations et la prestation facturée.')
                for promotion in line['promotions']:
                    name = normalized(promotion)
                    if not any(name in normalized(p) or normalized(p) in name for c in selected for p in c['promotions']):
                        flag('promotion', 'Une promotion mentionnée sur la facture n’est pas identifiée dans les séances rapprochées : '+promotion+'.')
                if line['minutes'] is not None and line['minutes'] != planned:
                    flag('duration', 'Durée facturée différente de la durée des séances rapprochées.', 'error' if exact else 'review')
                if line['minutes'] is not None and line['minutes'] > 0:
                    used.update(c['id'] for c in selected)
                if any(c['incomplete'] for c in selected):
                    flag('incomplete_planning', 'Au moins une séance est incomplète dans le planning.')
                if any(not c['rollcall_at'] and not c['journal_at'] for c in selected):
                    flag('delivery_unconfirmed', 'Ni appel finalisé ni cahier de texte renseigné pour certaines séances. Réalisation à confirmer, sans conclure à une absence.')
                rates = {c['rate_cents'] for c in selected}
                if None not in rates:
                    theoretical = rounded(sum(Decimal(c['minutes']) * c['rate_cents'] / 60 for c in selected))
                    if amounts['amount_'+basis] is not None and abs(amounts['amount_'+basis] - theoretical) > 2:
                        flag('planned_amount', 'Le montant '+basis.upper()+' diffère du montant prévu pour ces séances, sur la base tarifaire sélectionnée.', 'error' if exact else 'review')
                    if len(rates) == 1 and amounts['rate_'+basis] is not None and amounts['rate_'+basis] not in rates:
                        flag('rate', 'Tarif horaire différent de celui applicable à la date du cours.', 'error' if exact else 'review')
                else:
                    theoretical = None
                    flag('rate_missing', 'Tarif applicable manquant pour une séance rapprochée.')
            else:
                planned, theoretical = None, None
        else:
            planned, theoretical = None, None
            if amounts['amount_'+basis] is not None:
                expenses += amounts['amount_'+basis]
            flag('non_teaching', 'Frais, remise ou autre poste : exclu du rapprochement des heures et à valider séparément.')
        rows.append(dict(number=number, description=line['description'], kind=line['kind'],
                         evidence=line['evidence'], minutes=line['minutes'], planned_minutes=planned,
                         amount_cents=amounts['amount_'+basis], expected_cents=theoretical,
                         courses=selected, exact_match=exact, issues=issues[before:]))
    for cid, count in used.items():
        if count > 1:
            issue('duplicate_session', 'La séance du '+courses[cid]['date']+' '+courses[cid]['start']+' apparaît dans plusieurs lignes. Un cours commun ne se facture pas une fois par promotion.', 'error')
    for base in ('ht', 'ttc'):
        values = [cents(line['amount_'+base]) for line in data['lines']]
        if values and all(v is not None for v in values) and totals['total_'+base] is not None:
            if abs(sum(values) - totals['total_'+base]) > 2:
                issue('sum_lines', 'La somme des lignes '+base.upper()+' ne correspond pas au total de la facture (vérifiez remises et frais).', 'error')
    if hours_complete and taught_minutes > context['minutes']:
        issue('excess_hours', 'Les heures de cette facture dépassent le total des heures planifiées du mois.', 'error')
    if data['complete_month'] and hours_complete and taught_minutes != context['minutes']:
        issue('complete_month', 'La facture annonce le mois complet, mais son volume ne correspond pas au planning.', 'error')
    if not data['period_start'] and not data['period_end'] and any(not l['service_date'] for l in data['lines'] if l['kind'] == 'teaching'):
        issue('period_missing', 'Période de prestation insuffisamment précisée.')
    if not any(l['kind'] == 'teaching' for l in data['lines']):
        issue('no_teaching', 'Aucune ligne d’heures de cours identifiée.')
    status = 'ecarts' if any(i['level'] == 'error' for i in issues) else ('a_verifier' if issues else 'coherent')
    return dict(status=status, issues=issues, lines=rows, totals=totals,
                teaching_minutes=taught_minutes if hours_complete else None,
                teaching_cents=billed_teaching if money_complete and data['currency'].strip().upper() in ('EUR', '€') else None,
                extra_cents=expenses, course_ids=sorted(used), basis=basis,
                notice='Contrôle du planning uniquement : ni preuve de présence du formateur, ni validation de paiement.')


def aggregate(invoices, context):
    analyzed = [item for item in invoices if item.get('report') and not item.get('archived')]
    issues, seen_refs, seen_courses = [], {}, {}
    def add(message, level='review'):
        issues.append(dict(message=message, level=level))
    for item in analyzed:
        data, report = item['extraction'], item['report']
        ref = normalized(data['number']).replace(' ', '')
        if ref:
            if ref in seen_refs:
                add('Numéro de facture répété : '+data['number']+'. Vérifiez le doublon entre fichiers.', 'error')
            seen_refs[ref] = item['id']
        if data['document_type'] != 'invoice':
            add('Un avoir ou un autre document figure dans le lot : les totaux nécessitent une validation manuelle.')
        for cid in report['course_ids']:
            if cid in seen_courses:
                add('Une même séance apparaît dans plusieurs factures : '+next(c['date']+' '+c['start'] for c in context['courses'] if c['id']==cid)+'.', 'error')
            seen_courses[cid] = item['id']
    pending = sum(1 for item in invoices if not item.get('archived') and not item.get('report'))
    if pending:
        add(f'{pending} facture(s) non analysée(s) : bilan incomplet.')
    regular_invoices = all(i['extraction']['document_type'] == 'invoice' for i in analyzed)
    minutes = sum(i['report']['teaching_minutes'] for i in analyzed) if analyzed and regular_invoices and all(i['report']['teaching_minutes'] is not None for i in analyzed) else None
    bases = {i['basis'] for i in analyzed}
    amount = sum(i['report']['teaching_cents'] for i in analyzed) if analyzed and regular_invoices and len(bases)==1 and all(i['report']['teaching_cents'] is not None for i in analyzed) else None
    if len(bases)>1:
        add('Les factures ne sont pas rapprochées sur la même base HT/TTC : comparaison des montants désactivée.')
    if minutes is not None:
        if minutes > context['minutes']:
            add('Le cumul facturé dépasse les heures du planning mensuel.', 'error')
        elif minutes < context['minutes']:
            add('Facturation partielle ou heures encore non rapprochées. Ce n’est pas nécessairement une erreur.')
    return dict(analyzed_count=len(analyzed), pending_count=pending, teaching_minutes=minutes,
                planned_minutes=context['minutes'], teaching_cents=amount,
                expected_cents=context['expected_cents'], basis=next(iter(bases)) if len(bases)==1 else None,
                difference_cents=amount-context['expected_cents'] if amount is not None and context['expected_cents'] is not None else None,
                issues=issues, unmatched_courses=[c for c in context['courses'] if c['id'] not in seen_courses])
