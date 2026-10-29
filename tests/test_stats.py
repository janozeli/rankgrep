"""Corpus statistics describe the same indexed sections that search ranks."""

import math
from pathlib import Path

import pytest


def test_statistics_count_sections_not_occurrences_and_survive_reload(run):
    Path("sample.md").write_text(
        "# Shared\n## First\nrare rare common\n## Second\ncommon common\n"
    )
    first = run("--stats", "rare common Shared absent rare", "sample.md")
    assert first.code == 0
    assert [r["term"] for r in first.hits] == ["rare", "common", "shared", "absent"]
    assert [r["df"] for r in first.hits] == [1, 2, 2, 0]
    assert [r["section_count"] for r in first.hits] == [2] * 4
    assert [r["fraction"] for r in first.hits] == [0.5, 1, 1, 0]
    assert first.hits[0]["idf"] == pytest.approx(math.log(2))
    assert first.hits[1]["idf"] == pytest.approx(math.log(1.2))
    assert first.hits[3]["idf"] is None
    again = run("--stats", "rare common Shared absent rare", "sample.md")
    assert again.out == first.out and again.err == ""
    assert len(run("shared", "sample.md").hits) == first.hits[2]["df"]


def test_statistics_share_search_tokenization_and_file_selection(run):
    Path("sample.md").write_text("# Settings\nmax_tokens ação\n")
    result = run("--stats", "MAX_tokens acao missing", "--files-from", "-", stdin="sample.md\n")
    assert result.code == 0
    assert [r["term"] for r in result.hits] == ["max_tokens", "max", "tokens", "acao", "missing"]
    assert [r["df"] for r in result.hits] == [1, 1, 1, 1, 0]
    assert all(set(r) == {"term", "df", "section_count", "fraction", "idf"} for r in result.hits)
    assert run("--stats", "absent", "sample.md").code == 0
    assert run("--stats", "the of", "sample.md").code == 2
    assert run("--stats", "-k", "2", "max", "sample.md").code == 2


def test_statistics_refresh_when_corpus_changes(run):
    path = Path("sample.md")
    path.write_text("# First\nrare\n")
    assert run("--stats", "rare", str(path)).hits[0]["df"] == 1
    path.write_text("# First\nrare\n# Second\nrare again\n")
    row = run("--stats", "rare", str(path)).hits[0]
    assert row["df"] == row["section_count"] == 2
