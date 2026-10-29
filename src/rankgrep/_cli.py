"""The command-line boundary: parse argv, run one search, print JSON Lines,
map every outcome to an exit code. Every sentence an agent reads comes from
this module, and each is one stderr line that says what to do next."""

import argparse
import enum
import json
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import version

from rankgrep._corpus import MAX_FILE_BYTES, Corpus, MissingPaths, select
from rankgrep._index import Hit, NoText, Origin, Query, open_index

DEFAULT_TOP = 8
ISSUES_URL = "https://github.com/janozeli/rankgrep/issues"


class Exit(enum.IntEnum):
    OK = 0
    NO_MATCH = 1
    USAGE = 2
    BUG = 3


@dataclass(frozen=True, slots=True)
class Args:
    query: str
    paths: tuple[str, ...]
    top: int
    stats: bool
    weighted: tuple[tuple[str, float], ...]


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _search(argv)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return Exit.OK
    except Exception as error:
        _say(f"internal error: {type(error).__name__}: {error}. Please report it at {ISSUES_URL}; use rg meanwhile.")
        return Exit.BUG


def _search(argv: Sequence[str] | None) -> Exit:
    args = _parse(argv)
    if isinstance(args, Exit):
        return args
    query = Query.parse(args.query, args.weighted)
    if query is None:
        if args.weighted:
            _say("no searchable words with positive weight. Give at least one searchable term a weight above zero.")
        else:
            _say(f'no searchable words in "{args.query}". Use distinctive keywords such as names, identifiers or error codes.')
        return Exit.USAGE
    corpus = select(args.paths)
    if isinstance(corpus, MissingPaths):
        _say(f"no such file or directory: {', '.join(corpus.paths)}. Pass existing files or folders.")
        return Exit.USAGE
    opened = open_index(corpus)
    if isinstance(opened, NoText):
        skipped = _skipped(opened.binary, opened.oversized)
        where = ", ".join(root.given for root in corpus.roots)
        _say(f"no text files in: {where}{f' ({skipped} skipped)' if skipped else ''}. Pass folders or files that contain text.")
        return Exit.USAGE
    if opened.origin is not Origin.REUSED:
        index = opened.index
        skipped = _skipped(index.skipped_binary, corpus.oversized)
        unsaved = " (not saved: no writable cache directory)" if opened.origin is Origin.BUILT_UNSAVED else ""
        _say(f"indexed {len(index.files)} files ({len(index.chunks)} sections) in {opened.seconds:.1f}s"
             f"{f', skipped {skipped}' if skipped else ''}{unsaved}")
    if args.stats:
        for row in opened.index.stats(query):
            print(json.dumps(asdict(row), ensure_ascii=False, separators=(",", ":")))
        sys.stdout.flush()
        return Exit.OK
    result = opened.index.search(query, args.top)
    if not result.hits:
        _say(f"no matches. Not in this corpus: {', '.join(result.unknown)}. Try other words.")
        return Exit.NO_MATCH
    if result.unknown:
        _say(f"not in this corpus: {', '.join(result.unknown)}")
    for hit in result.hits:
        print(_render(hit, corpus))
    sys.stdout.flush()
    return Exit.OK


def _skipped(binary: int, oversized: int) -> str:
    parts = [f"{binary} binary or unreadable"] if binary else []
    parts += [f"{oversized} over {MAX_FILE_BYTES // 2**20} MiB"] if oversized else []
    return ", ".join(parts)


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _UsageError(message)


def _top(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _parse(argv: Sequence[str] | None) -> Args | Exit:
    parser = _Parser(
        prog="rankgrep",
        description="Rank sections of local text files against keywords with BM25. "
        "Prints one JSON object per hit: path, start, end, score, section, line, text, matched.",
        epilog="Exit codes: 0 hits or statistics printed, 1 no matches, 2 the command cannot run as written, 3 internal error.",
    )
    parser.add_argument("query", help="keywords, quoted as one argument")
    parser.add_argument("paths", nargs="*", metavar="PATH", help="files or folders to search")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("-k", "--top", type=_top, default=DEFAULT_TOP, metavar="N",
                        help=f"number of hits to print (default {DEFAULT_TOP})")
    output.add_argument("--stats", action="store_true",
                        help="print term, df, section_count, fraction and idf as JSONL instead of hits")
    parser.add_argument("--weight", nargs=2, action="append", default=[], metavar=("TEXT", "FACTOR"),
                        help="set weights for normalized terms in TEXT (adds missing terms); repeatable, last wins; "
                        "FACTOR is 0 to 1000000, default 1, zero removes terms")
    parser.add_argument("--files-from", metavar="FILE", help='read more paths from FILE, one per line ("-" for stdin)')
    parser.add_argument("--version", action="version", version=f"rankgrep {version('rankgrep')}")
    try:
        parsed = parser.parse_args(argv)
    except _UsageError as error:
        _say(f"{error}. Run rankgrep --help for usage.")
        return Exit.USAGE
    if parsed.stats and parsed.weight:
        _say("--stats cannot be combined with --weight. Inspect frequencies or run a weighted search separately.")
        return Exit.USAGE
    weighted = []
    for text, factor in parsed.weight:
        try:
            weight = float(factor)
        except ValueError:
            weight = math.nan
        if not math.isfinite(weight) or not 0 <= weight <= 1_000_000:
            _say("--weight FACTOR must be a finite number between 0 and 1000000.")
            return Exit.USAGE
        if Query.parse(text) is None:
            _say("--weight TEXT must contain searchable terms. Use keywords, identifiers or error codes.")
            return Exit.USAGE
        weighted.append((text, weight))
    paths = list(parsed.paths)
    if parsed.files_from:
        try:
            listed = sys.stdin.read() if parsed.files_from == "-" else open(parsed.files_from, encoding="utf-8").read()
        except OSError:
            _say(f"no such file or directory: {parsed.files_from}. Pass existing files or folders.")
            return Exit.USAGE
        paths += [line for line in listed.splitlines() if line.strip()]
    if not paths:
        _say("nothing to search. Pass folders or files after the query, or --files-from -.")
        return Exit.USAGE
    return Args(parsed.query, tuple(paths), parsed.top, parsed.stats, tuple(weighted))


def _render(hit: Hit, corpus: Corpus) -> str:
    return json.dumps(
        {
            "path": corpus.display(hit.path),
            "start": hit.start,
            "end": hit.end,
            "score": round(hit.score, 2),
            "section": hit.section,
            "line": hit.line,
            "text": hit.text,
            "matched": list(hit.matched),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _say(message: str) -> None:
    print(f"rankgrep: {message}", file=sys.stderr)
