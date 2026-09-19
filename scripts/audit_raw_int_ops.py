#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""找 3DMigoto 反编译器的「整数 / 浮点位模式混用」缺陷(E6 / E7)。

    python audit_raw_int_ops.py <游戏字节码反汇编 .msasm/.txt>

反编译器把所有寄存器都声明成 float4,整数结果按**数值**存进去。这对小整数没问题,但有三种情况会算错,
编译不报错、静态门全绿,只在实机表现为「某个效果没了 / 怪了」:

  E6 整数指令直接吃**原始位**(来源是常量缓冲、贴图读数或浮点值,中间没有 ftou/ftoi):
     反编译必须写 asuint()/asint();写成 (uint)/(int) 就是数值转换。
     实例:终末地天气字 cb2[材质号*16+13].x 是打包 uint,数值转换后四个字节恒为 0 ⇒ 无雨、无雪。
  E6c 条件跳转 / movc 条件直接判断**原始位**是否非零(if_nz cbN[..] 之类):
     反编译写成 `if (cb[..] != 0)` 是浮点比较,小整数的位模式是非规格化数,可能被冲成 0 ⇒ 条件恒假。
  E7 浮点指令读了**整数指令产出的位模式**(典型:and x, l(0x3f800000) 造 1.0/0.0、and x, l(0x7fffffff) 取绝对值):
     反编译把整数结果按数值存,1.0 的位模式就成了 1065353216.0 ⇒ 必须写 asfloat(...)。

做法:逐分量追踪每个寄存器分量最后一次由什么写入(int / float / raw=来自 cb 或贴图),列出上面三类位置。
「比较掩码 and 浮点值」是 `cond ? x : 0` 的惯用法,不算缺陷,只计数。
**每一处都要回反编译 HLSL 核对**:那里已经用了 asuint/asint/asfloat 就没事,用的是 (uint)/(int)/隐式数值存储就要修。
"""
# 输入是一份游戏 shader 的 Microsoft 反汇编；脚本只读取文本，不生成文件。
# 输出先报 uint 输入与惯用掩码数量，再分别列 E6、E6c、E7 的位置和来源类型。
# 三类标题后的数字都是“需要回 HLSL 核对”的候选数；0 表示该类未发现候选，不能替代编译回环。
# 每条的 asm 数字是反汇编行号，“分量”指出受影响的 xyzw，“来源”说明寄存器当前装的是哪类位值。
# 无参数时打印说明并退出 0；参数数量错误退出 1；完成审计时沿用 Python 正常退出 0。

import re, sys

INT_CONSUMERS = {"and", "or", "xor", "not", "ushr", "ishr", "ishl", "ubfe", "ibfe", "bfi", "bfrev", "countbits",
                 "firstbit_hi", "firstbit_lo", "firstbit_shi", "iadd", "imul", "umul", "udiv", "imad", "umad",
                 "imin", "imax", "umin", "umax", "ineg", "ieq", "ine", "ilt", "ige", "ult", "uge", "utof", "itof"}
INT_PRODUCERS = (INT_CONSUMERS - {"utof", "itof"}) | {"ftou", "ftoi", "eq", "ne", "lt", "ge"}
FLOAT_CONSUMERS = {"add", "mul", "mad", "div", "dp2", "dp3", "dp4", "min", "max", "rsq", "sqrt", "exp", "log", "frc",
                   "round_ne", "round_ni", "round_pi", "round_z", "sincos", "eq", "ne", "lt", "ge", "rcp",
                   "deriv_rtx", "deriv_rty", "deriv_rtx_coarse", "deriv_rty_coarse", "deriv_rtx_fine", "deriv_rty_fine"}
CONDS = re.compile(r"^(if_nz|if_z|breakc_nz|breakc_z|continuec_nz|continuec_z|discard_nz|discard_z|retc_nz|retc_z)\b")
SKIP = re.compile(r"^(else|endif|loop|endloop|break\b|continue\b|ret\b|switch|case|default|endswitch|label|call|dcl_|vs_|ps_|cs_|customdata|\{|\}|//)")
COMP = "xyzw"


# Split assembly operands while preserving comma groups inside literal vectors.
def split_ops(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# Return the register name and addressed components from one assembly operand.
def reg_parts(opnd):
    m = re.match(r"^-?\|?(r\d+|v\d+)(?:\.([xyzw]{1,4}))?\|?$", opnd)
    return (m.group(1), m.group(2) or "xyzw") if m else None


# Track value kinds through the assembly and print candidates where bit patterns need explicit casts.
def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 1)
    lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
    uint_inputs = set()
    for l in lines:                    # 声明为 uint 的输入:constant 插值的材质号、SV_IsFrontFace 等 SGV
        m = re.match(r"^\s*dcl_input_ps(?:_sgv|_siv)?\s+(?:constant\s+)?(v\d+)\.\w+(?:,\s*(\w+))?", l)
        if m and ("constant" in l or (m.group(2) or "") in ("is_front_face", "primitive_id", "sampleIndex", "coverage")):
            uint_inputs.add(m.group(1))
    typ, e6, e6c, e7, idiom = {}, [], [], [], 0

    # Read the current kind of one source component so each instruction can propagate it correctly.
    def src_type(s, dcomp):
        if s.startswith("l("):
            return "lit"
        if re.search(r"\b(cb\d+|icb)\[", s) or re.match(r"^-?\|?t\d+", s):
            return "raw"
        rp = reg_parts(s)
        if not rp:
            return "float"
        reg, swz = rp
        ch = swz[COMP.index(dcomp)] if len(swz) == 4 else swz[0]
        if reg.startswith("v"):
            return "int" if reg in uint_inputs else "float"
        return typ.get((reg, ch), "float")

    for no, raw in enumerate(lines, 1):
        l = raw.strip()
        if not l:
            continue
        mc = CONDS.match(l)
        if mc:
            opnd = l[len(mc.group(1)):].strip()
            k = src_type(opnd, "x")
            if k in ("raw", "float"):
                e6c.append((no, l, k))
            continue
        if SKIP.match(l):
            continue
        parts = l.split(None, 1)
        op = re.sub(r"(_sat|_indexable\(.*|_aoffimmi.*|\(.*)$", "", parts[0])
        ops = split_ops(parts[1]) if len(parts) > 1 else []
        if not ops:
            continue
        dest = reg_parts(ops[0]); srcs = ops[1:]
        dcomps = dest[1] if dest else ""
        if dest:
            for dc in dcomps:
                kinds = [src_type(s, dc) for s in srcs]
                if op in INT_CONSUMERS and any(k in ("float", "raw") for k in kinds):
                    if op in ("and", "or") and "int" in kinds and not any(s.startswith("l(0x") for s in srcs):
                        idiom += 1
                    else:
                        e6.append((no, l, dc, kinds))
                    break
                if op in FLOAT_CONSUMERS and "int" in kinds:
                    e7.append((no, l, dc, kinds)); break
                if op == "movc" and kinds and kinds[0] in ("raw", "float"):
                    e6c.append((no, l, kinds[0])); break
        if dest:
            reg = dest[0]
            for dc in dcomps:
                if op in INT_PRODUCERS:
                    t = "int"
                elif op in ("mov", "movc"):
                    ks = [src_type(s, dc) for s in srcs]
                    vals = ks[1:] if op == "movc" else ks
                    t = "raw" if "raw" in vals else ("float" if "float" in vals else "int")
                elif op.startswith(("ld", "sample", "gather")):
                    t = "raw"
                else:
                    t = "float"
                typ[(reg, dc)] = t
    print(f"声明为 uint 的输入: {sorted(uint_inputs) or '无'};「比较掩码 and 浮点值」惯用法(不算缺陷)= {idiom} 处")
    print(f"\nE6 整数指令吃原始位 / 浮点值: {len(e6)} 处  —— 反编译应为 asuint/asint")
    for no, l, dc, kinds in e6:
        print(f"  asm {no:>5}: {l[:90]}   [分量 {dc},来源 {kinds}]")
    print(f"\nE6c 条件直接判原始位 / 浮点值非零: {len(e6c)} 处  —— 反编译应为 asint(...) != 0")
    for no, l, k in e6c:
        print(f"  asm {no:>5}: {l[:90]}   [来源 {k}]")
    print(f"\nE7 浮点指令读整数位模式: {len(e7)} 处  —— 反编译应为 asfloat(...)")
    for no, l, dc, kinds in e7:
        print(f"  asm {no:>5}: {l[:90]}   [分量 {dc},来源 {kinds}]")


if __name__ == "__main__":
    main()
