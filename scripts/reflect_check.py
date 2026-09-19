#!/usr/bin/env python3
"""reflect_check.py - 替换像素着色器的「严格编译 + 反射对照」静态门。

把「替换 PS」和「原 PS(3DMigoto 转储)」放在一起检查,回答模板方法论里最容易被跳过的
几个问题:编译真的过了吗、没打开的开关分支里有没有藏错、贴图/采样器/常量缓冲的声明
和原 PS 一不一样、有没有越界读 cb、mod 注入的高槽(t70/t71/t72)到底有没有被读到。

用法:
    python reflect_check.py <replacement.hlsl> --original <原PS转储.txt 或 .hlsl>
        [--matrix ANISO_DEBUG_MODE=0,1,2,3,4,5,6]     开关矩阵,全部组合都编译一遍
        [--require t70 t71 t72]                      替换 PS 反射里必须出现的槽(自动视为允许多出)
        [--allow-extra t60 t61]                      其他允许替换 PS 比原 PS 多出的槽
        [--allow-missing]                            允许替换 PS 比原 PS 少声明(默认 FAIL)
        [--compiler auto|fxc|d3dcompiler]            用哪个编译器,默认 auto(见下)
        [--out DIR] [--json report.json] [--fxc PATH] [--model ps_5_0] [--entry main]

只读输入;产物(bin / asm)只写到 --out(默认系统临时目录)。退出码 0 = 全绿。

编译器(--compiler):
    auto         默认。先找 fxc.exe(--fxc 显式指定 > Windows SDK 标准位置);找不到就改用系统
                 自带的 C:\\Windows\\System32\\d3dcompiler_47.dll,输出里会写一句
                 「没找到 fxc,改用系统 d3dcompiler_47.dll」。不装 Windows SDK 也能跑。
    fxc          只用 fxc.exe,找不到就报错退出。
    d3dcompiler  只用系统 d3dcompiler_47.dll(忽略 --fxc)。
fxc.exe 本身就是 d3dcompiler_47.dll 的命令行外壳(3DMigoto 在游戏里编译 HLSL 用的也是这个库)。
走 dll 时由同目录的 d3dc.py 用 ctypes 直接调 D3DCompile / D3DDisassemble,标志位同样是
/Ges /WX /O3,产出同格式的 bin / asm,错误 / 警告原话照搬,所以各项检查和判定与 fxc 一样。
系统 dll 和 SDK 里 fxc 用的那份版本常常不同,但实测 10.0.19041 / 10.0.26100 两代 dll 编出的 bin
与 fxc 逐字节相同;将来版本万一有出入,也只是 bin 的 SHA-256 变了,不影响任何检查项。

fxc.exe 来自 Windows SDK,常见位置:
    C:\\Program Files (x86)\\Windows Kits\\10\\bin\\<版本>\\x64\\fxc.exe
"""
# 输入是替换 PS 和原 PS，可选 macro 矩阵、允许/必需资源槽、编译器与输出目录。
# 输出 C1–C7 的逐项 PASS/FAIL、编译产物和可选 JSON；临时目录只在未指定 --out 时使用。
# “指令数”仅作异常变化提示，编译器优化会浮动；资源/采样器/cb 数量必须结合每项 PASS 判读。
# 最后“结果:全绿(N 项检查,0 项失败)”才允许进入下一步；任何失败数大于 0 都要按对应 C 项处理。
# 成功退出 0；静态门有失败退出 1；缺文件、macro 格式或编译器环境错误退出非 0。

import argparse
import glob
import hashlib
import itertools
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

FXC_PATTERNS = [
    r'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\fxc.exe',
    r'C:\Program Files (x86)\Windows Kits\10\bin\x64\fxc.exe',
    r'C:\Program Files\Windows Kits\10\bin\*\x64\fxc.exe',
]

DCL_RE = re.compile(r'^\s*(dcl_\w+)\b(.*)$')
CB_IMM_RE = re.compile(r'\bcb(\d+)\[(\d+)\]', re.I)
INSTR_COUNT_RE = re.compile(r'Approximately (\d+) instruction slots used')


# Search installed Windows SDK versions for the newest fxc executable.
def find_fxc():
    for pat in FXC_PATTERNS:
        hits = sorted(glob.glob(pat))
        if hits:
            return Path(hits[-1])
    return None


# Hash an input or output file for reproducible evidence.
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Decode shader text across common Windows and UTF encodings.
def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


# ---------------------------------------------------------------- 反射解析

# Parse resource declarations, constant-buffer bounds, signatures, and instruction counts.
def parse_decls(asm_text: str) -> dict:
    """从反汇编文本里抽出全部 dcl_* 声明,按类别整理。"""
    d = {'res': {}, 'samp': {}, 'cb': {}, 'in': [], 'out': [], 'other': [],
         'cb_max_imm': {}, 'instr': None}
    for line in asm_text.splitlines():
        m = DCL_RE.match(line)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            if kind.startswith('dcl_resource') or kind.startswith('dcl_uav'):
                reg = re.search(r'\b([tu]\d+)\b', rest)
                if reg:
                    d['res'][reg.group(1)] = '%s %s' % (kind, rest)
            elif kind == 'dcl_sampler':
                reg = re.search(r'\b(s\d+)\b', rest)
                if reg:
                    d['samp'][reg.group(1)] = rest
            elif kind == 'dcl_constantbuffer':
                m2 = re.search(r'\b(cb\d+)\[(\d+)\]', rest, re.I)
                if m2:
                    d['cb'][m2.group(1).lower()] = (int(m2.group(2)), 'dynamicIndexed' in rest)
            elif kind.startswith('dcl_input'):
                d['in'].append('%s %s' % (kind, rest))
            elif kind.startswith('dcl_output'):
                d['out'].append('%s %s' % (kind, rest))
            else:
                d['other'].append('%s %s' % (kind, rest))
            continue
        # 普通指令行:统计 cb 立即索引的最大值
        if line.lstrip().startswith('//'):
            mc = INSTR_COUNT_RE.search(line)
            if mc:
                d['instr'] = int(mc.group(1))
            continue
        for mc in CB_IMM_RE.finditer(line):
            key = 'cb' + mc.group(1)
            idx = int(mc.group(2))
            if idx > d['cb_max_imm'].get(key, -1):
                d['cb_max_imm'][key] = idx
    return d


# Extract the declaration-bearing assembly tail from a 3DMigoto text dump.
def embedded_asm(text: str):
    """3DMigoto 的 *_replace.txt 末尾有块注释包住的原始反汇编;有就返回那一段。"""
    if not re.search(r'^\s*dcl_', text, re.M):
        return None
    # 取第一条 dcl_ 到文件末尾;够反射解析用
    m = re.search(r'^\s*dcl_', text, re.M)
    return text[m.start():]


# ---------------------------------------------------------------- 编译

# Replace exactly one definition per matrix macro before compiling a variant.
def patch_defines(src: str, overrides: dict) -> str:
    for name, val in overrides.items():
        pat = re.compile(r'^(\s*#define\s+%s)\s+\S+' % re.escape(name), re.M)
        src, n = pat.subn(r'\g<1> %s' % val, src)
        if n != 1:
            raise SystemExit('源文件里 `#define %s` 出现 %d 次(需要恰好 1 次)' % (name, n))
    return src


# Import the companion D3D compiler wrapper from this script directory.
def load_d3dc():
    """导入同目录的 d3dc.py(系统 d3dcompiler_47.dll 的 ctypes 封装);缺文件返回 None。"""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # 别在 skill 目录里留 __pycache__
    try:
        import d3dc
        return d3dc
    except ImportError:
        return None
    finally:
        sys.dont_write_bytecode = old


# Select the requested compiler route and report the exact executable or DLL used.
def pick_compiler(choice: str, fxc_arg):
    """按 --compiler / --fxc 选编译器。返回 (fxc 路径或 None, 表头说明行);None = 走系统 dll。"""
    notes = []
    if choice != 'd3dcompiler':
        fxc = Path(fxc_arg) if fxc_arg else find_fxc()
        if fxc and fxc.exists():
            return fxc, ['fxc        : %s' % fxc]
        if choice == 'fxc':
            raise SystemExit('本机没找到 fxc.exe(Windows SDK 组件)。装了 SDK 的话用 --fxc 指定路径;'
                             '没装就去掉 --compiler fxc,脚本会改用系统自带的 d3dcompiler_47.dll。')
        if fxc_arg:
            notes.append('fxc        : --fxc 指定的路径不存在:%s' % fxc_arg)
        notes.append('fxc        : 没找到 fxc,改用系统 d3dcompiler_47.dll')
    elif fxc_arg:
        notes.append('fxc        : --compiler d3dcompiler,忽略 --fxc')
    d3dc = load_d3dc()
    if d3dc is None:
        raise SystemExit('没有 fxc,同目录也缺 d3dc.py,没法编译。')
    try:
        _, dll = d3dc.load()
    except d3dc.D3DCompilerError as e:
        raise SystemExit('没有 fxc,系统 d3dcompiler_47.dll 也用不了:%s' % e)
    notes.append('编译器     : %s(%s,经 d3dc.py 直接调用)' % (dll, d3dc.dll_version(dll) or '版本未知'))
    return None, notes


# Compile one source file and produce both bytecode and assembly for reflection checks.
def compile_hlsl(fxc, src: Path, out_bin: Path, out_asm: Path, model: str, entry: str, compile_cache=None):
    """严格编译(/Ges /WX /O3)并写 bin / asm,返回 (是否通过, 编译器输出)。

    fxc = fxc.exe 路径;传 None 就走系统 d3dcompiler_47.dll(d3dc.py),返回格式相同。
    """
    if fxc is None:
        d3dc = load_d3dc()
        if d3dc is None:
            raise SystemExit('没有 fxc,同目录也缺 d3dc.py,没法编译。')
        try:
            r = d3dc.compile_file(src, entry=entry, target=model, flags=d3dc.STRICT_FLAGS,
                                  out_bin=out_bin, out_asm=out_asm, compile_cache=compile_cache)
        except d3dc.D3DCompilerError as e:
            raise SystemExit('系统 d3dcompiler_47.dll 用不了:%s' % e)
        log = r.messages.strip()
        if not r.ok:   # 收尾和 fxc 的输出一致
            log = (log + '\n\n' if log else '') + 'compilation failed; no code produced'
        return r.ok, log
    if compile_cache:
        print('编译缓存: fxc 实际 DLL 身份无法可靠追踪，本次重新严格编译')
    cmd = [str(fxc), '/nologo', '/T', model, '/E', entry, '/Ges', '/WX', '/O3',
           '/Fo', str(out_bin), '/Fc', str(out_asm), str(src)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- 主流程

# Run fidelity, strict compilation, macro matrix, and reflection comparisons in order.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('replacement', nargs='?', help='替换 PS(.hlsl);--fidelity-only 时可省略')
    ap.add_argument('--original', required=True, help='原 PS:3DMigoto 转储 txt 或 hlsl')
    ap.add_argument('--fidelity-only', action='store_true',
                    help='只做原 PS 转储的忠实性判定(原文严格编译 + 反射来源),不需要替换 PS')
    ap.add_argument('--matrix', nargs='*', default=[], help='NAME=v1,v2 ... 全组合编译')
    ap.add_argument('--require', nargs='*', default=[], help='替换 PS 必须反射出的资源槽,如 t70 t71 t72')
    ap.add_argument('--allow-extra', nargs='*', default=[], help='允许比原 PS 多出的资源/采样器槽')
    ap.add_argument('--allow-missing', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('--json')
    ap.add_argument('--fxc', help='fxc.exe 路径;不给就在 Windows SDK 标准位置找')
    ap.add_argument('--compiler', choices=('auto', 'fxc', 'd3dcompiler'), default='auto',
                    help='auto(默认)= 有 fxc 用 fxc,找不到改用系统 d3dcompiler_47.dll;'
                         'fxc / d3dcompiler = 强制只用这一个')
    ap.add_argument('--model', default='ps_5_0')
    ap.add_argument('--entry', default='main')
    ap.add_argument('--compile-cache', help='复用同目录、同内容、同编译条件的成功字节码')
    args = ap.parse_args()

    if not args.replacement and not args.fidelity_only:
        raise SystemExit('缺少替换 PS 路径;只想判转储忠实性请加 --fidelity-only')
    repl = Path(args.replacement).resolve() if args.replacement else None
    orig = Path(args.original).resolve()
    if (repl and not repl.exists()) or not orig.exists():
        raise SystemExit('文件不存在:%s / %s' % (repl, orig))
    fxc, compiler_notes = pick_compiler(args.compiler, args.fxc)   # fxc 为 None = 走系统 dll
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix='reflect_check_'))
    out.mkdir(parents=True, exist_ok=True)

    results = []

    # Append one named verdict and print the same status immediately.
    def check(name, ok, detail=''):
        results.append({'check': name, 'ok': bool(ok), 'detail': detail})
        print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' -- ' + detail) if detail else ''))

    for line in compiler_notes:
        print(line)
    print('替换 PS    : %s' % (repl or '(无,--fidelity-only)'))
    print('原 PS      : %s' % orig)
    print('产物目录   : %s' % out)
    if repl:
        print('SHA-256 替换 PS 源 : %s' % sha256(repl))
    print('SHA-256 原 PS 文件 : %s' % sha256(orig))
    print()

    # ---- C1 原 PS 的声明:优先用转储自带的原始反汇编,没有就编译一遍
    print('C1 原 PS 反射来源')
    orig_text = read_text(orig)
    asm = embedded_asm(orig_text)
    if asm:
        orig_decl = parse_decls(asm)
        check('C1 原 PS 声明取自转储内嵌的原始反汇编', True, '%d 资源 / %d 采样器 / %d cb'
              % (len(orig_decl['res']), len(orig_decl['samp']), len(orig_decl['cb'])))
    else:
        ok, log = compile_hlsl(fxc, orig, out / 'original.bin', out / 'original.asm', args.model, args.entry, args.compile_cache)
        if not ok:
            check('C1 原 PS 严格编译(转储无内嵌反汇编,只能重编译)', False, log.splitlines()[0] if log else '')
            print('     提示:3DMigoto 反编译产物常见的一处非法转换是 `#define cmp -` 导致的')
            print('     (uint)(-1.0) 字面量(X4115)。对照 asm 的 bfi/lt 指令改成 `cond ? 1u : 0u`。')
            orig_decl = None
        else:
            orig_decl = parse_decls(read_text(out / 'original.asm'))
            check('C1 原 PS 严格编译并反射', True)

    # 顺手报告:原转储本身能不能严格编译(反编译忠实性判定,只报告不判定)
    ok_o, log_o = compile_hlsl(fxc, orig, out / 'original_strict.bin', out / 'original_strict.asm', args.model, args.entry, args.compile_cache)
    print('     原 PS 原文严格编译:%s%s' % ('通过' if ok_o else '失败', '' if ok_o else ' -> ' + (log_o.splitlines()[0] if log_o else '')))
    if not ok_o:
        print('     (失败不算错,只说明反编译产物需要一处忠实修补后才能当替换 PS 的底子)')
        print('     常见的一处:X4115 (uint)(-1.0),来自 `#define cmp -`;按 E1 忠实修法改')
    print()
    if args.fidelity_only:
        check('F 原 PS 原文严格编译(忠实性)', ok_o, '' if ok_o else '修补后再跑一次,通过才算底子干净')
        return finish(results, args.json, out)

    # ---- C2 出厂档严格编译 + 反射
    print('C2 替换 PS 出厂档严格编译(/Ges /WX /O3)')
    ok, log = compile_hlsl(fxc, repl, out / 'replacement.bin', out / 'replacement.asm', args.model, args.entry, args.compile_cache)
    check('C2 出厂档编译', ok, '' if ok else (log.splitlines()[0] if log else ''))
    if not ok:
        print(log)
        finish(results, args.json, out)
        return 1
    repl_decl = parse_decls(read_text(out / 'replacement.asm'))
    print('     bin SHA-256: %s  (%d B)' % (sha256(out / 'replacement.bin'), (out / 'replacement.bin').stat().st_size))
    print()

    # ---- C3 开关矩阵
    if args.matrix:
        print('C3 开关矩阵全组合编译')
        names, values = [], []
        for item in args.matrix:
            if '=' not in item:
                raise SystemExit('--matrix 项格式应为 NAME=v1,v2:%s' % item)
            n, v = item.split('=', 1)
            names.append(n.strip())
            values.append([x.strip() for x in v.split(',') if x.strip()])
        src = read_text(repl)
        fails = 0
        for combo in itertools.product(*values):
            overrides = dict(zip(names, combo))
            tag = '_'.join('%s%s' % (k, v) for k, v in overrides.items())
            tmp = out / ('matrix_%s.hlsl' % tag)
            tmp.write_text(patch_defines(src, overrides), encoding='utf-8')
            ok, log = compile_hlsl(fxc, tmp, out / ('matrix_%s.bin' % tag), out / ('matrix_%s.asm' % tag), args.model, args.entry, args.compile_cache)
            size = (out / ('matrix_%s.bin' % tag)).stat().st_size if ok else 0
            print('     %-40s %s %s' % (tag, 'PASS' if ok else 'FAIL', ('%d B' % size) if ok else (log.splitlines()[0] if log else '')))
            fails += 0 if ok else 1
        check('C3 矩阵 %d 组合' % len(list(itertools.product(*values))), fails == 0, '失败 %d' % fails)
        print()

    # ---- C4~C7 反射对照
    print('C4-C7 反射对照(替换 PS vs 原 PS)')
    if orig_decl is None:
        check('C4 反射对照', False, '原 PS 没有可用的声明来源')
    else:
        allow_extra = set(args.allow_extra) | set(args.require)
        for cat, label in (('res', '资源槽 t#/u#'), ('samp', '采样器 s#')):
            o, r = set(orig_decl[cat]), set(repl_decl[cat])
            missing, extra = sorted(o - r), sorted(r - o)
            bad_extra = [x for x in extra if x not in allow_extra]
            detail = []
            if missing:
                detail.append('少了 %s' % ','.join(missing))
            if extra:
                detail.append('多了 %s' % ','.join(extra))
            ok = (not missing or args.allow_missing) and not bad_extra
            check('C4 %s 集合' % label, ok, '; '.join(detail) if detail else '完全一致(%d)' % len(o))
            # 同名槽的类型也要一致(Texture2D vs Texture3D / structured)
            for k in sorted(o & r):
                if orig_decl[cat][k] != repl_decl[cat][k]:
                    check('C4 %s 类型一致' % k, False, '%s != %s' % (orig_decl[cat][k], repl_decl[cat][k]))
        # cb 声明 + 越界
        o, r = orig_decl['cb'], repl_decl['cb']
        same = set(o) == set(r) and all(o[k][0] == r[k][0] for k in o)
        check('C5 常量缓冲声明一致', same, ', '.join('%s[%d]' % (k, r[k][0]) for k in sorted(r, key=lambda x: int(x[2:]))))
        for k in sorted(r, key=lambda x: int(x[2:])):
            size, dyn = r[k]
            mx = repl_decl['cb_max_imm'].get(k, -1)
            check('C5 %s 立即索引最高 %d < 声明 %d' % (k, mx, size), mx < size,
                  '动态索引,只查立即值' if dyn else '')
        check('C6 输入签名一致', orig_decl['in'] == repl_decl['in'],
              '' if orig_decl['in'] == repl_decl['in'] else '原 %d 项 / 替换 %d 项' % (len(orig_decl['in']), len(repl_decl['in'])))
        check('C7 输出签名一致', orig_decl['out'] == repl_decl['out'], ', '.join(repl_decl['out']))
    for reg in args.require:
        check('C8 必须反射出 %s' % reg, reg in repl_decl['res'] or reg in repl_decl['samp'],
              '' if reg in repl_decl['res'] else '未声明或被优化掉:只在 HLSL 里写了不算,得真的采样')
    if repl_decl.get('instr') is not None or (orig_decl and orig_decl.get('instr') is not None):
        oi = orig_decl.get('instr') if orig_decl else None
        print('     指令数:原 %s / 替换 %s(仅参考,编译器优化会让它浮动;3DMigoto 转储里常写 0)'
              % (oi if oi else '?', repl_decl.get('instr')))
    print()
    return finish(results, args.json, out)


# Print the aggregate verdict, write optional JSON, and return the failure status.
def finish(results, json_path, out):
    fails = [r for r in results if not r['ok']]
    print('=' * 60)
    print('结果:%s(%d 项检查,%d 项失败)' % ('全绿' if not fails else '有失败', len(results), len(fails)))
    if json_path:
        Path(json_path).write_text(json.dumps({'results': results, 'out_dir': str(out)}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('JSON:%s' % json_path)
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
