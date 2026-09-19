#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""find_draw_shaders.py —— 在 3DMigoto 帧转储的 log.txt 里,按 ini 段名 / IB hash / draw 参数找 draw,
列出 call 号、当时生效的 VS / PS hash、draw 参数、是哪个 TextureOverride 接管的。只读,只用标准库。
(skill efmi-sheer-skin 第 2 节第 1、2 步)

    python find_draw_shaders.py <转储目录或 log.txt> [更多转储 ...]
        [--section 子串 ...] [--ib HASH ...] [--draw 个数,起点[,基址] ...] [--vs HASH] [--ps HASH]
        [--mod-only | --game-only] [--cmds] [--slots] [--max N] [--list-sections] [--root <3DMigoto 根>]

- 至少给一个筛选条件。不同条件之间 = 都要满足(AND);同一条件给多次 = 任一命中(OR)。
  不知道段名:先 `--list-sections`(可配 `--section` 缩小),列出这一帧里执行过的全部 mod 段。
- `--section` 不分大小写,匹配「mod 发的 draw 自己所在的段」或「同一个 call 里在它之前执行过的段」
  (对游戏自己的 draw = 这个 call 里执行过的全部段,也就是被哪个 TextureOverride 接管了)。
- `--ib`:mod ini 里 `[TextureOverride…]` 的 `hash = ` 值。**EFMI 的游戏 IB 是一整块共享缓冲**(log 里
  `IASetIndexBuffer … hash=` 几乎全是同一个值),mod 的 8 位 hash 根本不出现在 log 里 ⇒ 本脚本到
  `--root`(默认自动找:转储目录的上一级 / 上两级里有 `Mods` 的那个)读 ini,把段名换成 hash 再比。
  ini 是**现在磁盘上**那份;段路径里的 mod 文件夹被加了 `DISABLED_` 前缀也能找到;dump 之后改过 hash 就对不上。
- `--vs` / `--ps` 按前缀匹配(给 8 位也行)。`--cmds` 打出命中 call 里匹配段执行过的命令
  (看 `if vs == 202 …: true/false`、`ps-t90 = …` 这类门控与绑定);`--slots` 打出游戏在该 draw 时绑定的 ps-t 槽贴图 hash。

log.txt 的格式(3DMigoto 1.3.x,EFMI 2026-09 实测;换版本先 `--list-sections` 看一眼还对不对):
- 每行开头 6 位数字 = call 号。游戏的一次 draw 与它之前的状态设置(IASetIndexBuffer / VSSetShader / PSSetShader …)
  共用同一个号;状态跨 call 保留,某次 draw 用的 VS / PS = 在它之前最后设置的那个(本脚本逐行追踪)。
- 游戏的 draw:`000118 DrawIndexedInstanced(IndexCountPerInstance:…, InstanceCount:…, StartIndexLocation:…, BaseVertexLocation:…, …)`
- mod 发的 draw(ini 里 `drawindexed = …`):
  `000118 3DMigoto  [commandlist\mods\…\x.ini\_draw_component4_lod] DrawIndexedInstanced(38925, 1, 204684, 0, 0)`;
  CommandList / CustomShader 段名被转成小写并带 ini 的相对路径,TextureOverride 段名保留原大小写。
- 同一个 call 的 `3DMigoto pre { … }` / `post { … }` 块写在游戏 draw 那一行**之后**,但 pre 块是在 draw 之前执行的。
- mod 发的 draw 用的 VS / PS = 游戏在这个 call 设好的那一对;段是 `[customshader…]`(写了 `ps = …`)时
  PS 实际是 mod 自己的替换 PS,输出里在 PS 后标 `*`。

⚠ `d3dx.ini` 的 `analyse_options` 必须带 `deferred_ctx_immediate`,否则角色的 draw 大多不进 log;
   一个 TextureOverride 都没找到时本脚本会提醒。定位只要 log.txt;要读 cb 常量得用带 `dump_cb` + `txt` 的转储
   (同目录 `<call>-ps-cb6=<hash>-vs=…-ps=….txt`)。LOD0(主控)和 LOD1(队友)是两帧,各给一个转储。

输出样例(作者本机 2026-09-10 庄方仪 V5 转储,找大腿袜 38925@204684;路径已缩写):

    python find_draw_shaders.py "<FrameAnalysis>\2026-09-10-122142 [zhuangfangyi]" --draw 38925,204684

    == 2026-09-10-122142 [zhuangfangyi]  (analyse_options: 0140063d, 1527 次游戏 draw, 155 次 mod draw, ini 根 <3DMigoto 根>)
    000118  mod  38925@204684+0   x1  IB 9a09f1f0  VS f11c7e1dbf876a69  PS d7bb9dd57f5b70c6  段 commandlist:…\zhuang fangyi.ini\_draw_component4_lod  ← TextureOverride:…\Zhuang Fangyi.ini\_Component4_LOD0 [49dfa7b0]
    001077  mod  38925@204684+0   x1  IB 9a09f1f0  VS f11c7e1dbf876a69  PS d7bb9dd57f5b70c6  段 commandlist:…\zhuang fangyi.ini\_draw_component4  ← TextureOverride:…\Zhuang Fangyi.ini\_Component4 [fe47dc61]
    001142  mod  38925@204684+0   x1  IB 9a09f1f0  VS 7b3a141f99cd9b39  PS 78015be8a27acd24  段 commandlist:…\zhuang fangyi.ini\_draw_component4  ← TextureOverride:…\Zhuang Fangyi.ini\_Component4 [fe47dc61]
    001399  mod  38925@204684+0   x1  IB 9a09f1f0  VS 1479b2b594b9c91a  PS 19c279d21b2035d5*  段 customshader:…\zhuang fangyi.ini\zfaniso_siwa2  ← TextureOverride:…\Zhuang Fangyi.ini\_Component0 [0f9e1087]  ← TextureOverride:…\mod.ini\_Texture…
    ...
    == 命中的 draw 共用 3 种 VS/PS 组合
       VS f11c7e1dbf876a69  PS d7bb9dd57f5b70c6  : 3 次
       VS 1479b2b594b9c91a  PS 19c279d21b2035d5  : 2 次
       VS 7b3a141f99cd9b39  PS 78015be8a27acd24  : 1 次

    python find_draw_shaders.py "<同一转储>" --ib 0f9e1087 --vs 1479b2b5 --mod-only     # C0 在材质 pass 画了哪些
    ...
          1 mod  56004@245133+0    1479b2b594b9c91a 19c279d21b2035d5 customshader:…\zhuang fangyi.ini\zfaniso_siwa1
          1 mod  38925@204684+0    1479b2b594b9c91a 19c279d21b2035d5 customshader:…\zhuang fangyi.ini\zfaniso_siwa2
    == 命中的 draw 共用 1 种 VS/PS 组合(门控证明:同一目标在 LOD0 / LOD1 两帧都只出现目标 PS)

读法:同一段几何一帧里被画好几次 = 不同 pass(阴影 / prepass / 材质 / 描边),每次 VS/PS 不同;材质 pass 那次
(本例 call 1399,VS 1479b2b5 布料族)的 PS 就是要替换的材质 PS。call 1399 由 `_Component0` 接管 ⇒ 这片 C4 的袜子
是从 C0 的列表里跨 IB 画的。第二个 `←` = 同一个 call 里别的 mod 的 TextureOverride 也触发了(本例是同角色的大招子 mod
在换贴图),不影响判断。要证明门控只命中目标,加 `--vs <材质 VS>` 在 LOD0 / LOD1 两帧里各跑一次,
「共用 1 种 VS/PS 组合」才算过。
"""
from __future__ import annotations

# 输入是一份或多份 FrameAnalysis log，以及至少一个 section/IB/draw/VS/PS 筛选条件。
# 输出逐帧报游戏 draw、mod draw、命中数和可选命令/槽位，再按 draw、VS、PS、段汇总。
# 帧标题里的两个 draw 数是该 log 解析到的总数；“命中 N”才是筛选后的数量，0 表示证据不足或条件不匹配。
# “共用 N 种 VS/PS 组合”用于判断目标是否共用材质 shader；期望共用时 N 必须为 1。
# --max 只限制逐条打印数量，不影响汇总计数。正常完成退出 0；log 不存在或参数无效时退出非 0。

import argparse
import collections
import os
import re
import sys

LINE = re.compile(r'^(\d{6}) (.*)$')
SUBLINE = re.compile(r'^\s+(\d+): (.*)$')
HASH = re.compile(r'hash=([0-9a-fA-F]+)')
MIG = re.compile(r'^3DMigoto\s+\[([^\]]+)\]\s*(.*)$')
DRAWCALL = re.compile(r'^(Draw\w*)\((.*)\)')
NAMED = re.compile(r'(\w+):(0x[0-9A-Fa-f]+|-?\d+)')
PSSRV = re.compile(r'^PSSetShaderResources\(StartSlot:(\d+), NumViews:(\d+)')
INI_SEC = re.compile(r'^\s*\[([^\]]+)\]')
INI_HASH = re.compile(r'^\s*hash\s*=\s*([0-9a-fA-F]+)')


# Normalize separators and case so log and INI section paths can be compared.
def norm(s: str) -> str:
    return s.replace('/', '\\').lower()


# Shorten a full command-list path for compact terminal tables.
def short(sec: str | None) -> str:
    if not sec:
        return '-'
    parts = sec.split('\\')
    if len(parts) > 3:
        return f'{parts[0]}:…\\{parts[-2]}\\{parts[-1]}'
    if len(parts) == 3:
        return f'{parts[0]}:{parts[-2]}\\{parts[-1]}'
    return sec


# Resolve TextureOverride section names from a frame log back to their current INI hashes.
class IniHashes:
    """把 log 里的 TextureOverride 段路径换成 ini 里写的 hash(读现在磁盘上的 ini)。"""

    # Store the optional game root and initialize per-file parse caches.
    def __init__(self, root: str | None):
        self.root = root
        self.files: dict[str, dict[str, str] | None] = {}
        self.memo: dict[str, str | None] = {}

    # Locate an INI despite a DISABLED prefix added after the frame was captured.
    def _find(self, rel_parts: list[str]) -> str | None:
        cur = self.root
        for comp in rel_parts:
            for cand in (comp, 'DISABLED_' + comp):
                p = os.path.join(cur, cand)
                if os.path.exists(p):
                    cur = p
                    break
            else:
                return None
        return cur if os.path.isfile(cur) else None

    # Parse and cache section-to-hash mappings for one INI file.
    def _load(self, path: str) -> dict[str, str] | None:
        if path not in self.files:
            table: dict[str, str] = {}
            sec = None
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    for line in f:
                        m = INI_SEC.match(line)
                        if m:
                            sec = m.group(1).strip().lower()
                            continue
                        m = INI_HASH.match(line)
                        if m and sec and sec not in table:
                            table[sec] = m.group(1).lower()
            except OSError:
                table = None
            self.files[path] = table
        return self.files[path]

    # Return the TextureOverride hash corresponding to a logged section path.
    def hash_of(self, sec: str) -> str | None:
        if not self.root or sec in self.memo:
            return self.memo.get(sec)
        parts = sec.split('\\')
        h = None
        if len(parts) >= 3 and parts[0].lower() == 'textureoverride':
            path = self._find(parts[1:-1])
            table = self._load(path) if path else None
            if table:
                h = table.get(('textureoverride' + parts[-1]).lower())
        self.memo[sec] = h
        return h


# Normalize named game draw arguments to count, start, and base vertex.
def game_draw_args(args: str):
    kv = {k: int(v, 0) for k, v in NAMED.findall(args)}
    count = next((kv[k] for k in ('IndexCountPerInstance', 'IndexCount', 'VertexCountPerInstance', 'VertexCount') if k in kv), None)
    start = next((kv[k] for k in ('StartIndexLocation', 'StartVertexLocation') if k in kv), None)
    return count, start, kv.get('BaseVertexLocation'), kv.get('InstanceCount')


# Normalize positional 3DMigoto draw arguments according to the API variant.
def mod_draw_args(api: str, args: str):
    n = [int(x) for x in re.findall(r'-?\d+', args)]
    if api == 'DrawIndexedInstanced' and len(n) >= 4:
        return n[0], n[2], n[3], n[1]
    if api == 'DrawIndexed' and len(n) >= 3:
        return n[0], n[1], n[2], None
    if api == 'DrawInstanced' and len(n) >= 3:
        return n[0], n[2], None, n[1]
    if api == 'Draw' and len(n) >= 2:
        return n[0], n[1], None, None
    return None, None, None, None


# Hold one draw event together with the shader state and mod commands active at that call.
class Ev:
    __slots__ = ('call', 'kind', 'api', 'count', 'start', 'base', 'inst', 'ib', 'vs', 'ps', 'own', 'trail', 'slots', 'cmds')

    # Format normalized draw coordinates for matching and terminal output.
    def draw_str(self) -> str:
        if self.count is None:
            return self.api
        s = f'{self.count}@{self.start}'
        if self.base is not None:
            s += f'+{self.base}'
        return s

    # Return every section that can explain why this draw was intercepted.
    def triggers(self) -> list[str]:
        return [t for t in self.trail if norm(t).startswith('textureoverride')]


# Apply AND across filter kinds and OR within repeated values of one kind.
def matches(ev: Ev, a, inih: IniHashes) -> bool:
    if a.mod_only and ev.kind != 'mod':
        return False
    if a.game_only and ev.kind != 'game':
        return False
    if a.section:
        pool = [norm(x) for x in ([ev.own] if ev.own else []) + ev.trail]
        if not any(norm(s) in p for s in a.section for p in pool):
            return False
    if a.ib:
        want = {h.lower() for h in a.ib}
        have = {(ev.ib or '').lower()} | {inih.hash_of(t) for t in ev.triggers()}
        if not want & have:
            return False
    if a.vs and not (ev.vs or '').lower().startswith(a.vs.lower()):
        return False
    if a.ps and not (ev.ps or '').lower().startswith(a.ps.lower()):
        return False
    if a.draw:
        got = [ev.count, ev.start, ev.base]
        if not any(all(i < 3 and got[i] == w for i, w in enumerate(int(x) for x in spec.split(',') if x.strip()))
                   for spec in a.draw):
            return False
    return True


# Replay a frame log's state changes and emit fully attributed draw events.
def scan(path: str, a, inih: IniHashes):
    """逐行读 log,返回 (命中的事件表, 统计, 段计数, analyse_options 头)。"""
    vs = ps = ib = None
    ps_srv: dict[int, str | None] = {}
    pending_srv = False
    cur = None
    call_secs: list[str] = []
    call_cmds: list[tuple[str, str]] = []
    call_evs: list[Ev] = []
    hits: list[Ev] = []
    stats = collections.Counter()
    sec_count = collections.Counter()
    header = ''

    # Finalize the current call after all state-setting and mod command lines have been seen.
    def flush():
        for ev in call_evs:
            if ev.kind == 'game':
                ev.trail = list(dict.fromkeys(call_secs))
            if matches(ev, a, inih):
                if a.cmds:
                    ev.cmds = [(s, t) for s, t in call_cmds
                               if not a.section or any(norm(x) in norm(s) for x in a.section)]
                hits.append(ev)

    with open(path, 'r', encoding=a.encoding, errors='replace') as f:
        for raw in f:
            raw = raw.rstrip('\r\n')
            m = LINE.match(raw)
            if not m:
                if raw.startswith('analyse_options'):
                    header = raw.split(':', 1)[-1].strip()
                elif pending_srv:
                    sm = SUBLINE.match(raw)
                    if sm:
                        h = HASH.search(sm.group(2))
                        ps_srv[int(sm.group(1))] = h.group(1) if h else None
                continue
            call, text = m.group(1), m.group(2)
            pending_srv = False
            if call != cur:
                flush()
                cur, call_secs, call_cmds, call_evs = call, [], [], []
            if text.startswith('3DMigoto'):
                mm = MIG.match(text)
                if not mm:
                    continue
                sec, rest = mm.group(1), mm.group(2)
                call_secs.append(sec)
                if a.cmds:
                    call_cmds.append((sec, rest))
                if norm(sec).startswith(('textureoverride', 'commandlist', 'customshader', 'shaderoverride')):
                    sec_count[sec] += 1
                dm = DRAWCALL.match(rest)
                if dm:
                    ev = Ev()
                    ev.call, ev.kind, ev.api = call, 'mod', dm.group(1)
                    ev.count, ev.start, ev.base, ev.inst = mod_draw_args(dm.group(1), dm.group(2))
                    ev.ib, ev.vs, ev.ps, ev.own = ib, vs, ps, sec
                    ev.trail = list(dict.fromkeys(call_secs[:-1]))
                    ev.slots = dict(ps_srv) if a.slots else None
                    ev.cmds = None
                    call_evs.append(ev)
                    stats['mod'] += 1
                continue
            if text.startswith('IASetIndexBuffer('):
                h = HASH.search(text)
                ib = h.group(1) if h else None
            elif text.startswith('VSSetShader('):
                h = HASH.search(text)
                vs = h.group(1) if h else None
            elif text.startswith('PSSetShader('):
                h = HASH.search(text)
                ps = h.group(1) if h else None
            elif text.startswith('PSSetShaderResources('):
                sm = PSSRV.match(text)
                if sm:
                    s0, n = int(sm.group(1)), int(sm.group(2))
                    for k in range(s0, s0 + n):
                        ps_srv.pop(k, None)
                    pending_srv = True
            else:
                dm = DRAWCALL.match(text)
                if dm:
                    ev = Ev()
                    ev.call, ev.kind, ev.api = call, 'game', dm.group(1)
                    ev.count, ev.start, ev.base, ev.inst = game_draw_args(dm.group(2))
                    ev.ib, ev.vs, ev.ps, ev.own = ib, vs, ps, None
                    ev.trail = []
                    ev.slots = dict(ps_srv) if a.slots else None
                    ev.cmds = None
                    call_evs.append(ev)
                    stats['game'] += 1
        flush()
    return hits, stats, sec_count, header


# Accept either a dump directory or its log.txt path.
def resolve_log(p: str) -> str:
    if os.path.isdir(p):
        p = os.path.join(p, 'log.txt')
    if not os.path.isfile(p):
        sys.exit(f'找不到 log.txt:{p}')
    return p


# Find the 3DMigoto root near the dump unless the caller supplied one.
def guess_root(log_path: str, given: str | None) -> str | None:
    if given:
        return given if os.path.isdir(given) else None
    d = os.path.dirname(os.path.abspath(log_path))
    for c in (os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
        if os.path.isdir(os.path.join(c, 'Mods')):
            return c
    return None


# Validate filters, scan every log, print matches, and summarize unique shader pairs.
def main():
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='在 3DMigoto 帧转储 log.txt 里按段名 / IB hash / draw 参数找 draw,列出 call 号与 VS / PS hash(只读)。',
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split('\n\n', 2)[1] if __doc__ else None)
    ap.add_argument('dumps', nargs='+', help='转储目录(内含 log.txt)或 log.txt 路径,可给多个(如 LOD0 帧 + LOD1 帧)')
    ap.add_argument('--section', action='append', default=[], help='ini 段名子串,不分大小写,可多次')
    ap.add_argument('--ib', action='append', default=[], help='mod ini 里 TextureOverride 的 hash(8 位),可多次')
    ap.add_argument('--draw', action='append', default=[], help='个数,起点[,基址];例 38925,204684,可多次')
    ap.add_argument('--vs', default='', help='VS hash 前缀')
    ap.add_argument('--ps', default='', help='PS hash 前缀')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--mod-only', action='store_true', help='只看 mod 发的 draw')
    g.add_argument('--game-only', action='store_true', help='只看游戏自己的 draw')
    ap.add_argument('--cmds', action='store_true', help='打出命中 call 里匹配段执行过的命令(看门控 / 绑定)')
    ap.add_argument('--slots', action='store_true', help='打出游戏在该 draw 时绑定的 ps-t 槽贴图 hash')
    ap.add_argument('--max', type=int, default=40, help='每个转储最多打印多少条命中(汇总不受限),默认 40')
    ap.add_argument('--list-sections', action='store_true', help='列出这一帧执行过的 mod 段(可配 --section 过滤)')
    ap.add_argument('--root', default=None, help='3DMigoto 根目录(含 Mods 与 d3dx.ini),--ib 与显示 hash 用;默认自动找')
    ap.add_argument('--encoding', default='utf-8', help='log.txt 编码,默认 utf-8(段名里的中文对不上时试 gbk)')
    a = ap.parse_args()
    if not (a.list_sections or a.section or a.ib or a.draw or a.vs or a.ps):
        ap.error('至少给一个筛选条件(--section / --ib / --draw / --vs / --ps),或用 --list-sections')

    groups = collections.Counter()
    pairs = collections.Counter()
    for d in a.dumps:
        path = resolve_log(d)
        inih = IniHashes(guess_root(path, a.root))
        hits, stats, sec_count, header = scan(path, a, inih)
        name = os.path.basename(os.path.dirname(os.path.abspath(path)))
        print(f'== {name}  (analyse_options: {header or "?"}, {stats["game"]} 次游戏 draw, {stats["mod"]} 次 mod draw, '
              f'ini 根 {inih.root or "未找到:--ib 只能比游戏 IB、不显示段 hash,用 --root 指定"})')
        if not any(norm(s).startswith('textureoverride') for s in sec_count):
            print('   ⚠ 这一帧没有任何 TextureOverride 被触发:可能是没装 mod 的原版帧、mod 被禁用,'
                  '或 d3dx.ini 的 analyse_options 缺 deferred_ctx_immediate(角色 draw 不进 log)。')
        if a.list_sections:
            rows = [(n, s) for s, n in sec_count.items()
                    if not a.section or any(norm(x) in norm(s) for x in a.section)]
            for n, s in sorted(rows, key=lambda r: (-r[0], r[1]))[:80]:
                h = inih.hash_of(s)
                print(f'   {n:5d}  {short(s)}' + (f'  [{h}]' if h else ''))
            if not (a.ib or a.draw or a.vs or a.ps):
                continue
        for i, ev in enumerate(hits):
            if i >= a.max:
                print(f'   … 还有 {len(hits) - a.max} 条未打印(--max 调大)')
                break
            star = '*' if ev.own and norm(ev.own).startswith('customshader') else ''
            line = (f'{ev.call}  {ev.kind:4s} {ev.draw_str():16s}' + (f' x{ev.inst}' if ev.inst else '')
                    + f'  IB {ev.ib or "-"}  VS {ev.vs or "-"}  PS {ev.ps or "-"}{star}')
            if ev.own:
                line += f'  段 {short(ev.own)}'
            for t in ev.triggers()[:2]:
                if t != ev.own:
                    h = inih.hash_of(t)
                    line += f'  ← {short(t)}' + (f' [{h}]' if h else '')
            print(line)
            if a.slots and ev.slots:
                print('        ps-t: ' + '  '.join(f't{k}={v or "null"}' for k, v in sorted(ev.slots.items())))
            if a.cmds and ev.cmds:
                for s, t in ev.cmds[:30]:
                    print(f'        [{short(s)}] {t[:150]}')
                if len(ev.cmds) > 30:
                    print(f'        … 另有 {len(ev.cmds) - 30} 行命令')
        for ev in hits:
            groups[(ev.kind, ev.draw_str(), ev.vs or '-', ev.ps or '-', short(ev.own))] += 1
            pairs[(ev.vs or '-', ev.ps or '-')] += 1
        if not hits:
            print('   (无命中)')

    if groups:
        print('== 汇总:按 类型 / draw / VS / PS / 段 分组')
        print('   次数 类型 draw              VS               PS               段')
        for (kind, dr, v, p, s), n in sorted(groups.items(), key=lambda r: -r[1])[:60]:
            print(f'   {n:4d} {kind:4s} {dr:17s} {v:16s} {p:16s} {s}')
        print(f'== 命中的 draw 共用 {len(pairs)} 种 VS/PS 组合' +
              ('(门控证明:同一目标在 LOD0 / LOD1 两帧都只出现目标 PS)' if len(pairs) == 1 else ''))
        if len(pairs) > 1:
            for (v, p), n in pairs.most_common(12):
                print(f'   VS {v}  PS {p}  : {n} 次')


if __name__ == '__main__':
    main()
