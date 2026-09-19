"""Reuse successful DLL compilation only when all compiler inputs still match."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import uuid


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compiler_identity(lib, wrapper):
    """Hash the loaded module, not an assumed DLL search location."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(lib._handle, buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError('无法确认已加载的编译器路径')
    path = Path(buffer.value).resolve()
    return {'path': str(path), 'dll': digest(path.read_bytes()),
            'wrapper': digest(Path(wrapper).read_bytes()),
            'cache': digest(Path(__file__).read_bytes())}


def prepare(folder, src, data, identity, entry, target, defines, flags, flags2):
    """Skip includes and line continuations rather than guess their dependencies."""
    if b'include' in data.lower() or bytes([92, 10]) in data or bytes([92, 13, 10]) in data:
        print('编译缓存: 未复用（含 include 或续行，依赖需重新编译）')
        return None
    macros = list(defines.items()) if isinstance(defines, dict) else defines
    temporal_inputs = data + json.dumps(macros, ensure_ascii=True).encode()
    if any(name in temporal_inputs for name in (b'__DATE__', b'__TIME__', b'__TIMESTAMP__')):
        print('编译缓存: 未复用（含时变预定义宏，需重新编译）')
        return None
    inputs = {'source': digest(data), 'path': str(src), 'cwd': str(Path.cwd().resolve()),
              'compiler': identity, 'entry': entry, 'target': target, 'defines': macros,
              'flags': flags, 'flags2': flags2}
    key = digest(json.dumps(inputs, sort_keys=True, ensure_ascii=True).encode())
    return Path(folder) / (key + '.json'), key


def read(ticket, disassemble):
    """Regenerate assembly from checked bytecode, never trust a cached listing."""
    if ticket is None:
        return None
    path, key = ticket
    try:
        item = json.loads(path.read_text(encoding='utf-8'))
        bytecode = base64.b64decode(item['bytecode'], validate=True)
        if item['key'] != key or item['sha256'] != digest(bytecode):
            raise ValueError('缓存摘要不匹配')
        listing = disassemble(bytecode)
        messages = item['messages']
        if not isinstance(messages, str):
            raise ValueError('缓存消息格式错误')
        print('编译缓存: 命中，复用字节码并重新反汇编')
        return bytecode, listing, messages
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print('编译缓存: 未命中或损坏，重新严格编译')
        return None


def write(ticket, bytecode, messages):
    """Publish one complete entry atomically; cache failures never skip compilation."""
    if ticket is None:
        return
    path, key = ticket
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'key': key, 'sha256': digest(bytecode),
                   'bytecode': base64.b64encode(bytecode).decode('ascii'), 'messages': messages}
        temporary.write_text(json.dumps(payload), encoding='utf-8')
        os.replace(temporary, path)
    except OSError:
        print('编译缓存: 写入失败，本次严格编译结果仍有效')
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
