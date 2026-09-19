# -*- coding: utf-8 -*-
"""resolve_textures.py —— 从 mod 的 ini 反推「每次 draw 实际绑了哪些贴图」(通吃各种写法),只读。

用法:
    python resolve_textures.py <mod 文件夹> [--section 子串] [--draw 数量,起点[,基顶点]] [--ini 相对路径子串]
                               [--mods-root <Mods 根>] [--ps-hlsl <底子.fixed.hlsl>] [--json 输出.json] [--all] [--verbose]

默认只列有 draw 的 TextureOverride / CommandList 段;`--section` / `--draw` 缩到目标那几次;`--all` 连 `[CustomShader*]` 里的重放 draw 也列。

认这些写法(2026-09 在 Mods 里全见过):
  ① 槽位式       `ps-t16 = ResourceX` —— 直接写进游戏 PS 自己读的槽。⚠ 槽号每个 PS 都不一样(同一角色见过 t16/17/18、t18/19/20、描边 t13),不能查表
  ② RabbitFX 式  `Resource\\RabbitFx\\Diffuse = ref ResourceX` + `run = CommandList\\RabbitFx\\SetTextures`
                  → 固定高槽 t70 漫反射 / t71 光照图 / t72 法线 / t73 抠图 / t74 雨;GlowMap t60 / FXMap t61。映射从 <Mods 根> 里的 RabbitFX.ini 读,找不到用内置表
  ③ 中转别名     `ResourceRFXCur_Diffuse = ref Resource-4` … 再 `Resource\\RabbitFX\\Diffuse = ref ResourceRFXCur_Diffuse`(别名链自动跟到文件)
  ④ 换 hash      `[TextureOverride…] hash = <贴图 hash>` + `this = Resource_Texture7`:替换游戏自己那张图,槽号由游戏定,角色按文件名 / 格式猜
  ⑤ 状态分支     `if $swapkey3 == 0 … elif … else … endif`:draw 的祖先分支 = 确定;同级互斥分支丢掉;之前已关掉的 if 块里的赋值 = 分支(带条件)。
                  再用 [Constants] 里 `global [persist] $x = 默认值` 算出**默认状态下**生效的是哪张
  ⑥ 嵌套命令表   `run = CommandListX` 原地展开(最多 8 层,防环);跑到别的 namespace(EFMIv1 / RabbitFx)只记一笔「外部」
  ⑦ 运行时改写   draw 前 `ps-uN =`、`Dispatch`、名字像 SuperSet / Color / Recolor 的命令表 → 提示贴图可能被计算着色器改过色

`--ps-hlsl` 给底子时再从着色器那头反推:列出所有 `tN.Sample*`,标出 `cb6[6]` 染色前那一次(= 漫反射槽),以及有没有 t70 桥接。
两头对上,才算「知道这次 draw 的漫反射是哪张图」。找到贴图后用 stocking_preview.py 按 draw 的 UV 岛取色,别拿整张图的平均色。

依赖:标准库。
"""
from __future__ import annotations

# 输入是 mod 文件夹及可选 draw/section/INI 筛选；--ps-hlsl 可补充 shader 侧采样证据。
# 输出逐 draw 列到达条件、贴图绑定、别名链、DDS 格式和漫反射结论；--json 才写结构化文件。
# “[Constants] 默认值(N 个)”是参与状态分支求值的变量数；只显示前 12 个不影响内部判定。
# 每个 draw 的候选贴图数量和“其它状态 N 种”用于判断是否要为多个状态分别接线；N 不是重复文件数。
# shader 侧的 tN 行号和染色行号是当前 HLSL 证据；“没找到”表示输入可能不是材质 PS。
# 成功完成退出 0；mod/INI 输入错误退出非 0；“没有匹配 draw”仍是正常查询结果并退出 0。

import argparse
import json
import re
import struct
import sys
from pathlib import Path

RE_SECTION = re.compile(r'^\s*\[([^\]]+)\]\s*$')
RE_IF = re.compile(r'^\s*if\s+(.+?)\s*$', re.I)
RE_ELIF = re.compile(r'^\s*(?:elif|else\s+if)\s+(.+?)\s*$', re.I)
RE_ELSE = re.compile(r'^\s*else\s*$', re.I)
RE_ENDIF = re.compile(r'^\s*endif\s*$', re.I)
RE_DRAW = re.compile(r'^\s*(drawindexed|drawindexedinstanced|draw|drawinstanced)\s*=\s*(.+?)\s*$', re.I)
RE_ASSIGN = re.compile(r'^\s*([A-Za-z_$][\w\\\-\.]*)\s*=\s*(.+?)\s*$')
RE_RUN = re.compile(r'^\s*run\s*=\s*(.+?)\s*$', re.I)
RE_SLOT = re.compile(r'^(ps|vs|cs|gs|hs|ds)-(t|u|s)(\d+)$', re.I)
RE_MESH = re.compile(r'\[mesh:([^\]]+)\]')
RE_VCOUNT = re.compile(r'\[vertex_count:(\d+)\]')
RE_HASH8 = re.compile(r'^[0-9a-fA-F]{8}$')
RE_CONST = re.compile(r'^\s*(?:global\s+)?(?:persist\s+)?(\$\w+)\s*=\s*(-?\d+(?:\.\d+)?)\s*$', re.I)

RABBITFX_DEFAULT = {'diffuse': 70, 'lightmap': 71, 'normalmap': 72, 'discardmap': 73, 'rainmap': 74, 'glowmap': 60, 'fxmap': 61}
RECOLOR_HINT = re.compile(r'superset|recolor|color|hue|tint', re.I)
SRGB_DXGI = {29, 72, 75, 78, 91, 93, 99}
DXGI_NAMES = {28: 'RGBA8', 29: 'RGBA8_SRGB', 71: 'BC1', 72: 'BC1_SRGB', 74: 'BC2', 75: 'BC2_SRGB', 77: 'BC3', 78: 'BC3_SRGB',
              80: 'BC4', 83: 'BC5', 95: 'BC6H', 98: 'BC7', 99: 'BC7_SRGB', 87: 'BGRA8', 91: 'BGRA8_SRGB'}
FOURCC_NAMES = {b'DXT1': 'BC1', b'DXT3': 'BC2', b'DXT5': 'BC3', b'ATI1': 'BC4', b'BC4U': 'BC4', b'ATI2': 'BC5', b'BC5U': 'BC5'}


# Decode INI text without losing files written in common Windows encodings.
def read_text(p: Path) -> str:
    b = p.read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode('latin-1')


# Treat any DISABLED-prefixed path component as an inactive configuration source.
def is_disabled(rel: Path) -> bool:
    return any(part.upper().startswith('DISABLED') for part in rel.parts)


# Remove INI comments while preserving the executable assignment text.
def code(raw: str) -> str:
    """Strip a trailing comment; whole-line comments become ''."""
    s = raw.lstrip()
    if s.startswith(';'):
        return ''
    return raw.split(';', 1)[0].rstrip()


# Parse the DDS header fields needed to identify dimensions, format, mip count, and sRGB use.
def dds_info(path: Path):
    try:
        with open(path, 'rb') as f:
            h = f.read(148)
    except OSError:
        return None
    if len(h) < 128 or h[:4] != b'DDS ':
        return None
    height, width = struct.unpack_from('<2I', h, 12)
    mips = struct.unpack_from('<I', h, 28)[0] or 1
    fourcc = h[84:88]
    if fourcc == b'DX10' and len(h) >= 132:
        dxgi = struct.unpack_from('<I', h, 128)[0]
        return width, height, mips, DXGI_NAMES.get(dxgi, f'DXGI_{dxgi}'), dxgi in SRGB_DXGI
    return width, height, mips, FOURCC_NAMES.get(fourcc, fourcc.decode('latin-1').strip('\x00') or 'RGBA'), None


# Infer a display-only texture role from binding context before falling back to weak filename hints.
def role_guess(name: str, fmt, srgb, via_name) -> str:
    """Diffuse / LightMap / NormalMap … from the RabbitFX name first, then the file name, then the DDS format."""
    for src in (via_name or '', name or ''):
        v = src.lower()
        for k, r in (('diffuse', 'Diffuse'), ('lightmap', 'LightMap'), ('normal', 'NormalMap'), ('discard', 'DiscardMap'),
                     ('rain', 'RainMap'), ('glow', 'GlowMap'), ('fxmap', 'FXMap'), ('ramp', 'RampMap'), ('mask', 'Mask')):
            if k in v:
                return r
    if fmt == 'BC5':
        return 'NormalMap?'
    if fmt and srgb:
        return 'Diffuse?'
    if fmt and srgb is False:
        return 'data?'
    return '?'


# Store one parsed INI as ordered sections so command execution can be replayed faithfully.
class Ini:
    """One ini split into sections; each line keeps its 1-based number."""

    # Decode the file and preserve section order, line numbers, and relative paths.
    def __init__(self, path: Path, mod: Path):
        self.path = path
        self.rel = str(path.relative_to(mod)).replace('\\', '/')
        self.sections: dict[str, list[tuple[int, str]]] = {}
        self.names: dict[str, str] = {}
        self.order: list[str] = []
        self.namespace = ''
        cur = None
        for i, raw in enumerate(read_text(path).splitlines(), 1):
            m = RE_SECTION.match(code(raw))
            if m:
                cur = m.group(1).strip()
                self.sections.setdefault(cur.lower(), [])
                self.names[cur.lower()] = cur
                self.order.append(cur)
                continue
            if cur is None:
                m2 = RE_ASSIGN.match(code(raw))
                if m2 and m2.group(1).lower() == 'namespace':
                    self.namespace = m2.group(2).strip()
                continue
            self.sections[cur.lower()].append((i, raw))


# Index all enabled INI files and expose case-insensitive section lookup across the mod.
class Mod:
    # Build the section table and collect default values used to evaluate state branches.
    def __init__(self, root: Path):
        self.root = root
        self.inis = [Ini(p, root) for p in sorted(root.rglob('*.ini'))
                     if not is_disabled(p.relative_to(root)) and p.name.lower() != 'desktop.ini']
        self.index: dict[str, tuple[Ini, list[tuple[int, str]]]] = {}
        for ini in self.inis:
            for k, lines in ini.sections.items():
                self.index.setdefault(k, (ini, lines))
        self.resources = {k: self.kv(v[1]) for k, v in self.index.items() if k.startswith('resource')}
        # default values of $variables from every [Constants] section (for the "default state" evaluation)
        self.defaults: dict[str, float] = {}
        for ini in self.inis:
            for _, raw in ini.sections.get('constants', []):
                m = RE_CONST.match(code(raw))
                if m:
                    self.defaults.setdefault(m.group(1).lower(), float(m.group(2)))

    @staticmethod
    # Parse plain key/value assignments from a section body.
    def kv(lines):
        out = {}
        for _, raw in lines:
            m = RE_ASSIGN.match(code(raw))
            if m:
                out.setdefault(m.group(1).lower(), m.group(2).strip())
        return out

    # Resolve a section name case-insensitively across all enabled INI files.
    def section(self, name: str):
        return self.index.get(name.lower())

    # Evaluate simple state expressions against declared defaults and return unknown when unsafe.
    def evaluate(self, cond: str):
        """True / False under the [Constants] defaults, None when the condition needs runtime info (ps ==, vs ==, unknown $var)."""
        expr = cond
        unknown = False

        # Substitute only variables whose default value was read from Constants.
        def sub(m):
            nonlocal unknown
            v = self.defaults.get(m.group(0).lower())
            if v is None:
                unknown = True
                return '0'
            return repr(v)
        expr = re.sub(r'\$\w+', sub, expr)
        if unknown or re.search(r'\b(ps|vs|cs|DRAW_TYPE|time|x\d+|y\d+|z\d+|w\d+|rt_width|rt_height|res_width|res_height)\b', expr, re.I):
            return None
        expr = expr.replace('&&', ' and ').replace('||', ' or ')
        expr = re.sub(r'!(?!=)', ' not ', expr)
        if not re.fullmatch(r'[\d\s\.\(\)=<>!andornot\-\+\*/]+', expr):
            return None
        try:
            return bool(eval(expr, {'__builtins__': {}}, {}))
        except Exception:
            return None


# Remove INI reference prefixes so resource aliases share one canonical spelling.
def strip_ref(v: str) -> str:
    v = v.strip()
    for kw in ('ref ', 'reference ', 'copy ', 'copy_desc '):
        if v.lower().startswith(kw):
            return v[len(kw):].strip()
    return v


# Read the live RabbitFX slot map and fall back to documented defaults only when unavailable.
def load_rabbitfx_map(mods_root):
    if mods_root:
        for p in sorted(Path(mods_root).rglob('RabbitFX.ini')):
            if is_disabled(p.relative_to(mods_root)):
                continue
            m = {}
            for slot, res in re.findall(r'^\s*ps-t(\d+)\s*=\s*(?:ref\s+)?Resource(\w+)', read_text(p), re.M | re.I):
                m.setdefault(res.lower(), int(slot))
            if m:
                return m, str(p)
    return dict(RABBITFX_DEFAULT), '(内置表;没找到 RabbitFX.ini)'


# Record one active conditional branch while replaying nested command lists.
class Frame:
    __slots__ = ('conds', 'branch')

    # Start a branch frame with no previously closed alternatives.
    def __init__(self, cond):
        self.conds = [cond]
        self.branch = 0


# Render the current branch as a concise condition for human-readable evidence.
def branch_cond(fr: Frame) -> str:
    # elif shows only its own test (the implied "previous ones were false" is noise for a reader); else shows the negation
    c = fr.conds[fr.branch]
    if c is not None:
        return c
    return '!(' + ' || '.join(x for x in fr.conds if x) + ')'


# Replay INI sections in execution order and emit draw events with their effective bindings.
class Walker:
    """Flatten one section (following `run =`) into events tagged with their if-frame path."""

    # Keep the parsed mod and the event list produced by each traversal.
    def __init__(self, mod: Mod):
        self.mod = mod

    # Traverse one root section with a fresh alias and recursion state.
    def walk(self, sec_name: str):
        self.events = []
        self._walk(sec_name, [], 0, set(), '')
        return self.events

    # Expand nested command lists in place while preventing cycles and excessive depth.
    def _walk(self, sec_name, prefix, depth, seen, inherited_label):
        hit = self.mod.section(sec_name)
        if hit is None:
            self.events.append(dict(kind='external', text=sec_name, path=list(prefix)))
            return
        ini, lines = hit
        key = sec_name.lower()
        if key in seen or depth > 8:
            self.events.append(dict(kind='note', text=f'{sec_name}: 递归 / 太深,不再展开', path=list(prefix)))
            return
        seen = seen | {key}
        frames: list[Frame] = []

        # Snapshot only the currently active conditions for the next emitted event.
        def path():
            return prefix + [(id(f), f.branch, branch_cond(f)) for f in frames]

        last_comment = inherited_label
        for ln, raw in lines:
            s = raw.strip()
            if s.startswith(';'):
                if RE_MESH.search(s) or RE_VCOUNT.search(s):
                    last_comment = s.lstrip('; ').strip()
                continue
            t = code(raw)
            if not t.strip():
                continue
            if RE_ENDIF.match(t):
                if frames:
                    frames.pop()
                continue
            m = RE_ELIF.match(t)
            if m and frames:
                frames[-1].conds.append(m.group(1)); frames[-1].branch += 1
                continue
            if RE_ELSE.match(t) and frames:
                frames[-1].conds.append(None); frames[-1].branch += 1
                continue
            m = RE_IF.match(t)
            if m:
                frames.append(Frame(m.group(1)))
                continue
            m = RE_DRAW.match(t)
            if m:
                self.events.append(dict(kind='draw', ini=ini.rel, line=ln, section=ini.names[key], op=m.group(1).lower(),
                                        args=m.group(2), label=last_comment, path=path(), depth=depth))
                if depth == 0:
                    last_comment = ''
                continue
            m = RE_RUN.match(t)
            if m:
                target = m.group(1).strip()
                if target.lower().startswith('commandlist') and '\\' not in target:
                    self.events.append(dict(kind='run', text=target, path=path(), ini=ini.rel, line=ln))
                    self._walk(target, path(), depth + 1, seen, last_comment)
                else:
                    self.events.append(dict(kind='external', text=target, path=path(), ini=ini.rel, line=ln))
                continue
            if t.strip().lower().startswith('dispatch'):
                self.events.append(dict(kind='dispatch', text=t.strip(), path=path(), ini=ini.rel, line=ln))
                continue
            m = RE_ASSIGN.match(t)
            if m:
                self.events.append(dict(kind='assign', lhs=m.group(1), rhs=m.group(2).strip(), path=path(), ini=ini.rel, line=ln))


# Classify whether a binding path is certain, conditional, or incompatible with a draw path.
def relation(ev_path, draw_path):
    """'certain' when the event is on the draw's own path, 'excluded' when in a sibling branch, else ('maybe', extra conds)."""
    extra = []
    for k, (fid, br, cond) in enumerate(ev_path):
        if k < len(draw_path) and draw_path[k][0] == fid:
            if draw_path[k][1] != br:
                return 'excluded', []
            continue
        extra.append(cond)
    return ('maybe', extra) if extra else ('certain', [])


# Follow resource aliases to a filename while recording every hop and breaking cycles.
def resolve_chain(mod: Mod, name: str, aliases: dict):
    """Follow `X = ref Y` aliases and [ResourceX] filename until a file, a filename-less resource, or an unknown name."""
    cur = strip_ref(name)
    trail = [cur]
    for _ in range(12):
        low = cur.lower()
        if low in aliases:
            cur = strip_ref(aliases[low]); trail.append(cur); continue
        sec = mod.resources.get(low)
        if sec is not None:
            return trail, sec.get('filename'), sec
        return trail, None, None
    return trail, None, None


# Normalize draw syntax so equivalent indexed calls can be grouped together.
def draw_key(op: str, args: str):
    a = [x.strip() for x in args.split(',')]
    if op == 'drawindexedinstanced':
        return (a[0], a[2] if len(a) > 2 else '0', a[3] if len(a) > 3 else '0')
    return tuple((a + ['0', '0'])[:3])


# Reconstruct all texture candidates reaching one draw and select its default-state diffuse.
def analyse_draw(M: Mod, rfx: dict, events, d, verbose: bool):
    """Replay the events before draw `d`, return the effective bindings (certain first, then alternatives) and notes."""
    slots, names, aliases, notes, externals = {}, {}, {}, [], []
    for e in events:
        if e is d:
            break
        if e['kind'] in ('draw', 'note'):
            continue
        rel, extra = relation(e['path'], d['path'])
        if rel == 'excluded':
            continue
        if e['kind'] == 'assign':
            lhs, rhs = e['lhs'], e['rhs']
            ms = RE_SLOT.match(lhs)
            if ms:
                k = f'{ms.group(1).lower()}-{ms.group(2).lower()}{ms.group(3)}'
                store = slots.setdefault(k, [])
                if not extra:
                    store.clear()
                store.append((rhs, extra, f"{e['ini']}:{e['line']}", None))
                if ms.group(2).lower() == 'u':
                    notes.append(f"{e['ini']}:{e['line']} 写 {lhs}(UAV)—— draw 前有运行时写入")
            elif lhs.lower().startswith('resource') and '\\' in lhs:
                ns, _, nm = lhs[len('Resource'):].lstrip('\\').rpartition('\\')
                store = names.setdefault(nm.lower(), [])
                if not extra:
                    store.clear()
                store.append((rhs, extra, f"{e['ini']}:{e['line']}", f'{ns}\\{nm}'))
            elif lhs.lower().startswith('resource'):
                if not extra or lhs.lower() not in aliases:
                    aliases[lhs.lower()] = rhs
        elif e['kind'] == 'run':
            if RECOLOR_HINT.search(e['text']):
                notes.append(f"run = {e['text']}" + (f'(仅当 {" && ".join(extra)})' if extra else '') + ' —— 名字像改色 / 重写贴图的命令表,贴图可能被计算着色器改过')
        elif e['kind'] == 'dispatch':
            notes.append(f"{e['text']} —— draw 前跑了计算着色器")
        elif e['kind'] == 'external':
            externals.append(e['text'] + (f'(仅当 {" && ".join(extra)})' if extra else ''))

    bound = []
    for nm, lst in names.items():
        slot = rfx.get(nm)
        target = f'ps-t{slot}' if slot else f'?(RabbitFX 没有 {nm})'
        bound += [(target, rhs, extra, where, via) for rhs, extra, where, via in lst]
    for k, lst in slots.items():
        bound += [(k, rhs, extra, where, via) for rhs, extra, where, via in lst]

    rows = {}
    for target, rhs, extra, where, via in bound:
        trail, fn, sec = resolve_chain(M, rhs, aliases)
        info, exists = None, None
        if fn:
            owner = M.index.get(trail[-1].lower())
            fp = (owner[0].path.parent / fn) if owner else (M.root / fn)
            exists = fp.is_file()
            info = dds_info(fp) if exists else None
        value = fn or (trail[-1] + ('(无 filename,运行时生成)' if sec is not None else '(找不到定义)'))
        cond = ' && '.join(extra)
        default = M.evaluate(cond) if cond else True
        key = (target, value)
        row = rows.get(key)
        if row is None:
            row = rows[key] = dict(slot=target, value=value, file=fn, exists=exists, via=via, where=where, chain=' → '.join(trail),
                                   dds=(f'{info[0]}x{info[1]} mip{info[2]} {info[3]}' + (' sRGB' if info[4] else ' linear' if info[4] is False else '')) if info else '',
                                   role=('UAV(运行时写入)' if target.split('-')[1].startswith('u') else role_guess(fn or rhs, info[3] if info else None, info[4] if info else None, via)),
                                   conds=[], default=None, hits=0)
        row['hits'] += 1
        if not cond:
            row['certain'] = True          # an unconditional assignment on the draw's path: never demote it again
            row['conds'] = []
        elif not row.get('certain') and (not row['conds'] or len(cond) < len(row['conds'][0])):
            row['conds'] = [cond]
        # default-state verdict: certain wins; else True if any alternative evaluates True
        if default is True:
            row['default'] = True
        elif row['default'] is None:
            row['default'] = default
    # collapse families of numbered runtime resources (SuperColor001 … 018) into one line
    groups: dict[tuple, list] = {}
    for r in rows.values():
        if r['file'] is None and r['conds']:
            groups.setdefault((r['slot'], re.sub(r'\d+', '#', r['value'])), []).append(r)
    out = []
    dropped = set()
    for (slot, pat), grp in groups.items():
        if len(grp) >= 3:
            first = grp[0]
            merged = dict(first, value=f'{pat}(同类 {len(grp)} 个)', hits=sum(g['hits'] for g in grp),
                          default=True if any(g['default'] is True for g in grp) else (None if any(g['default'] is None for g in grp) else False))
            out.append(merged)
            dropped.update(id(g) for g in grp)
    out += [r for r in rows.values() if id(r) not in dropped]
    out.sort(key=lambda r: (r['conds'] != [], r['default'] is not True, r['slot']))
    # notes that only differ by a number (SuperSet_001 … 019) collapse into one line as well
    fam: dict[str, list] = {}
    for n in sorted(set(notes)):
        fam.setdefault(re.sub(r'\d+', '#', n), []).append(n)
    flat = [(v[0] if len(v) < 3 else f'{re.sub(r"\(仅当.*?\)", "", k)}(同类 {len(v)} 条,条件形如 {re.search(r"仅当 (.*?)\) ——", v[0]).group(1)[:80] if re.search(r"仅当 (.*?)\) ——", v[0]) else "?"})')
            for k, v in fam.items()]
    return out, flat, sorted(set(externals))


# Filter target draws, print their binding evidence, and optionally serialize the full result.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mod', help='mod 文件夹(含 ini 的那层或它的上级)')
    ap.add_argument('--section', help='只看段名含此子串的段')
    ap.add_argument('--draw', help='只看这组 draw 参数:数量,起点[,基顶点]')
    ap.add_argument('--ini', help='只看这个 ini(相对 mod 的路径子串)')
    ap.add_argument('--mods-root', help='Mods 根(读 RabbitFX.ini 的槽位映射;默认从 mod 路径往上找名为 Mods 的目录)')
    ap.add_argument('--ps-hlsl', help='底子 .fixed.hlsl:从着色器那头列采样槽并标出漫反射那次')
    ap.add_argument('--json', help='把完整结果写成 JSON(给别的脚本用;不给就不写任何文件)')
    ap.add_argument('--all', action='store_true', help='连 [CustomShader*] 里的重放 draw 也列')
    ap.add_argument('--verbose', action='store_true', help='每行都打印别名链和出处')
    a = ap.parse_args()

    mod = Path(a.mod)
    if not mod.is_dir():
        sys.exit(f'不是文件夹:{mod}')
    M = Mod(mod)
    if not M.inis:
        sys.exit('mod 里没有启用的 ini')
    mods_root = Path(a.mods_root) if a.mods_root else next((p for p in mod.resolve().parents if p.name.lower() == 'mods'), None)
    rfx, rfx_src = load_rabbitfx_map(mods_root)
    print(f'RabbitFX 槽位映射 {{{", ".join(f"{k}: t{v}" for k, v in sorted(rfx.items(), key=lambda x: x[1]))}}}  ← {rfx_src}')
    if M.defaults:
        shown = ', '.join(f'{k} = {v:g}' for k, v in list(M.defaults.items())[:12])
        print(f'[Constants] 默认值({len(M.defaults)} 个):{shown}{" …" if len(M.defaults) > 12 else ""}')

    want = tuple((a.draw.replace(' ', '').split(',') + ['0', '0'])[:3]) if a.draw else None
    W = Walker(M)
    results = []
    for ini in M.inis:
        if a.ini and a.ini.lower() not in ini.rel.lower():
            continue
        for sec in ini.order:
            low = sec.lower()
            is_top = low.startswith('textureoverride') or low.startswith('commandlist')
            if not (is_top or (a.all and low.startswith('customshader'))):
                continue
            if a.section and a.section.lower() not in low:
                continue
            events = W.walk(sec)
            head = M.kv(M.section(sec)[1])
            for d in [e for e in events if e['kind'] == 'draw']:
                key = draw_key(d['op'], d['args'])
                if want and key != want:
                    continue
                rows, notes, externals = analyse_draw(M, rfx, events, d, a.verbose)
                results.append(dict(ini=d['ini'], line=d['line'], section=d['section'], via_section=sec if d['depth'] else None,
                                    op=d['op'], args=d['args'], key=key, label=d['label'], ib_hash=head.get('hash'),
                                    filter_index=head.get('filter_index'), match_first_index=head.get('match_first_index'),
                                    path_conds=[p[2] for p in d['path']], bindings=rows, notes=notes, externals=externals))

    replaced = []
    for ini in M.inis:
        for sec in ini.order:
            if not sec.lower().startswith('textureoverride'):
                continue
            kv = M.kv(M.section(sec)[1])
            if 'this' in kv and kv.get('hash') and RE_HASH8.match(kv['hash']):
                trail, fn, _ = resolve_chain(M, kv['this'], {})
                fp = ini.path.parent / fn if fn else None
                info = dds_info(fp) if fp and fp.is_file() else None
                replaced.append((sec, kv['hash'], kv['this'], fn, info, kv.get('match_priority')))

    for r in results:
        print('\n' + '=' * 100)
        where = f"{r['ini']}:{r['line']}  [{r['section']}]" + (f"  (经 [{r['via_section']}] 展开)" if r['via_section'] else '')
        print(f"draw  {where}  {r['op']} = {r['args']}")
        if r['label']:
            print(f"      {r['label']}")
        extra = [x for x in (f'IB hash {r["ib_hash"]}' if r['ib_hash'] else '', f'match_first_index {r["match_first_index"]}' if r['match_first_index'] else '',
                             f'filter_index {r["filter_index"]}' if r['filter_index'] else '') if x]
        if extra:
            print('      ' + ' | '.join(extra))
        if r['path_conds']:
            print('      到达条件:' + '  &&  '.join(r['path_conds']))
        if not r['bindings']:
            print('      (draw 前没有任何贴图赋值 —— 贴图由外部命令表 / 游戏自己决定,见「外部」)')
        for b in r['bindings']:
            if b['conds']:
                mark = {True: '默认状态下生效', False: '非默认状态', None: '视运行时条件'}[b['default']]
                cond = f"   ⟵ {mark}:{b['conds'][0][:110]}" + (f'(共 {b["hits"]} 处赋值)' if b['hits'] > 1 else '')
            else:
                cond = ''
            via = f' (经 {b["via"]})' if b['via'] else ''
            ex = '' if b['exists'] in (None, True) else '  ⚠ 文件不存在'
            print(f"      {b['slot']:<8} {b['role']:<20} {b['value']:<46} {b['dds']}{ex}{via}{cond}")
            if a.verbose and '→' in b['chain']:
                print(f"               链:{b['chain']}   @ {b['where']}")
        # one-line verdict for the diffuse
        diff = [b for b in r['bindings'] if b['role'].startswith('Diffuse')]
        if diff:
            cert = [b for b in diff if not b['conds']]
            dflt = [b for b in diff if b['conds'] and b['default'] is True]
            alts = [b for b in diff if b['conds']]
            if cert:
                print(f"      ▶ 漫反射 = {cert[-1]['value']}(确定)")
            elif dflt:
                print(f"      ▶ 漫反射 默认状态下 = {dflt[0]['value']};其它状态 {len(alts) - 1} 种(见上)")
            else:
                print(f"      ▶ 漫反射 视状态而定,{len(alts)} 种候选(见上);没有一种在默认值下成立 —— 条件里有运行时量")
        for n in r['notes']:
            print('      ⚠ ' + n)
        for x in r['externals']:
            print('      外部:' + x)

    if replaced:
        print('\n' + '=' * 100)
        print('换 hash 式贴图替换([TextureOverride] hash = <贴图 hash> + this = …;槽号由游戏定,角色按文件名 / 格式猜):')
        for sec, h, this, fn, info, prio in replaced:
            dd = f'{info[0]}x{info[1]} {info[3]}' + (' sRGB' if info and info[4] else ' linear' if info and info[4] is False else '') if info else ''
            print(f'      [{sec}] hash {h} → {this} → {fn}  {dd}  {role_guess(fn or this, info[3] if info else None, info[4] if info else None, None)}')

    if a.ps_hlsl:
        print('\n' + '=' * 100)
        print(f'着色器那头:{a.ps_hlsl}')
        txt = read_text(Path(a.ps_hlsl)).splitlines()
        tint = next((i for i, l in enumerate(txt) if re.search(r'cb6\[6\]\.\w+\s*\*|\*\s*cb6\[6\]', l)), None)
        samples = [(i, m.group(1), l.strip()) for i, l in enumerate(txt) for m in [re.search(r'\bt(\d+)\.(?:Sample|Load|Gather)\w*\(', l)] if m]
        bridged = sorted({m.group(1) for l in txt for m in [re.search(r'\bt(\d+)\.GetDimensions\(', l)] if m and int(m.group(1)) >= 60})
        if bridged:
            print(f'      t{", t".join(bridged)} 有 GetDimensions 探测 = RabbitFX 高槽桥接(绑了高槽就读高槽,否则回落游戏自己的槽)')
        # the diffuse sample is the one that wrote the register cb6[6] multiplies, not simply the nearest sample above
        diffuse_line = None
        if tint is not None:
            mreg = re.match(r'\s*(r\d+)\.\w+\s*=\s*cb6\[6\]', txt[tint]) or re.search(r'\*\s*(r\d+)\.', txt[tint])
            reg = mreg.group(1) if mreg else None
            for j, slot, l in reversed(samples):
                if j < tint and (reg is None or re.match(rf'\s*{reg}\.\w+\s*=', l)):
                    diffuse_line = j
                    break
        for i, slot, l in samples:
            mark = '   ← 漫反射(它写的寄存器随后被 cb6[6] 染色)' if i == diffuse_line else ''
            print(f'      第 {i + 1} 行  t{slot}: {l[:96]}{mark}')
        if tint is not None:
            print(f'      第 {tint + 1} 行  染色:{txt[tint].strip()[:96]}')
        if tint is None:
            print('      没找到 cb6[6] 染色那一行 —— 这份可能不是材质 PS')

    if a.json:
        Path(a.json).write_text(json.dumps(dict(mod=str(mod), rabbitfx=rfx, defaults=M.defaults, draws=results,
                                                 hash_replaced=[dict(section=s, hash=h, this=t, file=f) for s, h, t, f, _, _ in replaced]),
                                           ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        print(f'\nJSON:{a.json}')
    if not results and not replaced:
        print('\n没有匹配的 draw。--section / --draw 放宽一点,或加 --all。')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main())
