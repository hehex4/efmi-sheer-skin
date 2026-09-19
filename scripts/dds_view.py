# -*- coding: utf-8 -*-
"""dds_view.py —— 看贴图的标准姿势:任意 DDS / PNG → 一张带标签的缩略图拼板,直接用看图工具打开。

用法:
    python dds_view.py <文件或文件夹>... --out <拼板.png> [--size 256] [--cols 4] [--alpha] [--crop u0,v0,u1,v1] [--recursive]
    python dds_view.py <文件或文件夹>... --info            # 只打印表:尺寸 / mip / 格式 / sRGB / alpha 是否有内容

解码顺序:Pillow(12.x 解 BC1–BC7,8K BC7 约 0.6 s)→ texture2ddecoder(装了才用)→ texconv.exe(在 PATH 或 --texconv 指定)。
`--crop` 用 UV 框(左上原点,0–1)在**全分辨率**上裁一块再缩,用来放大看某个 UV 岛。
`--alpha` 在每张旁边多放一格 alpha 灰度图(遮罩 / 抠图常藏在这里)。

只读;唯一输出是 --out 指定的那一张 PNG。依赖:Pillow;numpy 可选(算 alpha 覆盖率更快)。
"""
from __future__ import annotations

# 输入是 DDS/PNG 文件或目录；递归、UV 裁剪、alpha 展示和最大张数都由参数控制。
# 输出表逐张显示尺寸、mip、格式、sRGB 与 alpha 统计；给 --out 时另写一张拼板 PNG。
# alpha 的 min/max 是通道取值范围，非 255 百分比表示 alpha 不透明像素之外还有实际内容。
# 拼板末行的“N 张、WxH”分别是纳入拼板的图片数和最终像素尺寸；超过 --max 的文件不会进入。
# 成功退出 0；找不到可读图片、裁剪框非法或所有解码路线失败时退出非 0。

import argparse
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRGB_DXGI = {29, 72, 75, 78, 91, 93, 99}
DXGI_NAMES = {28: 'RGBA8', 29: 'RGBA8_SRGB', 71: 'BC1', 72: 'BC1_SRGB', 74: 'BC2', 75: 'BC2_SRGB', 77: 'BC3', 78: 'BC3_SRGB',
              80: 'BC4', 83: 'BC5', 95: 'BC6H', 96: 'BC6H_SF', 98: 'BC7', 99: 'BC7_SRGB', 87: 'BGRA8', 91: 'BGRA8_SRGB', 10: 'RGBA16F', 2: 'RGBA32F'}
FOURCC_NAMES = {b'DXT1': 'BC1', b'DXT3': 'BC2', b'DXT5': 'BC3', b'ATI1': 'BC4', b'BC4U': 'BC4', b'ATI2': 'BC5', b'BC5U': 'BC5'}
IMG_EXT = {'.dds', '.png', '.jpg', '.jpeg', '.tga', '.bmp'}


# Parse only the DDS header fields needed for format, size, mip, and sRGB reporting.
def dds_header(path: Path):
    """Return dict(w, h, mips, fmt, srgb, dxgi, fourcc) or None when the file is not a DDS."""
    with open(path, 'rb') as f:
        h = f.read(148)
    if len(h) < 128 or h[:4] != b'DDS ':
        return None
    height, width = struct.unpack_from('<2I', h, 12)
    mips = struct.unpack_from('<I', h, 28)[0] or 1
    fourcc = h[84:88]
    if fourcc == b'DX10' and len(h) >= 132:
        dxgi = struct.unpack_from('<I', h, 128)[0]
        return dict(w=width, h=height, mips=mips, fmt=DXGI_NAMES.get(dxgi, f'DXGI_{dxgi}'), srgb=dxgi in SRGB_DXGI, dxgi=dxgi, fourcc='DX10')
    name = FOURCC_NAMES.get(fourcc, fourcc.decode('latin-1').strip('\x00') or 'RGBA')
    return dict(w=width, h=height, mips=mips, fmt=name, srgb=None, dxgi=None, fourcc=fourcc.decode('latin-1').strip('\x00'))


# Decode supported block-compressed DDS data with the optional lightweight decoder.
def _via_texture2ddecoder(path: Path, hdr):
    import texture2ddecoder as T   # optional dependency
    b = path.read_bytes()
    off = 148 if hdr['fourcc'] == 'DX10' else 128
    dec = {'BC1': T.decode_bc1, 'BC1_SRGB': T.decode_bc1, 'BC3': T.decode_bc3, 'BC3_SRGB': T.decode_bc3, 'BC4': T.decode_bc4,
           'BC5': T.decode_bc5, 'BC6H': T.decode_bc6, 'BC7': T.decode_bc7, 'BC7_SRGB': T.decode_bc7}.get(hdr['fmt'])
    if dec is None:
        raise ValueError(f'texture2ddecoder 不解 {hdr["fmt"]}')
    raw = dec(b[off:], hdr['w'], hdr['h'])          # BGRA
    im = Image.frombytes('RGBA', (hdr['w'], hdr['h']), raw, 'raw', 'BGRA')
    return im


# Convert an unsupported DDS through texconv in an isolated temporary directory.
def _via_texconv(path: Path, texconv: str | None):
    exe = texconv or shutil.which('texconv') or shutil.which('texconv.exe')
    if not exe:
        raise FileNotFoundError('没有 texconv.exe')
    with tempfile.TemporaryDirectory(prefix='ddsview_') as d:
        subprocess.run([exe, '-nologo', '-y', '-ft', 'png', '-m', '1', '-o', d, str(path)], check=True, capture_output=True)
        out = Path(d) / (path.stem + '.png')
        im = Image.open(out); im.load()
        return im.convert('RGBA')


# Try decoders in order and return both the image and the route used.
def load_image(path: Path, texconv: str | None = None) -> tuple[Image.Image, str]:
    """Decode any supported texture to an RGBA PIL image. Returns (image, decoder name)."""
    path = Path(path)
    hdr = dds_header(path) if path.suffix.lower() == '.dds' else None
    errors = []
    try:
        im = Image.open(path); im.load()
        return im.convert('RGBA'), 'Pillow'
    except Exception as e:      # Pillow cannot read this format -> fall through
        errors.append(f'Pillow: {type(e).__name__}: {e}')
    if hdr:
        try:
            return _via_texture2ddecoder(path, hdr), 'texture2ddecoder'
        except Exception as e:
            errors.append(f'texture2ddecoder: {type(e).__name__}: {e}')
    try:
        return _via_texconv(path, texconv), 'texconv'
    except Exception as e:
        errors.append(f'texconv: {type(e).__name__}: {e}')
    raise RuntimeError(f'{path.name} 解不开:' + ' | '.join(errors))


# Summarize alpha range and non-opaque coverage without changing the image.
def alpha_summary(im: Image.Image) -> str:
    """'alpha 无' when the channel is flat 255, else the share of texels below 50%."""
    a = im.getchannel('A')
    lo, hi = a.getextrema()
    if lo == hi == 255:
        return 'alpha 无'
    if lo == hi:
        return f'alpha 全 {lo}'
    hist = a.histogram()
    below = sum(hist[:128]) / max(1, sum(hist))
    return f'alpha {below * 100:.0f}% 透'


# Load a readable Windows font and fall back to Pillow's built-in face.
def font(size: int):
    for name in ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf', 'simsun.ttc', 'DejaVuSans.ttf', 'arial.ttf'):
        for d in (r'C:\Windows\Fonts', '/usr/share/fonts', os.path.expanduser('~/.fonts')):
            p = Path(d) / name
            if p.is_file():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    pass
    return ImageFont.load_default()


# Expand files and directories into a stable, de-duplicated image list.
def collect(inputs, recursive):
    files = []
    for x in inputs:
        p = Path(x)
        if p.is_dir():
            it = p.rglob('*') if recursive else p.iterdir()
            files += sorted(q for q in it if q.is_file() and q.suffix.lower() in IMG_EXT)
        elif p.is_file():
            files.append(p)
        else:
            print(f'跳过(不存在):{x}', file=sys.stderr)
    return files


# Convert a normalized UV box to a bounded pixel crop.
def crop_uv(im: Image.Image, box):
    u0, v0, u1, v1 = box
    w, h = im.size
    return im.crop((int(u0 * w), int(v0 * h), max(int(u0 * w) + 1, int(u1 * w)), max(int(v0 * h) + 1, int(v1 * h))))


# Print image metadata and optionally compose the labelled contact sheet.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', help='DDS / PNG 文件或文件夹')
    ap.add_argument('--out', help='拼板 PNG 路径(不给就只打印表)')
    ap.add_argument('--size', type=int, default=256, help='每格边长(默认 256)')
    ap.add_argument('--cols', type=int, default=4)
    ap.add_argument('--alpha', action='store_true', help='每张旁边多一格 alpha 灰度')
    ap.add_argument('--crop', help='UV 框 u0,v0,u1,v1(左上原点),全分辩率裁完再缩')
    ap.add_argument('--recursive', action='store_true')
    ap.add_argument('--max', type=int, default=64, help='最多放几张(默认 64)')
    ap.add_argument('--texconv', help='texconv.exe 路径(Pillow / texture2ddecoder 都解不开时的兜底)')
    ap.add_argument('--info', action='store_true', help='只打印表,不解码(快)')
    a = ap.parse_args()

    files = collect(a.inputs, a.recursive)[:a.max]
    if not files:
        sys.exit('没有可看的文件')
    box = tuple(float(x) for x in a.crop.split(',')) if a.crop else None
    if box and (len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
        sys.exit('--crop 要 u0,v0,u1,v1,0–1 且左上小于右下')

    rows, tiles = [], []
    for p in files:
        hdr = dds_header(p) if p.suffix.lower() == '.dds' else None
        meta = (f"{hdr['w']}x{hdr['h']} mip{hdr['mips']} {hdr['fmt']}" + (' sRGB' if hdr['srgb'] else ' linear' if hdr['srgb'] is False else '')) if hdr else ''
        size_mb = p.stat().st_size / 1048576
        if a.info and not a.out:
            rows.append((p, meta, f'{size_mb:.1f} MB', ''))
            continue
        try:
            im, dec = load_image(p, a.texconv)
        except Exception as e:
            rows.append((p, meta, f'{size_mb:.1f} MB', f'解码失败 {e}'))
            continue
        if not meta:
            meta = f'{im.width}x{im.height} {p.suffix[1:].upper()}'
        al = alpha_summary(im)
        rows.append((p, meta, f'{size_mb:.1f} MB', f'{al} ({dec})'))
        if a.out:
            src = crop_uv(im, box) if box else im
            rgb = src.convert('RGB'); rgb.thumbnail((a.size, a.size), Image.BOX)
            tiles.append((p.name, meta, al, rgb, src.getchannel('A').copy() if a.alpha else None))

    w0 = max(len(str(r[0].name)) for r in rows)
    for p, meta, sz, note in rows:
        print(f'{p.name:<{w0}}  {meta:<32} {sz:>9}  {note}')

    if a.out and tiles:
        S, pad, label_h = a.size, 8, 44
        per = 2 if a.alpha else 1
        cols = max(1, a.cols)
        n = len(tiles)
        rows_n = (n + cols - 1) // cols
        W = cols * (S * per + pad) + pad
        H = rows_n * (S + label_h + pad) + pad
        sheet = Image.new('RGB', (W, H), (28, 28, 28))
        dr = ImageDraw.Draw(sheet)
        f1, f2 = font(14), font(12)
        for i, (name, meta, al, rgb, alpha) in enumerate(tiles):
            r, c = divmod(i, cols)
            x = pad + c * (S * per + pad); y = pad + r * (S + label_h + pad)
            # checkerboard behind the RGB tile so pure black texels stay distinguishable from empty space
            cell = Image.new('RGB', (S, S), (60, 60, 60))
            cd = ImageDraw.Draw(cell)
            for yy in range(0, S, 16):
                for xx in range(0, S, 16):
                    if (xx // 16 + yy // 16) % 2 == 0:
                        cd.rectangle((xx, yy, xx + 15, yy + 15), fill=(72, 72, 72))
            cell.paste(rgb, ((S - rgb.width) // 2, (S - rgb.height) // 2))
            sheet.paste(cell, (x, y))
            if alpha is not None:
                g = alpha.convert('L'); g.thumbnail((S, S), Image.BOX)
                cellA = Image.new('L', (S, S), 40); cellA.paste(g, ((S - g.width) // 2, (S - g.height) // 2))
                sheet.paste(cellA.convert('RGB'), (x + S, y))
                dr.text((x + S + 4, y + 4), 'alpha', fill=(255, 200, 80), font=f2)
            # labels must stay inside their own tile: clip long names in the middle, keep the meta line short
            maxc = max(12, (S * per) // 8)
            shown = name if len(name) <= maxc else name[:maxc // 2 - 1] + '…' + name[-(maxc // 2 - 1):]
            short_meta = re.sub(r'^(\d+)x\1\b', r'\1²', meta).replace(' mip1', '').replace('_SRGB sRGB', ' sRGB').replace(' linear', ' lin')
            short_al = al.replace('alpha ', 'α').replace('% 透', '%').replace('无', '-')
            dr.text((x + 2, y + S + 2), f'{i + 1}. {shown}', fill=(240, 240, 240), font=f1)
            dr.text((x + 2, y + S + 22), f'{short_meta} {short_al}'[:maxc + 8], fill=(180, 200, 255), font=f2)
        if box:
            dr.text((pad, H - 16), f'crop UV {box}', fill=(255, 200, 80), font=f2)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(a.out)
        print(f'\n拼板:{a.out}  ({n} 张,{W}x{H})')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main())
