from akto_payments import reconcile


def example():
    dues=[{'montantTotal':v,'dateOuverture':d} for v,d in [(100,'2025-09-01'),(80,'2026-03-01'),(80,'2027-03-01')]]
    lines=[dict(name='Montant CP',amount=260,billed=180,paid=180),dict(name='Équipement',amount=20,billed=20,paid=20)]
    bills=[dict(kind='Facture',ref=str(i),issued=d,payment_date=d,status='Payé',no_credit=True,single_dossier=True,amount=v) for i,(v,d) in enumerate([(120,'03/09/2025'),(80,'03/03/2026')])]
    return dict(schedules=dues,funding_lines=lines,invoices=bills,invoices_complete=True,paid='200')


def test_several_receipts_and_bundled_expense():
    r=example();reconcile(r)
    assert [d['montantRegle'] for d in r['schedules']]==[100,80,0]
    assert r['schedules'][0]['invoice_ref']=='0' and r['pending']==0


def test_ambiguous_or_shared_invoices_are_not_allocated():
    for condition in ('shared','ambiguous','credit','missing'):
        r=example()
        if condition=='shared': r['invoices'][0]['single_dossier']=False
        if condition=='ambiguous': r['schedules'][2]['dateOuverture']='2026-03-01'
        if condition=='credit': r['invoices'][0]['no_credit']=False
        if condition=='missing': r['invoices_complete']=False
        reconcile(r)
        assert all('montantRegle' not in d for d in r['schedules'])
