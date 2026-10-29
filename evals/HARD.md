# Hard documentation lookup

This suite asks whether a search tool can find and combine evidence in a larger documentation library when the question does not hand it the right search string. It keeps the original experiment in `evals/results/` unchanged. Run this suite with:

```
uv run evals/hard.py all
```

It needs uv, rg, and an authenticated Claude Code CLI, as the original harness does. Model calls incur usage. Each answering call has a $2 limit and each judge call has a $1 limit; the full suite makes 72 answering calls and 24 judge calls, so those per-call limits are not a small total budget. Actual reported answer costs are in `hard-results/runs.jsonl`. Downloads, plugin copy, indexes, and cached model calls live in `/tmp/rankgrep-hard` by default. Use `--work` to change that folder. Nothing from that folder is committed.

The stages are `fetch`, `validate`, `run`, `grade`, and `report`. `all` runs everything except the separate validation display; question evidence is validated before running. For a pilot, use `--limit 1 --out /tmp/hard-pilot`: one question per axis. Full and pilot runs have different provenance keys. `--jobs` controls concurrent CLI processes, default 4. A repeat with the same provenance reuses calls; it is not an independent trial.

## Corpus

The library has **914 files and 24,354,998 bytes** of documentation: all `.rst` files under CPython's `Doc/` at Python 3.14.0, and all `.sgml` files under PostgreSQL's `doc/src/sgml/` at PostgreSQL 18.0. There is no artificial repetition or filler. Source markup is retained; images, source code, and generated HTML are excluded. These formats exercise rankgrep's plain-text windows rather than its Markdown heading extraction.

Both upstream commit IDs, archive checksums, and a checksum of the selected file manifest are pinned in `hard.py` and recorded in `hard-results/meta.json`. Each arm gets the identical file tree. Extra files or modified bytes make validation fail. The agent knows only that `docs/` holds Python 3.14 and PostgreSQL 18 documentation: it is not handed a target file or line range.

The plugin is copied from the checkout's committed HEAD on the first fetch and its commit is recorded. Later runs in that workspace keep that plugin. To measure a changed plugin, commit it and use a new `--work` folder. Corpus, selected questions, plugin commit, guard, requested model and protocol version form the run provenance key; individual calls additionally hash their prompt and flags. Increment the protocol version if answering semantics change. Grading has a separate version and hashes of its input runs, questions, and output verdicts. Grading refuses a different corpus, question selection, plugin, protocol, model, or CLI version.

## Questions

There are 24 curated questions, six per axis, with three Python and three PostgreSQL questions in each. These were written by the implementing agent from the pinned documentation, not sampled from user traffic. The reference answers and exact evidence ranges were checked against the pinned source files before the answering runs. The script checks ranges and literal quotes on every run. The questions were frozen before the full comparison.

- **Direct:** names the API or setting. This is the control, not a hard-question claim.
- **Vague:** describes a symptom or goal without naming the responsible API or SQL construct. The domain is still given, so the task remains answerable.
- **Constraints:** requires several conditions or exceptions to be satisfied together. A partly right answer fails.
- **Multi-hop:** connects facts in at least two different source files and asks for evidence covering the combined answer.

Examples include a memoizing wrapper that computes twice despite being thread-safe, temporary-file reopening and cleanup rules on Windows, a queue query that skips row locks but can still wait for a table lock, and connecting a process pool's changed startup behavior to the platform's new process-start default.

Using rankgrep's tokenizer, the median fraction of question terms present in the curated evidence is 47.5% for direct, 11.7% for vague, 38.2% for constraints, and 34.1% for multi-hop. This checks the vocabulary gap; it does not establish retrieval difficulty. These are short evidence ranges, so this is not directly comparable to the original experiment's whole-section overlap.

The axes are task categories, not independent causal factors. Topics recur across categories. This is a small diagnostic set, not a random sample or a factorial experiment, and six questions per axis cannot support a general ranking of the tools.

## Protocol and scoring

The original harness supplies isolated Claude Code calls, tool restrictions, the plugin setup, usage accounting, and response caching. This suite retains its three arms: no tools, `rg` plus Read, and rankgrep plus Read. The rankgrep arm loads the plugin skill normally. Tools cannot browse the web or start subagents. The shell hook restricts Bash to the assigned search program, without pipes or command chaining. The skill's suggestion to switch to rg is unavailable in the rankgrep-only arm, as in the original experiment. This does not measure a real agent with both tools available.

Question/arm order is seeded and shuffled. Each question runs once per arm. The agent returns an answer and a list of relative `path:start-end` citations, at most 40 lines per citation. Paths must resolve to existing files inside `docs/`; missing files, escaping paths, invalid line numbers, and oversized ranges are rejected. Reference answers and evidence remain outside the agents' folders.

The judge receives structured answers under shuffled labels (without the raw citation strings), the reference answer, the reference excerpts, and only the exact ranges each reply cites. It sees no arm names. It grades two outcomes:

- **Correct:** all parts of the question are answered consistently with the reference evidence. Equivalent wording and straightforward inferences count; extra reference detail not asked by the question is not required.
- **Supported:** the answer is correct and the cited extracts together support all its required parts. This is stricter than the original experiment's whole-section citation grading.

**Gold recall** is a separate deterministic diagnostic: the fraction of curated evidence ranges overlapped by valid citations. It does not prove semantic support. A citation of another equally good passage can have low gold recall and still pass the judge. Errors count as failures; they are also reported separately. Costs and CLI-reported elapsed times in the report cover answering calls, not judge calls, setup, or the pilot.

The no-tools arm is essential because these public manuals and API behaviors may be familiar to the model. Correct answers without tools do not establish successful retrieval. The judge is the same model family as the answerer, so judge bias remains possible; inspect `verdicts.jsonl` and the saved answers before interpreting small differences. Citation validity and gold-range recall do not use a model.

## Results

See [the generated report](hard-results/summary.md), [answers and usage](hard-results/runs.jsonl), [judge reasons](hard-results/verdicts.jsonl), and [question references](hard-results/questions.jsonl). The report separates all four axes and includes a per-question breakdown. The chart shows fully supported answers, not answers that merely sound right.

Both tool arms answered **24/24** correctly. Fully supported answers under the citation rules were **22/24 for rg** and **21/24 for rankgrep**. The no-tools arm was judged correct on **22/24**, with no supported answers. The answering runs reported $0.8439 for rg, $1.2805 for rankgrep, and $0.2973 without tools; no runs had execution errors. Median CLI-reported durations were 10.15 s, 12.85 s, and 9.4 s respectively. There were 25 refused calls for rg and 28 for rankgrep, so shell restrictions still affect this comparison.

All five tool-arm failures on Supported involved an oversized citation: `constraints-02` for rankgrep (55 lines), `constraints-03` for both tools (41 lines), `multi-hop-02` for rg (58 lines), and `vague-06` for rankgrep (41 lines). Some retained other valid citations, but those did not cover the whole question. The rejected ranges do contain the needed evidence. These are citation-format failures, not demonstrated retrieval failures. The 40-line rule was kept unchanged after inspecting the replies.

The direct control saturated, but so did answer correctness on the other axes. The vocabulary gap alone did not make these familiar documentation questions hard for this model. This run does not establish a retrieval advantage for either tool, and it does not establish that the tool-arm difference on Supported generalizes. It does establish a reproducible larger-corpus test with separate axes and auditable multi-file evidence.

### Grader audit

The first grading was rejected after inspecting its reasons: it marked the logically equivalent CHECK/NULL explanation wrong (`direct-04`, no tools), and credited an oversized citation that was absent from the validated excerpts (`multi-hop-02`, rg). [The initial verdicts](hard-results/verdicts-initial.jsonl) are retained for audit and are never used by the report. Grading version 2 sees only structured answers and validated excerpts, explicitly accepts logical equivalence, and separates correctness from citation quality. All 24 questions were regraded with the same rule; the questions, 72 answering runs, and citation-size limit were not changed. [grading.json](hard-results/grading.json) binds the final verdicts to their input runs and questions.

The implementing agent inspected every final tool-arm citation failure against the source ranges. One no-tools judgment remains arguable: `constraints-02` says directory write permission “(create and delete)”; the judge rejected it for not clearly distinguishing delete access. Counting that as sufficient would raise the no-tools result to 23/24. The report preserves the model verdict, so it is 22/24. This uncertainty does not change either search arm's result. The audit is not an independent human or blinded second-model adjudication.
