import base64
import json
import os
from unittest import TestCase
from unittest.mock import patch

from .intro_generation import (
    _kling_token,
    kling_video_configured,
    openai_image_configured,
)
from .transfermarkt_assets import build_kling_prompt_text, build_prompt_text


class IntroGenerationConfigurationTests(TestCase):
    def test_paid_connectors_are_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(openai_image_configured())
            self.assertFalse(kling_video_configured())

    def test_kling_token_contains_access_key_without_exposing_secret(self):
        with patch.dict(os.environ, {
            "KLING_ACCESS_KEY": "access-key-test",
            "KLING_SECRET_KEY": "secret-key-test",
        }, clear=True):
            token = _kling_token()
        _header, encoded_claims, _signature = token.split(".")
        padding = "=" * (-len(encoded_claims) % 4)
        claims = json.loads(base64.urlsafe_b64decode(
            encoded_claims + padding
        ).decode("utf-8"))

        self.assertEqual(claims["iss"], "access-key-test")
        self.assertNotIn("secret-key-test", token)


class IntroPromptTests(TestCase):
    def setUp(self):
        self.data = {
            "player_name": "Joueur Test",
            "club_name": "Club Test",
            "nationality": "Tunisia",
            "primary_position": "Right winger",
            "market_value": "€500k",
        }

    def test_image_prompt_requires_verified_club_identity_and_stable_frame(self):
        prompt = build_prompt_text(self.data)

        self.assertIn("Preserve the uploaded player's real identity exactly", prompt)
        self.assertIn("First analyze the uploaded real club logo", prompt)
        self.assertIn("Never invent a new crest", prompt)
        self.assertIn("exactly 1920x1080", prompt)

    def test_kling_prompt_contains_requested_natural_micro_movements(self):
        prompt = build_kling_prompt_text(self.data)

        self.assertIn("Natural subtle breathing", prompt)
        self.assertIn("transfer of body weight", prompt)
        self.assertIn("progressive closed-mouth smile", prompt)
        self.assertIn("thin clouds drift very slowly", prompt)
        self.assertIn("tiny distant birds", prompt)
        self.assertIn("imperceptible slow push-in", prompt)
        self.assertIn("No face morphing", prompt)
