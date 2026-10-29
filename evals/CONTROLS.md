# Optional corpus controls: frozen evaluation protocol

This experiment tests whether making corpus statistics and explicit query weights available improves a free agent's evidence selection. It is inspired by [SIRA](https://arxiv.org/abs/2605.06647), not a reproduction: there is no LLM corpus enrichment, reranker, required query expansion, or one-shot restriction. The agent controls its own search process.

## Conditions and sample

All sessions use **Codex GPT-6.1 Terra, medium reasoning, requested priority service**, unrestricted native tools and shell composition. There are three arms:

- `free`: no rankgrep plugin provided.
- `original`: the unchanged plugin from `31379def63c8eb4a21f0be3ecf5f1e2e52ff8a00`.
- `controls`: the plugin from `a66c2dd88cff48aec1ead5927106d64bf7a520d9`, including `--stats`, `--weight`, and their factual skill documentation.

The plugin remains optional. Task prompts never mention rankgrep or its new controls. Original and controls arms retain the original skill's existing search-loop guidance; the change adds optional capabilities and documentation. This compares the capability package, not the causal effect of executing either flag or changing documentation alone. We do not substitute a model if Terra is unavailable.

The sample contains **15 questions: three per FreshStack topic**, selected by ascending hash of `["corpus-controls-v1", topic, query_id]`. It excludes every question in the original 50-question benchmark and the six-question description experiment. Selection does not use text, nuggets, difficulty labels or outcomes. The reservation was generated before either implementation was evaluated, with SHA-256 `45bab069b9aee18ad01ea3bc5aa5a7dd7b3624247abcb1ea15e1e720eac8cec1`. It contains sources, exclusions, query IDs and prompt hashes, not answer evidence.

Each question has **two fresh executions per arm: 90 sessions**. Repeats use distinct homes, scratch directories and session IDs; a cached rerun is not another repeat. Within each topic, all 18 tasks are shuffled using a fixed seed. Topics run in the declared order, with at most two concurrent sessions. All questions, versions, runner files and this protocol are hashed before the first model call. No selection, prompt, tool description, scoring, threshold or runtime tuning is allowed after inspecting outcomes.

These questions are reserved from our earlier evaluation work, not necessarily unseen during model pretraining. Domains overlap earlier experiments. The small sample does not establish broad generalization or validated difficulty categories.

## Corpus, isolation and budget

The full five pinned FreshStack corpora, existing filename mapping and unchanged `freshstack.prompt` are reused. Queries, nuggets and relevance labels are not mounted into the agent environment. Corpora are checked against upstream bytes and file sets before and after each topic. The namespace mounts the corpus read-only. No personal skills, project instructions, memories, account-synchronized plugins or extra MCPs are loaded. Only the authentication file is mounted from the real home; the environment remains an explicit HOME/PATH/LANG allowlist. Both preflight and actual session catalogs, native tool definitions, model and effort are checked.

Each augmented session copies a dedicated, corpus-wide warm seed into its own temporary cache using independent inodes or copy-on-write extents. The installed launcher is warmed before timing. No mutable runtime cache is shared by concurrent agents or successive repeats. Dependency-copy checks are saved; disposable session caches are removed after the call, while homes, rollouts, native event logs, replies and records remain. Seeds have no model-session history. This limits disk usage without carrying state between repetitions.

There is a 1,200-second invocation timeout, no turn limit and no dollar cap. The old Claude budget is not claimed equivalent. Priority is requested configuration, not verified backend service tier. Recorded latency excludes setup, installation and warmup; further indexes for narrowed paths are ordinary task work. Tokens are recorded as usage, not converted to unsupported dollar estimates. Latency and token totals are secondary descriptive measures.

Completed execution failures remain in the denominator with zero evidence credit. Missing audits, context mismatches, launcher dependency failures, timeouts or partial sessions abort the run for investigation; they are not silently retried, dropped or replaced. Any necessary infrastructure repair or exclusion must be disclosed separately. Existing cache records must match the frozen manifest exactly.

## Scoring and interpretation

The primary metric is the unchanged upstream **Coverage@20**: the fraction of answer nuggets supported by at least one selected local document. The existing parser, path contract and 20-slot budget are unchanged. Recall@20, all-nuggets coverage, invalid paths, usage and errors are retained. This measures evidence selection, **not generated-answer accuracy**. Pooled, model-generated labels can miss valid evidence; no post-hoc reference expansion is used to choose a winner.

The primary comparison is `controls` minus `original`. `controls` minus `free` is a secondary practical reference. Average the two repeats within each question before computing paired differences. Report a 95% percentile paired bootstrap interval from 10,000 draws, resampling questions within each topic (seed 20261029); repeats do not turn 15 questions into 30 independent questions. These intervals describe this small, stratified convenience sample and are not a confirmatory generalization claim.

The predeclared screening bar for further investment is: at least **+5 percentage points** mean coverage versus original, a primary paired interval entirely above zero, nonnegative mean coverage difference versus free, and no more than **25% higher** median latency or mean output tokens versus original. This is a practical screening rule, not statistical proof or a reason to discard a valid negative result. Report every condition regardless of whether the bar is met. Do not select a different metric, subset, description or repeat to obtain a favorable result.

Adoption is diagnostic. Native completed command-execution events identify direct rankgrep invocations and structured hits. The controls audit records actual `--stats` output and requested `--weight` arguments, excluding file reads and echoes. It conservatively recognizes direct commands and ordinary shell composition; arbitrary aliases or dynamically generated scripts can evade recognition. A requested weight does not establish successful execution. Multiple commands in one shell event share output, so results are not attributed to individual invocations without inspecting the trace.

After all runs, inspect tool-call inputs for benchmark-label access, baseline installation of rankgrep, and unsupported interpretations of control use. Record observed term/weight choices as exploratory diagnostics; do not infer that statistics caused a change solely from temporal order. Any future improvement informed by these observations requires a new reserved set.

## Reproduction

The corpus setup and attribution are documented in [FRESHSTACK.md](FRESHSTACK.md). This experiment uses only the Codex CLI, not Claude Code. An authenticated Codex installation, Bubblewrap, mise, uv and the pinned dataset files are required.

```sh
uv run --group eval evals/controls.py freeze
uv run --group eval evals/controls.py run
uv run --group eval evals/controls.py report
```

Local execution artifacts live in `~/.cache/rankgrep-evals/corpus-controls`. Committed summaries contain per-session results, frozen manifests and provenance; raw native logs remain local. The report command verifies retained native logs, hashes, contexts, installed plugins and replayed scores without new model calls. Changing a frozen input requires a separate experiment directory and manifest, not overwriting these results.
