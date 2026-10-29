# Codex Astra medium / priority: original conditions

Original questions, prompt, plugin and scoring. Isolated fresh sessions; no adoption interventions. See [protocol and harness differences](../CODEX.md).

| Topic | Arm | Questions | Coverage@20 | Recall@20 | Invoked / returned hits | Seconds, median | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| angular | free | 10 | 64.17% | 23.08% | 0/10 / 0/10 | 21.64 | 0 |
| angular | free+rankgrep | 10 | 70.00% | 22.19% | 9/10 / 9/10 | 27.47 | 0 |
| godot | free | 10 | 66.67% | 35.36% | 0/10 / 0/10 | 22.20 | 0 |
| godot | free+rankgrep | 10 | 55.67% | 26.79% | 8/10 / 8/10 | 25.45 | 0 |
| langchain | free | 10 | 68.57% | 22.51% | 0/10 / 0/10 | 21.47 | 0 |
| langchain | free+rankgrep | 10 | 71.07% | 23.34% | 8/10 / 8/10 | 34.45 | 0 |
| laravel | free | 10 | 93.33% | 51.69% | 0/10 / 0/10 | 15.18 | 0 |
| laravel | free+rankgrep | 10 | 96.67% | 51.69% | 4/10 / 4/10 | 20.67 | 0 |
| yolo | free | 10 | 69.17% | 30.51% | 0/10 / 0/10 | 20.46 | 0 |
| yolo | free+rankgrep | 10 | 65.00% | 32.51% | 6/10 / 6/10 | 26.37 | 0 |
| all | free | 50 | 72.38% | 32.63% | 0/50 / 0/50 | 20.46 | 0 |
| all | free+rankgrep | 50 | 71.68% | 31.30% | 35/50 / 35/50 | 25.73 | 0 |

Invocation is audited from native shell execution events, excluding reads or echoes of the launcher. Returned hits requires exit code 0 and structured rankgrep results in stdout. Timings exclude corpus-wide setup; narrower searches may build additional indexes. One observation per question/arm, not a stable causal ranking. Priority is the requested service tier. Model token usage is retained; dollar costs and the former Claude budget are not claimed equivalent.
