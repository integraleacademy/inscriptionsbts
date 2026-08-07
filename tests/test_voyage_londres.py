import io
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("INTEGRITY_CHECK", "0")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="bts-test-bootstrap-"))

import app as application


class VoyageLondresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        application.DB_PATH = os.path.join(self.tmp.name, "test.db")
        application.VOYAGE_DIR = os.path.join(self.tmp.name, "voyage")
        os.makedirs(application.VOYAGE_DIR)
        application.init_db()
        application.migrate_voyage_londres()
        conn = application.db()
        now = "2026-08-07T10:00:00"
        conn.execute(
            "INSERT INTO candidats(id,nom,prenom,email,tel,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("c1", "Clément", "Noël", "clement@example.fr", "0102030405", now, now),
        )
        conn.commit()
        conn.close()
        self.client = application.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self):
        with self.client.session_transaction() as session:
            session["admin_ok"] = True
            session["voyage_csrf"] = "test-csrf"
        return {"X-CSRF-Token": "test-csrf"}

    def test_admin_protection_search_defaults_duplicate_cancel_reactivate_delete(self):
        self.assertEqual(self.client.get("/admin/voyage-londres/api/inscriptions").status_code, 403)
        headers = self.login()
        found = self.client.get("/admin/voyage-londres/api/recherche?q=Clement").get_json()["personnes"]
        self.assertEqual(found[0]["id"], "c1")
        self.assertEqual(self.client.post("/admin/voyage-londres/api/inscriptions", json={"candidat_id": "c1"}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/admin/voyage-londres/api/inscriptions", json={"candidat_id": "c1"}, headers=headers).status_code, 409)
        row = self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"][0]
        self.assertEqual((row["statut"], row["convention"], row["opco"], row["billet"]), ("active", "À faire", 0, 0))
        iid = row["id"]
        changed = {"convention": "Transmise OPCO", "opco": 1, "billet": 1, "hebergement": 1, "immigration": 1}
        self.assertEqual(self.client.patch(f"/admin/voyage-londres/api/inscriptions/{iid}", json=changed, headers=headers).status_code, 200)
        self.client.patch(f"/admin/voyage-londres/api/inscriptions/{iid}", json={"statut": "annulee"}, headers=headers)
        self.assertEqual(self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"][0]["statut"], "annulee")
        self.client.post("/admin/voyage-londres/api/inscriptions", json={"candidat_id": "c1"}, headers=headers)
        self.assertEqual(len(self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"]), 1)
        self.client.delete(f"/admin/voyage-londres/api/inscriptions/{iid}", headers=headers)
        conn = application.db()
        self.assertIsNotNone(conn.execute("SELECT id FROM candidats WHERE id='c1'").fetchone())
        conn.close()

    def test_legacy_convention_values_are_exposed_with_a_visible_canonical_label(self):
        headers = self.login()
        self.client.post("/admin/voyage-londres/api/inscriptions", json={"candidat_id": "c1"}, headers=headers)
        conn = application.db()
        conn.execute("UPDATE voyage_londres_inscriptions SET convention='editee' WHERE candidat_id='c1'")
        conn.commit()
        conn.close()
        row = self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"][0]
        self.assertEqual(row["convention"], "Éditée")

    def test_passport_validation_and_document_lifecycle_and_recap(self):
        headers = self.login()
        self.client.post("/admin/voyage-londres/api/inscriptions", json={"candidat_id": "c1"}, headers=headers)
        iid = self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"][0]["id"]
        bad = {"passeport": 1, "numero_passeport": "12AB3456", "passeport_delivrance": "2030-01-01", "passeport_expiration": "2029-01-01"}
        self.assertEqual(self.client.patch(f"/admin/voyage-londres/api/inscriptions/{iid}/passeport", json=bad, headers=headers).status_code, 400)
        bad["passeport_expiration"] = "2035-01-01"
        self.assertEqual(self.client.patch(f"/admin/voyage-londres/api/inscriptions/{iid}/passeport", json=bad, headers=headers).status_code, 200)
        listed = self.client.get("/admin/voyage-londres/api/inscriptions").get_json()["inscriptions"][0]
        self.assertNotIn("numero_passeport", listed)
        self.assertEqual(listed["passeport_masque"], "••••3456")
        upload = {"categorie": "Billet", "documents": (io.BytesIO(b"%PDF-1.4\ncontent"), "billet.pdf")}
        self.assertEqual(self.client.post(f"/admin/voyage-londres/api/inscriptions/{iid}/documents", data=upload, headers=headers).status_code, 200)
        docs = self.client.get(f"/admin/voyage-londres/api/inscriptions/{iid}/documents").get_json()["documents"]
        did = docs[0]["id"]
        response = self.client.get(f"/admin/voyage-londres/documents/{did}/telecharger")
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get(f"/admin/voyage-londres/recapitulatif/{iid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/admin/voyage-londres/documents/{did}", headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
