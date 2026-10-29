"""Search evaluation contracts, independent of external datasets and model calls."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals"
for name in ("harness", "freshstack_data", "freshstack"):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
f = sys.modules["freshstack_data"]
a = sys.modules["freshstack"]


def question():
    return {"query_id": "1", "query_title": "real title", "query_text": "real body", "answer_text": "SECRET ANSWER",
            "nuggets": [{"text": "SECRET NUGGET", "relevant_corpus_ids": ["a", "b"], "non_relevant_corpus_ids": ["x"]},
                        {"text": "OTHER SECRET", "relevant_corpus_ids": ["b", "c"], "non_relevant_corpus_ids": ["x"]}]}


def test_coverage_counts_facts_not_number_of_matching_documents():
    q = question()
    assert f.metrics(q, ["a"])["coverage@20"] == .5
    assert f.metrics(q, ["b"])["coverage@20"] == 1
    assert f.metrics(q, ["b", "b"])["recall@20"] == pytest.approx(1 / 3)
    assert f.metrics(q, ["unknown", "x"])["coverage@20"] == 0
    assert f.metrics(q, [])["recall@20"] == 0


def test_cutoffs_and_missing_slots_are_not_inflated():
    ranked = [f"unknown-{i}" for i in range(20)] + ["b"]
    assert f.metrics(question(), ranked)["coverage@20"] == 0
    assert f.metrics(question(), ranked)["recall@20"] == 0
    assert f.metrics(question(), ["b"])["judged@20"] == .05


def test_materialization_preserves_text_and_format_without_injecting_labels(tmp_path):
    doc = {"_id": "repo/guide.md_0_100", "text": "# Guide\nA real paragraph\n"}
    mapping = f.materialize(tmp_path, "topic", [doc])
    path = tmp_path / "topic/library/docs" / f.filename(doc)
    assert path.suffix == ".md"
    assert path.read_text() == doc["text"]
    assert mapping[path.relative_to(tmp_path / "topic/library/docs").as_posix()] == doc["_id"]
    (path.parent / "unexpected.txt").write_text("label leak")
    with pytest.raises(ValueError, match="unexpected files"):
        f.materialize(tmp_path, "topic", [doc])


def test_queries_and_agent_prompt_never_receive_answer_or_nuggets():
    assert f.question_text(question()) == "real title real body"
    text = a.prompt(question())
    assert "real title real body" in text
    assert "SECRET" not in text


def test_agent_paths_must_be_known_and_budget_applies_before_filtering():
    mapping = {"a.md": "a", "b.md": "b"}
    reply = json.dumps({"documents": ["docs/a.md", "docs/a.md", "../a.md", "docs/../a.md", "docs/b.md"]})
    assert a.selected(reply, mapping) == (["a", "b"], 2)
    reply = json.dumps({"documents": ["bad"] * 20 + ["docs/a.md"]})
    assert a.selected(reply, mapping) == ([], 20)
    assert a.selected("not JSON", mapping) == ([], 1)


def test_sample_is_stable_under_input_order_and_ignores_answers():
    qs = [{"query_id": str(i)} for i in range(20)]
    assert a.sample(qs, "topic", 6) == a.sample(list(reversed(qs)), "topic", 6)
    before = [q["query_id"] for q in a.sample(qs, "topic", 6)]
    for q in qs:
        q["answer_text"] = "new answer"
    assert before == [q["query_id"] for q in a.sample(qs, "topic", 6)]


def test_only_agent_configuration_difference_is_plugin():
    plugin = Path("/plugin/rankgrep")
    plain = a.flags(plugin, "free")
    augmented = a.flags(plugin, "free+rankgrep")
    assert augmented == plain + ["--plugin-dir", str(plugin)]
    assert plain[plain.index("--tools") + 1] == "default"
    assert plain[plain.index("--permission-mode") + 1] == "bypassPermissions"
    assert not {"--allowedTools", "--disallowedTools", "--settings"} & set(plain)
    assert "pipelines" in a.prompt(question())


def test_baseline_environment_does_not_inherit_project_rankgrep_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(f.REPO / ".venv/bin") + ":/usr/bin:/bin")
    env = a.agent_env(sys.modules["harness"].Work(tmp_path))
    assert env["PATH"] == "/usr/bin:/bin"


def test_failed_agent_call_cannot_get_credit_for_an_intermediate_selection():
    q = question()
    stream = [{"type": "result", "subtype": "error_max_turns", "is_error": True,
               "result": json.dumps({"documents": ["docs/a.md"]})}]
    row = a.record(q, "free", stream, {"a.md": "a"})
    assert row["error"] == "error_max_turns"
    assert row["documents"] == []
    assert row["coverage@20"] == 0


def test_zero_sample_means_every_question():
    qs = [{"query_id": str(i)} for i in range(12)]
    assert len(a.sample(qs, "topic", 0)) == 12


def test_pinned_loader_matches_upstream_last_duplicate_wins(tmp_path, monkeypatch):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    root = tmp_path / "downloads"
    root.mkdir()
    raw = {
        "corpus": [{"_id": "repo/a.md_0_5", "text": "first"}, {"_id": "repo/a.md_0_5", "text": "last"}],
        "queries": [{"query_id": "1", "nuggets": [{"_id": "1_0", "relevant_corpus_ids": ["repo/a.md_0_5"]}]}],
    }
    specs = []
    for kind, rows in raw.items():
        path = root / f"topic-{kind}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        specs.append({"kind": kind, "sha256": f.sha(path)})
    monkeypatch.setattr(f, "source_rows", lambda topic: specs)
    corpus, qs = f.load(tmp_path, "topic")
    assert corpus == [{"_id": "repo/a.md_0_5", "text": "last"}]
    assert len(qs) == 1
    (root / "topic-corpus.parquet").write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="checksum mismatch"):
        f.load(tmp_path, "topic")
