"""The plugin ships what pyproject.toml says, and the skill matches the CLI."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / "skills" / "rankgrep" / "SKILL.md").read_text(encoding="utf-8")
LAUNCHER = "${CLAUDE_PLUGIN_ROOT}/bin/rankgrep"
GENERATED = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
]


def sync(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "sync_plugin.py"), *args], capture_output=True, text=True
    )


def test_generated_plugin_files_are_current():
    result = sync(REPO, "--check")

    assert result.returncode == 0, result.stderr


def test_check_names_every_stale_file_and_changes_nothing(tmp_path):
    for relative in ["pyproject.toml", "scripts/sync_plugin.py", *GENERATED]:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / relative, tmp_path / relative)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('version = "0.1.0"', 'version = "9.9.9"'))
    before = {p: (tmp_path / p).read_text() for p in GENERATED}

    stale = sync(tmp_path, "--check")
    after = {p: (tmp_path / p).read_text() for p in GENERATED}
    sync(tmp_path)

    assert stale.returncode == 1
    for relative in [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json"]:
        assert relative in stale.stderr
    assert after == before
    assert json.loads((tmp_path / ".codex-plugin/plugin.json").read_text())["version"] == "9.9.9"
    assert sync(tmp_path, "--check").returncode == 0


def test_skill_commands_parse_with_the_real_cli(run):
    commands = re.findall(re.escape(LAUNCHER) + r" ([^`\n]+)", SKILL)

    assert len(commands) >= 3
    for command in commands:
        argv = shlex.split(command.replace("<keywords>", "keywords").replace("<path>...", "docs"))
        result = run(*argv)
        assert "Run rankgrep --help" not in result.err, command
    assert "allowed-tools: Bash(" + LAUNCHER + " *)" in SKILL


def test_skill_output_example_has_the_real_keys(run):
    example = json.loads(re.search(r"^\{\"path\".*\}$", SKILL, re.MULTILINE).group())
    real = run("matcher", "docs-a").hits[0]

    assert list(example) == list(real)
    assert [type(v) for v in example.values()] == [type(v) for v in real.values()]


@pytest.mark.skipif(shutil.which("uv") is None, reason="the launcher needs uv")
def test_launcher_runs_from_another_directory(corpora, tmp_path):
    uv_cache = subprocess.run(["uv", "cache", "dir"], capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path / "xdg"), UV_CACHE_DIR=uv_cache, UV_OFFLINE="1")
    env.pop("VIRTUAL_ENV", None)

    result = subprocess.run(
        [str(REPO / "bin" / "rankgrep"), "-k", "1", "PreToolUse matcher", "docs-a"],
        cwd=corpora, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["path"] == "docs-a/hooks.md"
