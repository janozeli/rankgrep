"""Isolation contracts without model calls or account access."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('codex_isolation', Path(__file__).parents[1] / 'evals/codex_isolation.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    install = tmp_path / 'installation'
    install.mkdir()
    (install / 'uv').touch()
    monkeypatch.setattr(ci, 'installation', lambda tool: install)
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    (corpus / 'reference.txt').write_text('reference')
    return ci.Isolated(tmp_path / 'session', corpus)


def test_environment_is_an_allowlist_not_inherited(runtime, monkeypatch):
    monkeypatch.setenv('RANKGREP_TEST_HOST_SECRET', 'must not reach child')
    seen = {}
    monkeypatch.setattr(ci.subprocess, 'run', lambda *a, **kw: seen.update(kw))
    runtime.invoke(['--version'])
    assert set(seen['env']) == {'HOME', 'PATH', 'LANG'}
    assert 'mise' not in seen['env']['PATH']
    command = runtime.command([])
    assert '/plugin' not in command
    assert ['--ro-bind', '/etc', '/etc'] != command[command.index('--dir'):command.index('--dir')+3]


def test_unexpected_skill_or_tool_fails_before_model_execution(runtime, monkeypatch):
    context = [{'content': [{'text': '<skills_instructions>\n- personal: do stuff (file: /x/SKILL.md)\n</skills_instructions>'}]}]
    monkeypatch.setattr(runtime, 'invoke', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(context)))
    with pytest.raises(ValueError, match='unexpected skills'):
        runtime.prepare()
    context[:] = [{'type': 'additional_tools', 'tools': [{'name': 'personal_mcp'}]}]
    with pytest.raises(ValueError, match='tool namespace'):
        runtime.prepare()


def test_real_mounts_hide_host_files_and_protect_corpus(runtime, tmp_path):
    if not shutil.which('bwrap'):
        pytest.skip('Bubblewrap unavailable')
    # This check does not need credentials; replace the auth source with a blank fixture.
    fake_auth = tmp_path / 'auth-placeholder'
    fake_auth.touch()
    (runtime.home / '.codex/plugins').mkdir()
    (runtime.home / '.codex/config.toml').write_text(ci.CONFIG)
    runtime.frozen = True
    command = runtime.command([])[:-1]
    auth = str(Path.home() / '.codex/auth.json')
    command[command.index(auth)] = str(fake_auth)
    canary = tmp_path / 'host-only-secret'
    canary.write_text('not visible')
    script = f'''from pathlib import Path
assert not Path({str(canary)!r}).exists()
assert not Path('/plugin').exists()
assert Path('/workspace/docs/reference.txt').read_text() == 'reference'
try:
    (Path.home() / '.codex/plugins/unexpected').mkdir()
except OSError:
    pass
else:
    raise AssertionError('plugin directory is writable')
try:
    Path('/workspace/docs/reference.txt').write_text('changed')
except OSError:
    pass
else:
    raise AssertionError('corpus is writable')
'''
    r = subprocess.run(command + ['/usr/bin/python3', '-c', script], capture_output=True, text=True,
                       env={'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    if r.returncode and ('namespace' in r.stderr or 'Operation not permitted' in r.stderr):
        pytest.skip('host disallows Bubblewrap namespaces')
    assert r.returncode == 0, r.stderr


def test_late_account_plugin_download_is_rejected(runtime):
    remote = runtime.home / '.codex/plugins/cache/openai-curated-remote'
    remote.mkdir(parents=True)
    with pytest.raises(ValueError, match='unexpected plugin installation'):
        runtime.assert_local_plugins()


def test_plugin_and_config_mounts_are_frozen_after_setup(runtime):
    runtime.frozen = True
    command = runtime.command([])
    for name in ['plugins', 'config.toml']:
        source = str(runtime.home / '.codex' / name)
        index = command.index(source)
        assert command[index - 1] == '--ro-bind'
