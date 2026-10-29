"""Frozen optional-tool experiment: Terra medium, three arms, independent repeats."""
import argparse
import concurrent.futures
import io
import json
import random
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

import codex_audit as audit
import codex_freshstack as base
import codex_isolation as ci
import freshstack as f
import freshstack_data as d

MODEL = 'gpt-6.1-terra'
WORK = Path.home() / '.cache/rankgrep-evals/corpus-controls'
OUT = d.REPO / 'evals/controls-results'
ARMS = ('free', 'original', 'controls')
COMMITS = {'original': '31379def63c8eb4a21f0be3ecf5f1e2e52ff8a00',
           'controls': 'a66c2dd88cff48aec1ead5927106d64bf7a520d9'}
RESERVATION_SHA = '45bab069b9aee18ad01ea3bc5aa5a7dd7b3624247abcb1ea15e1e720eac8cec1'
RUNNERS = ('controls.py', 'controls_report.py', 'controls_audit.py', 'codex_isolation.py',
           'codex_freshstack.py', 'codex_audit.py', 'freshstack.py', 'freshstack_data.py')
ENV = {'HOME': str(Path.home()), 'PATH': '/opt/codex/bin:/opt/codex/codex-path:/opt/uv:/usr/bin:/bin',
       'LANG': 'C.UTF-8'}


def plugin_hashes(root):
    return {str(p.relative_to(root)): d.sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def plugins():
    result = {}
    for arm, commit in COMMITS.items():
        target = WORK / 'plugins' / arm
        # Reconstruct the expected snapshot separately, so an existing workspace
        # cannot silently become a different treatment.
        archive = subprocess.check_output(['git', 'archive', commit, 'bin', 'src', 'skills',
            'pyproject.toml', 'uv.lock', '.codex-plugin', '.agents', '.claude-plugin',
            'LICENSE', 'README.md', '.python-version'], cwd=d.REPO)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(source, filter='data')
            if not target.exists():
                shutil.copytree(source, target)
            assert plugin_hashes(target) == plugin_hashes(source), 'modified plugin snapshot'
        result[arm] = target
    return result


def expected_manifest(variants):
    reservation = OUT / 'reservation.json'
    assert d.sha(reservation) == RESERVATION_SHA, 'question reservation changed'
    return {'reservation_sha256': RESERVATION_SHA, 'reservation': json.loads(reservation.read_text()),
        'model': MODEL, 'effort': 'medium', 'service_tier_requested': 'priority',
        'config': ci.CONFIG.replace(ci.MODEL, MODEL), 'timeout_seconds': 1200, 'jobs': 2,
        'plugin_commits': COMMITS, 'plugins_sha256': {a: plugin_hashes(p) for a, p in variants.items()},
        'runner_sha256': {name: d.sha(d.REPO / 'evals' / name) for name in RUNNERS},
        'protocol_sha256': d.sha(d.REPO / 'evals/CONTROLS.md'),
        'codex': subprocess.check_output(['codex', '--version'], text=True).strip(),
        'cache_policy': 'Private per-session copy of dedicated warm seed; disposable cache removed after session. '
                        'Fresh home, work and rollout retained; repeats never resume sessions.',
        'budget_note': '1200-second invocation timeout; no max-turn or dollar cap. Priority requested, not verified backend tier.'}


def freeze():
    variants = plugins()
    manifest = expected_manifest(variants)
    path = OUT / 'manifest.json'
    if path.exists():
        assert json.loads(path.read_text()) == manifest, 'frozen protocol changed; use a new experiment'
    else:
        path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest, variants


def inputs(topic, manifest):
    corpus, questions = d.load(d.WORK, topic)
    reservation = manifest['reservation']
    assert d.source_rows(topic) == reservation['sources'][topic]
    excluded = set(json.loads((d.OUT / topic / 'selection.json').read_text())['selection'])
    prior = d.REPO / 'evals/adoption-results' / topic / 'selection.json'
    if prior.exists():
        excluded.update(json.loads(prior.read_text())['selection'])
    assert sorted(excluded) == reservation['exclusions'][topic]
    chosen = sorted((q for q in questions if q['query_id'] not in excluded),
                    key=lambda q: d.digest([reservation['seed'], topic, q['query_id']]))[:3]
    assert [q['query_id'] for q in chosen] == reservation['selection'][topic]
    assert {q['query_id']: d.digest(f.prompt(q)) for q in chosen} == reservation['prompts'][topic]
    return corpus, chosen


def warm(runtime):
    installed = next((runtime.home / '.codex/plugins/cache').rglob('bin/rankgrep'))
    assert plugin_hashes(installed.parents[1]) == plugin_hashes(runtime.plugin), 'installed plugin differs'
    launcher = Path.home() / installed.relative_to(runtime.home)
    result = subprocess.run(runtime.command([])[:-1] + [str(launcher), '-k', '1', 'warm', 'docs'],
        capture_output=True, text=True, timeout=1200, env=ENV)
    assert result.returncode in (0, 1) and 'Traceback' not in result.stderr, result.stderr


def seed_cache(topic, arm, plugin, corpus):
    root = WORK / 'warmup' / topic / arm
    cache = root / 'cache'
    if (root / 'ready.json').exists():
        assert json.loads((root / 'ready.json').read_text()) == plugin_hashes(plugin)
        return cache
    assert not (root / 'home').exists(), f'partial warmup: {root}'
    runtime = ci.Isolated(root, corpus, plugin, cache, model=MODEL)
    runtime.prepare()
    warm(runtime)
    (root / 'ready.json').write_text(json.dumps(plugin_hashes(plugin)))
    return cache


def copy_cache(seed, target):
    subprocess.run(['cp', '-a', '--reflink=auto', str(seed) + '/.', str(target)], check=True)
    # Copies may share disk extents but must never share writable dependency inodes.
    checks = []
    for source in sorted(seed.rglob('bm25s/__init__.py')):
        copied = target / source.relative_to(seed)
        a, b = source.stat(), copied.stat()
        assert (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)
        assert d.sha(source) == d.sha(copied)
        checks.append({'path': str(source.relative_to(seed)), 'sha256': d.sha(copied),
                       'seed_inode': [a.st_dev, a.st_ino], 'session_inode': [b.st_dev, b.st_ino]})
    assert checks, 'warm seed has no installed bm25s dependency'
    return checks


def run():
    import controls_audit

    manifest, variants = freeze()
    cache_root = WORK / 'session-caches'
    cache_root.mkdir(exist_ok=True)
    for topic in d.TOPICS:
        corpus, chosen = inputs(topic, manifest)
        f.verify_corpus(d.WORK, topic, corpus)
        folder = d.WORK / topic / 'library/docs'
        mapping = {d.filename(doc): doc['_id'] for doc in corpus}
        seeds = {arm: seed_cache(topic, arm, plugin, folder) for arm, plugin in variants.items()}
        tasks = [(q, arm, repeat) for q in chosen for arm in ARMS for repeat in range(2)]
        random.Random(f"{manifest['reservation']['seed']}:{topic}:order").shuffle(tasks)

        def one(task):
            q, arm, repeat = task
            root = WORK / 'runs' / topic / q['query_id'] / arm / str(repeat)
            cached = root / 'record.json'
            if cached.exists():
                row = json.loads(cached.read_text())
                assert row['run_key'] == d.digest(manifest), 'stale run'
                return row
            assert not (root / 'home').exists(), f'partial session: {root}; inspect before any retry'
            with tempfile.TemporaryDirectory(prefix=f'{topic}-{arm}-{repeat}-', dir=cache_root) as temporary:
                cache = Path(temporary)
                proof = copy_cache(seeds[arm], cache) if arm != 'free' else []
                runtime = ci.Isolated(root, folder, variants.get(arm), cache if arm != 'free' else None,
                                      model=MODEL)
                exposure = runtime.prepare()
                if arm != 'free':
                    warm(runtime)
                start = time.monotonic()
                status, events, raw = runtime.execute(f.prompt(q))
                row = base.record(topic, q, arm, events, raw, mapping, time.monotonic() - start, status)
                row.update(repeat=repeat, run_key=d.digest(manifest), cache_copy=proof, returncode=status,
                    exposure={'skills': exposure['skills'], 'tools_sha256': d.digest(exposure['tools']),
                              'context_sha256': d.sha(root / 'context.json')},
                    audit=audit.audit_session(root), controls=controls_audit.audit_controls(events),
                    rollout_sha256=d.sha(next((runtime.home / '.codex/sessions').rglob('*.jsonl'))))
                assert not any(c['runtime_error'] for c in row['audit']['launches']), 'dependency runtime failure'
                cached.write_text(json.dumps(row) + '\n')
            print(topic, q['query_id'], arm, repeat, row['coverage@20'], row['error'], flush=True)
            return row

        with concurrent.futures.ThreadPoolExecutor(max_workers=manifest['jobs']) as pool:
            rows = list(pool.map(one, tasks))
        assert len({r['exposure']['tools_sha256'] for r in rows}) == 1
        f.verify_corpus(d.WORK, topic, corpus)
        d.write_rows(OUT / topic / 'runs.jsonl', sorted(rows, key=lambda r: (r['query_id'], r['arm'], r['repeat'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'run', 'report'])
    args = parser.parse_args()
    if args.stage == 'freeze':
        frozen, _ = freeze()
        print('Frozen manifest:', d.digest(frozen))
    elif args.stage == 'run':
        run()
    else:
        from controls_report import report
        report()
