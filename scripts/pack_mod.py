# -*- coding: utf-8 -*-
"""pack_mod.py —— 把做好的透肉 mod 打成一个 zip,默认放进用户的「下载」文件夹。原 mod 文件夹一个字节都不动。

用法:
    python pack_mod.py --src <原 mod 文件夹> [--overlay <改动目录>]... [--name <zip 与顶层文件夹名>] [--out <目录或 .zip 路径>]
                       [--exclude <通配符>]... [--dry-run]

怎么组:zip 里只有一个顶层文件夹 <name>/,内容 = 原 mod 的全部文件,再用 --overlay 目录里的同相对路径文件**覆盖 / 新增**
(改过的 ini、res/sheer/*.hlsl、Textures/SheerSkin_*.dds 就放在 overlay 里,相对路径和 mod 里一致)。
这样不用复制几百 MB 的原 mod,也不会把工作目录里的中间产物带进去。

默认:<name> = 原文件夹名去掉 DISABLED_ 前缀再加 " Sheer";输出到「下载」(Windows 从注册表读真实位置,搬过家的也对;
其它系统 ~/Downloads);同名已存在就加 (2)、(3),不覆盖。.dds / .buf / .bin / .png 直接存储不压缩(本来就压过),文本才 deflate。
打完单次读回核对 CRC、全部条目与源字节/总字节，不另跑重复 ZIP 检查。不记 sha256、不写清单文件。

依赖:标准库。
"""
from __future__ import annotations

# 输入是原 mod 目录和零个或多个 overlay；后给的 overlay 对同一相对路径优先。
# 输出一个顶层目录结构完整的 zip；--dry-run 只列计划路径，不创建 zip。
# “文件 N 个、M MB”是最终条目数与未压缩源文件总量；“覆盖/新增”只统计来自 overlay 的变化。
# 完成行中的 zip 大小是压缩后体积，“N 个文件”必须与前面的预期条目数一致，CRC 自检还必须无坏条目。
# 成功或 dry-run 退出 0；路径错误、99 个候选名都占用或 zip 自检失败时退出非 0。

import argparse
import fnmatch
import os
import sys
import zipfile
from pathlib import Path

STORED_EXT = {'.dds', '.buf', '.bin', '.png', '.jpg', '.zip', '.7z', '.rar', '.mp4', '.ogg'}
DEFAULT_EXCLUDE = ['*.bak', '*.bak_*', '__pycache__', '*.pyc', 'Thumbs.db', 'desktop.ini', '*.tmp']


# Resolve the user's actual Downloads folder, including redirected Windows profiles.
def downloads_dir() -> Path:
    """The user's real Downloads folder (Windows shell folder from the registry, else ~/Downloads)."""
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
                val, _ = winreg.QueryValueEx(k, '{374DE290-123F-4565-9164-39C4925E467B}')
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
        except OSError:
            pass
    p = Path.home() / 'Downloads'
    return p if p.is_dir() else Path.home()


# Match exclusion patterns against both the relative path and its individual names.
def excluded(rel: Path, patterns) -> bool:
    return any(fnmatch.fnmatch(part, pat) for part in rel.parts for pat in patterns)


# Choose a free output name without overwriting an existing archive.
def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 100):
        q = path.with_name(f'{path.stem} ({n}){path.suffix}')
        if not q.exists():
            return q
    sys.exit(f'{path} 及其 (2)–(99) 都已存在')


# Merge source and overlay inventories, then dry-run or create and verify the archive.
def verify_archive(path, name, files, expected_total):
    """Read each entry once for CRC and source comparison without loading whole textures."""
    total = 0
    with zipfile.ZipFile(path) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        expected = {f'{name}/{rel}': source for rel, source in files.items()}
        if len(entries) != len(expected) or {info.filename for info in entries} != set(expected):
            raise ValueError('条目名称或数量与源文件不一致')
        for info in entries:
            with archive.open(info) as packed, expected[info.filename].open('rb') as source:
                while True:
                    chunk = packed.read(1024 * 1024)
                    original = source.read(1024 * 1024)
                    if chunk != original:
                        raise ValueError(f'源字节不一致: {info.filename}')
                    total += len(chunk)
                    if not chunk:
                        break
        if total != expected_total:
            raise ValueError(f'总字节不一致: {total} / {expected_total}')
    return len(entries), total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', required=True, help='原 mod 文件夹(含 ini 的那层或它的上级,原样进 zip)')
    ap.add_argument('--overlay', action='append', default=[], help='改动目录:同相对路径的文件覆盖 / 新增;可多个,后者优先')
    ap.add_argument('--name', help='zip 名 = 顶层文件夹名;默认 原名去 DISABLED_ + " Sheer"')
    ap.add_argument('--out', help='输出目录或 .zip 完整路径;默认用户的「下载」')
    ap.add_argument('--exclude', action='append', default=[], help=f'额外排除的通配符(默认已排 {", ".join(DEFAULT_EXCLUDE)})')
    ap.add_argument('--dry-run', action='store_true', help='只列清单不写 zip')
    a = ap.parse_args()

    src = Path(a.src)
    if not src.is_dir():
        sys.exit(f'--src 不是文件夹:{src}')
    overlays = [Path(o) for o in a.overlay]
    for o in overlays:
        if not o.is_dir():
            sys.exit(f'--overlay 不是文件夹:{o}')
    patterns = DEFAULT_EXCLUDE + a.exclude
    name = a.name
    if not name:
        base = src.name
        for pre in ('DISABLED_', 'DISABLED ', 'disabled_'):
            if base.startswith(pre):
                base = base[len(pre):]
        name = base if base.endswith(' Sheer') else base + ' Sheer'
    if a.out and a.out.lower().endswith('.zip'):
        out = Path(a.out)
    else:
        out = (Path(a.out) if a.out else downloads_dir()) / f'{name}.zip'
    out = unique(out)

    # relative path -> source file; overlays win, later overlays win over earlier ones
    files: dict[str, Path] = {}
    for p in sorted(src.rglob('*')):
        if p.is_file():
            rel = p.relative_to(src)
            if not excluded(rel, patterns):
                files[rel.as_posix()] = p
    replaced, added = [], []
    for o in overlays:
        for p in sorted(o.rglob('*')):
            if p.is_file():
                rel = p.relative_to(o).as_posix()
                if excluded(Path(rel), patterns):
                    continue
                (replaced if rel in files else added).append(rel)
                files[rel] = p
    total = sum(p.stat().st_size for p in files.values())

    print(f'顶层文件夹 / zip 名:{name}')
    print(f'文件 {len(files)} 个,{total / 1048576:.1f} MB;来自 overlay:覆盖 {len(replaced)}、新增 {len(added)}')
    for r in replaced:
        print(f'  覆盖  {r}')
    for r in added:
        print(f'  新增  {r}')
    if not replaced and not added and overlays:
        print('  ⚠ overlay 里没有任何文件进包 —— 相对路径是不是和 mod 里的不一致?')
    if a.dry_run:
        print(f'(dry-run)将写到:{out}')
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w') as z:
        for rel, p in files.items():
            method = zipfile.ZIP_STORED if p.suffix.lower() in STORED_EXT else zipfile.ZIP_DEFLATED
            z.write(p, f'{name}/{rel}', compress_type=method)
    try:
        n, checked_bytes = verify_archive(out, name, files, total)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        sys.exit(f'⚠ zip 自检失败: {exc}')
    print(f'单次读回: CRC、条目及源字节一致，共 {checked_bytes} 源字节；无需另跑同项 ZIP 检查')
    print(f'写好:{out}  ({out.stat().st_size / 1048576:.1f} MB,{n} 个文件,自检通过)')
    print('安装:解压得到一个文件夹,放进 <Mods 根>\\character\\<角色>\\;原版文件夹改名加 DISABLED_ 前缀(或在 mod 管理器里停用);完全重启游戏。')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main())
