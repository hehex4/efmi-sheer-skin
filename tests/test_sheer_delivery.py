"""Reject incomplete deliveries through a reproducible INI and shader fixture."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from synthetic_fixture import write_fixed
import subprocess
import sys
import os
import re

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_sheer_delivery.py'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_delivery(root):
    """Return checker inputs; the original source identity is distinct from overlay."""
    source = root / 'source.ini'
    source.write_text('[TextureOverrideBody]\ndrawindexed = 3,0,0\n', encoding='utf-8')
    texture = root / 'skin.dds'
    texture.write_bytes(b'fixture texture')
    ini = root / 'overlay.ini'
    ini.write_text('''[Constants]
global $style = 0
global $debug = 0
global $colour = 0
global $present = 0
[TextureOverrideBody]
ib = Resource_Body_Index
vb0 = Resource_Body_Position
vb1 = Resource_Body_Texcoord
run = CommandListSheer
[CommandListSheer]
x233 = $style
if vs == 12 && ps == 34
  if $debug == 1
    run = CustomShaderProbe
  elif $colour == 0
    run = CustomShaderOne
  elif $colour == 1
    run = CustomShaderTwo
  else
    drawindexed = 3,0,0
  endif
else
  drawindexed = 3,0,0
endif
[CustomShaderOne]
ps = one.hlsl
ps-t90 = ResourceSkin
drawindexed = 3,0,0
[CustomShaderTwo]
ps = two.hlsl
ps-t90 = ResourceSkin
drawindexed = 3,0,0
[CustomShaderProbe]
ps = probe.hlsl
ps-t90 = ResourceSkin
drawindexed = 3,0,0
[ResourceSkin]
filename = skin.dds
[KeyStyle]
condition = $present == 1
key = K
type = cycle
$style = 0,1
''', encoding='utf-8')
    fixed = root / 'fixed.hlsl'
    command = [sys.executable, '-B', str(SCRIPT.parent / 'build_sheer_ps.py'), str(fixed),
               '--out-dir', str(root / 'generated'), '--name', 'test', '--style-index', '233',
               *write_fixed(fixed), '--skin', '0.6,0.4,0.3', '--skin-slot', 't90',
               '--skin-tint-source', 'shared', '--no-compile']
    result = subprocess.run(command, capture_output=True, encoding='utf-8',
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    shader = (root / 'generated/test_default.hlsl').read_text(encoding='utf-8-sig')
    for name in ('one', 'two', 'probe'):
        text = re.sub(r'(ANISO_DEBUG_MODE\s+)0', r'\g<1>1', shader) if name == 'probe' else shader
        (root / (name + '.hlsl')).write_text(text, encoding='utf-8')
    report = root / 'colour.json'
    inputs = {}
    for kind in ('Index', 'Position', 'Texcoord'):
        path = root / (kind + '.buf')
        path.write_bytes(b'mesh fixture ' + kind.encode())
        inputs[kind] = {'path': str(path), 'sha256': digest(path)}
        with ini.open('a', encoding='utf-8') as stream:
            stream.write('[Resource_Body_' + kind + ']\nfilename = ' + path.name + '\n')
        with source.open('a', encoding='utf-8') as stream:
            stream.write('[Resource_Body_' + kind + ']\nfilename = ' + path.name + '\n')
    report.write_text(json.dumps({'schema_version': 2, 'ini': {'path': str(source), 'sha256': digest(source)},
                                 'pieces': [{'label': 'TextureOverrideBody', 'resource': 'Body',
                                             'draw': [3, 0, 0], 'texture': {'path': str(texture), 'sha256': digest(texture)},
                                             'inputs': inputs, 'status': 'nonuniform', 'complete': True,
                                             'addressing': 'clamp'}]}), encoding='utf-8')
    return ini, [root / 'one.hlsl', root / 'two.hlsl'], report


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('delivery', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ini, self.shaders, self.report = write_delivery(self.root)

    def check(self, route='B', index=233):
        return self.module.check_delivery(self.ini, self.shaders, self.report, route, index)

    def replace(self, path, old, new):
        text = path.read_text(encoding='utf-8')
        if old.startswith(('SKIN_FROM_TEX', 'SPEC_GAIN')):
            key, value = old.split()
            text = re.sub(key + r'\s+' + re.escape(value), new, text)
        else:
            text = text.replace(old, new)
        path.write_text(text, encoding='utf-8')

    def test_valid(self):
        self.assertEqual(self.check()['errors'], [])
        self.assertEqual(len(self.check()['reflection_groups']), 1)

    def test_nonuniform_constant(self):
        self.assertTrue(self.check('A')['errors'])

    def test_second_shader_loses_skin(self):
        self.replace(self.shaders[1], 'SKIN_FROM_TEX 1', 'SKIN_FROM_TEX 0')
        self.assertTrue(self.check()['errors'])

    def test_missing_cycle(self):
        self.replace(self.ini, 'type = cycle', 'type = hold')
        self.assertTrue(self.check()['errors'])

    def test_wrong_index(self):
        self.replace(self.ini, 'x233', 'x234')
        self.assertTrue(self.check()['errors'])

    def test_undefined_presence(self):
        self.replace(self.ini, '$present == 1', '$absent == 1')
        self.assertTrue(self.check()['errors'])

    def test_zero_gain(self):
        self.replace(self.shaders[1], 'SPEC_GAIN 1.0', 'SPEC_GAIN 0.0')
        self.assertTrue(self.check()['errors'])

    def test_missing_state_argument(self):
        self.shaders.pop()
        self.assertTrue(self.check()['errors'])

    def test_complex_call_rejected(self):
        self.replace(self.ini, 'x233 = $style', 'run = CommandListOther\nx233 = $style')
        self.assertTrue(self.check()['errors'])

    def test_stale_input_rejected(self):
        (self.root / 'skin.dds').write_bytes(b'changed')
        self.assertTrue(self.check()['errors'])

    def test_actual_uv_binding_cannot_use_stale_report(self):
        (self.root / 'other_uv.buf').write_bytes(b'different UV data')
        with self.ini.open('a', encoding='utf-8') as stream:
            stream.write('[ResourceOtherUV]\nfilename = other_uv.buf\n')
        self.replace(self.ini, 'vb1 = Resource_Body_Texcoord', 'vb1 = ResourceOtherUV')
        self.assertTrue(any('D28' in error for error in self.check()['errors']))

    def test_custom_shader_uv_override_is_checked(self):
        (self.root / 'other_uv.buf').write_bytes(b'different UV data')
        with self.ini.open('a', encoding='utf-8') as stream:
            stream.write('[ResourceOtherUV]\nfilename = other_uv.buf\n')
        self.replace(self.ini, '[CustomShaderTwo]', '[CustomShaderTwo]\nvb1 = ResourceOtherUV')
        self.assertTrue(any('D28' in error for error in self.check()['errors']))

    def test_unproven_inherited_binding_is_not_passed(self):
        self.replace(self.ini, 'vb1 = Resource_Body_Texcoord', '')
        self.assertTrue(any('D28' in error for error in self.check()['errors']))

    def test_binding_after_call_does_not_change_checked_draw(self):
        self.replace(self.ini, 'run = CommandListSheer',
                     'run = CommandListSheer\nvb1 = null')
        self.assertEqual(self.check()['errors'], [])

    def test_draw_spacing_preserved(self):
        self.replace(self.ini, 'drawindexed =', 'drawindexed=')
        self.replace(self.ini, '$style = 0,1', '$style = 0, 1')
        self.assertEqual(self.check()['errors'], [])

    def test_instanced_draw_preserved(self):
        self.replace(self.ini, 'drawindexed = 3,0,0', 'drawindexedinstanced = 3,1,0,0,0')
        self.assertEqual(self.check()['errors'], [])

    def test_c_source_draw_can_differ(self):
        report = json.loads(self.report.read_text(encoding='utf-8'))
        source = dict(report['pieces'][0], label='bare_source', draw=[900, 30, 0])
        report['pieces'].append(source)
        self.report.write_text(json.dumps(report), encoding='utf-8')
        self.assertEqual(self.check('C')['errors'], [])

    def test_explicit_optout(self):
        for path in self.shaders:
            text = path.read_text(encoding='utf-8')
            path.write_text(text.replace(' * _shLook', ''), encoding='utf-8')
        self.assertEqual(self.check(index=None)['errors'], [])

    def test_optimized_away_skin(self):
        self.replace(self.shaders[1], 'SHEER_GAIN         1.0', 'SHEER_GAIN         0.0')
        text = self.shaders[1].read_text(encoding='utf-8')
        self.shaders[1].write_text(re.sub(r'(#define\s+SHEER_GAIN\s+)\S+', r'\g<1>0.0', text), encoding='utf-8')
        self.assertTrue(any('D22' in error for error in self.check()['errors']))
