import os
import unittest
from unittest.mock import Mock, patch

from services.ypareo_neo import (
    YpareoError,
    construire_payload_apprenant,
    get_ypareo_access_token,
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

    def test_international_french_phone_is_converted_to_national_format(self):
        payload = construire_payload_apprenant(
            {"nom": "Dupont", "tel": "+33 6 12 34 56 78"}
        )

        self.assertEqual(payload["telephones"][0]["indicatif"], "+33")
        self.assertEqual(payload["telephones"][0]["numero"], "0612345678")

    def test_invalid_phone_is_omitted_instead_of_rejected_by_ypareo(self):
        payload = construire_payload_apprenant(
            {"nom": "Dupont", "tel": "12345"}
        )

        self.assertNotIn("telephones", payload)


if __name__ == "__main__":
    unittest.main()
