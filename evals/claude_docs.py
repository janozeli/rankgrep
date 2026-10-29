"""Free-agent lookup and description adoption on the complete Claude Code Markdown export."""
import argparse
import concurrent.futures
import json
import random
import shutil
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

import codex_adoption as adoption
import codex_audit as audit
import codex_freshstack as base
import codex_isolation as ci
import freshstack_data as d

WORK = base.WORK.parent / 'claude-docs'
OUT = d.REPO / 'evals/claude-docs-results'
CORPUS = WORK / 'library/docs'
DESCRIPTIONS = {
    'original': None,
    'capabilities': adoption.DESCRIPTIONS['capabilities'],
    'domain': 'Search local Claude Code documentation for CLI flags, settings.json, hooks, permissions, plugins, skills, subagents, MCP, and session behavior. BM25 keyword ranking returns source paths, line ranges, snippets, and matched terms as JSONL.',
    'output': adoption.DESCRIPTIONS['output'],
}
ARMS = ('free', *DESCRIPTIONS)
SEED = 'claude-docs-adoption-v1'


def prompt(q):
    return ('Find documentation evidence answering the following question in docs/claude-code.md. '
        'It is the complete official Claude Code documentation in Markdown. You may use any available tools. '
        'Return a final JSON object with an answer string and a citations array. Each citation must have '
        'path, start and end (inclusive, 1-based line numbers in the local file). Use at most 8 citations, '
        'each at most 40 lines. Cite evidence for every part of the question.\n\n' + q['question'])


def parse(reply, line_count):
    value = None
    decoder = json.JSONDecoder()
    for i, char in enumerate(reply):
        if char == '{':
            try:
                candidate, _ = decoder.raw_decode(reply[i:])
            except ValueError:
                continue
            if isinstance(candidate, dict) and isinstance(candidate.get('citations'), list):
                value = candidate
    if value is None:
        return [], 1
    citations, invalid = [], max(0, len(value['citations']) - 8)
    for c in value['citations'][:8]:
        if not isinstance(c, dict):
            invalid += 1
            continue
        path, start, end = c.get('path'), c.get('start'), c.get('end')
        if (path not in ('docs/claude-code.md', '/workspace/docs/claude-code.md') or
            type(start) is not int or type(end) is not int or not 1 <= start <= end <= line_count or
            end - start + 1 > 40):
            invalid += 1
        else:
            citations.append({'path': 'docs/claude-code.md', 'start': start, 'end': end})
    return citations, invalid


def score(q, citations):
    covered = [any(c['start'] <= line <= c['end'] for c in citations for line in alternatives)
               for alternatives in q['reference_lines']]
    return {'covered': covered, 'reference_coverage': sum(covered) / len(covered),
            'all_references': all(covered)}


def corpus():
    meta = json.loads((OUT / 'corpus.json').read_text())
    path = CORPUS / 'claude-code.md'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(meta['url'], timeout=120) as response:
            path.write_bytes(response.read())
    assert d.sha(path) == meta['sha256'], 'official export changed; do not reuse old reference lines'
    assert [p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob('*') if p.is_file()] == ['claude-code.md']
    return meta


def plugins():
    source = base.plugin_snapshot()
    result = {}
    for name, description in DESCRIPTIONS.items():
        target = WORK / 'plugins' / name
        if not target.exists():
            shutil.copytree(source, target)
        original = (source / 'skills/rankgrep/SKILL.md').read_text()
        text = original if description is None else '\n'.join(
            'description: ' + description if line.startswith('description: ') else line
            for line in original.splitlines()) + '\n'
        (target / 'skills/rankgrep/SKILL.md').write_text(text)
        assert text.split('---', 2)[2] == original.split('---', 2)[2]
        for p in source.rglob('*'):
            if p.is_file() and p.relative_to(source).as_posix() != 'skills/rankgrep/SKILL.md':
                assert p.read_bytes() == (target / p.relative_to(source)).read_bytes()
        result[name] = target
    return result


def warm(runtime):
    installed = next((runtime.home / '.codex/plugins/cache').rglob('bin/rankgrep'))
    launcher = Path.home() / installed.relative_to(runtime.home)
    r = subprocess.run(runtime.command([])[:-1] + [str(launcher), '-k', '1', 'documentation', 'docs'],
        capture_output=True, text=True, timeout=1200,
        env={'HOME': str(Path.home()), 'PATH': '/opt/codex/bin:/opt/codex/codex-path:/opt/uv:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    assert r.returncode == 0 and 'Traceback' not in r.stderr, r.stderr


def run(jobs):
    meta = corpus()
    questions = json.loads((OUT / 'questions.json').read_text())
    variants = plugins()
    manifest = {'corpus_sha256': d.digest(meta), 'questions_sha256': d.sha(OUT / 'questions.json'),
        'model': ci.MODEL, 'effort': 'medium', 'service_tier_requested': 'priority', 'config': ci.CONFIG,
        'seed': SEED, 'arms': ARMS, 'descriptions': DESCRIPTIONS, 'plugin_commit': base.PLUGIN_COMMIT,
        'skill_sha256': {k: d.sha(v / 'skills/rankgrep/SKILL.md') for k, v in variants.items()},
        'prompt_sha256': {q['id']: d.digest(prompt(q)) for q in questions},
        'runner_sha256': {n: d.sha(d.REPO / 'evals' / n) for n in
            ['claude_docs.py', 'codex_isolation.py', 'codex_audit.py', 'codex_freshstack.py', 'codex_adoption.py']},
        'codex': subprocess.check_output(['codex', '--version'], text=True).strip(),
        'cache_policy': 'Private session copies of an independently warmed corpus cache; native launcher warmed before timing.',
        'timeout_seconds': 1200, 'budget_note': 'No max-turns or dollar cap; priority is requested, not backend-verified.'}
    # JSON round-trip gives the same representation on cached reruns (tuples become lists).
    manifest = json.loads(json.dumps(manifest))
    manifest_path = OUT / 'manifest.json'
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text()) == manifest, 'stale run manifest'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    seed_cache = WORK / 'warm-cache'
    runtime = ci.Isolated(WORK / 'warmup', CORPUS, variants['original'], seed_cache)
    runtime.prepare()
    warm(runtime)
    tasks = [(q, arm) for q in questions for arm in ARMS]
    random.Random(SEED).shuffle(tasks)

    def one(task):
        q, arm = task
        root = WORK / 'runs' / q['id'] / arm
        cached = root / 'record.json'
        if cached.exists():
            row = json.loads(cached.read_text())
            assert row['run_key'] == d.digest(manifest), 'stale cached record'
            return row
        assert not (root / 'home').exists(), f'partial session: {root}'
        cache = None
        if arm != 'free':
            cache = root / 'cache'
            cache.mkdir(parents=True)
            subprocess.run(['cp', '-a', '--reflink=auto', str(seed_cache) + '/.', str(cache)], check=True)
        runtime = ci.Isolated(root, CORPUS, variants.get(arm), cache)
        exposure = runtime.prepare()
        if arm != 'free':
            warm(runtime)
        start = time.monotonic()
        status, events, raw = runtime.execute(prompt(q))
        elapsed = time.monotonic() - start
        completed = next((e for e in reversed(events) if e['type'] == 'turn.completed'), None)
        replies = [e['item']['text'] for e in events if e['type'] == 'item.completed' and e['item']['type'] == 'agent_message']
        reply = replies[-1] if replies else ''
        citations, invalid = parse(reply, meta['lines'])
        error = None if completed and status == 0 else 'execution_failed'
        if error:
            citations = []
        native_audit = audit.audit_session(root)
        assert not any(c['runtime_error'] for c in native_audit['launches']), 'launcher runtime failure'
        row = {'id': q['id'], 'axis': q['axis'], 'arm': arm, 'run_key': d.digest(manifest),
            'reply': reply, 'citations': citations, 'invalid_citations': invalid, 'error': error,
            'seconds': elapsed, 'usage': completed.get('usage') if completed else None,
            'exposure': {'skills': exposure['skills'], 'tools_sha256': d.digest(exposure['tools']),
                         'context_sha256': d.sha(root / 'context.json')},
            'audit': native_audit, **score(q, citations)}
        cached.write_text(json.dumps(row) + '\n')
        print(q['id'], arm, row['reference_coverage'], native_audit['invoked'], error, flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        rows = list(pool.map(one, tasks))
    corpus()
    d.write_rows(OUT / 'runs.jsonl', sorted(rows, key=lambda r: (r['id'], r['arm'])))


def report():
    meta = corpus()
    questions = json.loads((OUT / 'questions.json').read_text())
    manifest = json.loads((OUT / 'manifest.json').read_text())
    assert manifest['questions_sha256'] == d.sha(OUT / 'questions.json')
    assert manifest['corpus_sha256'] == d.digest(meta)
    rows = d.read_rows(OUT / 'runs.jsonl')
    qs = {q['id']: q for q in questions}
    assert len(rows) == len(questions) * len(ARMS)
    assert {(r['id'], r['arm']) for r in rows} == {(qid, arm) for qid in qs for arm in ARMS}
    assert len({r['exposure']['tools_sha256'] for r in rows}) == 1
    for r in rows:
        assert r['run_key'] == d.digest(manifest)
        assert manifest['prompt_sha256'][r['id']] == d.digest(prompt(qs[r['id']]))
        assert len(r['exposure']['skills']) == int(r['arm'] != 'free')
        citations, invalid = parse(r['reply'], meta['lines'])
        assert r['invalid_citations'] == invalid and r['citations'] == ([] if r['error'] else citations)
        assert all(r[k] == v for k, v in score(qs[r['id']], r['citations']).items())
    lines = ['# Complete Claude Code Markdown lookup', '',
        f"{len(meta['pages'])} official pages; {meta['bytes']:,} bytes; {len(qs)} questions per condition. "
        'Astra medium / requested priority. Only the plugin description differs between augmented conditions.', '',
        '| Condition | Tool used / returned hits | Reference coverage | All reference groups | Median seconds | Mean output tokens | Invalid citations | Agent errors |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        lines.append(f"| {arm} | {sum(r['audit']['invoked'] for r in rs)}/{len(rs)} / "
            f"{sum(r['audit']['returned_hits'] for r in rs)}/{len(rs)} | "
            f"{statistics.mean(r['reference_coverage'] for r in rs):.2%} | "
            f"{sum(r['all_references'] for r in rs)}/{len(rs)} | "
            f"{statistics.median(r['seconds'] for r in rs):.2f} | "
            f"{statistics.mean((r['usage'] or {}).get('output_tokens', 0) for r in rs):.0f} | "
            f"{sum(r['invalid_citations'] for r in rs)} | {sum(bool(r['error']) for r in rs)} |")
    lines += ['', 'Reference coverage counts predefined evidence lines inside valid citations, averaged per question. '
        'It does not grade answer correctness and may miss alternative valid evidence. '
        'Eight authored questions, one run each; exploratory, not a population estimate. '
        'Native tools remain unrestricted. Setup/warmup is excluded from timing; host I/O may vary. '
        'See [protocol](../CLAUDE_DOCS.md).']
    (OUT / 'summary.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if not args.report:
        run(args.jobs)
    report()
