"""Mandatory highlight switching tests use only an original synthetic shader."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from synthetic_fixture import write_fixed


class HighlightTests(unittest.TestCase):
    def test_public_cli_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixed = root / 'fixture.fixed.hlsl'
            mapping = ['--style-index', '233', *write_fixed(fixed)]
            cases = [('missing', [], 2), ('exclusive', mapping + ['--no-style-switch'], 2),
                     ('mapping', ['--style-index', '233'], 1),
                     ('index', ['--style-index', '4096'], 1)]
            cases += [('gain' + str(n), mapping + ['--state', 'white:SPEC_GAIN=' + value], 1)
                      for n, value in enumerate(['0', '-1', 'nan', 'inf', '1e999', '1e-999', '1e100', '1e-50'])]
            cases += [('switch', mapping + ['--state', 'black', '--state', 'white:SPEC_GAIN=0.8',
                                           '--state', 'numeric:SPEC_GAIN=1_0'], 0),
                      ('optout', ['--no-style-switch', '--normal-input', 'v3', '--tangent-input', 'v4'], 0)]
            for name, args, expected in cases:
                with self.subTest(name=name):
                    out = root / name
                    command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/build_sheer_ps.py'),
                               str(fixed), '--out-dir', str(out), '--name', 'test', '--skin', '0.6,0.4,0.3', *args]
                    if name != 'switch' or os.name != 'nt':
                        command.append('--no-compile')
                    result = subprocess.run(command, capture_output=True, encoding='utf-8',
                                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    if expected:
                        self.assertFalse(out.exists())
                    elif name == 'switch':
                        for tag, gain in [('black', '1.0'), ('white', '0.8'), ('numeric', '10.0')]:
                            text = (out / ('test_' + tag + '.hlsl')).read_text(encoding='utf-8-sig')
                            self.assertRegex(text, '#define +SHEER_SPEC_GAIN +' + gain)
                            self.assertIn('.Load(int2(233, 0)).x > 0.5', text)
                            self.assertIn('SHEER_SPEC_GAIN * _shLook', text)
                    else:
                        self.assertNotIn('_shLook', (out / 'test_default.hlsl').read_text(encoding='utf-8-sig'))
