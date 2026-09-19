#!/usr/bin/env python3
"""Check the supported step-09 wiring and every formal shader without editing files.

输入: overlay INI、所有正式 PS、preview v2 颜色报告、A/B/C 路线、外观下标。
输出: 错误编号及修复动作、按绑定声明分组的反射代表。退出 0=静态接线通过，
1=不通过/无法证明，2=输入缺失。仍需每组正式反射及实机检查，不证明游戏效果。
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys


def compiled_bindings(path, compile_cache=None):
    """Strictly compile each state and inspect resources retained after optimization."""
    import importlib.util
    folder = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('sheer_delivery_d3dc', folder / 'd3dc.py')
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    result = compiler.compile_file(path, compile_cache=compile_cache)
    if not result.ok:
        raise ValueError(result.messages)
    listing = compiler.disassemble(result.bytecode)
    declarations = tuple(sorted(line.strip() for line in listing.splitlines()
                                if re.match(r'^\s*dcl_(resource|sampler|constantbuffer|input|output)', line)))
    resources = set(re.findall(r'\bdcl_resource[^\n]*\b(t\d+)\b', listing))
    return declarations, resources


def sha256(path):
    """Bind reports to bytes rather than filenames."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_file(parent, value):
    """Accept INI Windows separators on either test platform."""
    return (parent / value.strip().strip('"').replace('\\', '/')).resolve()


def read_sections(path, strict=True):
    """Keep ordered command lines; the delivered INI must not repeat a section name.

    Files we did not write (the author's original, the report's source snapshot) are read
    with strict=False: a repeated section is appended to the first one, which is how
    3DMigoto itself merges them, so an author-side quirk cannot fail our identity checks.
    """
    sections, current = {}, None
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1].lower()
            if current in sections and strict:
                raise ValueError(f'{path}:{number} 重复段 {current}')
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def assignments(lines, name):
    """Return exact INI assignments; comments have already been removed."""
    pattern = re.compile(r'^' + re.escape(name) + r'\s*=\s*(.+)$', re.I)
    return [match.group(1).strip() for line in lines if (match := pattern.match(line))]


def mesh_bindings_at_call(lines, controller):
    """Capture direct buffer assignments at each call, not later cleanup assignments."""
    active, calls = {}, []
    for line in lines:
        match = re.fullmatch(r'(ib|vb0|vb1)\s*=\s*(.+)', line, re.I)
        if match:
            active[match.group(1).lower()] = match.group(2).lower()
        if any(value.lower() == controller for value in assignments([line], 'run')):
            calls.append(dict(active))
    return calls


def mesh_bindings_at_draw(lines, inherited):
    """Apply CustomShader overrides only until its direct draw executes."""
    active = dict(inherited)
    for line in lines:
        if re.match(r'^draw\w*\s*=', line, re.I):
            return active
        match = re.fullmatch(r'(ib|vb0|vb1)\s*=\s*(.+)', line, re.I)
        if match:
            active[match.group(1).lower()] = match.group(2).lower()
    return active


def blocks(lines):
    """Group a section body into statements and {branches: [(condition, body), ...]}.

    Branches stay separate so a binding made in one branch (LOD0 buffers) never leaks
    into the path that takes another branch (LOD1 buffers).
    """
    items, i = [], 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^if\b', line, re.I):
            depth, j = 1, i + 1
            while j < len(lines) and depth:
                if re.match(r'^if\b', lines[j], re.I):
                    depth += 1
                elif re.match(r'^endif\b', lines[j], re.I):
                    depth -= 1
                j += 1
            inner, branches, condition, body, depth = lines[i + 1:j - 1], [], line[2:].strip(), [], 0
            for entry in inner:
                if re.match(r'^if\b', entry, re.I):
                    depth += 1
                elif re.match(r'^endif\b', entry, re.I):
                    depth -= 1
                if depth == 0 and re.match(r'^(elif|else\s+if|else)\b', entry, re.I):
                    branches.append((condition, body))
                    condition = re.sub(r'^(elif|else\s+if|else)\b', '', entry, flags=re.I).strip() or 'else'
                    body = []
                    continue
                body.append(entry)
            branches.append((condition, body))
            items.append({'branches': [(c, blocks(b)) for c, b in branches]})
            i = j
            continue
        items.append(line)
        i += 1
    return items


def feasible(conditions):
    """A path that needs one variable to equal two different values can never run."""
    seen = {}
    for condition in conditions:
        for name, value in re.findall(r'\$([\w\\]+)\s*==\s*(-?[\w.]+)', condition):
            if seen.setdefault(name.lower(), value) != value:
                return False
    return True


def call_target(line, sections):
    """Return the CommandList a line hands control to, whether by `run =` or by assigning
    `ref <CommandList>` to a callback slot (the EFMI generator's entry-point style)."""
    match = re.match(r'^run\s*=\s*(.+)$', line, re.I)
    if match:
        target = match.group(1).strip().lower()
        return target if target in sections else None
    match = re.match(r'^[^=]+=\s*ref\s+(.+)$', line, re.I)
    if match:
        target = match.group(1).strip().lower()
        return target if target.startswith('commandlist') and target in sections else None
    return None


def walk_paths(sections, start, controller, state=None, conditions=(), chain=(), depth=0):
    """Every feasible route from `start` to a `run = controller` line, with the ib/vb0/vb1
    bindings in force and the conditions taken along the way."""
    if depth > 12 or start not in sections or start in chain:
        return []
    found = []

    def run_items(items, state, conditions):
        for index, item in enumerate(items):
            if isinstance(item, dict):
                for condition, body in item['branches']:
                    run_items(list(body) + items[index + 1:], dict(state), conditions + [condition])
                return
            match = re.fullmatch(r'(ib|vb0|vb1)\s*=\s*(.+)', item, re.I)
            if match:
                state[match.group(1).lower()] = re.sub(r'^ref\s+', '', match.group(2).strip(), flags=re.I).lower()
                continue
            target = call_target(item, sections)
            if target == controller:
                if feasible(conditions):
                    found.append({'bindings': dict(state), 'conditions': list(conditions), 'chain': list(chain) + [start]})
            elif target:
                found.extend(walk_paths(sections, target, controller, dict(state), tuple(conditions),
                                        tuple(chain) + (start,), depth + 1))

    run_items(blocks(sections[start]), dict(state or {}), list(conditions))
    return found


def parse_gate(line):
    """Split the controller gate into its material terms and optional state restrictions.

    Accepted: one `vs == N`, one `ps == M`, plus any number of `$variable == number`
    conjuncts in any order. Returns the state conjuncts, or None when the line is not a gate.
    """
    match = re.fullmatch(r'if\s+(.+)', line, re.I)
    if not match:
        return None
    numeric = r'-?\d+(?:\.\d+)?'
    terms = [term.strip() for term in match.group(1).split('&&')]
    material = [t for t in terms if re.fullmatch(r'(vs|ps)\s*==\s*' + numeric, t, re.I)]
    states = [t for t in terms if re.fullmatch(r'\$\w+\s*==\s*' + numeric, t)]
    if len(material) != 2 or len(states) + 2 != len(terms) or {m.split('==')[0].strip().lower() for m in material} != {'vs', 'ps'}:
        return None
    return states


def normalised(lines):
    """Compare INI commands by meaning: spacing around `=` and commas is not a change."""
    return [re.sub(r'\s+', ' ', re.sub(r'\s*([=,])\s*', r'\1', line)).strip().lower() for line in lines]


def describe(path):
    """One readable line per proven path for the runbook user."""
    chain = ' -> '.join('[' + name + ']' for name in path['chain'])
    conditions = '; '.join(path['conditions']) or '无'
    return f'{chain}  条件: {conditions}'


def check_delivery(ini, shaders, colour_report, source_route, style_index, compile_cache=None, original_ini=None):
    """Prove the runbook structure along every reachable call path; unknown control flow is a failure."""
    ini, colour_report = Path(ini).resolve(), Path(colour_report).resolve()
    shaders = [Path(path).resolve() for path in shaders]
    errors, groups = [], {}

    def fail(code, where, reason, action):
        errors.append(f'{code} {where}: {reason}。修复: {action}')

    try:
        sections = read_sections(ini)
        report = json.loads(colour_report.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'errors': [f'D01 {exc}。修复: 补齐可读取的 INI 和 preview v2 JSON。'], 'reflection_groups': []}
    # Reject legacy arrays and incomplete object shapes before reading their identity fields.
    valid_shape = (isinstance(report, dict) and report.get('schema_version') == 2
                   and isinstance(report.get('ini'), dict)
                   and isinstance(report.get('pieces'), list) and bool(report['pieces']))
    if valid_shape:
        for piece in report['pieces']:
            if (not isinstance(piece, dict) or not isinstance(piece.get('texture'), dict)
                    or not isinstance(piece.get('inputs'), dict)
                    or not all(isinstance(value, dict) for value in piece['inputs'].values())):
                valid_shape = False
                break
    if not valid_shape:
        fail('D02', colour_report, '不是有目标切片的 v2 报告', '对真实源 INI 和目标 draw 重跑步 06 preview')
        return {'errors': errors, 'reflection_groups': []}
    identities = [report.get('ini', {})]
    piece_bindings = {}
    for piece in report.get('pieces', []):
        identities += [piece.get('texture', {})] + list(piece.get('inputs', {}).values())
        if source_route == 'A' and (piece.get('status') != 'uniform_diffuse' or not piece.get('complete') or piece.get('addressing') != 'clamp'):
            fail('D03', piece.get('label'), '非单色或未完整证明单色不能走 A', '保留真实光腿贴图走 B；UV 不对应走 C；不要关闭纹理采样')
    for identity in identities:
        try:
            path = Path(identity['path'])
            if not path.is_file() or sha256(path) != identity['sha256']:
                raise ValueError()
        except (KeyError, TypeError, OSError, ValueError):
            fail('D04', colour_report, f'源身份缺失或 SHA 已变化: {identity.get("path", "缺 path")}', '保留原 INI/输入快照，再用当前真实输入重新生成颜色报告')
    for piece in report.get('pieces', []):
        try:
            source_ini = Path(report['ini']['path'])
            source_sections = read_sections(source_ini, strict=False)
            resource = piece['resource']
            if '=' in resource:
                names = dict(item.split('=', 1) for item in resource.split(','))
                bindings = dict(zip(('Index', 'Position', 'Texcoord'), (names['ib'], names['pos'], names['uv'])))
            else:
                variants = [('Index', 'Position', 'Texcoord'), ('IB', 'VB0', 'VB1')]
                suffixes = next(items for items in variants if all(('resource_' + resource + '_' + suffix).lower() in source_sections for suffix in items))
                bindings = {kind: 'Resource_' + resource + '_' + suffix for kind, suffix in zip(('Index', 'Position', 'Texcoord'), suffixes)}
            for kind, name in bindings.items():
                references = assignments(source_sections[name.lower()], 'filename')
                if len(references) != 1 or sha256(resolve_file(source_ini.parent, references[0])) != piece['inputs'][kind]['sha256']:
                    raise ValueError(kind)
            piece_bindings[id(piece)] = bindings
        except (KeyError, ValueError, StopIteration, OSError, TypeError) as exc:
            fail('D25', piece.get('label'), f'报告网格资源与原 INI 身份不符: {exc}', '保留原 Index/Position/Texcoord 和原 INI 快照，再用正确资源重新生成报告')

    # Resolve every local resource reference before accepting any draw path.
    for name, lines in sections.items():
        for field in ('filename', 'ps'):
            for value in assignments(lines, field):
                if field == 'ps' and not name.startswith('customshader'):
                    continue
                if not resolve_file(ini.parent, value).is_file():
                    fail('D05', name, f'{field} 文件不存在: {value}', '把 overlay 与原资源组成可读取的完整目录，修正相对路径')
    formal = {}
    for name, lines in sections.items():
        if not name.startswith('customshader'):
            continue
        for value in assignments(lines, 'ps'):
            path = resolve_file(ini.parent, value)
            if path.is_file():
                text = path.read_text(encoding='utf-8-sig')
                if re.search(r'^\s*#define\s+ANISO_DEBUG_MODE\s+0\b', text, re.M):
                    formal[name] = path
    selected = {name: path for name, path in formal.items() if path in shaders}
    if len(set(shaders)) != len(shaders) or len(selected) != len(shaders):
        fail('D06', ini, '正式 PS 参数重复、未接到 CustomShader 或不是正式模式', '逐个填写本目标所有正式 --shader，不传 probe')
    controllers = [name for name, lines in sections.items() if name.startswith('commandlist')
                   and any(value.lower() in selected for value in assignments(lines, 'run'))]
    if len(controllers) != 1:
        fail('D07', ini, '不能唯一定位目标 CommandList', '采用步 09 的单层 CommandList 模板；复杂调用需独立证明，不能记 PASS')
    controller = controllers[0] if len(controllers) == 1 else ''
    lines = sections.get(controller, [])
    called = {value.lower() for value in assignments(lines, 'run')}
    if any(name in formal and formal[name] not in shaders for name in called):
        fail('D08', controller, '遗漏该 draw 的正式状态 --shader', '把本 CommandList 引用的全部正式状态加入命令')
    for called_name in called:
        if not called_name.startswith('customshader') or called_name not in sections:
            fail('D09', controller, f'未支持或不存在的嵌套调用 {called_name}', '使用步 09 直接调用 CustomShader 的结构，复杂分支另做证明')
    callers = [name for name, body in sections.items() if controller and controller in [v.lower() for v in assignments(body, 'run')]]
    notes = []

    # Match the complete ordered grammar, not disconnected regex fragments.
    cursor = 0
    style_var = None
    if style_index is not None:
        if not 0 <= style_index <= 4095:
            fail('D11', ini, '外观下标越界', '填写审计过的 0–4095 下标')
        match = re.fullmatch(r'x' + str(style_index) + r'\s*=\s*(\$\w+)', lines[0] if lines else '', re.I)
        if match:
            style_var, cursor = match.group(1), 1
        else:
            fail('D11', controller, '第一条必须给实际外观下标传值', f'在 draw 分支前写 x{style_index} = $sheer_style，并与 builder 下标一致')
    elif lines and re.fullmatch(r'x\d+\s*=\s*\$\w+', lines[0], re.I):
        cursor = 1
    numeric = r'-?\d+(?:\.\d+)?'
    gate_states = parse_gate(lines[cursor]) if cursor < len(lines) else None
    valid = gate_states is not None
    body = lines[cursor + 1:] if valid else []
    pattern = (r'if\s+\$\w+\s*==\s*' + numeric + r'\nrun\s*=\s*CustomShader\w+'
               r'(?:\nelif\s+\$\w+\s*==\s*' + numeric + r'\nrun\s*=\s*CustomShader\w+)'
               + r'+\nelse\n(draw\w*\s*=\s*[^\n]+)\nendif\nelse\n(draw\w*\s*=\s*[^\n]+)\nendif')
    grammar = re.fullmatch(pattern, '\n'.join(body), re.I)
    if not valid or not grammar or grammar.group(1) != grammar.group(2):
        fail('D12', controller, '分支结构/双门控/原 draw 回退未获证明', '逐行按步 09 模板接线：门控写 vs/ps 两项，可再加 `$变量 == 数字` 状态限制；保留原 draw 操作和全部参数；复杂表达式不能静态记通过')

    # Every route from a TextureOverride to the controller, through run lines and EFMI
    # callback refs alike, with the mesh bindings each route carries.
    paths = []
    for name in sections:
        if name.startswith('textureoverride'):
            paths.extend(walk_paths(sections, name, controller))
    paths = [path for path in paths if feasible(path['conditions'] + (gate_states or []))]
    if controller and not paths:
        fail('D10', controller, '没有任何 TextureOverride 能到达目标 CommandList', '把 run 写在目标 draw 原来的那一行；保留原调用链（run / 回调 ref）和原条件，不要新增条件')
    for path in paths:
        notes.append(f'D10 路径 {describe(path)}（运行时条件由步 11 的纯绿检查覆盖）')

    if original_ini is not None:
        # The redirect must sit exactly where the original draw sat; nothing else in the
        # calling section may change, so no condition can have been invented or removed.
        original = read_sections(Path(original_ini), strict=False)
        original_draw = grammar.group(1) if valid and grammar else None
        for caller in callers:
            body = sections[caller]
            rebuilt = [original_draw if call_target(line, sections) == controller and original_draw else line for line in body]
            if caller not in original or normalised(rebuilt) != normalised(original[caller]):
                fail('D29', caller, '目标 draw 不是原位替换，或调用段的其它命令/条件被改动', '把 run 写回原 draw 所在行，调用段其余命令保持原样；合并段或改条件都不算原位替换')
    else:
        notes.append('D29 未核对原位替换：命令没有给 --original-ini')

    if valid and grammar and grammar.group(1) == grammar.group(2):
        original_draw = grammar.group(1)
        for name in called:
            custom = sections.get(name, [])
            draws = [line for line in custom if re.match(r'^draw\w*\s*=', line, re.I)]
            if draws != [original_draw] or any(re.match(r'^(run|if|elif|else|endif)\b', line, re.I) for line in custom):
                fail('D13', name, 'CustomShader 有复杂调用或 draw 与回退不同', '使用单一原 draw，参数与两处 else 逐字一致')
        operation = original_draw.split('=', 1)[0].strip().lower()
        counts = [int(x.strip()) for x in original_draw.split('=', 1)[1].split(',') if re.fullmatch(r'-?\d+', x.strip())]
        actual = counts if operation == 'drawindexed' and len(counts) == 3 else [counts[0], counts[2], counts[3]] if operation == 'drawindexedinstanced' and len(counts) == 5 else None
        if actual is None or not any(piece.get('draw') == actual for piece in report.get('pieces', [])):
            fail('D14', controller, '颜色报告没有匹配的目标 draw 或 draw 形式未支持', 'preview 同次报告加入目标丝袜 --piece；C 可另含不同 draw 的身体源；其他 draw 类型需单独证明，不擅改操作名')
        else:
            target_found = False
            for piece in report.get('pieces', []):
                if piece.get('draw') != actual or id(piece) not in piece_bindings:
                    continue
                try:
                    for kind, name in piece_bindings[id(piece)].items():
                        references = assignments(sections[name.lower()], 'filename')
                        if len(references) != 1 or sha256(resolve_file(ini.parent, references[0])) != piece['inputs'][kind]['sha256']:
                            raise ValueError(kind)
                    target_found = True
                except (KeyError, OSError, ValueError):
                    continue
            if not target_found:
                fail('D26', controller, '目标 draw 的网格输入与验收目录不匹配', '保留目标资源引用与文件，使用该目标重新生成报告；身体源资源不必绑定到丝袜 draw')
            # Existing Resource sections do not prove which buffers the draw consumes: the
            # bindings in force on every feasible path into the controller must match the report.
            candidates = [piece for piece in report['pieces']
                          if piece.get('draw') == actual and id(piece) in piece_bindings]
            for path in paths:
                for custom_name in called:
                    active = mesh_bindings_at_draw(sections.get(custom_name, []), path['bindings'])
                    try:
                        actual_hashes = {}
                        for slot, kind in (('ib', 'Index'), ('vb0', 'Position'), ('vb1', 'Texcoord')):
                            references = assignments(sections[active[slot]], 'filename')
                            if len(references) != 1:
                                raise ValueError(slot)
                            actual_hashes[kind] = sha256(resolve_file(ini.parent, references[0]))
                        if not any(all(piece['inputs'][kind]['sha256'] == digest
                                       for kind, digest in actual_hashes.items())
                                   for piece in candidates):
                            raise ValueError('actual buffer SHA differs from target report')
                    except (KeyError, OSError, ValueError) as exc:
                        fail('D28', f'{describe(path)} -> {custom_name}', f'实际 ib/vb0/vb1 绑定与颜色报告未获证明: {exc}',
                             '保留原绑定；这条路径绑的若是另一档（例如别的 LOD）的缓冲，就把区分它的 mod 自有变量加进门控（如 `$lod_level == 0 &&`）；否则核对调用前及 CustomShader draw 前的真实资源，用该网格重跑 preview。不能添加猜测绑定或改资源来换 PASS')
    if style_index is not None and style_var:
        constants = '\n'.join(sections.get('constants', []))
        if not re.search(r'^global\s+' + re.escape(style_var) + r'\s*=\s*0$', constants, re.M | re.I):
            fail('D15', 'Constants', '外观必须非 persist 初始 0', f'声明 global {style_var} = 0，启动只透肉')
        keys = [body for name, body in sections.items() if name.startswith('key')
                and [re.sub(r'\s+', '', x) for x in assignments(body, style_var)] == ['0,1'] and assignments(body, 'type') == ['cycle']]
        if len(keys) != 1 or not assignments(keys[0], 'key'):
            fail('D16', ini, '缺少唯一的 0,1 cycle 按键', '按步 09 补 key/type=cycle/外观变量=0,1')
        else:
            condition = assignments(keys[0], 'condition')
            match = re.fullmatch(r'(\$\w+)\s*==\s*1', condition[0]) if len(condition) == 1 else None
            if not match or not re.search(r'^global\s+(?:persist\s+)?' + re.escape(match.group(1)) + r'\s*=', constants, re.M | re.I):
                fail('D17', 'Key', '在场变量未定义或条件无法证明', '使用本 mod Constants 中已定义的在场变量；实机确认会置 1')

    for name, path in selected.items():
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', path.read_text(encoding='utf-8-sig'), flags=re.S)
        defs = re.findall(r'^\s*#define\s+SHEER_SKIN_FROM_TEX\s+(\S+)', text, re.M)
        samples = re.findall(r'float3\s+_shSkin\s*=\s*([^;]+);', text)
        slots = set(re.findall(r'\b(t\d+)\.Sample\w*\(', ' '.join(samples)))
        if source_route in ('B', 'C'):
            if (defs and defs != ['1']) or not slots:
                fail('D18', path, '肤色采样关闭/缺失/宏不明确', '所有正式状态保留纹理肤色；去掉 SKIN_FROM_TEX=0 后重建，不能切 A')
            for slot in slots:
                resources = assignments(sections[name], 'ps-' + slot)
                if len(resources) != 1 or resources[0].lower() not in sections:
                    fail('D19', name, f'肤色槽 {slot} 未绑定有效 Resource', '绑定生成 PS 的同一槽，并补对应 Resource filename')
        if style_index is not None:
            gains = re.findall(r'^\s*#define\s+SHEER_SPEC_GAIN\s+(\S+)', text, re.M)
            try:
                gain = float(gains[0]) if len(gains) == 1 else 0
            except ValueError:
                gain = 0
            if not math.isfinite(gain) or gain <= 0 or gain > 3.402823466e38:
                fail('D20', path, '正式状态高光增益不是有限正数', '使用有效正 SPEC_GAIN 重建该状态，不要删除切换')
            if not re.search(r'float\s+_shLook\s*=\s*\([^;]*\.Load\(int2\(' + str(style_index) + r',\s*0\)\)\.x\s*>\s*0\.5\)\s*\?\s*1\.0\s*:\s*0\.0;', text) or not re.search(r'o0\.xyz\s*=\s*lerp\(o0\.xyz,\s*_shLit,\s*SHEER_SPEC_GAIN\s*\*\s*_shLook\b', text):
                fail('D21', path, '实际输出未使用指定 IniParams 外观值', '用相同 --style-index 重建；复杂手改 HLSL 需独立验证')
        try:
            signature, active_resources = compiled_bindings(path, compile_cache)
            if source_route in ('B', 'C') and not slots.issubset(active_resources):
                fail('D22', path, '严格编译后的真实资源表丢失肤色采样', '检查 SHEER_GAIN/遮罩/状态宏，恢复真实纹理肤色效果并重建')
            if style_index is not None:
                ini_slots = set(re.findall(r'Texture1D<float4>\s+\w+\s*:\s*register\((t\d+)\)', text))
                if not ini_slots or not ini_slots.issubset(active_resources):
                    fail('D23', path, '严格编译后的外观资源不存在', '恢复正高光和有效切换调用；不能只保留声明')
            groups.setdefault(signature, []).append(str(path))
        except Exception as exc:
            fail('D24', path, f'无法完成正式严格编译/实际资源反射: {exc}', '在 Windows 运行并修复编译错误后重试；未编译不能记 PASS')
    return {'errors': errors, 'notes': notes,
            'reflection_groups': [{'representative': members[0], 'members': members} for members in groups.values()]}


def main():
    """Expose deterministic exit codes and recovery steps to runbook users."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ini', required=True, type=Path)
    parser.add_argument('--shader', required=True, action='append', type=Path)
    parser.add_argument('--colour-report', required=True, type=Path)
    parser.add_argument('--source-route', required=True, choices=('A', 'B', 'C'))
    parser.add_argument('--compile-cache', help='复用同目录、同内容、同编译条件的成功字节码')
    parser.add_argument('--original-ini', type=Path, help='未改动的原 mod INI；给了就核对 run 是否原位替换原 draw（D29）')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--style-index', type=int)
    group.add_argument('--no-style-switch', action='store_true')
    args = parser.parse_args()
    missing = [str(path) for path in [args.ini, args.colour_report, *args.shader, *([args.original_ini] if args.original_ini else [])] if not path.is_file()]
    if missing:
        print('D00 输入缺失: ' + ', '.join(missing) + '。修复: 完成对应生成步骤并填写存在的路径。')
        return 2
    try:
        result = check_delivery(args.ini, args.shader, args.colour_report, args.source_route, args.style_index,
                                args.compile_cache, args.original_ini)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(f'D27 输入无法解析: {exc}。修复: 在副本中转成 UTF-8，并重跑 preview 生成完整 v2 报告；不要手改 JSON 冒充证据。')
        return 1
    for note in result.get('notes', []):
        print('INFO ' + note)
    for error in result['errors']:
        print(error)
    for number, group in enumerate(result['reflection_groups'], 1):
        print(f'REFLECT_GROUP {number}: {group["representative"]} ({len(group["members"])} states); run reflect_check.py for this representative')
    if result['errors']:
        print('FAIL: 未通过/未验证；按错误动作修复后原命令重跑。')
        return 1
    print('PASS: 支持模板的静态接线一致；仍需逐组正式反射和实机检查。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
