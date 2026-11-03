"""Reconcile AKTO's invoice list with its separate pedagogical and expense totals."""
from decimal import Decimal
from datetime import datetime
import re


def number(text):
    cleaned=re.sub(r'[\s€]', '', text)
    if ',' in cleaned:
        cleaned=cleaned.replace('.', '').replace(',', '.')
    return Decimal(cleaned)


def as_cents(value):
    return int(100*Decimal(str(value)))


def funding_lines(body):
    detail=body.split('Masquer le détail',1)[-1].split('Factures & Remboursements',1)[0]
    rows=[]
    for block in re.split(r'(?m)^Nature\s*\n',detail)[1:]:
        line={'name':block.splitlines()[0].strip()}
        for key,label in [('amount','Accordé'),('billed','Montant facturé'),('paid','Payé'),('balance','Solde')]:
            m=re.search(r'(?m)^'+label+r' \(HT\)\s*\n([^\n]+)',block)
            if not m:
                return []
            line[key]=float(number(m[1]))
        rows.append(line)
    return rows


def reconcile(record):
    dues=record.get('schedules',[])
    lines=record.get('funding_lines',[])
    if not dues or not lines:
        return
    cp=[r for r in lines if r['name'].casefold()=='montant cp']
    total=sum(as_cents(d['montantTotal']) for d in dues)
    if not cp or total<=0 or sum(as_cents(r['amount']) for r in cp)!=total:
        return
    paid=sum(as_cents(r['paid']) for r in cp)
    receipts=record.get('invoices',[])
    if any(as_cents(r['paid'])<0 for r in lines) or sum(as_cents(r['paid']) for r in lines)!=as_cents(record['paid']):
        return
    if (record.get('invoices_complete') and all(r['billed']==r['paid'] for r in lines)
            and sum(as_cents(i['amount']) for i in receipts)==as_cents(record['paid'])
            and all(i['status'].casefold() in ('payé','payée') and i.get('single_dossier') and i.get('no_credit') for i in receipts)):
        for d in dues:
            d['montantEnCoursInstruction']=0
        record['pending']=0
    if paid==0 or paid==total:
        for d in dues:
            d['montantRegle']=d['montantTotal'] if paid else 0
        return
    # Only reconcile full installments. Never spread a partial, shared or
    # ambiguous payment among installments or charge an expense to tuition.
    if not record.get('invoices_complete'):
        return
    settled=[i for i in receipts if i['status'].casefold() in ('payé','payée')]
    if not settled or any(not i.get('single_dossier') or not i.get('payment_date') or not i.get('no_credit') for i in settled):
        return
    gross=as_cents(record['paid'])
    if sum(as_cents(i['amount']) for i in settled)!=gross:
        return
    fees=gross-paid
    if fees<0 or len(settled)>20:
        return
    # Consider both an invoice with the known expense total bundled in it
    # and a separate expense-only invoice. Require a unique global match.
    solutions=[]
    budget=10000
    def match(n,used,fee_left,links):
        nonlocal budget
        budget-=1
        if budget<0 or len(solutions)>1:
            return
        if n==len(settled):
            if fee_left==0 and sum(as_cents(dues[j]['montantTotal']) for j in used)==paid:
                solutions.append(dict(links))
            return
        inv=settled[n]
        when=datetime.strptime(inv['issued'],'%d/%m/%Y').date().isoformat()
        amt=as_cents(inv['amount'])
        if amt<=0:
            return
        if amt==fee_left:
            match(n+1,used,0,links)
        for j,d in enumerate(dues):
            if j in used or d['dateOuverture']>when:
                continue
            diff=amt-as_cents(d['montantTotal'])
            if diff==0 or diff==fee_left:
                match(n+1,used|{j},fee_left-diff,{**links,j:inv})
    match(0,set(),fees,{})
    if len(solutions)!=1 or budget<0:
        return
    mapping=solutions[0]
    for j,d in enumerate(dues):
        d['montantRegle']=d['montantTotal'] if j in mapping else 0
        if j in mapping:
            d['invoice_ref']=mapping[j]['ref']
            d['paid_on']=mapping[j]['payment_date']
