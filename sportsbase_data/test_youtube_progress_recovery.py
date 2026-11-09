"""Regression tests for a stale YouTube Studio upload percentage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from .youtube_uploader import YouTubeStudioUploader


VIDEO_ID = "mntTTAmSohM"


class YouTubeProgressRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.uploader = YouTubeStudioUploader(self.temp_dir.name)

    @staticmethod
    def _studio_context(*, video_id=VIDEO_ID, status="Unlisted", visibility="Unlisted"):
        context = MagicMock()
        page = context.new_page.return_value
        rows = MagicMock()
        page.locator.return_value = rows
        rows.count.return_value = 1
        row = rows.nth.return_value
        link = MagicMock()
        link.count.return_value = 1
        link.get_attribute.return_value = f"/video/{video_id}/edit"
        link.first = link
        visibility_node = MagicMock()
        visibility_node.count.return_value = 1
        visibility_node.inner_text.return_value = visibility
        visibility_node.first = visibility_node
        row.locator.side_effect = lambda selector: (
            link if selector.startswith("a[href") else visibility_node
        )
        row.inner_text.return_value = status
        return context

    def test_confirm_published_unlisted_row_in_studio(self):
        context = self._studio_context()
        self.assertTrue(
            self.uploader._video_is_published_in_studio(
                context, VIDEO_ID, "unlisted"
            )
        )
        context.new_page.return_value.close.assert_called_once()

    def test_stale_uploading_label_must_never_be_success(self):
        context = self._studio_context(status="Uploading 95% - Unlisted")
        self.assertFalse(
            self.uploader._video_is_published_in_studio(
                context, VIDEO_ID, "unlisted"
            )
        )

    def test_pending_row_must_never_be_success(self):
        context = self._studio_context(status="Pending checks - Unlisted")
        self.assertFalse(
            self.uploader._video_is_published_in_studio(
                context, VIDEO_ID, "unlisted"
            )
        )

    def test_cannot_confirm_another_video(self):
        context = self._studio_context(video_id="abcdefghijk")
        self.assertFalse(
            self.uploader._video_is_published_in_studio(
                context, VIDEO_ID, "unlisted"
            )
        )

    def test_cannot_confirm_wrong_visibility(self):
        context = self._studio_context(visibility="Private")
        self.assertFalse(
            self.uploader._video_is_published_in_studio(
                context, VIDEO_ID, "unlisted"
            )
        )

    def test_pending_receipt_preserves_video_id_for_recovery(self):
        job = {"job_id": 298}
        receipt = {
            "status": "link_assigned",
            "youtube_url": f"https://youtu.be/{VIDEO_ID}",
            "youtube_video_id": VIDEO_ID,
            "youtube_channel_id": self.uploader.channel_id,
            "content_sha256": "a" * 64,
            "file_size_bytes": 348500000,
            "visibility": "unlisted",
        }
        self.uploader._save_receipt(job, receipt)
        self.assertEqual(
            self.uploader._load_pending_receipt(
                job,
                content_sha256="a" * 64,
                file_size=348500000,
            ),
            receipt,
        )
        self.assertIsNone(
            self.uploader._load_pending_receipt(
                job,
                content_sha256="b" * 64,
                file_size=348500000,
            )
        )

    def test_enabled_save_does_not_wait_for_a_percent(self):
        page = MagicMock()
        save_button = MagicMock()
        save_button.is_visible.return_value = True
        save_button.is_enabled.return_value = True
        save_button.get_attribute.return_value = None
        self.assertTrue(
            self.uploader._wait_for_save_or_studio_confirmation(
                page, save_button, VIDEO_ID, "unlisted"
            )
        )
        page.wait_for_timeout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
