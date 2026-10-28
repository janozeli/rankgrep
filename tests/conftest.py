"""Run the CLI the way an agent does and read what it reads.

``run`` calls rankgrep in process, inside a fresh copy of tests/corpora with a
private cache, and returns the exit code, the parsed JSON lines and stderr.
``cli`` does the same in a real subprocess. No test imports a private module.
"""

import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import rankgrep

CORPORA = Path(__file__).parent / "corpora"


@dataclass(frozen=True)
class Run:
    code: int
    hits: list[dict]
    err: str
    out: str


def _parse(code: int, out: str, err: str) -> Run:
    return Run(code, [json.loads(line) for line in out.splitlines()], err, out)


@pytest.fixture
def corpora(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "corpora"
    shutil.copytree(CORPORA, root)
    monkeypatch.chdir(root)
    monkeypatch.setenv("RANKGREP_CACHE_DIR", str(tmp_path / "cache"))
    return root


@pytest.fixture
def run(corpora, monkeypatch, capsys):
    def run(*argv: str, stdin: str = "") -> Run:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = rankgrep.main(list(argv))
        captured = capsys.readouterr()
        return _parse(code, captured.out, captured.err)

    return run


@pytest.fixture
def cli(corpora):
    def cli(*argv: str, env: dict[str, str] | None = None) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "rankgrep", *argv],
            env=env or dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    return cli


def finish(process: subprocess.Popen) -> Run:
    out, err = process.communicate(timeout=60)
    return _parse(process.returncode, out, err)


@pytest.fixture
def lines_at(corpora):
    """What an agent gets when it reads a hit's range with ``sed -n``."""

    def lines_at(hit: dict, start: int | None = None, end: int | None = None) -> list[str]:
        first, last = start or hit["start"], end or hit["end"]
        out = subprocess.run(
            ["sed", "-n", f"{first},{last}p", hit["path"]], capture_output=True, check=True
        ).stdout
        return out.decode("utf-8", errors="replace").split("\n")[:-1]

    return lines_at
