"""Manual admission remains admin-only, atomic and independent of public enrolment."""
from datetime import date

import pytest

from promotions import ensure_promotions_schema
from test_admissions_2027 import application, auth, client

PATH = '/admin/candidat/ajouter'


def data(client, **changes):
    auth(client)
    assert client.get(PATH).status_code == 200
    with client.session_transaction() as session:
        csrf = session['_candidate_message_csrf']
    return dict(nom='  duPont ', prenom='éLÉONORE', email='TEST@example.test', tel='', bts='MCO',
                rentree_annee='2026', mode='presentiel', statut='preinscription', csrf_token=csrf, **changes)


def rows():
    with application.db() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM candidats')]


def test_manual_creation_when_public_portal_closed_and_no_notifications(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: False)
    def unexpected_send(*args, **kwargs):
        pytest.fail('Manual creation must not send mail or SMS')
    monkeypatch.setattr(application, 'send_mail', unexpected_send)
    monkeypatch.setattr(application, 'send_sms_brevo', unexpected_send)
    response = client.post(PATH, data=data(client))
    assert response.status_code == 303
    row, = rows()
    assert (row['nom'], row['prenom'], row['email']) == ('DUPONT', 'Éléonore', 'test@example.test')
    assert row['numero_dossier'].startswith('2026BTS') and row['slug_public']
    assert row['rentree_annee'] == 2026 and row['statut'] == 'preinscription'
    assert row['fichiers_photo'] == '[]' and row['est_mineur'] == 0
    assert client.get(response.location).status_code == 200
    assert client.post('/admin/candidat/'+row['id']+'/informations', json={'adresse':'1 rue de Test'}).status_code == 200
    assert client.post('/admin/candidat/'+row['id']+'/informations', json={'tel':'incorrect'}).status_code == 400
    assert row['id'] in client.get('/admin?rentree=2026').text
    with application.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM logs WHERE type='CREATION_MANUELLE'").fetchone()[0] == 1


def test_permissions_and_csrf(client):
    assert client.get(PATH).status_code == 302
    assert client.post(PATH, data={}).status_code == 403
    payload = data(client)
    payload['csrf_token'] = 'incorrect'
    assert client.post(PATH, data=payload).status_code == 400
    assert not rows()


def test_duplicate_submission_and_email_case_do_not_create_two_dossiers(client):
    payload = data(client)
    assert client.post(PATH, data=payload).status_code == 303
    payload['email'] = 'test@EXAMPLE.test'
    response = client.post(PATH, data=payload)
    assert response.status_code == 400 and 'Ouvrir le dossier existant' in response.text
    assert len(rows()) == 1
    payload['rentree_annee'] = '2027'
    assert client.post(PATH, data=payload).status_code == 303
    assert len({row['numero_dossier'] for row in rows()}) == 2


@pytest.mark.parametrize('field,value', [('nom',''), ('email','wrong'), ('tel','123'), ('mode','wrong'),
                                        ('bts','wrong'), ('statut','wrong'), ('rentree_annee','2039'),
                                        ('date_naissance','2027-02-30'), ('date_naissance','2099-01-01')])
def test_invalid_values_retain_form_and_leave_database_unchanged(client, field, value):
    payload = data(client); payload[field] = value
    response = client.post(PATH, data=payload)
    assert response.status_code == 400
    assert 'candidate-create-form' in response.text
    assert not rows()


def test_promotion_assignment_is_validated_in_same_transaction(client):
    payload = data(client)
    with application.db() as conn:
        ensure_promotions_schema(conn)
        for pid, bts, year in [('good','MCO',2026), ('wrong-bts','MOS',2026), ('wrong-year','MCO',2027)]:
            conn.execute('INSERT INTO promotions(id,nom,bts,niveau,rentree_annee,created_at,updated_at) VALUES(?,?,?,1,?,?,?)',
                         (pid,'Promotion '+pid,bts,year,'2026-01-01','2026-01-01'))
    for pid in ('missing', 'wrong-bts', 'wrong-year'):
        payload['promotion_id'] = pid
        assert client.post(PATH, data=payload).status_code == 400
        assert not rows()
    payload.update(promotion_id='good', statut='confirmee', tel='+33 6 12 34 56 78', date_naissance='2010-01-01')
    assert client.post(PATH, data=payload).status_code == 303
    row, = rows()
    assert row['date_confirmee'] and row['tel'] == '0612345678'
    expected_minor = date.today() < date(2028, 1, 1)
    assert bool(row['est_mineur']) == expected_minor
    with application.db() as conn:
        assert conn.execute('SELECT promotion_id FROM student_promotions WHERE candidate_id=?', (row['id'],)).fetchone()[0] == 'good'
