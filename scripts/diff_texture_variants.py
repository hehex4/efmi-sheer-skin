#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""比较光腿贴图与丝袜贴图变体:找出「透肉会改动的范围」,并量丝袜底下的肤色(skill efmi-sheer-skin 第 0 节前提 2 / 3)。

    python diff_texture_variants.py --bare <光腿.dds> --variant <黑丝.dds> [--variant <白丝.dds> ...]
                                    [--box u0,v0,u1,v1] [--thr 8] [--maxdim 2048] [--out <出图目录>]

- 透肉公式在「光腿贴图」与「当前贴图」之间混合,两张一样的像素自动原样不动 ⇒ 「当前 ≠ 光腿」的像素就是效果范围。
- 给了 --box 就分框内 / 框外统计:框外的零散差异要在着色器里用 UV 框挡掉;框内「差 1–thr 级」的是压缩噪声。
- 丝袜底下光腿像素的中位数 = 该角色腿上的真实肤色(常数路线可直接用,换算好的线性值一并打印)。
支持 BC1 / BC3 / BC7(DX10 头或 DXT1 / DXT5 fourcc),自动取边长不大于 --maxdim 的 mip 分析；RGBA8 DX10 DDS 和 PNG 用原始分辨率、显式颜色信息解码。只读,不改任何贴图。
依赖:numpy、Pillow(读 DDS、出图);装了 texture2ddecoder 就优先用它解码。
"""
# 输入是一张光腿 diffuse 和一张或多张丝袜变体，可选 UV 框、差异阈值与分析 mip 上限。
# 输出逐变体给差异比例、UV 包围框、框内外数量、压缩噪声和两侧中位色；可选写范围图。
# “改动像素”是任一 RGB 通道差超过 --thr 的像素比例；默认 8 级用于滤掉 BC 压缩抖动。
# “框外 N 像素”应接近 0；非零说明 box 没罩全或变体还改了别处。“差 1–thr 级”只报压缩噪声占比。
# 最后一行的肤色同时给 sRGB 中位和 shader 可用的线性值。正常完成退出 0；输入/格式错误退出非 0。

import argparse, pathlib, struct, sys
import numpy as np

try:
    import texture2ddecoder
except ImportError:  # 没装就用 Pillow 解码(打包版默认路线,少装一个包)
    texture2ddecoder = None

DXGI = {98: "bc7", 99: "bc7", 71: "bc1", 72: "bc1", 77: "bc3", 78: "bc3"}


# Repackage one mip as a single-level DDS so Pillow can decode it consistently.
def _decode_pillow(b, off, size, lw, lh):
    # 把选中的那一级 mip 单独包成「只有一级 mip」的 DDS 交给 Pillow 解;返回 RGB uint8,和 texture2ddecoder 路线同形状
    import io
    from PIL import Image
    hdr = bytearray(b[:148] if b[84:88] == b"DX10" else b[:128])
    struct.pack_into("<II", hdr, 12, lh, lw)  # 高、宽
    struct.pack_into("<I", hdr, 20, size)     # 线性大小
    struct.pack_into("<I", hdr, 28, 1)        # 只剩一级 mip
    im = Image.open(io.BytesIO(bytes(hdr) + b[off:off + size]))
    return np.asarray(im.convert("RGB"))


# Load the largest mip within the analysis limit and report its source format.
def load(path, maxdim):
    b = pathlib.Path(path).read_bytes()
    if b[:4] != b"DDS " or (len(b) >= 132 and b[84:88] == b"DX10" and struct.unpack_from('<I', b, 128)[0] in (28, 29)):
        # Decode explicit colour metadata before measuring differences in sRGB levels.
        from texture_colour import load_colour_texture, linear_to_srgb
        linear, metadata = load_colour_texture(path)
        rgb = np.rint(np.clip(linear_to_srgb(linear), 0, 1) * 255).astype(np.int16)
        return rgb, f'{rgb.shape[1]}x{rgb.shape[0]} native RGB; {metadata}'
    h, w = struct.unpack_from("<II", b, 12)
    mips = max(1, struct.unpack_from("<I", b, 28)[0])
    fc, off = b[84:88], 128
    if fc == b"DX10":
        kind = DXGI.get(struct.unpack_from("<I", b, 128)[0]); off = 148
    else:
        kind = {b"DXT1": "bc1", b"DXT5": "bc3"}.get(fc)
    if kind is None:
        sys.exit(f"{path}: 不支持的格式 {fc!r}")
    bpb = 8 if kind == "bc1" else 16
    lw, lh, lv = w, h, 0
    while max(lw, lh) > maxdim and lv + 1 < mips:
        off += ((lw + 3) // 4) * ((lh + 3) // 4) * bpb
        lw, lh, lv = max(1, lw // 2), max(1, lh // 2), lv + 1
    size = ((lw + 3) // 4) * ((lh + 3) // 4) * bpb
    if texture2ddecoder is not None:
        dec = {"bc7": texture2ddecoder.decode_bc7, "bc1": texture2ddecoder.decode_bc1, "bc3": texture2ddecoder.decode_bc3}[kind]
        img = np.frombuffer(dec(b[off:off + size], lw, lh), np.uint8).reshape(lh, lw, 4)[..., [2, 1, 0]]
    else:
        img = _decode_pillow(b, off, size, lw, lh)
    return img.astype(np.int16), f"{w}x{h} {kind} mips={mips} → 分析 mip{lv} {lw}x{lh}"


# Convert measured sRGB colours to shader-ready linear values.
def s2l(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# Compare each variant with bare skin, print the effect bounds, and optionally render masks.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bare", required=True, help="光腿(无丝袜)那张 diffuse")
    ap.add_argument("--variant", action="append", required=True, help="丝袜变体,可多次")
    ap.add_argument("--box", default=None, help="u0,v0,u1,v1(UV,左上原点)")
    ap.add_argument("--thr", type=int, default=8, help="任一通道差超过它才算「不同」(sRGB 级,默认 8)")
    ap.add_argument("--maxdim", type=int, default=2048)
    ap.add_argument("--out", default=None, help="出范围图的目录(不给就不出图)")
    a = ap.parse_args()

    bare, info = load(a.bare, a.maxdim)
    print(f"光腿 {pathlib.Path(a.bare).name}: {info}")
    H, W = bare.shape[:2]
    box = np.ones((H, W), bool)
    if a.box:
        u0, v0, u1, v1 = (float(x) for x in a.box.split(","))
        box = np.zeros((H, W), bool)
        box[int(v0 * H):int(v1 * H), int(u0 * W):int(u1 * W)] = True
    union = np.zeros((H, W), bool)
    for vp in a.variant:
        img, info = load(vp, a.maxdim)
        name = pathlib.Path(vp).name
        print(f"\n{name}: {info}")
        if img.shape != bare.shape:
            print("  尺寸与光腿不同,跳过"); continue
        d = np.abs(img - bare).max(-1)
        m = d > a.thr
        union |= m
        ys, xs = np.nonzero(m)
        if not len(xs):
            print("  与光腿无差异"); continue
        print(f"  改动像素 = 整图 {100 * m.mean():.2f}%;差异包围框 u{xs.min() / W:.2f}-{xs.max() / W:.2f} v{ys.min() / H:.2f}-{ys.max() / H:.2f}")
        if a.box:
            noise = box & (d > 0) & (d <= a.thr)
            print(f"  框内 {100 * m[box].mean():.1f}% / 框外 {(m & ~box).sum()} 像素;框内「差 1–{a.thr} 级」压缩噪声 {100 * noise[box].mean():.2f}% 的框")
        print(f"  改动区中位 sRGB:本变体 {np.median(img[m], 0).astype(int)} / 光腿 {np.median(bare[m], 0).astype(int)}")
        if a.out:
            try:
                from PIL import Image, ImageDraw
            except ImportError:
                print("  (没装 Pillow,跳过出图)"); continue
            o = img.astype(float)
            o[m] = o[m] * 0.35 + np.array([0.0, 255.0, 0.0]) * 0.65
            im = Image.fromarray(o.clip(0, 255).astype(np.uint8)).resize((1024, 1024))
            if a.box:
                ImageDraw.Draw(im).rectangle([u0 * 1024, v0 * 1024, u1 * 1024, v1 * 1024], outline=(255, 220, 0), width=3)
            outdir = pathlib.Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
            dst = outdir / f"scope_{pathlib.Path(vp).stem}.png"
            im.save(dst); print(f"  范围图(绿 = 会被透肉改动的像素)→ {dst}")
    if union.any():
        sk = np.median(bare[union], 0)
        print(f"\n丝袜底下的光腿肤色:sRGB 中位 {sk.astype(int)} → 线性 {np.round(s2l(sk), 4)}")


if __name__ == "__main__":
    main()
