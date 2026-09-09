import os
import unittest
from unittest.mock import patch

from .agent_config import dailymotion_upload_enabled, youtube_upload_enabled


class YouTubeLocalAgentConfigurationTests(unittest.TestCase):
    def test_upload_is_enabled_by_default_for_subscription_driven_delivery(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(youtube_upload_enabled())

    def test_blank_legacy_setting_does_not_disable_subscription_delivery(self):
        with patch.dict(os.environ, {"YOUTUBE_UPLOAD_ENABLED": ""}, clear=True):
            self.assertTrue(youtube_upload_enabled())

    def test_explicit_false_remains_an_emergency_kill_switch(self):
        with patch.dict(
            os.environ,
            {"YOUTUBE_UPLOAD_ENABLED": "false"},
            clear=True,
        ):
            self.assertFalse(youtube_upload_enabled())

    def test_explicit_true_enables_upload(self):
        with patch.dict(
            os.environ,
            {"YOUTUBE_UPLOAD_ENABLED": "true"},
            clear=True,
        ):
            self.assertTrue(youtube_upload_enabled())


class DailymotionLocalAgentConfigurationTests(unittest.TestCase):
    def test_fallback_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(dailymotion_upload_enabled())

    def test_fallback_requires_an_explicit_true_value(self):
        with patch.dict(
            os.environ,
            {"DAILYMOTION_UPLOAD_ENABLED": "true"},
            clear=True,
        ):
            self.assertTrue(dailymotion_upload_enabled())

    def test_blank_value_keeps_fallback_disabled(self):
        with patch.dict(
            os.environ,
            {"DAILYMOTION_UPLOAD_ENABLED": ""},
            clear=True,
        ):
            self.assertFalse(dailymotion_upload_enabled())


if __name__ == "__main__":
    unittest.main()
