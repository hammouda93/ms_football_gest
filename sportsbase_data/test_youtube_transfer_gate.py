"""Regression tests: YouTube transfer must finish before publication."""
from django.test import SimpleTestCase

from .youtube_uploader import YouTubeStudioUploader, YouTubeUploadError


class FakeUploadProgress:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def get_attribute(self, key):
        if key == "uploading":
            return "true" if self.page.sample["uploading"] else None
        if key == "aria-valuenow":
            return self.page.sample["percent"]
        return None

    def locator(self, selector):
        return FakeProgressLabel(self.page) if selector == ".progress-label" else FakeProgressBar(self.page)

    def inner_text(self):
        return self.page.sample["status"]


class FakeProgressLabel:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def inner_text(self):
        return self.page.sample["status"]


class FakeProgressBar:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, key):
        return self.page.sample["percent"] if key == "aria-valuenow" else None


class FakeProgressHosts:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1

    def nth(self, _index):
        return FakeUploadProgress(self.page)


class FakeUploadPage:
    def __init__(self, samples, *, close_after=None):
        self.samples = samples
        self.index = 0
        self.polls = 0
        self.close_after = close_after

    @property
    def sample(self):
        return self.samples[min(self.index, len(self.samples) - 1)]

    def is_closed(self):
        return self.close_after is not None and self.polls >= self.close_after

    def locator(self, selector):
        if selector == "ytcp-video-upload-progress":
            return FakeUploadProgress(self)
        return FakeProgressHosts(self)

    def wait_for_timeout(self, _milliseconds):
        self.polls += 1
        self.index += 1


class YouTubeTransferGateTests(SimpleTestCase):
    def setUp(self):
        self.uploader = object.__new__(YouTubeStudioUploader)
        self.uploader.upload_timeout_ms = 10000

    def test_100_percent_while_still_uploading_cannot_finish(self):
        page = FakeUploadPage([
            {"percent": "94", "uploading": True, "status": "Uploading 94%"},
            {"percent": "99", "uploading": True, "status": "Uploading 99%"},
            {"percent": "100", "uploading": True, "status": "Uploading 100%"},
            {"percent": "100", "uploading": False, "status": "Uploading 100%"},
            {"percent": "100", "uploading": False, "status": "Uploading 100%"},
            {"percent": "100", "uploading": False, "status": "Uploading 100%"},
        ])
        self.uploader._wait_upload_transfer_complete(page)
        self.assertGreaterEqual(page.polls, 5)

    def test_interrupted_transfer_raises_instead_of_succeeding(self):
        page = FakeUploadPage(
            [{"percent": "94", "uploading": True, "status": "Uploading 94%"}],
            close_after=3,
        )
        with self.assertRaisesRegex(YouTubeUploadError, "Chrome"):
            self.uploader._wait_upload_transfer_complete(page)

    def test_explicit_upload_complete_message_can_finish(self):
        page = FakeUploadPage([
            {"percent": "", "uploading": False,
             "status": "Upload complete. Processing will begin shortly"}
        ])
        self.uploader._wait_upload_transfer_complete(page)
        # A single completion message is enough: it may disappear next poll.
        self.assertEqual(page.polls, 0)

    def test_complete_message_not_lost_when_checking_replaces_it(self):
        page = FakeUploadPage([
            {"percent": "", "uploading": True,
             "status": "Upload complete ... Processing will begin shortly"},
            {"percent": "", "uploading": True,
             "status": "Processing up to HD ... 3 minutes left"},
            {"percent": "", "uploading": True,
             "status": "Checking 0% ... 10 minutes left"},
        ])
        self.uploader._wait_upload_transfer_complete(page)
        self.assertEqual(page.polls, 0)

    def test_checking_percent_alone_is_not_transfer_completion(self):
        page = FakeUploadPage(
            [{"percent": "", "uploading": True,
              "status": "Checking 6% ... 5 minutes left"}],
            close_after=3,
        )
        with self.assertRaisesRegex(YouTubeUploadError, "Chrome"):
            self.uploader._wait_upload_transfer_complete(page)

    def test_partial_upload_text_is_not_a_completion_signal(self):
        for message in ("Uploading 94%", "Video uploaded 94%", "Upload 99%"):
            page = FakeUploadPage([
                {"percent": "94", "uploading": True, "status": message}
            ])
            self.assertFalse(self.uploader._upload_completion_detected(page))


class FakeVideoProcessingClose:
    def __init__(self, dialog):
        self.dialog = dialog
        self.click_count = 0

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self):
        return self.dialog.visible

    def is_enabled(self):
        return True

    def click(self, **_kwargs):
        self.click_count += 1
        self.dialog.visible = False


class FakeVideoProcessingDialog:
    def __init__(self):
        self.visible = True
        self.button = FakeVideoProcessingClose(self)
        self.hidden_waited = False

    def is_visible(self):
        return self.visible

    def locator(self, _selector):
        return self.button

    def get_by_role(self, _role, **_kwargs):
        return self.button

    def wait_for(self, *, state, timeout):
        self.hidden_waited = state == "hidden" and timeout == 15000
        assert not self.visible


class FakeVideoProcessingDialogs:
    def __init__(self, dialog):
        self.dialog = dialog

    def count(self):
        return 1

    def nth(self, _index):
        return self.dialog


class FakeVideoProcessingPage:
    def __init__(self):
        self.dialog = FakeVideoProcessingDialog()
        self.waits = 0

    def locator(self, _selector):
        return FakeVideoProcessingDialogs(self.dialog)

    def wait_for_timeout(self, _ms):
        self.waits += 1


class YouTubeProcessingCloseTests(SimpleTestCase):
    def test_close_processing_modal_without_waiting_for_checks(self):
        page = FakeVideoProcessingPage()
        closed = YouTubeStudioUploader._close_video_processing_dialog(
            page, timeout_ms=1000
        )
        self.assertTrue(closed)
        self.assertEqual(page.dialog.button.click_count, 1)
        # The Close click is sufficient; do not wait for SD/HD processing.
        self.assertFalse(page.dialog.visible)
        self.assertFalse(page.dialog.hidden_waited)
        self.assertEqual(page.waits, 0)

    def test_no_processing_modal_is_harmless(self):
        class MissingDialogs:
            def count(self):
                return 0

        class MissingPage:
            def locator(self, _selector):
                return MissingDialogs()

            def wait_for_timeout(self, _milliseconds):
                return None

        self.assertFalse(
            YouTubeStudioUploader._close_video_processing_dialog(
                MissingPage(), timeout_ms=0
            )
        )


class YouTubeFinishAfterCloseTests(SimpleTestCase):
    def test_close_processing_goes_directly_to_uploaded_path(self):
        uploader = object.__new__(YouTubeStudioUploader)
        calls = []
        uploader._publish_anyway_if_prechecks_pending = (
            lambda _page: calls.append("publish_if_present")
        )
        uploader._close_video_processing_dialog = (
            lambda _page: calls.append("close") or True
        )
        uploader._wait_upload_dialog_closed = (
            lambda *_args, **_kwargs: self.fail(
                "Already closed: do not wait for other dialogs"
            )
        )
        uploader._wait_for_studio_publication = (
            lambda *_args: self.fail(
                "Processing modal closed: do not wait for SD/HD processing"
            )
        )

        uploader._complete_saved_upload(
            object(), object(), "CuK3Na4aLgw", "unlisted"
        )
        self.assertEqual(calls, ["publish_if_present", "close"])

    def test_no_processing_modal_and_no_publish_anyway_does_not_block(self):
        uploader = object.__new__(YouTubeStudioUploader)
        calls = []
        uploader._publish_anyway_if_prechecks_pending = (
            lambda _page: calls.append("publish_absent") or False
        )
        uploader._close_video_processing_dialog = (
            lambda _page: calls.append("close_absent") or False
        )
        uploader._wait_for_studio_publication = (
            lambda *_args: self.fail("SD/HD must not block a saved upload")
        )

        self.assertTrue(uploader._complete_saved_upload(
            object(), object(), "EfUDnSY4Es0", "unlisted"
        ))
        self.assertEqual(calls, ["publish_absent", "close_absent"])

    def test_missing_close_button_does_not_fail_after_save(self):
        uploader = object.__new__(YouTubeStudioUploader)
        page = FakeVideoProcessingPage()
        page.dialog.button.is_visible = lambda: False
        uploader._publish_anyway_if_prechecks_pending = lambda _page: True

        self.assertTrue(uploader._complete_saved_upload(
            page, object(), "EfUDnSY4Es0", "unlisted"
        ))
        self.assertEqual(page.dialog.button.click_count, 0)

    def test_publish_confirmation_error_still_raises(self):
        uploader = object.__new__(YouTubeStudioUploader)
        def fail_publish(_page):
            raise YouTubeUploadError("Publish anyway confirmation failed")
        uploader._publish_anyway_if_prechecks_pending = fail_publish
        uploader._close_video_processing_dialog = (
            lambda _page: self.fail("Do not ignore Publish errors")
        )

        with self.assertRaisesRegex(YouTubeUploadError, "confirmation failed"):
            uploader._complete_saved_upload(
                object(), object(), "EfUDnSY4Es0", "unlisted"
            )
