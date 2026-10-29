"""Short paired description experiments, after the frozen Codex replication."""
import argparse
import concurrent.futures
import json
import random
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import codex_audit as audit
import codex_freshstack as base
import codex_isolation as ci
import freshstack as f
import freshstack_data as d

WORK = base.WORK.parent / 'codex-adoption-v2'
OUT = d.REPO / 'evals/adoption-results'
TOPICS = ('angular', 'godot', 'langchain')
SEED = 'codex-adoption-v1'
DESCRIPTIONS = {
    'original': None,
    'capabilities': 'Local documentation search across many files. BM25 ranks sections by keyword relevance and returns source paths, exact line ranges, and matching snippets. Supports unfamiliar wording and queries spanning several concepts; exact-string search remains available through rg.',
    'unix': 'A composable Unix search command for local text. rankgrep QUERY PATH... emits ranked JSONL with paths and line ranges; -k controls result count, --files-from - accepts a file list on stdin, and ordinary exit codes support shell pipelines. Works alongside rg, find, sed, and scripts.',
    'output': 'Ranked evidence lookup in local documentation and source text. Each JSONL result contains path, start, end, score, a matching snippet, and matched query terms. Keyword retrieval with BM25, automatic cached indexing, and no model calls or embeddings.',
}


def select(topic, questions):
    excluded = set(json.loads((d.OUT / topic / 'selection.json').read_text())['selection'])
    available = [q for q in questions if q['query_id'] not in excluded]
    # Nugget count is a breadth proxy, not a validated difficulty or vagueness label.
    return [min((q for q in available if (len(q['nuggets']) >= 4) == broad),
                key=lambda q: d.digest([SEED, topic, q['query_id']])) for broad in (False, True)]


def plugins():
    source = base.plugin_snapshot()
    result = {}
    for name, description in DESCRIPTIONS.items():
        target = WORK / 'plugins' / name
        if not target.exists():
            shutil.copytree(source, target)
        skill = source / 'skills/rankgrep/SKILL.md'
        text = skill.read_text()
        if description:
            text = '\n'.join('description: ' + description if line.startswith('description: ') else line
                             for line in text.splitlines()) + '\n'
        (target / 'skills/rankgrep/SKILL.md').write_text(text)
        # Only frontmatter description may differ; engine, launcher and skill body stay pinned.
        for path in source.rglob('*'):
            if path.is_file() and path != skill:
                assert path.read_bytes() == (target / path.relative_to(source)).read_bytes()
        assert text.split('---', 2)[2] == skill.read_text().split('---', 2)[2]
        result[name] = target
    return result


def run(jobs):
    # Fail closed if phase A is incomplete, rather than silently racing the replication.
    assert (base.OUT / 'summary.md').exists()
    assert len(d.read_rows(base.OUT / 'execution-audit.jsonl')) == 100
    variants = plugins()
    manifests, inputs = {}, {}
    for topic in TOPICS:
        corpus, questions = d.load(d.WORK, topic)
        f.verify_corpus(d.WORK, topic, corpus)
        chosen = select(topic, questions)
        manifest = {'model': ci.MODEL, 'effort': 'medium', 'service_tier_requested': 'priority',
            'config': ci.CONFIG, 'seed': SEED, 'selection': [q['query_id'] for q in chosen],
            'nugget_counts': {q['query_id']: len(q['nuggets']) for q in chosen},
            'prompt_sha256': {q['query_id']: d.digest(f.prompt(q)) for q in chosen},
            'descriptions': DESCRIPTIONS, 'plugin_commit': base.PLUGIN_COMMIT,
            'skill_sha256': {k: d.sha(v / 'skills/rankgrep/SKILL.md') for k, v in variants.items()},
            'sources': d.source_rows(topic), 'warm_cache': True, 'timeout_seconds': 1200,
            'cache_policy': 'Private session copy of phase-A topic cache; native installed launcher warmed before timing.',
            'codex': json.loads((base.OUT / topic / 'selection.json').read_text())['codex'],
            'baseline_runs_sha256': {t: d.sha(base.OUT / t / 'runs.jsonl') for t in d.TOPICS},
            'runner_sha256': {n: d.sha(d.REPO / 'evals' / n) for n in
                ['codex_adoption.py', 'codex_isolation.py', 'codex_freshstack.py', 'codex_audit.py']}}
        out = OUT / topic
        out.mkdir(parents=True, exist_ok=True)
        path = out / 'selection.json'
        if path.exists():
            assert json.loads(path.read_text()) == manifest, 'stale manifest; use a new workspace'
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        manifests[topic] = manifest
        inputs[topic] = (corpus, chosen)
    # Freeze every selection and treatment before the first model call.
    for topic, (corpus, chosen) in inputs.items():
        manifest = manifests[topic]
        mapping = {d.filename(doc): doc['_id'] for doc in corpus}
        tasks = [(q, name) for q in chosen for name in DESCRIPTIONS]
        random.Random(f'{SEED}:{topic}:order').shuffle(tasks)

        def one(task):
            q, name = task
            root = WORK / topic / q['query_id'] / name
            cached = root / 'record.json'
            if cached.exists():
                row = json.loads(cached.read_text())
                assert row['run_key'] == d.digest(manifest), 'stale run'
                return row
            assert not (root / 'home').exists(), f'partial session: {root}'
            cache = root / 'cache'
            cache.mkdir(parents=True)
            # Independent inodes (or copy-on-write clones): uv may synchronize its environment.
            # Never share a mutable runtime environment between concurrently running agents.
            subprocess.run(['cp', '-a', '--reflink=auto', str(base.WORK / topic / 'cache') + '/.', str(cache)], check=True)
            runtime = ci.Isolated(root, d.WORK / topic / 'library/docs', variants[name], cache)
            exposure = runtime.prepare()
            installed = next((runtime.home / '.codex/plugins/cache').rglob('bin/rankgrep'))
            launcher = Path.home() / installed.relative_to(runtime.home)
            warm = subprocess.run(runtime.command([])[:-1] + [str(launcher), '-k', '1', 'warm', 'docs'],
                capture_output=True, text=True, timeout=1200,
                env={'HOME': str(Path.home()), 'PATH': '/opt/codex/bin:/opt/codex/codex-path:/opt/uv:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
            assert warm.returncode in (0, 1) and 'Traceback' not in warm.stderr, warm.stderr
            start = time.monotonic()
            status, events, raw = runtime.execute(f.prompt(q))
            row = base.record(topic, q, name, events, raw, mapping, time.monotonic() - start, status)
            row.update(run_key=d.digest(manifest), exposure={
                'skills': exposure['skills'], 'tools_sha256': d.digest(exposure['tools']),
                'context_sha256': d.sha(root / 'context.json')}, audit=audit.audit_session(root))
            assert not any(c['runtime_error'] for c in row['audit']['launches']), 'runtime failure: inspect session before retry'
            cached.write_text(json.dumps(row) + '\n')
            print(topic, q['query_id'], name, row['audit']['invoked'], row['coverage@20'], row['error'], flush=True)
            return row

        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            rows = list(pool.map(one, tasks))
        f.verify_corpus(d.WORK, topic, corpus)
        d.write_rows(OUT / topic / 'runs.jsonl', sorted(rows, key=lambda r: (r['query_id'], r['arm'])))


def report():
    rows = []
    native_tools = json.loads((base.OUT / 'angular/runs.jsonl').read_text().splitlines()[0])['exposure']['tools_sha256']
    for topic in TOPICS:
        meta = json.loads((OUT / topic / 'selection.json').read_text())
        _, questions = d.load(d.WORK, topic)
        chosen = select(topic, questions)
        assert [q['query_id'] for q in chosen] == meta['selection']
        qs = {q['query_id']: q for q in chosen}
        rs = d.read_rows(OUT / topic / 'runs.jsonl')
        assert len(rs) == 8
        assert {(r['query_id'], r['arm']) for r in rs} == {(q, a) for q in qs for a in DESCRIPTIONS}
        for r in rs:
            assert r['run_key'] == d.digest(meta)
            assert meta['prompt_sha256'][r['query_id']] == d.digest(f.prompt(qs[r['query_id']]))
            assert all(r[k] == v for k, v in d.metrics(qs[r['query_id']], r['documents']).items())
            assert r['exposure']['tools_sha256'] == native_tools and len(r['exposure']['skills']) == 1
        rows += rs
    lines = ['# Exploratory description experiments', '',
        'Six held-out questions, one observation per condition, Astra medium / requested priority. '
        'All agents have the optional plugin and unrestricted native tools. Only its catalog description changes.', '',
        '| Description | Invoked | Returned hits | Coverage@20 | Recall@20 | Median seconds | Mean output tokens | Errors |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name in DESCRIPTIONS:
        rs = [r for r in rows if r['arm'] == name]
        lines.append(f"| {name} | {sum(r['audit']['invoked'] for r in rs)}/6 | "
            f"{sum(r['audit']['returned_hits'] for r in rs)}/6 | "
            f"{statistics.mean(r['coverage@20'] for r in rs):.2%} | "
            f"{statistics.mean(r['recall@20'] for r in rs):.2%} | "
            f"{statistics.median(r['seconds'] for r in rs):.2f} | "
            f"{statistics.mean((r['usage'] or {}).get('output_tokens', 0) for r in rs):.0f} | "
            f"{sum(r['error'] is not None for r in rs)} |")
    lines += ['', 'Selection uses a fixed hash within two nugget-count strata per topic (at most three / at least four), '
        'excluding all original benchmark questions. Nugget count is only a breadth proxy. '
        'The sample is small and exploratory, without independent repeats. No winner or adoption improvement is established. '
        'Each session has a private copy of the phase-A cache, warmed through the installed launcher; timing is descriptive. '
        'Upstream pooled, model-generated labels may omit valid evidence. The original skill body is unchanged, including its existing guidance. '
        'Treatments add no tool-first requirement, tool restriction, task hint, or answer evidence.']
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
