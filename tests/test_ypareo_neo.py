import os
import unittest
from unittest.mock import Mock, patch

from services.ypareo_neo import YpareoError, get_ypareo_access_token


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


if __name__ == "__main__":
    unittest.main()
