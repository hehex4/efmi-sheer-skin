"""Check real compiler reuse and conservative invalidation without game files."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import d3dc
import compile_cache


@unittest.skipUnless(os.name == 'nt', 'Requires the native D3D compiler')
class CompileCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sheer_cache_')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'test.hlsl'
        self.src.write_text('float4 main() : SV_Target { return 1; }', encoding='utf-8')
        self.cache = self.root / 'cache'

    def run_compile(self, **kwargs):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = d3dc.compile_file(self.src, compile_cache=self.cache, **kwargs)
        return result, stream.getvalue()

    def test_real_compile_called_once_and_listing_regenerated(self):
        lib, _ = d3dc.load()
        with mock.patch.object(lib, 'D3DCompile', wraps=lib.D3DCompile) as native:
            first, _ = self.run_compile()
            second, log = self.run_compile(out_asm=self.root / 'new.asm')
            self.assertTrue(first.ok and second.ok)
            self.assertEqual(native.call_count, 1)
            self.assertEqual(first.bytecode, second.bytecode)
            self.assertEqual(second.listing, d3dc.disassemble(first.bytecode))
            self.assertIn('命中，复用', log)

    def test_source_options_and_compiler_identity_invalidate(self):
        self.run_compile()
        for options in ({'flags': 0}, {'flags2': 1}, {'defines': ['X=1']},
                        {'target': 'ps_4_0'}, {'entry': 'missing'}):
            with self.subTest(options=options):
                _, log = self.run_compile(**options)
                self.assertNotIn('命中，复用', log)
        self.src.write_text('float4 main() : SV_Target { return 0; }', encoding='utf-8')
        _, log = self.run_compile()
        self.assertNotIn('命中，复用', log)
        with mock.patch.object(compile_cache, 'compiler_identity', return_value={'dll': 'changed'}):
            _, log = self.run_compile()
            self.assertNotIn('命中，复用', log)

    def test_include_changes_never_reuse(self):
        include = self.root / 'colour.h'
        include.write_text('#define COLOUR 1', encoding='utf-8')
        self.src.write_text('#include "colour.h"\nfloat4 main() : SV_Target { return COLOUR; }', encoding='utf-8')
        first, _ = self.run_compile()
        include.write_text('#define COLOUR 0', encoding='utf-8')
        second, log = self.run_compile()
        self.assertTrue(first.ok and second.ok)
        self.assertNotEqual(first.bytecode, second.bytecode)
        self.assertIn('含 include', log)
        self.assertFalse(self.cache.exists())

    def test_corrupt_missing_and_failed_inputs_recompile(self):
        first, _ = self.run_compile()
        entry = next(self.cache.glob('*.json'))
        entry.write_text('{"bytecode":"broken"}', encoding='utf-8')
        repaired, log = self.run_compile()
        self.assertEqual(first.bytecode, repaired.bytecode)
        self.assertIn('未命中或损坏', log)
        entry.unlink()
        _, log = self.run_compile()
        self.assertIn('未命中或损坏', log)
        self.src.write_text('invalid shader', encoding='utf-8')
        before = set(self.cache.glob('*.json'))
        for _ in range(2):
            result, log = self.run_compile()
            self.assertFalse(result.ok)
            self.assertNotIn('命中，复用', log)
        self.assertEqual(before, set(self.cache.glob('*.json')))

    def test_source_path_and_no_cache_are_conservative(self):
        self.run_compile()
        other = self.root / 'other.hlsl'
        other.write_bytes(self.src.read_bytes())
        self.src = other
        _, log = self.run_compile()
        self.assertNotIn('命中，复用', log)
        lib, _ = d3dc.load()
        with mock.patch.object(lib, 'D3DCompile', wraps=lib.D3DCompile) as native:
            d3dc.compile_file(self.src)
            d3dc.compile_file(self.src)
            self.assertEqual(native.call_count, 2)

    def test_temporal_macros_in_source_and_arguments_never_reuse(self):
        for name in ('__DATE__', '__TIME__', '__TIMESTAMP__'):
            for source, defines in ((name.encode(), None), (b'plain', ['VALUE=' + name]),
                                    (b'plain', {'VALUE': name})):
                with self.subTest(name=name, defines=defines):
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        ticket = compile_cache.prepare(self.cache, self.src, source, {},
                                                       'main', 'ps_5_0', defines, 0, 0)
                    self.assertIsNone(ticket)
                    self.assertIn('时变预定义宏', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
