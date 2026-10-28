"""Synthetic candidates, original model, no messaging or live service calls."""
from io import BytesIO
import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from docx import Document

from test_admissions_2027 import application, auth, client, seed
from london_mobility import london_context, schema
from wedof_contracts import ensure_schema as wedof_schema


@pytest.fixture
def london(client, tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'VOYAGE_DIR', str(tmp_path / 'voyage'))
    seed(2026, 'london'); seed(2026, 'other')
    with application.db() as conn:
        schema(conn)
        conn.execute("UPDATE candidats SET date_naissance='1999-03-12',sexe='Femme',bts='MOS' WHERE id='london'")
    auth(client)
    response = client.get('/admin/candidat/london')
    assert response.status_code == 200
    return client


def data(client, **changes):
    with application.db() as conn:
        row = dict(conn.execute("SELECT * FROM candidats WHERE id='london'").fetchone())
        context = london_context(conn, row)
    with client.session_transaction() as state: csrf = state['_campus_csrf']
    return {**context['values'], 'csrf_token': csrf, 'revision': str(context['revision']),
            'source_fingerprint': context['source_fingerprint'], 'action': 'generate',
            'employer_name': 'Entreprise Exemple', 'employer_siret': '12345678901234',
            'employer_address': '12 rue des Écoles', 'employer_postcode': '75001', 'employer_city': 'Paris', **changes}


def post(client, values):
    return client.post('/admin/candidat/london/londres/convention', data=values, headers={'Accept':'application/json'})


def versions():
    with application.db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM london_mobility_versions WHERE candidate_id='london' ORDER BY created_at DESC")]


def test_generation_download_word_pdf_revision_and_no_duplicate(london):
    response = post(london, data(london))
    assert response.status_code == 200, response.json
    records = versions(); assert len(records) == 1
    vid = records[0]['id']
    pdf = london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf')
    assert pdf.mimetype == 'application/pdf' and pdf.headers['Cache-Control'] == 'private, no-store'
    reader = PdfReader(BytesIO(pdf.data)); text = '\n'.join(p.extract_text() for p in reader.pages)
    for expected in ['Entreprise Exemple','Camille','75001','12 rue des Écoles','08/11/2027','12/11/2027','Article 7','ANNEXE 1','KAPLAN']:
        assert expected in text
    for excluded in ['LONDONFIELD_', '«NOM_', '[sc_', 'BTSMARK_']:
        assert excluded not in text
    word = london.get(f'/admin/candidat/london/londres/conventions/{vid}/docx')
    doc = Document(BytesIO(word.data)); content = '\n'.join(p.text for p in doc.paragraphs)
    assert 'Entreprise Exemple' in content and '08/11/2027' in content
    assert 'LONDONFIELD_' not in content and '[sc_' not in content
    assert post(london, data(london)).status_code == 200 and len(versions()) == 1
    assert post(london, data(london, mobility_start='2027-11-09')).status_code == 200
    assert len(versions()) == 2
    assert london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').data == pdf.data
    with application.db() as conn:
        assert conn.execute("SELECT convention FROM voyage_londres_inscriptions WHERE candidat_id='london'").fetchone()[0] == 'Éditée'
        assert conn.execute('SELECT count(*) FROM voyage_londres_documents').fetchone()[0] == 4


def test_auth_csrf_modes_cross_candidate_and_stale_source(london):
    original = data(london)
    assert post(london, {**original, 'csrf_token':'wrong'}).status_code == 400
    with application.db() as conn: conn.execute("UPDATE candidats SET nom='MODIFIÉ' WHERE id='london'")
    assert post(london, original).status_code == 409 and not versions()
    assert post(london, data(london)).status_code == 200
    vid = versions()[0]['id']
    assert london.get(f'/admin/candidat/other/londres/conventions/{vid}/pdf').status_code == 404
    with application.db() as conn: conn.execute("UPDATE candidats SET mode='distanciel' WHERE id='london'")
    page = london.get('/admin/candidat/london').text
    assert 'id="panel-londres"' not in page
    assert post(london, data(london)).status_code == 400
    # Historical documents remain accessible after a mode change.
    assert london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').status_code == 200
    with london.session_transaction() as state: state.clear()
    assert london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').status_code == 403
    assert post(london, original).status_code == 403


@pytest.mark.parametrize('changes', [
    {'employer_name':''}, {'employer_siret':'bad'}, {'mobility_start':'2027-11-13'},
    {'mobility_end':'2028-01-01'}, {'mobility_cost':'NaN'}, {'mobility_cost':'-1'}, {'convention_date':'invalid'},
])
def test_invalid_data_creates_no_document_or_status(london, changes):
    response = post(london, data(london, **changes))
    assert response.status_code == 400, response.json
    assert not versions()
    with application.db() as conn: assert conn.execute('SELECT count(*) FROM voyage_londres_inscriptions').fetchone()[0] == 0


def test_minor_requires_guardian_and_has_a_separate_signature_area(london):
    with application.db() as conn: conn.execute("UPDATE candidats SET date_naissance='2010-03-12' WHERE id='london'")
    assert post(london, data(london)).status_code == 400
    assert post(london, data(london, guardian_first_name='Alex',guardian_last_name='EXEMPLE')).status_code == 200
    vid = versions()[0]['id']
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').data)).pages)
    assert 'Pour le représentant légal' in text and 'Alex' in text


def test_signed_upload_is_candidate_bound_preserves_original_and_marks_status(london):
    assert post(london, data(london)).status_code == 200
    version = versions()[0]; vid = version['id']
    original = london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').data
    # A synthetic copy stands in for a manually signed document. No signature is forged.
    fields = {'csrf_token':data(london)['csrf_token'], 'signed_confirmed':'yes'}
    route = f'/admin/candidat/london/londres/conventions/{vid}/signee'
    bad = london.post(route,data={**fields,'document':(BytesIO(b'not a PDF'),'document.pdf')},headers={'Accept':'application/json'})
    assert bad.status_code == 400
    upload = lambda: {**fields, 'document':(BytesIO(original),'convention-signee.pdf')}
    response = london.post(route,data=upload(),headers={'Accept':'application/json'})
    assert response.status_code == 200, response.json
    assert london.post(route,data=upload(),headers={'Accept':'application/json'}).status_code == 409
    assert london.get(f'/admin/candidat/london/londres/conventions/{vid}/pdf').data == original
    assert london.get(f'/admin/candidat/london/londres/conventions/{vid}/signed').data == original
    with application.db() as conn:
        assert conn.execute("SELECT convention FROM voyage_londres_inscriptions WHERE candidat_id='london'").fetchone()[0] == 'Signée'


def test_generation_failure_rolls_back_and_concurrent_save_is_rejected(london, monkeypatch):
    old = data(london, action='save')
    assert post(london, old).status_code == 200
    assert post(london, old).status_code == 409
    monkeypatch.setattr('london_mobility.word_document', lambda *args: (_ for _ in ()).throw(RuntimeError('conversion failed')))
    assert post(london, data(london)).status_code == 503
    assert not versions()
    with application.db() as conn:
        assert conn.execute('SELECT count(*) FROM voyage_londres_documents').fetchone()[0] == 0


def test_prepopulation_selects_only_attached_contract_and_dates_are_checked(london):
    with application.db() as conn:
        wedof_schema(conn)
        payload = {'state':'accepted','employer_name':'Employeur OPCO','employer_siret':'12345678901234',
                   'employer_address':'1 rue du Contrat','employer_postcode':'69001','employer_city':'Lyon',
                   'training_start':'2026-09-01','training_end':'2028-08-31'}
        values = {'contract_id':'123','candidate_id':'london','payload':json.dumps(payload),'checked_at':1,'linked_at':1,'error':''}
        conn.execute('INSERT INTO student_wedof_contracts (' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values()))
    page = london.get('/admin/candidat/london').text
    assert 'Employeur OPCO' in page and '1 rue du Contrat' in page
    assert post(london, data(london, contract_id='foreign')).status_code == 400
    assert post(london, data(london, contract_id='123',mobility_start='2029-11-08',mobility_end='2029-11-12')).status_code == 400
    assert not versions()


def test_voyage_actions_preserve_versioned_conventions(london):
    assert post(london, data(london)).status_code == 200
    version = versions()[0]
    with application.db() as conn:
        iid = conn.execute("SELECT id FROM voyage_londres_inscriptions WHERE candidat_id='london'").fetchone()[0]
    with london.session_transaction() as state: state['voyage_csrf'] = 'archive-test'
    headers = {'X-CSRF-Token': 'archive-test'}
    assert london.delete(f"/admin/voyage-londres/documents/{version['pdf_id']}", headers=headers).status_code == 409
    assert london.delete(f'/admin/voyage-londres/api/inscriptions/{iid}', headers=headers).status_code == 409
    assert london.patch(f'/admin/voyage-londres/api/inscriptions/{iid}', json={'statut':'annulee'}, headers=headers).status_code == 200
    assert london.get(f"/admin/candidat/london/londres/conventions/{version['id']}/pdf").status_code == 200
    assert post(london, data(london, mobility_start='2027-11-09')).status_code == 400
