"""Campaign boundary, cohort isolation and submission regressions (no external sends)."""
import io
import json
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault('INTEGRITY_CHECK', '0')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='bts-campaign-bootstrap-'))
import pytest
import app as application
from campaign import ADMISSION_YEAR, OPENS_AT, candidate_year, campaign_is_open
from mail_templates import mail_html
from utils import dossier_number, get_mail_context


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(application, 'DB_PATH', str(tmp_path / 'app.db'))
    monkeypatch.setattr(application, 'UPLOAD_DIR', str(tmp_path / 'uploads'))
    monkeypatch.setattr(application, 'PORTAL_FILE', str(tmp_path / 'portal.json'))
    monkeypatch.setattr(application, 'send_mail', lambda *args, **kwargs: True)
    monkeypatch.setattr(application, 'send_sms_brevo', lambda *args, **kwargs: True)
    application.init_db()
    application.ensure_schema()
    application.ensure_apprentissage_fields()
    application.ensure_baccalaureat_field()
    application.ensure_logs_cid_column()
    application.ensure_relance_field()
    application.ensure_souhaite_accompagnement_field()
    application.ensure_campaign_schema()
    return application.app.test_client()


def auth(client):
    with client.session_transaction() as session:
        session['admin_ok'] = True


def seed(year, cid, status='confirmee'):
    with application.db() as conn:
        conn.execute('INSERT INTO candidats(id,nom,prenom,email,bts,mode,numero_dossier,rentree_annee,statut,created_at,slug_public) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (cid,'TEST','Camille',cid+'@example.test','MCO','presentiel',f'{year}BTS01120001',year,status,'2026-12-01T10:00:00',cid))


def payload():
    fields=dict(nom='TEST',prenom='Camille',sexe='Femme',date_naissance='2008-01-01',ville_naissance='Paris',cp_naissance='75001',pays_naissance='France',nationalite='Française',num_secu='208017512345646',email='camille@example.test',email_confirm='camille@example.test',tel='0600000000',adresse='1 rue Test',cp='75001',ville='Paris',bts='MCO',mode='presentiel',baccalaureat='Prévu en 2027',bac_type='Général',permis_b='Oui',projet_pourquoi='Apprendre le commerce',projet_objectif='Devenir responsable',consent='1',entreprise_trouvee='non',recherches_commencees='oui',cherche_idf='non')
    for key in ['ci','ci2','carte_vitale','cv','lm']:
        fields[key]=(io.BytesIO(b'%PDF-1.4\n'),key+'.pdf')
    fields['photo']=(io.BytesIO(b'\x89PNG\r\n\x1a\n'),'photo.png')
    return fields


def test_exact_paris_opening_boundary():
    assert not campaign_is_open(OPENS_AT-timedelta(microseconds=1))
    assert campaign_is_open(OPENS_AT)
    assert campaign_is_open(OPENS_AT+timedelta(seconds=1))
    assert OPENS_AT.isoformat()=='2026-12-01T09:00:00+00:00'


def test_closed_server_cannot_be_bypassed(client, monkeypatch):
    monkeypatch.setattr(application,'campaign_is_open',lambda:False)
    assert b'count-days' in client.get('/').data
    assert b'application-form' not in client.get('/?admin_bypass=1').data
    assert client.get('/candidature?preview=1').status_code==302
    assert client.post('/submit',data=payload()).status_code==403
    assert client.post('/save_draft',json={'full_form':{'email':'a@example.test'}}).status_code==403
    assert client.get('/reprendre/any-token').status_code==302
    auth(client)
    assert client.get('/candidature?preview=1').status_code==200
    assert client.post('/submit',data=payload()).status_code==403
    with application.db() as conn: assert conn.execute('SELECT COUNT(*) FROM candidats').fetchone()[0]==0


def test_opening_and_manual_pause(client,monkeypatch):
    monkeypatch.setattr(application,'campaign_is_open',lambda:True)
    assert client.get('/candidature').status_code==200
    assert client.post('/set_portal_status',json={'status':'closed'}).status_code==403
    auth(client)
    assert client.post('/set_portal_status',json={'status':'closed'}).status_code==200
    assert client.get('/candidature').status_code==302
    client.post('/set_portal_status',json={'status':'open'})
    assert client.get('/candidature').status_code==200


def test_ics_uses_absolute_timezone(client):
    response=client.get('/ouverture.ics')
    assert response.mimetype=='text/calendar'
    assert b'DTSTART:20261201T090000Z' in response.data


def test_cohort_migration_idempotent_and_isolated_admin(client):
    seed(2026,'old');seed(2027,'new')
    application.ensure_campaign_schema();application.ensure_campaign_schema()
    auth(client)
    assert [r['id'] for r in client.get('/admin/json').json['rows']]==['new']
    assert [r['id'] for r in client.get('/admin/json?rentree=2026').json['rows']]==['old']
    assert len(client.get('/admin/json?rentree=all').json['rows'])==2
    assert client.get('/api/kpi?rentree=2027').json['confirmee']==1
    assert client.get('/admin/count_confirmed?rentree=2026').json['count']==1
    assert [r['id'] for r in client.get('/admin/export.json?rentree=2027').json]==['new']
    assert 'old' not in client.get('/admin/export.csv?rentree=2027').text


def test_complete_submission_saves_cohort_permit_and_both_identity_sides(client,monkeypatch):
    monkeypatch.setattr(application,'campaign_is_open',lambda:True)
    response=client.post('/submit',data=payload(),headers={'Accept':'application/json'})
    assert response.status_code==200, response.text
    assert response.json['ok']
    with application.db() as conn:
        row=dict(conn.execute('SELECT * FROM candidats').fetchone())
    assert row['rentree_annee']==2027
    assert row['numero_dossier'].startswith('2027BTS')
    assert row['permis_b']==1
    assert len(json.loads(row['fichiers_ci']))==2
    for f in json.loads(row['fichiers_ci']): assert os.path.isfile(f)
    page=client.get(response.json['redirect'])
    assert 'septembre 2027' in page.text
    assert 'septembre 2026' not in page.text


def test_incomplete_submission_does_not_write_files_or_candidates(client,monkeypatch):
    monkeypatch.setattr(application,'campaign_is_open',lambda:True)
    p=payload();p['email_confirm']='different@example.test'
    assert client.post('/submit',data=p).status_code==400
    with application.db() as conn: assert conn.execute('SELECT COUNT(*) FROM candidats').fetchone()[0]==0


def test_draft_resumption_retains_campaign_and_tags(client,monkeypatch):
    monkeypatch.setattr(application,'campaign_is_open',lambda:True)
    response=client.post('/save_draft',json={'full_form':{'email':'test@example.test','qualites[]':['rigoureux','curieux'],'bts':'CG'}})
    assert response.json['success']
    resumed=client.get(response.json['link'])
    assert resumed.status_code==200
    assert 'rigoureux' in resumed.text and 'curieux' in resumed.text
    assert 'rentree_annee' in resumed.text


def test_old_drafts_cannot_be_silently_reclassified(client,monkeypatch,tmp_path):
    monkeypatch.setattr(application,'campaign_is_open',lambda:True)
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    (tmp_path/'drafts.json').write_text(json.dumps([{'id':'old-draft','full_form':{'email':'old@example.test'}}]))
    response=client.get('/reprendre/old-draft')
    assert response.status_code==302 and '/candidature' in response.location


def test_mail_and_numbers_follow_candidate_year(client):
    assert dossier_number().startswith('2027BTS')
    assert candidate_year({'numero_dossier':'2026BTS01120001'})==2026
    with application.app.test_request_context():
        for year in [2026,2027]:
            context=get_mail_context({'rentree_annee':year,'bts':'MCO','prenom':'Camille','slug_public':'example'})
            html=mail_html('candidature_validee',**context)
            assert f'septembre {year}' in html
            assert f'septembre {2027 if year==2026 else 2026}' not in html


def test_ypareo_mos_never_reuses_previous_campaign(monkeypatch):
    from services.ypareo_neo import construire_payload_participation_bts_mos, YpareoError
    for key in ['ACTION_FORMATION_ID','DATE_DEBUT','DATE_FIN']:
        monkeypatch.delenv('YPAREO_BTS_MOS_2027_'+key, raising=False)
    with pytest.raises(YpareoError): construire_payload_participation_bts_mos(2027)
    assert construire_payload_participation_bts_mos(2026)[0]['dateDebut'].startswith('2026')
    monkeypatch.setenv('YPAREO_BTS_MOS_2027_ACTION_FORMATION_ID','123')
    monkeypatch.setenv('YPAREO_BTS_MOS_2027_DATE_DEBUT','2027-09-01')
    monkeypatch.setenv('YPAREO_BTS_MOS_2027_DATE_FIN','2028-06-30')
    item=construire_payload_participation_bts_mos(2027)[0]
    assert item['idActionFormation']==123 and item['dateDebut']=='2027-09-01'


def test_certificates_follow_each_candidates_cohort(client):
    from docx import Document
    seed(2026,'previous');seed(2027,'current');auth(client)
    for cid,year in [('previous',2026),('current',2027)]:
        for path in ['generate_certificat','generate_certificat_presentiel']:
            response=client.get(f'/admin/{path}/{cid}')
            assert response.status_code==200
            doc=Document(io.BytesIO(response.data))
            text=' '.join(p.text for p in doc.paragraphs)+' '.join(p.text for t in doc.tables for r in t.rows for c in r.cells for p in c.paragraphs)
            assert str(year) in text and str(year+2) in text, text
            assert f"Certificat de scolarité {year}-{year+2}" in text
            assert '{{' not in text
            if year == 2027:
                assert '6000€' not in text
                assert 'septembre 2026' not in text
                assert '2025, 100 %' in text  # A historical result must remain historical.
            response.close()


def test_aps_2027_does_not_promise_unconfirmed_dates_or_prices(client):
    with application.app.test_request_context():
        html=mail_html('demande_aps',rentree_annee=2027,prenom='Camille')
        assert 'rentrée 2027' in html and 'confirmer le calendrier' in html
        assert '950' not in html and 'QONTO' not in html


def test_certificate_placeholders_split_across_runs():
    from docx import Document
    from certificates import personalize_certificate
    doc=Document();p=doc.add_paragraph()
    p.add_run('2026-2028 — {{NOM_').bold=True
    p.add_run('PRENOM}} : {{DATE_AUJOURDHUI}}')
    personalize_certificate(doc,{'{{NOM_PRENOM}}':'Camille TEST','{{DATE_AUJOURDHUI}}':'24/10/2026'},2027)
    assert p.text=='2027-2029 — Camille TEST : 24/10/2026'
    assert p.runs[0].bold
