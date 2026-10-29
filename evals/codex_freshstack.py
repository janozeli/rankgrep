"""Repeat the frozen FreshStack questions on isolated Codex Astra medium/priority.

uv run --group eval evals/codex_freshstack.py
"""
import argparse
import concurrent.futures
import json
import random
import subprocess
import time
from pathlib import Path

import codex_isolation as ci
import freshstack as f
import freshstack_data as d

WORK = Path.home() / '.cache/rankgrep-evals/codex-freshstack'
OUT = d.REPO / 'evals/codex-results'
PLUGIN_COMMIT = '31379def63c8eb4a21f0be3ecf5f1e2e52ff8a00'


def plugin_snapshot():
    plugin = WORK / 'plugin'
    if not plugin.exists():
        import io, tarfile
        archive = subprocess.check_output(['git', 'archive', PLUGIN_COMMIT, 'bin', 'src', 'skills',
            'pyproject.toml', 'uv.lock', '.codex-plugin', '.agents', '.claude-plugin', 'LICENSE', 'README.md', '.python-version'], cwd=d.REPO)
        plugin.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(plugin, filter='data')
    return plugin


def record(topic, q, arm, events, raw, mapping, elapsed, returncode):
    complete = next((e for e in reversed(events) if e['type'] == 'turn.completed'), None)
    messages = [e['item']['text'] for e in events if e['type'] == 'item.completed' and e['item']['type'] == 'agent_message']
    reply = messages[-1] if messages else ''
    docs, invalid = f.selected(reply, mapping)
    error = None if complete and returncode == 0 else 'execution_failed'
    if error:
        docs = []
    calls = [e['payload'] for e in raw if e['type'] == 'response_item' and
             e['payload']['type'] in ('function_call', 'custom_tool_call')]
    return {'topic': topic, 'query_id': q['query_id'], 'arm': arm, 'documents': docs,
        'invalid_paths': invalid, 'reply': reply, 'tool_calls': calls, 'error': error,
        'seconds': elapsed, 'usage': complete.get('usage') if complete else None,
        **d.metrics(q, docs)}


def run(topics, jobs):
    plugin = plugin_snapshot()
    for topic in topics:
        corpus, questions = d.load(d.WORK, topic)
        mapping = {d.filename(doc): doc['_id'] for doc in corpus}
        f.verify_corpus(d.WORK, topic, corpus)
        selection = json.loads((d.OUT / topic / 'selection.json').read_text())['selection']
        by_id = {q['query_id']: q for q in questions}
        chosen = [by_id[qid] for qid in selection]
        assert len(chosen) == 10
        cache = WORK / topic / 'cache'
        warm = ci.Isolated(WORK / topic / 'warmup', d.WORK / topic / 'library/docs', plugin, cache)
        warm.prepare()
        command = warm.command([])[:-1] + ['/plugin/bin/rankgrep', '-k', '1', 'warm', 'docs']
        env = {'HOME': str(Path.home()), 'PATH': '/opt/codex/bin:/opt/codex/codex-path:/opt/uv:/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        warmed = subprocess.run(command, env=env, capture_output=True, text=True)
        if warmed.returncode not in (0, 1):
            raise RuntimeError('rankgrep warmup failed: ' + warmed.stderr)
        print(topic, 'warmup passed', flush=True)
        out = OUT / topic
        out.mkdir(parents=True, exist_ok=True)
        manifest = {'model': ci.MODEL, 'effort': 'medium', 'service_tier_requested': 'priority',
                    'selection': selection, 'plugin_commit': PLUGIN_COMMIT, 'sources': d.source_rows(topic),
                    'prompt_sha256': {q['query_id']: d.digest(f.prompt(q)) for q in chosen},
                    'config': ci.CONFIG, 'timeout_seconds': 1200, 'warm_cache': True,
                    'runner_sha256': {name: d.sha(Path(__file__).with_name(name)) for name in ['codex_freshstack.py', 'codex_isolation.py']},
                    'budget_note': 'Codex CLI has no equivalent of Claude max-turns/max-budget-usd; not enforced or compared.',
                    'codex': subprocess.check_output(['codex', '--version'], text=True).strip()}
        (out / 'selection.json').write_text(json.dumps(manifest, indent=2)+'\n')
        tasks = [(q, arm) for q in chosen for arm in f.ARMS]
        random.Random(f'{f.SEED}:{topic}:order').shuffle(tasks)
        def one(task):
            q, arm = task
            root = WORK / topic / q['query_id'] / arm
            cached = root / 'record.json'
            if cached.exists():
                row = json.loads(cached.read_text())
                if row.get('run_key') != d.digest(manifest):
                    raise ValueError('stale cached run; use a new workspace')
                return row
            if (root / 'home').exists():
                raise RuntimeError(f'partial session; inspect before retry: {root}')
            runtime = ci.Isolated(root, d.WORK / topic / 'library/docs', plugin if arm == 'free+rankgrep' else None, cache if arm == 'free+rankgrep' else None)
            exposure = runtime.prepare()
            start = time.monotonic()
            status, events, raw = runtime.execute(f.prompt(q))
            row = record(topic, q, arm, events, raw, mapping, time.monotonic()-start, status)
            row['run_key'] = d.digest(manifest)
            row['exposure'] = {'skills': exposure['skills'], 'tools_sha256': d.digest(exposure['tools']),
                               'context_sha256': d.sha(root / 'context.json')}
            cached.write_text(json.dumps(row)+'\n')
            print(topic, q['query_id'], arm, row['coverage@20'], row['error'], flush=True)
            return row
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            rows = list(pool.map(one, tasks))
        assert len({r['exposure']['tools_sha256'] for r in rows}) == 1
        f.verify_corpus(d.WORK, topic, corpus)
        d.write_rows(out / 'runs.jsonl', sorted(rows, key=lambda r: (r['query_id'], r['arm'])))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--topics', nargs='+', choices=d.TOPICS, default=list(d.TOPICS))
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args()
    run(a.topics, a.jobs)
