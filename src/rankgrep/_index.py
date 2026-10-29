"""BM25 over the sections of one corpus state, and the search that reads it.
The only module that imports bm25s."""

import enum
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import bm25s
import numpy as np

from rankgrep import _store
from rankgrep._chunks import chunk, is_markdown
from rankgrep._corpus import Corpus, read_lines
from rankgrep._terms import terms

SNIPPET_CHARS = 160
SECTIONS_FILE = "sections.json"
_WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class Query:
    """Non-empty, distinct terms in query order. ``parse`` returns None
    instead of an empty Query, because bm25s raises on an empty term list."""

    terms: tuple[str, ...]

    @classmethod
    def parse(cls, text: str) -> "Query | None":
        unique = tuple(dict.fromkeys(terms(text)))
        return cls(unique) if unique else None


@dataclass(frozen=True, slots=True)
class Hit:
    """One ranked section, field for field what the CLI prints. ``line`` is
    the line with the most distinct query terms, earliest first, skipping the
    section's own heading unless nothing else matches. ``text`` is that line,
    whitespace collapsed, cut to SNIPPET_CHARS around its first match."""

    path: Path
    start: int
    end: int
    score: float
    section: str
    line: int
    text: str
    matched: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Result:
    """``hits`` best first, ties in corpus order. ``unknown`` lists query
    terms found nowhere; when ``hits`` is empty it is every query term."""

    hits: tuple[Hit, ...]
    unknown: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TermStats:
    """Frequency in indexed sections, including inherited heading terms.

    An absent term has no usable IDF contribution, represented by None.
    """

    term: str
    df: int
    section_count: int
    fraction: float
    idf: float | None


@dataclass(frozen=True, slots=True)
class Chunk:
    """A row of the section table. Its position is its bm25s document id."""

    file: int
    start: int
    end: int
    section: str


@dataclass(frozen=True, slots=True)
class NoText:
    binary: int
    oversized: int


@dataclass(frozen=True, slots=True, eq=False)
class Index:
    """BM25 over every section of one corpus state. Never empty: ``build``
    returns NoText instead. ``chunks`` is in (path, start) order, so stable
    ranking ties fall back to reading order."""

    files: tuple[Path, ...]
    chunks: tuple[Chunk, ...]
    skipped_binary: int
    _bm25: bm25s.BM25

    @classmethod
    def build(cls, corpus: Corpus) -> "Index | NoText":
        files: list[Path] = []
        chunks: list[Chunk] = []
        tokens: list[list[str]] = []
        binary = 0
        for source in corpus.files:
            lines = read_lines(source.path)
            if lines is None:
                binary += 1
                continue
            for span in chunk(lines, is_markdown(source.path, lines)):
                section_terms = terms(span.section) + terms("\n".join(lines[span.start - 1 : span.end]))
                if section_terms:
                    chunks.append(Chunk(len(files), span.start, span.end, span.section))
                    tokens.append(section_terms)
            files.append(source.path)
        if not chunks:
            return NoText(binary, corpus.oversized)
        bm25 = bm25s.BM25()
        bm25.index(tokens, show_progress=False)
        return cls(tuple(files), tuple(chunks), binary, bm25)

    @classmethod
    def load(cls, directory: Path) -> "Index":
        """Raises on any missing or corrupt file. open_index rebuilds then."""
        table = json.loads((directory / SECTIONS_FILE).read_text(encoding="utf-8"))
        bm25 = bm25s.BM25.load(directory, mmap=True, show_progress=False)
        chunks = tuple(Chunk(*row) for row in table["chunks"])
        if bm25.scores["num_docs"] != len(chunks):
            raise ValueError(f"snapshot {directory} has mismatched sections")
        return cls(tuple(Path(f) for f in table["files"]), chunks, table["skipped_binary"], bm25)

    def save(self, directory: Path) -> None:
        self._bm25.save(directory, show_progress=False)
        table = {
            "files": [str(f) for f in self.files],
            "chunks": [[c.file, c.start, c.end, c.section] for c in self.chunks],
            "skipped_binary": self.skipped_binary,
        }
        (directory / SECTIONS_FILE).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")

    def search(self, query: Query, top: int) -> Result:
        """Rank every section with ``get_scores`` and a stable sort, not
        ``BM25.retrieve``: retrieve raises when top exceeds the number of
        sections and does not order tied scores."""
        vocab = self._bm25.vocab_dict
        known = [t for t in query.terms if t in vocab]
        unknown = tuple(t for t in query.terms if t not in vocab)
        if not known:
            return Result((), unknown)
        scores = self._bm25.get_scores(known)
        ids = np.flatnonzero(scores > 0)
        ids = ids[np.argsort(-scores[ids], kind="stable")][:top]
        files: dict[int, list[str]] = {}
        hits = []
        for doc in ids:
            row = self.chunks[doc]
            if row.file not in files:
                files[row.file] = read_lines(self.files[row.file]) or []
            hits.append(_hit(self.files[row.file], files[row.file], row, float(scores[doc]), query))
        return Result(tuple(hits), unknown)

    def stats(self, query: Query) -> tuple[TermStats, ...]:
        """Read document frequencies from the pinned Lucene posting lists.

        Each posting is one section containing the term, regardless of how
        often the term occurs there. No source passages need to be read.
        """
        count = len(self.chunks)
        indptr = self._bm25.scores["indptr"]
        rows = []
        for term in query.terms:
            token = self._bm25.vocab_dict.get(term)
            df = int(indptr[token + 1] - indptr[token]) if token is not None else 0
            idf = math.log1p((count - df + 0.5) / (df + 0.5)) if df else None
            rows.append(TermStats(term, df, count, df / count, idf))
        return tuple(rows)


def _hit(path: Path, lines: list[str], row: Chunk, score: float, query: Query) -> Hit:
    wanted = set(query.terms)
    found = set(terms(row.section)) & wanted
    best, best_count = row.start, 0
    for number in range(row.start, min(row.end, len(lines)) + 1):
        here = set(terms(lines[number - 1])) & wanted
        found |= here
        own_heading = number == row.start and bool(row.section) and lines[number - 1].lstrip().startswith("#")
        if len(here) > best_count and not own_heading:
            best, best_count = number, len(here)
    text = _snippet(lines[best - 1] if best <= len(lines) else "", wanted)
    return Hit(path, row.start, row.end, score, row.section, best, text,
               tuple(t for t in query.terms if t in found))


def _snippet(line: str, wanted: set[str]) -> str:
    text = " ".join(line.split())
    if len(text) <= SNIPPET_CHARS:
        return text
    anchor = next((m.start() for m in _WORD.finditer(text) if wanted & set(terms(m.group()))), 0)
    begin = max(0, min(anchor - SNIPPET_CHARS // 4, len(text) - SNIPPET_CHARS))
    end = begin + SNIPPET_CHARS
    return ("…" if begin else "") + text[begin:end] + ("…" if end < len(text) else "")


class Origin(enum.Enum):
    REUSED = enum.auto()
    BUILT_SAVED = enum.auto()
    BUILT_UNSAVED = enum.auto()


@dataclass(frozen=True, slots=True)
class Ready:
    index: Index
    origin: Origin
    seconds: float


def open_index(corpus: Corpus) -> Ready | NoText:
    """An Index for the corpus as it is now, reusing a saved one when current."""
    for snapshot in _store.snapshots(corpus):
        try:
            return Ready(Index.load(snapshot), Origin.REUSED, 0.0)
        except Exception:
            _store.discard(snapshot)
    started = time.monotonic()
    built = Index.build(corpus)
    if isinstance(built, NoText):
        return built
    saved = _store.publish(corpus, built.save)
    return Ready(built, Origin.BUILT_SAVED if saved else Origin.BUILT_UNSAVED, time.monotonic() - started)
