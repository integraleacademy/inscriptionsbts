"""Selected whole-week copies keep useful courses without weakening hard caps."""
from unittest.mock import patch

import pytest

from test_planning import app, client, db, add, call, course, count, setup_school


def weeks(client, target_weeks=None, **changes):
    payload=dict(promotion_id='p1', mode='weeks', source_start='2027-01-04',
                 target_weeks=target_weeks if target_weeks is not None else ['2027-01-11','2027-01-18'])
    payload.update(changes)
    return call(client, '/courses/preview', payload)


def commit(client, preview, keys=None, **changes):
    payload=dict(preview_token=preview['preview_token'],
                 selected_keys=keys if keys is not None else [item['key'] for item in preview['items']])
    payload.update(changes)
    return call(client, '/courses/batch', payload)


@pytest.mark.parametrize('changes', [
    {'target_weeks':[]}, {'target_weeks':'2027-01-11'}, {'target_weeks':['2027-01-12']},
    {'target_weeks':['2027-01-11','2027-01-11']}, {'target_weeks':['2027-01-04']},
    {'target_weeks':['2027-02-30']}, {'target_weeks':[None]},
    {'source_start':'2027-01-05'}, {'source_start':'2027-13-04'},
])
def test_invalid_week_selections_are_rejected_without_inserts(client, db, changes):
    setup_school(client);add(client)
    response=weeks(client, **changes)
    assert response.status_code==400,response.json
    assert count(db)==1


def test_empty_source_and_overlarge_selection_are_rejected(client, db):
    setup_school(client)
    assert weeks(client).status_code==400
    for hour in range(7, 13):add(client,start=f'{hour:02d}:00',end=f'{hour+1:02d}:00')
    from datetime import date,timedelta
    targets=[(date(2027,1,11)+timedelta(weeks=index)).isoformat() for index in range(100)]
    response=weeks(client,targets)
    assert response.status_code==400 and '500' in response.json['message']
    assert count(db)==6


def test_whole_week_metadata_and_chronological_source_offsets(client, db):
    setup_school(client)
    first=add(client,room_id=None)
    last=add(client,date='2027-01-08',start='14:30',end='16:00',sid='s3')
    preview=weeks(client,['2027-01-18','2027-01-11']).json
    assert preview['mode']=='weeks' and preview['partial'] is True
    assert [item['course']['date'] for item in preview['items']]==['2027-01-11','2027-01-15','2027-01-18','2027-01-22']
    assert [item['source_course_id'] for item in preview['items']]==[first['id'],last['id'],first['id'],last['id']]
    assert [item['source_date'] for item in preview['items']]==['2027-01-04','2027-01-08']*2
    response=commit(client,preview)
    assert response.status_code==200 and response.json['count']==4
    assert response.json['skipped_count']==0 and response.json['created_keys']==['0','1','2','3']
    with db() as conn:
        copies=conn.execute("SELECT * FROM planning_courses WHERE date>'2027-01-08' ORDER BY date").fetchall()
    assert copies[0]['room_id'] is None
    assert copies[1]['start_min']==870 and copies[1]['end_min']==960


def test_shared_source_from_secondary_promotion_is_one_physical_copy(client, db):
    setup_school(client)
    source=add(client,shared=[{'promotion_id':'p2','subject_id':'s2'}])
    preview=weeks(client,['2027-01-11'],promotion_id='p2').json
    assert len(preview['items'])==1 and preview['items'][0]['source_course_id']==source['id']
    assert preview['items'][0]['course']['promotion_id']=='p1'
    response=commit(client,preview)
    assert response.status_code==200 and response.json['count']==1
    with db() as conn:
        groups=conn.execute('SELECT promotion_id,subject_id FROM planning_course_groups WHERE course_id=? ORDER BY promotion_id',
                            (response.json['course_ids'][0],)).fetchall()
    assert [tuple(row) for row in groups]==[('p1','s1'),('p2','s2')]
    assert count(db)==2


def test_shared_budget_limits_copy_and_unchecking_frees_later_occurrence(client, db):
    setup_school(client);add(client,shared=[{'promotion_id':'p2','subject_id':'s2'}])
    with db() as conn:conn.execute("UPDATE planning_subjects SET planned_hours=4 WHERE id='s2'")
    preview=weeks(client).json
    assert [item['valid'] for item in preview['items']]==[True,False]
    assert any(issue['type']=='subject_budget' for issue in preview['items'][1]['conflicts'])
    response=commit(client,preview,keys=['1'])
    assert response.status_code==200 and response.json['count']==1
    with db() as conn:
        assert conn.execute("SELECT date FROM planning_courses WHERE id=?",(response.json['course_ids'][0],)).fetchone()[0]=='2027-01-18'
        from planning import _subject_minutes
        assert _subject_minutes(conn,'s1')==240 and _subject_minutes(conn,'s2')==240


def test_reverse_checkbox_order_cannot_change_which_week_gets_scarce_budget(client, db):
    setup_school(client);add(client)
    with db() as conn:conn.execute("UPDATE planning_subjects SET planned_hours=4 WHERE id='s1'")
    preview=weeks(client).json
    response=commit(client,preview,keys=['1','0'])
    assert response.status_code==200 and response.json['count']==1
    assert response.json['created_keys']==['0']
    skipped=response.json['skipped']
    assert len(skipped)==1 and skipped[0]['key']=='1'
    assert skipped[0]['course']['date']=='2027-01-18'
    assert any(issue['type']=='subject_budget' for issue in skipped[0]['conflicts'])
    assert response.json['summary']=={'total':2,'created':1,'skipped':1}


def test_invalid_catalog_item_skips_only_its_occurrences(client, db):
    setup_school(client);add(client);add(client,sid='s3',date='2027-01-05')
    preview=weeks(client,['2027-01-11']).json
    with db() as conn:conn.execute("UPDATE trainers SET active=0 WHERE id='t1'")
    response=commit(client,preview)
    assert response.status_code==200 and response.json['count']==1 and response.json['skipped_count']==1
    assert response.json['skipped'][0]['conflicts'][0]['type']=='invalid_course'
    with db() as conn:
        row=conn.execute('SELECT trainer_id,date FROM planning_courses WHERE id=?',(response.json['course_ids'][0],)).fetchone()
    assert tuple(row)==('t2','2027-01-12')


def test_integrity_failure_remains_fatal_and_rolls_back_all_copies(client, db):
    setup_school(client);add(client)
    preview=weeks(client).json
    with patch('planning.secrets.token_urlsafe',return_value='duplicate-test-id'):
        response=commit(client,preview)
    assert response.status_code==409
    assert count(db)==1


def test_partial_option_cannot_weaken_existing_date_or_repeat_batches(client, db):
    setup_school(client)
    for mode in ('dates','repeat'):
        data=dict(promotion_id='p1',mode=mode,partial=True,template=dict(subject_id='s1',start='09:00',end='11:00'),
                  dates=['2027-03-29','2027-03-30'],start_date='2027-03-29',end_date='2027-03-30',weekdays=[0,1])
        preview=call(client,'/courses/preview',data).json
        response=commit(client,preview,partial=True)
        assert response.status_code==409 and count(db)==0


@pytest.mark.parametrize('keys', [['0','0'],['-1'],['01'],[0],['999'],['0',{}]])
def test_invalid_committed_keys_are_fatal(client, db, keys):
    setup_school(client);add(client)
    preview=weeks(client).json
    response=commit(client,preview,keys=keys)
    assert response.status_code==400 and count(db)==1
