"""Nested EFMI layouts must be proven along the real call chain, not refused.

The EFMI generator attaches draws through a callback ref and binds buffers in a parent
CommandList with per-LOD branches. The checker has to follow that chain, keep branch
bindings apart, and still reject a gate that lets another LOD reach the replacement.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_sheer_delivery import SCRIPT, digest, write_delivery

NESTED_HEAD = '''[TextureOverrideBody]
$present = 1
if $mod_enabled && DRAW_TYPE == 4
  CommandList\\EFMIv1\\Callback_Component_DrawCustom = ref CommandListDrawBody
endif
[CommandListDrawBody]
ib = ref Resource_Body_Index
if $lod_level == 0
  vb0 = ref Resource_Body_Position
  vb1 = ref Resource_Body_Texcoord
elif $lod_level == 1
  vb0 = ref Resource_Body_Position
  vb1 = ResourceOtherUV
endif
run = CommandListDrawInner
[CommandListDrawInner]
x180 = 1
if $colour == 0
  run = CommandListSheer
endif
x180 = 0
'''


class NestedLayoutTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('delivery_nested', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ini, self.shaders, self.report = write_delivery(self.root)
        text = self.ini.read_text(encoding='utf-8')
        head, tail = text.split('[TextureOverrideBody]', 1)
        tail = tail.split('[CommandListSheer]', 1)[1]
        text = (head.replace('global $present = 0', 'global $present = 0\nglobal $mod_enabled = 1\nglobal $lod_level = 0')
                + NESTED_HEAD + '[CommandListSheer]' + tail)
        text = text.replace('if vs == 12 && ps == 34', 'if $lod_level == 0 && vs == 12 && ps == 34')
        (self.root / 'other_uv.buf').write_bytes(b'different UV data')
        text += '[ResourceOtherUV]\nfilename = other_uv.buf\n'
        self.ini.write_text(text, encoding='utf-8')
        # The author's original: the draw sits where the run now sits, and the file repeats
        # [Constants] the way EFMI's merged-skeleton template does.
        self.original = self.root / 'source.ini'
        self.original.write_text(text.replace('  run = CommandListSheer\n', '  drawindexed = 3,0,0\n')
                                 + '[Constants]\nglobal $merged = 0\n', encoding='utf-8')
        report = json.loads(self.report.read_text(encoding='utf-8'))
        report['ini'] = {'path': str(self.original), 'sha256': digest(self.original)}
        self.report.write_text(json.dumps(report), encoding='utf-8')

    def check(self, original=None):
        return self.module.check_delivery(self.ini, self.shaders, self.report, 'B', 233, None, original)

    def replace(self, old, new):
        text = self.ini.read_text(encoding='utf-8')
        self.assertIn(old, text)
        self.ini.write_text(text.replace(old, new), encoding='utf-8')

    def test_nested_chain_with_lod_gate_passes_and_reports_path(self):
        result = self.check(self.original)
        self.assertEqual(result['errors'], [])
        self.assertTrue(any('D10 路径' in note and '[textureoverridebody]' in note for note in result['notes']))

    def test_other_lod_branch_reaching_replacement_is_rejected(self):
        self.replace('if $lod_level == 0 && vs == 12 && ps == 34', 'if vs == 12 && ps == 34')
        errors = self.check(self.original)['errors']
        self.assertTrue(any('D28' in error and '$lod_level == 1' in error for error in errors))
        self.assertFalse(any('D10' in error for error in errors))

    def test_in_place_replacement_is_checked_against_original(self):
        self.assertFalse(any('D29' in error for error in self.check(self.original)['errors']))
        self.replace('x180 = 1\nif $colour == 0', 'x180 = 1\nx181 = 1\nif $colour == 0')
        self.assertTrue(any('D29' in error for error in self.check(self.original)['errors']))
        self.assertTrue(any('D29' in note for note in self.check()['notes']))

    def test_duplicate_section_in_original_does_not_break_identity(self):
        self.assertFalse(any('D25' in error for error in self.check()['errors']))

    def test_unreachable_controller_is_d10(self):
        self.replace('ref CommandListDrawBody', 'ref CommandListNowhere')
        self.assertTrue(any('D10' in error for error in self.check()['errors']))


if __name__ == '__main__':
    unittest.main()
