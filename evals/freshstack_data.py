"""Pinned FreshStack data, native text files, and deterministic relevance metrics."""

import hashlib
import importlib.metadata
import json
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

import numpy as np


REPO = Path(__file__).resolve().parents[1]
SOURCES = REPO / "evals/freshstack-sources.json"
OUT = REPO / "evals/freshstack-results"
TOPICS = ("angular", "godot", "langchain", "laravel", "yolo")
WORK = Path(tempfile.gettempdir()) / "rankgrep-freshstack"
PROTOCOL = 2


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def source_rows(topic: str) -> list[dict]:
    return [s for s in json.loads(SOURCES.read_text()) if s["topic"] == topic]


def fetch(work: Path, topic: str) -> None:
    for spec in source_rows(topic):
        path = work / "downloads" / f"{topic}-{spec['kind']}.parquet"
        if path.exists() and sha(path) == spec["sha256"]:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".partial")
        with urllib.request.urlopen(spec["url"], timeout=120) as response, temporary.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        if sha(temporary) != spec["sha256"]:
            raise ValueError(f"checksum mismatch: {path.name}")
        temporary.replace(path)


def load(work: Path, topic: str) -> tuple[list[dict], list[dict]]:
    import pyarrow.parquet as pq

    data = {}
    for spec in source_rows(topic):
        path = work / "downloads" / f"{topic}-{spec['kind']}.parquet"
        if sha(path) != spec["sha256"]:
            raise ValueError(f"checksum mismatch: {path.name}; run fetch")
        data[spec["kind"]] = pq.read_table(path).to_pylist()
    # Upstream DataLoader converts rows to a dict: repeated corpus IDs keep the LAST row.
    corpus = list({d["_id"]: d for d in data["corpus"]}.values())
    questions = data["queries"]
    ids = {d["_id"] for d in corpus}
    if len({q['query_id'] for q in questions}) != len(questions):
        raise ValueError("duplicate query ID")
    for q in questions:
        if not q["nuggets"]:
            raise ValueError(f"no nuggets: {q['query_id']}")
        for n in q["nuggets"]:
            if not n["relevant_corpus_ids"] or not set(n["relevant_corpus_ids"]) <= ids:
                raise ValueError(f"unsupported or missing gold documents: {n['_id']}")
    return corpus, questions


def filename(document: dict) -> str:
    # Preserve source hierarchy and extensions so Glob/rg/path narrowing remain useful.
    path = PurePosixPath(document["_id"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe upstream document path")
    original = document["_id"].rsplit("_", 2)[0]
    suffix = Path(original).suffix
    if not suffix or not suffix[1:].isalnum():
        suffix = ".text"
    return str(path) + suffix


def materialize(work: Path, topic: str, corpus: list[dict]) -> dict[str, str]:
    root = work / topic / "library" / "docs"
    root.mkdir(parents=True, exist_ok=True)
    mapping = {filename(d): d["_id"] for d in corpus}
    if len(mapping) != len(corpus):
        raise ValueError("document path collision")
    if {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - set(mapping):
        raise ValueError(f"unexpected files in {root}; use a fresh --work")
    for d in corpus:
        path = root / filename(d)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = d["text"].encode()
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    return mapping


def question_text(q: dict) -> str:
    # Matches the upstream DataLoader. Do not use answer_text or nugget text.
    return q["query_title"] + " " + q["query_text"]


def unique(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(values))[:limit]


def metrics(q: dict, ranked: list[str]) -> dict[str, float]:
    ranked = unique(ranked, 20)
    nuggets = [set(n["relevant_corpus_ids"]) for n in q["nuggets"]]
    relevant = set.union(*nuggets)
    judged = set.union(*(set(n["relevant_corpus_ids"]) | set(n["non_relevant_corpus_ids"]) for n in q["nuggets"]))
    top20 = set(ranked[:20])
    covered = sum(bool(top20 & n) for n in nuggets)
    return {"coverage@20": covered / len(nuggets), "recall@20": len(top20 & relevant) / len(relevant),
            "all-nuggets@20": float(covered == len(nuggets)),
            "judged@20": len(top20 & judged) / 20}


def engine_hash() -> str:
    return digest({p.name: sha(p) for p in sorted((REPO / "src/rankgrep").glob("*.py"))})


def provenance(topic: str) -> dict:
    return {"protocol": PROTOCOL, "sources": source_rows(topic), "engine_sha256": engine_hash(),
            "bm25s": importlib.metadata.version("bm25s"), "numpy": np.__version__}
