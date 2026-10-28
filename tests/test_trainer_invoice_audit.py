"""Arithmetic/matching must not trust AI conclusions or hide missing evidence."""
from copy import deepcopy
from pathlib import Path

import pytest

from trainer_invoice_audit import InvoiceError, aggregate, cents, reconcile, validate_extraction


def context():
    return dict(month='2026-10', trainer_name='Camille Martin', minutes=120,
                expected_cents=9000, unpriced_minutes=0, now='2026-11-01T10:00',
                courses=[dict(id='c1', date='2026-10-05', start='08:00', end='10:00',
                title='Anglais', minutes=120, promotions=['BTS CI 1', 'BTS PI 1'],
                is_shared=True, rate_cents=4500, amount_cents=9000, incomplete=False,
                rollcall_at='2026-10-05T09:00', journal_at=None)])


def extraction():
    return dict(document_type='invoice', document_count=1, number='F-001', issuer='Camille MARTIN',
        recipient='Intégrale Academy', currency='EUR', issue_date='2026-11-01',
        period_start='2026-10-01', period_end='2026-10-31', total_ht='90.00', total_vat='18.00',
        total_ttc='108.00', complete_month=True, summary='Une séance de deux heures.', warnings=[],
        lines=[dict(description='Anglais du 05/10', subject='Anglais', promotions=['BTS CI 1', 'BTS PI 1'],
                    kind='teaching', service_date='2026-10-05', start='08:00', end='10:00',
                    minutes=120, rate_ht='45.00', rate_ttc='54.00', amount_ht='90.00', amount_ttc='108.00',
                    vat_rate='20.00', course_ids=['c1'], evidence='Page 1 : 05/10, 08:00–10:00, 2 h × 45 € HT.', confidence='high')])


def codes(report):
    return {i['code'] for i in report['issues']}


def item(identity='i1', data=None, ctx=None, basis='ht', archived=False):
    data, ctx = data or extraction(), ctx or context()
    return dict(id=identity, extraction=data, report=reconcile(data,ctx,basis), basis=basis, archived=archived)


def test_exact_shared_lesson_counted_once_and_next_month_issue_date_valid():
    data = validate_extraction(extraction())
    report = reconcile(data, context(), 'ht')
    assert report['status'] == 'coherent'
    assert report['teaching_minutes'] == 120
    assert report['teaching_cents'] == 9000
    assert report['course_ids'] == ['c1']
    assert report['lines'][0]['exact_match']
    assert 'validation de paiement' in report['notice']


def test_ttc_basis_uses_explicitly_selected_rate_basis():
    ctx = context(); ctx['courses'][0]['rate_cents'] = 5400; ctx['expected_cents'] = 10800
    assert reconcile(extraction(),ctx,'ttc')['status'] == 'coherent'
    assert 'rate' in codes(reconcile(extraction(),context(),'ttc'))


def test_same_shared_session_cannot_be_billed_once_per_promotion():
    data = extraction(); data['lines'].append(deepcopy(data['lines'][0]))
    data.update(total_ht='180.00',total_vat='36.00',total_ttc='216.00')
    report = reconcile(data,context(),'ht')
    assert {'duplicate_session','excess_hours'} <= codes(report)
    assert report['status']=='ecarts'


def test_missing_amount_and_hours_never_become_zero():
    data = extraction(); data['lines'][0].update(minutes=None,amount_ht=None)
    report = reconcile(data,context(),'ht')
    assert report['teaching_minutes'] is None and report['teaching_cents'] is None
    assert {'hours_missing','amount_missing'} <= codes(report)
    total = aggregate([item(data=data)],context())
    assert total['teaching_minutes'] is None and total['difference_cents'] is None


def test_missing_rate_is_not_free_teaching():
    ctx = context(); ctx.update(expected_cents=None,unpriced_minutes=120)
    ctx['courses'][0].update(rate_cents=None,amount_cents=None)
    report = reconcile(extraction(),ctx,'ht')
    assert {'missing_rates','rate_missing'} <= codes(report)
    assert report['lines'][0]['expected_cents'] is None


def test_changed_or_deleted_planning_is_rechecked():
    ctx = context(); ctx['courses'][0]['rate_cents']=5000
    assert {'rate','planned_amount'} <= codes(reconcile(extraction(),ctx,'ht'))
    ctx.update(courses=[],minutes=0,expected_cents=0)
    report = reconcile(extraction(),ctx,'ht')
    assert 'not_planned' in codes(report) and report['course_ids']==[]


def test_no_delivery_proof_is_not_inferred_from_a_past_date():
    ctx = context(); ctx['courses'][0].update(rollcall_at=None,journal_at=None)
    report = reconcile(extraction(),ctx,'ht')
    assert 'delivery_unconfirmed' in codes(report)
    assert report['status']=='a_verifier'


def test_future_courses_need_review_even_with_a_journal():
    ctx = context(); ctx['now']='2026-10-05T09:00'
    assert 'future_course' in codes(reconcile(extraction(),ctx,'ht'))


def test_subject_and_promotions_not_silently_ignored():
    data = extraction(); data['lines'][0].update(subject='Économie',promotions=['BTS MCO 2'])
    assert {'subject','promotion'} <= codes(reconcile(data,context(),'ht'))


def test_ai_ids_alone_are_never_exact_proof():
    data = extraction(); data['lines'][0].update(service_date=None,start=None,end=None)
    report = reconcile(data,context(),'ht')
    assert not report['lines'][0]['exact_match']
    assert 'suggested_match' in codes(report) and report['status']=='a_verifier'
    data['lines'][0]['course_ids']=['invented-id']
    assert reconcile(data,context(),'ht')['course_ids']==[]


def test_wrong_date_must_not_reuse_ai_proposed_course():
    data = extraction(); data['lines'][0]['service_date']='2026-09-05'
    report = reconcile(data,context(),'ht')
    assert {'outside_month','not_planned'} <= codes(report)
    assert report['course_ids']==[]


def test_money_arithmetic_and_vat_are_checked_independently():
    data=extraction(); data['total_ttc']='999.00'; data['lines'][0]['amount_ht']='91.00'
    assert {'vat_total','line_math','line_vat','sum_lines'} <= codes(reconcile(data,context(),'ht'))


def test_two_cent_rounding_tolerance_and_integer_decimal_math():
    assert cents('0.29')==29
    data=extraction(); data['total_ttc']='108.02'
    assert 'vat_total' not in codes(reconcile(data,context(),'ht'))
    data['total_ttc']='108.03'
    assert 'vat_total' in codes(reconcile(data,context(),'ht'))


def test_non_eur_amounts_are_not_summed_as_euros():
    data=extraction(); data['currency']='USD'
    row=item(data=data)
    assert 'currency' in codes(row['report'])
    assert row['report']['teaching_cents'] is None
    assert aggregate([row],context())['teaching_cents'] is None


def test_credits_do_not_silently_increase_monthly_totals():
    data=extraction(); data['document_type']='credit'
    total=aggregate([item(data=data)],context())
    assert total['teaching_minutes'] is None and total['teaching_cents'] is None


def test_additional_fees_do_not_increase_teaching_hours_or_cost():
    data=extraction(); fee=deepcopy(data['lines'][0])
    fee.update(kind='expense',description='Déplacement',subject=None,promotions=[],minutes=None,
               rate_ht=None,rate_ttc=None,amount_ht='10.00',amount_ttc='12.00',course_ids=[])
    data['lines'].append(fee); data.update(total_ht='100.00',total_vat='20.00',total_ttc='120.00')
    report=reconcile(data,context(),'ht')
    assert report['teaching_cents']==9000 and report['extra_cents']==1000
    assert report['teaching_minutes']==120 and 'non_teaching' in codes(report)


def test_multiple_invoices_detect_overlap_and_reference_duplicates():
    total=aggregate([item('i1'),item('i2')],context())
    text=' '.join(i['message'] for i in total['issues'])
    assert 'Numéro de facture répété' in text and 'plusieurs factures' in text
    assert total['teaching_minutes']==240
    assert total['difference_cents']==9000


def test_partial_billing_is_not_reported_as_an_error():
    ctx=context(); second=deepcopy(ctx['courses'][0]); second.update(id='c2',date='2026-10-12')
    ctx['courses'].append(second); ctx.update(minutes=240,expected_cents=18000)
    data=extraction(); data['complete_month']=False
    row=item(data=data,ctx=ctx); total=aggregate([row],ctx)
    assert row['report']['status']=='coherent'
    assert not any(i['level']=='error' for i in total['issues'])
    assert len(total['unmatched_courses'])==1


def test_archived_and_pending_documents_are_handled_explicitly():
    rows=[item('active'),item('archive',archived=True),dict(id='pending',report=None,archived=False)]
    total=aggregate(rows,context())
    assert total['analyzed_count']==1 and total['pending_count']==1
    assert total['teaching_minutes']==120


def test_mixed_rate_bases_disable_global_money_comparison():
    total=aggregate([item('one'),item('two',basis='ttc')],context())
    assert total['teaching_cents'] is None and total['difference_cents'] is None


@pytest.mark.parametrize('amount',[True,1.5,'NaN','Infinity','1e3','1.234',{},'1,23'])
def test_invalid_monetary_types_are_rejected(amount):
    with pytest.raises(InvoiceError): cents(amount)


@pytest.mark.parametrize('change',[
    lambda x:x.update(document_count=2),lambda x:x.update(complete_month='yes'),
    lambda x:x['lines'][0].update(minutes=True),lambda x:x['lines'][0].update(service_date='2026-02-31'),
    lambda x:x['lines'][0].update(vat_rate='200.00'),lambda x:x['lines'][0].update(start='27:00'),
    lambda x:x['lines'][0].update(course_ids=['x']*301),lambda x:x.update(total_ht='NaN')])
def test_malformed_ai_output_never_creates_a_valid_report(change):
    data=extraction();change(data)
    with pytest.raises(InvoiceError):validate_extraction(data)


def test_frontend_does_not_interpret_ai_or_filename_html():
    js=(Path(__file__).parents[1]/'static/js/trainer-invoices.js').read_text()
    assert 'innerHTML' not in js and 'insertAdjacentHTML' not in js
    assert 'textContent' in js and 'X-CSRF-Token' in js
