"""Validate the hard suite's evidence accounting without model/network calls."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals"
spec = importlib.util.spec_from_file_location("harness", EVALS / "harness.py")
harness = importlib.util.module_from_spec(spec)
sys.modules["harness"] = harness
spec.loader.exec_module(harness)
spec = importlib.util.spec_from_file_location("hard_eval", EVALS / "hard.py")
hard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hard)


def test_citations_reject_wrong_files_escape_and_excessive_ranges(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("line\n" * 60)
    (tmp_path / "secret.txt").write_text("secret\n")
    (docs / "escape.txt").symlink_to(tmp_path / "secret.txt")
    reply = json.dumps({"sources": ["docs/a.txt:2-5", "a.txt:2", "docs/a.txt:0", "docs/a.txt:1-41",
                                    "docs/a.txt:61", "docs/../secret.txt:1", "docs/escape.txt:1"]})
    assert hard.citations(reply, tmp_path) == [{"path": "docs/a.txt", "start": 2, "end": 5}]


def test_multi_file_evidence_requires_both_files_and_does_not_count_duplicates():
    a = {"path": "docs/a.txt", "start": 10, "end": 12}
    b = {"path": "docs/b.txt", "start": 10, "end": 12}
    q = {"evidence": [a, b]}
    assert hard.evidence_recall(q, []) == 0
    assert hard.evidence_recall(q, [a, a]) == 0.5
    assert hard.evidence_recall(q, [a, b]) == 1


def test_committed_suite_has_balanced_axes_and_cross_file_questions():
    qs = harness._read_jsonl(hard.QUESTIONS)
    assert len({q["id"] for q in qs}) == 24
    for axis in hard.AXES:
        subset = [q for q in qs if q["axis"] == axis]
        assert len(subset) == 6
        assert sum(q["evidence"][0]["path"].startswith("docs/python/") for q in subset) == 3
        if axis == "multi-hop":
            assert all(len({e["path"] for e in q["evidence"]}) >= 2 for q in subset)


def test_question_validation_detects_stale_quote(tmp_path, monkeypatch):
    work = harness.Work(tmp_path)
    path = work.project(harness.ARMS["rg"]) / "docs" / "a.txt"
    path.parent.mkdir(parents=True)
    path.write_text("actual evidence\n")
    questions = tmp_path / "questions.jsonl"
    q = {"id": "direct-01", "axis": "direct", "evidence": [
        {"path": "docs/a.txt", "start": 1, "end": 1, "quote": "wrong text"}]}
    harness._write_jsonl(questions, [q])
    monkeypatch.setattr(hard, "QUESTIONS", questions)
    with pytest.raises(ValueError, match="evidence quote changed"):
        hard.load_questions(work)


def test_run_provenance_rejects_changed_questions(tmp_path, monkeypatch):
    (tmp_path / "meta.json").write_text(json.dumps({"questions_sha256": "old"}))
    monkeypatch.setattr(hard, "identity", lambda work, qs: {"questions_sha256": "new"})
    with pytest.raises(ValueError, match="provenance differs"):
        hard.check_meta(harness.Work(tmp_path), tmp_path, [])


def test_grader_never_sees_rejected_citations_and_cannot_credit_empty_sources(tmp_path, monkeypatch):
    work = harness.Work(tmp_path / "work")
    path = work.project(harness.ARMS["rg"]) / "docs" / "a.txt"
    path.parent.mkdir(parents=True)
    path.write_text("reference fact\n")
    q = {"id": "direct-01", "question": "What is the fact?", "answer": "reference fact", "evidence": [
        {"path": "docs/a.txt", "start": 1, "end": 1}]}
    rows = [{"id": q["id"], "arm": arm, "answer": "reference fact", "sources": [], "error": None,
             "reply": 'reference fact, sources: ["REJECTED_CITATION_MARKER"]'} for arm in harness.ARMS]
    harness._write_jsonl(tmp_path / "runs.jsonl", rows)
    monkeypatch.setattr(hard, "check_meta", lambda *args: {"cache_key": "test", "model": "test", "claude_code": "test"})
    prompts = []

    def call(stem, prompt, *args):
        prompts.append(prompt)
        return [{"subtype": "init", "model": "test", "claude_code_version": "test"},
                {"type": "result", "subtype": "success", "structured_output": {"grades": [
                    {"label": label, "correct": True, "cited_ok": True, "reason": "test"} for label in "ABC"]}}]

    monkeypatch.setattr(harness, "_cached_call", call)
    hard.grade(work, tmp_path, [q], 1)
    assert "REJECTED_CITATION_MARKER" not in prompts[0]
    verdicts = harness._read_jsonl(tmp_path / "verdicts.jsonl")
    assert all(v["correct"] and not v["cited_ok"] for v in verdicts)
