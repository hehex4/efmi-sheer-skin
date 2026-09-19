#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""build_sheer_ps.py —— 从忠实修补过的底子生成透肉替换 PS:按状态各出一份(只差参数段)+ 一份探针版(检查模式)。
只读输入,只用标准库(编译自检要 fxc.exe)。(skill efmi-sheer-skin 第 2 节第 5、6 步)

    python build_sheer_ps.py <X.fixed.hlsl> --out-dir <目录> [--skin r,g,b] [--skin-slot tNN [--skin-slot-kind bareleg|baked]]
        (--style-index N | --no-style-switch)
        [--state 名[@文件标签]:键=值,键=值 ...] [--box u0,v0,u1,v1] [--spec-stocking-only]
        [--name 输出名] [--aniso-core 路径] [--sheer-core 路径] [--tint-cb "cb6[6]"]
        [--aniso-n 寄存器@行号] [--aniso-l 寄存器@行号]
        [--view-line 行号] [--normal-input vN] [--tangent-input vN]
        [--no-probe] [--no-compile] [--fxc 路径]

输入 = fix_decompiler_defects.py 的产物 <X>.fixed.hlsl(原样拿来;已经注入过透肉 / 高光的会被拒)。
输出(--out-dir 下,输入文件本身不动):
  <名>_<状态>.hlsl   每个 --state 一份,彼此只差最上面的参数段
  <名>_probe.hlsl    检查版 = 第一个状态 + ANISO_DEBUG_MODE 1:整块纯绿。接到 ini 开头的检查开关(改 1 = 整块纯绿 =
                     替换 PS 挂上了、门控命中了)。它只做严格编译,别跑 reflect_check(纯绿会把大部分代码剔掉)
  <名>_build.txt     锚点、行号证据、覆写核查、编译结果

输出文件从上到下:可调参数段(取自 assets/sheer_core.hlsl,值按 --state 改)→ 底子的声明部分(原样)
  → 高光核心整段(--aniso-core,带 ANISO_DEBUG_MODE 探针)→ 透肉核心(sheer_core.hlsl 的「透肉核心」段,
  肤色 / 光腿槽 / UV 框按参数改)→ 原 PS 的 main(一行不改)+ 各锚点注入 + 调用点。
  两个核心放在 main() 之前、底子声明之后(与两个实案的生成脚本一致)。

自动定位(每个锚点都断言恰好命中 1 次,否则停下并说明):
  声明点  main 里 `uint4 bitmask, uiDest;` 之后:声明 _anisoV / _anisoN / _anisoL、_shCov / _shScope / _shStk
  V       TEXCOORD1 那个输入的归一化链:rA.xyz 由 TEXCOORD1 算出 → dot(rA, rA) → rsqrt → `rV.xyz = rA.xyz * rS.www`;
          在赋值行之后立即捕获进 _anisoV(必须在 main 顶层),并按 regcheck.py 的办法列出「赋值 → 注入点」之间
          对 rV 的写入次数(0 = 寄存器本身也干净;非 0 也不要紧,用的是捕获值)
  N / T   TBN 重建里的叉积三连 `c = a.yzx * b.zxy; c = b.yzx * a.zxy - c; c = a.www * c` 认出切线 a、几何法线 b;
          透肉的 N = normalize(几何法线),高光核心的切线 / 手性 = a.xyz / a.w
  注入点  `rX = <--tint-cb>.xyz(w) * rY.xyz(w);`(2026-09 是 cb6[6]),rY 最近一次必须是贴图采样
          (描边 / 阴影 PS 没有这一行 —— 找不到就说明给的不是材质 PS);透肉块紧跟其后,必须在 main 顶层
  调用点  main 末尾最后一次写 o0 之后、别的输出(o1…)和 `return;` 之前,在顶层;main 里有别的 return 就停
  不开高光时 _anisoN = 几何法线、_anisoL = V(合法向量,只有探针档 2–5 会读它们);要开高光先按
  efmi-anisotropic-highlight 的 references/variable-mapping.md 定位最终法线 / 主光,用 --aniso-n / --aniso-l 给。

参数的出处:
  --skin r,g,b      常数肤色(来源 A,**线性值 0–1**):scripts/suggest_sheer_params.py 按「该角色自己的」皮肤贴图给,
                    或 diff_texture_variants.py 量出的丝袜底下肤色中位数换线性。不乘染色常量(SKILL.md 第 1 节)。
  --skin-slot tNN   贴图肤色的槽:ini 在 CustomShader 里把贴图绑到这个槽,先 grep 全 <Mods 根> 的 `ps-tN` 挑没人用的。
                    采样器 / UV / bias 抄原漫反射那一行。--skin 和 --skin-slot 一起给 = 带对比开关 SHEER_SKIN_FROM_TEX
                    (参数段里,默认 1 = 贴图、0 = 常数,改完 F10 对比);只给 --skin-slot 时不留常数肤色。
  --skin-slot-kind  bareleg(默认)= 光腿贴图(来源 B)，必须显式选择 --skin-tint-source shared|constant;
                   shared 仅限已证明同一染色链；constant 用 --skin-tint-linear r,g,b 指定光腿固定线性乘数。
                    baked = bake_skin_to_stocking_uv.py 烘焙的身体肤色(来源 C,独立丝袜网格)⇒ 只采样,不乘丝袜的染色常量。
  --style-index N   外观切换(每个透肉 mod 默认要做):调用点的高光乘 (IniParams[N].x > 0.5);IniParams 的名字从底子里
                    `Texture1D<float4> … : register(t120)` 的声明读(有的叫 t120、有的叫 IniParams),没声明就补。
                    要同时给 --aniso-n / --aniso-l;没在 --state 里写 SPEC_GAIN 的状态默认 1.0(只在外观第 1 档生效)。
                    N 必须来自空槽审计;每个状态 SPEC_GAIN 都须是有限正数,不能用 0 让切换失效。
  --no-style-switch  仅用户明确取消高光切换时使用;不能为了省略空槽审计或 N/L 定位使用。
  --state           状态名来自 mod ini 里切丝袜的变量 / 按键(SKILL.md「丝袜状态」),值来自 suggest_sheer_params.py;
                    键 = sheer_core.hlsl 参数段里的 SHEER_* 名(可省 SHEER_ 前缀、不分大小写)。不给 = 一份出厂值。
                    名字不是纯 ASCII 时用 @标签 给文件名(例:黑丝@black),否则按 s1、s2… 编号。
  --box u0,v0,u1,v1 UV 框(左闭右开):diff_texture_variants.py 找出的丝袜所在 UV 岛;独立丝袜网格不用给(默认整张图)。
  --spec-stocking-only  丝袜画在身体贴图上、又要开高光时打开:高光只乘丝袜像素(要 --skin-slot)。
  --tint-cb         注入锚点里的染色常量,默认 cb6[6](references/cases.md 时效表;换游戏版本先 grep 确认)。
  --aniso-n / --aniso-l  寄存器@行号,例 r15.xyz@1268:行号是输入 .fixed.hlsl 的行号,在该行之后捕获(之后必须在 main 顶层)。
  --view-line / --normal-input / --tangent-input  自动定位失败时手工指定(报错里会列候选)。
  --aniso-core      默认先找本包 assets/aniso_highlight_core.hlsl,再找同级 efmi-anisotropic-highlight/assets/。
  --sheer-core      默认本包 assets/sheer_core.hlsl。

退出码:0 = 全部生成且(若编译)严格编译通过;1 = 锚点 / 自检 / 编译失败;2 = 参数错误。
下一步(脚本最后会打印成可复制的命令):按实际编译签名分组，每组一个正式代表做 reflect_check.py 原 PS 对照，
用同一个 --compile-cache 复用相同条件的成功编译。只有底子回环失败或未解释整数差异才补 raw-int 审计，不跑八档矩阵。
检查版(<名>_probe.hlsl)只做严格编译(本脚本已做),不跑 reflect_check。
"""
from __future__ import annotations

# 输入是忠实修补后的 HLSL、两份核心模板和每个状态的参数；原底子只读。
# 输出是每状态一份正式 HLSL、默认一份绿色探针 HLSL，以及显式 --report 时的构建报告。
# “候选 / 捕获 / 覆写”数字用于证明 V、N、L 等寄存器映射；候选不唯一或捕获后有写入会直接停止。
# 每个状态的“0 告警、N B”表示严格编译通过及字节码大小；字节数只用于发现异常分支，不是质量分数。
# “失败 N”统计编译失败的输出数；N 必须为 0。成功退出 0，定位/模板/编译任一失败退出 1。

import argparse
import glob
import hashlib
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FXC_PATTERNS = [
    r'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\fxc.exe',
    r'C:\Program Files (x86)\Windows Kits\10\bin\x64\fxc.exe',
    r'C:\Program Files\Windows Kits\10\bin\*\x64\fxc.exe',
]
PARAM_BEGIN = '// ==================== 可调参数'
PARAM_END = '// ==================== 以上'
CORE_BEGIN = '// ---- 透肉核心'
CORE_END = '/* ---------------- 注入片段'
TOP_NOTE = '// ---- 以下为 build_sheer_ps.py 生成的着色器本体,不要手改;可调参数只在上面那一段 ----'

# Rebuild recipe written into the head of every generated file: the command line that made it and the base's hash.
# This replaces any separate build report — the installed .hlsl is the only record needed to redo or debug a build.
RECIPE_LINES: list[str] = []


# Build the reproducible command and base hash stored at the top of each generated shader.
def recipe_lines(a) -> list[str]:
    import shlex
    import hashlib as _h
    argv = list(sys.argv)
    argv[0] = 'scripts/' + os.path.basename(argv[0])
    cmd = ' '.join(shlex.quote(x) if ' ' in x or '"' in x else x for x in argv)
    sha = _h.sha256(open(a.fixed, 'rb').read()).hexdigest()
    return ['// 重建命令(在 skill 目录下运行;底子 = 修补过的反编译,sha256 见下):',
            f'//   python {cmd}',
            f'// 底子 sha256 {sha}   底子文件 {os.path.basename(a.fixed)}']


# Mark an unsafe or ambiguous build condition that must stop generation.
class BuildError(Exception):
    pass


# Raise a consistent build error from deep validation helpers.
def die(msg: str):
    raise BuildError(msg)


# Decode shader text and retain the detected encoding for byte-faithful output.
def read_text(path: str) -> tuple[str, str]:
    raw = open(path, 'rb').read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('gbk', errors='replace')
    nl = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n'), nl


# Resolve an explicit or installed fxc executable before using the DLL fallback.
def find_fxc(given: str | None) -> str | None:
    if given:
        return given if os.path.isfile(given) else None
    for pat in FXC_PATTERNS:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


# Import the bundled compiler wrapper without requiring it as a Python package.
def load_d3dc():
    """同目录的 d3dc.py(系统 d3dcompiler_47.dll 的 ctypes 封装),没有 fxc 时用;缺文件 / 用不了返回 None。"""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # 别在 skill 目录里留 __pycache__
    try:
        import d3dc
        d3dc.load()
        return d3dc
    except Exception:
        return None
    finally:
        sys.dont_write_bytecode = old


# Compile one generated shader with warnings treated as errors.
def strict_compile(comp, src: str, out_bin: str, compile_cache=None):
    """/T ps_5_0 /E main /Ges /WX /O3。comp = fxc 路径或 d3dc 模块。返回 (通过?, 编译器原话)。"""
    if isinstance(comp, str):
        if compile_cache:
            print('编译缓存: fxc 实际 DLL 身份无法可靠追踪，本次重新严格编译')
        r = subprocess.run([comp, '/nologo', '/T', 'ps_5_0', '/E', 'main', '/Ges', '/WX', '/O3', '/Fo', out_bin, src],
                           capture_output=True, text=True, errors='replace')
        return r.returncode == 0, (r.stdout + r.stderr)
    res = comp.compile_file(src, out_bin=out_bin, compile_cache=compile_cache)
    return bool(res.ok), res.messages or ''


# Strip line comments before matching generated-code anchors.
def code_part(s: str) -> str:
    return s.split('//', 1)[0]


# ============================================================== main 结构

# Index the main function, braces, and register writes needed for safe insertion.
class Body:
    """main 的行表:每行所在深度、写了哪个寄存器。"""

    # Parse main once so every locator shares the same source coordinates.
    def __init__(self, lines: list[str]):
        self.lines = lines
        mains = [k for k, l in enumerate(lines) if l.startswith('void main(')]
        if len(mains) != 1:
            die(f'`void main(` 出现 {len(mains)} 次(须 1 次):输入不像反编译底子')
        self.main = mains[0]
        k = self.main
        while k < len(lines) and lines[k].strip() != '{':
            k += 1
        if k >= len(lines):
            die('main 的签名后面找不到 `{`')
        self.sig = '\n'.join(lines[self.main:k])
        self.b0 = k + 1
        self.b1 = next((j for j in range(self.b0, len(lines)) if lines[j].rstrip() == '}'), None)
        if self.b1 is None:
            die('找不到 main 结束的顶格 `}`')
        self.depth_in: dict[int, int] = {}     # 行所在深度
        self.depth_after: dict[int, int] = {}  # 这一行之后的深度(在它后面插入的代码所处深度)
        self.stmts: list[int] = []             # 语句行
        d = 0
        for li in range(self.b0, self.b1):
            s = code_part(lines[li]).strip()
            if not s:
                continue
            if s == '}':
                d -= 1
                self.depth_in[li] = d
            elif s == '} else {':
                self.depth_in[li] = d - 1
            else:
                self.depth_in[li] = d
                if re.match(r'^(if \(.*\)|while \(true\)|switch\s*\(.*\))\s*\{$', s):
                    d += 1
            self.depth_after[li] = d
            if not re.match(r'^(float4 r\d|uint4 bitmask|float4 fDest|const float4 icb|\{\s*-?[\d.])', s) and not s.endswith('} };'):
                self.stmts.append(li)
        self.inputs: dict[str, tuple[str, str]] = {}   # 语义 -> (寄存器, 类型)
        for m in re.finditer(r'(?:nointerpolation\s+|linear\s+|noperspective\s+|centroid\s+|sample\s+)*\b(float|uint|int)(\d?)\s+(v\d+)\s*:\s*(\w+)', self.sig):
            self.inputs[m.group(4).upper()] = (m.group(3), m.group(1) + m.group(2))

    # Return comment-free code for one zero-based source line.
    def code(self, li: int) -> str:
        return code_part(self.lines[li]).strip()

    @staticmethod
    # Extract the destination register and written components from one assignment.
    def writes(code: str):
        """这一行写的寄存器与分量;不认得 → None。"""
        m = re.match(r'^if \(\d+ == 0\) (r\d+)\.([xyzw]) = 0;', code)
        if m:
            return m.group(1), m.group(2)
        m = re.search(r'^bitmask\.[xyzw] = .*;\s*(r\d+)\.([xyzw]+)\s*=', code)
        if m:
            return m.group(1), m.group(2)
        m = re.match(r'^(r\d+|o\d+)(?:\.([xyzw]+))?\s*=(?!=)', code)
        if m:
            return m.group(1), m.group(2) or 'xyzw'
        m = re.match(r'^sincos\([^,]+,\s*(r\d+)\.([xyzw]+)', code)
        if m:
            return m.group(1), m.group(2)
        return None

    # List writes that overlap a captured register component interval.
    def regcheck(self, reg: str, comps: str, lo: int, hi: int) -> list[int]:
        """lo..hi(0 基、含两端)之间写 reg 的这些分量的行(与 aniso 的 regcheck.py 同一判据,另认 ubfe / bfi 模板)。"""
        hits = []
        for li in range(lo, hi + 1):
            if li < self.b0 or li >= self.b1:
                continue
            w = self.writes(self.code(li))
            if w and w[0] == reg and set(w[1]) & set(comps):
                hits.append(li)
        return hits


# ============================================================== 定位

# Locate the normalized TEXCOORD1 view vector before the diffuse anchor.
def locate_view(B: Body, before: int, forced: int | None):
    tc1 = B.inputs.get('TEXCOORD1')
    if not tc1:
        die('main 签名里没有 TEXCOORD1 输入:V 定位不了,用 --view-line 指定 V 赋值行')
    vk = tc1[0]
    rx = re.compile(r'^(r\d+)\.([xyzw]{3}) = (?:(r\d+)\.xyz \* (r\d+)\.([xyzw])\5\5|(r\d+)\.([xyzw])\7\7 \* (r\d+)\.xyz);$')
    cands = []
    for n, li in enumerate(B.stmts):
        if li >= before:
            break
        if forced is not None and li != forced:
            continue
        m = rx.match(B.code(li))
        if not m:
            continue
        v, vcomps = m.group(1), m.group(2)
        a, s, c = (m.group(3), m.group(4), m.group(5)) if m.group(3) else (m.group(8), m.group(6), m.group(7))
        prev = [B.code(k) for k in B.stmts[max(0, n - 8):n]]
        if not any(re.match(rf'^{s}\.{c} = rsqrt\(', p) for p in prev[-4:]):
            continue
        dot_at = [i for i, p in enumerate(prev) if re.search(rf'= dot\({a}\.xyz, {a}\.xyz\);$', p)]
        if not dot_at:
            continue
        defs = [p for p in prev[:dot_at[-1]] if re.match(rf'^{a}\.[xyzw]+ = ', p)]
        if not any(re.search(rf'\b{vk}\.xyz\b', p) for p in defs):
            continue
        cands.append((li, v, vcomps))
    if forced is not None and not cands:
        die(f'--view-line {forced + 1} 那一行不是认得的 V 归一化形式 `rV.xyz = rA.xyz * rS.www`')
    if len(cands) != 1:
        die(f'V(TEXCOORD1 = {vk} 的归一化链)命中 {len(cands)} 次,须 1 次'
            + (':候选 ' + ', '.join(f'第 {item[0] + 1} 行' for item in cands) if cands else '')
            + ' —— 核对后用 --view-line 指定')
    li, v, vcomps = cands[0]
    if B.depth_after[li] != 0:
        die(f'V 赋值行(第 {li + 1} 行)不在 main 顶层,不能在这里捕获;用 --view-line 指定顶层的那一行')
    return li, v, vcomps, vk


# Locate a unique geometry normal and tangent basis or validate the caller's explicit inputs.
def locate_tbn(B: Body, n_forced: str | None, t_forced: str | None):
    if n_forced or t_forced:
        if not (n_forced and t_forced):
            die('--normal-input 和 --tangent-input 要一起给')
        return n_forced, t_forced, None, None
    hits = []
    codes = [B.code(li) for li in B.stmts]
    for n in range(len(codes) - 2):
        m0 = re.match(r'^(r\d+)\.xyz = (v\d+)\.yzx \* (v\d+)\.zxy;$', codes[n])
        if not m0:
            continue
        c, p, q = m0.groups()
        if not re.match(rf'^{c}\.xyz = {q}\.yzx \* {p}\.zxy \+ -{c}\.xyz;$', codes[n + 1]):
            continue
        m2 = re.match(rf'^{c}\.xyz = (?:(v\d+)\.www \* {c}\.xyz|{c}\.xyz \* (v\d+)\.www);$', codes[n + 2])
        if not m2:
            continue
        t = m2.group(1) or m2.group(2)
        if t not in (p, q):
            continue
        hits.append((q if t == p else p, t, B.stmts[n]))
    pairs = list(dict.fromkeys((h[0], h[1]) for h in hits))
    where = ', '.join(f'{sorted(set(h[:2]))} 第 {h[2] + 1} 行' for h in hits)
    if not pairs:
        die('TBN 叉积三连一处都没有,认不出几何法线 / 切线输入 —— 用 --normal-input / --tangent-input 指定'
            f'(EFMI 惯例:TEXCOORD2 = 几何法线,TEXCOORD3 = 切线 xyz + 手性 w,本 PS:'
            f'{", ".join(f"{k}={v[0]}" for k, v in B.inputs.items() if k.startswith("TEXCOORD"))})')
    note = None
    if len(pairs) > 1:
        # 不止一组(例:另一套 UV 的细节法线也重建了 TBN)。只在「最先出现」和「法线输入编号最小」指向同一组时自动取,否则停下
        first = pairs[0]
        lowest = min(pairs, key=lambda p: int(p[0][1:]))
        if first != lowest:
            die(f'TBN 叉积三连认出了不止一组输入({where}),且最先出现的与编号最小的不是同一组 —— '
                '用 --normal-input / --tangent-input 指定(几何法线一般是材质法线贴图那次 TBN 用的那组)')
        note = f'TBN 叉积三连认出不止一组输入({where}),按「最先出现、法线输入编号最小」取 {first};不对就用 --normal-input / --tangent-input'
    n, t = pairs[0]
    return n, t, [h[2] for h in hits if (h[0], h[1]) == (n, t)], note


# Find the diffuse sample multiplied by the selected tint constant exactly once.
def locate_anchor(B: Body, tint_cb: str):
    cb = re.escape(tint_cb)
    rx = re.compile(rf'^(r\d+)\.([xyzw]{{3,4}}) = (?:{cb}\.([xyzw]{{3,4}}) \* (r\d+)\.([xyzw]{{3,4}})|(r\d+)\.([xyzw]{{3,4}}) \* {cb}\.([xyzw]{{3,4}}));$')
    hits = [li for li in B.stmts if rx.match(B.code(li))]
    if len(hits) != 1:
        other = [li for li in B.stmts if re.search(rf'{cb}\.[xyzw]+ \*|\* {cb}\.[xyzw]+', B.code(li))]
        die(f'注入锚点 `rX = {tint_cb}.xyz(w) * <漫反射采样>` 命中 {len(hits)} 次(须 1 次)'
            + (f';含 {tint_cb} 乘法的行:' + ', '.join(f'第 {li + 1} 行' for li in other[:6]) if other else
               ':一处都没有 —— 给的多半不是材质 PS(描边 / 阴影 PS 没有这一行),或游戏更新后染色常量换了位置(--tint-cb)'))
    li = hits[0]
    m = rx.match(B.code(li))
    dst, dm = m.group(1), m.group(2)
    src, sm = (m.group(4), m.group(5)) if m.group(4) else (m.group(6), m.group(7))
    if B.depth_after[li] != 0:
        die(f'注入锚点(第 {li + 1} 行)不在 main 顶层,透肉块插在这里不是每个像素都跑 —— 需要人工看')
    fab = f'{dst}.{dm[:3]}'
    # rY 最近的写入:必须是贴图采样(if / else 两支都算)
    writers, seen_branch = [], False
    k = B.stmts.index(li) - 1
    while k >= 0:
        lk = B.stmts[k]
        code = B.code(lk)
        if seen_branch and B.depth_in[lk] == B.depth_in[li] and re.match(r'^if \(.*\) \{$', code):
            break
        w = Body.writes(code)
        if w and w[0] == src and set(w[1]) & set(sm[:3]):
            writers.append(lk)
            if B.depth_in[lk] <= B.depth_in[li]:
                break
            seen_branch = True
        k -= 1
    samples = []
    for lk in writers:
        ms = re.match(rf'^{src}\.[xyzw]+ = (t\d+)\.(Sample\w*)\((.*)\)\.[xyzw]+;$', B.code(lk))
        if not ms:
            die(f'注入锚点右边的 {src} 最近一次(第 {lk + 1} 行)不是贴图采样:{B.code(lk)[:90]} —— 这份 PS 可能不是材质 PS')
        samples.append((lk, ms.group(1), ms.group(2), ms.group(3)))
    if not samples:
        die(f'注入锚点之前找不到 {src} 的贴图采样')
    if len({(s[2], s[3]) for s in samples}) != 1:
        die('漫反射采样在两个分支里的采样器 / UV / bias 不一样,光腿贴图不知道该抄哪一个:' +
            '; '.join(f'第 {s[0] + 1} 行 {s[1]}.{s[2]}({s[3]})' for s in samples))
    method, args = samples[0][2], samples[0][3]
    parts = [p.strip() for p in args.split(',')]
    if len(parts) < 2:
        die(f'漫反射采样参数看不懂:{args}')
    return {'li': li, 'fab': fab, 'cb': tint_cb, 'method': method, 'args': args, 'uv': parts[1], 'samples': samples}


# Find the final colour call point after control-flow joins and before auxiliary outputs.
def locate_callpoint(B: Body):
    rets = [li for li in B.stmts if re.search(r'\breturn\b', B.code(li))]
    last = B.stmts[-1]
    if not rets or rets[-1] != last or B.code(last) != 'return;' or B.depth_in[last] != 0:
        die('main 的最后一句不是顶层的 `return;`,调用点定位不了')
    if len(rets) != 1:
        die('main 里除了末尾还有别的 return(' + ', '.join(f'第 {li + 1} 行' for li in rets[:-1]) +
            '):那些路径不会经过调用点 —— 需要人工决定')
    n = len(B.stmts) - 2
    trailing = []
    while n >= 0:
        li = B.stmts[n]
        w = Body.writes(B.code(li))
        if B.depth_in[li] == 0 and w and w[0].startswith('o'):
            trailing.insert(0, li)
            n -= 1
        else:
            break
    o0_tr = [li for li in trailing if Body.writes(B.code(li))[0] == 'o0']
    if o0_tr:
        after = o0_tr[-1]
        rest = trailing[trailing.index(after) + 1:]
    else:
        after = B.stmts[n]
        rest = trailing
    if any(Body.writes(B.code(li))[0] == 'o0' for li in rest):
        die('调用点之后还有写 o0 的语句,定位不可靠')
    if B.depth_after[after] != 0:
        die(f'调用点(第 {after + 1} 行之后)不在 main 顶层')
    o0_xyz = [li for li in B.stmts if li <= after and (Body.writes(B.code(li)) or ('', ''))[0] == 'o0'
              and set(Body.writes(B.code(li))[1]) & set('xyz')]
    if not o0_xyz:
        die('调用点之前没有任何写 o0.xyz 的语句')
    return after, o0_xyz


# Parse an explicit register capture and prove it survives unchanged to the call point.
def parse_capture(spec: str, B: Body, what: str, call_after: int):
    m = re.fullmatch(r'(r\d+)\.([xyzw]{3})@(\d+)', spec.strip())
    if not m:
        die(f'--aniso-{what} 格式应为 寄存器.xyz@行号(例 r15.xyz@1268):{spec}')
    reg, comps, line = m.group(1), m.group(2), int(m.group(3)) - 1
    if line not in B.depth_after:
        die(f'--aniso-{what} 的行号 {line + 1} 不在 main 里')
    if B.depth_after[line] != 0:
        die(f'--aniso-{what}:第 {line + 1} 行之后不在 main 顶层(在 if / loop 里),捕获不是每条路径都跑')
    if line >= call_after:
        die(f'--aniso-{what}:第 {line + 1} 行在调用点之后')
    k = B.stmts.index(line) if line in B.stmts else None
    written = False
    for lk in reversed(B.stmts[:(k + 1) if k is not None else 0]):
        w = Body.writes(B.code(lk))
        if w and w[0] == reg and set(w[1]) & set(comps):
            written = True
            break
    if not written:
        die(f'--aniso-{what}:第 {line + 1} 行及之前没有写 {reg}.{comps} 的语句')
    return reg + '.' + comps, line


# ============================================================== 核心与参数段

# Extract tunable parameters and callable core code using the four stable template markers.
def load_cores(sheer_path: str, aniso_path: str):
    st, _ = read_text(sheer_path)
    an, _ = read_text(aniso_path)
    sl = st.split('\n')
    try:
        p0 = next(k for k, l in enumerate(sl) if l.startswith(PARAM_BEGIN))
        p1 = next(k for k, l in enumerate(sl) if l.startswith(PARAM_END) and k > p0)
        c0 = next(k for k, l in enumerate(sl) if l.startswith(CORE_BEGIN))
        c1 = next(k for k, l in enumerate(sl) if l.startswith(CORE_END) and k > c0)
    except StopIteration:
        die(f'{sheer_path} 的结构变了:找不到「可调参数 / 以上 / 透肉核心 / 注入片段」分段标记')
    params = sl[p0:p1 + 1]
    core = sl[c0:c1]
    while core and not core[-1].strip():
        core.pop()
    tun = [m.group(1) for l in params for m in [re.match(r'^#define\s+(SHEER_\w+)\s', l)] if m]
    for n in tun:
        if any(re.match(rf'^#define\s+{n}\s', l) for l in core):
            die(f'{n} 在 sheer_core.hlsl 的参数段和核心段里都定义了')
    if an.count('#define ANISO_DEBUG_MODE') != 1 or an.count('float3 ApplyAnisoHighlight(') != 1:
        die(f'{aniso_path} 不像高光核心:`#define ANISO_DEBUG_MODE` / `ApplyAnisoHighlight(` 不是恰好 1 次')
    return params, tun, core, an.split('\n')


# Replace one anchored line and stop if the template shape is ambiguous.
def sub_once(lines: list[str], pat: str, repl, what: str) -> list[str]:
    rx = re.compile(pat)
    hits = [k for k, l in enumerate(lines) if rx.search(l)]
    if len(hits) != 1:
        die(f'sheer_core.hlsl 里「{what}」命中 {len(hits)} 次(须 1 次),模板结构变了')
    out = list(lines)
    out[hits[0]] = rx.sub(repl, out[hits[0]], count=1)
    return out


# Apply one state's tuning values while preserving every unselected template parameter.
def state_params(params: list[str], tun: list[str], name: str, vals: dict, n_states: int, probe=False) -> list[str]:
    out = [params[0]] + RECIPE_LINES
    out.append('// 检查模式(探针版):ANISO_DEBUG_MODE 1,整块纯绿 = 替换 PS 挂上了、门控命中了;这份里的参数不起作用'
               if probe else f'// 状态:{name}(build_sheer_ps.py 生成;{n_states} 份状态文件只差这一段)')
    for l in params[1:]:
        m = re.match(r'^(#define\s+(SHEER_\w+)\s+)(\S+)(.*)$', l)
        if m and m.group(2) in vals:
            v = vals[m.group(2)]
            out.append(m.group(1) + v.ljust(len(m.group(3))) + m.group(4))
        else:
            out.append(l)
    return out


# Parse state names, safe output labels, and key/value overrides from command-line specifications.
def parse_states(specs: list[str], tun: list[str]):
    states = []
    for n, spec in enumerate(specs or ['default'], 1):
        name, _, kv = spec.partition(':')
        name, _, tag = name.strip().partition('@')
        if not name:
            die(f'--state 缺名字:{spec}')
        tag = tag.strip() or (name if re.fullmatch(r'[A-Za-z0-9_\-]+', name) else f's{n}')
        if not re.fullmatch(r'[A-Za-z0-9_\-]+', tag):
            die(f'--state 的文件标签只能用字母数字 _ -:{tag}')
        vals = {}
        for item in filter(None, (x.strip() for x in kv.split(','))):
            k, eq, v = item.partition('=')
            if not eq:
                die(f'--state 里的「{item}」应为 键=值')
            key = k.strip().upper()
            key = key if key.startswith('SHEER_') else 'SHEER_' + key
            if key not in tun:
                die(f'--state 的键 {k.strip()} 不在 sheer_core.hlsl 参数段里(可用:{", ".join(t[6:] for t in tun)})')
            try:
                float(v)
            except ValueError:
                die(f'--state {name} 的 {key} 值不是数:{v}')
            vals[key] = v.strip()
        states.append((name, tag, vals))
    if len({t for _, t, _ in states}) != len(states):
        die('--state 的文件标签重复了')
    return states


# ============================================================== 组装

# Locate anchors, assemble each shader variant, run invariants, and compile requested outputs.
def build(a) -> int:
    # Bareleg colour and stocking colour may use different material multipliers.
    skin_multiplier = None
    if a.skin_slot and a.skin_slot_kind == 'bareleg':
        if a.skin_tint_source is None:
            die('TINT01: B 光腿贴图必须显式给 --skin-tint-source shared 或 constant。核对光腿颜色链；相同才选 shared，固定不同用 constant 和 --skin-tint-linear r,g,b；动态链先捕获真实颜色源及生命周期。')
        if a.skin_tint_source == 'constant':
            try:
                values = [float(x) for x in (a.skin_tint_linear or '').split(',')]
                if len(values) != 3 or any(not math.isfinite(x) or x < 0 or x > 3.402823466e38 for x in values):
                    raise ValueError()
            except ValueError:
                die('TINT02: constant 要三个有限、非负、可表示为 HLSL float 的线性 RGB。重新读取光腿固定乘数，填写 --skin-tint-linear r,g,b；不要填写丝袜染色或任意 HLSL。')
            skin_multiplier = 'float3(' + ', '.join(repr(x) for x in values) + ')'
        elif a.skin_tint_linear is not None:
            die('TINT03: shared 不接收 --skin-tint-linear；独立乘数请选择 constant。')
    elif a.skin_tint_source is not None or a.skin_tint_linear is not None:
        die('TINT04: --skin-tint-* 仅用于 B bareleg；C 的身体乘数请在 bake 的 --body-tint-linear 中应用一次。')
    # Require an audited switch binding unless the user explicitly opted out.
    if a.style_index is None and not a.no_style_switch:
        die('默认必须做高光切换:请审计空槽后提供 --style-index N,并提供 --aniso-n / --aniso-l;仅用户明确取消时可用 --no-style-switch')
    if a.style_index is not None:
        if a.no_style_switch:
            die('--style-index 与 --no-style-switch 不能同时使用')
        if not 0 <= a.style_index <= 4095:
            die(f'--style-index 要 0–4095:{a.style_index}')
        if not (a.aniso_n and a.aniso_l):
            die('默认高光切换需要 --aniso-n / --aniso-l;请定位最终法线和主光后提供寄存器@行号')
    if not os.path.isfile(a.fixed):
        die(f'找不到 {a.fixed}')
    text, nl = read_text(a.fixed)
    for bad in ('ANISO_DEBUG_MODE', 'LastRiteSheerBase', '[sheer]', 'ApplyAnisoHighlight'):
        if bad in text:
            die(f'底子里已经有 {bad}:要的是没注入过的 .fixed.hlsl')
    warn = []
    if '[fix-E' not in text and '[fidelity-fix' not in text:
        warn.append('底子里没有任何修补标记:确认已经跑过 fix_decompiler_defects.py(反编译原件不能直接当底子)')
    lines = text.split('\n')
    B = Body(lines)

    sheer_core = a.sheer_core or os.path.join(SKILL, 'assets', 'sheer_core.hlsl')
    cands = [a.aniso_core] if a.aniso_core else [os.path.join(SKILL, 'assets', 'aniso_highlight_core.hlsl'),
                                                  os.path.join(os.path.dirname(SKILL), 'efmi-anisotropic-highlight', 'assets', 'aniso_highlight_core.hlsl')]
    aniso_core = next((p for p in cands if p and os.path.isfile(p)), None)
    if not aniso_core:
        die('找不到高光核心 aniso_highlight_core.hlsl:用 --aniso-core 指定(efmi-anisotropic-highlight/assets/ 里)')
    if not os.path.isfile(sheer_core):
        die(f'找不到透肉模板 {sheer_core}')
    params, tun, core, aniso = load_cores(sheer_core, aniso_core)
    params, tun = list(params), list(tun)
    global RECIPE_LINES
    RECIPE_LINES = recipe_lines(a)
    if a.skin and a.skin_slot:   # 对比开关放进最上面的参数段:用户改完 F10 就能对比
        k = max(i for i, l in enumerate(params) if re.match(r'#define\s+SHEER_\w+', l))
        params = params[:k + 1] + ['#define SHEER_SKIN_FROM_TEX  1      // 肤色来源:1 = 贴图(--skin-slot,默认);0 = 常数 SHEER_SKIN_ALBEDO。改完保存按 F10 对比'] + params[k + 1:]
        tun = tun + ['SHEER_SKIN_FROM_TEX']
    states = parse_states(a.state, tun)
    if a.style_index is not None:   # 外观切换:高光只在第 1 档生效,状态没写 SPEC_GAIN 就默认 1.0
        for name, _, vals in states:
            vals.setdefault('SHEER_SPEC_GAIN', '1.0')
            # Every material state needs an effective highlight-on setting.
            gain = float(vals['SHEER_SPEC_GAIN'])
            if not math.isfinite(gain) or not 1.1754943508222875e-38 <= gain <= 3.4028234663852886e38:
                die(f'--state {name} 的 SPEC_GAIN 必须是有限正数且在 HLSL float 正规值范围内:删除该覆盖值以使用 1.0,或提供有效增益')
            # Emit a portable HLSL literal instead of Python-only numeric spellings.
            vals['SHEER_SPEC_GAIN'] = repr(gain)

    # ---- 定位
    bm = [li for li in range(B.b0, B.b1) if lines[li].strip() == 'uint4 bitmask, uiDest;']
    if len(bm) != 1:
        die(f'main 里 `uint4 bitmask, uiDest;` 命中 {len(bm)} 次(须 1 次),声明点定位不了')
    decl_li = bm[0]
    anc = locate_anchor(B, a.tint_cb)
    v_li, v_reg, v_comps, vk = locate_view(B, anc['li'], (a.view_line - 1) if a.view_line else None)
    if v_li <= decl_li:
        die('V 赋值行在声明点之前,不对劲')
    nrm, tan, tbn_li, tbn_note = locate_tbn(B, a.normal_input, a.tangent_input)
    if tbn_note:
        warn.append(tbn_note)
    call_after, o0_writes = locate_callpoint(B)
    if not (decl_li < v_li < anc['li'] < call_after):
        die(f'锚点顺序不对:声明 {decl_li + 1} / V {v_li + 1} / 注入 {anc["li"] + 1} / 调用点 {call_after + 1}')
    v_dirty = B.regcheck(v_reg, v_comps, v_li + 1, anc['li'])
    capN = parse_capture(a.aniso_n, B, 'n', call_after) if a.aniso_n else None
    capL = parse_capture(a.aniso_l, B, 'l', call_after) if a.aniso_l else None
    look, look_lines, look_mul = None, [], ''
    if a.style_index is not None:
        if not (capN and capL):
            die('--style-index(外观切换)要开高光,得同时给 --aniso-n / --aniso-l(最终法线 / 主光)')
        if not 0 <= a.style_index <= 4095:
            die(f'--style-index 要 0–4095:{a.style_index}')
        m = re.search(r'Texture1D<float4>\s+(\w+)\s*:\s*register\(\s*t120\s*\)', text)
        look = (m.group(1) if m else 'IniParams', a.style_index, bool(m))
        look_lines = [f'    float _shLook = ({look[0]}.Load(int2({look[1]}, 0)).x > 0.5) ? 1.0 : 0.0;'
                      f'   // [sheer] 外观切换:ini 每次 draw 前写 x{look[1]} = $<mod>_style(0 只透肉 / 1 透肉 + 高光)']
        look_mul = ' * _shLook'

    # ---- 肤色来源:常数(A)/ 贴图(B 光腿、C 烘焙);常数 + 贴图一起给 = 带对比开关 SHEER_SKIN_FROM_TEX(默认贴图)
    if not (a.skin or a.skin_slot):
        die('要给肤色来源:--skin r,g,b(常数,线性)和 / 或 --skin-slot tNN(光腿贴图 / 烘焙肤色贴图)')
    core2 = list(core)
    tint3 = f'{anc["cb"]}.xyz'
    if a.skin:
        try:
            rgb = [float(x) for x in a.skin.split(',')]
        except ValueError:
            die(f'--skin 要三个数:{a.skin}')
        if len(rgb) != 3 or any(not (0.0 <= c <= 1.0) for c in rgb):
            die(f'--skin 要三个 0–1 的线性值(不是 sRGB 0–255;suggest_sheer_params.py 会给):{a.skin}')
        core2 = sub_once(core2, r'(#define\s+SHEER_SKIN_ALBEDO\s+)float3\([^)]*\)',
                         lambda m: m.group(1) + 'float3({:.4f}, {:.4f}, {:.4f})'.format(*rgb), 'SHEER_SKIN_ALBEDO')
    else:
        # 只用贴图:模板里那行示例常数(别的角色的肤色)删掉,免得留下误导人的数
        core2 = sub_once(core2, r'^#define\s+SHEER_SKIN_ALBEDO\s+float3\([^)]*\).*$',
                         '// (本份只用贴图肤色 --skin-slot,没有常数肤色 SHEER_SKIN_ALBEDO)', 'SHEER_SKIN_ALBEDO')
    if a.skin_slot:
        slot = a.skin_slot.strip().lower()
        if not re.fullmatch(r't\d+', slot):
            die(f'--skin-slot 要写成 tNN:{a.skin_slot}')
        if re.search(rf'register\(\s*{slot}\s*\)', text):
            die(f'{slot} 已经被这份 PS 自己声明了,换一个没人用的槽')
        core2 = sub_once(core2, r'^//\s*Texture2D<float4>\s+t\d+\s*:\s*register\(t\d+\);',
                         f'Texture2D<float4> {slot} : register({slot});', '光腿贴图声明(注释掉的 t90 那行)')
        samp = f'{slot}.{anc["method"]}({anc["args"]}).xyz'
        if a.skin_slot_kind == 'baked':
            tex_expr = samp
            tex_note = (f'烘焙肤色 {slot}(身体腿部肤色按丝袜 UV 烘好):与原漫反射同采样器 / UV / bias({anc["args"]});'
                        f'不乘 {tint3} —— 那是丝袜自己的染色')
        else:
            multiplier = skin_multiplier or tint3
            tex_expr = f'{multiplier} * {samp}'
            tex_note = f'光腿贴图 {slot}:与原漫反射同采样器 / UV / bias；光腿染色来源 {a.skin_tint_source}: {multiplier}'
    if a.skin and a.skin_slot:
        skin_lines = ['#if SHEER_SKIN_FROM_TEX',
                      f'    float3 _shSkin = {tex_expr};   // {tex_note}',
                      '#else',
                      '    float3 _shSkin = SHEER_SKIN_ALBEDO;   // 常数肤色(线性),对比用',
                      '#endif']
        skin_note = f'对比开关 SHEER_SKIN_FROM_TEX(默认 1 = {tex_note};0 = 常数 SHEER_SKIN_ALBEDO)'
    elif a.skin_slot:
        skin_lines = [f'    float3 _shSkin = {tex_expr};   // {tex_note}']
        skin_note = tex_note
    else:
        skin_lines = ['    float3 _shSkin = SHEER_SKIN_ALBEDO;   // 常数肤色 SHEER_SKIN_ALBEDO(线性,不乘染色常量)']
        skin_note = '常数肤色 SHEER_SKIN_ALBEDO(线性,不乘染色常量)'
    if look and not look[2]:
        core2.insert(0, f'Texture1D<float4> IniParams : register(t120);   // [sheer] 3DMigoto IniParams:外观切换读 x{look[1]}(底子没声明,补上)')
    if a.spec_stocking_only:
        if not a.skin_slot:
            die('--spec-stocking-only 要配 --skin-slot(丝袜像素标记靠「当前贴图 ≠ 光腿贴图」)')
        if a.skin_slot_kind == 'baked':
            die('--spec-stocking-only 只给光腿贴图(来源 B)用;烘焙肤色是独立丝袜网格,整片都是袜子')
        core2 = sub_once(core2, r'^(#define\s+SHEER_SPEC_STOCKING_ONLY\s+)0\b', r'\g<1>1', 'SHEER_SPEC_STOCKING_ONLY')
    if a.box:
        try:
            box = [float(x) for x in a.box.split(',')]
        except ValueError:
            die(f'--box 要四个数:{a.box}')
        if len(box) != 4 or not (box[0] < box[2] and box[1] < box[3]):
            die(f'--box 应为 u0,v0,u1,v1 且 u0<u1、v0<v1:{a.box}')
        for nm, v in zip(('U0', 'V0', 'U1', 'V1'), box):
            core2 = sub_once(core2, rf'^(#define\s+SHEER_BOX_{nm}\s+)\S+', lambda m, v=v: m.group(1) + f'{v:g}' + ('' if '.' in f'{v:g}' else '.0'),
                             f'SHEER_BOX_{nm}')
    else:
        # 没给 UV 框 = 独立丝袜网格,整片都是袜子:遮罩恒 1(模板注释的约定)。不留 0..1 的默认框 ——
        # 那样 UV 超出 0..1(平铺 / 镜像岛)的像素会被静默关掉透肉,也多几条比较指令
        core2 = sub_once(core2, r'^(\s*)return \(uv\.x.*\) \? 1\.0 : 0\.0;',
                         r'\g<1>return 1.0;   // 没给 --box:独立丝袜网格,整片都是袜子(build_sheer_ps.py)', 'SheerMask 的 return')
    for need in ('float3 LastRiteSheerBase(', 'float SheerMask(', '#define SHEER_SPEC_STOCKING_ONLY'):
        if sum(l.count(need) for l in core2) != 1:
            die(f'sheer_core.hlsl 的透肉核心里「{need}」不是恰好 1 次')

    # ---- 注入内容
    fab, uv = anc['fab'], anc['uv']
    ins_after: dict[int, list[str]] = {}
    ins_after[decl_li] = [
        '  float3 _anisoV = 0, _anisoN = 0, _anisoL = 0;   // [sheer] 高光核心的 V / N / L(不开高光时 N = 几何法线、L = V 占位,只有探针档 2–5 读)',
        '  float _shCov = 1.0;    // [sheer] 纤维覆盖率(1 = 不透),给高光耦合',
        '  float _shScope = 0.0;  // [sheer] 范围探针档 7 用;正式档里是死代码',
        '  float _shStk = 1.0;    // [sheer] 丝袜像素标记(SHEER_SPEC_STOCKING_ONLY 用);独立丝袜网格保持 1',
    ]
    vcap = [f'  _anisoV = {v_reg}.{v_comps};   // [sheer] V:第 {v_li + 1} 行 {vk}(TEXCOORD1)归一化链,赋值后立即捕获']
    if not capN:
        vcap.append(f'  _anisoN = normalize({nrm}.xyz);   // [sheer] N 占位 = 几何法线;开高光时用 --aniso-n 换成最终法线')
    if not capL:
        vcap.append('  _anisoL = _anisoV;   // [sheer] L 占位 = V;开高光时用 --aniso-l 换成主光')
    ins_after.setdefault(v_li, []).extend(vcap)
    ins_after.setdefault(anc['li'], []).extend([
        '  {   // [sheer] Last Rite 白纱透肉:拿到「染色后的漫反射」立即换掉;之后 sRGB 链、湿身、落雪、光照照常吃新值',
        f'    float3 _shOrig = {fab};',
        *skin_lines,
        '    float  _shW = 1.0;',
        f'    float3 _shBase = LastRiteSheerBase({fab}, _shSkin, SHEER_ALPHA, normalize({nrm}.xyz), _anisoV, _shW);',
        f'    float  _shMix = SheerMask({uv}) * SHEER_GAIN;',
        f'    {fab} = lerp({fab}, _shBase, _shMix);',
        '    _shCov = lerp(1.0, _shW, _shMix);',
        f'    float3 _shRel = abs({fab} - _shOrig) / max(_shOrig, 0.02);',
        '    _shScope = smoothstep(0.05, 0.15, max(_shRel.x, max(_shRel.y, _shRel.z)));   // 相对改动 >5% 开始泛绿;BC 压缩噪声不亮',
        '#if SHEER_SPEC_STOCKING_ONLY',
        '    float3 _shStkD = abs(_shOrig - _shSkin) / max(_shSkin, 0.02);   // 只看「当前贴图 vs 光腿贴图」,与透肉参数无关',
        f'    _shStk = SheerMask({uv}) * smoothstep(0.05, 0.15, max(_shStkD.x, max(_shStkD.y, _shStkD.z)));',
        '#endif',
        '  }',
    ])
    for cap, var, what in ((capN, '_anisoN', 'N'), (capL, '_anisoL', 'L')):
        if cap:
            ins_after.setdefault(cap[1], []).append(f'  {var} = {cap[0]};   // [sheer] {what}:--aniso-{what.lower()} 给的第 {cap[1] + 1} 行之后捕获')
    ins_after.setdefault(call_after, []).extend([
        '  {   // [sheer] 调用点:最终颜色写进 o0 之后、其余输出与 return 之前。不开高光也照写:SHEER_SPEC_GAIN 0 时高光被常量折叠掉,探针档照样可用',
        f'    float3 _shLit = ApplyAnisoHighlight(o0.xyz, _anisoN, _anisoL, _anisoV, {tan}.xyz, {tan}.w);',
        '#if ANISO_DEBUG_MODE == 0 || ANISO_DEBUG_MODE == 7',
        *look_lines,
        '    if (SHEER_SPEC_GAIN > 0.0)          // 常量折叠:增益 0 时整段剔除,也避开 lerp(a, NaN, 0) = NaN',
        f'      o0.xyz = lerp(o0.xyz, _shLit, SHEER_SPEC_GAIN{look_mul} * lerp(1.0, _shCov, SHEER_SPEC_COUPLING) * _shStk);',
        '#if ANISO_DEBUG_MODE == 7',
        '    o0.xyz = lerp(o0.xyz, float3(0.0, 1.0, 0.0), _shScope);    // 范围探针:只把透肉真正改动过颜色的像素涂绿',
        '#endif',
        '#else',
        '    o0.xyz = _shLit;                    // 探针档原样写出;否则探针颜色会被覆盖率稀释,看不准',
        '#endif',
        '  }',
    ])

    # Insert declarations, captures, sheer code, and the final call without rewriting base lines.
    def assemble(ptext: list[str], probe: bool) -> tuple[list[str], list[tuple[str, int | None]]]:
        an = list(aniso)
        if probe:
            k = next(i for i, l in enumerate(an) if l.startswith('#define ANISO_DEBUG_MODE'))
            an[k] = re.sub(r'^(#define ANISO_DEBUG_MODE\s+)\d+', r'\g<1>1', an[k])
        rows: list[tuple[str, int | None]] = [(l, None) for l in ptext] + [('', None), (TOP_NOTE, None), ('', None)]
        for li, l in enumerate(lines):
            if li == B.main:
                rows += [(x, None) for x in an] + [('', None)] + [(x, None) for x in core2] + [('', None)]
            rows.append((l, li))
            for x in ins_after.get(li, []):
                rows.append((x, None))
        return [r[0] for r in rows], rows

    # ---- 生成 + 自检
    name = a.name
    if not name:
        m = re.search(r'([0-9a-fA-F]{16})', os.path.basename(a.fixed))
        name = f'sheer_{m.group(1)[:8].lower()}' if m else 'sheer_ps'
    os.makedirs(a.out_dir, exist_ok=True)
    outputs = []
    jobs = [(nm, tag, vals, False) for nm, tag, vals in states]
    if not a.no_probe:
        jobs.append(('探针', 'probe', states[0][2], True))
    for nm, tag, vals, probe in jobs:
        ptext = state_params(params, tun, nm, vals, len(states), probe=probe)
        out, rows = assemble(ptext, probe)
        # 自检 1:去掉插入的行 = 输入原样(只插入、不改一行)
        if [r[0] for r in rows if r[1] is not None] != lines:
            die('自检失败:输出去掉注入行后与输入不一致')
        body = '\n'.join(out)
        for n in tun:
            c = len(re.findall(rf'^#define {n}\s', body, re.M))
            if c != 1:
                die(f'自检失败:{n} 在输出里有 {c} 个 #define')
        want = {'#define ANISO_DEBUG_MODE': 1, 'float3 LastRiteSheerBase(': 1, 'LastRiteSheerBase(': 2,
                'float3 _shLit = ApplyAnisoHighlight(o0.xyz, _anisoN, _anisoL, _anisoV,': 1,
                f'_anisoV = {v_reg}.{v_comps};': 1, f'{fab} = lerp({fab}, _shBase, _shMix);': 1, 'float _shCov = 1.0;': 1}
        for pat, n in want.items():
            if body.count(pat) != n:
                die(f'自检失败:{pat!r} 出现 {body.count(pat)} 次,期望 {n}')
        path = os.path.join(a.out_dir, f'{name}_{tag}.hlsl')
        data = (nl.join(out) + nl).encode('utf-8')
        with open(path, 'wb') as f:
            f.write(data)
        outputs.append((nm, tag, path, data, probe))

    # ---- 编译自检
    comp, comp_desc = None, '跳过(--no-compile)'
    if not a.no_compile:
        comp = find_fxc(a.fxc) if a.compiler != 'd3dcompiler' else None
        comp_desc = f'fxc {comp}' if comp else ''
        if not comp:
            comp = load_d3dc()
            comp_desc = ('没找到 fxc,改用系统 d3dcompiler_47.dll(同目录 d3dc.py)' if comp else
                         '跳过:没找到 fxc.exe(Windows SDK),同目录也没有能用的 d3dc.py')
    comp_rows, failed = [f'  编译器:{comp_desc}'], 0
    if comp:
        with tempfile.TemporaryDirectory(prefix='sheer_build_') as work:
            for nm, tag, path, data, probe in outputs:
                binp = os.path.join(work, tag + '.bin')
                ok, msg = strict_compile(comp, path, binp, a.compile_cache)
                if ok:
                    b = open(binp, 'rb').read()
                    comp_rows.append(f'  {os.path.basename(path)}: 严格编译通过,{len(b)} B,sha256 {hashlib.sha256(b).hexdigest()}')
                else:
                    failed += 1
                    first = next((l for l in msg.splitlines() if 'error' in l), msg.strip()[:200])
                    comp_rows.append(f'  {os.path.basename(path)}: 编译失败 —— {first.strip()[-220:]}')

    # ---- 报告
    R = [f'build_sheer_ps.py 报告', f'底子     : {os.path.abspath(a.fixed)}(sha256 {hashlib.sha256(open(a.fixed, "rb").read()).hexdigest()})',
         f'高光核心 : {aniso_core}', f'透肉模板 : {sheer_core}', '']
    R += ['== 锚点(行号 = 底子 .fixed.hlsl 的行号;每个都恰好命中 1 次)',
          f'  声明点   第 {decl_li + 1} 行  {lines[decl_li].strip()}',
          f'  V        第 {v_li + 1} 行  {lines[v_li].strip()}   ({vk} = TEXCOORD1)',
          f'           regcheck {v_reg}.{v_comps} 第 {v_li + 2}..{anc["li"] + 1} 行(赋值 → 注入点)写入 {len(v_dirty)} 处'
          + (':' + ', '.join(str(x + 1) for x in v_dirty[:8]) + '(用的是赋值后立即捕获的 _anisoV,不受影响)' if v_dirty else '(寄存器本身也干净)'),
          f'  N / T    几何法线 {nrm}、切线 {tan}' + ('(TBN 叉积三连 ' + '、'.join(f'第 {x + 1}–{x + 3} 行' for x in tbn_li) + ')'
                                                    if tbn_li else '(手工指定)'),
          f'  注入点   第 {anc["li"] + 1} 行  {lines[anc["li"]].strip()}   织物色 = {fab},遮罩 UV = {uv}',
          '           漫反射采样:' + '; '.join(f'第 {s[0] + 1} 行 {s[1]}.{s[2]}({s[3]})' for s in anc['samples']),
          f'  调用点   第 {call_after + 1} 行之后(最后一次写 o0 之后;o0.xyz 写在第 {", ".join(str(x + 1) for x in o0_writes[-4:])} 行)',
          f'  肤色     {skin_note}']
    if look:
        R.append(f'  外观     IniParams[{look[1]}](底子里叫 {look[0]}{"" if look[2] else ",底子没声明,已补"}):'
                 f'0 只透肉 / 1 透肉 + 高光;ini 每次 draw 前写 x{look[1]} = $<mod>_style')
    for cap, what in ((capN, 'N'), (capL, 'L')):
        if cap:
            reg, line = cap
            dirty = B.regcheck(reg.split('.')[0], reg.split('.')[1], line + 1, call_after)
            R.append(f'  {what}(高光) {reg} 第 {line + 1} 行之后捕获;第 {line + 2}..{call_after + 1} 行对它写入 {len(dirty)} 处(用捕获值,不受影响)')
    R += [''] + [f'⚠ {w}' for w in warn] + ['== 输出']
    for nm, tag, path, data, probe in outputs:
        R.append(f'  {path}  ({"探针版 ANISO_DEBUG_MODE 1" if probe else "状态 " + nm}; sha256 {hashlib.sha256(data).hexdigest()})')
    R += ['', '== 编译自检(fxc /T ps_5_0 /E main /Ges /WX /O3)'] + (comp_rows or ['  跳过(--no-compile 或没找到 fxc)'])
    first = outputs[0][2]
    req = ' --require t120' + (' ' + a.skin_slot.lower() if a.skin_slot else '')

    # Prefer companion scripts in this skill and fall back to the shared original location.
    def tool(name):
        p = os.path.join(HERE, name)
        return f'"{p}"' if os.path.isfile(p) else f'<aniso>/scripts/{name}'
    reuse = (' --compiler d3dcompiler' if a.compiler == 'd3dcompiler' else '')
    if a.compile_cache:
        reuse += ' --compile-cache "' + os.path.abspath(a.compile_cache) + '"'
    R += ['', '== 下一步：按 references/step-08-static-gate.md 对实际编译签名分组，每组检查代表文件',
          f'  python {tool("reflect_check.py")} "{first}" --original "{os.path.abspath(a.fixed)}" '
          f'{req}{reuse} --out "{os.path.join(os.path.abspath(a.out_dir), "reflection")}"',
          f'  仅底子回环失败或有未解释整数差异时：python {tool("audit_raw_int_ops.py")} <目录>/replacement.asm；正常通过不重复审计。',
          f'  检查版 {name}_probe.hlsl 只做严格编译(上面已做),别跑 reflect_check:纯绿会把大部分代码剔掉,资源 / cb 对不上是正常的',
          '  任一反射或交付检查失败：修正后重跑；未全部通过时禁止运行 pack_mod.py 或创建交付 ZIP。']
    print('\n'.join(R))
    # No report file by default: the recipe header inside each generated .hlsl is the durable record.
    if a.report:
        rep = os.path.join(a.out_dir, f'{name}_build.txt')
        with open(rep, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(R) + '\n')
        print(f'报告另存:{rep}')
    return 1 if failed else 0


# Parse all build choices and convert a controlled BuildError into the documented exit code.
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    doc = __doc__ or ''
    ap = argparse.ArgumentParser(description='从忠实修补过的底子生成透肉替换 PS(按状态多份 + 探针版)。',
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=doc.split('\n\n', 2)[2] if doc.count('\n\n') >= 2 else None)
    ap.add_argument('fixed', help='fix_decompiler_defects.py 出的 <X>.fixed.hlsl')
    ap.add_argument('--out-dir', required=True, help='输出目录')
    ap.add_argument('--name', help='输出文件名前缀,默认 sheer_<hash 前 8 位>')
    ap.add_argument('--state', action='append', default=[], help='名[@文件标签]:键=值,…  可多次;例 黑丝@black:ALPHA=0.45,W_MIN=0.6,W_MAX=1.0')
    ap.add_argument('--skin', help='常数肤色(来源 A):线性 r,g,b(0–1)。和 --skin-slot 一起给 = 带对比开关 SHEER_SKIN_FROM_TEX(默认贴图,0 档用这个常数)')
    ap.add_argument('--skin-slot', help='贴图肤色的槽,例 t90:光腿贴图(来源 B)或烘焙肤色贴图(来源 C),种类见 --skin-slot-kind')
    ap.add_argument('--skin-slot-kind', choices=('bareleg', 'baked'), default='bareleg',
                    help='bareleg = 光腿贴图(必须显式选择 --skin-tint-source);baked = 已含身体染色的烘焙肤色(不再乘丝袜染色)')
    ap.add_argument('--skin-tint-source', choices=('shared', 'constant'),
                    help='B 必填: shared 仅限已证实光腿和丝袜染色相同；constant 使用独立固定线性乘数')
    ap.add_argument('--skin-tint-linear', help='constant 必填:光腿固定线性 RGB 乘数 r,g,b，有限且非负；动态链须先现场映射')
    style = ap.add_mutually_exclusive_group(required=True)
    style.add_argument('--style-index', type=int,
                    help='默认必做外观切换:审计后的 IniParams 下标 N,ini 每次 draw 前写 xN = $<mod>_style(0 只透肉 / 1 透肉 + 高光);要同时给 --aniso-n / --aniso-l')
    style.add_argument('--no-style-switch', action='store_true',
                    help='仅用户明确取消高光切换时使用;不能以此跳过空槽审计或 N/L 定位')
    ap.add_argument('--box', help='UV 框 u0,v0,u1,v1(左闭右开),默认整张图')
    ap.add_argument('--spec-stocking-only', action='store_true', help='高光只打丝袜像素(要 --skin-slot)')
    ap.add_argument('--tint-cb', default='cb6[6]', help='注入锚点里的染色常量,默认 cb6[6]')
    ap.add_argument('--aniso-core', help='高光核心 aniso_highlight_core.hlsl 路径')
    ap.add_argument('--sheer-core', help='透肉模板 sheer_core.hlsl 路径,默认本包 assets/')
    ap.add_argument('--aniso-n', help='开高光用:最终法线 寄存器.xyz@行号')
    ap.add_argument('--aniso-l', help='开高光用:主光方向 寄存器.xyz@行号')
    ap.add_argument('--view-line', type=int, help='自动定位失败时:V 赋值行的行号')
    ap.add_argument('--normal-input', help='自动定位失败时:几何法线输入,例 v3')
    ap.add_argument('--tangent-input', help='自动定位失败时:切线输入,例 v4')
    ap.add_argument('--no-probe', action='store_true', help='不出探针版')
    ap.add_argument('--report', action='store_true', help='另存 <名>_build.txt(默认不写:屏幕输出 + hlsl 头部的重建命令就是全部记录)')
    ap.add_argument('--no-compile', action='store_true', help='不做 fxc 严格编译自检')
    ap.add_argument('--fxc', help='fxc.exe 路径,默认按 Windows SDK 标准位置找')
    ap.add_argument('--compiler', choices=('auto', 'd3dcompiler'), default='auto',
                    help='d3dcompiler 固定使用系统 DLL，便于跨步骤复用严格编译结果')
    ap.add_argument('--compile-cache', help='可选临时缓存目录；源码或编译条件改变自动重编译')
    a = ap.parse_args()
    try:
        return build(a)
    except BuildError as e:
        print(f'停下:{e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
