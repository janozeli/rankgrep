"""Recompute frozen scores and paired question-level estimates; no model calls."""
import json
import statistics

import numpy as np

import controls as c
import controls_audit
import codex_audit
import freshstack as f
import freshstack_data as d


def paired_deltas(rows, treatment, comparator):
    questions = sorted({(r['topic'], r['query_id']) for r in rows})
    deltas = []
    for topic, qid in questions:
        scores = {}
        for arm in (treatment, comparator):
            rs = [r for r in rows if (r['topic'], r['query_id'], r['arm']) == (topic, qid, arm)]
            assert len(rs) == 2 and {r['repeat'] for r in rs} == {0, 1}
            scores[arm] = statistics.mean(r['coverage@20'] for r in rs)
        deltas.append({'topic': topic, 'query_id': qid, 'delta': scores[treatment] - scores[comparator]})
    return deltas


def interval(deltas):
    # Resample question pairs within topic. Repeated sessions are not extra questions.
    rng = np.random.default_rng(20261029)
    groups = [[r['delta'] for r in deltas if r['topic'] == t] for t in sorted({r['topic'] for r in deltas})]
    draws = [rng.choice(group, size=(10000, len(group)), replace=True).mean(axis=1) for group in groups]
    bounds = np.quantile(np.mean(draws, axis=0), [0.025, 0.975])
    return [float(x) for x in bounds]


def validate():
    manifest, variants = c.freeze()
    rows, tool_hashes = [], set()
    for topic in d.TOPICS:
        corpus, questions = c.inputs(topic, manifest)
        qs = {q['query_id']: q for q in questions}
        mapping = {d.filename(doc): doc['_id'] for doc in corpus}
        rs = d.read_rows(c.OUT / topic / 'runs.jsonl')
        assert len(rs) == 18
        assert {(r['query_id'], r['arm'], r['repeat']) for r in rs} == {
            (q, a, n) for q in qs for a in c.ARMS for n in range(2)}
        for row in rs:
            root = c.WORK / 'runs' / topic / row['query_id'] / row['arm'] / str(row['repeat'])
            assert row == json.loads((root / 'record.json').read_text())
            assert row['run_key'] == d.digest(manifest)
            docs, invalid = f.selected(row['reply'], mapping)
            assert (docs if row['error'] is None else []) == row['documents']
            assert invalid == row['invalid_paths']
            assert all(row[k] == v for k, v in d.metrics(qs[row['query_id']], row['documents']).items())
            events = d.read_rows(root / 'stdout.jsonl')
            assert row['audit'] == codex_audit.audit_session(root)
            assert row['controls'] == controls_audit.audit_controls(events)
            assert row['exposure']['context_sha256'] == d.sha(root / 'context.json')
            context = json.loads((root / 'context.json').read_text())
            tools = [{'tools': m['tools']} for m in context if m.get('type') == 'additional_tools']
            assert d.digest(tools) == row['exposure']['tools_sha256']
            tool_hashes.add(row['exposure']['tools_sha256'])
            paths = list((root / 'home/.codex/sessions').rglob('*.jsonl'))
            assert len(paths) == 1 and d.sha(paths[0]) == row['rollout_sha256']
            raw = d.read_rows(paths[0])
            contexts = [r['payload'] for r in raw if r['type'] == 'turn_context']
            assert contexts and all(x['model'] == c.MODEL and x['effort'] == 'medium' for x in contexts)
            assert any(block.get('text') == f.prompt(qs[row['query_id']])
                       for event in raw if event['type'] == 'response_item'
                       and event['payload'].get('role') == 'user'
                       for block in event['payload'].get('content', [])), 'actual prompt differs'
            assert (root / 'home/.codex/config.toml').read_text() == manifest['config']
            entries = []
            for event in raw:
                payload = event.get('payload', {})
                if event['type'] == 'response_item' and payload.get('role') == 'developer':
                    for block in payload.get('content', []):
                        for catalog in block.get('text', '').split('<skills_instructions>')[1:]:
                            entries += [line for line in catalog.split('</skills_instructions>')[0].splitlines()
                                        if line.startswith('- ') and '(file:' in line]
            augmented = row['arm'] != 'free'
            assert len(entries) == len(row['exposure']['skills']) == int(augmented)
            assert all(e.startswith('- rankgrep:rankgrep:') for e in entries)
            installed = root / 'home/.codex/plugins/cache'
            if augmented:
                skill = next(installed.rglob('skills/rankgrep/SKILL.md'))
                assert c.plugin_hashes(skill.parents[2]) == manifest['plugins_sha256'][row['arm']]
                assert row['cache_copy'] and all(x['seed_inode'] != x['session_inode'] for x in row['cache_copy'])
            else:
                assert not installed.exists() or not list(installed.iterdir())
                assert row['cache_copy'] == []
            # Replay reply parsing, event usage, errors and metric calculation from the native log.
            replay = c.base.record(topic, qs[row['query_id']], row['arm'], events, raw, mapping,
                                   row['seconds'], row['returncode'])
            assert all(row[k] == v for k, v in replay.items())
        f.verify_corpus(d.WORK, topic, corpus)
        rows.extend(rs)
    assert len(tool_hashes) == 1
    return rows


def report():
    rows = validate()
    summary = {}
    for arm in c.ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        summary[arm] = {'sessions': len(rs),
            'coverage@20': statistics.mean(r['coverage@20'] for r in rs),
            'recall@20': statistics.mean(r['recall@20'] for r in rs),
            'median_seconds': statistics.median(r['seconds'] for r in rs),
            'mean_output_tokens': statistics.mean((r['usage'] or {}).get('output_tokens', 0) for r in rs),
            'mean_input_tokens': statistics.mean((r['usage'] or {}).get('input_tokens', 0) for r in rs),
            'invoked': sum(r['audit']['invoked'] for r in rs),
            'returned_hits': sum(r['audit']['returned_hits'] for r in rs),
            'statistics_returned': sum(r['controls']['statistics_returned'] for r in rs),
            'weights_requested': sum(r['controls']['weights_requested'] for r in rs),
            'errors': sum(r['error'] is not None for r in rs)}
        pairs = [[r['coverage@20'] for r in rs if (r['topic'], r['query_id']) == key]
                 for key in sorted({(r['topic'], r['query_id']) for r in rs})]
        summary[arm]['mean_absolute_repeat_gap'] = statistics.mean(abs(a - b) for a, b in pairs)
    comparisons = {}
    for other in ('original', 'free'):
        deltas = paired_deltas(rows, 'controls', other)
        comparisons[other] = {'mean_delta': statistics.mean(x['delta'] for x in deltas),
                              'bootstrap_95': interval(deltas), 'questions': deltas}
    primary = comparisons['original']
    screening = (primary['mean_delta'] >= .05 and primary['bootstrap_95'][0] > 0
        and comparisons['free']['mean_delta'] >= 0
        and summary['controls']['median_seconds'] <= 1.25 * summary['original']['median_seconds']
        and summary['controls']['mean_output_tokens'] <= 1.25 * summary['original']['mean_output_tokens'])
    result = {'arms': summary, 'controls_minus': comparisons, 'screening_bar_met': screening}
    (c.OUT / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['# Terra: optional corpus controls', '',
        '15 reserved questions, five topics, two independent sessions per arm/question. '
        'No required tool use. Primary metric is upstream evidence coverage, not answer accuracy.', '',
        '| Arm | Coverage@20 | Recall@20 | Used / hits | Stats returned | Weights requested | Median seconds | Mean output tokens | Errors |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm, s in summary.items():
        lines.append(f"| {arm} | {s['coverage@20']:.2%} | {s['recall@20']:.2%} | "
            f"{s['invoked']}/30 / {s['returned_hits']}/30 | {s['statistics_returned']}/30 | "
            f"{s['weights_requested']}/30 | {s['median_seconds']:.2f} | {s['mean_output_tokens']:.0f} | {s['errors']} |")
    lines += ['', '## Paired coverage differences', '',
              'Repeats are averaged within question before topic-stratified paired bootstrap (10,000 draws). '
              'Intervals are descriptive for this small reserved sample, not proof of broad generalization.', '']
    for other, delta in comparisons.items():
        lo, hi = delta['bootstrap_95']
        lines.append(f"- controls minus {other}: {delta['mean_delta'] * 100:+.2f} pp; 95% interval [{lo * 100:+.2f}, {hi * 100:+.2f}] pp.")
    lines += ['', f"Predeclared screening bar met: **{screening}**.", '',
              'Mean absolute coverage gap between independent repeats: ' + ', '.join(
                  f"{arm} {s['mean_absolute_repeat_gap'] * 100:.2f} pp" for arm, s in summary.items()) + '.']
    lines += ['', '## Per-question repeat means', '', '| Topic | Question | free | original | controls |', '| --- | --- | --- | --- | --- |']
    for topic, qid in sorted({(r['topic'], r['query_id']) for r in rows}):
        means = [statistics.mean(r['coverage@20'] for r in rows if (r['topic'], r['query_id'], r['arm']) == (topic, qid, arm)) for arm in c.ARMS]
        lines.append(f"| {topic} | {qid} | " + ' | '.join(f'{m:.2%}' for m in means) + ' |')
    lines += ['', 'Upstream pooled, model-generated labels can omit valid evidence. The controls condition changes '
        'both CLI capabilities and their skill documentation, so it does not isolate the effect of either flag. '
        'Control usage counts direct recognized native commands, not arbitrary scripts or aliases. Weights requested '
        'does not imply a successful weighted search. Costs exclude warmup, installation and index construction; '
        'latency and token usage are descriptive. Requested priority is not independently verified as backend tier. '
        'See [frozen protocol](../CONTROLS.md).']
    (c.OUT / 'summary.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(result['arms'], indent=2))


if __name__ == '__main__':
    report()
