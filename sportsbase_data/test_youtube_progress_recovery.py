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


    def test_steps_advance_without_fixed_wait_after_clicks(self):
        page = MagicMock()
        next_button = MagicMock()
        next_button.first = next_button  # Locator.first must keep the same mock.
        next_button.count.return_value = 1
        next_button.is_visible.return_value = True
        next_button.is_enabled.return_value = True
        next_button.get_attribute.return_value = None

        radio = MagicMock()
        radio.count.return_value = 1
        radio.is_visible.side_effect = [False, False, False, True]
        radio.first = radio

        absent = MagicMock()
        absent.count.return_value = 0
        absent.first = absent

        def find(selector):
            if selector.startswith("tp-yt-paper-radio-button"):
                return radio
            if selector in ("#next-button", "ytcp-button#next-button"):
                return next_button
            return absent

        page.locator.side_effect = find
        page.get_by_text.return_value.first = absent
        with patch.object(
            self.uploader, "_wait_button_enabled", return_value=None
        ):
            self.assertEqual(
                self.uploader._select_visibility(page, "unlisted"), "unlisted"
            )
        self.assertEqual(next_button.click.call_count, 3)
        radio.click.assert_called_once()
        page.wait_for_timeout.assert_not_called()

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
