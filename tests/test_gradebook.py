"""Independent grading, migration, ownership, publication and roster isolation."""
import json
import re

import teaching as t
from test_teaching import env, logged, homework, post, state
from test_planning_portal_security import portal_db


def create(client, **overrides):
    data = dict(version=0,kind='evaluation',promotion_id='p1',subject_id='s1',
        title='Évaluation indépendante',instructions='Une étude de cas.',evaluation_date='2025-04-12',
        scale=20,coefficient=1,published=False)
    data.update(overrides)
    return client.post('/formateur/devoirs-notes/enregistrer',json=data,headers={'X-CSRF-Token':'csrf'})


def page_state(client, role='student'):
    response = client.get('/espace/devoirs-notes' if role == 'student' else '/formateur/devoirs-notes')
    assert response.status_code == 200
    return json.loads(re.search(r'id="gradebook-state">(.*?)</script>',response.text,re.S).group(1))


def grades(client, item, **overrides):
    data = dict(version=item['version'],students=[dict(id=s['id'],status='graded',score=0 if s['id']=='c1' else 17.5,comment='Avis '+s['id']) for s in item['students']])
    data.update(overrides)
    return client.post('/formateur/devoirs-notes/'+item['id']+'/notes',json=data,headers={'X-CSRF-Token':'csrf'})


def test_evaluation_without_any_lesson_or_timetable_allocation(env):
    client = logged(env)
    with env[1]() as conn:
        t.schema(conn)
        conn.execute('DELETE FROM planning_course_groups')
        conn.execute('DELETE FROM planning_courses')
        conn.execute("INSERT INTO planning_subject_catalog VALUES('catalog-only','Matière sans cours','matiere sans cours','#223344',1)")
        conn.execute("INSERT INTO planning_subject_diplomas VALUES('catalog-only','MCO','{}')")
    response = create(client,subject_id='catalog-only')
    assert response.status_code == 200
    item = response.json['item']
    assert item['course_id'] == '' and item['evaluation_date'] == '2025-04-12'
    assert {s['id'] for s in item['students']} == {'c1','c5'}
    assert grades(client,item).status_code == 200
    assert grades(client,item).status_code == 409
    assert page_state(client,'trainer')['items'][0]['graded_count'] == 2


def test_publication_only_exposes_students_own_grade(env):
    client=logged(env); item=create(client).json['item']
    item=grades(client,item).json['item']
    student=logged(env,'student','c1')
    assert page_state(student)['items'] == []
    response=create(client,**{k:item[k] for k in ['id','version','kind','title','instructions','evaluation_date','scale','coefficient']},published=True)
    assert response.status_code == 200
    visible=page_state(student)['items']
    assert len(visible)==1 and visible[0]['grades'][0]['score']==0
    assert visible[0]['grades'][0]['comment']=='Avis c1'
    assert 'Avis c5' not in json.dumps(visible)
    assert page_state(logged(env,'student','c2'))['items']==[]
    assert page_state(logged(env,'student','c3'))['items']==[]
    assert 'students' not in visible[0]


def test_legacy_homework_and_grades_survive_lesson_deletion(env):
    client=logged(env); old=homework(client,published=True).json['homework'][0]
    before=client.get('/formateur/devoirs-notes/'+old['id']+'/state').json['item']
    assert grades(client,before).status_code==200
    with env[1]() as conn:
        conn.execute("DELETE FROM planning_course_groups WHERE course_id='own'")
        conn.execute("DELETE FROM planning_courses WHERE id='own'")
        t.schema(conn)
    items=page_state(client,'trainer')['items']
    assert len(items)==1 and items[0]['id']==old['id'] and len(items[0]['grades'])==2
    assert len(page_state(logged(env,'student','c1'))['items'])==1


def test_migration_from_deployed_twelve_column_table_is_idempotent(env):
    client=logged(env); item=homework(client,published=True).json['homework'][0]
    loaded=client.get('/formateur/devoirs-notes/'+item['id']+'/state').json['item']
    assert grades(client,loaded).status_code==200
    with env[1]() as conn:
        conn.execute('DROP TABLE teaching_homework_groups')
        conn.execute('DROP INDEX teaching_homework_trainer')
        for column in ['kind','evaluation_date','scope_migrated']:
            conn.execute('ALTER TABLE teaching_homework DROP COLUMN '+column)
        before=tuple(conn.execute('SELECT * FROM teaching_homework').fetchone())
        saved_grades=[tuple(row) for row in conn.execute('SELECT * FROM teaching_grades ORDER BY candidate_id')]
        t.schema(conn)
        t.schema(conn)
        assert tuple(conn.execute('SELECT * FROM teaching_homework').fetchone())[:12]==before
        assert [tuple(row) for row in conn.execute('SELECT * FROM teaching_grades ORDER BY candidate_id')]==saved_grades
        assert conn.execute('SELECT count(*) FROM teaching_homework_groups').fetchone()[0]==1
    assert len(page_state(logged(env,'student','c1'))['items'])==1


def test_another_teacher_cannot_read_or_write_owned_evaluations(env):
    owner=logged(env); item=create(owner).json['item']; other=logged(env,identity='t2')
    assert other.get('/formateur/devoirs-notes/'+item['id']+'/state').status_code==404
    assert grades(other,item).status_code==404
    assert create(other,id=item['id'],version=item['version']).status_code==404
    assert page_state(other,'trainer')['items']==[]


def test_revoked_group_and_disabled_account_fail_closed(env):
    client=logged(env); item=create(client).json['item']
    with env[1]() as conn:
        conn.execute("DELETE FROM trainer_promotions WHERE trainer_id='t1' AND promotion_id='p1'")
    assert grades(client,item).status_code==404
    assert create(client).status_code==404
    assert page_state(client,'trainer')['items']==[]
    with env[1]() as conn: conn.execute("UPDATE trainers SET active=0 WHERE id='t1'")
    assert create(client,promotion_id='p2',subject_id='s2').status_code==401


def test_subject_diploma_and_csrf_checks(env):
    client=logged(env)
    with env[1]() as conn:
        t.schema(conn)
        conn.execute("INSERT INTO planning_subject_catalog VALUES('mos-only','MOS seulement','mos seulement','#223344',1)")
        conn.execute("INSERT INTO planning_subject_diplomas VALUES('mos-only','MOS','{}')")
    assert create(client,subject_id='mos-only').status_code==400
    assert create(client,promotion_id='p3').status_code==404
    assert client.post('/formateur/devoirs-notes/enregistrer',json={}).status_code==403
    assert env[0].test_client().get('/formateur/devoirs-notes').headers['Location']=='/formateur/connexion'


def test_grade_validation_is_atomic_and_versions_are_checked(env):
    client=logged(env); item=create(client).json['item']
    rows=[dict(id='c1',status='graded',score=15),dict(id='c5',status='graded',score=21)]
    assert grades(client,item,students=rows).status_code==400
    with env[1]() as conn: assert conn.execute('SELECT count(*) FROM teaching_grades').fetchone()[0]==0
    rows[1]['id']='c2'; rows[1]['score']=12
    assert grades(client,item,students=rows).status_code==409
    item=grades(client,item).json['item']
    assert create(client,id=item['id'],version=item['version'],scale=10).status_code==400


def test_dated_homework_and_course_page_separation(env):
    client=logged(env)
    assert create(client,kind='homework',due_date='2025-05-01',published=True).status_code==200
    assert create(client,kind='homework',due_date='').status_code==400
    assert create(client,evaluation_date='bogus').status_code==400
    html=client.get('/formateur/cours/own').text
    assert 'id="panel-devoirs"' not in html and 'id="teach-homework-form"' not in html
    assert '/formateur/devoirs-notes' in html
    assert html.count('class="trainer-portal-nav"')==1
