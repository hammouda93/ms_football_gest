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
        self.assertGreaterEqual(page.polls, 2)

    def test_partial_upload_text_is_not_a_completion_signal(self):
        for message in ("Uploading 94%", "Video uploaded 94%", "Upload 99%"):
            page = FakeUploadPage([
                {"percent": "94", "uploading": True, "status": message}
            ])
            self.assertFalse(self.uploader._upload_completion_detected(page))
