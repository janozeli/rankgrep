# Isolated Codex replication and adoption experiments

The first phase repeats the 50 paired FreshStack questions from `freshstack-results`, with the original `freshstack.prompt`, original scoring, all five complete corpora and the plugin frozen at `31379def63c8eb4a21f0be3ecf5f1e2e52ff8a00`. Neither the skill description nor its body changes. The requested model is GPT-6 Astra with medium reasoning and priority service (fast). Session records verify model and reasoning effort; priority is the configured request, not a claim about backend scheduling.

Each call runs inside a new Bubblewrap mount/PID namespace with a new personal directory and scratch directory. Host user configuration, memories, sessions, skills and plugins are absent. The environment contains only HOME (the unchanged account path, backed by the fresh directory), PATH (explicit runtime binaries) and LANG. Only the authentication file is mounted from the host personal directory. No credential contents are copied to results or prompts. The system mounts contain runtime binaries, CA certificates, DNS and account-name lookup files, not the host's general `/etc` configuration. Network remains available to the native agent tools and model API.

The corpus is mounted read-only at `/workspace/docs`. The baseline has no plugin mount. The augmented arm installs the unchanged plugin through Codex's native local marketplace installer. Bundled/personal skills, remote apps/plugins and memories are disabled; the available skill catalog is checked for exactly zero skills or only `rankgrep:rankgrep`. The initial model-visible context is retained outside the repository and checked for unexpected tool namespaces and known host instructions. Native Codex tools remain available without search-tool filters. Tool definitions must match between arms.

A dedicated cache for each corpus is warmed outside measured agent latency, matching the earlier warm-cache protocol. It contains only runtime dependencies and rankgrep indexes, not agent transcripts. Individual sessions do not share their home or scratch directories. The model, effort, prompt hashes, source hashes, runner hashes and requested service tier are recorded. Cached runs must match the manifest.

Codex CLI has no equivalent of Claude Code's `--max-turns 24 --max-budget-usd 2`; those limits are **not enforced or claimed equivalent**. Each invocation has the original 1,200-second infrastructure timeout. Token usage is retained, but no fabricated dollar cost is reported. The model, native tool schemas, skill integration, environment isolation and budget controls differ from the earlier Claude harness, so this is a replication of its questions and scoring, not an experiment changing only model weights. Comparisons of adoption interventions must stay within this Codex harness.

A discarded 40-call diagnostic run revealed late account-plugin downloads despite feature flags; its results are excluded. The final runner disables plugin activation by default, explicitly enables only rankgrep, freezes the plugin/config mounts read-only after installation, and checks actual session skill messages and on-disk plugins after execution. The original preview alone was insufficient. Model-driven inventory probes then returned the same 13 native tools in both arms, zero baseline skills/plugins, and only rankgrep in the augmented arm.

The infrastructure smoke run initially exposed a missing uv executable inside the namespace. It was stopped, excluded from results and retained separately as diagnostic data. A successful rankgrep warmup is now required before any benchmark question in a topic.

Run after downloading/materializing the pinned FreshStack corpora using the existing harness:

```
uv run --group eval evals/codex_freshstack.py --jobs 2
uv run --group eval evals/codex_audit.py
uv run --group eval evals/codex_report.py
uv run --group eval evals/codex_adoption.py --jobs 2
uv run --group eval pytest -q
```

Requires Linux Bubblewrap with usable namespaces, mise-managed Codex/uv installations, and an already authenticated Codex CLI. Work files live under `~/.cache/rankgrep-evals/codex-freshstack`; published results go to `evals/codex-results`. Do not reuse a partial session or change the runner mid-experiment. No adoption variants should run until the original-condition replication finishes.

## Description experiment

After all 100 replication calls finished, a separate experiment compares four catalog descriptions: the original; a factual description of keyword retrieval capabilities; a description of Unix composition and CLI syntax; and a description of the returned evidence fields. Exact treatment text is in `codex_adoption.DESCRIPTIONS` and the saved manifests. Only the skill's frontmatter description changes. Its existing body, including its existing search guidance, launcher, engine and package metadata remain pinned. No treatment adds an instruction to prefer rankgrep, changes the question, or removes any native tools. The production plugin remains unchanged.

Description-run work files live under `~/.cache/rankgrep-evals/codex-adoption-v2`; results go to `evals/adoption-results`. The earlier excluded round remains outside the repository under `~/.cache/rankgrep-evals/codex-adoption/excluded-results`.

The experiment uses six held-out questions: two each from Angular, Godot and LangChain, excluding the original benchmark sample. Within each topic, a fixed hash selects one question with at most three nuggets and one with at least four. This varies the number of evidence requirements; it is not a validated measure of difficulty or vague wording. All six questions run once with each description, including a fresh original-description control. Every selection and treatment manifest is saved before the first experiment call. Conditions are shuffled within each topic with a fixed seed.

The same isolation checks apply to all 24 calls. Each session receives its own copy of the phase-A topic cache, with independent files or copy-on-write clones, and warms the actual installed launcher before timing starts. No mutable runtime environment is shared between concurrent calls. These caches contain dependencies and indexes only, including narrower indexes created during earlier calls and diagnostics. Host I/O contention also occurred during the experiment. Thus latency is descriptive, not a controlled speed comparison. No session history or scratch files are shared. The model sees the same plugin identity and installation path in every condition.

An initial 24-call description round was excluded in full: one control invocation failed to import `bm25s.utils` while sessions shared a mutable runtime cache, although the agent completed normally using other tools. The failure and excluded artifact hashes are retained in [adoption-diagnostic.json](adoption-diagnostic.json). The private-cache rerun keeps exactly the same questions, descriptions and ordering. A regression test distinguishes this dependency traceback from rankgrep's normal no-hits exit code; runtime tracebacks now stop the description experiment instead of being silently scored as successful agent executions.

Adoption is audited from completed native shell execution events. Reading the skill or echoing the launcher does not count. The report separates invocation from a successful command returning structured result lines, and also measures evidence coverage and recall. More tool use alone is not a quality improvement. This small exploratory sample has no independent repetitions and cannot establish a stable winner. Upstream labels are model-generated and pooled, so valid evidence outside the pool may receive no credit.

The [original-condition results](codex-results/summary.md) and [description results](adoption-results/summary.md) retain individual replies, document selections, tool calls, token usage and manifest hashes. Native execution audits retain launcher commands, exit codes and result counts; full private execution logs stay outside the repository. `codex_report.py` and `codex_adoption.py --report` regenerate tables without model calls, given the pinned downloaded data.

## Observed results

In the 100-call replication, rankgrep was invoked and returned structured hits in 35 of 50 augmented sessions. Mean nugget coverage was 72.38% for the free agent and 71.68% with the optional plugin. There were no invalid document paths, agent execution failures or launcher tracebacks.

In the valid 24-call description experiment, the original description was used in 3/6 sessions, capabilities in 6/6, Unix in 0/6, and output fields in 5/6. Every invocation returned structured hits. Coverage was respectively 75.00%, 81.67%, 78.33% and 73.33%. The capabilities gain comes entirely from one Godot question where both descriptions already invoked rankgrep; it does not establish that the extra invocations improved evidence retrieval. This is a candidate for a larger confirmation experiment, not sufficient evidence to change the production description. All 24 private dependency caches had distinct files across sessions, and no launcher traceback, invalid document path or agent execution failure occurred.

Both phases' coverage aggregates were checked against FreshStack's upstream coverage function, and per-question recall against NIST `trec_eval` 9.0.8. The final native-command audit covered all 124 included sessions. The 40-call account-sync diagnostic and 24-call shared-cache description diagnostic are excluded; cached reruns are not counted as independent trials.
