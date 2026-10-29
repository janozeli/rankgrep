"""Explicit weights control ranking without changing search output or indexing."""

from pathlib import Path

import pytest


def test_weights_change_ranking_and_match_weighted_single_term_scores(run):
    Path("weighted.md").write_text("# First\napple apple\n# Second\nbanana banana\n# Third\napple banana\n")
    apples = {h["start"]: h["score"] for h in run("apple", "weighted.md").hits}
    bananas = {h["start"]: h["score"] for h in run("banana", "weighted.md").hits}
    weighted = run("--weight", "banana", "3", "apple", "weighted.md")
    assert weighted.code == 0
    assert weighted.hits[0]["section"] == "Second"
    assert weighted.hits[0]["matched"] == ["banana"]
    for hit in weighted.hits:
        # CLI scores are rounded to hundredths, including the single-term inputs.
        expected = apples.get(hit["start"], 0) + 3 * bananas.get(hit["start"], 0)
        assert hit["score"] == pytest.approx(expected, abs=0.025)
    reversed_weights = run("--weight", "apple", "3", "apple banana", "weighted.md")
    assert reversed_weights.hits[0]["section"] == "First"


def test_default_unit_and_zero_weights_preserve_search_bytes(run):
    plain = run("PreToolUse matcher", "docs-a")
    unit = run("--weight", "PreToolUse matcher", "1", "PreToolUse matcher", "docs-a")
    assert plain.out == unit.out
    without = run("--weight", "matcher", "0", "PreToolUse matcher", "docs-a")
    assert without.out == run("PreToolUse", "docs-a").out
    assert run("--weight", "matcher", "0", "matcher", "docs-a").code == 2


def test_weights_normalize_identifiers_add_terms_and_last_option_wins(run):
    Path("weighted.md").write_text("# Size\nmax_tokens\n# Accent\nação\n")
    actual = run("--weight", "max_tokens", "0", "--weight", "MAX_tokens ação", "0.5",
                 "missing", "--files-from", "-", stdin="weighted.md\n")
    expected = run("--weight", "max_tokens acao", "0.5", "missing", "weighted.md")
    assert actual.code == 0 and actual.out == expected.out
    assert "not in this corpus: missing" in actual.err
    assert actual.hits[0]["matched"] == ["max_tokens", "max", "tokens"]
    absent = run("--weight", "unfindable", "2", "missing", "weighted.md")
    assert absent.code == 1 and "unfindable" in absent.err


@pytest.mark.parametrize("factor", ["-1", "nan", "inf", "1000001", "huge"])
def test_invalid_weights_fail_as_usage_errors(run, factor):
    result = run("--weight", "matcher", factor, "matcher", "docs-a")
    assert result.code == 2 and result.out == ""
    assert result.err.count("\n") == 1


def test_empty_weight_text_and_stats_combination_are_usage_errors(run):
    for args in [("--weight", "the of", "2"), ("--stats", "--weight", "matcher", "2")]:
        result = run(*args, "matcher", "docs-a")
        assert result.code == 2 and result.out == ""
