"""Create original mesh, texture, and shader inputs for offline B/C walkthroughs."""
from pathlib import Path
import json
import sys
import numpy as np
from synthetic_fixture import write_fixed

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from bake_skin_to_stocking_uv import write_dds


def create_case(root, route):
    """Return real paths and preflight facts; no game files or author assets are used."""
    root = Path(root)
    source = root / 'source'
    source.mkdir(parents=True)
    (root / 'work').mkdir()
    positions = np.array([[0, 0, 0], [.1, 0, 0], [0, .1, 0], [.1, .1, 0]], dtype=np.float32)
    indices = np.array([0, 1, 2, 2, 1, 3], dtype=np.uint32)
    uv = np.array([[.25, .25], [.75, .25], [.25, .75], [.75, .75]], dtype=np.float32)
    positions.tofile(source / 'Body.pos')
    stocking_positions = positions.copy()
    stocking_positions[:, 2] += .001
    stocking_positions.tofile(source / 'Stock.pos')
    (np.concatenate([indices, indices]) if route == 'C' else indices).tofile(source / 'mesh.ib')
    uv.tofile(source / 'Body.uv')
    stock_uv = uv.copy()
    if route == 'C':
        stock_uv[:, 0] = 1 - stock_uv[:, 0]
    stock_uv.tofile(source / 'Stock.uv')
    skin = np.full((64, 64, 4), (220, 180, 165, 255), dtype=np.uint8)
    skin[20:44, 32:44, :3] = (240, 145, 150)
    fabric = np.full((64, 64, 4), (45, 35, 40, 255), dtype=np.uint8)
    write_dds(source / 'Bare.dds', [skin])
    write_dds(source / 'Stock.dds', [fabric])
    sections = ['[Constants]', 'global $object_detected = 1', 'global $colour = 0', '',
                '[TextureOverrideStock]', 'hash = 11223344', 'ib = Resource_Stock_Index',
                'vb0 = Resource_Stock_Position', 'vb1 = Resource_Stock_Texcoord',
                'ps-t0 = ResourceStockDiffuse', 'drawindexed = 6,0,0', '',
                '[ResourceStockDiffuse]', 'filename = Stock.dds', '']
    for name in ('Body', 'Stock'):
        sections += [f'[Resource_{name}_Index]', 'filename = mesh.ib', 'format = R32_UINT', '',
                     f'[Resource_{name}_Position]', f'filename = {name}.pos', 'stride = 12', '',
                     f'[Resource_{name}_Texcoord]', f'filename = {name}.uv', 'stride = 8', '']
    ini = source / 'case.ini'
    ini.write_text('\n'.join(sections), encoding='utf-8')
    fixed = source / 'case.fixed.hlsl'
    mapping = write_fixed(fixed)
    facts = dict(route=route, ini=str(ini.resolve()), fixed=str(fixed.resolve()), mapping=mapping,
                 body_resource='Body', stocking_resource='Stock', draw='6,0,0',
                 body_draw='12,0,0' if route == 'C' else '6,0,0', stocking_draw='6,0,0',
                 body_texture=str((source / 'Bare.dds').resolve()),
                 stocking_texture=str((source / 'Stock.dds').resolve()),
                 style_index=233, skin_slot='t90', vs_gate=202, ps_gate=1718.1,
                 colour_states=[0, 1], source_tint=[1, 1, 1],
                 same_uv=route == 'B', address_mode='clamp')
    (root / 'facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding='utf-8')
    return facts
