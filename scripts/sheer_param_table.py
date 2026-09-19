#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""离线算透肉参数的效果:正对 / 斜 60° / 接近轮廓三个角度的颜色(未打光反照率,sRGB)与「有袜 ÷ 光腿」比。

    python sheer_param_table.py --skin 255,207,198 --fabric 76,64,66 --set 0.45,0,0.9,1 --set 0.45,0.65,1.0,1

--set    ALPHA,W_MIN,W_MAX,GAIN(可多次)
--offset SHEER_ALPHA_OFFSET(默认 1.0,Last Rite 原值)
数学与 skill efmi-sheer-skin 第 1 节相同。混合在线性空间做,少量皮肤在 sRGB 上就显得很亮 —— 这张表就是为了进游戏前先把数算对。
对照锚点:现役深色袜「有袜 ÷ 光腿」sRGB 比 0.60–0.75、三通道近似相等;浅色袜约 0.97 / 1.03 / 1.07。
光照对光腿和丝袜同比例,所以表里的相对关系在游戏里成立;最终以实机为准。
"""
# 输入是肤色、袜色和一组或多组 ALPHA/W_MIN/W_MAX/GAIN；所有颜色参数使用 sRGB 0–255。
# 输出先报三通道“可见度上限”，再列正对、斜 60°、轮廓的预测色、皮肤份额和正对亮度比。
# 括号内百分比是最终颜色中的皮肤混合份额；“正对 ÷ 光腿”三个数分别对应 RGB 通道。
# 深色袜可用 0.60–0.75 附近作离线起点；数值只预测未打光颜色，不能代替实机确认。
# 参数合法时正常退出 0；缺参数或数字格式错误由 argparse/Python 退出非 0；脚本不写文件。

import argparse
import numpy as np


# Convert input sRGB values to linear light for physically meaningful blending.
def s2l(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# Convert predicted linear colours back to display-space sRGB values.
def l2s(c):
    c = np.clip(np.asarray(c, float), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255.0


# Parse one comma-separated RGB triplet into a numeric vector.
def rgb(s):
    return np.array([float(x) for x in s.split(",")])


# Evaluate every parameter set at the three reference view angles and print one comparison row.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skin", required=True, help="光腿肤色 sRGB,如 255,207,198")
    ap.add_argument("--fabric", required=True, help="丝袜(染色后)sRGB,如 76,64,66")
    ap.add_argument("--set", action="append", required=True, help="ALPHA,W_MIN,W_MAX,GAIN")
    ap.add_argument("--offset", type=float, default=1.0)
    a = ap.parse_args()
    skin, fab = rgb(a.skin), rgb(a.fabric)
    sl, fl = s2l(skin), s2l(fab)
    print(f"光腿 {skin.astype(int)} / 袜子 {fab.astype(int)};可见度上限 |肤色 − 袜色| = {np.abs(skin - fab).astype(int)} 级")
    print(f"{'ALPHA/W_MIN/W_MAX/GAIN':<26}{'正对镜头':<24}{'斜 60°':<24}{'接近轮廓':<24}正对 ÷ 光腿")
    for s in a.set:
        alpha, wmin, wmax, gain = (float(x) for x in s.split(","))
        t = min(1.0, max(0.0, alpha + 1.0 - a.offset))
        cells, ratio = [], None
        for ndv in (1.0, 0.5, 0.2):
            f = min(1.0, (1.05 - ndv) ** (2.0 * t))
            w = wmin + (wmax - wmin) * f
            base = sl + (fl - sl) * w              # lerp(肤色, 袜色, w)
            out = l2s(fl + (base - fl) * gain)     # lerp(原袜色, base, GAIN)
            cells.append(f"{'/'.join(str(int(round(c))) for c in out)} ({100 * (1 - w) * gain:.0f}%)")
            if ratio is None:
                ratio = out / np.maximum(skin, 1.0)
        print(f"{s:<26}" + "".join(f"{c:<24}" for c in cells) + " / ".join(f"{r:.2f}" for r in ratio))
    print("(括号 = 皮肤份额)")


if __name__ == "__main__":
    main()
