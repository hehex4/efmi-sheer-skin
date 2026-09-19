#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""按 diffuse 贴图给透肉参数定默认值(skill efmi-sheer-skin 第 3 节)。默认值只是起点,装好后用户进游戏再调。

    python suggest_sheer_params.py --bare <光腿.dds> --variant <丝袜.dds> [--box u0,v0,u1,v1] [--name 黑丝]
    python suggest_sheer_params.py --skin 255,207,198 --fabric 76,64,66 [--name 黑丝]
    可选:--target 0.60   深色袜「正对镜头时 有袜 ÷ 光腿」的目标比值

做法:
1. 量颜色。给了两张贴图:取「丝袜 ≠ 光腿」的像素(任一通道差 > --thr 级),两张图在这些像素上的中位数
   = 袜色 / 丝袜底下的肤色。独立丝袜网格没有光腿变体时,自己取样后用 --skin / --fabric 直接给(sRGB 0–255)。
2. 分类:r = 袜色亮度 ÷ 肤色亮度(线性光,Rec.709 权重)。
   - 三个通道的差都 < 20 级:肉色袜,透肉看不出来(可见度 ≈ |肤色 − 袜色|,第 0 节),建议不做;
   - r ≤ 0.35 深色:ALPHA 0.45、W_MAX 1.0,W_MIN 解到正对镜头「有袜 ÷ 光腿」= --target。
     默认 0.60 = 现役深色袜 mod 的 0.60–0.75 取偏暗一端;2026-09 唯一一次用户手调(last rite 黑丝)落在 0.50,更不透;
   - r ≥ 0.80 浅色:直接用 Last Rite 原值 ALPHA 0.25 / W_MIN 0 / W_MAX 0.9;
   - 之间:三个量按 r 在两套之间线性过渡。
   GAIN 1.0;各向异性高光默认关(SPEC_GAIN 0,要开再调)。
3. 打印可直接粘进参数段的 #define 行,以及正对 / 斜 60° / 接近轮廓三个角度的效果(与 sheer_param_table.py 同一套数学)。
依赖:numpy;给贴图时还要 Pillow(复用同目录 diff_texture_variants.py 的读图;装了 texture2ddecoder 就优先用它)。只读,不改任何文件。
"""
# 输入可以是光腿/丝袜两张 diffuse，也可以是两组三通道 sRGB 颜色；可选 box 限制统计范围。
# 输出丝袜像素比例、肤色/袜色、线性亮度比、深浅判定、可复制参数段和三个角度的预测色。
# “袜 ÷ 肤”小于 0.35 判深色，大于等于 0.80 判浅色，中间值做参数插值；这些是离线起点。
# “丝袜像素 P%”只统计任一通道差超过 --thr 的像素；P 为 0 会停止，说明变体或范围选错。
# 每角度的百分比是皮肤混合份额；末行正对比值用于检查深色袜是否接近 --target。
# 正常完成退出 0；输入组合、颜色格式、尺寸或差异范围错误时退出非 0；脚本不写文件。

import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).parent
DARK_R, LIGHT_R = 0.35, 0.80
DARK = dict(alpha=0.45, wmax=1.0)
LIGHT = dict(alpha=0.25, wmin=0.0, wmax=0.9)


# Convert sampled sRGB colours to linear light before ratios and mixing.
def s2l(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# Convert a predicted linear colour back to display-space sRGB.
def l2s(c):
    c = np.clip(np.asarray(c, float), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255.0


# Compute Rec.709 luminance for the fabric-to-skin classification ratio.
def lum(lin):
    return float(np.dot(lin, [0.2126, 0.7152, 0.0722]))


# Evaluate the sheer equation at one view angle and return colour plus coverage.
def render(sl, fl, alpha, wmin, wmax, gain, ndv, offset=1.0):
    t = min(1.0, max(0.0, alpha + 1.0 - offset))
    f = min(1.0, (1.05 - ndv) ** (2.0 * t))
    w = wmin + (wmax - wmin) * f
    base = sl + (fl - sl) * w                    # lerp(肤色, 袜色, w)
    return l2s(fl + (base - fl) * gain), w       # lerp(原袜色, base, GAIN)


# Measure the frontal RGB ratio used to tune dark fabric without bleaching it.
def face_ratio(skin, sl, fl, alpha, wmin, wmax, gain=1.0):
    out, _ = render(sl, fl, alpha, wmin, wmax, gain, 1.0)
    return float(np.mean(out / np.maximum(skin, 1.0)))


# Solve the frontal minimum coverage by bounded search because the display-space ratio is nonlinear.
def solve_wmin(skin, sl, fl, alpha, wmax, target):
    lo, hi = 0.0, wmax                            # 深色袜:W_MIN 越大正面越暗,比值单调下降
    if face_ratio(skin, sl, fl, alpha, lo, wmax) <= target:
        return lo
    if face_ratio(skin, sl, fl, alpha, hi, wmax) >= target:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if face_ratio(skin, sl, fl, alpha, mid, wmax) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# Measure skin and fabric medians only where the selected texture variant differs.
def colors_from_textures(a):
    sys.path.insert(0, str(HERE))
    from diff_texture_variants import load
    bare, info_b = load(a.bare, a.maxdim)
    var, info_v = load(a.variant, a.maxdim)
    print(f"光腿 {pathlib.Path(a.bare).name}: {info_b}")
    print(f"丝袜 {pathlib.Path(a.variant).name}: {info_v}")
    if bare.shape != var.shape:
        sys.exit("两张贴图尺寸不同,没法逐像素比")
    m = np.abs(var - bare).max(-1) > a.thr
    if a.box:
        u0, v0, u1, v1 = (float(x) for x in a.box.split(","))
        H, W = m.shape
        box = np.zeros_like(m)
        box[int(v0 * H):int(v1 * H), int(u0 * W):int(u1 * W)] = True
        m &= box
    if not m.any():
        sys.exit("两张贴图(框内)没有差异:这个变体上没画丝袜")
    print(f"丝袜像素 = 整图 {100 * m.mean():.2f}%")
    return np.median(bare[m], 0).astype(float), np.median(var[m], 0).astype(float)


# Parse one user-provided sRGB triplet and reject malformed colour input.
def rgb(s):
    v = np.array([float(x) for x in s.split(",")])
    if v.shape != (3,):
        sys.exit(f"颜色要写成 R,G,B:{s}")
    return v


# Select the recipe, print tunable defines, and show predictions at reference angles.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bare", help="光腿(无丝袜)那张 diffuse")
    ap.add_argument("--variant", help="丝袜那张 diffuse")
    ap.add_argument("--box", help="u0,v0,u1,v1(UV,左上原点;只统计框内)")
    ap.add_argument("--thr", type=int, default=8, help="任一通道差超过它才算丝袜像素(sRGB 级,默认 8)")
    ap.add_argument("--maxdim", type=int, default=2048)
    ap.add_argument("--skin", help="肤色 sRGB,如 255,207,198(不给贴图时用)")
    ap.add_argument("--fabric", help="袜色 sRGB,如 76,64,66(不给贴图时用)")
    ap.add_argument("--target", type=float, default=0.60, help="深色袜正对镜头「有袜 ÷ 光腿」目标(默认 0.60)")
    ap.add_argument("--name", default="丝袜", help="这套参数叫什么(黑丝 / 白丝 …),只影响打印")
    a = ap.parse_args()

    if a.bare and a.variant:
        skin, fab = colors_from_textures(a)
    elif a.skin and a.fabric:
        skin, fab = rgb(a.skin), rgb(a.fabric)
    else:
        sys.exit("要么给 --bare + --variant 两张贴图,要么给 --skin + --fabric 两个颜色")

    sl, fl = s2l(skin), s2l(fab)
    r = lum(fl) / max(lum(sl), 1e-6)
    gap = np.abs(skin - fab)
    print(f"\n肤色 sRGB {skin.astype(int)} / 袜色 {fab.astype(int)};亮度比(袜 ÷ 肤,线性)r = {r:.3f};"
          f"可见度上限 |肤色 − 袜色| = {gap.astype(int)} 级")
    if gap.max() < 20:
        print("⚠ 肉色袜:肤色和袜色几乎一样,着色器透肉在屏幕上看不出来(第 0 节)。建议不做,质感交给光泽和织纹。")
        return

    wmin_dark = solve_wmin(skin, sl, fl, DARK["alpha"], DARK["wmax"], a.target)
    if r <= DARK_R:
        k, kind = 0.0, "深色袜"
    elif r >= LIGHT_R:
        k, kind = 1.0, "浅色袜(Last Rite 原值)"
    else:
        k = (r - DARK_R) / (LIGHT_R - DARK_R)
        kind = f"中间色(按深 {1 - k:.0%} / 浅 {k:.0%} 过渡)"
    alpha = DARK["alpha"] + (LIGHT["alpha"] - DARK["alpha"]) * k
    wmax = DARK["wmax"] + (LIGHT["wmax"] - DARK["wmax"]) * k
    wmin = wmin_dark + (LIGHT["wmin"] - wmin_dark) * k
    print(f"判定:{kind}")

    print(f"\n// ==================== 可调参数:改这里 → 保存 → 游戏里按 F10 ====================")
    print(f"// {a.name}:默认值由 suggest_sheer_params.py 按贴图算出({kind}),用户进游戏再调")
    print(f"#define SHEER_ALPHA          {alpha:.2f}   // 透明度,越大越透")
    print(f"#define SHEER_W_MIN          {wmin:.2f}   // 正对镜头时丝袜本色占比,越大越不透")
    print(f"#define SHEER_W_MAX          {wmax:.2f}   // 侧面轮廓丝袜本色占比")
    print(f"#define SHEER_GAIN           1.0    // 透肉强度,0 = 原样")
    print(f"#define SHEER_SPEC_GAIN      0.0    // 各向异性高光,默认关")
    print(f"#define SHEER_SPEC_COUPLING  1.0    // 越透的地方高光越弱")
    print(f"// ==================== 以上 ====================")

    print(f"\n{'角度':<10}{'屏幕色(未打光,sRGB)':<24}皮肤份额")
    for label, ndv in (("正对镜头", 1.0), ("斜 60°", 0.5), ("接近轮廓", 0.2)):
        out, w = render(sl, fl, alpha, wmin, wmax, 1.0, ndv)
        print(f"{label:<10}{'/'.join(str(int(round(c))) for c in out):<24}{100 * (1 - w):.0f}%")
    print(f"正对镜头「有袜 ÷ 光腿」= {face_ratio(skin, sl, fl, alpha, wmin, wmax):.2f}"
          f"(深色袜对照 0.60–0.75;浅色袜约 1.0 上下)")


if __name__ == "__main__":
    main()
