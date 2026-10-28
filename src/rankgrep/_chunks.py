"""How a file's lines become sections, the unit rankgrep ranks and points to.

Markdown splits at H1 to H3 headings outside fenced code. Every other text
file is one section. Both are then windowed to at most MAX_LINES lines and
MAX_CHARS characters, so a hit never asks the agent to read more than about
a thousand tokens.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_LINES = 80
MAX_CHARS = 4000
SPLIT_DEPTH = 3
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdx"})
SNIFF_MIN_HEADINGS = 3

_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*")

type Heading = tuple[int, str] | None


@dataclass(frozen=True, slots=True)
class Span:
    """Lines start..end of one file, 1-based and inclusive, numbered the way
    ``sed -n`` numbers them. Neither end is blank. ``section`` is the heading
    path "H1 > H2 > H3", empty for plain text and for text before the first
    heading."""

    start: int
    end: int
    section: str


def is_markdown(path: Path, lines: Sequence[str]) -> bool:
    """True for markdown suffixes, and for a .txt with at least
    SNIFF_MIN_HEADINGS H1 to H3 headings outside fences, which is how
    llms-full.txt files look. Only .txt is sniffed, because in most other
    formats a line starting with "#" is a comment."""
    suffix = path.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return True
    if suffix != ".txt":
        return False
    headings, _ = _outline(lines)
    return sum(1 for h in headings if h and h[0] <= SPLIT_DEPTH) >= SNIFF_MIN_HEADINGS


def chunk(lines: Sequence[str], markdown: bool) -> list[Span]:
    """Split ``lines`` into spans in file order, without overlap.

    A markdown section whose body is blank is dropped: a heading-only span
    is one line long, so BM25 length normalization would rank it above the
    sections that hold the content, and its title already lives in its
    children's section paths.

    Long sections are windowed. A window is cut before a heading deeper than
    H3 when it has one, else after its last blank line outside a fence, else
    before the line that overflows.
    """
    if markdown:
        headings, fenced = _outline(lines)
    else:
        headings, fenced = [None] * len(lines), [False] * len(lines)
    spans = []
    for lo, hi, section in _sections(headings, len(lines)):
        if section and not any(line.strip() for line in lines[lo + 1 : hi]):
            continue
        for start, end in _windows(lines, lo, hi, headings, fenced):
            while start < end and not lines[start].strip():
                start += 1
            while end > start and not lines[end - 1].strip():
                end -= 1
            if start < end:
                spans.append(Span(start + 1, end, section))
    return spans


def _outline(lines: Sequence[str]) -> tuple[list[Heading], list[bool]]:
    """Per line: its ATX heading (depth, title) outside fences, and whether it is part of a fence."""
    headings: list[Heading] = []
    fenced: list[bool] = []
    fence = ""
    for line in lines:
        if fence:
            close = _FENCE_CLOSE.fullmatch(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = ""
            headings.append(None)
            fenced.append(True)
            continue
        opening = _FENCE.match(line)
        if opening:
            fence = opening.group(1)
            headings.append(None)
            fenced.append(True)
            continue
        heading = _HEADING.fullmatch(line)
        headings.append((len(heading.group(1)), heading.group(2).strip()) if heading else None)
        fenced.append(False)
    return headings, fenced


def _sections(headings: Sequence[Heading], count: int) -> Iterator[tuple[int, int, str]]:
    """Yield (lo, hi, path) as 0-based half-open line ranges."""
    stack: list[tuple[int, str]] = []
    lo, path = 0, ""
    for i, heading in enumerate(headings):
        if heading and heading[0] <= SPLIT_DEPTH:
            yield lo, i, path
            while stack and stack[-1][0] >= heading[0]:
                stack.pop()
            stack.append(heading)
            lo, path = i, " > ".join(title for _, title in stack)
    yield lo, count, path


def _windows(
    lines: Sequence[str], lo: int, hi: int, headings: Sequence[Heading], fenced: Sequence[bool]
) -> Iterator[tuple[int, int]]:
    start = lo
    while start < hi:
        end, size = start, 0
        heading_cut = blank_cut = None
        while end < hi:
            size += len(lines[end]) + 1
            if end > start and (end - start >= MAX_LINES or size > MAX_CHARS):
                break
            if end > start and headings[end]:
                heading_cut = end
            if not fenced[end] and not lines[end].strip():
                blank_cut = end + 1
            end += 1
        if end == hi:
            yield start, hi
            return
        cut = heading_cut if heading_cut is not None else blank_cut if blank_cut is not None else end
        yield start, cut
        start = cut
