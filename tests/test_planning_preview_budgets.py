"""Preview budgets must describe the same current state as available courses."""
import pytest
from test_planning import app,client,db,add,call,setup_school,BASE


def preview_payload(source,mode):
    if mode=='weeks':
        return dict(mode=mode,promotion_id='p1',source_start='2027-01-04',target_weeks=['2027-01-11'])
    if mode=='dates':
        return dict(mode=mode,promotion_id='p1',dates=['2027-01-11'],source_course_id=source['id'],source_version=source['version'])
    return dict(mode=mode,promotion_id='p1',start_date='2027-01-11',end_date='2027-01-11',weekdays=[0],
                template=dict(subject_id='s1',trainer_id='t1',room_id='r1',start='09:00',end='11:00'))


@pytest.mark.parametrize('mode',['weeks','dates','repeat'])
def test_fresh_preview_unblocks_hours_freed_after_old_catalog(client,db,mode):
    setup_school(client)
    with db() as conn:conn.execute("UPDATE planning_subjects SET planned_hours=4 WHERE id='s1'")
    source=add(client)
    removed=add(client,date='2027-01-06')
    old=client.get(BASE+'/state?promotion_id=p1&start=2027-01-04&end=2027-01-10').json
    assert next(item for item in old['catalog']['subjects'] if item['id']=='s1')['remaining_minutes']==0
    assert call(client,'/courses/'+removed['id'],dict(version=removed['version']),method='DELETE').status_code==200
    preview=call(client,'/courses/preview',preview_payload(source,mode))
    assert preview.status_code==200,preview.json
    assert preview.json['items'][0]['valid']
    assert preview.json['budgets']==[dict(id='s1',name='Matière s1',planned_hours=4.0,planned_minutes=240,
                                        scheduled_minutes=120,remaining_minutes=120,budget_configured=True)]
    created=call(client,'/courses/batch',dict(preview_token=preview.json['preview_token'],selected_keys=['0']))
    assert created.status_code==200 and created.json['count']==1


def test_shared_preview_includes_each_participating_subject_budget(client,db):
    setup_school(client)
    source=add(client,shared=[dict(promotion_id='p2',subject_id='s2')])
    preview=call(client,'/courses/preview',preview_payload(source,'weeks')).json
    assert {budget['id'] for budget in preview['budgets']}=={'s1','s2'}
    assert all(budget['scheduled_minutes']==120 and budget['remaining_minutes']==1680 for budget in preview['budgets'])


def test_missing_budget_remains_a_blocker(client,db):
    setup_school(client);source=add(client)
    with db() as conn:conn.execute("UPDATE planning_subjects SET planned_hours=NULL WHERE id='s1'")
    preview=call(client,'/courses/preview',preview_payload(source,'dates')).json
    assert not preview['items'][0]['valid']
    assert preview['budgets'][0]['budget_configured'] is False
    assert preview['budgets'][0]['remaining_minutes'] is None
    assert preview['items'][0]['conflicts'][0]['type']=='subject_budget_missing'
