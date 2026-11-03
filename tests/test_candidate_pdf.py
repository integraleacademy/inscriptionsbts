"""Exercise the admin PDF with real form submissions, stored crops and legacy rows."""
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from candidate_photos import load_candidate_portrait
from test_admissions_2027 import application, auth, client, payload, seed
from test_promotion_metrics import contract
from filiz_fixtures import account


def printed(client, cid):
    response = client.get('/admin/print/' + cid)
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    pdf = PdfReader(BytesIO(response.data))
    return pdf, '\n'.join(page.extract_text() for page in pdf.pages)


def test_submitted_answers_photo_crop_and_linked_contract_reach_pdf(client, monkeypatch):
    monkeypatch.setattr(application, 'campaign_is_open', lambda: True)
    data = payload()
    photo = Image.new('RGB', (320, 200), 'blue')
    photo.paste('red', (80, 0, 240, 200))
    buf = BytesIO()
    photo.save(buf, 'PNG')
    buf.seek(0)
    data.update(photo=(buf, 'photo.png'), bts='MOS', mos_parcours='autre', aps_souhaitee='non',
                raison_aps='Carte professionnelle en renouvellement', cherche_idf='oui',
                projet_objectif='Animer une équipe et transmettre mon expérience.')
    data['qualites[]'] = ['esprit_equipe', 'curieux']
    assert client.post('/submit', data=data).status_code in (200, 302)
    with closing(application.db()) as conn:
        row = dict(conn.execute('SELECT * FROM candidats').fetchone())
        assert row['cherche_idf'] == 'oui' and row['consent'] == 1
        cid = row['id']
        _, source_hash, _ = load_candidate_portrait(row, application.UPLOAD_DIR, application.db)
        crop = dict(x=.25, y=0, width=.5, height=1, rotation=0)
        conn.execute('INSERT INTO candidate_photo_crops VALUES(?,?,?)', (cid, source_hash, json.dumps(crop)))
        cv_name = Path(json.loads(row['fichiers_cv'])[0]).name
        conn.execute('UPDATE candidats SET verif_docs=?,label_carte_etudiante=1 WHERE id=?',
                     (json.dumps({cv_name: {'etat': 'conforme'}}), cid))
        account(conn)
        contract(conn, cid, employer_name='Entreprise témoin', deca_number='DECA123')
        conn.commit()
    auth(client)
    pdf, content = printed(client, cid)
    for expected in ('Camille TEST', 'Général', 'Entreprise témoin', 'DECA123', 'Curiosité',
                     'Esprit d’équipe', 'Carte professionnelle en renouvellement', 'Animer une équipe',
                     'Recherche en Île-de-France', 'Carte étudiante envoyée', 'Conforme', 'Exactitude des informations'):
        assert expected in content
    assert all(private not in content for private in (cid, row['token_confirm'], cv_name))
    assert 'Photo indisponible' not in content
    portraits = [obj.image.convert('RGB') for obj in pdf.pages[0].images if obj.image.width < obj.image.height]
    assert len(portraits) == 1
    im = portraits[0]
    for x in (2, im.width//2, im.width-3):
        red, _, blue = im.getpixel((x, im.height//2))
        assert red > 220 and blue < 40  # The saved red-only crop, not the blue original.


def test_legacy_answers_replacements_missing_portrait_and_long_text(client):
    seed(2026, 'legacy')
    seed(2026, 'other')
    root = Path(application.UPLOAD_DIR)
    own = root/'legacy'
    own.mkdir(parents=True)
    (root/'other').mkdir()
    Image.new('RGB', (100, 150), 'blue').save(root/'other'/'portrait.jpg')
    (own/'unreadable.jpg').write_bytes(b'not an image')
    (own/'CV_legacy.pdf').write_bytes(b'%PDF-1.7\n')
    with closing(application.db()) as conn:
        conn.execute('''UPDATE candidats SET fichiers_photo=?,replace_meta=?,verif_docs=?,
                        projet_qualites=?,projet_pourquoi=?,bac_status='bac_ms',bts='MOS',
                        resp_email='responsable@example.test',commentaires='Note historique',
                        souhaite_accompagnement='non',permis_b=0 WHERE id='legacy' ''',
                     (json.dumps([str(root/'other'/'portrait.jpg'), str(own/'unreadable.jpg')]),
                      json.dumps({'nouveaux_fichiers':[{'fichier':'CV_legacy.pdf','label':application.DOC_FIELDS['cv'][1]}]}),
                      json.dumps({'refuse.pdf': {'etat':'non_conforme','label': application.DOC_FIELDS['lm'][1]}}),
                      json.dumps(['organise','Qualité historique']), 'Texte en plusieurs lignes.\n'*95 + 'Dernière ligne conservée.'))
        conn.commit()
    auth(client)
    pdf, content = printed(client, 'legacy')
    assert len(pdf.pages) > 2
    for expected in ('Photo indisponible', 'Organisation', 'Qualité historique', 'Responsable légal',
                     'responsable@example.test', 'Bac pro Métiers de la sécurité obtenu', 'Nouveau dépôt',
                     'Refus antérieur', 'Dernière ligne conservée.', 'Note historique'):
        assert expected in content
    assert 'Exactitude des informations confirmée' not in content
    assert 'Formation APS souhaitée' not in content
    assert len(pdf.pages[0].images) == 1  # Only the Academy logo.
