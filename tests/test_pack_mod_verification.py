"""Ensure one archive pass covers source integrity as well as valid ZIP structure."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pack_mod import verify_archive


class ArchiveVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'texture.bin'
        self.source.write_bytes(b'abcd' * 300000)
        self.archive = self.root / 'mod.zip'
        with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as packed:
            packed.write(self.source, 'Mod/texture.bin')
        self.files = {'texture.bin': self.source}

    def test_matching_source_larger_than_chunk(self):
        self.assertEqual(verify_archive(self.archive, 'Mod', self.files, 1200000), (1, 1200000))

    def test_same_size_source_change_is_rejected(self):
        self.source.write_bytes(b'zzzz' * 300000)
        with self.assertRaisesRegex(ValueError, '源字节'):
            verify_archive(self.archive, 'Mod', self.files, 1200000)

    def test_unexpected_entry_is_rejected(self):
        with zipfile.ZipFile(self.archive, 'a') as packed:
            packed.writestr('Mod/extra.ini', 'unexpected')
        with self.assertRaisesRegex(ValueError, '条目'):
            verify_archive(self.archive, 'Mod', self.files, 1200000)

    def test_total_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '总字节'):
            verify_archive(self.archive, 'Mod', self.files, 1200001)
