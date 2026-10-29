"""Does an agent find answers in a large text with rg, with rankgrep, or with no tools?

    uv run evals/harness.py all

runs every stage in order: fetch, questions, run, grade, report. Each stage
caches its claude calls under --work, keyed by a hash of the model, prompt and
flags, so a rerun repeats only what is missing or changed. The README section "Does it
work?" describes the design and the results.
"""

import argparse
import bisect
import concurrent.futures
import hashlib
import io
import itertools
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from rankgrep._chunks import Span, chunk, is_markdown
from rankgrep._corpus import read_lines
from rankgrep._terms import terms

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "evals" / "results"
QUESTIONS = RESULTS / "questions.jsonl"
CANDIDATES = RESULTS / "question-candidates.jsonl"
MODEL = "sonnet"
SEED = "rankgrep-lookup-1"
PER_CORPUS = 25
BATCH = 6
MAX_BATCHES = 10
RUN_BUDGET_USD = "2"
RUN_TIMEOUT_S = 1200
PROJECT = "notes-library"
PLUGIN_FILES = ("bin", "src", "skills", "pyproject.toml", "uv.lock", ".claude-plugin", "LICENSE", "README.md", ".python-version")
NO_WEB = ("Grep", "Glob", "WebFetch", "WebSearch", "Agent", "Task")
NO_TOOLS_NOTE = ("This session has no tools. You cannot open files or run commands, so answer from what you "
                 "already know. Give your best answer even if you are not sure.")


@dataclass(frozen=True, slots=True)
class Corpus:
    key: str
    url: str
    sha256: str
    path: str
    title: str
    intro: str
    body: tuple[str, str] | None = None


CORPORA = {
    corpus.key: corpus
    for corpus in (
        Corpus(
            key="docs",
            url="https://code.claude.com/docs/llms-full.txt",
            sha256="e7006d8e0ab98d3f6ba528f8fc8b51d8bb4de2b798f2030f1be8be4fb69abad5",
            path="docs/claude-code/llms-full.txt",
            title="the Claude Code documentation",
            intro="I keep the Claude Code docs as one file at docs/claude-code/llms-full.txt.",
        ),
        Corpus(
            key="book",
            url="https://www.gutenberg.org/cache/epub/135/pg135.txt",
            sha256="6cf3b9d6fc5e6f733737425267d3af296d7f99f9b9fd1d255a3ab7689a6346ab",
            path="books/les-miserables.txt",
            title="Les Misérables by Victor Hugo, in Isabel F. Hapgood's English translation",
            intro="I have Les Misérables by Victor Hugo, in Isabel Hapgood's translation, as plain text at books/les-miserables.txt.",
            body=("*** START OF THE PROJECT GUTENBERG EBOOK", "*** END OF THE PROJECT GUTENBERG EBOOK"),
        ),
    )
}


@dataclass(frozen=True, slots=True)
class Arm:
    name: str
    desk: str
    tools: tuple[str, ...]


ARMS = {
    arm.name: arm
    for arm in (
        Arm("closed-book", "desk-1", ()),
        Arm("rg", "desk-2", ("Bash", "Read", "Skill")),
        Arm("rankgrep", "desk-3", ("Bash", "Read", "Skill")),
    )
}


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    corpus: str
    path: str
    start: int
    end: int
    section: str
    question: str
    answer: str
    line: int
    quote: str
    overlap: float


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    corpus: str
    arm: str
    found: bool
    cited: str | None
    answer: str | None
    reply: str
    tool_calls: dict[str, int]
    blocked: int
    turns: int
    tokens: int
    cost_usd: float
    seconds: float
    error: str | None


@dataclass(frozen=True, slots=True)
class Verdict:
    id: str
    arm: str
    correct: bool
    cited_ok: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Work:
    """Everything a run writes outside the repository. Agents see only the
    desk folders and the plugin copy, and no path among them names the measurement."""

    root: Path

    def download(self, corpus: Corpus) -> Path:
        return self.root / "downloads" / corpus.key / Path(corpus.path).name

    def project(self, arm: Arm) -> Path:
        return self.root / arm.desk / PROJECT

    @property
    def plugin(self) -> Path:
        return self.root / "plugins" / "rankgrep"

    @property
    def launcher(self) -> Path:
        return self.plugin / "bin" / "rankgrep"

    @property
    def guard(self) -> Path:
        return self.root / "shell" / "allow.py"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def private(self) -> Path:
        return self.root / "private"

    def calls(self, label: str) -> Path:
        return self.root / "calls" / label


def fetch(work: Work) -> None:
    for corpus in CORPORA.values():
        target = work.download(corpus)
        if not (target.exists() and _sha256(target) == corpus.sha256):
            target.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(corpus.url, headers={"User-Agent": "rankgrep (+https://github.com/janozeli/rankgrep)"})
            with urllib.request.urlopen(request) as response:
                data = response.read()
            got = hashlib.sha256(data).hexdigest()
            if got != corpus.sha256:
                sys.exit(f"{corpus.url} changed: sha256 {got}, expected {corpus.sha256}. "
                         "The committed questions point at line ranges of the pinned version.")
            target.write_bytes(data)
        for arm in ARMS.values():
            copy = work.project(arm) / corpus.path
            if not (copy.exists() and _sha256(copy) == corpus.sha256):
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, copy)
    prepare(work, [target for c in CORPORA.values() for target in (c.path, str(Path(c.path).parent))])


def prepare(work: Work, targets: list[str]) -> None:
    """Install the pinned plugin, guard and warm indexes for a prepared corpus."""
    if not work.plugin.exists():
        commit = _git("rev-parse", "HEAD").strip()
        archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", commit, *PLUGIN_FILES],
                                 check=True, capture_output=True).stdout
        work.plugin.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(work.plugin, filter="data")
        (work.plugin.parent / "rankgrep.commit").write_text(commit + "\n")
    work.guard.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / "evals" / "guard.py", work.guard)
    work.private.mkdir(parents=True, exist_ok=True)
    project = work.project(ARMS["rankgrep"])
    for target in targets:
        warm = subprocess.run([str(work.launcher), "-k", "1", "warm", target], cwd=project, env=_agent_env(work),
                              capture_output=True, text=True)
        if warm.returncode not in (0, 1):
            sys.exit(f"rankgrep failed on {target}: {warm.stderr.strip()}")
    print(f"prepared {work.root}, plugin at commit {_plugin_commit(work)[:12]}")


def write_questions(work: Work, jobs: int) -> None:
    candidates: list[dict] = []
    questions: list[Question] = []
    for corpus in CORPORA.values():
        kept, seen = _questions_for(work, corpus, jobs)
        questions += kept
        candidates += seen
    _write_jsonl(QUESTIONS, [asdict(q) for q in questions])
    _write_jsonl(CANDIDATES, candidates)
    for corpus in CORPORA:
        statuses = Counter(c["status"] for c in candidates if c["corpus"] == corpus)
        print(f"{corpus}: {dict(statuses)}")


@dataclass(frozen=True, slots=True)
class Folded:
    """A text's lines, folded and joined by spaces, so that a quote matches
    across the hard line breaks of a plain-text book."""

    text: str
    starts: list[int]

    @classmethod
    def of(cls, lines: list[str]) -> "Folded":
        parts = [_fold(line) for line in lines]
        starts = list(itertools.accumulate((len(part) + 1 for part in parts[:-1]), initial=0))
        return cls(" ".join(parts), starts)

    def find(self, quote: str) -> list[tuple[int, int]]:
        """First and last line, 1-based, of every occurrence of ``quote``."""
        found = []
        at = self.text.find(quote)
        while at != -1:
            found.append((bisect.bisect_right(self.starts, at), bisect.bisect_right(self.starts, at + len(quote) - 1)))
            at = self.text.find(quote, at + 1)
        return found


def _questions_for(work: Work, corpus: Corpus, jobs: int) -> tuple[list[Question], list[dict]]:
    path = work.download(corpus)
    lines, spans = _sections(path)
    order = _eligible(corpus, lines, spans)
    random.Random(f"{SEED}:{corpus.key}").shuffle(order)
    folded = Folded.of(lines)
    seen: list[dict] = []
    batches = 0
    while sum(c["status"] == "kept" for c in seen) < PER_CORPUS and batches < MAX_BATCHES:
        missing = PER_CORPUS - sum(c["status"] == "kept" for c in seen)
        wave = range(batches, min(MAX_BATCHES, batches + max(1, math.ceil(missing * 1.6 / BATCH))))
        with concurrent.futures.ThreadPoolExecutor(jobs) as executor:
            results = list(executor.map(
                lambda b: _write_batch(work, corpus, lines, order[b * BATCH:(b + 1) * BATCH], b), wave))
        for batch in results:
            for span, item in batch:
                seen.append(_vet(corpus, folded, span, item))
        batches = wave.stop
    kept: list[Question] = []
    for candidate in seen:
        if candidate["status"] != "kept":
            continue
        if len(kept) == PER_CORPUS:
            candidate["status"] = "spare"
            continue
        candidate["id"] = f"{corpus.key}-{len(kept) + 1:02d}"
        candidate["overlap"] = _overlap(candidate["question"], lines[candidate["start"] - 1:candidate["end"]])
        kept.append(Question(**{k: candidate[k] for k in Question.__dataclass_fields__}))
    return kept, seen


WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "excerpt": {"type": "integer"},
                    "skip": {"type": "boolean"},
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "line": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["excerpt", "skip", "question", "answer", "line", "quote"],
            },
        }
    },
    "required": ["items"],
}

WRITER_PROMPT = """Below are {count} excerpts from {title}. Each line of an excerpt starts with its line number in the full text.

For each excerpt, write one question that a reader of {title} might ask, and that this excerpt answers.

- The answer is one specific fact that the excerpt states: a value, a name, a rule, a step, an event, a detail. Not a summary, a theme, or an opinion.
- Only this excerpt answers it. General knowledge does not.
- The question makes sense to someone who has never seen the excerpt. Name what it is about, such as the feature or setting, or the characters and the situation, so that it points to one place in the whole text. Never write "this excerpt", "this section", or "the passage".
- Phrase it in your own words, the way someone who has not read the text would ask. Where a natural paraphrase exists, do not reuse the excerpt's distinctive words or identifiers. Keep a name only when the question is unclear without it.
- answer: the correct answer, at most 25 words.
- line: the number of the one line that states the answer.
- quote: 3 to 12 consecutive words copied exactly from that line, which carry the answer.
- If the excerpt states no such fact, for example because it is only a table of contents, a list of links, license text, or code with no explanation, set skip to true and leave the other fields empty.

Return one item per excerpt, with excerpt set to its number.

{excerpts}"""


def _overlap(question: str, section: list[str]) -> float:
    """Share of the question's distinct rankgrep terms that its section contains.
    A low share means the question is worded differently from the text."""
    asked = set(terms(question))
    return round(len(asked & set(terms("\n".join(section)))) / len(asked), 2) if asked else 0.0


def _write_batch(work: Work, corpus: Corpus, lines: list[str], spans: list[Span], batch: int) -> list[tuple[Span, dict]]:
    excerpts = "\n\n".join(
        f"<excerpt {n}>\n" + "\n".join(f"{i}: {lines[i - 1]}" for i in range(span.start, span.end + 1)) + f"\n</excerpt {n}>"
        for n, span in enumerate(spans, 1)
    )
    prompt = WRITER_PROMPT.format(count=len(spans), title=corpus.title, excerpts=excerpts)
    result = _final(_cached_call(work.calls("questions") / f"{corpus.key}-{batch:02d}", prompt, work.private,
                                 _schema_flags(WRITER_SCHEMA), _private_env()))
    items = {item["excerpt"]: item for item in (result.get("structured_output") or {}).get("items", [])}
    return [(span, items.get(n, {"skip": True, "missing": True})) for n, span in enumerate(spans, 1)]


def _vet(corpus: Corpus, folded: Folded, span: Span, item: dict) -> dict:
    candidate = {"id": None, "corpus": corpus.key, "path": corpus.path, "start": span.start, "end": span.end,
                 "section": span.section, "question": item.get("question", ""), "answer": item.get("answer", ""),
                 "line": item.get("line", 0), "quote": item.get("quote", "")}
    if item.get("missing"):
        return candidate | {"status": "writer returned nothing"}
    if item.get("skip"):
        return candidate | {"status": "writer skipped"}
    quote = _fold(candidate["quote"])
    if len(quote.split()) < 3:
        return candidate | {"status": "quote under 3 words"}
    occurrences = folded.find(quote)
    inside = [(first, last) for first, last in occurrences if span.start <= first and last <= span.end]
    if not any(first <= candidate["line"] <= last for first, last in inside):
        return candidate | {"status": "quote not on its line"}
    if len(inside) < len(occurrences):
        elsewhere = [first for first, last in occurrences if (first, last) not in inside]
        return candidate | {"status": "quote also outside its section", "elsewhere": elsewhere[:20]}
    return candidate | {"status": "kept"}


def run_arms(work: Work, out: Path, limit: int | None, jobs: int) -> None:
    questions = _load_questions(limit)
    tasks = [(q, arm) for q in questions for arm in ARMS.values()]
    random.Random(f"{SEED}:order").shuffle(tasks)

    def one(task: tuple[Question, Arm]) -> tuple[Run, tuple[str, str]]:
        question, arm = task
        stream = _cached_call(work.calls(out.name) / arm.name / question.id, _agent_prompt(question),
                              work.project(arm), _arm_flags(work, arm), _agent_env(work))
        init = next(e for e in stream if e.get("subtype") == "init")
        return _record(question, arm, stream), (init["model"], init["claude_code_version"])

    with concurrent.futures.ThreadPoolExecutor(jobs) as executor:
        done = list(executor.map(one, tasks))
    versions = {version for _, version in done}
    if len(versions) != 1:
        raise SystemExit(f"runs used more than one model or Claude Code version: {sorted(versions)}")
    (model, claude_code), = versions
    runs = sorted((run for run, _ in done), key=lambda r: (r.id, list(ARMS).index(r.arm)))
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "runs.jsonl", [asdict(r) for r in runs])
    meta = {
        "date": date.today().isoformat(),
        "model": model,
        "claude_code": claude_code,
        "plugin_commit": _plugin_commit(work),
        "corpora": {c.key: {"url": c.url, "sha256": c.sha256} for c in CORPORA.values()},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{len(runs)} runs written to {out / 'runs.jsonl'}")


ANSWER_FORMAT = ('Keep the answer short. End with one line of JSON: {"answer": "<your answer>", "source": "<file>:<line>"}, '
                 "where the line is the one in that file that backs up the answer.")


def _agent_prompt(question: Question) -> str:
    return f"{CORPORA[question.corpus].intro} {question.question}\n\n{ANSWER_FORMAT}"


def _arm_flags(work: Work, arm: Arm) -> list[str]:
    flags = ["--tools", ",".join(arm.tools), "--disallowedTools", *NO_WEB, "--max-budget-usd", RUN_BUDGET_USD]
    if arm.name == "closed-book":
        # Without this note, the pilot agent wrote tool calls as plain text until it hit the output limit.
        flags += ["--append-system-prompt", NO_TOOLS_NOTE, "--max-turns", "1"]
    if arm.name == "rg":
        flags += ["--allowedTools", "Bash(rg *)", "Read", "--settings", _guard_settings(work, arm, "rg")]
    if arm.name == "rankgrep":
        flags += ["--plugin-dir", str(work.plugin),
                  "--allowedTools", f"Bash({work.launcher} *)", "Read", "Skill(rankgrep:rankgrep)",
                  "--settings", _guard_settings(work, arm, str(work.launcher))]
    return flags


def _guard_settings(work: Work, arm: Arm, program: str) -> str:
    command = f"{shutil.which('python3')} -I {work.guard} {program} {work.project(arm)}"
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|Read", "hooks": [{"type": "command", "command": command}]}]}})


def _record(question: Question, arm: Arm, stream: list[dict]) -> Run:
    init = next(e for e in stream if e.get("subtype") == "init")
    if sorted(init["tools"]) != sorted(arm.tools):
        raise SystemExit(f"{arm.name} {question.id}: agent had tools {init['tools']}, expected {list(arm.tools)}")
    result = _final(stream)
    calls: dict[str, str] = {}
    for event in stream:
        if event.get("type") == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = block["name"]
    reply = result.get("result") or ""
    final = _final_json(reply)
    cited = str(final.get("source")) if final and final.get("source") else None
    answer = str(final.get("answer")) if final and final.get("answer") is not None else None
    usage = result.get("modelUsage") or {}
    tokens = sum(u.get(k, 0) for u in usage.values()
                 for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"))
    return Run(
        id=question.id, corpus=question.corpus, arm=arm.name,
        found=_cites_gold(cited, question), cited=cited, answer=answer, reply=reply,
        tool_calls=dict(sorted(Counter(calls.values()).items())),
        blocked=len(result.get("permission_denials") or []),
        turns=result.get("num_turns", 0), tokens=tokens,
        cost_usd=round(result.get("total_cost_usd", 0.0), 4),
        seconds=round(result.get("duration_ms", 0) / 1000, 1),
        error=None if result.get("subtype") == "success" and not result.get("is_error") else result.get("subtype", "error"),
    )


def _final_json(reply: str) -> dict | None:
    for line in reversed(reply.strip().splitlines()):
        line = line.strip().strip("`").strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _cites_gold(cited: str | None, question: Question) -> bool:
    line = _cited_line(cited, question)
    return line is not None and question.start <= line <= question.end


def _cited_line(cited: str | None, question: Question) -> int | None:
    """The line a "path:line" citation points to, when the path names the question's file."""
    match = re.match(r"\s*(.+?):(\d+)", cited or "")
    if not match:
        return None
    cited_parts = Path(os.path.normpath(match.group(1).strip().strip("`"))).parts
    gold_parts = Path(question.path).parts
    shorter = min(len(cited_parts), len(gold_parts))
    return int(match.group(2)) if shorter > 0 and cited_parts[-shorter:] == gold_parts[-shorter:] else None


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "correct": {"type": "boolean"},
                    "cited_ok": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["label", "correct", "cited_ok", "reason"],
            },
        }
    },
    "required": ["grades"],
}

JUDGE_PROMPT = """You are grading replies to a question about {title} against a reference answer.

Question: {question}

Reference answer: {answer}

The passage that answers it, lines {start} to {end} of the text:
<passage>
{passage}
</passage>

{replies}

Each reply cites a line of the text. After each reply, the lines around its citation are shown, so that you can check them.

For each reply, decide two things.

correct: whether the reply answers the question correctly. Correct means that it states the fact in the reference answer and the passage, in any wording. Extra detail is fine unless the passage contradicts it. A reply is incorrect when its answer is wrong or contradicts the passage, when it offers two or more different answers, or when it says that it could not find or does not know the answer. One answer given with low confidence is graded on what it says. Ignore how the reply found its answer.

cited_ok: whether the cited lines themselves state the fact in the reference answer. They may come from a different part of the text than the passage above. If the citation points nowhere, cited_ok is false.

Return one grade per reply, with label set to the reply's label."""


def grade(work: Work, out: Path, limit: int | None, jobs: int) -> None:
    questions = _load_questions(limit)
    runs = {(r["id"], r["arm"]): r for r in _read_jsonl(out / "runs.jsonl")}
    texts = {c.key: _sections(work.download(c)) for c in CORPORA.values()}

    def one(question: Question) -> list[Verdict]:
        arms = list(ARMS)
        random.Random(f"{SEED}:{question.id}").shuffle(arms)
        labels = dict(zip("ABC", arms))
        lines, spans = texts[question.corpus]
        replies = "\n\n".join(
            f'<reply label="{label}">\n{runs[(question.id, arm)]["reply"].strip() or "(no reply)"}\n</reply>\n'
            f'<cited label="{label}">\n{_cited_passage(runs[(question.id, arm)]["cited"], question, lines, spans)}\n</cited>'
            for label, arm in labels.items()
        )
        prompt = JUDGE_PROMPT.format(
            title=CORPORA[question.corpus].title, question=question.question, answer=question.answer,
            start=question.start, end=question.end, passage="\n".join(lines[question.start - 1:question.end]),
            replies=replies)
        result = _final(_cached_call(work.calls(out.name) / "judge" / question.id, prompt, work.private,
                                     _schema_flags(JUDGE_SCHEMA), _private_env()))
        grades = {g["label"]: g for g in (result.get("structured_output") or {}).get("grades", [])}
        if set(grades) != set(labels):
            raise SystemExit(f"judge returned labels {sorted(grades)} for {question.id}")
        return [Verdict(question.id, arm, bool(grades[label]["correct"]), bool(grades[label]["cited_ok"]),
                        grades[label]["reason"]) for label, arm in labels.items()]

    with concurrent.futures.ThreadPoolExecutor(jobs) as executor:
        verdicts = [v for batch in executor.map(one, questions) for v in batch]
    verdicts.sort(key=lambda v: (v.id, list(ARMS).index(v.arm)))
    _write_jsonl(out / "verdicts.jsonl", [asdict(v) for v in verdicts])
    print(f"{len(verdicts)} verdicts written to {out / 'verdicts.jsonl'}")


def _cited_passage(cited: str | None, question: Question, lines: list[str], spans: list[Span]) -> str:
    """The section that holds the cited line, or 10 lines either side when no section does."""
    line = _cited_line(cited, question)
    if line is None or not 1 <= line <= len(lines):
        return "(the citation does not point to a line of this text)"
    at = bisect.bisect_right([span.start for span in spans], line) - 1
    if at >= 0 and spans[at].start <= line <= spans[at].end:
        low, high = spans[at].start, spans[at].end
    else:
        low, high = max(1, line - 10), min(len(lines), line + 10)
    return f"lines {low} to {high}:\n" + "\n".join(lines[low - 1:high])


OUTCOMES = {
    "correct": "Correct",
    "found": "Found",
    "cited_ok": "Cited lines state the answer",
}


def report(out: Path, limit: int | None) -> None:
    questions = _load_questions(limit)
    runs = {(r["id"], r["arm"]): r for r in _read_jsonl(out / "runs.jsonl")}
    verdicts = {(v["id"], v["arm"]): v for v in _read_jsonl(out / "verdicts.jsonl")}
    meta = json.loads((out / "meta.json").read_text())

    def outcome(name: str, qid: str, arm: str) -> bool:
        return bool(runs[(qid, arm)]["found"] if name == "found" else verdicts[(qid, arm)][name])

    text = [
        "# Lookup results",
        "",
        f"Generated by `uv run evals/harness.py report` from `questions.jsonl`, `runs.jsonl` and `verdicts.jsonl`. "
        f"Agent and judge `{meta['model']}` in Claude Code {meta['claude_code']}, rankgrep at commit "
        f"`{meta['plugin_commit'][:12]}`, run on {meta['date']}. One run per question per arm.",
        "",
        "- Correct: the judge says the answer states the reference fact.",
        "- Found: the cited line is inside the section the question was written from. No model involved.",
        "- Cited lines state the answer: the judge says the section around the cited line states the reference fact, "
        "wherever in the text it is.",
        "",
        "Brackets hold 95% Wilson intervals.",
    ]
    for corpus in CORPORA.values():
        ids = [q.id for q in questions if q.corpus == corpus.key]
        if not ids:
            continue
        overlaps = [q.overlap for q in questions if q.corpus == corpus.key]
        text += ["", f"## {corpus.title}", "",
                 f"{len(ids)} questions. Text from {corpus.url}, sha256 `{corpus.sha256}`. "
                 f"A question shares a median {statistics.median(overlaps):.0%} of its search terms with its section "
                 f"(range {min(overlaps):.0%} to {max(overlaps):.0%}).", "",
                 "| Arm | " + " | ".join(OUTCOMES.values()) + " |", "| --- " * (len(OUTCOMES) + 1) + "|"]
        for arm in ARMS:
            text.append(f"| {arm} | " + " | ".join(
                _rate(sum(outcome(name, i, arm) for i in ids), len(ids)) for name in OUTCOMES) + " |")
        text += ["", "| Arm | Tool calls, median | Refused calls, total | Tokens, median | Cost per question, mean | Seconds, median | Errors |",
                 "| --- | --- | --- | --- | --- | --- | --- |"]
        for arm in ARMS:
            rows = [runs[(i, arm)] for i in ids]
            text.append(
                f"| {arm} | {statistics.median(sum(r['tool_calls'].values()) for r in rows):g} "
                f"| {sum(r['blocked'] for r in rows)} | {statistics.median(r['tokens'] for r in rows):,.0f} "
                f"| ${statistics.mean(r['cost_usd'] for r in rows):.3f} | {statistics.median(r['seconds'] for r in rows):g} "
                f"| {sum(r['error'] is not None for r in rows)} |")
        text += ["", "rankgrep against rg on the same questions:", ""]
        for name, label in OUTCOMES.items():
            only_rankgrep = sum(outcome(name, i, "rankgrep") and not outcome(name, i, "rg") for i in ids)
            only_rg = sum(outcome(name, i, "rg") and not outcome(name, i, "rankgrep") for i in ids)
            text.append(f"- {label}: only rankgrep on {only_rankgrep}, only rg on {only_rg}. "
                        f"Exact two-sided sign test, p = {_sign_test(only_rankgrep, only_rg):.2f}.")
    text += ["", "## Per question", "",
             "C is correct, F is found, S is cited lines state the answer, and a dash is none of them.", "",
             "| Question | Term overlap | " + " | ".join(ARMS) + " |", "| --- " * (len(ARMS) + 2) + "|"]
    for question in questions:
        marks = ["".join(letter for letter, name in zip("CFS", OUTCOMES) if outcome(name, question.id, arm)) or "-"
                 for arm in ARMS]
        text.append(f"| {question.id} | {question.overlap:.0%} | " + " | ".join(marks) + " |")
    (out / "summary.md").write_text("\n".join(text) + "\n")
    print((out / "summary.md").read_text())


def _rate(count: int, total: int) -> str:
    low, high = _wilson(count, total)
    return f"{count}/{total} [{low:.0%}, {high:.0%}]"


def _wilson(count: int, total: int, z: float = 1.96) -> tuple[float, float]:
    p = count / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _sign_test(a: int, b: int) -> float:
    n = a + b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(a, b) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _cached_call(stem: Path, prompt: str, cwd: Path, flags: list[str], env: dict[str, str]) -> list[dict]:
    """Run claude -p once per distinct model, prompt and flags, and keep its stream-json output.

    API errors and crashes are retried, because they say nothing about the
    agent. Any other outcome, including a failed or over-budget run, is kept.
    """
    path = _call_path(stem, prompt, flags)
    if path.exists():
        return _read_stream(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["claude", "-p", "--model", MODEL, "--output-format", "stream-json", "--verbose",
               "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "project",
               "--permission-mode", "dontAsk", *flags]
    for _ in range(3):
        process = subprocess.run(command, input=prompt, cwd=cwd, env=env, capture_output=True, text=True,
                                 timeout=RUN_TIMEOUT_S)
        events = [json.loads(line) for line in process.stdout.splitlines() if line.startswith("{")]
        result = next((e for e in events if e.get("type") == "result"), None)
        if result is not None and not result.get("api_error_status"):
            temporary = path.with_suffix(".partial")
            temporary.write_text(process.stdout)
            temporary.rename(path)
            return events
    raise SystemExit(f"claude -p failed three times for {path}: {process.stderr.strip()[-500:]}")


def _call_path(stem: Path, prompt: str, flags: list[str]) -> Path:
    key = hashlib.sha256("\0".join([MODEL, prompt, *flags]).encode()).hexdigest()[:10]
    return stem.with_name(f"{stem.name}-{key}.jsonl")


def _read_stream(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith("{")]


def _final(stream: list[dict]) -> dict:
    return next(e for e in stream if e.get("type") == "result")


def _schema_flags(schema: dict) -> list[str]:
    return ["--tools", "", "--json-schema", json.dumps(schema), "--max-budget-usd", "1"]


def _private_env() -> dict[str, str]:
    keep = ("HOME", "PATH", "LANG", "USER", "TERM", "ANTHROPIC_API_KEY")
    return {k: os.environ[k] for k in keep if k in os.environ} | {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    }


def _agent_env(work: Work) -> dict[str, str]:
    """No variable from the calling session reaches the agent, and its
    rankgrep environment, index and uv cache live under the work folder."""
    return _private_env() | {"XDG_CACHE_HOME": str(work.cache)}


def _sections(path: Path) -> tuple[list[str], list[Span]]:
    lines = read_lines(path)
    return lines, chunk(lines, is_markdown(path, lines))


def _eligible(corpus: Corpus, lines: list[str], spans: list[Span]) -> list[Span]:
    if corpus.body is None:
        return list(spans)
    first = next(i for i, line in enumerate(lines, 1) if line.startswith(corpus.body[0]))
    last = next(i for i, line in enumerate(lines, 1) if line.startswith(corpus.body[1]))
    return [span for span in spans if first < span.start and span.end < last]


_STRAIGHT = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "`": None, "*": None, "_": None})


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_STRAIGHT).casefold().split())


def _load_questions(limit: int | None) -> list[Question]:
    questions = [Question(**q) for q in _read_jsonl(QUESTIONS)]
    if limit is None:
        return questions
    return [q for q in questions if int(q.id.rsplit("-", 1)[1]) <= limit]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout


def _plugin_commit(work: Work) -> str:
    return (work.plugin.parent / "rankgrep.commit").read_text().strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("fetch", "questions", "run", "grade", "report", "all"))
    parser.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "notes-desk",
                        help="folder for downloads, agent folders and cached claude calls")
    parser.add_argument("--out", type=Path, default=RESULTS, help="folder for runs.jsonl, verdicts.jsonl and summary.md")
    parser.add_argument("--limit", type=int, help="use only the first N questions of each corpus")
    parser.add_argument("--jobs", type=int, default=4, help="claude -p processes at once")
    args = parser.parse_args()
    work = Work(args.work.resolve())
    out = args.out.resolve()
    if args.stage in ("fetch", "all"):
        fetch(work)
    if args.stage in ("questions", "all") and not (args.stage == "all" and QUESTIONS.exists()):
        write_questions(work, args.jobs)
    if args.stage in ("run", "all"):
        run_arms(work, out, args.limit, args.jobs)
    if args.stage in ("grade", "all"):
        grade(work, out, args.limit, args.jobs)
    if args.stage in ("report", "all"):
        report(out, args.limit)


if __name__ == "__main__":
    main()
