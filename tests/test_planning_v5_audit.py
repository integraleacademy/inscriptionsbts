"""Independent checks across annual costs, trainer tabs and change notifications."""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from trainer_workload import get_trainer_annual_workload, WorkloadError
from test_trainer_workload import workload_db, workload_client, lesson, rate


def annual(db, year=2027):
    with db() as conn:
        return get_trainer_annual_workload(conn, 't1', year)


def test_annual_cost_counts_shared_sessions_once_and_changes_rates_on_exact_date(workload_db):
    with workload_db() as conn:
        lesson(conn, 'jan', day='2027-01-04', end=570, groups=('p1','p2','p3'))
        lesson(conn, 'jun', day='2027-06-30', end=540)
        lesson(conn, 'jul', day='2027-07-01', end=525, groups=('p1','p2'))
        lesson(conn, 'dec', day='2027-12-31', end=600)
        lesson(conn, 'other-trainer', day='2027-01-04', end=720, trainer='t2')
        lesson(conn, 'previous-year', day='2026-12-31', end=600)
        lesson(conn, 'next-year', day='2028-01-01', end=600)
    rate(workload_db, '40.00', '2026-01-01')
    rate(workload_db, '52.50', '2027-07-01', 1)
    snapshot=annual(workload_db)
    assert snapshot['total_minutes']==315
    assert snapshot['shared_minutes']==135
    assert snapshot['course_count']==4
    assert snapshot['estimated_cents']==24438
    assert snapshot['all_priced'] is True
    by_month={row['number']:row for row in snapshot['months']}
    assert by_month[1]['minutes']==90 and by_month[7]['estimated_cents']==3938
    assert len(by_month)==12 and by_month[2]['minutes']==0


def test_annual_unpriced_time_is_never_silently_treated_as_zero(workload_db):
    with workload_db() as conn:
        lesson(conn,'unpriced',day='2027-01-04',end=525)
        lesson(conn,'priced',day='2027-12-31',end=540)
    rate(workload_db,'60','2027-02-01')
    snapshot=annual(workload_db)
    assert snapshot['total_minutes']==105
    assert snapshot['unpriced_minutes']==45 and not snapshot['all_priced']
    assert snapshot['estimated_cents']==6000
    assert snapshot['months'][0]['all_priced'] is False
    assert snapshot['months'][11]['all_priced'] is True


def test_annual_sum_rounds_after_exact_minutes_instead_of_accumulating_month_rounding(workload_db):
    with workload_db() as conn:
        for i,month in enumerate((1,2,3),1):
            lesson(conn,f'fraction-{i}',day=f'2027-{month:02d}-04',end=481)
    rate(workload_db,'1.00')
    snapshot=annual(workload_db)
    assert snapshot['estimated_cents']==5
    assert sum(row['estimated_cents'] for row in snapshot['months'])==6
    with workload_db() as conn:
        conn.execute("UPDATE planning_courses SET end_min=540 WHERE id='fraction-1'")
        conn.execute("DELETE FROM planning_course_groups WHERE course_id='fraction-2'")
        conn.execute("DELETE FROM planning_courses WHERE id='fraction-2'")
    changed=annual(workload_db)
    assert changed['course_count']==2 and changed['total_minutes']==61
    assert changed['estimated_cents']==102


@pytest.mark.parametrize('year',[True,False,1899,2201,'2027',None,2027.0])
def test_annual_year_validation_does_not_accept_scope_or_type_coercion(workload_db,year):
    with pytest.raises(WorkloadError):annual(workload_db,year)


from test_planning import app, client, db, setup_school, call, add


@pytest.mark.parametrize('template',[
    {'start':'09:00','end':'11:00'},
    {'subject_id':'s1','start':'09:00','end':'11:00','shared':[{}]},
    {'subject_id':'s1','start':'09:00','end':'11:00','shared':'not-a-list'},
    {'subject_id':'s1','start':'09:00','end':'11:00','shared':[None]},
])
def test_preview_budget_snapshot_does_not_turn_invalid_course_into_server_error(client,db,template):
    setup_school(client)
    response=call(client,'/courses/preview',dict(promotion_id='p1',mode='repeat',
        start_date='2027-01-11',end_date='2027-01-11',weekdays=[0],template=template))
    assert response.status_code in (200,400)
    if response.status_code==200:
        assert all(not row['valid'] for row in response.json['items'])
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM planning_courses').fetchone()[0]==0
