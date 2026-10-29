"""Audit native command-execution events, rather than counting skill mentions."""
import json
import shlex
from pathlib import Path

import codex_freshstack as runner
import freshstack_data as d


def invokes_rankgrep(command):
    words = shlex.split(command)
    script = words[2] if len(words) >= 3 and words[0].endswith(('bash', 'sh')) and words[1] in ('-lc', '-c') else command
    lexer = shlex.shlex(script, posix=True, punctuation_chars=';&|()\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    start = True
    for word in lexer:
        if word and all(c in ';&|()\n' for c in word):
            start = True
        elif start:
            if word in ('exec', 'command', 'env', 'time') or '=' in word:
                continue
            if Path(word).name == 'rankgrep':
                return True
            start = False
    return False


def audit_session(root):
    events = d.read_rows(root / 'stdout.jsonl')
    launches = []
    for event in events:
        item = event.get('item', {})
        if event['type'] != 'item.completed' or item.get('type') != 'command_execution':
            continue
        command = item['command']
        if not invokes_rankgrep(command):
            continue
        hits = 0
        for line in item.get('aggregated_output', '').splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and {'path', 'start', 'end', 'score', 'matched'} <= value.keys():
                hits += 1
        launches.append({'command': command, 'exit_code': item.get('exit_code'), 'hits': hits,
                         'runtime_error': 'Traceback (most recent call last):' in item.get('aggregated_output', '')})
    return {'invoked': bool(launches), 'returned_hits': any(c['exit_code'] == 0 and c['hits'] for c in launches),
            'launches': launches, 'stdout_sha256': d.sha(root / 'stdout.jsonl')}


def main():
    rows = []
    for topic in d.TOPICS:
        for row in d.read_rows(runner.OUT / topic / 'runs.jsonl'):
            root = runner.WORK / topic / row['query_id'] / row['arm']
            rows.append({k: row[k] for k in ('topic', 'query_id', 'arm', 'run_key')} |
                        audit_session(root))
    d.write_rows(runner.OUT / 'execution-audit.jsonl', rows)
    print('Audited native commands for', len(rows), 'sessions')


if __name__ == '__main__':
    main()
