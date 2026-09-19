"""Check independent bareleg tint through the real builder CLI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import re
import importlib.util
from synthetic_fixture import write_fixed

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build_sheer_ps.py'


class SkinColourChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixed = self.root / 'fixture.fixed.hlsl'
        self.mapping = write_fixed(self.fixed)

    def build(self, *args):
        cmd = [sys.executable, '-B', str(SCRIPT), str(self.fixed), '--out-dir',
               str(self.root / 'out'), '--name', 'test', '--no-compile',
               '--style-index', '233', *self.mapping, *args]
        return subprocess.run(cmd, capture_output=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})

    def test_bareleg_requires_explicit_tint(self):
        result = self.build('--skin-slot', 't90')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('TINT01', result.stdout)

    def test_constant_independent_from_stocking_tint(self):
        result = self.build('--skin-slot', 't90', '--skin-tint-source', 'constant',
                            '--skin-tint-linear', '1,0.8,0.7')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = (self.root / 'out/test_default.hlsl').read_text(encoding='utf-8-sig')
        self.assertIn('float3(1.0, 0.8, 0.7) * t90.Sample', text)
        self.assertIn('r3.xyz = cb6[6].xyz * r2.xyz;', text)
        multiplier = re.search(r'_shSkin = float3\(([^)]+)\) \* t90', text).group(1)
        actual = [0.5 * float(x) for x in multiplier.split(',')]
        self.assertEqual(actual, [0.5, 0.4, 0.35])
        self.assertNotEqual(actual, [0.5 * 0.2] * 3)
        self.assertIn('--skin-tint-linear 1,0.8,0.7', text)
        if os.name == 'nt':
            spec = importlib.util.spec_from_file_location('tint_compiler', SCRIPT.parent / 'd3dc.py')
            compiler = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(compiler)
            compiled = compiler.compile_file(self.root / 'out/test_default.hlsl')
            self.assertTrue(compiled.ok, compiled.messages)

    def test_shared_preserves_chain(self):
        result = self.build('--skin-slot', 't90', '--skin-tint-source', 'shared')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('cb6[6].xyz * t90.Sample',
                      (self.root / 'out/test_default.hlsl').read_text(encoding='utf-8-sig'))

    def test_invalid_fixed_tints(self):
        for value in ('nan,1,1', 'inf,1,1', '-1,1,1', '1,1', '1e99,1,1'):
            with self.subTest(value=value):
                result = self.build('--skin-slot', 't90', '--skin-tint-source', 'constant',
                                    '--skin-tint-linear', value)
                self.assertEqual(result.returncode, 1)
                self.assertIn('TINT02', result.stdout)

    def test_baked_never_multiplies_stocking_tint(self):
        result = self.build('--skin-slot', 't90', '--skin-slot-kind', 'baked')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = (self.root / 'out/test_default.hlsl').read_text(encoding='utf-8-sig')
        self.assertIn('float3 _shSkin = t90.Sample', text)


if __name__ == '__main__':
    unittest.main()
