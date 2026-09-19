import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np

spec = importlib.util.spec_from_file_location('preview', Path(__file__).resolve().parents[1] / 'scripts' / 'stocking_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class NativeColourTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((64, 64, 3), 127, dtype=np.uint8)
        self.uv = np.array([[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
        self.ib = np.array([0, 1, 2, 0, 2, 3])

    def check_colour(self, **kwargs):
        return preview.detect_native_colour(self.image, self.ib, self.uv, **kwargs)

    def test_uniform(self):
        result = self.check_colour()
        self.assertEqual(result['status'], 'uniform_diffuse')
        self.assertTrue(result['complete'])
        self.assertFalse(result['requires_spatial_colour'])

    def test_single_level_mark_with_unchanged_median(self):
        self.image[32, 32, 0] += 1
        self.assertEqual(np.median(self.image[:, :, 0]), 127)
        result = self.check_colour()
        self.assertEqual(result['status'], 'nonuniform')
        self.assertTrue(result['requires_spatial_colour'])

    def test_outside_island_is_excluded(self):
        self.image[:8] = 0
        self.assertEqual(self.check_colour()['status'], 'uniform_diffuse')

    def test_partial_sampling_cannot_prove_uniform(self):
        result = self.check_colour(complete=False)
        self.assertEqual(result['status'], 'unknown')
        self.assertTrue(result['requires_spatial_colour'])

    def test_out_of_range_uv_is_unknown(self):
        self.uv[0, 0] = -0.1
        self.assertEqual(self.check_colour()['status'], 'unknown')

    def test_thin_triangle_between_pixel_centres(self):
        self.uv = np.array([[0.3, 0.3], [0.3001, 0.7], [0.3002, 0.3]])
        self.ib = np.array([0, 1, 2])
        self.image[25, 19, 1] = 200
        self.assertEqual(self.check_colour()['status'], 'nonuniform')

    def test_high_precision_dds_cannot_prove_uniform(self):
        header = dict(fmt='RGBA16F', w=64, h=64)
        with patch.object(preview.V, 'dds_header', return_value=header):
            self.assertFalse(preview.native_precision_preserved(Path('texture.dds'), (64, 64)))

    def test_supported_dds_must_keep_native_dimensions(self):
        header = dict(fmt='BC7_SRGB', w=64, h=64)
        with patch.object(preview.V, 'dds_header', return_value=header):
            self.assertTrue(preview.native_precision_preserved(Path('texture.dds'), (64, 64)))
            self.assertFalse(preview.native_precision_preserved(Path('texture.dds'), (32, 32)))

    def test_bilinear_neighbour_outside_triangle_is_included(self):
        self.uv = np.array([[10.1, 10.1], [10.3, 10.1], [10.1, 10.3]]) / 64
        self.ib = np.arange(3)
        self.image[10, 9, 0] = 200
        self.assertEqual(self.check_colour()['status'], 'nonuniform')

    def test_unproven_addressing_never_proves_uniform(self):
        for mode in ('unknown', 'wrap', 'mirror'):
            with self.subTest(mode=mode):
                result = self.check_colour(address_mode=mode)
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['addressing'], mode)

    def test_dynamic_sampling_never_proves_uniform(self):
        self.assertEqual(self.check_colour(dynamic_sampling=True)['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
