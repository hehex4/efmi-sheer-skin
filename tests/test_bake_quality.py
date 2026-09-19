"""Reject spatial errors before producing a colour average."""
import pathlib
import sys
import unittest
import tempfile
import json
import subprocess
from PIL import Image

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import bake_skin_to_stocking_uv as bake


class BakeQualityTests(unittest.TestCase):
    def setUp(self):
        self.pos = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        self.uv = self.pos[:, :2].copy()
        self.surface = bake.TriangleSurface(self.pos[None], self.uv[None])

    def test_local_far_pixels_rejected(self):
        class LocalGap:
            def sample(self, points):
                distances = np.where(points[:, 0] > .9, .1, 0.)
                return distances, points[:, :2]
        with self.assertRaisesRegex(ValueError, 'DISTANCE_LIMIT'):
            bake.bake_surface(np.arange(3), self.pos, self.uv, LocalGap(), np.ones((2, 2, 3)), 64, 127, 'piece')

    def test_same_piece_overlap_rejected(self):
        class TwoColours:
            def sample(self, points):
                return np.zeros(len(points)), np.stack([points[:, 2], np.zeros(len(points))], axis=1)
        pos = np.concatenate([self.pos, self.pos + [0, 0, 1]])
        uv = np.concatenate([self.uv, self.uv])
        with self.assertRaisesRegex(ValueError, 'UV_COLOUR_CONFLICT'):
            bake.bake_surface(np.arange(6), pos, uv, TwoColours(), np.array([[[0., 0., 0.], [1., 1., 1.]]]), 16, 47, 'piece')

    def test_matching_overlap_is_valid(self):
        acc, count = bake.bake_surface(np.tile(np.arange(3), 2), self.pos, self.uv, self.surface, np.ones((2, 2, 3)), 16, 17, 'piece')
        np.testing.assert_equal(acc[count > 0] / count[count > 0, None], 1)

    def test_rasterize_has_pixel_budget(self):
        acc, count = bake.rasterize(np.arange(3), self.uv, np.ones((3, 3)), 64, batch_pixels=7)
        np.testing.assert_allclose(acc[count > 0] / count[count > 0, None], 1)

    def test_outside_uv_is_rejected(self):
        uv = self.uv.copy(); uv[0, 0] = -.001
        with self.assertRaisesRegex(ValueError, 'UV_RANGE'):
            bake.bake_surface(np.arange(3), self.pos, uv, self.surface, np.ones((2, 2, 3)), 16, 17, 'piece')

    def test_cross_piece_conflict_rejected(self):
        hits = np.ones(4)
        with self.assertRaisesRegex(ValueError, 'CROSS_PIECE_UV_CONFLICT'):
            bake.merge_baked_pieces([(np.zeros((4, 3)), hits), (np.ones((4, 3)), hits)], 2)
        acc, count = bake.merge_baked_pieces([(np.ones((4, 3)), hits)] * 2, 2)
        np.testing.assert_allclose(acc / count[:, None], 1)

    def test_padding_does_not_wrap_across_texture_border(self):
        image = np.zeros((3, 5, 3)); mask = np.zeros((3, 5), dtype=bool)
        image[1, 0] = [1, 0, 0]; image[1, 3] = [0, 0, 1]
        mask[1, 0] = mask[1, 3] = True
        padded = bake.dilate_colour(image, mask, iterations=1)
        np.testing.assert_equal(padded[1, 4], [0, 0, 1])

    def test_distance_error_has_complete_mask_and_triangle(self):
        with self.assertRaises(bake.BakeQualityError) as result:
            bake.bake_surface(np.arange(3), self.pos + [0, 0, .02], self.uv, self.surface, np.ones((2, 2, 3)), 16, 17, 'piece')
        error = result.exception
        self.assertEqual(error.report['distance_exceeded_pixels'], int(error.mask.sum()))
        self.assertEqual(error.report['worst']['triangle'], 0)
        self.assertTrue(error.report['coverage_complete'])

    def test_distance_tolerance_and_explicit_limit(self):
        for distance, limit in ((.0100005, 10), (.02, 20)):
            bake.bake_surface(np.arange(3), self.pos + [0, 0, distance], self.uv, self.surface, np.ones((2, 2, 3)), 16, 17, 'piece', max_distance_mm=limit)

    def test_thin_island_and_shared_edge(self):
        uv = np.array([[.49, 0], [.51, 0], [.51, 1], [.49, 1]])
        pos = np.column_stack([uv, np.zeros(4)])
        surface = bake.TriangleSurface(pos[np.array([[0, 1, 2], [0, 2, 3]])], uv[np.array([[0, 1, 2], [0, 2, 3]])])
        acc, count = bake.bake_surface(np.array([0, 1, 2, 0, 2, 3]), pos, uv, surface, np.ones((2, 2, 3)), 64, 17, 'thin')
        self.assertGreater(int((count > 0).sum()), 0)
        np.testing.assert_allclose(acc[count > 0] / count[count > 0, None], 1)

    def test_cli_tint_once_and_failure_has_no_dds(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            np.arange(3, dtype=np.uint32).tofile(folder / 'ib.buf')
            self.pos.astype(np.float32).tofile(folder / 'pos.buf')
            self.uv.astype(np.float32).tofile(folder / 'uv.buf')
            (folder / 'mod.ini').write_text('\n'.join(['[Resource_M_Index]', 'format=R32_UINT', 'filename=ib.buf', '[Resource_M_Position]', 'stride=12', 'filename=pos.buf', '[Resource_M_Texcoord]', 'stride=8', 'filename=uv.buf']), encoding='utf-8')
            Image.new('RGB', (2, 2), (128, 128, 128)).save(folder / 'body.png')
            args = [sys.executable, '-B', str(pathlib.Path(bake.__file__)), '--ini', str(folder / 'mod.ini'), '--stocking', 'M', '--stocking-draw', '3', '--body', 'M', '--body-draw', '3', '--body-tex', 'body.png', '--body-tex-is-bare', '--size', '16']
            output = folder / 'tinted.dds'
            result = subprocess.run(args + ['--out', str(output), '--body-tint-linear', '1,.8,.7'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            image = np.asarray(Image.open(output))
            expected = np.round(bake.l2s(bake.s2l(np.array([128, 128, 128]) / 255) * [1, .8, .7]) * 255)
            np.testing.assert_allclose(image[1, 1, :3], expected, atol=1)
            invalid = folder / 'invalid.dds'
            result = subprocess.run(args + ['--out', str(invalid), '--body-tint-linear', 'nan,1,1'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(invalid.exists())
            report = json.loads(invalid.with_suffix('.quality.json').read_text(encoding='utf-8'))
            self.assertFalse(report['output_written'])
            self.assertIn('BODY_TINT_INVALID', report['recovery'])

    def test_cli_uv_conflict_writes_mask_instead_of_dds(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            np.arange(6, dtype=np.uint32).tofile(folder / 'ib.buf')
            np.concatenate([self.pos, self.pos + [0, 0, 1]]).astype(np.float32).tofile(folder / 'pos.buf')
            np.concatenate([self.uv, self.uv]).astype(np.float32).tofile(folder / 'stock.uv')
            np.array([[0, 0]] * 3 + [[1, 0]] * 3, dtype=np.float32).tofile(folder / 'body.uv')
            lines = []
            for resource, filename in [('B', 'body.uv'), ('S', 'stock.uv')]:
                lines.extend([f'[Resource_{resource}_Index]', 'format=R32_UINT', 'filename=ib.buf', f'[Resource_{resource}_Position]', 'stride=12', 'filename=pos.buf', f'[Resource_{resource}_Texcoord]', 'stride=8', f'filename={filename}'])
            (folder / 'mod.ini').write_text('\n'.join(lines), encoding='utf-8')
            Image.fromarray(np.array([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)).save(folder / 'body.png')
            output = folder / 'conflict.dds'
            args = [sys.executable, '-B', str(pathlib.Path(bake.__file__)), '--ini', str(folder / 'mod.ini'), '--stocking', 'S', '--stocking-draw', '6', '--body', 'B', '--body-draw', '6', '--body-tex', 'body.png', '--size', '16', '--out', str(output)]
            result = subprocess.run(args, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            report = json.loads(output.with_suffix('.quality.json').read_text(encoding='utf-8'))
            self.assertEqual(report['code'], 'UV_COLOUR_CONFLICT')
            self.assertGreater(report['conflict_pixels'], 0)
            self.assertTrue(pathlib.Path(report['error_mask']).is_file())

    def test_uv_twins_detected_and_one_side_kept(self):
        # Two triangles mirrored across x share one UV footprint; the body colours differ per side.
        pos = np.concatenate([self.pos, self.pos * [-1, 1, 1] + [-2, 0, 0]])
        uv = np.concatenate([self.uv, self.uv])
        sib = np.arange(6)
        groups = bake.find_uv_twins(sib, uv, 16)
        self.assertEqual([sorted(g) for g in groups], [[0, 1]])
        kept, keep, info = bake.choose_twin_side(groups, pos, sib, 'auto')
        self.assertEqual((info['axis'], info['side'], info['dropped_triangles']), ('x', '+', 1))
        np.testing.assert_equal(kept, np.arange(3))
        kept, keep, info = bake.choose_twin_side(groups, pos, sib, 'x-')
        np.testing.assert_equal(kept, np.arange(3, 6))
        self.assertEqual(bake.find_uv_twins(np.arange(3), self.uv, 16), [])

    def test_cli_uv_twins_explain_conflict_and_bake_one_side(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            np.arange(6, dtype=np.uint32).tofile(folder / 'ib.buf')
            np.concatenate([self.pos, self.pos + [0, 0, 1]]).astype(np.float32).tofile(folder / 'pos.buf')
            np.concatenate([self.uv, self.uv]).astype(np.float32).tofile(folder / 'stock.uv')
            np.array([[0, 0]] * 3 + [[1, 0]] * 3, dtype=np.float32).tofile(folder / 'body.uv')
            lines = []
            for resource, filename in [('B', 'body.uv'), ('S', 'stock.uv')]:
                lines.extend([f'[Resource_{resource}_Index]', 'format=R32_UINT', 'filename=ib.buf', f'[Resource_{resource}_Position]', 'stride=12', 'filename=pos.buf', f'[Resource_{resource}_Texcoord]', 'stride=8', f'filename={filename}'])
            (folder / 'mod.ini').write_text('\n'.join(lines), encoding='utf-8')
            Image.fromarray(np.array([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)).save(folder / 'body.png')
            output = folder / 'twins.dds'
            args = [sys.executable, '-B', str(pathlib.Path(bake.__file__)), '--ini', str(folder / 'mod.ini'), '--stocking', 'S', '--stocking-draw', '6', '--body', 'B', '--body-draw', '6', '--body-tex', 'body.png', '--size', '16', '--out', str(output)]
            result = subprocess.run(args, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(output.with_suffix('.quality.json').read_text(encoding='utf-8'))
            self.assertEqual(report['code'], 'UV_COLOUR_CONFLICT')
            self.assertEqual(report['uv_twins']['conflicts_in_twin_pixels'], report['uv_twins']['conflict_pixels'])
            self.assertIn('--uv-twins auto', report['recovery'])
            result = subprocess.run(args + ['--uv-twins', 'auto'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(output.exists())
            report = json.loads(output.with_suffix('.quality.json').read_text(encoding='utf-8'))
            twins = report['pieces'][0]['uv_twins']
            self.assertEqual((twins['axis'], twins['side'], twins['dropped_triangles']), ('z', '+', 1))
            self.assertGreater(twins['other_side']['over_16_levels'], 0)
            self.assertIsNotNone(twins['other_side']['over_16_box_xy'])


if __name__ == '__main__':
    unittest.main()
