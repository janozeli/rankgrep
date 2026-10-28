"""Where saved indexes live, and how processes share them without locks.

    <cache root>/<corpus key>/<fingerprint>/        an immutable snapshot
    <cache root>/<corpus key>/.tmp-<pid>-<random>/  a build in progress, or crash debris

The fingerprint hashes rankgrep's source, the bm25s version and every corpus
file's (path, size, mtime_ns). A search computes it from the files as they
are now and opens exactly that directory, so a missing directory is the
whole staleness check.

No process writes a path another process reads. A build writes into its own
.tmp directory and renames it to the fingerprint. Rename is atomic, so a
snapshot is absent or complete. When two processes race, the loser's rename
fails, it drops its .tmp directory and uses the winner's snapshot. There is
no lock for a crash to leave behind.
"""

import functools
import hashlib
import importlib.metadata
import os
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from rankgrep._corpus import Corpus

ENV_CACHE_DIR = "RANKGREP_CACHE_DIR"
STALE_TMP_SECONDS = 3600


def snapshots(corpus: Corpus) -> Iterator[Path]:
    """Existing snapshots for the corpus as it is now, in cache-root order.
    Every root is checked, so a snapshot built outside a sandbox is reused
    inside one that can only write to the temp directory."""
    key, fingerprint = _corpus_key(corpus), _fingerprint(corpus)
    for root in _cache_roots():
        snapshot = root / key / fingerprint
        if snapshot.is_dir():
            yield snapshot


def publish(corpus: Corpus, write: Callable[[Path], None]) -> bool:
    """Save a snapshot for the corpus's fingerprint into the first writable
    root. Return whether a snapshot exists afterwards."""
    key, fingerprint = _corpus_key(corpus), _fingerprint(corpus)
    for root in _cache_roots():
        folder = root / key
        target = folder / fingerprint
        tmp = folder / f".tmp-{os.getpid()}-{secrets.token_hex(4)}"
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder.mkdir(exist_ok=True)
            tmp.mkdir()
            write(tmp)
            tmp.rename(target)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            if target.is_dir():
                return True
            continue
        _prune(folder, keep=fingerprint)
        return True
    return False


def discard(snapshot: Path) -> None:
    """Remove a snapshot that failed to load. It is renamed to a .tmp name
    first, so no reader opens it half-deleted under its fingerprint."""
    doomed = snapshot.with_name(f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        snapshot.rename(doomed)
    except OSError:
        return
    shutil.rmtree(doomed, ignore_errors=True)


def _prune(folder: Path, keep: str) -> None:
    now = time.time()
    for entry in folder.iterdir():
        try:
            stale_tmp = entry.name.startswith(".tmp-") and now - entry.stat().st_mtime > STALE_TMP_SECONDS
        except OSError:
            continue
        if stale_tmp or not (entry.name.startswith(".tmp-") or entry.name == keep):
            shutil.rmtree(entry, ignore_errors=True)


def _cache_roots() -> list[Path]:
    """$RANKGREP_CACHE_DIR alone when set. Otherwise the platform cache
    directory, then a per-user directory in the temp dir, which sandboxes
    such as Codex's workspace-write mode can usually write."""
    explicit = os.environ.get(ENV_CACHE_DIR)
    if explicit:
        return [Path(explicit)]
    if sys.platform == "win32":
        user_cache = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        user_cache = Path.home() / "Library" / "Caches"
    else:
        user_cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    if not hasattr(os, "getuid"):
        return [user_cache / "rankgrep", Path(tempfile.gettempdir()) / "rankgrep"]
    shared = Path(tempfile.gettempdir()) / f"rankgrep-{os.getuid()}"
    try:
        foreign = shared.stat().st_uid != os.getuid()
    except OSError:
        foreign = False
    return [user_cache / "rankgrep"] + ([] if foreign else [shared])


def _corpus_key(corpus: Corpus) -> str:
    roots = "\0".join(sorted(str(root.path) for root in corpus.roots))
    return hashlib.sha256(roots.encode()).hexdigest()[:16]


def _fingerprint(corpus: Corpus) -> str:
    digest = hashlib.sha256(_code_digest().encode())
    for file in corpus.files:
        digest.update(f"{file.path}\0{file.size}\0{file.mtime_ns}\n".encode())
    return digest.hexdigest()[:16]


@functools.cache
def _code_digest() -> str:
    """Hash of every module in this package plus the bm25s version, so any
    change to tokenizing or chunking invalidates saved indexes with no
    hand-bumped schema number."""
    digest = hashlib.sha256(importlib.metadata.version("bm25s").encode())
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.read_bytes())
    return digest.hexdigest()
