"""Which files make up a corpus, and how their text is read.

A corpus is the paths the caller passes. Their canonical absolute paths are
its identity, so ``docs`` and ``/home/me/docs`` share one index, and the paths
as typed are how hits are displayed.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024 * 1024
SNIFF_BYTES = 8192
JUNK_DIRS = frozenset({"node_modules", "__pycache__", "venv", "site-packages"})


@dataclass(frozen=True, slots=True)
class Root:
    given: str
    path: Path


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class Corpus:
    """The files one search covers, as they are on disk right now.

    ``roots`` keeps argument order without duplicates. ``files`` is sorted by
    path, unique, regular, not hidden below its root, outside JUNK_DIRS and at
    most MAX_FILE_BYTES. Text or binary is decided at build time, so selecting
    costs one stat per file.
    """

    roots: tuple[Root, ...]
    files: tuple[SourceFile, ...]
    oversized: int

    def display(self, path: Path) -> str:
        for root in self.roots:
            if path.is_relative_to(root.path):
                return os.path.normpath(os.path.join(root.given, path.relative_to(root.path)))
        return str(path)


@dataclass(frozen=True, slots=True)
class MissingPaths:
    paths: tuple[str, ...]


def select(paths: Sequence[str]) -> Corpus | MissingPaths:
    """Resolve and walk the named paths.

    A named file is included even when hidden. Directories are walked without
    following directory symlinks, so there are no cycles. .gitignore is not
    read on purpose: downloaded doc sets usually live in ignored folders.
    """
    missing = tuple(p for p in paths if not os.path.exists(p))
    if missing:
        return MissingPaths(missing)
    roots: list[Root] = []
    for given in paths:
        path = Path(given).resolve()
        if all(root.path != path for root in roots):
            roots.append(Root(given, path))
    found: dict[Path, os.stat_result] = {}
    for root in roots:
        if root.path.is_dir():
            _walk(root.path, found)
        else:
            found[root.path] = root.path.stat()
    files = []
    oversized = 0
    for path, stat in sorted(found.items(), key=lambda item: str(item[0])):
        if stat.st_size > MAX_FILE_BYTES:
            oversized += 1
        else:
            files.append(SourceFile(path, stat.st_size, stat.st_mtime_ns))
    return Corpus(tuple(roots), tuple(files), oversized)


def _walk(directory: Path, found: dict[Path, os.stat_result]) -> None:
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith(".") or entry.name in JUNK_DIRS:
                continue
            if entry.is_dir(follow_symlinks=False):
                _walk(Path(entry.path), found)
            elif entry.is_file():
                found[Path(entry.path)] = entry.stat()


def read_lines(path: Path) -> list[str] | None:
    """Return the file's lines, or None when it is binary or unreadable.

    Binary means a NUL byte in the first SNIFF_BYTES, the test git uses.
    Text is UTF-8 with a cp1252 fallback. Lines split on "\\n" only, because
    ``str.splitlines`` also splits on form feeds and U+2028 and would shift
    line numbers away from what editors and ``sed -n`` show.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:SNIFF_BYTES]:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]
