import sys
import json
from pathlib import Path

# The evaluation modules are scripts, not a runtime package.
sys.path.insert(0, str(Path(__file__).parents[1] / 'evals'))
import codex_audit as audit


def test_native_invocation_is_not_a_skill_or_launcher_file_read():
    assert audit.invokes_rankgrep("/bin/bash -lc '/plugin/bin/rankgrep query docs | head'")
    assert audit.invokes_rankgrep("/bin/bash -lc 'cd docs; /plugin/bin/rankgrep query .'")
    assert audit.invokes_rankgrep('/bin/bash -lc "cd docs\n/plugin/bin/rankgrep query ."')
    assert not audit.invokes_rankgrep("/bin/bash -lc 'cat /plugin/bin/rankgrep'")
    assert not audit.invokes_rankgrep("/bin/bash -lc 'echo /plugin/bin/rankgrep'")
    assert not audit.invokes_rankgrep("/bin/bash -lc 'cat /plugin/skills/rankgrep/SKILL.md'")


def test_dependency_failure_is_not_a_normal_no_hits_exit(tmp_path):
    events = [{'type': 'item.completed', 'item': {
        'type': 'command_execution', 'command': '/plugin/bin/rankgrep query docs',
        'exit_code': 1, 'aggregated_output': output}} for output in
        ['', "Traceback (most recent call last):\nModuleNotFoundError: No module named 'bm25s.utils'"]]
    (tmp_path / 'stdout.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
    result = audit.audit_session(tmp_path)
    assert [c['runtime_error'] for c in result['launches']] == [False, True]
    assert result['invoked'] and not result['returned_hits']
