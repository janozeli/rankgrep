# Result: the optional controls did not clear the screening bar

All 90 planned Codex GPT-6.1 Terra medium/priority sessions completed, with zero execution errors and zero invalid submitted paths. The three conditions used the same native tools, original task prompts, pinned corpora and upstream judgments. The reserved sample, execution code, plugin snapshots and scoring were not changed after execution began.

Mean Coverage@20 was 71.39% for the free agent, 72.22% with the original plugin and 73.33% with controls. The primary paired difference was **+1.11 percentage points**, with a topic-stratified question-level bootstrap interval of **[0.00, +3.33] pp**. This misses both the predeclared +5 pp minimum and the requirement that the interval lie entirely above zero. The secondary difference versus free was +1.94 pp, interval [0.00, +4.17] pp. These describe the reserved sample, not a stable ranking or answer accuracy.

Median session times were 9.92, 11.33 and 12.03 seconds respectively, excluding setup. Mean output tokens were 497, 543 and 553. The controls condition stayed within the preset time/output-token limits, but the quality conditions were not met. Full precision, repeat means and paired differences are in [summary.json](summary.json); the readable table is in [summary.md](summary.md).

## What agents actually did

Rankgrep was invoked in **one of 30 sessions in each augmented arm**, with hits returned in both. Both uses concerned Angular question `78212630`, repeat 1. The original arm made one rankgrep command; controls made three ordinary unweighted rankgrep commands. Both first read the installed skill. **No session requested statistics or weights.** The corresponding six sessions had equal evidence coverage.

The entire primary coverage difference comes from Angular question `77057726`; none of its six sessions invoked rankgrep. The extra difference against free comes from Laravel question `78340907`, also without rankgrep use. This is an exploratory trace observation, not a causal attribution to plugin context or model randomness.

Across the 356 native shell events, the observed commands began with ls, rg, cat, rankgrep, find, sed or head. Nested tool calls used shell execution and process polling. Inspection found no benchmark-label access, baseline rankgrep installation, external data fetch or invocation through an alias/script missed by the direct-command audit. [trace-audit.json](trace-audit.json) records counts, input-scan scope and source hashes. The scan alone is not a proof against arbitrary obfuscation; the retained native events and tool-call inputs were also inspected.

The supported conclusion is narrow: **making these optional controls available did not demonstrate useful benefit under the frozen screening rule.** The experiment does not estimate how effective statistics or weights would be when used, and cannot transfer SIRA's pipeline results to this free-agent setting. Adoption is diagnostic, not success. These cases are now development evidence and must not become the target of another tuning-and-test cycle.

The CLI features remain available as composable operations, with deterministic behavior tests. Their implementation correctness is separate from the unproven claim that they improve a free coding agent's work. No new production description, prompt or default was selected from these results.

## Post-run validation repair

The preregistered reporter incorrectly expected the installed native config to be byte-identical to the base config. Native plugin installation adds two expected TOML tables: `plugins."rankgrep@rankgrep"` enables the supplied plugin, and `marketplaces.rankgrep` points to `/plugin`. This produced a reporting assertion after all model sessions had completed; it was not an agent error or contamination.

Only the post-processing validator was repaired: it now accepts exactly those entries for augmented sessions and rejects them for baseline, wrong marketplace paths, or additional plugins. Tests cover both accepted and rejected configurations. All 60 augmented configurations contain exactly those additions; all 30 baseline configurations equal the base. The original manifest and reporter hash are preserved, while [validation-repair.json](validation-repair.json) records the original and repaired reporter hashes. Every other frozen input remains checked exactly. Coverage, parsing, pairing, bootstrap and screening code are unchanged. No session was rerun, excluded or regraded with new relevance labels.

To regenerate the audited report from retained local native logs:

```sh
uv run --group eval evals/controls.py report
```

Exact execution inputs are archived at preregistration commit `f8ea048e63ace6e154c51ba0fcd481f6b0e12374`. The `freeze`/`run` stages intentionally reject the later reporter hash; use the preregistered revision for exact execution replay and this revision for corrected post-processing. Cached records are not independent repetitions. A new experiment requires a separate manifest and workspace.
