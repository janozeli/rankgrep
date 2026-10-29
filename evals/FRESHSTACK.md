# Does rankgrep help a free agent?

The experiment compares **a free agent** with **the same free agent plus the rankgrep plugin**. Both have the normal Claude Code tool set, including Bash, Read, scripts, pipelines, and the other default tools. Shell tools such as rg, grep, find, and glob expansion remain available. There is no program allowlist, shell filter, or requirement to use rankgrep. The augmented agent can combine rankgrep with rg and anything else it normally uses. The only tool-configuration difference is `--plugin-dir`.

This matches rankgrep's Unix role: a small search command that takes keywords and paths, prints structured results, and composes with the rest of the shell. The question is whether making it available improves the agent's work, not whether it can replace the other tools.

## Why FreshStack

The earlier local questions saturated on answer correctness, and citation-format rules caused most apparent differences. More paraphrasing alone did not solve that problem. We need real user questions, a large technical corpus, and relevance labels that exist before either agent runs.

[FreshStack](https://fresh-stack.github.io/) targets retrieval over technical documentation and code for community-asked Stack Overflow questions. Its October 2024 release covers Angular, Godot, LangChain, Laravel, and YOLO. Each question has answer facts, called nuggets, and published document-level judgments for those facts. The [paper](https://arxiv.org/abs/2504.13128) describes GPT-4o nugget generation and pooled relevance assessment; these are not fully human-labeled or exhaustive judgments.

[BRIGHT](https://brightbenchmark.github.io/) and its [Bright-Pro extension](https://github.com/yale-nlp/Bright-Pro) are useful reasoning-intensive retrieval benchmarks, including agentic evaluation in Bright-Pro. FreshStack is the closer primary fit here because its task is finding canonical technical evidence for real developer questions. We use the released dataset, not freshly generated questions or answers written from hand-picked passages.

The pinned snapshot is from 2024. We make no claim that it is new to the answering model in 2026. Instead of scoring an answer that the model might remember, we score the local documents it actually selects. Familiarity can still help search. This is an agentic adaptation of FreshStack, not a reproduction of its zero-shot retriever leaderboard or its answer-generation experiment.

## Data and materialization

The two Hugging Face releases are [queries-oct-2024](https://huggingface.co/datasets/freshstack/queries-oct-2024) and [corpus-oct-2024](https://huggingface.co/datasets/freshstack/corpus-oct-2024). `freshstack-sources.json` pins both repository revisions, all ten Parquet URLs, byte sizes, and SHA-256 hashes. Downloads stay outside the repository. PyArrow is an evaluation-only dependency; rankgrep's runtime dependencies are unchanged.

All corpus documents are available, not only the relevant ones or a small distractor sample. The release includes both documentation and source code. Its original chunk boundaries are retained because relevance labels refer to those chunks. A chunk becomes a local file with the upstream source hierarchy and extension preserved, plus its upstream byte-range suffix. For example, `repo/guide.md_0_100` becomes `docs/repo/guide.md_0_100.md`. This preserves useful directory names, glob patterns, and native Markdown handling. We do not add answer facts, relevance labels, source URLs, or synthetic text to searchable content.

Some upstream corpus IDs repeat, including conflicting text. We match the [official DataLoader](https://github.com/fresh-stack/freshstack/blob/f1c4ec96477f5100f10c83798d33b3101db727fa/freshstack/datasets/data_loader.py): the last row for an ID wins. There are 271,816 distinct chunks across all five topics. Native rankgrep can split those files further and applies its usual directory/file selection behavior. Scoring maps a selected file back to the original benchmark chunk; it does not claim that any one returned sub-window supports the whole fact.

## Protocol

The default run uses ten questions per topic, selected by sorting a fixed hash of seed, topic and query ID. Selection is independent of measured results and is written before any model call. That gives 50 paired questions and 100 agent calls. `--sample 0` runs all 672 upstream questions. No question text is rewritten. The prompt contains the original title and body, the local library location, and the request to select up to 20 supporting document paths.

The sample is balanced by topic, not by ambiguity or reasoning difficulty. Nugget count describes answer breadth; it is not a validated difficulty rating.

Both arms use the same model, default tools, permission mode, prompt, budget, corpus, and clean scratch-directory layout. Calls run in seeded shuffled order. The rankgrep plugin is loaded normally only in the augmented arm; the agent decides whether to load its skill or run its launcher. The repository's development virtualenv is removed from the common agent PATH so the baseline does not accidentally inherit a `rankgrep` executable from `uv run`.

Each call allows 24 turns and $2 of CLI-reported model usage. The default tools and `bypassPermissions` mode leave shell composition available. User/project memories and external MCP configuration are excluded equally for reproducibility; this does not selectively disable built-in search, browser, shell, or agent tools. The run records the actual tool list and refuses results if the model, CLI version, or default tool sets/common plugins/skills differ between calls. It verifies that the rankgrep plugin and skill are exposed only in the augmented arm.

The reference library is shared through a symlink, with a separate scratch directory per question and arm. Its bytes and file set are checked after the runs. Answers, nuggets, and relevance judgments are not placed in those directories or prompts. This is not an operating-system sandbox: a free shell can access other host paths. The saved tool-call inputs must be inspected for benchmark-label access or baseline contamination before interpreting the results. There is no hook restricting the agent to a particular executable.

The plugin is copied from committed HEAD on first setup and its commit is recorded. Index warmup is setup, outside per-question latency; later searches use the ordinary cache. To measure a changed plugin, commit it and use a new `--work` directory. Per-question time is CLI-reported. Tool calls, replies, token usage, costs, invalid paths and execution errors are retained.

## Scoring

No new model grades these runs. The upstream relevance judgments are fixed before search. Valid selected paths are mapped to document IDs and deduplicated. The 20-slot limit is applied before invalid entries are removed; returning more or repeating a document cannot increase the budget. Failed calls receive zero credit and remain in the denominator.

- **Coverage@20**, the primary metric: the fraction of a question's nuggets supported by at least one selected document.
- **Recall@20:** the fraction of all known relevant documents selected. One document can support several nuggets, so this is different from coverage.
- **All nuggets@20:** whether every nugget has at least one supporting selected document.
- **Judged@20**, retained per query: the fraction of the 20 result slots occupied by documents assessed for that question. Empty slots count as zero.

Coverage and recall follow the [upstream metric definitions](https://github.com/fresh-stack/freshstack/blob/f1c4ec96477f5100f10c83798d33b3101db727fa/freshstack/retrieval/metrics.py). The leaderboard's Recall@50 is not reported as if an agent returning 20 files had a 50-document budget. We do not implement or claim alpha-nDCG leaderboard comparability.

Unjudged documents receive no credit; that does not prove they are irrelevant. This measures the final evidence selection, not all text encountered, final answer quality, or coding-task success. One run per question captures neither run-to-run variation nor a stable ranking of tools. Report small differences descriptively, together with actual rankgrep adoption and usage cost.

## Run

```
uv run --group eval evals/freshstack.py all
uv run --group eval evals/freshstack.py all --sample 0 --out /tmp/freshstack-full-results
```

The default work directory is `/tmp/rankgrep-freshstack`; `--work` changes it. The corpus downloads are about 260 MB, expand to hundreds of MB of text, and produce many files and index caches. `--topics langchain` selects one topic. `--sample N` changes the questions per topic, and `--jobs N` changes concurrent model calls (default 4). The stages `fetch`, `run`, and `report` can also run separately. Calls with identical model, prompt, flags and run provenance reuse cached outputs; a cached rerun is not an independent trial. New evaluations should use a new output directory to preserve previous results.

The default 100 calls have a theoretical total cap of $200, not including possible infrastructure-error retries. Actual recorded usage is in the results. An authenticated Claude Code CLI and uv are required. The report can be regenerated from saved runs without model calls once the pinned corpus and plugin workspace exist. Run `uv run --group eval pytest -q` for all tests, including real Parquet checksum and duplicate-ID validation; CI uses this command.

## Attribution and results

FreshStack is by Nandan Thakur, Jimmy Lin, Sam Havens, Michael Carbin, Omar Khattab, and Andrew Drozdov (University of Waterloo and Databricks). The released datasets are **CC BY-SA 4.0**; their original source repositories retain their licenses. We download the data rather than bundle it. Upstream questions and labels are unchanged; local file paths are an adaptation described above. See the dataset cards and paper for provenance, licensing and limitations.

[Results](freshstack-results/summary.md) include the frozen selection, dataset/plugin provenance, per-question evidence lists, tool calls and usage. The earlier experiments remain historical records; this is the test of rankgrep as an optional Unix tool in a free agent's toolbox.

### Observed run

On 2026-10-29, Claude Sonnet 5.5 (`claude-sonnet-5-5`, Claude Code 2.1.312) completed the default 50 paired questions over all five full corpora. The 100 calls reported $5.347 of model usage and no execution errors. The selected questions have two to seven nuggets each. Every session had the same default tool set; all 414 observed tool calls used Bash. Inspection of their inputs found no benchmark-label access or baseline rankgrep invocation. The corpus byte/file-set checks passed after every topic.

The augmented agent had the plugin and skill available in all 50 sessions, but **never loaded the skill or invoked rankgrep**. Mean Coverage@20 was 67.70% for the free agent and 64.69% with rankgrep available. These observations do not estimate the effect of executing rankgrep: the actual searches used ordinary shell tools in both groups. Differences can arise from stochastic behavior and the additional plugin context. This is an adoption result, not evidence that either search engine is better.

There were 13 invalid submitted paths in three augmented responses. Eleven paths in Laravel questions `76083286` and `76823724` omitted the outer `docs/` prefix; two Godot paths named nonexistent chunks. The primary scores retain the declared path contract and give these entries no credit. As a **post-hoc diagnostic only**, restoring the omitted prefix in those two Laravel responses raises the augmented group's mean coverage to 68.69%. This reversal shows why even the direction of the raw gap should not be read as a retrieval advantage. Neither the saved selections nor the primary report are repaired. The task measures usable evidence paths as well as evidence selection.

Validation included 50 passing tests, the plugin sync check, and a real `--files-from -`/JSON-stdout pipeline. Recomputed saved scores matched all 100 records; coverage matched the upstream implementation and recall matched NIST `trec_eval` 9.0.8 (tolerance 0.0001 for printed rounding). One sol-loop round with GPT-6.1 Sol approved the implementation and protocol without findings or code changes; generated results were audited separately. Review usage was not exposed. The reviewed diff was 729 insertions and 3 deletions before and after review; subsequent additions document the observed results and their limits.
