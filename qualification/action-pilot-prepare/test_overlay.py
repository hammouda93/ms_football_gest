"""Reuse lot06 streaming overlay while preserving its already-mounted reader."""
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from slug_overlay import overlay, verify

class PilotOverlayTests(unittest.TestCase):
    def test_existing_reader_is_preserved_and_never_a_replacement(self):
        directory_root = Path(__file__).resolve().parent/'evidence'
        directory_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory_root) as directory:
            original, target = Path(directory)/'base.tgz', Path(directory)/'candidate.tgz'
            with tarfile.open(original, 'w:gz', format=tarfile.GNU_FORMAT) as archive:
                for name, body in {'./app/data_access/engine.py': b'FICTION-reader-preserved', './app/runtime.bin': b'opaque'}.items():
                    member = tarfile.TarInfo(name); member.size = len(body); member.mode = 0o644
                    archive.addfile(member, io.BytesIO(body))
            overlay(original, target, {'app/actions/__init__.py': b''})
            proof = verify(original, target, {'app/actions/__init__.py': b''})
            self.assertEqual(proof['unchangedFiles'], 2)
            with self.assertRaises(ValueError):
                overlay(original, Path(directory)/'bad.tgz', {'app/data_access/engine.py': b'forbidden'})

if __name__ == '__main__': unittest.main(verbosity=2)
