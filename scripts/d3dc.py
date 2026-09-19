#!/usr/bin/env python3
r"""d3dc.py - 不装 Windows SDK 也能编 HLSL:直接调系统自带的 d3dcompiler_47.dll。

fxc.exe 只是 d3dcompiler_47.dll 的命令行外壳;每台 Windows 10/11 的 C:\Windows\System32\
里都自带这个库(3DMigoto 在游戏里编译 HLSL 用的也是它)。本脚本只用 Python 标准库(ctypes)
调它的 D3DCompile / D3DDisassemble,产物和 fxc 一样:/Fo 的字节码 .bin、/Fc 的反汇编清单
.asm(同格式,reflect_check.py 照常解析)。

用法一:reflect_check.py 找不到 fxc 时自动导入本脚本,调 compile_file()。
用法二:命令行,参数名照搬 fxc,只是把 / 换成 --:
    python d3dc.py <shader.hlsl> --T ps_5_0 [--E main] [--D NAME=VAL ...]
        [--Ges] [--WX] [--Gis] [--Od | --O0 | --O1 | --O2 | --O3]
        [--strict]                 = --Ges --WX --O3(reflect_check.py 的严格档)
        [--Fo out.bin] [--Fc out.asm]
        [--dll PATH]               换一份 d3dcompiler_47.dll(默认系统自带那份)
    不写优化档 = fxc 默认的 /O1;--D 只写名字 = NAME=1(同 fxc)。
    退出码 0 = 编译通过,1 = 编译失败,2 = 用法 / 环境问题。
    错误和警告原样写到 stderr,格式同 fxc:
        <文件>(行,列): error X3004: undeclared identifier 'foo'

说明:
  - 相对 #include 用 D3D_COMPILE_STANDARD_FILE_INCLUDE 解析(源文件所在目录优先,再到当前目录)。
    源文件路径全是 ASCII 时调 D3DCompile,pSourceName 传绝对路径;路径含中文等非 ASCII 字符时
    改调 D3DCompileFromFile(宽字符路径)。原因:pSourceName 是窄字符串,实测 dll 按 UTF-8 解它,
    传本机 ANSI(GBK)编码的中文路径会让相对 #include 报 X1507 找不到文件;宽字符接口没有这个
    歧义。两条路的产物逐字节相同。
  - 报错里的路径按本机 ANSI 代码页输出(表示不了的字符变 ?),和 fxc 一样。
  - 编译失败时不写任何产物。
  - 本脚本和 fxc 的 .bin / .asm 逐字节相同:系统自带的 dll 和 Windows SDK 里 fxc 用的那份版本
    常常不同,但实测 10.0.19041 与 10.0.26100 两代 dll 的产物都和 fxc 一致;将来版本万一有出入,
    也只影响 SHA-256,资源绑定 / cb / 签名不受影响。
"""
# 输入是一份 HLSL、目标 profile、可选 macro 和编译标志；也可作为库接收字节串。
# 输出可写 /Fo 字节码与 /Fc 反汇编，并在 stdout 报 DLL 版本和“编译通过:字节码 N B”。
# N 是产出 bytecode 的字节数；只用于确认确实生成代码和比较异常变化，不代表 shader 更好或更快。
# 编译器警告/错误原样写 stderr。成功退出 0，编译失败退出 1，路径、DLL 或参数问题退出 2。

import argparse
import ctypes
import os
import sys
from collections import namedtuple
from pathlib import Path

# ---------------------------------------------------------------- 常量(d3dcompiler.h)

D3DCOMPILE_SKIP_OPTIMIZATION = 1 << 2                   # /Od
D3DCOMPILE_ENABLE_STRICTNESS = 1 << 11                  # /Ges
D3DCOMPILE_IEEE_STRICTNESS = 1 << 13                    # /Gis
D3DCOMPILE_OPTIMIZATION_LEVEL0 = 1 << 14                # /O0
D3DCOMPILE_OPTIMIZATION_LEVEL1 = 0                      # /O1(fxc 默认)
D3DCOMPILE_OPTIMIZATION_LEVEL2 = (1 << 14) | (1 << 15)  # /O2
D3DCOMPILE_OPTIMIZATION_LEVEL3 = 1 << 15                # /O3
D3DCOMPILE_WARNINGS_ARE_ERRORS = 1 << 18                # /WX
D3D_COMPILE_STANDARD_FILE_INCLUDE = 1                   # (ID3DInclude*)1:库自带的文件 include 处理器

OPT_LEVELS = {'d': D3DCOMPILE_SKIP_OPTIMIZATION, '0': D3DCOMPILE_OPTIMIZATION_LEVEL0,
              '1': D3DCOMPILE_OPTIMIZATION_LEVEL1, '2': D3DCOMPILE_OPTIMIZATION_LEVEL2,
              '3': D3DCOMPILE_OPTIMIZATION_LEVEL3}

# reflect_check.py 给 fxc 的 /Ges /WX /O3
STRICT_FLAGS = D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_WARNINGS_ARE_ERRORS | D3DCOMPILE_OPTIMIZATION_LEVEL3

Result = namedtuple('Result', 'ok hresult messages bytecode listing')
Result.__doc__ = """一次编译的结果。
ok        编译通过(等价于 fxc 退出码 0)
hresult   D3DCompile 的返回值
messages  编译器原话:错误和警告都在里面,格式同 fxc(成功时也可能有警告)
bytecode  字节码 bytes(失败时 None)
listing   反汇编清单文本(只在要求 out_asm 时生成,行尾 \\n)"""


# Represent compiler setup and COM-call failures without losing the original message.
class D3DCompilerError(RuntimeError):
    """d3dcompiler_47.dll 用不了:不是 Windows / 文件不存在 / 加载失败。"""


# Mirror the native macro structure passed to D3DCompile.
class D3D_SHADER_MACRO(ctypes.Structure):
    _fields_ = [('Name', ctypes.c_char_p), ('Definition', ctypes.c_char_p)]


# ---------------------------------------------------------------- 加载 dll

# Resolve the system compiler DLL from the Windows directory.
def system_dll() -> Path:
    """系统自带那份的完整路径(32 位 Python 会被 WOW64 自动重定向到 SysWOW64 里的 32 位版)。"""
    root = os.environ.get('SystemRoot') or os.environ.get('windir') or r'C:\Windows'
    return Path(root) / 'System32' / 'd3dcompiler_47.dll'


_loaded = {}


# Load the compiler DLL and declare the ctypes signatures used by this module.
def load(dll=None):
    """按完整路径加载 d3dcompiler_47.dll,返回 (库, 路径)。

    不走 DLL 搜索顺序,免得捡到当前目录或游戏目录里的同名文件。
    """
    if os.name != 'nt':
        raise D3DCompilerError('d3dcompiler_47.dll 只有 Windows 上有')
    path = Path(dll) if dll else system_dll()
    key = os.path.normcase(str(path))
    if key in _loaded:
        return _loaded[key]
    if not path.is_file():
        raise D3DCompilerError('找不到 %s' % path)
    try:
        lib = ctypes.WinDLL(str(path))
    except OSError as e:
        raise D3DCompilerError('加载 %s 失败:%s' % (path, e))
    P, vp = ctypes.POINTER, ctypes.c_void_p
    lib.D3DCompile.restype = ctypes.c_long
    lib.D3DCompile.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, P(D3D_SHADER_MACRO), vp,
                               ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, P(vp), P(vp)]
    lib.D3DCompileFromFile.restype = ctypes.c_long
    lib.D3DCompileFromFile.argtypes = [ctypes.c_wchar_p, P(D3D_SHADER_MACRO), vp, ctypes.c_char_p,
                                       ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, P(vp), P(vp)]
    lib.D3DDisassemble.restype = ctypes.c_long
    lib.D3DDisassemble.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_char_p, P(vp)]
    _loaded[key] = (lib, path)
    return lib, path


# Read the file version for reproducible compiler diagnostics.
def dll_version(path=None):
    """dll 的文件版本号,如 '10.0.26100.9444';拿不到返回 None。"""
    if os.name != 'nt':
        return None
    path = str(path or system_dll())
    ver = ctypes.WinDLL('version')
    ver.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    ver.GetFileVersionInfoSizeW.restype = ctypes.c_uint
    ver.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = ctypes.c_int
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    ver.VerQueryValueW.restype = ctypes.c_int
    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return None
    p, n = ctypes.c_void_p(), ctypes.c_uint()
    if not ver.VerQueryValueW(buf, '\\', ctypes.byref(p), ctypes.byref(n)) or not p.value:
        return None
    f = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32 * 4)).contents   # VS_FIXEDFILEINFO 前 4 个 DWORD
    ms, ls = f[2], f[3]
    return '%d.%d.%d.%d' % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


# ---------------------------------------------------------------- ID3DBlob(走 vtable)

# vtable 顺序:0 QueryInterface / 1 AddRef / 2 Release / 3 GetBufferPointer / 4 GetBufferSize
_FUNCTYPE = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)
_Release = _FUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_GetBufferPointer = _FUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
_GetBufferSize = _FUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)


# Copy bytes out of an ID3DBlob and release the COM object exactly once.
def _take_blob(blob):
    """拷出 ID3DBlob 的内容并 Release;空指针返回 None。"""
    if not blob.value:
        return None
    vtbl = ctypes.cast(blob, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    try:
        size = _GetBufferSize(vtbl[4])(blob)
        ptr = _GetBufferPointer(vtbl[3])(blob)
        return ctypes.string_at(ptr, size) if size and ptr else b''
    finally:
        _Release(vtbl[2])(blob)


# ---------------------------------------------------------------- 编译 / 反汇编

# Use the narrow API only when the source path is safely representable as ASCII.
def _ascii_name(path):
    """路径全是 ASCII 才直接当 D3DCompile 的 pSourceName;否则返回 None,改走宽字符的 D3DCompileFromFile。

    pSourceName 是窄字符串,实测 dll 按 UTF-8 解它:传本机 ANSI(GBK)编码的中文路径,
    相对 #include 会报 X1507 找不到文件。ASCII 没有编码歧义,宽字符接口也没有。
    """
    try:
        return str(path).encode('ascii')
    except UnicodeEncodeError:
        return None


# Decode compiler diagnostics using Windows-compatible fallbacks.
def _decode(raw):
    """编译器消息里的路径按本机 ANSI 代码页输出(和 fxc 一样),按同一代码页解回来。"""
    if not raw:
        return ''
    raw = raw.rstrip(b'\0')
    try:
        return raw.decode('mbcs', 'replace')
    except LookupError:
        return raw.decode('utf-8', 'replace')


# Build a null-terminated native macro array and keep its backing bytes alive.
def _macros(defines):
    """{'A': '1'} 或 ['A=1', 'B'] -> 以 NULL 结尾的 D3D_SHADER_MACRO 数组;只写名字 = 1(同 fxc /D)。"""
    if not defines:
        return None
    if isinstance(defines, dict):
        pairs = [(str(k), '1' if v is None else str(v)) for k, v in defines.items()]
    else:
        pairs = [tuple(d.split('=', 1)) if '=' in d else (d, '1') for d in defines]
    arr = (D3D_SHADER_MACRO * (len(pairs) + 1))()   # 最后一项保持 {NULL, NULL}
    for i, (k, v) in enumerate(pairs):
        arr[i].Name = k.strip().encode('utf-8')
        arr[i].Definition = v.encode('utf-8')
    return arr


# Convert shader bytecode to Microsoft assembly text through D3DDisassemble.
def disassemble(bytecode, dll=None, flags=0):
    """字节码 -> 与 fxc /Fc 同格式的反汇编清单文本(行尾 \\n)。flags 0 = fxc 的默认格式。"""
    lib, _ = load(dll)
    out = ctypes.c_void_p()
    hr = lib.D3DDisassemble(bytecode, len(bytecode), flags, None, ctypes.byref(out))
    raw = _take_blob(out)
    if hr < 0 or raw is None:
        raise D3DCompilerError('D3DDisassemble 失败,HRESULT 0x%08X' % (hr & 0xFFFFFFFF))
    return raw.rstrip(b'\0').decode('latin-1').replace('\r\n', '\n')


# Compile one HLSL file through the wide or narrow API according to its path encoding.
def compile_file(src, entry='main', target='ps_5_0', defines=None, flags=STRICT_FLAGS, flags2=0,
                 out_bin=None, out_asm=None, dll=None, compile_cache=None):
    """编译一份 HLSL 文件,等价于
        fxc /T <target> /E <entry> [/D ...] <flags> /Fo <out_bin> /Fc <out_asm> <src>

    defines : {'NAME': 'VAL'} 或 ['NAME=VAL', 'NAME'](同 fxc /D)
    flags   : D3DCOMPILE_* 位,默认 STRICT_FLAGS = /Ges /WX /O3
    out_bin / out_asm : 给了才写;编译失败时两者都不写
    返回 Result(ok, hresult, messages, bytecode, listing)。
    """
    lib, _ = load(dll)
    src = Path(src).resolve()
    data = src.read_bytes()
    ticket, cached = None, None
    if compile_cache:
        import compile_cache as cache
        try:
            identity = cache.compiler_identity(lib, __file__)
            ticket = cache.prepare(compile_cache, src, data, identity, entry, target,
                                   defines, flags, flags2)
            cached = cache.read(ticket, lambda code: disassemble(code, dll))
        except (OSError, ValueError, TypeError):
            print('编译缓存: 无法确认编译条件，重新严格编译')
    if cached:
        bytecode, listing, messages = cached
        if out_bin:
            Path(out_bin).write_bytes(bytecode)
        if out_asm:
            Path(out_asm).write_bytes(listing.replace('\n', '\r\n').encode('latin-1'))
        return Result(True, 0, messages, bytecode, listing if out_asm else None)
    macros = _macros(defines)
    code, errs = ctypes.c_void_p(), ctypes.c_void_p()
    e, t = entry.encode('ascii'), target.encode('ascii')
    name = _ascii_name(src)
    if name is not None:
        hr = lib.D3DCompile(data, len(data), name, macros, D3D_COMPILE_STANDARD_FILE_INCLUDE,
                            e, t, flags, flags2, ctypes.byref(code), ctypes.byref(errs))
    else:
        hr = lib.D3DCompileFromFile(str(src), macros, D3D_COMPILE_STANDARD_FILE_INCLUDE,
                                    e, t, flags, flags2, ctypes.byref(code), ctypes.byref(errs))
    bytecode = _take_blob(code)
    messages = _decode(_take_blob(errs))
    ok = hr >= 0 and bytecode is not None
    if not ok and not messages.strip():
        messages = '%s: error: D3DCompile 失败,HRESULT 0x%08X\n' % (src, hr & 0xFFFFFFFF)
    listing = None
    if ok:
        # A concurrent source edit must not publish a result under an older key.
        if ticket and src.read_bytes() == data:
            cache.write(ticket, bytecode, messages)
        if out_asm:
            listing = disassemble(bytecode, dll)
        if out_bin:
            Path(out_bin).write_bytes(bytecode)
        if out_asm:
            Path(out_asm).write_bytes(listing.replace('\n', '\r\n').encode('latin-1'))   # fxc 的 /Fc 是 CRLF
    return Result(ok, hr, messages, bytecode if ok else None, listing)


# ---------------------------------------------------------------- 命令行

# Provide the fxc-like command line and preserve distinct compile and environment exit codes.
def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument('hlsl', help='HLSL 源文件')
    ap.add_argument('--T', dest='target', required=True, metavar='PROFILE', help='目标,如 ps_5_0(同 fxc /T)')
    ap.add_argument('--E', dest='entry', default='main', metavar='NAME', help='入口函数(同 fxc /E),默认 main')
    ap.add_argument('--D', dest='defines', action='append', default=[], metavar='NAME=VAL',
                    help='宏定义,可重复(同 fxc /D)')
    ap.add_argument('--Ges', action='store_true', help='严格模式(同 fxc /Ges)')
    ap.add_argument('--WX', action='store_true', help='警告当错误(同 fxc /WX)')
    ap.add_argument('--Gis', action='store_true', help='IEEE 严格(同 fxc /Gis)')
    og = ap.add_mutually_exclusive_group()
    og.add_argument('--Od', dest='opt', action='store_const', const='d', help='关优化(同 fxc /Od)')
    for lvl in '0123':
        og.add_argument('--O' + lvl, dest='opt', action='store_const', const=lvl,
                        help='优化档 %s(同 fxc /O%s)%s' % (lvl, lvl, ';不写时的默认' if lvl == '1' else ''))
    ap.add_argument('--strict', action='store_true', help='= --Ges --WX --O3,reflect_check.py 的严格档')
    ap.add_argument('--Fo', metavar='FILE', help='字节码输出(同 fxc /Fo)')
    ap.add_argument('--Fc', metavar='FILE', help='反汇编清单输出(同 fxc /Fc)')
    ap.add_argument('--dll', metavar='PATH', help='指定 d3dcompiler_47.dll(默认 %s)' % system_dll())
    a = ap.parse_args(argv)

    flags = OPT_LEVELS[a.opt or ('3' if a.strict else '1')]
    if a.Ges or a.strict:
        flags |= D3DCOMPILE_ENABLE_STRICTNESS
    if a.WX or a.strict:
        flags |= D3DCOMPILE_WARNINGS_ARE_ERRORS
    if a.Gis:
        flags |= D3DCOMPILE_IEEE_STRICTNESS
    src = Path(a.hlsl)
    if not src.is_file():
        print('d3dc: 源文件不存在:%s' % src, file=sys.stderr)
        return 2
    try:
        _, path = load(a.dll)
    except D3DCompilerError as e:
        print('d3dc: %s' % e, file=sys.stderr)
        return 2
    print('d3dcompiler: %s(%s)' % (path, dll_version(path) or '版本未知'))
    r = compile_file(src, entry=a.entry, target=a.target, defines=a.defines, flags=flags,
                     out_bin=a.Fo, out_asm=a.Fc, dll=a.dll)
    if r.messages.strip():
        print(r.messages.rstrip(), file=sys.stderr)
    if not r.ok:
        print('\ncompilation failed; no code produced', file=sys.stderr)   # 同 fxc 的收尾
        return 1
    print('编译通过:字节码 %d B%s%s' % (len(r.bytecode),
                                      (';--Fo -> %s' % a.Fo) if a.Fo else '',
                                      (';--Fc -> %s' % a.Fc) if a.Fc else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
