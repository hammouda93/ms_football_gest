import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from .local_delivery import resolve_existing_actions_file


class LocalDeliveryFileTests(unittest.TestCase):
    def test_non_empty_actions_file_is_reused(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "player_1" / "match_1"
            folder.mkdir(parents=True)
            video = folder / "actions.mp4"
            video.write_bytes(b"video")
            self.assertEqual(
                resolve_existing_actions_file(
                    root,
                    "player_1/match_1",
                    "actions.mp4",
                ),
                video.resolve(),
            )

    def test_windows_folder_key_is_supported(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "player_1" / "match_1"
            folder.mkdir(parents=True)
            video = folder / "actions.mp4"
            video.write_bytes(b"video")
            self.assertEqual(
                resolve_existing_actions_file(
                    root,
                    r"player_1\match_1",
                    "actions.mp4",
                ),
                video.resolve(),
            )

    def test_empty_file_is_not_reused(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "player_1" / "match_1"
            folder.mkdir(parents=True)
            (folder / "actions.mp4").touch()
            self.assertIsNone(
                resolve_existing_actions_file(root, "player_1/match_1", "actions.mp4")
            )

    def test_path_traversal_is_rejected(self):
        with TemporaryDirectory() as directory:
            self.assertIsNone(
                resolve_existing_actions_file(directory, "../outside", "actions.mp4")
            )


if __name__ == "__main__":
    unittest.main()
