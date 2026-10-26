"""Calendar markers must include courses outside the visible week and shared groups."""
from test_planning import db, app, client, add, call, setup_school, BASE


def dates(client, pid='p1'):
    response = client.get(BASE + '/state', query_string={'promotion_id':pid,'start':'2027-01-04','end':'2027-01-10'})
    assert response.status_code == 200
    return response.json


def test_all_dates_shared_mapping_no_duplicates_and_promotion_isolation(client, db):
    setup_school(client)
    first = add(client, date='2027-02-01', shared=[{'promotion_id':'p2','subject_id':'s2'}])
    add(client, date='2027-02-01', start='14:00', end='15:00')
    add(client, pid='p2', sid='s4', date='2027-03-02', start='14:00', end='15:00')
    snapshot = dates(client)
    assert snapshot['courses'] == []
    assert snapshot['scheduled_days'] == [{'subject_id':'s1','date':'2027-02-01','count':2}]
    secondary = dates(client, 'p2')['scheduled_days']
    assert secondary == [{'subject_id':'s2','date':'2027-02-01','count':1}, {'subject_id':'s4','date':'2027-03-02','count':1}]
    # Rescheduling and deletion are reflected immediately by the normal state refresh.
    assert call(client, '/courses/'+first['id'], {'date':'2027-02-02','version':first['version']}, method='PUT').status_code == 200
    assert dates(client)['scheduled_days'] == [{'subject_id':'s1','date':'2027-02-01','count':1},{'subject_id':'s1','date':'2027-02-02','count':1}]
    assert call(client, '/courses/'+first['id'], {'version':first['version']+1}, method='DELETE').status_code == 200
    assert dates(client, 'p2')['scheduled_days'] == [{'subject_id':'s4','date':'2027-03-02','count':1}]
