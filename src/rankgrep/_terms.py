"""How text becomes BM25 terms. Documents and queries both go through ``terms``."""

import functools
import re
import unicodedata

from bm25s.stopwords import STOPWORDS_EN, STOPWORDS_PORTUGUESE

_RUN = re.compile(r"\w+(?:[.\-/]\w+)*")
_JOINERS = re.compile(r"[._\-/]+")

MAX_TERM_LENGTH = 64


def _fold(term: str) -> str:
    decomposed = unicodedata.normalize("NFD", term.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


_STOPWORDS = frozenset(_fold(w) for w in STOPWORDS_EN + STOPWORDS_PORTUGUESE)


def terms(text: str) -> list[str]:
    """Return the terms of ``text`` in order of appearance, with repeats.

    Each word-like run emits itself, its segments, and their camelCase and
    letter/digit parts, folded to lowercase without accents:
    "max_tokens" -> max_tokens, max, tokens; "getUserById" -> getuserbyid,
    get, user, id. The whole run is the rarer term, so a section that spells
    an identifier exactly outranks one that only uses its words. No stemming,
    so matching stays predictable in any language.
    """
    out: list[str] = []
    for match in _RUN.finditer(unicodedata.normalize("NFKC", text)):
        out.extend(_run_terms(match.group()))
    return out


@functools.lru_cache(maxsize=1 << 16)
def _run_terms(run: str) -> tuple[str, ...]:
    """Cached because text repeats the same words: tokenizing was nearly all
    of the index build time before this cache."""
    candidates = [run]
    for segment in _JOINERS.split(run):
        if segment:
            candidates.append(segment)
            candidates.extend(_parts(segment))
    unique = dict.fromkeys(_fold(candidate) for candidate in candidates)
    return tuple(term for term in unique if _searchable(term))


def _searchable(term: str) -> bool:
    if term in _STOPWORDS or len(term) > MAX_TERM_LENGTH:
        return False
    return len(term) > 1 or term.isdigit()


def _parts(segment: str) -> list[str]:
    """Split at lower-to-upper, acronym-to-word and letter/digit boundaries:
    "HTTPServer" -> HTTP, Server; "bm25s" -> bm, 25, s."""
    parts: list[str] = []
    start = 0
    for i in range(1, len(segment)):
        before, here = segment[i - 1], segment[i]
        after = segment[i + 1] if i + 1 < len(segment) else ""
        if (
            before.isdigit() != here.isdigit()
            or (before.islower() and here.isupper())
            or (before.isupper() and here.isupper() and after.islower())
        ):
            parts.append(segment[start:i])
            start = i
    parts.append(segment[start:])
    return parts
