"""Colour-space regressions use synthetic, freely reproducible images."""
import pathlib
import struct
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import bake_skin_to_stocking_uv as bake


class TextureColourTests(unittest.TestCase):
    def test_png_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'gray.png'
            Image.new('RGB', (1, 1), (128, 128, 128)).save(path)
            pixels, srgb = bake.texture_1024(path)
            linear = bake.s2l(pixels) if srgb else pixels
            self.assertAlmostEqual(float(linear[0, 0, 0]), .2158605, places=5)

    def test_shared_metadata_and_override(self):
        from texture_colour import load_colour_texture, linear_to_srgb
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'gray.png'
            Image.new('RGB', (1, 1), (128, 128, 128)).save(path)
            linear, meta = load_colour_texture(path)
            self.assertEqual(meta['colour_space'], 'srgb')
            self.assertEqual(meta['native_size'], [1, 1])
            self.assertEqual(round(float(linear_to_srgb(linear)[0, 0, 0]) * 255), 128)
            raw, _ = load_colour_texture(path, 'linear')
            self.assertAlmostEqual(float(raw[0, 0, 0]), 128 / 255)

    def test_dx10_srgb_and_unorm(self):
        from texture_colour import load_colour_texture
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'gray.dds'
            bake.write_dds(path, [np.full((1, 1, 4), 128, dtype=np.uint8)])
            linear, meta = load_colour_texture(path)
            self.assertAlmostEqual(float(linear[0, 0, 0]), .2158605, places=5)
            data = bytearray(path.read_bytes()); struct.pack_into('<I', data, 128, 28)
            path.write_bytes(data)
            raw, meta = load_colour_texture(path)
            self.assertEqual(meta['colour_space'], 'linear')
            self.assertAlmostEqual(float(raw[0, 0, 0]), 128 / 255)

    def test_legacy_dds_needs_explicit_space(self):
        from texture_colour import load_colour_texture
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'legacy.dds'
            Image.new('RGB', (4, 4), (128, 128, 128)).save(path)
            with self.assertRaisesRegex(ValueError, 'COLOUR_SPACE_REQUIRED'):
                load_colour_texture(path)
            linear, _ = load_colour_texture(path, 'srgb')
            self.assertAlmostEqual(float(linear[0, 0, 0]), .2158605, places=5)

    def test_png_and_srgb_dds_have_identical_linear_samples(self):
        from texture_colour import load_colour_texture
        import stocking_preview as preview
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            pixels = np.array([[[0, 0, 0], [128, 128, 128]], [[255, 255, 255], [64, 64, 64]]], dtype=np.uint8)
            Image.fromarray(pixels).save(folder / 'input.png')
            bake.write_dds(folder / 'input.dds', [np.dstack([pixels, np.full((2, 2), 255, dtype=np.uint8)])])
            png, _ = load_colour_texture(folder / 'input.png')
            dds, _ = load_colour_texture(folder / 'input.dds')
            np.testing.assert_equal(png, dds)
            resized, encoded = preview.load_texture(folder / 'input.png', 1)
            self.assertFalse(encoded)
            np.testing.assert_allclose(resized[0, 0], png.mean((0, 1)), atol=1e-7)


if __name__ == '__main__':
    unittest.main()
