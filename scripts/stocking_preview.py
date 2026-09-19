# -*- coding: utf-8 -*-
"""stocking_preview.py —— 按每次 draw 自己的 UV 岛看丝袜:各片独立取色、判深浅、给 UV 框,出一张带标签的对比图。

为什么要这样看:一张 8K 图集上通常同时画着黑丝、白丝、手套、内衣…,黑丝和白丝常是**同一张图上的两片网格、两块 UV 岛**,
靠 `$swapkey` 切换。拿整张图的中位色当袜色、或只看文件名,两种颜色都会判错(2026-09 Typhoeus 实例)。
正确做法 = 先用 resolve_textures.py 找到这次 draw 绑的漫反射,再用本脚本把 draw 的三角形按 UV 光栅化,只在岛内取色。

用法:
    python stocking_preview.py --ini <mod.ini> --out-dir <目录> [--tex <默认漫反射>] [--size 1024] [--skin r,g,b]
        --piece <标签> <资源> <数量,起点[,基顶点]> [<这片自己的漫反射>]    (可重复,一片一组)

    <资源> = ini 里 `[Resource_<前缀>_Index/_Position/_Texcoord]` 或 `_IB/_VB0/_VB1` 的 <前缀>,
             或明写 ib=<段名>,pos=<段名>,uv=<段名>
    <数量,起点,基顶点> = 那行 drawindexed 的三个数;drawindexedinstanced 取第 1、3、4 个数。

每片打印:岛像素数、UV 包围框、建议的 `--box`(行列直方图取 90% 像素的紧框)、岛内袜色中位 sRGB、
明暗档(深 / 中 / 浅)、像不像肤色(光腿嫌疑)、按高度 z 四段的中位色(看这一片有没有混着别的部件);
`--skin` 给了肤色就顺带算 |肤色 − 袜色|(透肉可见度的上限)。
出图:每片一张 `<标签>_island.png`(只画岛内像素,裁到包围框)+ 一张 `stocking_sheet.png` 拼板(标签 / draw / 色块 / 结论)。

只读 mod;输出只在 --out-dir。依赖:numpy、Pillow;复用同目录 bake_skin_to_stocking_uv.py 与 dds_view.py。
"""
from __future__ import annotations

# 输入是 mod INI、每片丝袜的资源与 draw 参数，以及默认或逐片 diffuse；可选肤色用于可见度估算。
# 输出每片 island PNG 和一张拼板，并打印 UV 覆盖、box、袜色、灰度、饱和度、色差与四段高度统计。
# “岛像素 N(P%)”中 P 是 UV 岛占整张统计图的比例；较小且颜色一致通常对应独立丝袜网格。
# 建议 box 后的百分比是 box 保留的岛像素比例；默认算法目标约 90%，仍要检查是否切掉袜口。
# 最大通道色差小于 30 个 sRGB 级时透肉通常不明显；高度段颜色差大表示同一 draw 可能混有其它部件。
# 成功退出 0；资源、贴图、piece 参数错误或所有 UV 岛为空时退出非 0。

import argparse
import colorsys
import json
import hashlib
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True          # 别在 skill 目录里留 __pycache__
import bake_skin_to_stocking_uv as B   # noqa: E402  (mesh / ini helpers)
import dds_view as V                    # noqa: E402  (texture decoding, font)
from texture_colour import load_colour_texture, linear_to_srgb


# Inspect every native texel touched by the draw's UV triangles, including thin
# triangles between pixel centres. A one-code RGB difference requires spatial colour.
def detect_native_colour(rgb, ib, uv, *, complete=True, address_mode='clamp', dynamic_sampling=False):
    """Classify decoded 8-bit diffuse pixels; this does not prove a whole shader uniform."""
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Native colour detection requires an unscaled uint8 RGB image')
    height, width = rgb.shape[:2]
    mask = np.zeros((height, width), dtype=bool)
    triangles = np.asarray(ib).reshape(-1, 3)
    reasons = [] if complete else ['incomplete_input_sampling']
    if address_mode != 'clamp':
        reasons.append('addressing_not_proven_clamp')
    if dynamic_sampling:
        reasons.append('dynamic_sampling_requires_runtime_mapping')
    if not len(triangles):
        reasons.append('empty_draw')
    for indices in triangles:
        tri = np.asarray(uv)[indices]
        if not np.isfinite(tri).all() or (tri < 0).any() or (tri > 1).any():
            reasons.append('unsupported_uv_range_or_nonfinite')
            continue
        p = tri * [width, height]
        edge = np.roll(p, -1, axis=0) - p
        area = edge[0, 0] * edge[1, 1] - edge[0, 1] * edge[1, 0]
        if abs(area) <= 1e-12:
            reasons.append('degenerate_uv_triangle')
            continue
        x0, y0 = np.maximum(np.floor(p.min(0)).astype(int) - 1, 0)
        x1, y1 = np.minimum(np.ceil(p.max(0)).astype(int) + 1, [width, height])
        xs = np.arange(x0, x1)[None, :] + 0.5
        # Triangle/texel-box separating-axis tests cover thin islands without
        # treating their bounding boxes or unrelated atlas regions as the island.
        for start in range(y0, y1, 64):
            stop = min(start + 64, y1)
            ys = np.arange(start, stop)[:, None] + 0.5
            # A bilinear texel contributes within one pixel of its centre.
            hit = ((xs + 1 >= p[:, 0].min()) & (xs - 1 <= p[:, 0].max()) &
                   (ys + 1 >= p[:, 1].min()) & (ys - 1 <= p[:, 1].max()))
            for dx, dy in edge:
                nx, ny = -dy, dx
                projection = p[:, 0] * nx + p[:, 1] * ny
                centres = xs * nx + ys * ny
                radius = abs(nx) + abs(ny)
                hit &= ((centres + radius >= projection.min() - 1e-10) &
                        (centres - radius <= projection.max() + 1e-10))
            mask[start:stop, x0:x1] |= hit
    minimum = np.full(3, 255, dtype=np.uint8)
    maximum = np.zeros(3, dtype=np.uint8)
    count = 0
    for start in range(0, height, 64):
        pixels = rgb[start:start + 64][mask[start:start + 64]]
        if len(pixels):
            minimum = np.minimum(minimum, pixels.min(0))
            maximum = np.maximum(maximum, pixels.max(0))
            count += len(pixels)
    if not count:
        reasons.append('no_native_texels')
    varied = bool(count and (maximum != minimum).any())
    status = 'nonuniform' if varied else ('unknown' if reasons else 'uniform_diffuse')
    return dict(status=status, complete=not reasons, native_size=[width, height],
                sampled_texels=count, minimum=minimum.tolist() if count else None,
                maximum=maximum.tolist() if count else None, threshold_codes=1,
                requires_spatial_colour=status != 'uniform_diffuse',
                reasons=sorted(set(reasons)), addressing=address_mode, dynamic_sampling=dynamic_sampling,
                scope='native decoded RGB8 including the bilinear support of the draw UV footprint; shader colour chain remains unproven')


# Do not let a decoder's RGB8 conversion hide higher-precision source variation.
def native_precision_preserved(path, size):
    if path.suffix.lower() == '.dds':
        header = V.dds_header(path)
        known = {'RGBA8', 'RGBA8_SRGB', 'BGRA8', 'BGRA8_SRGB', 'BC1', 'BC1_SRGB',
                 'BC2', 'BC2_SRGB', 'BC3', 'BC3_SRGB', 'BC4', 'BC5', 'BC7', 'BC7_SRGB'}
        return bool(header and header['fmt'] in known and
                    size == (header['w'], header['h']))
    with Image.open(path) as source:
        if source.size != size or source.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            return False
        if source.format == 'PNG':
            with path.open('rb') as stream:
                header = stream.read(25)
            return len(header) == 25 and header[24] <= 8
        return source.format in ('JPEG', 'BMP', 'TGA')


# Load a texture through the shared decoder and cap its analysis resolution.
def load_texture(path: Path, maxdim: int, colour_space='auto'):
    """Legacy pair API: linear RGB and False; resizing occurs in linear light."""
    rgb, _ = load_colour_texture(path, colour_space)
    height, width = rgb.shape[:2]
    if max(height, width) > maxdim:
        ratio = maxdim / max(height, width)
        size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
        rgb = np.stack([np.asarray(Image.fromarray(rgb[..., c].astype(np.float32)).resize(size, Image.Resampling.BOX))
                        for c in range(3)], axis=2).astype(np.float64)
    return rgb, False


def input_identity(path):
    """Bind a report to exact source bytes without embedding the source itself."""
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return dict(path=str(path), sha256=digest.hexdigest())


# Find a compact UV box that retains the requested share of island samples.
def tight_box(u, v, keep=0.90, bins=128):
    """Smallest contiguous UV band in each axis holding `keep` of the island texels."""
    # Trim histogram tails symmetrically until the retained mass reaches the target.
    def band(x):
        h, e = np.histogram(x, bins=bins, range=(0.0, 1.0))
        c = np.concatenate([[0], np.cumsum(h)])
        total = c[-1]
        best_len, best = bins + 1, (0, bins)
        for i in range(bins):
            j = int(np.searchsorted(c, c[i] + keep * total, side='left'))
            if j <= bins and j - i < best_len:
                best_len, best = j - i, (i, j)
        return e[best[0]], e[best[1]]
    u0, u1 = band(u); v0, v1 = band(v)
    return (round(float(u0), 3), round(float(v0), 3), round(float(u1), 3), round(float(v1), 3))


# Classify the island colour as dark, medium, light, or skin-like for routing.
def classify(med_srgb):
    r, g, b = [c / 255.0 for c in med_srgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    gray = 0.299 * med_srgb[0] + 0.587 * med_srgb[1] + 0.114 * med_srgb[2]
    tone = '深色' if gray < 96 else ('浅色' if gray > 176 else '中间色')
    skinlike = (h * 360 <= 45 or h * 360 >= 350) and 0.10 <= s <= 0.55 and gray > 120
    return tone, skinlike, gray, s


# Rasterize every requested piece, print numeric verdicts, and compose labelled previews.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ini', required=True, help='mod 的 ini(网格资源段从这里读;贴图路径相对它)')
    ap.add_argument('--piece', required=True, action='append', nargs='+', metavar='X',
                    help='<标签> <资源> <数量,起点[,基顶点]> [<漫反射路径>];可重复')
    ap.add_argument('--tex', help='默认漫反射(片没单独给时用);相对 ini 所在目录或绝对路径')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--size', type=int, default=1024, help='仅预览光栅化分辨率(默认 1024)，颜色检测始终使用原尺寸')
    ap.add_argument('--skin', help='肤色 sRGB r,g,b(可选,算 |肤色−袜色|)')
    ap.add_argument('--colour-space', choices=('auto', 'srgb', 'linear'), default='auto', help='按格式解码；旧 DDS 先核对实际 SRV，再显式填写 srgb/linear')
    ap.add_argument('--address-mode', choices=('unknown', 'clamp', 'wrap', 'mirror'), default='unknown', help='核对实际采样器后填写；只有已知 clamp 可证明此 UV 采样单色，其他方式标 unknown')
    ap.add_argument('--dynamic-sampling', action='store_true', help='存在动态 UV/纹理寻址时标 unknown，须现场映射后再检查')
    a = ap.parse_args()
    if a.size < 1:
        ap.error('--size 必须为正；建议 1024')

    ini = Path(a.ini)
    if not ini.is_file():
        sys.exit(f'ini 不存在:{ini}')
    text = B.read_text(ini)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    S = a.size
    skin = np.array([float(x) for x in a.skin.split(',')]) if a.skin else None
    tex_cache = {}

    # Resolve a piece-specific texture before falling back to the shared default.
    def tex_for(p):
        key = str(p.resolve())
        if key not in tex_cache:
            tex_cache[key] = load_texture(p, 2048, a.colour_space)
        return tex_cache[key]

    results = []
    colour_results = []
    for spec in a.piece:
        if len(spec) < 3:
            sys.exit(f'--piece 至少三项:标签 资源 draw参数(收到 {spec})')
        label, res_spec, draw_s = spec[0], spec[1], spec[2]
        texp = spec[3] if len(spec) > 3 else a.tex
        if not texp:
            sys.exit(f'{label}:没有漫反射路径(--tex 或第 4 项)')
        texp = Path(texp) if os.path.isabs(texp) else (ini.parent / texp)
        if not texp.is_file():
            sys.exit(f'{label}:贴图不存在 {texp}')
        draw = B.parse_draw(draw_s)
        res = B.resources(text, res_spec)
        ib, pos, uv = B.load_mesh(ini.parent, res, draw, label)
        native, _ = V.load_image(texp)
        _, texture_meta = load_colour_texture(texp, a.colour_space)
        colour = detect_native_colour(np.asarray(native.convert('RGB')), ib, uv,
                                      complete=native_precision_preserved(texp, native.size),
                                      address_mode=a.address_mode, dynamic_sampling=a.dynamic_sampling)
        colour.update(label=label, resource=res_spec, draw=draw, texture=input_identity(texp),
                      inputs={kind: input_identity(ini.parent / item['filename']) for kind, item in res.items()},
                      colour_space=texture_meta['colour_space'], texture_metadata=texture_meta)
        colour_results.append(colour)
        (out / 'colour_detection.json').write_text(
            json.dumps(dict(schema_version=2, ini=input_identity(ini), pieces=colour_results), ensure_ascii=False, indent=2), encoding='utf-8')
        del native
        print(f'{label}: 原尺寸腿部/丝袜 diffuse 检测 {colour["status"]}，'
              f'{colour["sampled_texels"]} texels；RGB 范围 {colour["minimum"]} → {colour["maximum"]}')
        if colour['requires_spatial_colour']:
            print('  必须使用光腿贴图(B 优先；先验证 UV 兼容)或烘焙(C)，不得退回常数肤色。')
        else:
            print('  仅此 draw 的原尺寸 diffuse 为单色；仍需检查 shader tint/其他颜色来源，不能据此证明整个材质单色。')
        tex, srgb = tex_for(texp)
        acc, cnt = B.rasterize(ib, uv, np.repeat(pos[:, 2:3], 3, 1), S)   # bake vertex z into the island for the height split
        filled = cnt > 0
        if not filled.any():
            print(f'{label}: UV 岛为空(UV 超界或 draw 参数不对)'); continue
        py, px = np.nonzero(filled.reshape(S, S))
        u, v = (px + 0.5) / S, (py + 0.5) / S
        fab = B.bilinear(tex, np.stack([u, v], 1))
        fab = fab if srgb else B.l2s(fab)          # stats in sRGB like the eye sees it
        fab8 = np.round(fab * 255)
        med = tuple(int(x) for x in np.median(fab8, 0))
        tone, skinlike, gray, sat = classify(med)
        z = (acc[:, 0] / np.maximum(cnt, 1)).reshape(S, S)[py, px]
        qs = np.quantile(z, [0, 0.25, 0.5, 0.75, 1.0])
        zrows = []
        for lo, hi in zip(qs[:-1], qs[1:]):
            m = (z >= lo) & (z <= hi)
            if m.any():
                zrows.append((lo, hi, tuple(int(x) for x in np.median(fab8[m], 0)), int(m.sum())))
        box = tight_box(u, v)
        inb = (u >= box[0]) & (u < box[2]) & (v >= box[1]) & (v < box[3])
        cov = len(px) / (S * S) * 100
        bbox = (u.min(), v.min(), u.max(), v.max())
        diff = int(np.abs(skin - med).max()) if skin is not None else None

        print('=' * 96)
        print(f'{label}  draw {draw_s}  贴图 {texp.name}({tex.shape[1]}x{tex.shape[0]} 统计分辩率,{"sRGB" if srgb else "linear→sRGB"})')
        print(f'  岛像素 {len(px)}({cov:.2f}% 的图)  UV 包围框 u[{bbox[0]:.3f},{bbox[2]:.3f}] v[{bbox[1]:.3f},{bbox[3]:.3f}]')
        print(f'  建议 --box {box[0]},{box[1]},{box[2]},{box[3]}(框内 {inb.mean() * 100:.0f}% 岛像素)')
        print(f'  岛内袜色中位 sRGB {tuple(med)}  灰度 {gray:.0f}  饱和 {sat:.2f}  → {tone}' + ('  ⚠ 像肤色(光腿 / 皮肤嫌疑,别当袜子)' if skinlike else ''))
        if diff is not None:
            print(f'  |肤色 − 袜色| 最大通道差 {diff}(sRGB 级;< 30 ⇒ 透肉几乎看不出)')
        for lo, hi, m8, n in zrows:
            print(f'  z[{lo:.2f},{hi:.2f}] {n:>7} px  中位 {tuple(m8)}')
        spread = max(int(np.abs(np.array(r[2]) - np.array(med)).max()) for r in zrows) if zrows else 0
        if spread > 40:
            print(f'  ⚠ 不同高度段颜色差 {spread}:这一片可能连着别的部件(饰件 / 袜口 / 吊带),用 --box 只框袜子本体')

        # island preview: island texels on dark grey, cropped to the bbox with a small margin
        img = np.full((S, S, 3), 36, np.uint8); img[py, px] = fab8.astype(np.uint8)
        x0, x1 = int(bbox[0] * S), int(np.ceil(bbox[2] * S)); y0, y1 = int(bbox[1] * S), int(np.ceil(bbox[3] * S))
        mg = max(4, (x1 - x0) // 20)
        crop = Image.fromarray(img[max(0, y0 - mg):min(S, y1 + mg), max(0, x0 - mg):min(S, x1 + mg)])
        safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in label)
        crop.save(out / f'{safe}_island.png')
        results.append(dict(label=label, draw=draw_s, tex=texp.name, med=tuple(int(x) for x in med), tone=tone, skinlike=skinlike,
                            box=box, cov=cov, crop=crop, n=len(px), diff=diff))

    if not results:
        sys.exit('没有一片能画出来')
    # contact sheet
    T, pad, lab = 320, 10, 78
    cols = min(3, len(results)); rows = (len(results) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (T + pad) + pad, rows * (T + lab + pad) + pad), (24, 24, 24))
    dr = ImageDraw.Draw(sheet); f1, f2 = V.font(15), V.font(13)
    for i, r in enumerate(results):
        rr, cc = divmod(i, cols)
        x = pad + cc * (T + pad); y = pad + rr * (T + lab + pad)
        th = r['crop'].copy(); th.thumbnail((T, T), Image.BOX)
        cell = Image.new('RGB', (T, T), (36, 36, 36)); cell.paste(th, ((T - th.width) // 2, (T - th.height) // 2))
        sheet.paste(cell, (x, y))
        dr.rectangle((x, y + T + 4, x + 26, y + T + 30), fill=tuple(r['med']), outline=(200, 200, 200))
        dr.text((x + 32, y + T + 4), f"{r['label']}  {r['tone']}" + ('  像肤色!' if r['skinlike'] else ''), fill=(245, 245, 245), font=f1)
        dr.text((x + 32, y + T + 26), f"draw {r['draw']}  中位 {r['med']}", fill=(180, 200, 255), font=f2)
        dr.text((x + 2, y + T + 46), f"{r['tex'][:30]}  岛 {r['cov']:.2f}%  box {r['box']}", fill=(160, 160, 160), font=f2)
    sheet_path = out / 'stocking_sheet.png'
    sheet.save(sheet_path)
    print('=' * 96)
    print(f'拼板:{sheet_path}   单片:{out}\\<标签>_island.png')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(f'PREVIEW_INPUT_INVALID: {exc}; repair the named input and rerun the same command')
