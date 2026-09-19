"""Old or malformed reports must give a repair action instead of a traceback."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DeliveryInputErrors(unittest.TestCase):
    def test_malformed_report_shapes_have_actionable_error(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/check_sheer_delivery.py'
        cases = [[], None, {'schema_version': 2, 'pieces': 'wrong'},
                 {'schema_version': 2, 'ini': [], 'pieces': [{}]},
                 {'schema_version': 2, 'ini': {}, 'pieces': [3]},
                 {'schema_version': 2, 'ini': {}, 'pieces': [{'inputs': []}]}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ini, shader, report = root / 'mod.ini', root / 'main.hlsl', root / 'report.json'
            ini.write_text('[Constants]\nglobal $style = 0\n', encoding='utf-8')
            shader.write_text('// only input shape is exercised', encoding='utf-8')
            for payload in cases:
                with self.subTest(payload=payload):
                    report.write_text(json.dumps(payload), encoding='utf-8')
                    result = subprocess.run([sys.executable, '-B', str(script), '--ini', str(ini),
                                             '--shader', str(shader), '--colour-report', str(report),
                                             '--source-route', 'B', '--style-index', '233'],
                                            capture_output=True, encoding='utf-8',
                                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('Traceback', result.stdout + result.stderr)
                    self.assertIn('D02', result.stdout)
                    self.assertIn('preview', result.stdout)


if __name__ == '__main__':
    unittest.main()
