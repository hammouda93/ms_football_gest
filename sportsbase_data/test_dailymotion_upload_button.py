"""Regression tests for Studio's French and English upload controls."""

from unittest import TestCase
from unittest.mock import Mock

from .dailymotion_uploader import DailymotionStudioUploader, UPLOAD_LABEL


class DailymotionStudioUploadButtonTests(TestCase):
    @staticmethod
    def _locator(visible=False):
        locator = Mock()
        locator.count.return_value = 1 if visible else 0
        element = locator.nth.return_value
        element.is_visible.return_value = visible
        return locator, element

    def test_supported_upload_labels(self):
        labels = (
            "Upload video",
            "Upload a video",
            "Upload",
            "Ajouter une vidéo",
            "Ajouter des vidéos",
            "Add a video",
            "Add video",
            "Add new video",
        )
        for label in labels:
            with self.subTest(label=label):
                self.assertIsNotNone(UPLOAD_LABEL.fullmatch(label))

    def test_unrelated_button_is_not_upload(self):
        self.assertIsNone(UPLOAD_LABEL.fullmatch("Ajouter une playlist"))

    def test_prefers_existing_accessible_button(self):
        page = Mock()
        button, element = self._locator(visible=True)
        page.get_by_role.return_value = button
        uploader = object.__new__(DailymotionStudioUploader)

        self.assertIs(uploader._upload_button(page), element)
        page.locator.assert_not_called()

    def test_falls_back_to_stable_studio_primary_button(self):
        page = Mock()
        missing, _ = self._locator()
        primary, element = self._locator(visible=True)
        page.get_by_role.return_value = missing
        page.locator.return_value = primary
        uploader = object.__new__(DailymotionStudioUploader)

        self.assertIs(uploader._upload_button(page), element)
        page.locator.assert_called_once_with(
            'button[data-test-id="header-actions-primary-button"]'
        )

    def test_missing_controls_returns_none(self):
        page = Mock()
        missing, _ = self._locator()
        page.get_by_role.return_value = missing
        page.locator.return_value = missing
        uploader = object.__new__(DailymotionStudioUploader)

        self.assertIsNone(uploader._upload_button(page))
