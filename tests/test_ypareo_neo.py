import os
import unittest
from unittest.mock import Mock, patch

from services.ypareo_neo import (
    YpareoError,
    construire_payload_apprenant,
    construire_payload_cursus,
    creer_apprenant_ypareo,
    _extract_id_inscription_bts_mos_premiere_annee,
    get_ypareo_access_token,
    inscrire_bts_mos_a_action_formation,
)


class YpareoBtsMosInscriptionExtractionTests(unittest.TestCase):
    def test_extracts_first_year_inscription_by_order_from_data(self):
        self.assertEqual(
            _extract_id_inscription_bts_mos_premiere_annee(
                {
                    "data": {
                        "id": "cursus-id",
                        "inscriptions": [
                            {
                                "anneeInscription": {"ordre": 2, "nom": "2ème année"},
                                "id": "second-year-id",
                            },
                            {
                                "anneeInscription": {"ordre": 1, "nom": "1ère année"},
                                "id": "first-year-id",
                            },
                        ],
                    }
                }
            ),
            "first-year-id",
        )

    def test_extracts_first_year_inscription_by_name_when_order_is_missing(self):
        self.assertEqual(
            _extract_id_inscription_bts_mos_premiere_annee(
                {
                    "data": {
                        "inscriptions": [
                            {
                                "anneeInscription": {"nom": "1ère année"},
                                "id": "first-year-id",
                            }
                        ]
                    }
                }
            ),
            "first-year-id",
        )

    def test_does_not_use_cursus_personne_or_formation_ids(self):
        with self.assertRaisesRegex(YpareoError, "id_inscription"):
            _extract_id_inscription_bts_mos_premiere_annee(
                {
                    "data": {
                        "id": "cursus-id",
                        "idPersonne": 1066,
                        "idActionFormation": 42,
                        "idFormation": 99,
                        "inscriptions": [],
                    }
                }
            )


class YpareoAuthenticationTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "YPAREO_API_URL": "https://ypareo.example/api",
            "YPAREO_AUTH_ENDPOINT": "/authenticate",
            "YPAREO_AUTH_TOKEN": "initial-token",
        },
        clear=False,
    )
    @patch("services.ypareo_neo.requests.post")
    def test_authenticate_sends_initial_token_as_json(self, post):
        response = Mock(ok=True)
        response.json.return_value = {"access_token": "access-token"}
        post.return_value = response

        token = get_ypareo_access_token()

        self.assertEqual(token, "access-token")
        post.assert_called_once_with(
            "https://ypareo.example/api/authenticate",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"token": "initial-token"},
            timeout=15,
        )

    @patch.dict(
        os.environ,
        {
            "YPAREO_API_URL": "https://ypareo.example/api",
            "YPAREO_AUTH_ENDPOINT": "/authenticate",
            "YPAREO_AUTH_TOKEN": "Bearer initial-token",
        },
        clear=False,
    )
    @patch("services.ypareo_neo.requests.post")
    def test_authenticate_rejects_bearer_prefix_in_render_token(self, post):
        with self.assertRaisesRegex(YpareoError, "sans préfixe"):
            get_ypareo_access_token()

        post.assert_not_called()


class YpareoPersonPayloadTests(unittest.TestCase):
    def test_string_address_is_nested_with_candidate_location(self):
        payload = construire_payload_apprenant(
            {
                "nom": "Dupont",
                "prenom": "Jean",
                "email": "jean@example.com",
                "tel": "06 12 34 56 78",
                "adresse": "12 rue du candidat",
                "cp": "75001",
                "ville": "Paris",
            }
        )

        self.assertEqual(
            payload,
            {
                "nom": "DUPONT",
                "prenom": "Jean",
                "emails": [{"adresse": "jean@example.com", "isDefault": True}],
                "telephones": [
                    {
                        "indicatif": "+33",
                        "isDefaultAppel": True,
                        "isDefaultSms": True,
                        "numero": "0612345678",
                    }
                ],
                "adresse": {
                    "ligne1": "12 rue du candidat",
                    "codePostal": "75001",
                    "ville": "Paris",
                    "paysAlpha": "FR",
                },
            },
        )

    def test_dict_address_keeps_only_ypareo_keys(self):
        payload = construire_payload_apprenant(
            {
                "nom": "Dupont",
                "adresse": {
                    "ligne1": "1 avenue Exemple",
                    "ligne2": "Bâtiment B",
                    "codePostal": "69001",
                    "ville": "Lyon",
                    "paysAlpha": "BE",
                    "country": "Belgique",
                    "schoolAddress": "54 CHE DE CARREOU",
                },
            }
        )

        self.assertEqual(
            payload["adresse"],
            {
                "ligne1": "1 avenue Exemple",
                "ligne2": "Bâtiment B",
                "codePostal": "69001",
                "ville": "Lyon",
                "paysAlpha": "BE",
            },
        )

    def test_missing_candidate_address_omits_address_even_with_city(self):
        payload = construire_payload_apprenant(
            {"nom": "Dupont", "cp": "83480", "ville": "Puget-sur-Argens"}
        )

        self.assertNotIn("adresse", payload)

    def test_birth_place_and_nationality_are_sent_to_ypareo(self):
        payload = construire_payload_apprenant(
            {
                "nom": "Dupont",
                "date_naissance": "12/05/2001",
                "ville_naissance": "Nice",
                "pays_naissance": "France",
                "nationalite": "Française",
            }
        )

        self.assertEqual(payload["dateNaissance"], "2001-05-12")
        self.assertEqual(payload["communeNaissance"], "Nice")
        self.assertEqual(payload["paysNaissanceAlpha"], "FR")
        self.assertEqual(payload["nationaliteAlpha"], "FR")

    def test_international_french_phone_is_converted_to_national_format(self):
        payload = construire_payload_apprenant(
            {"nom": "Dupont", "tel": "+33 6 12 34 56 78"}
        )

        self.assertEqual(payload["telephones"][0]["indicatif"], "+33")
        self.assertEqual(payload["telephones"][0]["numero"], "0612345678")

    def test_invalid_phone_is_omitted_instead_of_rejected_by_ypareo(self):
        payload = construire_payload_apprenant({"nom": "Dupont", "tel": "12345"})

        self.assertNotIn("telephones", payload)

    def test_training_mode_adds_distanciel_keyword(self):
        payload = construire_payload_apprenant({"nom": "Dupont", "mode": "Distanciel"})

        self.assertEqual(payload["motsCles"], ["distanciel"])

    def test_training_mode_adds_presentiel_keyword(self):
        payload = construire_payload_apprenant({"nom": "Dupont", "mode": "Présentiel"})

        self.assertEqual(payload["motsCles"], ["présentiel"])


class YpareoCursusPayloadTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "YPAREO_ID_FORMATION_BTS_MCO": "formation-mco",
            "YPAREO_ID_ORGANISME": "organisme",
            "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE": "42",
        },
        clear=False,
    )
    def test_cursus_uses_configured_situation_id(self):
        payload = construire_payload_cursus({"training_type": "BTS MCO"})

        self.assertEqual(
            payload,
            {
                "idFormation": "formation-mco",
                "idOrganisme": "organisme",
                "nom": "BTS MCO",
                "statutPremiereAnnee": "Stagiaire formation pro 3 mois",
                "etat": "Inscrit",
                "referentPedagogique": "Clément VAILLANT",
                "idSituationAvantApprentissage": 42,
            },
        )

    @patch.dict(
        os.environ,
        {
            "YPAREO_ID_FORMATION_BTS_MCO": "formation-mco",
            "YPAREO_ID_ORGANISME": "organisme",
        },
        clear=True,
    )
    def test_missing_situation_id_is_omitted_from_cursus_payload(self):
        payload = construire_payload_cursus({"training_type": "BTS MCO"})

        self.assertEqual(
            payload,
            {
                "idFormation": "formation-mco",
                "idOrganisme": "organisme",
                "nom": "BTS MCO",
                "statutPremiereAnnee": "Stagiaire formation pro 3 mois",
                "etat": "Inscrit",
                "referentPedagogique": "Clément VAILLANT",
            },
        )

    @patch.dict(
        os.environ,
        {
            "YPAREO_ID_FORMATION_BTS_MCO": "formation-mco",
            "YPAREO_ID_ORGANISME": "organisme",
            "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE": "42",
        },
        clear=False,
    )
    def test_bac_type_does_not_override_configured_situation_id(self):
        payload = construire_payload_cursus(
            {"training_type": "BTS MCO"}, {"bac_type": "Général"}
        )

        self.assertEqual(payload["idSituationAvantApprentissage"], 42)

    @patch.dict(
        os.environ,
        {
            "YPAREO_ID_FORMATION_BTS_MCO": "formation-mco",
            "YPAREO_ID_ORGANISME": "organisme",
        },
        clear=True,
    )
    def test_bac_type_does_not_add_default_situation_id(self):
        payload = construire_payload_cursus(
            {"training_type": "BTS MCO"}, {"bac_type": "Professionnel"}
        )

        self.assertNotIn("idSituationAvantApprentissage", payload)

    @patch.dict(
        os.environ,
        {
            "YPAREO_ID_FORMATION_BTS_MCO": "formation-mco",
            "YPAREO_ID_ORGANISME": "organisme",
            "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE": "situation",
        },
        clear=True,
    )
    def test_non_numeric_situation_id_has_actionable_render_error(self):
        with self.assertRaisesRegex(
            YpareoError,
            "identifiant numérique YPAREO",
        ) as context:
            construire_payload_cursus({"training_type": "BTS MCO"})

        self.assertEqual(context.exception.status_code, 503)


class YpareoBtsMosActionFormationTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"YPAREO_API_URL": "https://ypareo.example"},
        clear=True,
    )
    @patch("services.ypareo_neo.requests.put")
    def test_inscrire_bts_mos_a_action_formation_uses_participation_endpoint(self, put):
        response = Mock(ok=True, text='{"ok": true}', status_code=200)
        response.json.return_value = {"ok": True}
        put.return_value = response

        result = inscrire_bts_mos_a_action_formation(123, "access-token")

        self.assertEqual(result, {"ok": True})
        put.assert_called_once_with(
            "https://ypareo.example/api/inscription/123/participation",
            json=[
                {
                    "dateDebut": "2026-07-27",
                    "dateFin": "2027-07-25",
                    "id": None,
                    "idActionFormation": 42,
                }
            ],
            headers={
                "Authorization": "Bearer access-token",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    @patch.dict(
        os.environ,
        {
            "YPAREO_API_URL": "https://ypareo.example",
            "YPAREO_AUTH_ENDPOINT": "/authenticate",
            "YPAREO_AUTH_TOKEN": "initial-token",
            "YPAREO_APPRENANTS_ENDPOINT": "/api/personne",
            "YPAREO_CURSUS_ENDPOINT": "/api/personne/{IdPersonne}/cursus",
            "YPAREO_ID_FORMATION_BTS_MOS": "formation-mos",
            "YPAREO_ID_ORGANISME": "organisme",
        },
        clear=True,
    )
    @patch("services.ypareo_neo.requests.put")
    @patch("services.ypareo_neo.requests.post")
    def test_bts_mos_creation_attaches_first_year_inscription_to_action_formation(
        self, post, put
    ):
        auth_response = Mock(ok=True, status_code=200, content=b"{}")
        auth_response.json.return_value = {"access_token": "access-token"}
        personne_response = Mock(ok=True, status_code=201, content=b"{}")
        personne_response.json.return_value = {"idPersonne": 456}
        cursus_response = Mock(ok=True, status_code=201, content=b"{}")
        cursus_response.json.return_value = {
            "idCursus": 789,
            "data": {
                "inscriptions": [
                    {"anneeInscription": {"ordre": 1}, "id": "first-year-id"},
                    {"anneeInscription": {"ordre": 2}, "id": "second-year-id"},
                ]
            },
        }
        post.side_effect = [auth_response, personne_response, cursus_response]
        put_response = Mock(ok=True, text="", status_code=204)
        put.return_value = put_response

        result = creer_apprenant_ypareo(
            {"id": "candidat-1", "nom": "Dupont"},
            {"training_type": "BTS MOS 1ère année 2026-2028"},
        )

        self.assertEqual(result["personne_id"], 456)
        self.assertEqual(result["cursus_id"], 789)
        self.assertEqual(result["id_inscription_ypareo"], "first-year-id")
        put.assert_called_once()
        self.assertEqual(
            put.call_args.args[0],
            "https://ypareo.example/api/inscription/first-year-id/participation",
        )



if __name__ == "__main__":
    unittest.main()
