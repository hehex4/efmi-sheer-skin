# -*- coding: utf-8 -*-
"""discover_fresnel_targets.py - 扫描一个 EFMI / 3DMigoto mod,列出所有可以加
Fresnel 边缘光的绘制(draw),并判定可用的「材质 pass 门控」。

只读,不改任何文件。

用法:
    python discover_fresnel_targets.py "<mod 文件夹>" [--json out.json] [--all]

为什么需要它:overlay 必须插在**正确的 draw 之后**,而且必须**只在材质 pass 跑**。
这两件事都无法靠肉眼可靠地从几千行 ini 里看出来 —— 同一组 draw 参数经常在多个
命令表里重复出现(跨 IB mod 尤其如此),wrap 错地方要么没效果,要么污染阴影/
prepass。本脚本把这两件事变成确定性的机器判定。

输出的 ID(D01, D02, …)是稳定的:同一个 mod 反复跑,只要 ini 没改,ID 不变。
wire_fresnel.py 直接吃这些 ID。
"""

from __future__ import annotations

# 输入是一个 mod 文件夹，可选 Mods 根目录；脚本只读取启用中的 INI。
# 输出列可接 draw、按 draw 合并的部件、材质 pass gate、CutoutMask 与贴图槽；--json 才写文件。
# “可接 IDs”是同一部件在材质 pass 中仍有效的 draw 数；LOD0/LOD1 各一份时应保留两份。
# gate 的“置信度”按证据强弱排序；定义数量与来源路径用于判断 gate 是否依赖共享组件。
# CutoutMask 与 ps-t 槽后的计数是命中的声明数量；0 表示未找到证据，不能凭名称猜默认值。
# 成功完成退出 0；mod 路径错误退出 2；找不到可用几何时输出诊断后保持正常结束语义。

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# --- draw 行 ---------------------------------------------------------------
# 两种指令都要认,而且**字段顺序不同**,认错会把 StartIndex 当成 BaseVertex:
#   drawindexedinstanced = IndexCount, InstanceCount, StartIndex, BaseVertex, StartInstance
#   drawindexed          = IndexCount, StartIndex, BaseVertex
# 本机 17 个 mod 里 12 个用前者、5 个用后者(lastrite / liino / 陈千语 等),
# 只认前者会把后者整个漏掉并谎报「这个 mod 没有几何」。
#
# 故意**不认** `draw = 4,0` / `drawinstanced`:前者在这个生态里几乎都是
# CustomShader 里的全屏四边形辅助绘制(顶点数 4 或 4096),不是角色部件;
# 把它们收进来只会污染目标列表。真遇到非索引几何时需要手工处理。
RE_DRAW = re.compile(
    r'^\s*(drawindexedinstanced|drawindexed)\s*=\s*(.+?)\s*$', re.I)


# Normalize indexed draw syntax while respecting the different instanced argument order.
def parse_draw(m):
    """按指令种类取出 (IndexCount, StartIndex, BaseVertex)。"""
    op = m.group(1).lower()
    args = [a.strip() for a in m.group(2).split(',')]

    # Read an optional integer field without turning a missing field into zero evidence.
    def at(i):
        return args[i] if len(args) > i and args[i] else '0'

    if op == 'drawindexedinstanced':
        return at(0), at(2), at(3)
    return at(0), at(1), at(2)          # drawindexed
RE_SECTION = re.compile(r'^\s*\[([^\]]+)\]\s*$')
RE_IF = re.compile(r'^\s*if\s+(.+?)\s*$', re.I)
RE_ELIF = re.compile(r'^\s*elif\s+(.+?)\s*$', re.I)
RE_ELSE = re.compile(r'^\s*else\s*$', re.I)
RE_ENDIF = re.compile(r'^\s*endif\s*$', re.I)
RE_FILTER_IDX = re.compile(r'^\s*filter_index\s*=\s*([\d.]+)', re.I)
RE_IFVS = re.compile(r'\bvs\s*==\s*(\d+)')
RE_MESH_COMMENT = re.compile(r'\[mesh:([^\]]+)\]|\[vertex_count:(\d+)\]')
# 贴图注入槽:mod 常用 RabbitFX 把自己的贴图绑到高槽(t70/t71/t72),原游戏 ps
# 读的是低槽(t16/t17/t18)。overlay 若要采样贴图,必须用**这个 mod 实际绑的槽**。
RE_PS_SLOT = re.compile(r'^\s*ps-t(\d+)\s*=\s*(.+?)\s*$', re.I)
RE_SETTEX = re.compile(r'^\s*run\s*=\s*(.*SetTextures.*?)\s*$', re.I)

# 我们自己生成的 section 前缀 —— 扫描时必须排除,否则重复运行会把上一轮追加的
# 重放 draw 当成新目标,越滚越多。
OURS_PREFIX = 'CustomShaderFresnelRim'

# 任何 [CustomShader*] 段里的 draw 都是「重放」而不是原始绘制,一律不当目标:
# 给重放再套一层重放没有意义,而且会把上一轮(或别的 skill)的产物越滚越大。
REPLAY_PREFIX = 'CustomShader'

# 作者生成器给 draw 门控变量起的名字很长,`$draw_component_0_0f9e1087_siwa1_001`
# 里真正有信息的只有末尾的部件名。
RE_DRAW_VAR = re.compile(r'\$draw_component_\d+_[0-9a-fA-F]+_(\w+)')

# Velo/EFMI 的 CrossIB 分类器约定(filter_index → pass 语义)
VS_PASS_NAMES = {
    '200': 'Pose (骨骼计算)',
    '201': 'Prepass / G-buffer',
    '202': 'Material (材质着色) <- 目标',
    '203': 'Outline (描边)',
    '204': 'Effect',
    '205': 'Effect',
}
MATERIAL_VS = '202'

# 共享 RabbitFX 给**材质**像素着色器打的 filter_index;阴影 pass 是 1718.2。
RABBITFX_MAIN = '1718.1'


# Exclude every INI below a DISABLED-prefixed directory.
def is_disabled(p: Path) -> bool:
    return any(part.upper().startswith('DISABLED') for part in p.parts)


# Read raw INI lines and retain their byte-preserving display form.
def read_lines(path: Path):
    """按字节读并切行,不解码整个文件。

    mod 的 ini 编码五花八门(作者注释常是 GBK,我们自己加的行是 ASCII),
    整体解码会炸或者悄悄损坏中文注释。全流程走字节,只在需要匹配/显示时
    局部宽松解码。返回 (行列表: list[bytes], 行尾: bytes)。
    """
    raw = path.read_bytes()
    crlf = raw.count(b'\r\n')
    lf = raw.count(b'\n') - crlf
    eol = b'\r\n' if crlf >= lf else b'\n'
    other = lf if eol == b'\r\n' else crlf
    lines = raw.split(eol)
    return lines, eol, other


# Decode INI bytes for matching with deterministic fallback order.
def as_text(b: bytes) -> str:
    """宽松解码一行,只用于正则匹配 —— latin-1 对 ASCII 逐字节等价且从不抛错。"""
    return b.decode('latin-1')


# Decode section labels for terminal output without raising on legacy bytes.
def as_display(b: bytes) -> str:
    """尽量还原成人能看的文本(作者注释可能是 UTF-8 或 GBK)。"""
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode('latin-1')


# Yield enabled INI files in stable path order.
def iter_inis(mod: Path):
    for p in sorted(mod.rglob('*.ini')):
        if is_disabled(p.relative_to(mod)):
            continue
        if p.name.lower() == 'desktop.ini':
            continue
        yield p


# Derive a short part label from nearby mesh metadata and enclosing conditions.
def label_for(lines, idx: int, cond_stack, stop_at: int = -1) -> str:
    """给一个 draw 起个人能认的名字。

    优先级:本 draw 之前的 [mesh:...] 注释 > if 条件里的 $draw_xxx_名字
    > 最内层非 vs 条件。作者生成的 mod 几乎都带 mesh 注释,手写的靠条件名。

    `stop_at` = 上一个 draw 或 section 头的行号,回溯到它为止。
    **不能用固定行数窗口**:LoyalTools / EFMIv1 这类生成器会在 `; [mesh:...]`
    注释和 draw 之间塞 6~11 行 per-slice 贴图重绑(Diffuse/LightMap/NormalMap +
    ps-tN + run SetTextures),固定 6 行窗口会整组失效,label 全部退化成
    `$swapkeyN == 0` —— 而这个坏名字还会被 wire 拿去当 section 名,导致几个
    不同部件"重名"。回溯边界必须是结构性的,不是数字。
    """
    for j in range(idx - 1, stop_at, -1):
        t = as_display(lines[j]).strip()
        if not t.startswith(';'):
            continue
        m = RE_MESH_COMMENT.search(t)
        if m:
            mesh = m.group(1)
            vc = ''
            m2 = re.search(r'\[vertex_count:(\d+)\]', t)
            if m2:
                vc = ' v=%s' % m2.group(1)
            if mesh:
                # 去掉生成器加的 `LOD0.<hash>-<顶点数>-` 前缀,真正有信息的是后半段
                # 部件名(`… Cat Hoodie`)。不去掉的话表格一截断就只剩前缀,全都长一样。
                mesh = re.sub(r'^LOD\d+\.[0-9a-fA-F]+-\d+-', '', mesh)
                return (mesh + vc).strip()
    for cond in reversed(cond_stack):
        m = RE_DRAW_VAR.search(cond)
        if m:
            return m.group(1)
    for cond in reversed(cond_stack):
        if not RE_IFVS.search(cond):
            return cond.strip()
    return cond_stack[-1].strip() if cond_stack else '(无条件)'


# Collect original indexed draws with their section, pass constraints, and texture bindings.
def scan_draws(mod: Path):
    """收集全部 draw。返回 list[dict],已按 (ini, 行号) 排序。"""
    out = []
    for ini in iter_inis(mod):
        lines, _eol, _other = read_lines(ini)
        section = ''
        cond_stack = []
        slots = {}          # 本 section 内到目前为止绑过的 ps-tN
        setters = []        # 本 section 内跑过的 …SetTextures 命令表
        stop_at = -1        # 上一个 draw / section 头,label 回溯到此为止
        for i, raw in enumerate(lines):
            t = as_text(raw)
            m = RE_SECTION.match(t)
            if m:
                section = m.group(1)
                cond_stack = []
                slots = {}
                setters = []
                stop_at = i
                continue
            m = RE_PS_SLOT.match(t)
            if m:
                slots['t' + m.group(1)] = m.group(2)[:40]
            m = RE_SETTEX.match(t)
            if m and m.group(1).lower() not in [x.lower() for x in setters]:
                # 3DMigoto 的 section 名不区分大小写,RabbitFx / RabbitFX 是同一个,
                # 分两行列出来会让人以为挂了两套框架。
                setters.append(m.group(1))
            if RE_ENDIF.match(t):
                if cond_stack:
                    cond_stack.pop()
                continue
            m = RE_IF.match(t)
            if m and not t.strip().lower().startswith('endif'):
                cond_stack.append(m.group(1))
                continue
            m = RE_ELIF.match(t)
            if m:
                if cond_stack:
                    cond_stack[-1] = m.group(1)
                else:
                    cond_stack.append(m.group(1))
                continue
            if RE_ELSE.match(t):
                if cond_stack:
                    cond_stack[-1] = '!(%s)' % cond_stack[-1]
                continue
            m = RE_DRAW.match(t)
            if not m:
                continue
            if section.startswith(REPLAY_PREFIX):
                continue          # CustomShader 段里的 draw 是重放,不是目标
            # 光靠 (IndexCount, StartIndex) 认物体是不够的 —— 还要 BaseVertex。
            # 同一条 IB 上偏移相同、基顶点不同的两个 draw 是**两个物体**,
            # 合并它们会导致 rim 接到错的部件上。
            idx_count, first_idx, base_vertex = parse_draw(m)
            # 把 enclosing 条件里出现的所有 vs 值收集起来。这是判断「这份 draw
            # 在材质 pass 里到底会不会发出」的唯一可靠依据 —— 比「它在哪个
            # Component 的命令表里」靠谱得多。跨 IB mod 常见的写法是同一部件在
            # 两条命令表里各有一份,分别只在不同的 pass 集合下生效:
            #     [Component0]  if vs == 202 || vs == 203   -> 材质 pass 走这份
            #     [Component4]  if vs == 200 || 201 || 204 || 205 -> 材质 pass 不走
            # 光看 section 名会得出「原主自己画的那份」这种错理由。
            gated_on = [c for c in cond_stack if RE_IFVS.search(c)]
            vs_vals = set()
            for c in gated_on:
                vs_vals.update(RE_IFVS.findall(c))
            out.append(dict(
                ini=str(ini.relative_to(mod)).replace('\\', '/'),
                line=i + 1,
                section=section,
                index_count=idx_count,
                first_index=first_idx,
                base_vertex=base_vertex,
                vs_values=sorted(vs_vals),
                ps_slots=dict(slots),
                set_textures=list(setters),
                conds=list(cond_stack),
                vs_gated=gated_on[0] if gated_on else '',
                label=label_for(lines, i, cond_stack, stop_at),
                already_wired=any(
                    OURS_PREFIX in as_text(lines[k])
                    for k in range(i + 1, min(i + 6, len(lines)))),
            ))
            stop_at = i
    for n, d in enumerate(out, 1):
        d['id'] = 'D%02d' % n
    return out


# Find active CutoutMask declarations that may constrain pixel coverage.
def detect_cutout_mask(mod: Path):
    """找「像素级抠图遮罩」机制。

    有些 mod 靠一张遮罩贴图 + ShaderRegex 注入 `discard` 来做服装切换:几何照画,
    被遮罩判负的像素在 ps 里被丢弃。我们的 overlay **换掉了 ps**,那段注入对它
    不生效 —— 不复刻同一条 discard 的话,被抠掉的区域会浮出一圈没有实体的光边。

    返回 (ini 路径, 候选寄存器列表) 或 (None, [])。
    """
    for ini in iter_inis(mod):
        try:
            lines, _e, _o = read_lines(ini)
        except OSError:
            continue
        has_discard = any(b'discard' in raw.lower() for raw in lines)
        if not has_discard and 'cutout' not in ini.name.lower():
            continue
        regs = []
        for raw in lines:
            t = as_text(raw)
            for m in re.finditer(r'dcl_resource_texture2d\D*t(\d+)', t):
                if m.group(1) not in regs:
                    regs.append(m.group(1))
            m = re.match(r'\s*ps-t(\d+)\s*=', t, re.I)
            if m and m.group(1) not in regs:
                regs.append(m.group(1))
        if regs or 'cutout' in ini.name.lower():
            return ini, regs
    return None, []


# Walk upward to locate the shared Mods root when the caller did not provide one.
def find_mods_root(mod: Path):
    """从 mod 路径往上找名为 Mods 的目录 —— 共享 RabbitFX 通常是它的兄弟。"""
    for parent in mod.resolve().parents:
        if parent.name.lower() == 'mods':
            return parent
    return None


# Rank material-pass gate candidates from local and shared filter_index evidence.
def detect_gates(mod: Path, draws, mods_root: Path | None):
    """判定可用的材质 pass 门控。三条路,按可靠性排序。"""
    gates = []

    # --- G1: CrossIB 分类器 → 内建变量 vs 可用 ---------------------------
    # 关键:**分类器不必由目标 mod 自己提供**。filter_index 是全局的,别的 mod
    # 装的分类器给游戏原版着色器打的标签,这个 mod 一样能用 —— 这是最常见的
    # 「其实可用」情况(references/gating.md 也这么写)。所以先扫 mod 自己,
    # 再扫整个 Mods 根目录,两者分开记账:自带的可以随包分发,靠别人的不能。
    filt = {}
    filt_external = {}
    for ini in iter_inis(mod):
        lines, _e, _o = read_lines(ini)
        cur = ''
        for raw in lines:
            t = as_text(raw)
            m = RE_SECTION.match(t)
            if m:
                cur = m.group(1)
                continue
            m = RE_FILTER_IDX.match(t)
            if m:
                filt.setdefault(m.group(1), []).append(
                    '%s [%s]' % (ini.relative_to(mod), cur))
    if mods_root and mods_root.exists():
        own = {p.resolve() for p in iter_inis(mod)}
        for ini in sorted(mods_root.rglob('*.ini')):
            if is_disabled(ini) or ini.resolve() in own:
                continue
            try:
                lines, _e, _o = read_lines(ini)
            except OSError:
                continue
            cur = ''
            for raw in lines:
                t = as_text(raw)
                m = RE_SECTION.match(t)
                if m:
                    cur = m.group(1)
                    continue
                m = RE_FILTER_IDX.match(t)
                if m and m.group(1) in VS_PASS_NAMES:
                    filt_external.setdefault(m.group(1), []).append(
                        '%s [%s]' % (ini, cur))

    vs_vals = sorted(v for v in filt if v in VS_PASS_NAMES)
    if MATERIAL_VS in filt:
        ev = filt[MATERIAL_VS][0]
        material_named = 'material' in ev.lower()
        gates.append(dict(
            id='G1', expr='vs == %s' % MATERIAL_VS, available=True,
            confidence='high' if material_named else 'medium',
            rank=100,
            why='mod 自带 CrossIB 分类器,filter_index=%s 定义于 %s'
                % (MATERIAL_VS, ev),
            note='分类器给游戏原版顶点着色器打标签:%s。这是最精确的门控。'
                 % VS_PASS_NAMES[MATERIAL_VS]))
    elif MATERIAL_VS in filt_external:
        srcs = filt_external[MATERIAL_VS]
        gates.append(dict(
            id='G1', expr='vs == %s' % MATERIAL_VS, available=True,
            confidence='medium',
            rank=60,
            why='这个 mod 自己**没有**分类器,但同 Mods 目录下有 %d 个启用中的 mod '
                '提供了 filter_index=202,例如 %s' % (len(srcs), srcs[0]),
            note='⚠ 靠别人的分类器:一旦那些 mod 被停用、或把本 mod 单独发给别人,'
                 'vs 恒为 0,rim 会静默消失且零报错。要随包分发就得自带一份分类器,'
                 '或改用 G2。'))
    elif vs_vals or filt_external:
        gates.append(dict(
            id='G1', expr='vs == %s' % MATERIAL_VS, available=False,
            confidence='-',
            why='本 mod 定义了 filter_index %s、全局有 %s,都没有 202'
                % (','.join(vs_vals) or '(无)',
                   ','.join(sorted(filt_external)) or '(无)'),
            note='材质 pass 没被标记,vs 门控用不了。'))
    else:
        gates.append(dict(
            id='G1', expr='vs == %s' % MATERIAL_VS, available=False,
            confidence='-',
            why='本 mod 和整个 Mods 目录里都没有任何 filter_index 定义'
                + ('' if mods_root else '(而且没能定位 Mods 根目录,试试 --mods-root)'),
            note='没有分类器时 vs 恒为 0,`vs == 202` 永远不成立。'))

    # --- G2: 共享 RabbitFX 给材质像素着色器打了 1718.1 → ps 可用 ----------
    uses_rfx = False
    for ini in iter_inis(mod):
        if b'RabbitFX' in ini.read_bytes():
            uses_rfx = True
            break
    rfx_path = None
    if mods_root and mods_root.exists():
        for cand in mods_root.rglob('RabbitFX.ini'):
            if is_disabled(cand):
                continue
            if RABBITFX_MAIN.encode() in cand.read_bytes():
                rfx_path = cand
                break
    if rfx_path:
        gates.append(dict(
            id='G2', expr='ps == %s' % RABBITFX_MAIN, available=True,
            confidence='medium',
            # 目标 mod 本来就靠 RabbitFX 上贴图时,`ps == 1718.1` **不引入任何
            # 新依赖** —— 它只可能在「这个 mod 本来就已经坏了」的环境里为假。
            # 这种情况下它比「蹭别人 mod 装的分类器」稳,排名要更高。
            rank=80 if uses_rfx else 40,
            why='共享 RabbitFX 在 %s,其 [ShaderRegexMain] 给**材质**像素着色器'
                '打 filter_index=%s(阴影 pass 是 1718.2,天然分开)%s'
                % (rfx_path, RABBITFX_MAIN,
                   ';而且**本 mod 的贴图本来就靠 RabbitFX 上**,'
                   '用它做门控不引入任何新依赖' if uses_rfx else ''),
            note='不需要 CrossIB 分类器。代价:依赖使用者装了同版本 RabbitFX;'
                 'RabbitFX 未匹配到的着色器(某些头发/特殊材质)不会被门控住。'))
    elif uses_rfx:
        gates.append(dict(
            id='G2', expr='ps == %s' % RABBITFX_MAIN, available=False,
            confidence='-',
            why='mod 引用了 RabbitFX,但%s没找到带 filter_index=%s 的 RabbitFX.ini'
                % ('在 %s 下' % mods_root if mods_root
                   else '(没能从这个路径往上找到 Mods 根目录,可用 --mods-root 指定)',
                   RABBITFX_MAIN),
            note='确认 RabbitFX 已安装且未被 DISABLED_;'
                 '若在临时副本上测试,加 --mods-root 指向真实 Mods 目录。'))

    # --- G3: mod 自己已经把 draw 关在 if vs == N 里 ------------------------
    self_gated = [d for d in draws if d['vs_gated']]
    if self_gated:
        gates.append(dict(
            id='G3', expr='(draw 自身已在 vs 门控内)', available=True,
            confidence='high', rank=10,
            why='%d 个 draw 本来就写在 `if vs == …` 块里' % len(self_gated),
            note='这些 draw 的 overlay 可以不额外加门控 —— 但只有当那个块**只**'
                 '含材质 pass(如 `if vs == 202`)时才成立;`vs == 202 || vs == 203`'
                 '这种同时含描边 pass 的,仍要在里面再套一层 vs == 202。'))
    return gates, filt


# Print stable draw IDs and all evidence needed to choose a safe material-pass gate.
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mod', help='mod 文件夹路径')
    ap.add_argument('--json', help='把完整结果写成 JSON')
    ap.add_argument('--all', action='store_true',
                    help='列出全部 draw(默认合并重复的 draw 参数)')
    ap.add_argument('--mods-root', help='Mods 根目录(找共享 RabbitFX 用);'
                                        '默认从 mod 路径往上找名为 Mods 的目录')
    args = ap.parse_args()

    mod = Path(args.mod)
    if not mod.is_dir():
        print('ERROR: 不是一个目录: %s' % mod)
        return 2

    draws = scan_draws(mod)
    if not draws:
        print('ERROR: 在 %s 下没找到任何 drawindexed / drawindexedinstanced。' % mod)
        print('       这个 mod 多半是纯贴图替换(slot-style)或纯 UI,没有自己的几何,')
        print('       Fresnel overlay 无处可挂 —— 本 skill 不适用。')
        print('       (注:`draw = 4,0` 这类全屏四边形辅助绘制**不算**几何,')
        print('        故意不收进目标列表。)')
        return 3

    mods_root = Path(args.mods_root) if args.mods_root else find_mods_root(mod)
    gates, filt = detect_gates(mod, draws, mods_root)

    token = hashlib.md5(mod.resolve().name.encode('utf-8')).hexdigest()[:6]

    print('MOD   : %s' % mod.resolve())
    print('TOKEN : %s   (section 名里的 mod 标识,防止两个 mod 装同一 skill 时撞名)'
          % token)
    print()
    # Keep table labels readable while preserving the distinguishing tail.
    def short_section(s):
        """去掉生成器加的公共前缀,只留能区分 LOD0/LOD1、Component 号的尾巴。"""
        for pre in ('CommandList_Draw_', 'CommandList_', 'CommandList\\'):
            if s.startswith(pre):
                return s[len(pre):]
        return s

    # 默认按 (IndexCount, StartIndex) 合并 —— 同一块几何在 LOD0/LOD1/借槽位处
    # 会重复出现,合并后一眼能看清「这个部件一共有几处要接」。
    groups = {}
    for d in draws:
        groups.setdefault(
            (d['index_count'], d['first_index'], d['base_vertex']), []).append(d)

    # 「这份 draw 在材质 pass 里到底会不会发出」——选 ID 时最容易搞错的一步。
    # 判据只有一条:**它的 enclosing 门控与你要用的门控有没有交集**。
    # 不靠 section 名推理(跨 IB mod 里 section 名会骗人)。
    # Accept a draw only when its enclosing VS conditions can include the material pass.
    def mat_ok(d, mat_vs=MATERIAL_VS):
        if not d['vs_values']:
            return True, ''            # 无 vs 约束 = 每个 pass 都发出 -> 可接
        if mat_vs in d['vs_values']:
            return True, ''
        return False, 'vs∈{%s}' % ','.join(d['vs_values'])

    if args.all:
        print('== 可加 rim 的 draw(逐条)==')
        print('%-5s %-20s %9s %9s %5s %-28s %s'
              % ('ID', 'PART', 'IDX_CNT', 'FIRST_ID', '材质?', 'SECTION', 'ENCLOSING VS-GATE'))
        print('-' * 124)
        for d in draws:
            ok, why = mat_ok(d)
            flag = '  *WIRED*' if d['already_wired'] else ''
            print('%-5s %-20s %9s %9s %5s %-28s %s%s'
                  % (d['id'], d['label'][:20], d['index_count'], d['first_index'],
                     '是' if ok else '否', short_section(d['section'])[-28:],
                     d['vs_gated'] or '(无 vs 门控)', flag))
    else:
        print('== 可加 rim 的部件(按完整 draw 参数合并;--all 看逐条)==')
        print('假设材质 pass = vs %s。「不可接」= 该 draw 的 enclosing 门控不含 %s,'
              % (MATERIAL_VS, MATERIAL_VS))
        print('在材质 pass 里根本不发出,接了也永远不执行。')
        print()
        print('%-20s %9s %9s %6s  %-16s %s'
              % ('PART', 'IDX_CNT', 'FIRST_ID', 'BASE_V', '可接 IDs', '不可接 IDs(原因)'))
        print('-' * 116)
        for (ic, fi, bv), ds in sorted(groups.items(), key=lambda kv: kv[1][0]['id']):
            good = [d for d in ds if mat_ok(d)[0]]
            bad = [d for d in ds if not mat_ok(d)[0]]
            why = mat_ok(bad[0])[1] if bad else ''
            wired = sum(1 for d in ds if d['already_wired'])
            flag = '  *已接 %d 处*' % wired if wired else ''
            print('%-20s %9s %9s %6s  %-16s %s%s'
                  % (ds[0]['label'][:20], ic, fi, bv,
                     ' '.join(d['id'] for d in good) or '(无)',
                     ('%s  %s' % (' '.join(d['id'] for d in bad), why)) if bad else '',
                     flag))

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    if multi:
        print()
        print('!! %d 个部件的 draw 出现在多处。上表已经替你排除了「材质 pass 里不'
              % len(multi))
        print('   发出」的那些,**剩下的「可接 IDs」仍需你自己判断要不要全接**:')
        print('   · LOD0 与 LOD1 各一份 → **两份都要接**。队友被游戏强制走 LOD1,')
        print('     只接 LOD0 的表现是「自己看得见、别人看不见」。')
        print('   · 同一 pass 里同一部件被画了两遍(例如借槽位一份 + 原主一份都在')
        print('     材质 pass) → **只接一份**,都接会把 rim 叠两遍、亮度翻倍。')
        print('   分辨方法:看 --all 的 SECTION 列。属于 LOD0/LOD1 两条命令表的是')
        print('   前者(section 名通常差一个 _lod 后缀);同一条命令表里出现两次的')
        print('   是后者。')

    print()
    print('== 材质 pass 门控 ==')
    if not gates:
        print('  (没有找到任何门控)')
    for g in gates:
        mark = 'OK  ' if g['available'] else 'NO  '
        print('  [%s] %s  %-24s 置信度=%s' % (g['id'], mark, g['expr'], g['confidence']))
        print('       理由: %s' % g['why'])
        print('       说明: %s' % g['note'])

    usable = sorted([g for g in gates if g['available']],
                    key=lambda g: -g.get('rank', 0))
    print()
    if usable:
        print('建议门控: [%s] %s' % (usable[0]['id'], usable[0]['expr']))
        if len(usable) > 1:
            print('  (备选: %s —— 排名依据是「会不会引入新依赖」,'
                  % ', '.join('[%s] %s' % (g['id'], g['expr'])
                              for g in usable[1:] if g.get('rank', 0) > 10))
            print('   自带分类器 > 本来就依赖的 RabbitFX > 蹭别人装的分类器)')
    else:
        print('!! 没有可用门控。不要硬上 —— 没有门控的 overlay 会在 prepass /')
        print('   阴影 pass 也执行,往那些 pass 的 RT0 里加光,后果从「没效果」')
        print('   到「阴影发白」都有可能。处理办法见 references/gating.md。')

    # --- 像素级抠图遮罩 ----------------------------------------------------
    cut_ini, cut_regs = detect_cutout_mask(mod)
    if cut_ini:
        print()
        print('== 检测到像素级抠图遮罩(discard)==')
        print('  来源: %s' % cut_ini.relative_to(mod))
        print('  候选遮罩寄存器: %s' % (', '.join('t' + r for r in cut_regs) or '(未识别)'))
        print('  这个 mod 用「几何照画、按遮罩在 ps 里 discard 像素」的方式做服装切换。')
        print('  我们的 overlay **换掉了 ps**,那段 discard 对它不生效 ⇒ 不处理的话,')
        print('  被抠掉的区域会浮出一圈没有实体的光边。')
        print('  处理:接线时加 `--cutout-mask t116`(换成上面正确的那个寄存器),')
        print('       它会把 hlsl 的 USE_CUTOUT_MASK 打开并填好槽位。')

    # --- 贴图注入槽位 ------------------------------------------------------
    # overlay 默认一张贴图都不采样,所以多数情况用不到这一节。但一旦要开
    # 「按 diffuse alpha 削弱」或「用法线贴图加布纹」,就必须填**这个 mod 实际
    # 绑的槽**:原游戏 ps 读的低槽因 PS 而异(09-02 更新后普遍 -1),而 RabbitFX 类框架把 mod 贴图注入到
    # t70/t71/t72 一类的高槽。照抄别的 mod 的槽号会采到空资源或原版贴图。
    slot_use, setters = {}, {}
    for d in draws:
        for k, v in d.get('ps_slots', {}).items():
            slot_use.setdefault(k, set()).add(v)
        for s in d.get('set_textures', []):
            setters[s] = setters.get(s, 0) + 1
    if slot_use or setters:
        print()
        print('== 贴图注入槽位(只有要在 overlay 里采样贴图时才需要)==')
        for k in sorted(slot_use, key=lambda s: int(s[1:])):
            vals = sorted(slot_use[k])
            print('  ps-%-5s <- %s%s' % (k, vals[0],
                                         ' (+%d 种)' % (len(vals) - 1)
                                         if len(vals) > 1 else ''))
        for s, n in sorted(setters.items(), key=lambda kv: -kv[1]):
            print('  %-40s 在 %d 个 draw 前执行' % (s, n))
            print('      ^ 槽位由这个命令表决定,ini 里看不到 ps-tN 就去读它。')
        if not slot_use and setters:
            print('  (本 mod 的槽位全由上面的命令表设置,ini 里没有直接的 ps-tN)')

    if filt:
        extra = {k: v for k, v in filt.items() if k not in VS_PASS_NAMES}
        if extra:
            print()
            print('注意:本 mod 还定义了非标准 filter_index %s —— 多个 ini 给同一个'
                  % ','.join(sorted(extra)))
            print('      着色器打 filter_index 会互相抢(后解析者赢),门控失灵时先查这里。')

    if args.json:
        Path(args.json).write_text(json.dumps(
            dict(mod=str(mod.resolve()), token=token, draws=draws,
                 gates=gates, filter_index=filt),
            ensure_ascii=False, indent=2), encoding='utf-8')
        print()
        print('JSON -> %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
