# Exploratory description experiments

Six held-out questions, one observation per condition, Astra medium / requested priority. All agents have the optional plugin and unrestricted native tools. Only its catalog description changes.

| Description | Invoked | Returned hits | Coverage@20 | Recall@20 | Median seconds | Mean output tokens | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| original | 3/6 | 3/6 | 75.00% | 30.40% | 19.63 | 668 | 0 |
| capabilities | 6/6 | 6/6 | 81.67% | 33.73% | 39.37 | 742 | 0 |
| unix | 0/6 | 0/6 | 78.33% | 32.06% | 20.94 | 594 | 0 |
| output | 5/6 | 5/6 | 73.33% | 30.16% | 25.77 | 753 | 0 |

Selection uses a fixed hash within two nugget-count strata per topic (at most three / at least four), excluding all original benchmark questions. Nugget count is only a breadth proxy. The sample is small and exploratory, without independent repeats. No winner or adoption improvement is established. Each session has a private copy of the phase-A cache, warmed through the installed launcher; timing is descriptive. Upstream pooled, model-generated labels may omit valid evidence. The original skill body is unchanged, including its existing guidance. Treatments add no tool-first requirement, tool restriction, task hint, or answer evidence.
