# -*- coding: utf-8 -*-
"""audit_filter_index.py - 跨 mod 的 filter_index 冲突审计(P0 阻断检查)。

用法:
    python audit_filter_index.py "<Mods 根目录>" [--gate "vs == 202"]

**为什么这是 P0**:`filter_index` 不是「模组内部变量」。`[ShaderOverride]` 按
shader hash 命中,作用范围是**整个 3DMigoto 配置**,不是某个角色目录。两个都启用
的 mod 给同一个 hash 打不同的 filter_index 时,`allow_duplicate_hash = overrule`
**不会**让它同时等于两个值 —— 后加载的那个覆盖前一个,于是至少有一边的
`if ps == …` 永远进 else,表现是「效果完全没有,但一切看起来都对」。

这个失败模式在本项目真实发生过(两个角色 mod 在同一个头发 ps hash 上抢标记)。

所以:**接线之前先跑这个;它比编译 HLSL 更早执行。** 有 P0 冲突时不要安装,
更不要去调着色器参数 —— P0 没解决,任何参数都不会显示出来。

本脚本只读,不修改任何文件。它也不会去改别人的 mod:发现冲突时正确的做法是
让**你的** mod 复用已经存在的那个统一值。
"""

from __future__ import annotations

# 输入是 Mods 根目录和可选 gate 表达式；只读取启用中的 INI。
# 输出先给已扫描 INI、按 hash 声明和无 hash ShaderRegex 声明的数量，再列冲突与 gate 来源。
# “P0 冲突”后的数字是被赋予多个不同 filter_index 的 shader hash 数；大于 0 必须先处理。
# gate 结果里的“按 hash / 按 ShaderRegex”数字是该值的定义数量；两者都是 0 时 gate 永远不成立。
# 退出码 0 表示无冲突且所查 gate 可满足；1 表示有冲突或 gate 无定义；2 表示路径或参数错误。

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True   # 别在 skill 目录里留 __pycache__
from discover_fresnel_targets import (  # noqa: E402
    RE_SECTION, as_text, read_lines, is_disabled,
)

RE_HASH = re.compile(r'^\s*hash\s*=\s*([0-9a-fA-F]+)\s*$')
RE_FILTER = re.compile(r'^\s*filter_index\s*=\s*([\d.]+)')
RE_DUP = re.compile(r'^\s*allow_duplicate_hash\s*=\s*(\w+)', re.I)


# Scan enabled INI files and collect every filter_index definition by shader hash and regex.
def scan(root: Path):
    """返回 hash -> {filter_index -> [出处]} 以及 无 hash 的 ShaderRegex 统计。"""
    by_hash = defaultdict(lambda: defaultdict(list))
    regex_filters = defaultdict(list)
    n_ini = 0
    for ini in sorted(root.rglob('*.ini')):
        if is_disabled(ini):
            continue
        try:
            lines, _e, _o = read_lines(ini)
        except OSError:
            continue
        n_ini += 1
        sec = ''
        cur_hash = cur_filter = cur_dup = None

        # Commit one parsed section only after its hash, filter value, and duplicate policy are known.
        def flush():
            if cur_filter is None:
                return
            where = '%s [%s]' % (ini, sec)
            if cur_hash:
                by_hash[cur_hash.lower()][cur_filter].append(
                    (where, cur_dup or '-'))
            else:
                regex_filters[cur_filter].append(where)

        for raw in lines:
            t = as_text(raw)
            m = RE_SECTION.match(t)
            if m:
                flush()
                sec = m.group(1)
                cur_hash = cur_filter = cur_dup = None
                continue
            m = RE_HASH.match(t)
            if m:
                cur_hash = m.group(1)
                continue
            m = RE_FILTER.match(t)
            if m:
                cur_filter = m.group(1)
                continue
            m = RE_DUP.match(t)
            if m:
                cur_dup = m.group(1)
        flush()
    return by_hash, regex_filters, n_ini


# Parse the audit request, print conflict evidence, and return the gate verdict as an exit code.
def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mods_root', nargs='?', default=None,
                    help='3DMigoto 的 Mods 根目录')
    ap.add_argument('--mods-root', dest='mods_root_opt', default=None,
                    help='同上,选项写法 —— 与其他脚本的参数面保持一致')
    ap.add_argument('--gate', default='',
                    help='打算使用的门控表达式,如 "vs == 202" / "ps == 1718.1";'
                         '给了就额外检查这个值能不能站得住')
    args = ap.parse_args()

    if not (args.mods_root or args.mods_root_opt):
        print('ERROR: 需要 Mods 根目录(位置参数或 --mods-root)')
        return 2
    root = Path(args.mods_root_opt or args.mods_root)
    if not root.is_dir():
        print('ERROR: 不是一个目录: %s' % root)
        return 2

    by_hash, regex_filters, n_ini = scan(root)
    print('MODS ROOT : %s' % root.resolve())
    print('已扫描启用中的 ini: %d 个(路径含 DISABLED 的已跳过)' % n_ini)
    print('按 hash 声明 filter_index 的着色器: %d 个' % len(by_hash))
    print('无 hash 的 ShaderRegex filter_index 取值: %s'
          % (', '.join(sorted(regex_filters)) or '(无)'))
    print('-' * 76)

    conflicts = {h: v for h, v in by_hash.items() if len(v) > 1}
    if conflicts:
        print('P0 冲突:%d 个 shader hash 被赋予了**不同**的 filter_index。'
              % len(conflicts))
        print('这些 hash 上,后加载的定义会覆盖先加载的,至少一边静默失效。')
        print()
        for h, vals in sorted(conflicts.items()):
            print('  hash = %s' % h)
            for fv, places in sorted(vals.items()):
                print('    filter_index = %-10s' % fv)
                for where, dup in places:
                    print('        %s   allow_duplicate_hash=%s' % (where, dup))
            print()
        print('处理原则(与 references/main-ps-replacement.md 的「安全替换主 PS」方法论一致):')
        print('  · 只有一个已有值      -> 你的 mod 复用它')
        print('  · 多处定义但值相同    -> 可以继续')
        print('  · 同一 hash 出现不同值 -> P0,禁止安装,先统一')
        print('  · 完全没有定义        -> 才分配新值,分配后再全局搜一遍确认')
        print('不要去改别人的 mod 或改加载器来「解决」冲突。')
    else:
        print('OK: 没有发现「同一 hash 被赋予不同 filter_index」的冲突。')

    if args.gate:
        m = re.match(r'\s*(vs|ps)\s*==\s*([\d.]+)', args.gate.strip())
        if m:
            kind, val = m.group(1), m.group(2)
            print()
            print('门控 `%s` 的可满足性:' % args.gate.strip())
            hash_hits = [(h, places) for h, vals in by_hash.items()
                         for v, places in vals.items() if v == val]
            regex_hits = regex_filters.get(val, [])
            if hash_hits or regex_hits:
                print('  找到 %d 处按 hash、%d 处按 ShaderRegex 声明 filter_index = %s'
                      % (len(hash_hits), len(regex_hits), val))
                for where in regex_hits[:6]:
                    print('    %s' % where)
                if len(regex_hits) > 6:
                    print('    ...(共 %d 处)' % len(regex_hits))
                # 同一个值被多个来源声明本身没问题,危险的是它们打在同一批着色器上
                if len(regex_hits) > 1:
                    print('  注意:多个 ShaderRegex 都产出 %s。若它们匹配到同一个'
                          % val)
                    print('       着色器,按 namespace 字母序**后解析者赢**。门控'
                          '失灵时先查这里。')
            else:
                print('  !! 没有任何启用中的 ini 声明 filter_index = %s。' % val)
                print('     `%s` 永远不成立 —— overlay 一次都不会执行。' % args.gate.strip())
                print('     要么改用别的门控,要么确认提供它的 mod 已启用。')
                return 1
    print('-' * 76)
    return 1 if conflicts else 0


if __name__ == '__main__':
    sys.exit(main())
