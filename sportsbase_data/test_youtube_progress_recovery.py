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


    @staticmethod
    def _optional_confirmation_page(*, present=False, enabled=True):
        page = MagicMock()
        page.is_closed.return_value = False
        dialog = MagicMock()
        page.locator.return_value = dialog
        matches = MagicMock()
        matches.count.return_value = int(present)
        button = matches.nth.return_value
        button.is_visible.return_value = True
        button.is_enabled.return_value = enabled
        button.get_attribute.return_value = None
        dialog.get_by_role.return_value = matches
        dialog.locator.return_value = matches
        return page, dialog, button

    def test_missing_publish_anyway_skips_without_wait_or_click(self):
        page, dialog, button = self._optional_confirmation_page()
        self.assertFalse(self.uploader._publish_anyway_if_prechecks_pending(page))
        button.click.assert_not_called()
        page.wait_for_timeout.assert_not_called()
        for call in dialog.get_by_role.call_args_list:
            pattern = call.kwargs["name"]
            self.assertTrue(pattern.fullmatch("Publish anyway"))
            self.assertTrue(pattern.fullmatch("Publier quand même"))
            self.assertFalse(pattern.fullmatch("Cancel"))
        for call in dialog.locator.call_args_list:
            self.assertNotIn("secondary-action-button", call.args[0])

    def test_enabled_named_publish_anyway_clicks_once_without_force(self):
        page, _, button = self._optional_confirmation_page(present=True)
        self.assertTrue(self.uploader._publish_anyway_if_prechecks_pending(page))
        button.click.assert_called_once_with(timeout=1500)
        page.wait_for_timeout.assert_not_called()

    def test_disabled_publish_anyway_is_not_clicked(self):
        from .youtube_uploader import YouTubeUploadError
        page, _, button = self._optional_confirmation_page(present=True, enabled=False)
        with self.assertRaisesRegex(YouTubeUploadError, "non cliquable"):
            self.uploader._publish_anyway_if_prechecks_pending(page)
        button.click.assert_not_called()
        page.wait_for_timeout.assert_not_called()

    def test_disappearing_publish_anyway_does_not_force_click(self):
        from playwright.sync_api import TimeoutError
        page, _, button = self._optional_confirmation_page(present=True)
        button.click.side_effect = TimeoutError("dialog disappeared")
        button.is_visible.side_effect = [True, False] + [False] * 4
        self.assertFalse(self.uploader._publish_anyway_if_prechecks_pending(page))
        self.assertTrue(button.click.called)
        for call in button.click.call_args_list:
            self.assertEqual(call.kwargs, {"timeout": 1500})

    def _ready_save(self):
        save = MagicMock()
        save.is_visible.return_value = True
        save.is_enabled.return_value = True
        save.get_attribute.return_value = None
        return save

    def test_final_confirmation_closes_without_studio_check(self):
        page, _, _ = self._optional_confirmation_page()
        save = self._ready_save()
        with patch.object(self.uploader, "_close_published_confirmation", return_value=True), \
             patch.object(self.uploader, "_video_is_published_in_studio") as verify:
            self.uploader._complete_after_transfer(page, save, VIDEO_ID, "unlisted")
        save.click.assert_called_once_with(timeout=15000)
        verify.assert_not_called()

    def test_publish_anyway_then_close(self):
        page, _, button = self._optional_confirmation_page(present=True)
        with patch.object(self.uploader, "_close_published_confirmation", side_effect=[False, True]) as close, \
             patch.object(self.uploader, "_video_is_published_in_studio") as verify:
            self.uploader._complete_after_transfer(page, self._ready_save(), VIDEO_ID, "unlisted")
        button.click.assert_called_once_with(timeout=1500)
        close.assert_called_with(page, VIDEO_ID, after_publish=True)
        verify.assert_not_called()

    def test_publish_anyway_without_close_is_not_failure(self):
        page, _, button = self._optional_confirmation_page(present=True)
        with patch.object(self.uploader, "_close_published_confirmation", return_value=False) as close, \
             patch.object(self.uploader, "_video_is_published_in_studio") as verify:
            self.uploader._complete_after_transfer(page, self._ready_save(), VIDEO_ID, "unlisted")
        button.click.assert_called_once_with(timeout=1500)
        self.assertEqual(close.call_count, 5)
        self.assertEqual(page.wait_for_timeout.call_count, 3)
        verify.assert_not_called()

    def test_save_without_any_confirmation_is_unconfirmed_and_skips_studio(self):
        from .youtube_uploader import YouTubePostSaveUnconfirmed
        page, _, _ = self._optional_confirmation_page()
        with patch.object(self.uploader, "_wait_for_save_or_studio_confirmation", return_value=True), \
             patch.object(self.uploader, "_close_published_confirmation", return_value=False), \
             patch.object(self.uploader, "_video_is_published_in_studio") as verify, \
             patch("sportsbase_data.youtube_uploader.time.monotonic", side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(YouTubePostSaveUnconfirmed, VIDEO_ID):
                self.uploader._complete_after_transfer(page, self._ready_save(), VIDEO_ID, "unlisted")
        verify.assert_not_called()

    def test_page_closed_after_save_is_not_success(self):
        from .youtube_uploader import YouTubePostSaveUnconfirmed
        page, _, button = self._optional_confirmation_page()
        page.is_closed.return_value = True
        with patch.object(self.uploader, "_video_is_published_in_studio") as verify:
            with self.assertRaises(YouTubePostSaveUnconfirmed):
                self.uploader._complete_after_transfer(page, self._ready_save(), VIDEO_ID, "unlisted")
        button.click.assert_not_called()
        verify.assert_not_called()

    def test_failed_save_is_unconfirmed(self):
        from playwright.sync_api import TimeoutError
        from .youtube_uploader import YouTubePostSaveUnconfirmed
        page, _, button = self._optional_confirmation_page()
        save = self._ready_save()
        save.click.side_effect = TimeoutError("save failed")
        with self.assertRaises(YouTubePostSaveUnconfirmed):
            self.uploader._complete_after_transfer(page, save, VIDEO_ID, "unlisted")
        button.click.assert_not_called()

    def test_same_tab_studio_check_never_opens_new_page(self):
        context = self._studio_context()
        page = context.new_page.return_value
        self.assertTrue(self.uploader._video_is_published_in_studio(
            context, VIDEO_ID, "unlisted", page=page
        ))
        context.new_page.assert_not_called()
        page.close.assert_not_called()

    def test_confirmed_popup_closes_only_matching_success_dialog(self):
        page = MagicMock()
        dialogs = MagicMock()
        dialogs.count.return_value = 1
        page.locator.return_value = dialogs
        dialog = dialogs.nth.return_value
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = "Video published"
        dialog.locator.return_value.count.return_value = 0
        button = dialog.get_by_role.return_value.first
        button.count.return_value = 1
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        self.assertTrue(self.uploader._close_published_confirmation(page, VIDEO_ID))
        button.click.assert_called_once_with(timeout=1500)
        button.click.reset_mock()
        dialog.inner_text.return_value = "Draft saved"
        self.assertFalse(self.uploader._close_published_confirmation(page, VIDEO_ID))
        self.assertFalse(self.uploader._close_published_confirmation(page, VIDEO_ID, after_publish=True))
        button.click.assert_not_called()
        dialog.inner_text.return_value = "Your video is processing"
        self.assertTrue(self.uploader._close_published_confirmation(page, VIDEO_ID, after_publish=True))
        button.click.assert_called_once_with(timeout=1500)


if __name__ == "__main__":
    unittest.main()
