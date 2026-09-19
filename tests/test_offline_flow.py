"""Run original B/C inputs through preview, bake, generation, checking and ZIP."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from offline_fixture import create_case

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


@unittest.skipUnless(os.name == 'nt', 'Full shader compilation needs Windows d3dcompiler')
class OfflineFlowTests(unittest.TestCase):
    def command(self, script, *args):
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / script), *map(str, args)],
                                capture_output=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def run_route(self, route):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            facts = create_case(root, route)
            preview = root / 'work/preview'
            self.command('diff_texture_variants.py', '--bare', facts['body_texture'],
                         '--variant', facts['stocking_texture'])
            self.command('stocking_preview.py', '--ini', facts['ini'], '--out-dir', preview,
                         '--piece', 'target', 'Stock', facts['stocking_draw'], facts['stocking_texture'],
                         '--piece', 'skin', 'Body', facts['body_draw'], facts['body_texture'],
                         '--size', 64, '--address-mode', 'clamp')
            overlay = root / 'work/overlay'
            shutil.copytree(root / 'source', overlay)
            texture = 'Bare.dds'
            if route == 'C':
                texture = 'SheerSkin.dds'
                self.command('bake_skin_to_stocking_uv.py', '--ini', facts['ini'],
                             '--stocking', 'Stock', '--stocking-draw', facts['stocking_draw'],
                             '--body', 'Body', '--body-draw', facts['body_draw'],
                             '--body-tex', facts['body_texture'], '--out', overlay / texture,
                             '--size', 64, '--body-tint-linear', '1,1,1')
                # The target UV is mirrored; a pink patch must transfer to the other side.
                from PIL import Image
                import numpy as np
                baked = np.asarray(Image.open(overlay / texture).convert('RGB'))
                self.assertGreater(int(baked[30, 24, 0]), int(baked[30, 40, 0]))
            shader_dir = overlay / 'shaders'
            args = ['--skin-slot', 't90', '--skin-slot-kind', 'bareleg' if route == 'B' else 'baked']
            if route == 'B':
                args += ['--skin-tint-source', 'shared', '--spec-stocking-only']
            cache = root / 'work' / 'compile-cache'
            built = self.command('build_sheer_ps.py', facts['fixed'], '--out-dir', shader_dir,
                         '--name', 'main', '--state', 'dark', '--state', 'light',
                         '--style-index', 233, *facts['mapping'], *args,
                         '--compiler', 'd3dcompiler', '--compile-cache', cache)
            self.assertEqual(built.count('未命中或损坏'), 3)
            ini = overlay / 'case.ini'
            text = ini.read_text(encoding='utf-8').replace('[Constants]', '[Constants]\nglobal $style = 0\nglobal $debug = 0')
            text = text.replace('drawindexed = 6,0,0', 'run = CommandListSheer')
            text += '''
[CommandListSheer]
x233 = $style
if vs == 202 && ps == 1718.1
  if $debug == 1
    run = CustomShaderProbe
  elif $colour == 0
    run = CustomShaderDark
  elif $colour == 1
    run = CustomShaderLight
  else
    drawindexed = 6,0,0
  endif
else
  drawindexed = 6,0,0
endif
'''
            for name, tag in [('Dark', 'dark'), ('Light', 'light'), ('Probe', 'probe')]:
                text += f'\n[CustomShader{name}]\nps = shaders/main_{tag}.hlsl\nps-t90 = ResourceSkin\ndrawindexed = 6,0,0\n'
            text += f'\n[ResourceSkin]\nfilename = {texture}\n'
            text += '\n[KeyStyle]\ncondition = $object_detected == 1\nkey = ctrl alt no_shift VK_OEM_PERIOD\ntype = cycle\n$style = 0,1\n'
            ini.write_text(text, encoding='utf-8')
            result = self.command('check_sheer_delivery.py', '--ini', ini,
                                  '--shader', shader_dir / 'main_dark.hlsl', '--shader', shader_dir / 'main_light.hlsl',
                                  '--colour-report', preview / 'colour_detection.json',
                                  '--source-route', route, '--style-index', 233, '--compile-cache', cache)
            self.assertIn('PASS', result)
            self.assertEqual(result.count('命中，复用字节码'), 2)
            for state in ('dark', 'light'):
                reflected = self.command('reflect_check.py', shader_dir / f'main_{state}.hlsl',
                             '--original', facts['fixed'], '--require', 't90', 't120',
                             '--out', root / 'work' / f'reflect_{state}',
                             '--compiler', 'd3dcompiler', '--compile-cache', cache)
                self.assertGreaterEqual(reflected.count('命中，复用字节码'), 2)
            archive = root / 'work/delivery.zip'
            self.command('pack_mod.py', '--src', root / 'source', '--overlay', overlay,
                         '--name', 'Fixture', '--out', archive)
            with zipfile.ZipFile(archive) as packed:
                self.assertEqual(packed.read('Fixture/case.ini'), ini.read_bytes())
                self.assertEqual(packed.read('Fixture/' + texture), (overlay / texture).read_bytes())

    def test_bareleg_flow(self):
        self.run_route('B')

    def test_different_uv_bake_flow(self):
        self.run_route('C')


if __name__ == '__main__':
    unittest.main()
