#!/usr/bin/env python3
"""检查逐步说明的结构、命令和链接。退出 1 表示有错误，警告不改变退出码。"""
import argparse
import re
from pathlib import Path
from urllib.parse import unquote

HEADINGS = ['目标', '进入条件', '输入', '操作', '期望输出', '判定', '失败处理', '产物', '本步红旗']
BANNED = ['视情况', '按需', '酌情', '适当', '一般', '大概', '可能需要', '如果有必要']
PLACEHOLDER = re.compile(r'<([^<>\r\n]+)>')
LINK = re.compile(r'!?\[[^\]\n]*\]\(([^)\n]+)\)')
FENCE = re.compile(r'^\s*```([^`]*)$')


def sections(lines):
    """Keep heading positions so diagnostics point to the relevant section."""
    found = []
    for index, line in enumerate(lines, 1):
        if line.startswith('## '):
            found.append((line[3:].strip(), index))
    return found


def section_text(lines, name):
    """Return one section without allowing another heading to supply declarations."""
    active = False
    output = []
    for line in lines:
        if line.startswith('## '):
            active = line[3:].strip() == name
        elif active:
            output.append(line)
    return '\n'.join(output)


def fenced_lines(lines):
    """Expose fenced content with its language and original line number."""
    language = None
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if match:
            language = match.group(1).strip().lower() if language is None else None
        elif language is not None:
            yield number, language, line


def check(root):
    """Validate each document independently and retain every actionable diagnostic."""
    errors = []
    warnings = []
    skill = root / 'SKILL.md'
    root_lines = skill.read_text(encoding='utf-8-sig').splitlines() if skill.exists() else []
    common = set(PLACEHOLDER.findall(section_text(root_lines, '记号')))
    vision = root / 'references/vision-subagent.md'
    vision_ids = set(re.findall(r'\bVP\d+[a-z]?\b', vision.read_text(encoding='utf-8-sig'))) if vision.exists() else set()
    documents = sorted(root.rglob('*.md'))
    for path in documents:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
        relative = path.relative_to(root).as_posix()
        is_step = re.fullmatch(r'step-\d\d-.+\.md', path.name) is not None

        def report(number, rule, message):
            errors.append(f'{relative}:{number}: {rule} {message}')

        if is_step:
            has_vision = bool(lines and '👁' in lines[0])
            expected = HEADINGS.copy()
            if has_vision:
                expected.insert(6, '看图点')
            actual = sections(lines)
            if [name for name, _ in actual] != expected:
                report(1, 'R1', '二级标题必须按模板顺序出现：' + ' / '.join(expected))
            for section in ('操作', '判定'):
                body = section_text(lines, section)
                bad = [word for word in BANNED if word in body]
                if bad:
                    position = next((n for name, n in actual if name == section), 1)
                    report(position, 'R2', section + '含模糊词：' + '、'.join(bad))
            input_cells = [line.split('|')[1] for line in section_text(lines, '输入').splitlines() if line.lstrip().startswith('|')]
            declared = common | set(PLACEHOLDER.findall('\n'.join(input_cells)))
            missing = {}
            continuation = ''
            for number, language, line in fenced_lines(lines):
                for token in PLACEHOLDER.findall(line):
                    if token not in declared:
                        missing.setdefault(token, number)
                command = line.strip()
                if not command or command.startswith('#'):
                    continue
                command = continuation + command
                if command.endswith('`'):
                    continuation = command[:-1] + ' '
                    continue
                continuation = ''
                is_command = language in ('powershell', 'pwsh', 'sh', 'bash', 'shell', 'console', 'cmd') or command.startswith(('python ', 'pwsh ', 'cmd_Decompiler.exe ', 'tools/cmd_Decompiler/'))
                if not is_command:
                    continue
                match = re.match(r'python\s+scripts/([^\s"]+\.py)(?:\s|$)', command)
                if match:
                    if not (root / 'scripts' / match.group(1)).is_file():
                        report(number, 'R5', '命令中的脚本不存在：' + match.group(1))
                elif command.startswith(('cmd_Decompiler.exe ', 'tools/cmd_Decompiler/', 'pwsh ')):
                    scripts = re.findall(r'(?<![\w/])(?:[\w./-]+\.(?:py|ps1|exe))', command)
                    for script in scripts:
                        if script == 'cmd_Decompiler.exe':
                            script = 'tools/cmd_Decompiler/cmd_Decompiler.exe'
                        if not (root / script).is_file():
                            report(number, 'R5', '命令中的脚本不存在：' + script)
                else:
                    report(number, 'R5', '命令必须使用规定的入口且写成完整一行')
            for token, number in missing.items():
                report(number, 'R3', '占位符未在输入或记号声明：<' + token + '>')
            if has_vision:
                body = section_text(lines, '看图点')
                ids = set(re.findall(r'\bVP\d+[a-z]?\b', body))
                if not body or not ids or ids - vision_ids:
                    report(1, 'R6', '看图点缺失或引用了未定义的 VP 编号')
            if len(lines) > 250:
                warnings.append(f'{relative}:1: R7 警告：{len(lines)} 行，超过 250')
        # Markdown code spans and fenced examples do not create clickable links.
        link_lines = []
        in_fence = False
        for line in lines:
            if FENCE.match(line):
                in_fence = not in_fence
                link_lines.append('')
            else:
                link_lines.append('' if in_fence else re.sub(r'(`+).*?\1', '', line))
        definitions = {}
        for number, line in enumerate(link_lines, 1):
            definition = re.match(r'^\s*\[([^\]]+)\]:\s*(\S+)', line)
            if definition:
                definitions[definition.group(1).lower()] = definition.group(2)
        for number, line in enumerate(link_lines, 1):
            targets = LINK.findall(line)
            definition = re.match(r'^\s*\[([^\]]+)\]:\s*(\S+)', line)
            if definition:
                targets.append(definition.group(2))
            for label, identifier in re.findall(r'\[([^\]\n]+)\]\[([^\]\n]*)\]', line):
                key = (identifier or label).lower()
                if key not in definitions:
                    report(number, 'R4', '引用式链接未定义：' + key)
            for target in targets:
                target = target.strip().split(' "', 1)[0].strip('<>')
                if re.match(r'^[a-zA-Z][\w+.-]*:', target) or target.startswith(('#', '/', '\\')):
                    continue
                target = unquote(target.split('#', 1)[0])
                if target and not (path.parent / target).exists():
                    report(number, 'R4', '相对链接目标不存在：' + target)
    if not skill.is_file():
        errors.append('SKILL.md:1: R4 缺少入口文件')
    if len(root_lines) > 220:
        warnings.append(f'SKILL.md:1: R7 警告：{len(root_lines)} 行，超过 220')
    return errors, warnings


def main():
    """Print stable diagnostics and make errors visible to shell callers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, help='skill 根目录')
    args = parser.parse_args()
    errors, warnings = check(args.root.resolve())
    for message in errors + warnings:
        print(message)
    print(f'错误 {len(errors)}；警告 {len(warnings)}')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
