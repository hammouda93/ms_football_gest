"""RPA contract tests: all browser interaction is mocked, no live uploads."""

import hashlib
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, patch

from .dailymotion_links import canonical_dailymotion_url, extract_dailymotion_video_id
from .dailymotion_uploader import (
    DailymotionAuthenticationRequired,
    DailymotionStudioUploader,
    DailymotionUploadError,
)


class DailymotionLinksTests(unittest.TestCase):
    def test_private_share_identifier_is_preserved(self):
        for url in (
            "https://www.dailymotion.com/video/kPrivate123",
            "https://dai.ly/kPrivate123",
            "https://www.dailymotion.com/embed/video/kPrivate123",
            "https://geo.dailymotion.com/player/xplayer.html?video=kPrivate123",
        ):
            with self.subTest(url=url):
                self.assertEqual(extract_dailymotion_video_id(url), "kPrivate123")
                self.assertEqual(canonical_dailymotion_url(url), "https://www.dailymotion.com/video/kPrivate123")

    def test_external_and_studio_urls_are_not_share_links(self):
        for url in (
            "https://www.dailymotion.com/partner/x6445ea/media/video/x123456",
            "https://evil.test/video/x123456",
            "https://www.dailymotion.com.evil.test/video/x123456",
            "https://user@www.dailymotion.com/video/x123456",
            "javascript:alert(1)",
            "https://www.dailymotion.com/video/éabcde",
        ):
            with self.subTest(url=url):
                self.assertEqual(extract_dailymotion_video_id(url), "")


class DailymotionRPATests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "player_1" / "match_1"
        self.folder.mkdir(parents=True)
        self.video = self.folder / "actions.mp4"
        self.video.write_bytes(b"same-video-content")
        self.digest = hashlib.sha256(b"same-video-content").hexdigest()
        self.job = {
            "job_id": 91,
            "match": {"local_folder_key": "player_1/match_1", "filename": "actions.mp4"},
            "dailymotion": {"title": "Player — All Actions", "description": "MS Performance"},
        }
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.uploader = DailymotionStudioUploader(self.root)
        self.url = "https://www.dailymotion.com/video/kPrivate123"

    def browser_mock(self):
        playwright_patch = patch("sportsbase_data.dailymotion_uploader.sync_playwright")
        self.addCleanup(playwright_patch.stop)
        playwright_patch.start()
        context = MagicMock()
        page = Mock(url=self.uploader.content_url)
        context.pages = [page]
        self.uploader._launch_context = Mock(return_value=context)
        self.uploader._goto_studio = Mock()
        self.uploader._assert_studio = Mock()
        self.uploader._video_urls = Mock(return_value=set())
        self.uploader._open_upload_dialog = Mock()
        self.uploader._fill_details = Mock()
        self.uploader._wait_upload_transfer_complete = Mock()
        self.uploader._wait_save_button = Mock()
        self.uploader._wait_saved = Mock()
        self.uploader._read_video_url = Mock(return_value=self.url)
        return page, context

    def test_uses_sportsbase_chrome_profile_without_api_credentials(self):
        self.assertEqual(self.uploader.profile_id, "x6445ea")
        self.assertEqual(self.uploader.content_url, "https://www.dailymotion.com/partner/x6445ea/media/video")
        self.assertEqual(str(self.uploader.profile_dir), r"D:\SportsBase_Playwright_Profile")
        self.assertEqual(self.uploader.browser_channel, "chrome")
        self.assertFalse(self.uploader.headless)
        self.assertFalse(hasattr(self.uploader, "api_key"))
        self.assertFalse(hasattr(self.uploader, "api_secret"))

    def test_persistent_context_launch_uses_configured_profile(self):
        self.uploader.profile_dir = self.root / "chrome-profile"
        playwright = Mock()
        self.uploader._launch_context(playwright)
        playwright.chromium.launch_persistent_context.assert_called_once_with(
            user_data_dir=str(self.root / "chrome-profile"), channel="chrome",
            headless=False, no_viewport=True, args=["--start-maximized"],
        )

    def test_windows_relative_path_is_supported(self):
        self.job["match"]["local_folder_key"] = r"player_1\match_1"
        self.assertEqual(self.uploader.resolve_video_path(self.job), self.video.resolve())

    def test_path_traversal_and_invalid_files_are_rejected(self):
        for folder, filename in (
            ("../outside", "actions.mp4"),
            ("player_1/match_1", "../../actions.mp4"),
            ("player_1/match_1", "missing.mp4"),
        ):
            with self.subTest(folder=folder, filename=filename):
                with self.assertRaises(DailymotionUploadError):
                    self.uploader.resolve_video_path({"match": {"local_folder_key": folder, "filename": filename}})

    def test_upload_uses_file_input_then_waits_before_save(self):
        page, context = self.browser_mock()
        order = []
        self.uploader._open_upload_dialog.return_value.set_input_files.side_effect = lambda *_: order.append("file")
        self.uploader._fill_details.side_effect = lambda *_: order.append("details")
        self.uploader._wait_upload_transfer_complete.side_effect = lambda *_: order.append("transfer")
        self.uploader._wait_save_button.return_value.click.side_effect = lambda: order.append("save")
        self.uploader._wait_saved.side_effect = lambda *_: order.append("confirmed")

        result = self.uploader.upload(self.job)

        self.assertEqual(order, ["file", "details", "transfer", "save", "confirmed"])
        self.uploader._open_upload_dialog.return_value.set_input_files.assert_called_once_with(str(self.video.resolve()))
        self.uploader._fill_details.assert_called_once_with(page, "Player — All Actions", "MS Performance")
        self.assertEqual(result["dailymotion_video_id"], "kPrivate123")
        self.assertEqual(result["content_sha256"], self.digest)
        context.close.assert_called_once()

    def test_receipt_reuses_video_without_reopening_chrome(self):
        self.browser_mock()
        first = self.uploader.upload(self.job)
        self.uploader._launch_context.reset_mock()
        self.assertEqual(self.uploader.upload(self.job), first)
        self.uploader._launch_context.assert_not_called()

    def test_failure_before_save_does_not_mark_video_uploaded(self):
        _page, context = self.browser_mock()
        self.uploader._fill_details.side_effect = DailymotionUploadError("Privée non confirmée")
        with self.assertRaisesRegex(DailymotionUploadError, "Privée non confirmée"):
            self.uploader.upload(self.job)
        self.uploader._wait_save_button.assert_not_called()
        self.assertFalse(self.uploader._receipt_path(self.job).exists())
        context.close.assert_called_once()

    def test_uncertain_save_prevents_duplicate_on_retry(self):
        _page, context = self.browser_mock()
        self.uploader._wait_saved.side_effect = DailymotionUploadError("Confirmation absente")
        with self.assertRaises(DailymotionUploadError):
            self.uploader.upload(self.job)
        context.close.assert_called_once()
        self.uploader._launch_context.reset_mock()
        with self.assertRaisesRegex(DailymotionUploadError, "déjà été tenté"):
            self.uploader.upload(self.job)
        self.uploader._launch_context.assert_not_called()

    def test_expired_session_stops_before_selecting_a_file(self):
        page, context = self.browser_mock()
        self.uploader._assert_studio.side_effect = DailymotionAuthenticationRequired("Connexion requise")
        with self.assertRaises(DailymotionAuthenticationRequired):
            self.uploader.upload(self.job)
        self.uploader._open_upload_dialog.assert_not_called()
        page.screenshot.assert_not_called()
        context.close.assert_called_once()

    def test_first_connection_uses_regular_chrome_and_never_uploads(self):
        _page, first_context = self.browser_mock()
        second_context = MagicMock()
        second_context.pages = [Mock(url=self.uploader.content_url)]
        self.uploader._launch_context = Mock(
            side_effect=[first_context, second_context]
        )
        self.uploader._authentication_required = Mock(side_effect=[True, False])
        self.uploader._open_manual_login = Mock()
        self.uploader._wait_control = Mock()
        self.assertTrue(self.uploader.check_access())
        self.uploader._open_manual_login.assert_called_once_with()
        self.assertEqual(self.uploader._goto_studio.call_count, 2)
        self.uploader._open_upload_dialog.assert_not_called()
        first_context.close.assert_called_once()
        second_context.close.assert_called_once()

    def test_manual_login_launches_regular_chrome_with_shared_profile(self):
        chrome = self.root / "chrome.exe"
        chrome.write_bytes(b"")
        self.uploader.profile_dir = self.root / "sportsbase-profile"
        with patch.dict(
            os.environ,
            {"DAILYMOTION_CHROME_EXECUTABLE": str(chrome)},
        ), patch("sportsbase_data.dailymotion_uploader.subprocess.Popen") as launch, patch(
            "builtins.input", return_value=""
        ):
            self.uploader._open_manual_login()

        launch.assert_called_once_with(
            [
                str(chrome),
                f"--user-data-dir={self.uploader.profile_dir}",
                "--new-window",
                self.uploader.content_url,
            ]
        )

    def test_headless_first_connection_requires_user_to_enable_chrome(self):
        self.browser_mock()
        self.uploader.headless = True
        self.uploader._authentication_required = Mock(return_value=True)
        with patch("builtins.input") as prompt:
            with self.assertRaisesRegex(DailymotionAuthenticationRequired, "HEADLESS=false"):
                self.uploader.check_access()
        prompt.assert_not_called()

    def test_native_category_select_is_verified(self):
        field = Mock()
        field.evaluate.return_value = "select"
        option = Mock()
        option.get_attribute.return_value = "sport"
        field.locator.return_value.all.return_value = [option]
        field.input_value.return_value = "sport"
        self.uploader._wait_control = Mock(return_value=field)
        self.uploader._select_option(Mock(), re.compile("Category"), 'select[name="category"]', {"sport"}, re.compile("Sports"))
        field.select_option.assert_called_once_with(value="sport")

    def test_completion_requires_explicit_transfer_evidence(self):
        for text in ("Upload complete", "Optimizing", "Transfert terminé"):
            self.assertTrue(self.uploader._transfer_complete(text))
        for text in ("Upload in progress", "Uploaded on Monday", "No video uploaded", "Upload complete: false"):
            self.assertFalse(self.uploader._transfer_complete(text))
        self.assertFalse(self.uploader._transfer_complete("", [99]))
        self.assertTrue(self.uploader._transfer_complete("", [100]))

    def test_old_video_link_is_excluded_and_private_link_is_preserved(self):
        old = "https://www.dailymotion.com/video/xExisting123"
        self.uploader._video_urls = Mock(return_value={old, self.url})
        self.uploader._raise_if_blocked = Mock()
        self.assertEqual(self.uploader._read_video_url(Mock(), previous_urls={old}, title="Player"), self.url)

    def test_ambiguous_new_links_are_rejected(self):
        self.uploader._video_urls = Mock(return_value={
            "https://www.dailymotion.com/video/xCandidate1",
            "https://www.dailymotion.com/video/xCandidate2",
        })
        self.uploader._raise_if_blocked = Mock()
        with self.assertRaisesRegex(DailymotionUploadError, "Plusieurs liens"):
            self.uploader._read_video_url(Mock(), previous_urls=set(), title="Player")

    def test_exact_uploaded_title_is_opened_before_reading_share_link(self):
        page = Mock()
        self.uploader._goto_studio = Mock()
        self.uploader._raise_if_blocked = Mock()
        self.uploader._video_urls = Mock(side_effect=[set(), {self.url}])
        self.uploader._title_field = Mock(return_value=None)
        self.uploader._open_uploaded_title = Mock(return_value=True)
        self.uploader._reveal_share_panel = Mock(return_value=False)

        result = self.uploader._read_video_url(
            page,
            previous_urls=set(),
            title="Player — All Actions",
        )

        self.assertEqual(result, self.url)
        self.uploader._goto_studio.assert_called_once_with(page)
        self.uploader._open_uploaded_title.assert_called_once_with(
            page,
            "Player — All Actions",
        )

    def test_editor_share_panel_is_revealed_before_reading_link(self):
        page = Mock()
        self.uploader._goto_studio = Mock()
        self.uploader._raise_if_blocked = Mock()
        self.uploader._video_urls = Mock(side_effect=[set(), {self.url}])
        self.uploader._title_field = Mock(return_value=Mock())
        self.uploader._reveal_share_panel = Mock(return_value=True)
        self.uploader._open_uploaded_title = Mock(return_value=False)

        result = self.uploader._read_video_url(
            page,
            previous_urls=set(),
            title="Player — All Actions",
        )

        self.assertEqual(result, self.url)
        self.uploader._reveal_share_panel.assert_called_once_with(page)
        self.uploader._open_uploaded_title.assert_not_called()

    def test_library_embed_action_is_scoped_to_exact_uploaded_row(self):
        page = Mock()
        row = Mock()
        self.uploader._goto_studio = Mock()
        self.uploader._raise_if_blocked = Mock()
        self.uploader._video_urls = Mock(side_effect=[set(), {self.url}])
        self.uploader._title_field = Mock(return_value=None)
        self.uploader._uploaded_row = Mock(return_value=row)
        self.uploader._reveal_share_panel = Mock(return_value=True)
        self.uploader._open_uploaded_title = Mock(return_value=False)

        result = self.uploader._read_video_url(
            page,
            previous_urls=set(),
            title="Player — All Actions",
        )

        self.assertEqual(result, self.url)
        self.uploader._uploaded_row.assert_called_once_with(
            page,
            "Player — All Actions",
        )
        self.uploader._reveal_share_panel.assert_called_once_with(
            page,
            scope=row,
        )
        self.uploader._open_uploaded_title.assert_not_called()


class DailymotionAgentOrderTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "DJANGO_AUTOMATION_USERNAME": "agent",
            "DJANGO_AUTOMATION_PASSWORD": "secret",
            "DAILYMOTION_UPLOAD_ENABLED": "true",
        },
        clear=True,
    )
    @patch("sportsbase_data.local_agent.DailymotionStudioUploader")
    @patch("sportsbase_data.local_agent.YouTubeStudioUploader")
    @patch("sportsbase_data.local_agent.SportsBaseSubscriptionScraper")
    def test_enabled_fallback_reuses_sportsbase_chrome_profile(
        self,
        scraper,
        _youtube_uploader,
        dailymotion_uploader,
    ):
        from .local_agent import SportsBaseAgentClient

        shared_profile = Path(r"D:\SportsBase_Playwright_Profile")
        scraper.return_value.profile_dir = shared_profile

        client = SportsBaseAgentClient()

        dailymotion_uploader.assert_called_once_with(
            client.storage_root,
            profile_dir=shared_profile,
        )

    @patch.dict(
        os.environ,
        {
            "DJANGO_AUTOMATION_USERNAME": "agent",
            "DJANGO_AUTOMATION_PASSWORD": "secret",
            "DAILYMOTION_UPLOAD_ENABLED": "false",
        },
        clear=True,
    )
    @patch("sportsbase_data.local_agent.DailymotionStudioUploader")
    @patch("sportsbase_data.local_agent.YouTubeStudioUploader")
    @patch("sportsbase_data.local_agent.SportsBaseSubscriptionScraper")
    def test_disabled_fallback_does_not_initialize_dailymotion_profile(
        self,
        _scraper,
        _youtube_uploader,
        dailymotion_uploader,
    ):
        from .local_agent import SportsBaseAgentClient

        client = SportsBaseAgentClient()

        self.assertFalse(client.dailymotion_enabled)
        self.assertIsNone(client.dailymotion_uploader)
        dailymotion_uploader.assert_not_called()

    def client(self, youtube_enabled=True, dailymotion_enabled=True):
        from .local_agent import SportsBaseAgentClient

        client = object.__new__(SportsBaseAgentClient)
        client.youtube_enabled = youtube_enabled
        client.dailymotion_enabled = dailymotion_enabled
        client.next_job = Mock(return_value=None)
        client.next_youtube_job = Mock(return_value=None)
        client.next_dailymotion_job = Mock(return_value=None)
        client.youtube_uploader = Mock()
        client.youtube_uploader.upload.return_value = {"status": "uploaded"}
        client.dailymotion_uploader = Mock()
        client.dailymotion_uploader.upload.return_value = {"status": "uploaded"}
        client.submit_youtube_result = Mock()
        client.submit_dailymotion_result = Mock()
        return client

    def test_youtube_queue_keeps_priority(self):
        client = self.client()
        client.next_youtube_job.return_value = {"job_id": 1, "player": {"name": "Player"}, "match": {"match_id": "123"}}
        self.assertTrue(client.process_once())
        client.youtube_uploader.upload.assert_called_once()
        client.next_dailymotion_job.assert_not_called()

    def test_manual_fallback_works_even_when_youtube_kill_switch_is_off(self):
        client = self.client(youtube_enabled=False)
        client.next_dailymotion_job.return_value = {"job_id": 2, "player": {"name": "Player"}, "match": {"match_id": "123"}}
        self.assertTrue(client.process_once())
        client.next_youtube_job.assert_not_called()
        client.dailymotion_uploader.upload.assert_called_once()

    def test_dailymotion_disabled_does_not_claim_any_fallback(self):
        client = self.client(dailymotion_enabled=False)
        self.assertFalse(client.process_once())
        client.next_dailymotion_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
