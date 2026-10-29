"""Conservative audit of explicit controls in completed native shell events."""
import json
import shlex
from pathlib import Path


def rankgrep_commands(command):
    try:
        outer = shlex.split(command)
        script = outer[2] if len(outer) >= 3 and outer[0].endswith(('bash', 'sh')) and outer[1] in ('-lc', '-c') else command
        lexer = shlex.shlex(script, posix=True, punctuation_chars=';&|()\n')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        segments, current = [], []
        for token in lexer:
            if token and all(c in ';&|()\n' for c in token):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
    except ValueError:
        return []
    commands = []
    for segment in segments:
        while segment and (segment[0] in ('exec', 'command', 'env', 'time') or '=' in segment[0]):
            segment = segment[1:]
        if segment and Path(segment[0]).name == 'rankgrep':
            commands.append(segment)
    return commands


def flags(argv):
    stats, weights = False, []
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == '--':
            break
        if token == '--stats':
            stats = True
        if token == '--weight' and i + 2 < len(argv):
            weights.append({'text': argv[i + 1], 'factor': argv[i + 2]})
            i += 2
        elif token.startswith('--weight=') and i + 1 < len(argv):
            weights.append({'text': token.split('=', 1)[1], 'factor': argv[i + 1]})
            i += 1
        i += 1
    return {'stats_requested': stats, 'weights': weights}


def audit_controls(events):
    commands = []
    for event in events:
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') != 'command_execution':
            continue
        argv = rankgrep_commands(item['command'])
        if not argv:
            continue
        statistics = []
        for line in item.get('aggregated_output', '').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and {'term', 'df', 'section_count', 'fraction', 'idf'} <= row.keys():
                statistics.append(row)
        commands.append({'command': item['command'], 'exit_code': item.get('exit_code'),
                         'calls': [{'argv': a, **flags(a)} for a in argv], 'statistics': statistics})
    return {'stats_requested': any(c['stats_requested'] for e in commands for c in e['calls']),
            'statistics_returned': any(e['statistics'] for e in commands),
            'weights_requested': any(c['weights'] for e in commands for c in e['calls']),
            'commands': commands}
