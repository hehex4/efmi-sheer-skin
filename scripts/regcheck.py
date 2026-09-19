#!/usr/bin/env python3
"""regcheck.py - 寄存器覆写核查(只读)。

列出 3DMigoto 转储(或替换 PS)的 `main()` 里,指定行区间内对某个寄存器分量的**全部写入**。
用来证明「赋值行 → 捕获行」之间没有人再改这个寄存器(捕获进局部变量之后就不怕后面改了)
—— 变量映射表里每一格都该附这份证据。

用法:
    python regcheck.py <转储.txt> <寄存器.分量> <起始行> <结束行> [<寄存器.分量> <起始行> <结束行> ...]
示例:
    python regcheck.py dump.txt r17.xyz 1133 1316 r12.yzw 1104 1310 r2.xyz 142 1310

分量按集合判:查 r17.xyz 时,`r17.x = ...`、`r17.xyz = ...`、`r17 = ...` 都算命中,`r17.w = ...` 不算。
只扫 `main()` 正文;末尾块注释里的反汇编不参与。退出码:任一区间有写入 → 1,全部干净 → 0。
"""
# 输入是一份 HLSL 和一组“寄存器.分量 起始行 结束行”；脚本只读 main() 正文。
# 每段标题的范围会截到 main() 结尾，“写入:N 处”就是捕获后会破坏该寄存器值的赋值数量。
# N 为 0 才是干净区间；非 0 时下面每行的数字是源文件行号，需移动捕获点或改用别的寄存器。
# 全部区间干净退出 0；任一区间有写入退出 1；参数数量或格式错误打印本说明并退出 2。

import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


# Decode shader text with the encodings commonly emitted by Windows tools.
def read_lines(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc).split('\n')
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1').split('\n')


# Find the closing brace of main so embedded assembly comments stay outside the scan.
def main_end(lines):
    """main() 之后第一条以 /* 开头的行 = 反汇编块注释开始;没有就到文件尾。"""
    seen_main = False
    for i, l in enumerate(lines, 1):
        s = l.lstrip()
        if not seen_main and s.startswith('void main'):
            seen_main = True
        elif seen_main and s.startswith('/*'):
            return i - 1
    return len(lines)


# Report all component-overlapping writes in each requested source interval.
def main():
    if len(sys.argv) < 5 or (len(sys.argv) - 2) % 3:
        print(__doc__)
        return 2
    lines = read_lines(sys.argv[1])
    end = main_end(lines)
    args = sys.argv[2:]
    dirty = 0
    for k in range(0, len(args), 3):
        spec, lo, hi = args[k], int(args[k + 1]), int(args[k + 2])
        reg, _, comps = spec.partition('.')
        want = set(comps) if comps else set('xyzw')
        pat = re.compile(r'^\s*' + re.escape(reg) + r'(?:\.([xyzw]+))?\s*=')
        hits = []
        for n in range(lo, min(hi, end) + 1):
            m = pat.match(lines[n - 1])
            if m and (set(m.group(1) or 'xyzw') & want):
                hits.append((n, lines[n - 1].strip()))
        print('== %s 在 %d..%d 行内的写入:%d 处 ==' % (spec, lo, min(hi, end), len(hits)))
        for n, t in hits:
            print('  %d: %s' % (n, t))
        dirty += len(hits)
    print('结果:%s' % ('全部干净' if dirty == 0 else '有写入,捕获点或区间要重定'))
    return 0 if dirty == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
