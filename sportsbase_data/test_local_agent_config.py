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


class LocalAgentQueueTests(unittest.TestCase):
    def _agent(self):
        from unittest.mock import MagicMock
        from .local_agent import SportsBaseAgentClient
        agent = object.__new__(SportsBaseAgentClient)
        agent.next_job = MagicMock(return_value=None)
        agent.youtube_enabled = True
        agent.dailymotion_enabled = True
        agent.next_youtube_job = MagicMock(return_value=None)
        agent.next_dailymotion_job = MagicMock(return_value=None)
        agent.youtube_uploader = MagicMock()
        agent.dailymotion_uploader = MagicMock()
        agent.submit_youtube_result = MagicMock()
        agent.submit_dailymotion_result = MagicMock()
        return agent

    def _job(self):
        return {"job_id": 42, "player": {"name": "Test"}, "match": {"match_id": 1}}

    def test_completed_transfer_unconfirmed_does_not_block_queue(self):
        from .youtube_uploader import YouTubePostSaveUnconfirmed
        agent = self._agent()
        agent.next_youtube_job.return_value = self._job()
        agent.youtube_uploader.upload.side_effect = YouTubePostSaveUnconfirmed("draft possible")
        self.assertTrue(agent.process_once())
        agent.submit_youtube_result.assert_called_once_with(42, {"status": "failed", "error": "draft possible"})

    def test_incomplete_transfer_still_stops_queue(self):
        from .youtube_uploader import YouTubeUploadError
        agent = self._agent()
        agent.next_youtube_job.return_value = self._job()
        agent.youtube_uploader.upload.side_effect = YouTubeUploadError("transfer interrupted")
        with self.assertRaises(YouTubeUploadError):
            agent.process_once()

    def test_missing_dailymotion_category_continues_queue(self):
        from .dailymotion_uploader import DailymotionUploadError
        agent = self._agent()
        agent.next_dailymotion_job.return_value = self._job()
        error = "Studio : élément category|cat[eé]gorie introuvable."
        agent.dailymotion_uploader.upload.side_effect = DailymotionUploadError(error)
        self.assertTrue(agent.process_once())
        agent.submit_dailymotion_result.assert_called_once_with(42, {"status": "failed", "error": error})


if __name__ == "__main__":
    unittest.main()
