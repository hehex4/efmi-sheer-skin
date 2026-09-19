import importlib.util
import pathlib
import tempfile
import unittest
import subprocess
import sys
import time
import numpy as np
from PIL import Image

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'bake_skin_to_stocking_uv.py'
sys.path.insert(0, str(SOURCE.parent))
spec = importlib.util.spec_from_file_location('bake', SOURCE)
bake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bake)

class BakeTests(unittest.TestCase):
    def setUp(self):
        self.pos = np.array([[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]])
        self.uv = np.array([[0., 0.], [1., 0.], [0., 1.]])

    def test_sparse_surface_and_k_boundary(self):
        surface = bake.TriangleSurface(self.pos[None], self.uv[None], leaf_size=8)
        distance, uv = surface.sample(np.array([[.5, .5, .001], [1., 0., 0.]]))
        np.testing.assert_allclose(distance, [.001, 0.], atol=1e-12)
        np.testing.assert_allclose(uv, [[.25, .25], [.5, 0.]])
        for k in (1, 8, 64):
            surface = bake.TriangleSurface(np.repeat(self.pos[None], 8, axis=0), np.repeat(self.uv[None], 8, axis=0), k)
            distance, uv = surface.sample(np.array([[.5, .5, .001]]))
            np.testing.assert_allclose(distance, [.001], atol=1e-12)

    def test_texture_interior_survives(self):
        surface = bake.TriangleSurface(self.pos[None], self.uv[None])
        texture = np.zeros((32, 32, 3)); texture[5:12, 5:12, 0] = 1
        acc, count = bake.bake_surface(np.arange(3), self.pos, self.uv, surface, texture, 32, 23, 'test')
        self.assertGreater(acc[:, 0].max(), .99)
        self.assertTrue(np.any((count > 0) & (acc[:, 0] == 0)))

    def test_invalid_draws(self):
        for value in ('0', '-3', '4', '3,-1', '3,0,0,0', 'abc'):
            with self.subTest(value=value), self.assertRaises((ValueError, SystemExit)):
                bake.parse_draw(value)
        self.assertEqual(bake.parse_draw('3,2,6,4,0'), [3, 6, 4])

    def test_nan_surface(self):
        points = self.pos.copy(); points[0, 0] = np.nan
        with self.assertRaises(ValueError):
            bake.TriangleSurface(points[None], self.uv[None])

    def test_empty_uv_coverage(self):
        surface = bake.TriangleSurface(self.pos[None], self.uv[None])
        with self.assertRaisesRegex(ValueError, 'UV'):
            bake.bake_surface(np.arange(3), self.pos, np.zeros((3, 2)), surface, np.ones((2, 2, 3)), 16, 16, 'test')

    def test_distance_error_is_repairable(self):
        surface = bake.TriangleSurface(self.pos[None], self.uv[None])
        with self.assertRaisesRegex(ValueError, 'draw') as error:
            bake.bake_surface(np.arange(3), self.pos + [0, 0, .1], self.uv, surface, np.ones((2, 2, 3)), 16, 16, 'test')
        self.assertNotIn('常数', str(error.exception))

    def test_bvh_matches_exhaustive(self):
        rng = np.random.default_rng(42)
        triangles = rng.normal(size=(71, 3, 3))
        uv = rng.random((71, 3, 2)); points = rng.normal(size=(250, 3))
        surface = bake.TriangleSurface(triangles, uv, 3)
        distance, result = surface.sample(points)
        expected, ids, bary = bake.closest_triangles(points, triangles)
        np.testing.assert_allclose(distance ** 2, expected, atol=1e-12)
        np.testing.assert_allclose(result, (uv[ids] * bary[:, :, None]).sum(1), atol=1e-12)

    def test_legacy_preview_api(self):
        acc, count = bake.rasterize(np.arange(3), self.uv, np.ones((3, 3)), 8)
        self.assertTrue((acc[count > 0] == 1).all())

    def test_native_texture_and_single_texel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'texture.png'
            Image.new('RGB', (1200, 2), 'red').save(path)
            texture, _ = bake.texture_1024(path)
            self.assertEqual(texture.shape, (2, 1200, 3))
        np.testing.assert_equal(bake.bilinear(np.ones((1, 1, 3)), self.uv), np.ones((3, 3)))

    def test_cli_shared_buffers_and_bare_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            np.array([0, 1, 2, 0, 1, 2], dtype=np.uint32).tofile(folder / 'ib.buf')
            self.pos.astype(np.float32).tofile(folder / 'pos.buf')
            self.uv.astype(np.float32).tofile(folder / 'uv.buf')
            lines = ['[Resource_M_Index]', 'format=R32_UINT', 'filename=ib.buf',
                     '[Resource_M_Position]', 'stride=12', 'filename=pos.buf',
                     '[Resource_M_Texcoord]', 'stride=8', 'filename=uv.buf']
            (folder / 'mod.ini').write_text(chr(10).join(lines), encoding='utf-8')
            tex = np.zeros((32, 32, 3), dtype=np.uint8); tex[5:12, 5:12, 0] = 255
            Image.fromarray(tex).save(folder / 'body.png')
            args = [sys.executable, str(SOURCE), '--ini', str(folder / 'mod.ini'),
                    '--stocking', 'M', '--body', 'M', '--body-draw', '3',
                    '--body-tex', 'body.png', '--out', str(folder / 'out.dds'), '--size', '32']
            for draw, flag, success in [('3,3', [], True), ('3', [], False), ('3', ['--body-tex-is-bare'], True),
                                         ('3,-1', [], False), ('3,0,-1', [], False), ('3,9', [], False)]:
                with self.subTest(draw=draw, flag=flag):
                    result = subprocess.run(args + ['--stocking-draw', draw] + flag, capture_output=True)
                    self.assertEqual(result.returncode == 0, success, result.stderr)
                    if success:
                        output = np.asarray(Image.open(folder / 'out.dds'))
                        self.assertEqual(output[7, 7, 0], 255)
                        self.assertEqual(output[1, 1, 0], 0)

if __name__ == '__main__':
    unittest.main()
