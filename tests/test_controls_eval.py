"""Audit actual command use, independent caches and question-level pairing."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'evals'))
import controls
import controls_audit as audit
import controls_report as report


def test_controls_audit_ignores_mentions_and_extracts_native_options():
    def event(command, output=''):
        return {'type': 'item.completed', 'item': {'type': 'command_execution',
            'command': command, 'exit_code': 0, 'aggregated_output': output}}
    statistics = {'term': 'hooks', 'df': 2, 'section_count': 100, 'fraction': .02, 'idf': 3.7}
    events = [event('cat /plugin/bin/rankgrep'), event("echo 'rankgrep --stats hooks docs'"),
        event("/bin/bash -lc '/plugin/bin/rankgrep --stats hooks docs | head'", json.dumps(statistics)),
        event('/plugin/bin/rankgrep --weight "hook matcher" 0.5 retry docs')]
    found = audit.audit_controls(events)
    assert len(found['commands']) == 2
    assert found['stats_requested'] and found['statistics_returned'] and found['weights_requested']
    assert found['commands'][0]['statistics'] == [statistics]
    assert found['commands'][1]['calls'][0]['weights'] == [{'text': 'hook matcher', 'factor': '0.5'}]
    assert audit.flags(['rankgrep', '--', '--stats', '--weight', 'hook', '2']) == {
        'stats_requested': False, 'weights': []}


def test_cache_copy_does_not_share_writable_dependency_files(tmp_path):
    seed, target = tmp_path / 'seed', tmp_path / 'session'
    dependency = seed / 'uv/env/site-packages/bm25s/__init__.py'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('original')
    target.mkdir()
    proof = controls.copy_cache(seed, target)
    (target / dependency.relative_to(seed)).write_text('changed')
    assert dependency.read_text() == 'original'
    assert len(proof) == 1 and proof[0]['seed_inode'] != proof[0]['session_inode']


def test_repeats_are_averaged_before_question_level_pairing():
    rows = []
    for qid, a, b in [('one', [.8, 1.0], [.4, .6]), ('two', [0, .2], [.4, .6])]:
        for arm, scores in [('controls', a), ('original', b)]:
            rows += [{'topic': 'example', 'query_id': qid, 'arm': arm, 'repeat': n, 'coverage@20': x}
                     for n, x in enumerate(scores)]
    deltas = report.paired_deltas(rows, 'controls', 'original')
    assert [d['delta'] for d in deltas] == pytest.approx([.4, -.4])
    assert report.interval(deltas) == pytest.approx([-.4, .4])
    rows[-1]['repeat'] = 0
    with pytest.raises(AssertionError):
        report.paired_deltas(rows, 'controls', 'original')


def test_report_accepts_only_expected_native_plugin_configuration():
    base = controls.ci.CONFIG.replace(controls.ci.MODEL, controls.MODEL)
    additions = '\n[plugins."rankgrep@rankgrep"]\nenabled = true\n' \
                '[marketplaces.rankgrep]\nsource_type = "local"\nsource = "/plugin"\n'
    report.validate_config(base, base, False)
    report.validate_config(base + additions, base, True)
    for actual, augmented in [(base, True), (base + additions, False),
                              (base + additions.replace('/plugin', '/host'), True),
                              (base + additions + '[plugins.unexpected]\nenabled=true\n', True)]:
        with pytest.raises(AssertionError, match='unexpected native configuration'):
            report.validate_config(actual, base, augmented)
