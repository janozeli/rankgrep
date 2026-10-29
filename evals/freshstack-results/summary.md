# FreshStack: free agent vs free agent with rankgrep

Same model, default tools, unrestricted shell/pipelines and budget; only the plugin differs. Scoring uses upstream nugget/document judgments, not an answer judge or citation-length rule. Coverage measures the final selected documents, not every file the agent encountered.

| Topic | Queries | Arm | Coverage@20 | Recall@20 | All nuggets@20 | Cost/query | Seconds, median | Used rankgrep | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| angular | 10 | free | 72.50% | 28.93% | 50.00% | $0.049 | 12.50 | 0/10 | 0 |
| angular | 10 | free+rankgrep | 76.67% | 33.15% | 50.00% | $0.050 | 14.80 | 0/10 | 0 |
| godot | 10 | free | 59.33% | 28.19% | 20.00% | $0.071 | 24.45 | 0/10 | 0 |
| godot | 10 | free+rankgrep | 58.67% | 27.86% | 30.00% | $0.070 | 24.12 | 0/10 | 0 |
| langchain | 10 | free | 55.00% | 19.52% | 30.00% | $0.059 | 14.38 | 0/10 | 0 |
| langchain | 10 | free+rankgrep | 45.60% | 14.39% | 20.00% | $0.052 | 10.63 | 0/10 | 0 |
| laravel | 10 | free | 93.33% | 51.69% | 90.00% | $0.046 | 11.49 | 0/10 | 0 |
| laravel | 10 | free+rankgrep | 73.33% | 41.12% | 70.00% | $0.041 | 10.71 | 0/10 | 0 |
| yolo | 10 | free | 58.33% | 25.51% | 50.00% | $0.050 | 12.06 | 0/10 | 0 |
| yolo | 10 | free+rankgrep | 69.17% | 34.61% | 50.00% | $0.047 | 11.48 | 0/10 | 0 |
| all | 50 | free | 67.70% | 30.77% | 48.00% | $0.055 | 12.98 | 0/50 | 0 |
| all | 50 | free+rankgrep | 64.69% | 30.22% | 44.00% | $0.052 | 13.17 | 0/50 | 0 |

Total recorded model usage: $5.347. The augmented agent loaded the rankgrep skill in 0 of 50 questions. Used rankgrep counts questions with the plugin launcher's absolute path in a Bash call; inspect traces for indirect invocation.

Each topic uses a fixed hash-selected sample. One run per question/arm; small differences are not a reliable ranking. Upstream labels are model-generated and pooled: unseen valid evidence may receive no credit. Both arms have the same default tool set and 24-turn/$2 per-call budget; rankgrep is optional in the augmented arm. Timings exclude setup. Cached reruns are not independent trials.
