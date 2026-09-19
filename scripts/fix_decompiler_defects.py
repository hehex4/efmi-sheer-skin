#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""fix_decompiler_defects.py —— 把 cmd_Decompiler 反编译出的材质 PS 修成「严格编译 0 告警、语义与游戏字节码一致」的底子。
只读输入,只用标准库(编译检查要 fxc.exe)。(skill efmi-sheer-skin 第 2 节第 3、4 步)

    python fix_decompiler_defects.py <X.hlsl> [--msasm <X.msasm>] [--out-dir 目录] [--fxc fxc.exe 路径] [--no-compile]

输入:
  <X.hlsl>   `cmd_Decompiler.exe -D <bin>` 在 bin 旁边出的反编译原件,一字未改(已经修过的会被拒:含 [fix-E / [fidelity-fix 标记)。
             也收 hunting 导出的 `<hash>-ps_replace.txt`:它末尾块注释里的汇编就是真值,这时可以不给 --msasm。
  --msasm    同一个 bin 的 `cmd_Decompiler.exe --disassemble-ms <bin>` 输出(游戏字节码的反汇编,当真值)。
输出(默认写在输入旁边,--out-dir 改位置;输入文件本身不动):
  <X>.fixed.hlsl         修好的底子(给 build_sheer_ps.py);_replace.txt 输入时去掉末尾的注释汇编
  <X>.fixed.report.txt   逐处修补日志(行号、缺陷类、改前 / 改后、对应汇编行)+ 需要手工 + 提示 + 编译回环对照表
退出码:0 = 全部自动修好、严格编译 0 告警;1 = 有「需要手工」或编译没过;2 = 输入 / 参数错误。

做法(不认 hash、不认行号,全靠模式 + 与汇编交叉核对):
  1. 对齐:反编译器基本是一条汇编指令一条 HLSL 语句,按「写哪个寄存器 / 哪种控制流」把两边逐条对上
     (ubfe / bfi 这类一条指令拆成多行的也认)。对齐率低于 98% 就不往下做,列「需要手工」。
  2. 按汇编逐分量追踪每个寄存器存的是什么(if / else / loop 按结构合流):
       F 浮点、Rc 常量缓冲原始位、Rs 结构化缓冲原始位、B 32 位位模式(位掩码 / 哈希 / 整数造的浮点位)
       N 小整数、M 比较掩码、U uint 类型的输入(材质号、正反面)、Z 零
     反编译器把整数按「数值」存进 float 寄存器 —— 对 N / M / U 没问题;对 Rc / Rs / B 就是下表 E6–E8
     那一类「编译得过、值是错的」。
  3. 对上的 HLSL 逐条按下表检查:认得出的直接改(同一行只改那几个记号,不重写整段),每处记日志;
     认得出但改不了的列「需要手工」。
  4. 严格编译(fxc /T ps_5_0 /E main /Ges /WX /O3):X4000 → 补 0 初值(E5);X4115 → 按 E1 改;其它错误列「需要手工」。
  5. 编译回环:修好的 HLSL 重编译,把位运算关键指令(if_nz cb、ubfe、and l(0x3f800000)、imad、xor …)
     的条数与游戏字节码逐项对照,写进报告。

| 类 | 游戏字节码 | 反编译器写成 | 本脚本改成 |
|---|---|---|---|
| E1 | 整数指令(典型 bfi)读比较掩码 | (uint)<cmp 结果>,cmp 真值是 -1.0(X4115 或静默错) | (x != 0 ? 0xffffffffu : 0u) |
| E2 | and <比较掩码>, l(N) | x ? 0.000000 : 0(常量 N 丢成 0) | x ? N : 0 |
| E3 | dcl_resource_texture1d + ld | 漏声明;.Load(float4(..)) 缺对象名(X3000) | 补 Texture1D 声明;tN.Load(int2(x, mip)) |
| E4 | ld_aoffimmi(u,v,w) | tN.Load(r.xy, int3(0,0,0)):维度错、偏移丢 | tN.Load(int3(r.xy, mip), int2(u, v)) |
| E5 | —(fxc 流分析保守) | X4000 可能未初始化 | main 开头显式 0 初值 |
| E6 | 整数指令读原始位(天气字、灯光字节、结构化缓冲下标、光源位掩码) | (int)x / (uint)x 数值转换 | asint(x) / asuint(x);ubfe 模板整行改成 (asuint(x) >> o) & m |
| E6c | if_nz / breakc / movc 直接判原始位(灯光类型、位掩码) | if (x != 0) 浮点比较 | if (asint(x) != 0) |
| E7 | 整数指令造浮点位(and l(0x3f800000) 正反面、and l(0x7fffffff) 按位 |x|) | 整数结果按数值存 | asfloat(...) 存 |
| E8 | 32 位整数(光源位掩码、1 << n、LCG 哈希 imad) | 按数值存,> 2^24 丢位 | asfloat(...) 存,读的地方 asint / asuint |

不能自动处理(列「需要手工」,退出码 1):texture1d 以外漏声明的资源、缺对象名的非 Load 调用、非 texture2d 的 ld_aoffimmi、
同一个操作数各分量类型不一致、ubfe / bfi 模板里读位模式、形式看不懂的条件、与汇编对不上的段落里出现可疑整数转换、
除 X4000 / X4115 以外的编译错误。「提示」只是记录(例如条件判断的是真浮点 —— 位非零 ≡ 浮点非零,无害;
或各路径类型不一致但读法对了其中一路),不影响退出码,但要扫一眼。

⚠ 只修反编译器缺陷,不加任何效果。修完看报告末尾的编译回环表(SKILL.md 第 2 节第 4 步);
   位模式缺陷只有雨天 / 雪天 / 夜里靠近路灯才看得出 —— 静态全绿也要实机各看一次。
⚠ 默认假设「按数值存」的整数(N)都小于 2^24:由小整数移位(≤ 8 位)、加减得来的下标 / 计数都按 N 处理。
   真有大整数从这些路径过来,报告的「提示」里不会出现,只能靠实机 —— 这是本脚本已知的局限。
"""
from __future__ import annotations

# 输入是未经修改的反编译 HLSL，以及同一 bytecode 的 msasm 或内嵌汇编；两者都只读。
# 输出固定为 .fixed.hlsl；只有 --report 才另写逐处日志，--work-dir 才保留编译中间件。
# “对齐 P%”是汇编指令与 HLSL 语句的匹配率，低于 98% 会列入手工处理；它不是编译通过率。
# “自动修补 X N 行”按缺陷类型统计改动行数；“需要手工 N 处”必须为 0 才能继续。
# “严格编译:0 告警 N B”证明底子可编译；“编译回环 N 项与游戏不等”中的 N 必须为 0。
# 全部门通过退出 0；仍需手工或编译/回环失败退出 1；输入、参数或缺文件退出 2。

import argparse
import collections
import difflib
import glob
import hashlib
import os
import re
import subprocess
import sys
import tempfile

FXC_PATTERNS = [
    r'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\fxc.exe',
    r'C:\Program Files (x86)\Windows Kits\10\bin\x64\fxc.exe',
    r'C:\Program Files\Windows Kits\10\bin\*\x64\fxc.exe',
]
COMP = 'xyzw'
BITS = {'F', 'Rc', 'Rs', 'B'}          # 寄存器里存的就是游戏的原始位:整数指令必须 asint/asuint 读
NUMK = {'N', 'M', 'U', 'Z'}            # 寄存器里存的是整数的数值:(int)/(uint) 读是对的
KIND_NAME = {'F': '浮点', 'Rc': '常量缓冲原始位', 'Rs': '结构化缓冲原始位', 'B': '32 位位模式', 'N': '小整数',
             'M': '比较掩码', 'U': 'uint 输入', 'Z': '零', 'X': '各路径不一致', 'L': '字面量'}

CF_ASM = {'if_nz': 'IF', 'if_z': 'IF', 'else': 'ELSE', 'endif': 'END', 'loop': 'LOOP', 'endloop': 'END',
          'break': 'BRK', 'breakc_nz': 'BRK', 'breakc_z': 'BRK', 'continue': 'CONT', 'continuec_nz': 'CONT',
          'continuec_z': 'CONT', 'discard_nz': 'DISC', 'discard_z': 'DISC', 'ret': 'RET', 'retc_nz': 'RETC',
          'retc_z': 'RETC', 'switch': 'SW', 'case': 'CASE', 'default': 'CASE', 'endswitch': 'END'}
CF_WITH_COND = {'if_nz', 'if_z', 'breakc_nz', 'breakc_z', 'continuec_nz', 'continuec_z', 'discard_nz', 'discard_z',
                'retc_nz', 'retc_z'}
TWO_DEST = {'sincos', 'imul', 'umul', 'udiv', 'swapc', 'uaddc', 'usubb'}
INT_CONSUMERS = {'and', 'or', 'xor', 'not', 'ushr', 'ishr', 'ishl', 'ubfe', 'ibfe', 'bfi', 'bfrev', 'countbits',
                 'firstbit_hi', 'firstbit_lo', 'firstbit_shi', 'iadd', 'imad', 'imul', 'umul', 'umad', 'udiv', 'imin',
                 'imax', 'umin', 'umax', 'ineg', 'ieq', 'ine', 'ilt', 'ige', 'ult', 'uge', 'utof', 'itof', 'f16tof32',
                 'uaddc', 'usubb'}
STORE_BITS_OPS = {'and', 'or', 'xor', 'not', 'ishl', 'ishr', 'ushr', 'iadd', 'imad', 'imul', 'umul', 'umad', 'ineg',
                  'imin', 'imax', 'umin', 'umax', 'bfrev', 'bfi', 'ibfe', 'ubfe'}
MASK_OPS = {'eq', 'ne', 'lt', 'ge', 'ieq', 'ine', 'ilt', 'ige', 'ult', 'uge', 'deq', 'dne', 'dlt', 'dge'}
NUM_OPS = {'ftou', 'ftoi', 'udiv', 'firstbit_lo', 'firstbit_hi', 'firstbit_shi', 'countbits', 'f32tof16',
           'sampleinfo', 'bufinfo', 'resinfo_uint'}

# 编译回环对照:(名字, 指令正则, 是否应与游戏相等, 计数方式)
# 计数方式 c = 按目的分量(编译器会把两条标量指令合成一条向量指令,条数变、分量数不变);
#          i = 按条数(读贴图 / 缓冲的指令,编译器会删掉没用到的分量,分量数反而会变)
LOOP_KEYS = [
    ('if_nz / if_z 直接判 cb(E6c)', r'^if_n?z cb\d+\[', True, 'i'),
    ('按位取字段 ubfe + ushr(E6 / E8)', r'^(ubfe|ushr) ', True, 'c'),
    ('ubfe', r'^ubfe ', False, 'c'),
    ('ushr', r'^ushr ', False, 'c'),
    ('breakc_z / breakc_nz', r'^breakc_n?z ', False, 'i'),
    ('and … l(255)(E6)', r'^and .*\bl\(255\)', True, 'c'),
    ('and … l(0x3f800000)(E7 / 掩码惯用法)', r'^and .*l\(0x3f800000', True, 'c'),
    ('and … l(0x7fffffff)(E7)', r'^and .*l\(0x7fffffff', True, 'c'),
    ('ult … l(0x7f800000)(E7)', r'^ult .*l\(0x7f800000', True, 'c'),
    ('imad(E8 哈希)', r'^imad ', True, 'c'),
    ('xor(E8)', r'^xor ', True, 'c'),
    ('firstbit_lo(E8)', r'^firstbit_lo ', True, 'c'),
    ('ld_structured', r'^ld_structured', True, 'i'),
    ('ld_aoffimmi(E4)', r'^ld_aoffimmi', True, 'i'),
    ('ld texture1d(E3)', r'^ld\w*\(texture1d\)', True, 'i'),
    ('bfi', r'^bfi ', False, 'c'),
    ('ftou', r'^ftou ', False, 'c'), ('ftoi', r'^ftoi ', False, 'c'),
    ('utof', r'^utof ', False, 'c'), ('itof', r'^itof ', False, 'c'),
]


# Represent invalid or mismatched source evidence that must stop repair.
class InputError(Exception):
    pass


# ============================================================== 通用小工具

# Decode source text and return the encoding required for faithful output.
def read_text(path: str) -> tuple[str, str]:
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('gbk', errors='replace')
    nl = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n'), nl


# Hash source bytes so reports identify their exact input.
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# Resolve an explicit or installed fxc executable before the DLL fallback.
def find_fxc(given: str | None) -> str | None:
    if given:
        return given if os.path.isfile(given) else None
    for pat in FXC_PATTERNS:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


# Split assembly operands without breaking comma-separated literal vectors.
def split_ops(s: str) -> list[str]:
    out, dep, cur = [], 0, ''
    for ch in s:
        if ch in '([':
            dep += 1
        elif ch in ')]':
            dep -= 1
        if ch == ',' and dep == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# Separate an assembly opcode from its operand text after removing modifiers.
def split_head(t: str) -> tuple[str, str]:
    dep = 0
    for k, ch in enumerate(t):
        if ch == '(':
            dep += 1
        elif ch == ')':
            dep -= 1
        elif ch in ' \t' and dep == 0:
            return t[:k], t[k:].strip()
    return t, ''


# Preserve source indentation when replacing a decompiler statement.
def indent_of(s: str) -> str:
    return s[:len(s) - len(s.lstrip())]


# Remove line comments before matching HLSL semantics.
def code_part(s: str) -> str:
    return s.split('//', 1)[0]


# ============================================================== 汇编

# Store one parsed assembly instruction and its value-flow state.
class Ins:
    __slots__ = ('i', 'line', 'text', 'base', 'parens', 'dests', 'srcs', 'tok', 'dregs', 'srck', 'resk', 'st')


# Parse literal vector components as both raw bits and numeric values.
def parse_lit(inner: str) -> list[tuple[str, float]]:
    out = []
    for p in inner.split(','):
        p = p.strip()
        if re.fullmatch(r'-?0x[0-9a-fA-F]+', p):
            v = int(p.replace('-', ''), 16)
            out.append(('i', -v if p.startswith('-') else v))
        elif re.fullmatch(r'-?\d+', p):
            out.append(('i', int(p)))
        else:
            try:
                out.append(('f', float(p)))
            except ValueError:
                out.append(('f', 1.0))
    return out


# Parse one assembly operand into register, swizzle, modifiers, and literal metadata.
def parse_opnd(s: str) -> dict:
    s0 = s.strip()
    neg = s0.startswith('-')
    s1 = s0[1:] if neg else s0
    if s1.startswith('|') and s1.endswith('|'):
        s1 = s1[1:-1]
    m = re.match(r'^l\((.*)\)$', s1)
    if m:
        return {'kind': 'lit', 'lits': parse_lit(m.group(1)), 'text': s0}
    m = re.match(r'^(cb\d+)\[(.+)\]\.([xyzw]+)$', s1, re.I)
    if m:
        return {'kind': 'cb', 'swz': m.group(3), 'text': s0}
    m = re.match(r'^icb\[(.+)\]\.([xyzw]+)$', s1, re.I)
    if m:
        return {'kind': 'icb', 'swz': m.group(2), 'text': s0}
    m = re.match(r'^([rvo]\d+)(?:\.([xyzw]+))?$', s1)
    if m:
        return {'kind': 'reg', 'reg': m.group(1), 'swz': m.group(2) or 'xyzw', 'text': s0}
    m = re.match(r'^([tu]\d+)(?:\.[xyzw]+)?$', s1)
    if m:
        return {'kind': 'res', 'reg': m.group(1), 'text': s0}
    if re.match(r'^s\d+$', s1):
        return {'kind': 'samp', 'text': s0}
    if s1 == 'null':
        return {'kind': 'null', 'text': s0}
    return {'kind': 'other', 'text': s0}


# Convert Microsoft assembly text into instructions and resource declarations.
def parse_asm(lines: list[str], first_no: int = 1):
    """返回 (指令表, 资源声明 {tN: 类型}, 从汇编看出的 uint 输入)。遇到 */ 停(内嵌汇编块)。"""
    ins: list[Ins] = []
    dcl_res: dict[str, str] = {}
    uint_in: set[str] = set()
    in_icb = False
    for k, raw in enumerate(lines):
        no = first_no + k
        t = raw.strip()
        if '*/' in t:
            break
        if not t or t.startswith('//') or t.startswith('/*') or re.match(r'^[vp]s_\d_\d', t):
            continue
        if t.startswith('dcl_immediateConstantBuffer'):
            in_icb = not t.endswith('}')
            continue
        if in_icb:
            if t.endswith('}') and not t.endswith('},'):
                in_icb = False
            continue
        if t.startswith('{'):
            continue
        if t.startswith('dcl_'):
            m = re.match(r'^dcl_resource_(\w+)\s*(?:\(([^)]*)\))?\s*([tT]\d+)', t)
            if m:
                dcl_res[m.group(3).lower()] = m.group(1).lower()
            m = re.match(r'^dcl_input_ps_sgv\s+(v\d+)\.\w+,\s*(is_front_face|primitive_id|sampleIndex|coverage)', t)
            if m:
                uint_in.add(m.group(1))
            continue
        head, rest = split_head(t)
        name = re.sub(r'\([^()]*\)', '', head)
        x = Ins()
        x.i = len(ins)
        x.line = no
        x.text = t
        x.parens = re.findall(r'\(([^()]*)\)', head)
        x.base = name.replace('_indexable', '').replace('_sat', '')
        ops = [parse_opnd(o) for o in split_ops(rest)] if rest else []
        if x.base in CF_ASM:
            x.dests, x.srcs = [], ops
            x.tok = (CF_ASM[x.base], None)
            x.dregs = set()
        else:
            nd = 2 if x.base in TWO_DEST else (0 if x.base.startswith(('store', 'discard', 'emit', 'cut')) else 1)
            x.dests, x.srcs = ops[:nd], ops[nd:]
            regs = [d['reg'] for d in x.dests if d['kind'] == 'reg']
            x.dregs = set(regs)
            x.tok = ('W', regs[0] if regs else '?')
        x.srck, x.resk, x.st = [], {}, {}
        ins.append(x)
    return ins, dcl_res, uint_in


# ============================================================== HLSL

# Store one HLSL statement and the destination/control-flow features used for alignment.
class Stmt:
    __slots__ = ('li', 'tok', 'depth')


# Reduce one HLSL statement to a semantic token used in assembly alignment.
def hlsl_token(s: str):
    s = s.strip()
    if not s or s.startswith('//'):
        return None
    if re.match(r'^(float4 r\d|uint4 bitmask|float4 fDest|const float4 icb|\{\s*-?[\d.])', s) or s.endswith('} };'):
        return ('DECL', None)
    m = re.match(r'^if \(\d+ == 0\) (r\d+)\.[xyzw] = 0;', s)
    if m:
        return ('W', m.group(1))
    if s.startswith('bitmask.'):
        m = re.search(r';\s*(r\d+)\.[xyzw]+\s*=', s)
        return ('W', m.group(1)) if m else ('?', s)
    if s == 'while (true) {':
        return ('LOOP', None)
    if s == '} else {':
        return ('ELSE', None)
    if s == '}':
        return ('END', None)
    if re.match(r'^if \(.*\) break;$', s) or s == 'break;':
        return ('BRK', None)
    if re.match(r'^if \(.*\) continue;$', s) or s == 'continue;':
        return ('CONT', None)
    if re.match(r'^if \(.*\) discard;$', s) or s == 'discard;':
        return ('DISC', None)
    if s == 'return;':
        return ('RET', None)
    if re.match(r'^if \(.*\) return;$', s):
        return ('RETC', None)
    if re.match(r'^if \(.*\) \{$', s):
        return ('IF', None)
    if s.startswith('switch'):
        return ('SW', None)
    if re.match(r'^(case\b|default\s*:)', s):
        return ('CASE', None)
    m = re.match(r'^(r\d+|o\d+|oDepth)(?:\.[xyzw]+)?\s*=', s)
    if m:
        return ('W', m.group(1))
    if re.match(r'^t\d+\.GetDimensions', s):
        return ('HELPER', None)
    m = re.match(r'^sincos\([^,]+,\s*(r\d+)', s)
    if m:
        return ('W', m.group(1))
    return ('?', s)


# Locate the full main body and reject malformed decompiler output.
def find_main(lines: list[str]):
    try:
        st = next(k for k, l in enumerate(lines) if l.startswith('void main('))
    except StopIteration:
        raise InputError('找不到 `void main(`:输入不像 3DMigoto 反编译产物')
    k = st
    while k < len(lines) and lines[k].strip() != '{':
        k += 1
    if k >= len(lines):
        raise InputError('main 的签名后面找不到 `{`')
    b0 = k + 1
    for j in range(b0, len(lines)):
        if lines[j].rstrip() == '}':
            return st, b0, j
    raise InputError('找不到 main 的结束 `}`(顶格的一行 `}`)')


# Parse executable HLSL statements inside main while ignoring comments and declarations.
def parse_body(lines: list[str], b0: int, b1: int) -> list[Stmt]:
    out, d = [], 0
    for li in range(b0, b1):
        tok = hlsl_token(lines[li])
        if tok is None or tok[0] == 'DECL':
            continue
        s = Stmt()
        s.li, s.tok = li, tok
        if tok[0] in ('END',):
            d -= 1
        s.depth = d - 1 if tok[0] == 'ELSE' else d
        if tok[0] in ('IF', 'LOOP', 'SW'):
            d += 1
        out.append(s)
    return out


# ============================================================== 对齐

# Align assembly and HLSL with dynamic programming so fixes use the game's instruction as truth.
def align(ins: list[Ins], stmts: list[Stmt]):
    a = [x.tok for x in ins]
    h = [s.tok for s in stmts]
    sm = difflib.SequenceMatcher(None, a, h, autojunk=False)
    h2a: dict[int, int] = {}
    un_h, un_a = [], []

    # Score whether one HLSL statement plausibly represents one assembly instruction.
    def compat(j, i):
        if i < 0 or i >= len(a):
            return False
        return h[j] == a[i] or (h[j][0] == 'W' and h[j][1] in ins[i].dregs)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for d in range(i2 - i1):
                h2a[j1 + d] = i1 + d
        elif tag == 'insert':
            for j in range(j1, j2):
                if h[j][0] == 'HELPER':
                    h2a[j] = min(i1, len(a) - 1)
                elif compat(j, i1 - 1):
                    h2a[j] = i1 - 1
                elif compat(j, i1):
                    h2a[j] = i1
                else:
                    un_h.append(j)
        elif tag == 'delete':
            un_a.extend(range(i1, i2))
        else:
            if i2 - i1 == j2 - j1 and all(compat(j1 + d, i1 + d) for d in range(i2 - i1)):
                for d in range(i2 - i1):
                    h2a[j1 + d] = i1 + d
            else:
                un_a.extend(range(i1, i2))
                un_h.extend(range(j1, j2))
    matched = sum(1 for t, i1, i2, j1, j2 in sm.get_opcodes() if t == 'equal' for _ in range(i2 - i1))
    rate = matched / max(1, len(a))
    return h2a, un_h, un_a, rate


# ============================================================== 类型追踪

# Merge two value-kind labels while preserving mixed evidence.
def join(a: str, b: str) -> str:
    if a == b:
        return a
    if a == 'Z':
        return b
    if b == 'Z':
        return a
    if a in BITS and b in BITS:
        for k in ('B', 'Rs', 'Rc', 'F'):
            if k in (a, b):
                return k
    if a in NUMK and b in NUMK:
        return 'N'
    return 'X'


# Merge component-wise register states at a control-flow join.
def merge(s1: dict, s2: dict) -> dict:
    out = dict(s1)
    for k, v in s2.items():
        out[k] = join(out.get(k, 'Z'), v)
    for k in s1:
        if k not in s2:
            out[k] = join(s1[k], 'Z')
    return out


# Fold every incoming branch state into one conservative register state.
def merge_all(sts: list[dict]) -> dict:
    out = sts[0]
    for s in sts[1:]:
        out = merge(out, s)
    return out


# Classify a literal as a float, small integer, bit pattern, mask, or zero.
def lit_kind(l) -> str:
    t, v = l
    if v == 0:
        return 'Z'
    if t == 'f':
        return 'F'
    return 'N' if -(1 << 24) < v < (1 << 24) else 'B'


# Resolve the value kind read by one source component under the current state.
def src_for_comp(o: dict, c: str | None, dmask: str, st: dict, uint_in: set) -> tuple:
    k = o['kind']
    if k == 'lit':
        vals = o['lits']
        idx = COMP.index(c) if c else 0
        return ('L', vals[idx] if len(vals) == 4 else vals[0])
    if k == 'cb':
        return ('Rc', None)
    if k == 'icb':
        return ('N', None)
    if k == 'reg':
        swz = o['swz']
        if c is None:
            sc = swz[0]
        elif len(swz) == 4:
            sc = swz[COMP.index(c)]
        elif len(swz) == 1:
            sc = swz
        else:
            p = dmask.index(c) if c in dmask else 0
            sc = swz[min(p, len(swz) - 1)]
        reg = o['reg']
        if reg.startswith('v'):
            return ('U' if reg in uint_in else 'F', None)
        return (st.get((reg, sc), 'Z'), None)
    return ('F', None)


# Collapse a detailed source tuple to the effective kind consumed by an opcode.
def eff(s: tuple) -> str:
    return lit_kind(s[1]) if s[0] == 'L' else s[0]


# Infer the destination kind produced by an opcode from all source kinds.
def result_kind(b: str, srcs: list[tuple]) -> str:
    ks = [s[0] for s in srcs]
    lits = [s[1] for s in srcs if s[0] == 'L']
    if b in MASK_OPS:
        return 'M'
    if b in NUM_OPS:
        return 'N'
    if b in ('utof', 'itof', 'f16tof32'):
        return 'F'
    if b == 'mov':
        return eff(srcs[0]) if srcs else 'F'
    if b in ('movc', 'swapc'):
        return join(eff(srcs[1]), eff(srcs[2])) if len(srcs) >= 3 else 'F'
    if b in ('ld_structured', 'ld_raw'):
        return 'Rs'
    if b.startswith('resinfo'):
        return 'N' if b.endswith('_uint') else 'F'
    if b in ('and', 'or', 'xor'):
        if b in ('and', 'or') and 'M' in ks:
            others = [s for s in srcs if s[0] != 'M']
            if not others:
                return 'M'
            o = others[0]
            if b == 'and':
                if o[0] == 'L':
                    t, v = o[1]
                    if t == 'f' or abs(v) >= (1 << 24):
                        return 'F'          # 掩码 & 浮点位常量 = cond ? 1.0 : 0
                    return 'N'              # 掩码 & 小整数 = cond ? N : 0(E2 惯用法)
                return eff(o)               # 掩码 & x = 按位选择 x 或 0,类型跟 x
            return 'N' if eff(o) in NUMK else 'B'
        if lits:
            t, v = lits[0]
            if b == 'and' and t == 'i' and 0 <= v < (1 << 24):
                return 'N'
            return 'B'
        es = [eff(s) for s in srcs]
        if any(e in BITS for e in es):
            return 'B'
        if 'X' in es:
            return 'X'
        return 'N'
    if b == 'not':
        return 'M' if ks and ks[0] == 'M' else 'B'
    if b == 'ishl':
        a, sh = srcs[0], srcs[1]
        if eff(a) in BITS:
            return 'B'
        if sh[0] == 'L' and sh[1][1] <= 8 and a[0] != 'L':
            return 'N'
        if a[0] == 'L' and sh[0] == 'L':
            return lit_kind(('i', int(a[1][1]) << int(sh[1][1])))
        return 'B'
    if b in ('ushr', 'ishr'):
        a, sh = srcs[0], srcs[1]
        if eff(a) in NUMK:
            return 'N'
        if sh[0] == 'L' and sh[1][1] >= 8:
            return 'N'
        return 'B'
    if b in ('ubfe', 'ibfe'):
        w = srcs[0]
        return 'N' if w[0] == 'L' and w[1][1] <= 24 else 'B'
    if b == 'bfi':
        return 'N' if all(eff(s) in NUMK for s in srcs[2:]) else 'B'
    if b in ('iadd', 'imin', 'imax', 'umin', 'umax', 'ineg'):
        es = [eff(s) for s in srcs]
        return 'B' if 'B' in es else ('X' if 'X' in es else 'N')
    if b in ('imad', 'imul', 'umul', 'umad'):
        if any(l[0] == 'i' and abs(l[1]) >= (1 << 16) for l in lits):
            return 'B'
        es = [eff(s) for s in srcs]
        return 'B' if 'B' in es else ('X' if 'X' in es else 'N')
    if b in ('bfrev', 'uaddc', 'usubb'):
        return 'B'
    return 'F'


# Propagate value kinds through structured control flow and annotate every instruction.
def analyze(ins: list[Ins], uint_in: set):
    """结构化控制流上的前向类型追踪;loop 用上一轮的回边状态再跑,共 3 轮取稳定值。"""
    back: dict[int, dict] = {}
    for _ in range(3):
        st: dict = {}
        stack: list[dict] = []
        for x in ins:
            x.st = st
            t = x.tok[0]
            if x.base in CF_WITH_COND or x.base == 'switch':
                x.srck = [{None: src_for_comp(o, None, '', st, uint_in)} for o in x.srcs]
            if t == 'IF':
                stack.append({'t': 'if', 'pre': dict(st), 'then': None})
            elif t == 'ELSE':
                f = stack[-1]
                f['then'] = st
                st = dict(f['pre'])
            elif t == 'END':
                if not stack:
                    continue
                f = stack.pop()
                if f['t'] == 'if':
                    st = merge(f['then'], st) if f['then'] is not None else merge(f['pre'], st)
                elif f['t'] == 'loop':
                    back[f['start']] = merge_all([st] + f['conts'])
                    st = merge_all(f['breaks']) if f['breaks'] else st
                else:
                    st = merge_all(f['acc'] + [st])
            elif t == 'LOOP':
                st = merge(st, back[x.i]) if x.i in back else dict(st)
                stack.append({'t': 'loop', 'start': x.i, 'breaks': [], 'conts': []})
            elif t == 'BRK':
                for f in reversed(stack):
                    if f['t'] in ('loop', 'switch'):
                        if f['t'] == 'loop':
                            f['breaks'].append(dict(st))
                        break
            elif t == 'CONT':
                for f in reversed(stack):
                    if f['t'] == 'loop':
                        f['conts'].append(dict(st))
                        break
            elif t == 'SW':
                stack.append({'t': 'switch', 'pre': dict(st), 'acc': []})
            elif t == 'CASE':
                if stack and stack[-1]['t'] == 'switch':
                    stack[-1]['acc'].append(st)
                    st = dict(stack[-1]['pre'])
            elif t in ('DISC', 'RET', 'RETC'):
                pass
            else:
                new = dict(st)
                x.srck, x.resk = [], {}
                for d in x.dests:
                    if d['kind'] != 'reg':
                        continue
                    for c in d['swz']:
                        srcs = [src_for_comp(o, c, d['swz'], st, uint_in)
                                for o in x.srcs if o['kind'] not in ('res', 'samp', 'null')]
                        if x.base.startswith(('sample', 'gather', 'lod')) or \
                                (x.base.startswith('ld') and not x.base.startswith(('ld_structured', 'ld_raw'))):
                            k = 'F'                      # 贴图读数 = 浮点数据
                        else:
                            k = result_kind(x.base, srcs)
                        x.resk[(d['reg'], c)] = k
                        new[(d['reg'], c)] = k
                        x.srck.append({c: srcs})
                st = new


# ============================================================== 修补规则

CAST = re.compile(r'\((u?int)([234]?)\)\s*(?P<op>-?(?:[rv]\d+\.[xyzw]+|cb\d+\[[^\]]+\]\.[xyzw]+|icb\[[^\]]+\]\.[xyzw]+))')
UBFE_T = re.compile(r'^(?P<ind>\s*)if \((?P<w>\d+) == 0\) (?P<d>r\d+\.[xyzw]) = 0; else if \((?P=w)\+(?P<o>\d+) < 32\) \{.*\}'
                    r' else (?P=d) = \((?P<cast>u?int)\)(?P<src>.+?) >> (?P=o);\s*$')
BFI_T = re.compile(r'^(?P<ind>\s*)bitmask\.(?P<c>[xyzw]) = .*;\s*(?P<d>r\d+\.[xyzw]) = .*~bitmask\.(?P=c)\);\s*$')
COND_T = re.compile(r'^(?P<ind>\s*)if \((?P<x>.+?) (?P<cmp>[!=]=) 0\)(?P<rest>.*)$')
TERN_T = re.compile(r'^(?P<lhs>\s*(?:r\d+|o\d+)(?:\.[xyzw]+)?\s*=\s*)(?P<x>-?(?:r\d+\.[xyzw]+|cb\d+\[[^\]]+\]\.[xyzw]+))\s*\?(?P<rest>.*)$')
ASSIGN_T = re.compile(r'^(?P<lhs>\s*(?:r\d+|o\d+)(?:\.[xyzw]+)?\s*=\s*)(?P<rhs>.*?);(?P<tail>\s*(?://.*)?)$')
STRUCT_IDX = re.compile(r'\b(t\d+)\[(?P<idx>(?:[^\[\]]|\[[^\]]*\])+)\]\.val')


# Apply only repairs proven by aligned assembly and collect unresolved evidence separately.
class Fixer:
    # Keep mutable HLSL lines plus all alignment and declaration evidence used by repairs.
    def __init__(self, lines, ins, stmts, h2a, dcl_res, uint_in):
        self.lines = lines
        self.ins = ins
        self.stmts = stmts
        self.h2a = h2a
        self.dcl_res = dcl_res
        self.uint_in = uint_in
        self.patched: dict[int, dict] = {}     # li -> {'new': 文本, 'cls': [..], 'asm': [..], 'notes': [..]}
        self.manual: list[tuple] = []          # (li, 类, 说明)
        self.hints: list[tuple] = []           # (li, 类, 说明)
        self.ok_counts = collections.Counter()
        self.decl_add: list[str] = []

    # ---- 记录
    # Return comment-free current code for one source line.
    def cur(self, li):
        return self.patched[li]['new'] if li in self.patched else self.lines[li]

    # Replace one source line and record the exact assembly-backed repair.
    def put(self, li, new, cls, x: Ins | None, note):
        if new == self.cur(li):
            return
        p = self.patched.setdefault(li, {'new': self.lines[li], 'cls': [], 'asm': [], 'notes': []})
        p['new'] = new
        if cls not in p['cls']:
            p['cls'].append(cls)
        if x is not None and (x.line, x.text) not in p['asm']:
            p['asm'].append((x.line, x.text))
        p['notes'].append(note)

    # Record a blocking case where evidence is sufficient to flag but not rewrite safely.
    def need_manual(self, li, cls, msg):
        self.manual.append((li, cls, msg))

    # Record non-blocking evidence that a human should inspect.
    def hint(self, li, cls, msg):
        self.hints.append((li, cls, msg))

    # ---- 操作数类型(按 HLSL 文本查指令执行前的状态)
    # Infer value kinds mentioned in an HLSL expression using current register state.
    def text_kinds(self, t: str, st: dict):
        t = t.strip().lstrip('-')
        if re.match(r'^cb\d+\[', t):
            return ['Rc']
        if t.startswith('icb['):
            return ['N']
        m = re.match(r'^(r\d+|v\d+)\.([xyzw]+)$', t)
        if m:
            reg, comps = m.group(1), m.group(2)
            if reg.startswith('v'):
                return ['U' if reg in self.uint_in else 'F'] * len(comps)
            return [st.get((reg, c), 'Z') for c in comps]
        return None

    # ---- 主流程
    # Visit aligned statements in source order and then repair declarations.
    def run(self):
        for j, s in enumerate(self.stmts):
            li = s.li
            code = code_part(self.lines[li])
            if j not in self.h2a:
                if re.search(r'\(u?int[234]?\)\s*(cb\d+\[|r\d+\.)', code) or \
                        re.search(r'0x(3f800000|7fffffff|80000000|7f800000)', code) or '= .' in code:
                    self.need_manual(li, '对齐', '这一行没能与汇编对上,又含整数转换 / 位技巧常数 / 缺对象名 —— 请对照 msasm 手工核对')
                continue
            x = self.ins[self.h2a[j]]
            self.fix_stmt(li, x)
        self.fix_decls()

    # Dispatch one aligned statement to the repair matching its assembly opcode.
    def fix_stmt(self, li: int, x: Ins):
        b = x.base
        st = x.st
        text = self.cur(li)
        # ---- E3 缺对象名的 Load(Texture1D)
        if re.search(r'=\s*\.\w+\(', code_part(text)):
            res = next((o['reg'] for o in x.srcs if o['kind'] == 'res'), None)
            m = re.search(r'=\s*\.Load\(float4\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,[^)]*\)\)', text)
            if b.startswith('ld') and res and self.dcl_res.get(res) == 'texture1d' and m:
                new = text[:m.start()] + '= ' + f'{res}.Load(int2({m.group(1)},{m.group(2)}))' + text[m.end():]
                self.put(li, new, 'E3', x, f'反编译器不认 texture1d:补对象名 {res},地址 (x, mip) = ({m.group(1)}, {m.group(2)})')
                if res not in self.decl_add:
                    self.decl_add.append(res)
                text = self.cur(li)
            else:
                self.need_manual(li, 'E3', f'缺对象名的调用,但不是「texture1d + 字面量地址」这种认得的形式(汇编:{x.text[:80]})')
        # ---- E4 带立即偏移的 ld
        if 'aoffimmi' in b:
            m = re.search(r'(t\d+)\.Load\(\s*(?P<a>[rv]\d+\.[xyzw]{2})\s*,\s*int3\(\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+\s*\)\s*\)', text)
            res = next((o['reg'] for o in x.srcs if o['kind'] == 'res'), None)
            offs = re.match(r'^\s*(-?\d+)\s*,\s*(-?\d+)', x.parens[0]) if x.parens else None
            if m and res and self.dcl_res.get(res) == 'texture2d' and offs:
                a = m.group('a')
                mip = self.mip_of(li, a.split('.')[0])
                new = text[:m.start()] + f'{m.group(1)}.Load(int3({a}, {mip}), int2({offs.group(1)}, {offs.group(2)}))' + text[m.end():]
                self.put(li, new, 'E4', x, f'ld_aoffimmi({x.parens[0]}):坐标补成 int3(xy, mip),偏移 ({offs.group(1)}, {offs.group(2)}) 照汇编')
                text = self.cur(li)
            elif not re.search(r'\.Load\(int3\(', text):
                self.need_manual(li, 'E4', f'ld_aoffimmi 但 HLSL 形式或资源类型不认得(汇编:{x.text[:90]})')
        # ---- 条件 / movc 条件(E6c)
        if x.base in CF_WITH_COND:
            self.fix_cond(li, x)
            return
        if x.tok[0] != 'W':
            return
        # ---- E2 掩码 & 小整数
        if b == 'and':
            self.fix_e2(li, x)
            text = self.cur(li)
        if b == 'movc':
            self.fix_movc_cond(li, x)
            text = self.cur(li)
        # ---- ubfe / ibfe 模板
        mu = UBFE_T.match(code_part(text))
        if mu:
            self.fix_ubfe(li, x, mu)
            return
        # ---- 整数指令读操作数(E1 / E6)+ 结构化缓冲下标
        if b in INT_CONSUMERS or b.startswith('ld'):
            self.fix_casts(li, x)
        if b.startswith('ld_structured') or b.startswith('ld_raw'):
            self.fix_struct_index(li, x)
        # ---- 结果是 32 位位模式 → asfloat 存(E7 / E8)
        if b in STORE_BITS_OPS:
            self.fix_store(li, x)

    # Find the mip expression associated with a sampled register near the target statement.
    def mip_of(self, li: int, reg: str) -> str:
        for k in range(li - 1, max(0, li - 12), -1):
            m = re.match(r'^\s*' + reg + r'\.([xyzw]+)\s*=\s*(.*);', self.lines[k])
            if m and 'z' in m.group(1):
                rhs = m.group(2).strip()
                if re.fullmatch(r'(float\d\()?\s*0(\.0+)?\s*(,\s*0(\.0+)?\s*)*\)?', rhs):
                    return '0'
                break
        return f'{reg}.z'

    # Restore sample-level semantics that the decompiler flattened incorrectly.
    def fix_e2(self, li, x: Ins):
        text = self.cur(li)
        if not re.search(r'\?\s*0\.000000\s*:\s*0\s*;', text):
            return
        lits = set()
        for comp_srcs in x.srck:
            for srcs in comp_srcs.values():
                ks = [s[0] for s in srcs]
                if 'M' in ks:
                    for s in srcs:
                        if s[0] == 'L' and s[1][0] == 'i' and s[1][1] != 0:
                            lits.add(s[1][1])
        if len(lits) != 1 or len(x.resk) != 1:
            self.need_manual(li, 'E2', f'退化三元 `? 0.000000 : 0`,但汇编常量不止一个或是多分量(汇编:{x.text[:90]})')
            return
        v = lits.pop()
        new = re.sub(r'\?\s*0\.000000\s*:\s*0\s*;', f'? {v} : 0;', text, count=1)
        self.put(li, new, 'E2', x, f'`and <比较掩码>, l({v})` 真值是 {v},反编译把常量丢成 0')

    # Preserve raw-bit truth semantics for conditional assembly instructions.
    def fix_cond(self, li, x: Ins):
        text = self.cur(li)
        k = x.srck[0][None][0] if x.srck else 'F'
        if k in NUMK or k == 'L':          # 小整数 / 掩码 / 字面量条件:数值判零与按位判零一致
            return
        m = COND_T.match(code_part(text))
        if k == 'F':
            self.ok_counts['E6c 判真浮点(无害)'] += 1
            return
        if k == 'X':
            self.hint(li, 'E6c', f'条件寄存器各路径类型不一致(汇编:{x.text[:80]}),请人工确认')
            return
        if not m:
            self.need_manual(li, 'E6c', f'条件判原始位({KIND_NAME[k]}),但 HLSL 条件形式不认得(汇编:{x.text[:80]})')
            return
        xs = m.group('x').strip()
        if xs.startswith(('asint(', 'asuint(')):
            self.ok_counts['E6c 已按位判'] += 1
            return
        if self.text_kinds(xs, x.st) is None:
            self.need_manual(li, 'E6c', f'条件判原始位,但条件不是单个操作数:{xs}')
            return
        tail = text[len(code_part(text)):]
        new = f"{m.group('ind')}if (asint({xs}) {m.group('cmp')} 0){m.group('rest')}{tail}"
        self.put(li, new, 'E6c', x, f'条件直接判{KIND_NAME[k]}:按位判零,不做浮点比较')

    # Repair movc masks so the selected component follows assembly bit tests.
    def fix_movc_cond(self, li, x: Ins):
        if not x.srcs:
            return
        k0 = set()
        for comp_srcs in x.srck:
            for srcs in comp_srcs.values():
                k0.add(eff(srcs[0]) if srcs else 'F')
        bad = k0 & {'Rc', 'Rs', 'B'}
        if not bad:
            if 'X' in k0:
                self.hint(li, 'E6c', f'movc 条件各路径类型不一致(汇编:{x.text[:80]})')
            return
        text = self.cur(li)
        m = TERN_T.match(text)
        if not m:
            self.need_manual(li, 'E6c', f'movc 条件是{"/".join(KIND_NAME[b] for b in bad)},但 HLSL 不是 `x ? a : b` 形式')
            return
        if len(k0) != 1:
            self.need_manual(li, 'E6c', 'movc 条件各分量类型不一致')
            return
        new = m.group('lhs') + f"asint({m.group('x')}) ?" + m.group('rest')
        self.put(li, new, 'E6c', x, 'movc 条件直接判原始位:按位判零')

    # Restore unsigned bitfield extraction with explicit bit reinterpretation.
    def fix_ubfe(self, li, x: Ins, mu):
        src = mu.group('src').strip()
        kinds = self.text_kinds(src, x.st)
        if kinds is None:
            self.need_manual(li, 'E6', f'ubfe 模板的源看不懂:{src}')
            return
        if all(k in NUMK for k in kinds):
            self.ok_counts['E6 ubfe 读小整数(正确)'] += 1
            return
        if not all(k in BITS for k in kinds):
            self.need_manual(li, 'E6', f'ubfe 模板的源各路径类型不一致:{src}')
            return
        w, o, d = int(mu.group('w')), int(mu.group('o')), mu.group('d')
        text = self.cur(li)
        tail = text[len(code_part(text)):].rstrip()
        if mu.group('cast') == 'uint':
            body = f'{d} = (asuint({src}) >> {o}) & {(1 << w) - 1};' if w + o < 32 else f'{d} = asuint({src}) >> {o};'
        else:
            body = f'{d} = (asint({src}) << {32 - w - o}) >> {32 - w};' if w + o < 32 else f'{d} = asint({src}) >> {o};'
        new = mu.group('ind') + body + ((' ' + tail) if tail else '')
        self.put(li, new, 'E6', x, f'{"ubfe" if mu.group("cast") == "uint" else "ibfe"} 读{KIND_NAME[kinds[0]]}:'
                                   f'反编译模板先 (uint) 数值转换、中间量还按 float 存(>2^24 丢位),整行改成按位取')

    # Insert asuint, asint, or asfloat only where value-flow proves bit reinterpretation.
    def fix_casts(self, li, x: Ins):
        text = self.cur(li)
        code = code_part(text)
        out, pos, changed = [], 0, []
        is_bfi = bool(BFI_T.match(code))
        for m in CAST.finditer(code):
            op = m.group('op')
            kinds = self.text_kinds(op, x.st)
            if kinds is None or all(k in ('N', 'U', 'Z') for k in kinds):
                continue
            if all(k in ('M', 'Z') for k in kinds):
                if m.group(1) == 'uint':
                    if op.startswith('-'):
                        self.need_manual(li, 'E1', f'(uint)-<比较掩码>:{op}')
                        continue
                    rep = f'({op} != 0 ? 0xffffffffu : 0u)'
                    out.append(code[pos:m.start()] + rep)
                    pos = m.end()
                    changed.append(('E1', f'(uint){op} 读比较掩码(反编译的真值是 -1.0,(uint)(-1.0) 非法 / 未定义):按掩码取全 1'))
                continue
            if all(k in BITS for k in kinds):
                if is_bfi:
                    self.need_manual(li, 'E6', f'bfi 模板里读{KIND_NAME[kinds[0]]}:{op}(没做自动改写)')
                    continue
                if op.startswith('-'):
                    self.need_manual(li, 'E6', f'带负号的整数转换读{KIND_NAME[kinds[0]]}:{op}')
                    continue
                fn = 'asuint' if m.group(1) == 'uint' else 'asint'
                out.append(code[pos:m.start()] + f'{fn}({op})')
                pos = m.end()
                changed.append(('E6', f'({m.group(1)}{m.group(2)}){op} 读{KIND_NAME[kinds[0]]}:数值转换改按位读 {fn}()'))
                continue
            if 'X' in kinds:
                self.hint(li, 'E6', f'{op} 各路径类型不一致({"/".join(KIND_NAME[k] for k in kinds)}),保留反编译写法,请人工确认')
            else:
                self.need_manual(li, 'E6', f'{op} 各分量类型不一致:{"/".join(KIND_NAME[k] for k in kinds)}')
        if not changed:
            if x.base in INT_CONSUMERS and re.search(r'\bas(u?int)\((cb\d+\[|r\d+\.)', code):
                self.ok_counts['E6 已按位读(asint/asuint)'] += 1
            return
        out.append(code[pos:])
        new = ''.join(out) + text[len(code):]
        for cls, note in changed:
            self.put(li, new, cls, x, note)

    # Repair structured-buffer indexes whose decompiled numeric cast changes raw bits.
    def fix_struct_index(self, li, x: Ins):
        text = self.cur(li)
        code = code_part(text)
        m = STRUCT_IDX.search(code)
        if not m:
            return
        idx = m.group('idx').strip()
        if idx.startswith(('asuint(', 'asint(')):
            self.ok_counts['E6 结构化缓冲下标已按位'] += 1
            return
        kinds = self.text_kinds(idx, x.st)
        if kinds is None or all(k in NUMK for k in kinds):
            return
        if all(k in BITS for k in kinds):
            new = code[:m.start('idx')] + f'asuint({idx})' + code[m.end('idx'):] + text[len(code):]
            self.put(li, new, 'E6', x, f'结构化缓冲下标是{KIND_NAME[kinds[0]]}:float 下标会隐式数值转换(≈0,读错元素),改 asuint')
        else:
            self.need_manual(li, 'E6', f'结构化缓冲下标类型不一致:{idx}')

    # Preserve raw destination bits when integer assembly feeds later float operations.
    def fix_store(self, li, x: Ins):
        ks = set(x.resk.values())
        if 'B' not in ks:
            return
        text = self.cur(li)
        code = code_part(text)
        if BFI_T.match(code) or UBFE_T.match(code):
            self.need_manual(li, 'E8', f'bfi / ubfe 模板的结果是 32 位位模式(汇编:{x.text[:80]}),没做自动改写')
            return
        if ks != {'B'}:
            self.need_manual(li, 'E8', f'结果各分量类型不一致:{sorted(ks)}(汇编:{x.text[:80]})')
            return
        m = ASSIGN_T.match(text)
        if not m:
            self.need_manual(li, 'E8', f'结果是 32 位位模式,但这一行不是单条赋值(汇编:{x.text[:80]})')
            return
        rhs = m.group('rhs').strip()
        if rhs.startswith('asfloat(') or re.search(r'\?', rhs):
            if rhs.startswith('asfloat('):
                self.ok_counts['E7/E8 已按位存(asfloat)'] += 1
            return
        lit = [o for o in x.srcs if o['kind'] == 'lit' and any(t == 'i' and abs(v) >= 0x00800000 for t, v in o['lits'])]
        cls = 'E7' if x.base in ('and', 'or', 'xor') and lit else 'E8'
        new = m.group('lhs') + f'asfloat({rhs});' + m.group('tail')
        what = {'E7': '整数指令造的是浮点位模式', 'E8': '结果是 32 位整数(位掩码 / 移位 / 哈希)'}[cls]
        self.put(li, new, cls, x, f'{what}:反编译按数值存(> 2^24 丢位 / 浮点位变成大数),改 asfloat 按位存')

    # Initialize only declarations proven to trigger strict-compile uninitialized warnings.
    def fix_decls(self):
        """E3:汇编里声明了、HLSL 里没有的资源。texture1d 补声明;别的类型列需要手工。"""
        head = '\n'.join(self.lines)
        for t, typ in sorted(self.dcl_res.items(), key=lambda kv: int(kv[0][1:])):
            if re.search(r'register\(\s*' + t + r'\s*\)', head, re.I):
                continue
            if typ == 'texture1d':
                if t not in self.decl_add:
                    self.decl_add.append(t)
            else:
                self.need_manual(None, 'E3', f'汇编声明了 {t}({typ}),HLSL 里没有对应声明,本脚本只会补 texture1d')


# ============================================================== 编译

ERR = re.compile(r'\((\d+),(\d+)(?:-(\d+))?\):\s*(error|warning)\s+(X\d+):\s*(.*)$')


# Import the bundled compiler wrapper without requiring package installation.
def load_d3dc():
    """同目录的 d3dc.py(系统 d3dcompiler_47.dll 的 ctypes 封装),没有 fxc 时用;缺文件 / 用不了返回 None。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # 别在 skill 目录里留 __pycache__
    try:
        import d3dc
        d3dc.load()
        return d3dc
    except Exception:
        return None
    finally:
        sys.dont_write_bytecode = old


# Select fxc when available and otherwise use the system D3D compiler wrapper.
def pick_compiler(fxc_arg: str | None):
    """返回 (编译器, 说明):编译器 = fxc.exe 路径 或 d3dc 模块;都没有 → (None, 原因)。"""
    fxc = find_fxc(fxc_arg)
    if fxc:
        return fxc, f'fxc {fxc}'
    d = load_d3dc()
    if d is not None:
        return d, '没找到 fxc,改用系统 d3dcompiler_47.dll(同目录 d3dc.py;bin 可能与 fxc 差几个字节,各项检查不受影响)'
    return None, '没找到 fxc.exe(Windows SDK),同目录也没有能用的 d3dc.py'


# Strictly compile generated source and optionally retain its assembly listing.
def fxc_compile(comp, src_text: str, work: str, tag: str, listing: bool):
    """严格编译(/T ps_5_0 /E main /Ges /WX /O3)。comp = fxc 路径或 d3dc 模块。返回 (通过?, [错误], 原话)。"""
    src = os.path.join(work, f'{tag}.hlsl')
    with open(src, 'w', encoding='utf-8', newline='\n') as f:
        f.write(src_text)
    binp, asmp = os.path.join(work, f'{tag}.bin'), os.path.join(work, f'{tag}.asm')
    if isinstance(comp, str):
        cmd = [comp, '/nologo', '/T', 'ps_5_0', '/E', 'main', '/Ges', '/WX', '/O3', '/Fo', binp]
        if listing:
            cmd += ['/Fc', asmp]
        cmd.append(src)
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
        ok, out = r.returncode == 0, r.stdout + r.stderr
    else:
        res = comp.compile_file(src, out_bin=binp, out_asm=asmp if listing else None)
        ok, out = bool(res.ok), res.messages or ''
    errs = []
    for l in out.splitlines():
        m = ERR.search(l)
        if m:
            errs.append((int(m.group(1)), int(m.group(2)), int(m.group(3) or m.group(2)), m.group(5), m.group(6).strip()))
    return ok, errs, out.strip()


# Count fidelity-sensitive assembly operations by destination components or instructions.
def asm_metrics(path_or_lines):
    """按「分量」计数(`and r0.xy, …` 算 2):编译器把两条标量指令合成一条向量指令时条数会变,分量数不变。"""
    lines = path_or_lines if isinstance(path_or_lines, list) else open(path_or_lines, encoding='utf-8', errors='replace').read().split('\n')
    ins, _, _ = parse_asm(lines)
    rows = [(re.sub(r'\s+', ' ', x.text.lower()), x) for x in ins]
    out = collections.OrderedDict()
    out['指令总数'] = len(rows)
    for name, pat, _, mode in LOOP_KEYS:
        n = 0
        for t, x in rows:
            if re.match(pat, t):
                d = x.dests[0] if x.dests and x.dests[0]['kind'] == 'reg' else None
                n += len(d['swz']) if (d and mode == 'c') else 1
        out[name] = n
    return out


# ============================================================== 主流程

# Parse the repair request and preserve a separate exit code for invalid input.
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='把 cmd_Decompiler 反编译的材质 PS 按游戏字节码(msasm)忠实修补:E1–E8,每处记日志。',
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split('\n\n', 2)[2] if __doc__ else None)
    ap.add_argument('hlsl', help='cmd_Decompiler -D 出的 .hlsl 原件(或 hunting 导出的 _replace.txt)')
    ap.add_argument('--msasm', help='同一 bin 的 --disassemble-ms 输出;输入是带内嵌汇编的 _replace.txt 时可省')
    ap.add_argument('--out-dir', help='输出目录,默认 = 输入所在目录')
    ap.add_argument('--report', action='store_true', help='另存一份逐处修补日志 <X>.fixed.report.txt(默认不写文件,屏幕摘要够用)')
    ap.add_argument('--fxc', help='fxc.exe 路径,默认按 Windows SDK 标准位置找')
    ap.add_argument('--no-compile', action='store_true', help='不做严格编译与编译回环(不推荐;E1 / E5 只能靠编译发现)')
    ap.add_argument('--work-dir', help='保留编译产物(fixed.hlsl / .bin / .asm 反汇编)的目录,方便与 msasm 逐条对照;默认用完即删')
    a = ap.parse_args()
    try:
        return run(a)
    except InputError as e:
        print(f'输入错误:{e}')
        return 2


# Execute alignment, repair, strict compilation, round-trip comparison, and reporting.
def run(a) -> int:
    if not os.path.isfile(a.hlsl):
        raise InputError(f'找不到 {a.hlsl}')
    text, nl = read_text(a.hlsl)
    raw_bytes = open(a.hlsl, 'rb').read()
    if re.search(r'\[fix-E\d|\[fidelity-fix', text):
        raise InputError('输入里已有修补标记([fix-E… / [fidelity-fix):要的是一字未改的反编译原件')
    lines = text.split('\n')
    # 汇编来源
    embedded_at = next((k for k, l in enumerate(lines) if l.startswith('/*~~~~')), None)
    if a.msasm:
        if not os.path.isfile(a.msasm):
            raise InputError(f'找不到 {a.msasm}')
        atext, _ = read_text(a.msasm)
        alines, afirst, asrc = atext.split('\n'), 1, a.msasm
    elif embedded_at is not None:
        alines, afirst, asrc = lines[embedded_at + 1:], embedded_at + 2, a.hlsl + '(末尾内嵌汇编)'
    else:
        raise InputError('没给 --msasm,输入里也没有内嵌汇编:请用 cmd_Decompiler --disassemble-ms 出一份 .msasm')
    ins, dcl_res, uint_asm = parse_asm(alines, afirst)
    if len(ins) < 20:
        raise InputError(f'汇编里只解析出 {len(ins)} 条指令:确认 --msasm 给的是 --disassemble-ms 的输出')
    sig_start, b0, b1 = find_main(lines)
    sig = '\n'.join(lines[sig_start:b0])
    uint_in = set(re.findall(r'\b(?:nointerpolation\s+)?u?int[1-4]?\s+(v\d+)\s*:', sig)) | uint_asm
    stmts = parse_body(lines, b0, b1)
    unknown = [s for s in stmts if s.tok[0] == '?']
    h2a, un_h, un_a, rate = align(ins, stmts)
    analyze(ins, uint_in)

    fx = Fixer(lines, ins, stmts, h2a, dcl_res, uint_in)
    if rate < 0.98:
        fx.need_manual(None, '对齐', f'汇编与 HLSL 只对上 {rate:.1%}(< 98%):确认两份出自同一个 bin;不往下自动修')
    else:
        fx.run()
    for s in unknown:
        fx.hint(s.li, '解析', f'不认得的 HLSL 语句形式:{lines[s.li].strip()[:80]}')

    # ---- 组装输出
    stem = os.path.basename(a.hlsl)
    for ext in ('.hlsl', '.txt'):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
    out_dir = a.out_dir or os.path.dirname(os.path.abspath(a.hlsl))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, stem + '.fixed.hlsl')
    rep_path = os.path.join(out_dir, stem + '.fixed.report.txt')

    body_end = b1 + 1            # 保留到 main 的 `}`;_replace.txt 的注释汇编不带
    decl_at = next((k for k in range(0, sig_start) if re.match(
        r'^(Texture|RWTexture|Buffer|StructuredBuffer|ByteAddressBuffer|struct\s|SamplerState|SamplerComparisonState|cbuffer)', lines[k])), sig_start)
    bitmask_at = next((k for k in range(b0, b1) if lines[k].strip() == 'uint4 bitmask, uiDest;'), None)
    if bitmask_at is None:
        bitmask_at = next((k for k in range(b0, b1) if re.match(r'^\s*float4 r0\b', lines[k])), b0 - 1)

    # Rebuild source with the selected initializers while preserving every unrelated line.
    def assemble(init_regs):
        out, where = [], {}
        for k in range(body_end):
            if k == decl_at and fx.decl_add:
                for t in fx.decl_add:
                    out.append(f'// [fix-E3] cmd_Decompiler 不认 dcl_resource_texture1d,漏了这行声明(依据:汇编 dcl_resource_texture1d {t})')
                    out.append(f'Texture1D<float4> {t} : register({t});')
            where[k] = len(out)
            if k in fx.patched:
                p = fx.patched[k]
                tag = f'   // [fix-{"/".join(p["cls"])}]' + (f' 汇编第 {p["asm"][0][0]} 行 `{p["asm"][0][1][:60]}`' if p['asm'] else '')
                out.append(p['new'].rstrip() + tag)
            else:
                out.append(lines[k])
            if k == bitmask_at and init_regs:
                out.append('  ' + ' '.join(f'{r} = 0;' for r in init_regs) +
                           '   // [fix-E5] fxc X4000「可能未初始化」:这些寄存器只在条件块里赋值;显式 0 初值只消保守告警,可达路径行为不变')
        return out, where

    comp, comp_desc = (None, '按 --no-compile 跳过') if a.no_compile else pick_compiler(a.fxc)
    init_regs: list[str] = []
    compile_log = []
    ok = None
    loop_rows = None
    bin_info = ''
    if a.work_dir:
        os.makedirs(a.work_dir, exist_ok=True)
        work_ctx, work = None, a.work_dir
    else:
        work_ctx = tempfile.TemporaryDirectory(prefix='fixdd_')
        work = work_ctx.name
    try:
        if comp and not fx.manual:
            for rnd in range(1, 6):
                out_lines, where = assemble(init_regs)
                back = {v: k for k, v in where.items()}
                ok, errs, raw_log = fxc_compile(comp, '\n'.join(out_lines) + '\n', work, 'fixed', listing=True)
                compile_log.append(f'第 {rnd} 轮编译:{"通过" if ok else "失败"}' + ('' if ok else f'({len(errs)} 条错误)'))
                if ok:
                    break
                progress = False
                other = []
                for ln, c1, c2, code, msg in errs:
                    if code == 'X3129':
                        continue
                    k = back.get(ln - 1)
                    if code == 'X4000':
                        m = re.search(r'\((r\d+)\)', msg)
                        if m and m.group(1) not in init_regs:
                            init_regs.append(m.group(1))
                            progress = True
                        continue
                    if code == 'X4115' and k is not None:
                        t = fx.cur(k)
                        seg = t[max(0, c1 - 1):c2 + 12]
                        mm = re.search(r'\(uint[234]?\)\s*(-?r\d+\.[xyzw]+)', t[max(0, c1 - 12):c2 + 12])
                        if mm:
                            op = mm.group(1)
                            new = t.replace(mm.group(0), f'({op} != 0 ? 0xffffffffu : 0u)', 1)
                            x = ins[h2a[[j for j, s in enumerate(stmts) if s.li == k][0]]] if any(s.li == k for s in stmts) else None
                            fx.put(k, new, 'E1', x, f'fxc X4115:(uint){op} 的 {op} 是 cmp 结果(-1.0),按掩码取全 1')
                            progress = True
                            continue
                        other.append(f'第 {k + 1} 行 {code}: {msg}  [{seg.strip()[:60]}]')
                        continue
                    other.append(f'输出第 {ln} 行 {code}: {msg}' + (f'(反编译第 {k + 1} 行)' if k is not None else ''))
                if other:
                    for o in dict.fromkeys(other):
                        fx.need_manual(None, '编译', o)
                    break
                if not progress:
                    fx.need_manual(None, '编译', '严格编译失败,且没有可自动处理的 X4000 / X4115:' + raw_log.splitlines()[0][:160])
                    break
            if ok:
                binp = os.path.join(work, 'fixed.bin')
                bin_info = f'{os.path.getsize(binp)} B, sha256 {sha256_bytes(open(binp, "rb").read())}'
                game = asm_metrics(alines)
                ours = asm_metrics(os.path.join(work, 'fixed.asm'))
                loop_rows = [(k, game[k], ours[k], next((e for n, _, e, _m in LOOP_KEYS if n == k), False)) for k in game]
        out_lines, where = assemble(init_regs)
    finally:
        if work_ctx is not None:
            work_ctx.cleanup()

    data = (nl.join(out_lines) + nl).encode('utf-8', errors='surrogateescape')
    with open(out_path, 'wb') as f:
        f.write(data)

    # ---- 报告
    R = []
    R.append('fix_decompiler_defects.py 报告')
    R.append(f'输入 HLSL : {os.path.abspath(a.hlsl)}  (sha256 {sha256_bytes(raw_bytes)})')
    R.append(f'汇编真值 : {asrc}')
    R.append(f'输出     : {out_path}  (sha256 {sha256_bytes(data)})')
    R.append(f'对齐     : 汇编 {len(ins)} 条 / HLSL {len(stmts)} 句,对上 {rate:.2%};未对上的 HLSL {len(un_h)} 句、汇编 {len(un_a)} 条')
    R.append('')
    cls_count = collections.Counter(c for p in fx.patched.values() for c in p['cls'])
    R.append('== 自动修补:' + (', '.join(f'{c} {n} 行' for c, n in sorted(cls_count.items())) or '无') +
             (f';E5 显式 0 初值 {", ".join(init_regs)}' if init_regs else '') +
             (f';E3 补声明 {", ".join(fx.decl_add)}' if fx.decl_add else ''))
    for k in sorted(fx.patched):
        p = fx.patched[k]
        R.append(f'[{"/".join(p["cls"])}] 反编译第 {k + 1} 行 → 输出第 {where[k] + 1} 行' +
                 ''.join(f';汇编第 {ln} 行 `{t[:70]}`' for ln, t in p['asm'][:2]))
        R.append(f'    改前: {lines[k].strip()[:200]}')
        R.append(f'    改后: {p["new"].strip()[:200]}')
        for n in dict.fromkeys(p['notes']):
            R.append(f'    说明: {n}')
    R.append('')
    R.append(f'== 需要手工:{len(fx.manual)} 处')
    for li, cls, msg in fx.manual:
        R.append(f'[{cls}] ' + (f'反编译第 {li + 1} 行: ' if li is not None else '') + msg)
        if li is not None:
            R.append(f'    原文: {lines[li].strip()[:200]}')
    R.append('')
    R.append(f'== 提示(不影响退出码,扫一眼):{len(fx.hints)} 处')
    for li, cls, msg in fx.hints[:40]:
        R.append(f'[{cls}] ' + (f'反编译第 {li + 1} 行: ' if li is not None else '') + msg)
    if len(fx.hints) > 40:
        R.append(f'    … 另有 {len(fx.hints) - 40} 处')
    if fx.ok_counts:
        R.append('== 已核对、反编译本来就对的:' + ', '.join(f'{k} {v} 处' for k, v in sorted(fx.ok_counts.items())))
    R.append('')
    if a.no_compile:
        R.append('== 编译:按 --no-compile 跳过(E1 / E5 只能靠编译发现,底子干不干净未知)')
    elif not comp:
        R.append(f'== 编译:{comp_desc},跳过;用 --fxc 指定。E1 / E5 只能靠编译发现,底子干不干净未知')
    elif fx.manual and ok is None:
        R.append('== 编译:有「需要手工」,没编译')
    else:
        R.extend('== ' + l for l in compile_log)
        R.append(f'   编译器: {comp_desc}')
        if ok:
            R.append(f'   严格编译(/T ps_5_0 /E main /Ges /WX /O3)0 告警;bin {bin_info}')
    if loop_rows:
        R.append('')
        R.append('== 编译回环:位运算关键指令(按分量计数;游戏字节码 vs 修好的 HLSL 重编译)')
        R.append(f'   {"项目":<34}{"游戏":>8}{"修好后":>8}  判定')
        for k, g, o, must in loop_rows:
            flag = ('相等' if g == o else '⚠ 不等,回报告核对') if must else '仅参考(数值往返、编译器优化会让它浮动)'
            R.append(f'   {k:<34}{g:>8}{o:>8}  {flag}')
    mism = [r for r in (loop_rows or []) if r[3] and r[1] != r[2]]
    R.append('')
    R.append('结论:' + ('全部自动修好,严格编译 0 告警' if ok and not fx.manual else
                      ('有需要手工的地方(退出码 1)' if fx.manual else ('编译没过(退出码 1)' if ok is False else '未编译验证'))) +
             (f';编译回环有 {len(mism)} 项与游戏不等,见上表' if mism else ''))
    # The full log only goes to disk when asked for; by default nothing but the fixed .hlsl is written.
    if a.report:
        with open(rep_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(R) + '\n')

    # ---- 屏幕摘要
    print(f'对齐 {rate:.2%}(汇编 {len(ins)} 条 / HLSL {len(stmts)} 句)')
    print('自动修补:' + (', '.join(f'{c} {n} 行' for c, n in sorted(cls_count.items())) or '无') +
          (f';E5 初值 {", ".join(init_regs)}' if init_regs else '') + (f';E3 补声明 {", ".join(fx.decl_add)}' if fx.decl_add else ''))
    print(f'需要手工 {len(fx.manual)} 处,提示 {len(fx.hints)} 处')
    for li, cls, msg in fx.manual[:10]:
        print(f'  [{cls}] ' + (f'第 {li + 1} 行: ' if li is not None else '') + msg[:150])
    if ok is not None:
        print('严格编译:' + ('0 告警 ' + bin_info if ok else '失败'))
    if mism:
        print(f'⚠ 编译回环有 {len(mism)} 项与游戏不等:' + ', '.join(f'{k} {g}/{o}' for k, g, o, _ in mism))
    print(f'输出:{out_path}')
    if a.report:
        print(f'逐处日志:{rep_path}')
    if fx.manual or ok is False:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
