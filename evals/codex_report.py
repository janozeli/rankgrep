"""Validate and summarize the isolated Codex replication without model calls."""
import json
import statistics
from pathlib import Path

import codex_freshstack as runner
import freshstack as f
import freshstack_data as d


def report():
    audit_rows = d.read_rows(runner.OUT / 'execution-audit.jsonl')
    audits = {(r['topic'], r['query_id'], r['arm']): r for r in audit_rows}
    assert len(audits) == len(audit_rows) == 100
    groups = {}
    tools = set()
    for topic in d.TOPICS:
        root = runner.OUT / topic
        meta = json.loads((root / 'selection.json').read_text())
        original = json.loads((d.OUT / topic / 'selection.json').read_text())
        assert meta['selection'] == original['selection']
        _, questions = d.load(d.WORK, topic)
        qs = {q['query_id']: q for q in questions}
        rows = d.read_rows(root / 'runs.jsonl')
        for arm in f.ARMS:
            rs = [r for r in rows if r['arm'] == arm]
            assert len(rs) == 10 and {r['query_id'] for r in rs} == set(meta['selection'])
        for r in rows:
            audit = audits[(topic, r['query_id'], r['arm'])]
            assert r['run_key'] == audit['run_key'] == d.digest(meta)
            r['invoked'], r['returned_hits'] = audit['invoked'], audit['returned_hits']
            assert meta['prompt_sha256'][r['query_id']] == d.digest(f.prompt(qs[r['query_id']]))
            assert all(r[k] == v for k, v in d.metrics(qs[r['query_id']], r['documents']).items())
            assert bool(r['exposure']['skills']) == (r['arm'] == 'free+rankgrep')
            tools.add(r['exposure']['tools_sha256'])
        groups[topic] = rows
    assert len(tools) == 1
    groups['all'] = [r for rows in groups.values() for r in rows]
    lines = ['# Codex Astra medium / priority: original conditions', '',
             'Original questions, prompt, plugin and scoring. Isolated fresh sessions; no adoption interventions. '
             'See [protocol and harness differences](../CODEX.md).', '',
             '| Topic | Arm | Questions | Coverage@20 | Recall@20 | Invoked / returned hits | Seconds, median | Errors |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for topic, rows in groups.items():
        for arm in f.ARMS:
            rs = [r for r in rows if r['arm'] == arm]
            lines.append(f'| {topic} | {arm} | {len(rs)} | '
                f"{statistics.mean(r['coverage@20'] for r in rs):.2%} | "
                f"{statistics.mean(r['recall@20'] for r in rs):.2%} | "
                f"{sum(r['invoked'] for r in rs)}/{len(rs)} / {sum(r['returned_hits'] for r in rs)}/{len(rs)} | "
                f"{statistics.median(r['seconds'] for r in rs):.2f} | "
                f"{sum(r['error'] is not None for r in rs)} |")
    lines += ['', 'Invocation is audited from native shell execution events, excluding reads or echoes of the launcher. '
              'Returned hits requires exit code 0 and structured rankgrep results in stdout. Timings exclude corpus-wide setup; narrower searches may build additional indexes. '
              'One observation per question/arm, not a stable causal ranking. Priority is the requested service tier. '
              'Model token usage is retained; dollar costs and the former Claude budget are not claimed equivalent.']
    (runner.OUT / 'summary.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    report()
