# Terra: optional corpus controls

15 reserved questions, five topics, two independent sessions per arm/question. No required tool use. Primary metric is upstream evidence coverage, not answer accuracy.

| Arm | Coverage@20 | Recall@20 | Used / hits | Stats returned | Weights requested | Median seconds | Mean output tokens | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| free | 71.39% | 29.37% | 0/30 / 0/30 | 0/30 | 0/30 | 9.92 | 497 | 0 |
| original | 72.22% | 30.85% | 1/30 / 1/30 | 0/30 | 0/30 | 11.33 | 543 | 0 |
| controls | 73.33% | 30.82% | 1/30 / 1/30 | 0/30 | 0/30 | 12.03 | 553 | 0 |

## Paired coverage differences

Repeats are averaged within question before topic-stratified paired bootstrap (10,000 draws). Intervals are descriptive for this small reserved sample, not proof of broad generalization.

- controls minus original: +1.11 pp; 95% interval [+0.00, +3.33] pp.
- controls minus free: +1.94 pp; 95% interval [+0.00, +4.17] pp.

Predeclared screening bar met: **False**.

Mean absolute coverage gap between independent repeats: free 1.67 pp, original 0.00 pp, controls 2.22 pp.

## Per-question repeat means

| Topic | Question | free | original | controls |
| --- | --- | --- | --- | --- |
| angular | 77057726 | 66.67% | 66.67% | 83.33% |
| angular | 78212630 | 0.00% | 0.00% | 0.00% |
| angular | 78523046 | 0.00% | 0.00% | 0.00% |
| godot | 76560345 | 100.00% | 100.00% | 100.00% |
| godot | 78288487 | 50.00% | 50.00% | 50.00% |
| godot | 78467185 | 0.00% | 0.00% | 0.00% |
| langchain | 75952371 | 100.00% | 100.00% | 100.00% |
| langchain | 78171159 | 100.00% | 100.00% | 100.00% |
| langchain | 78631323 | 100.00% | 100.00% | 100.00% |
| laravel | 76330103 | 100.00% | 100.00% | 100.00% |
| laravel | 78340907 | 87.50% | 100.00% | 100.00% |
| laravel | 78600376 | 66.67% | 66.67% | 66.67% |
| yolo | 75121807 | 100.00% | 100.00% | 100.00% |
| yolo | 77017189 | 100.00% | 100.00% | 100.00% |
| yolo | 78092718 | 100.00% | 100.00% | 100.00% |

Upstream pooled, model-generated labels can omit valid evidence. The controls condition changes both CLI capabilities and their skill documentation, so it does not isolate the effect of either flag. Control usage counts direct recognized native commands, not arbitrary scripts or aliases. Weights requested does not imply a successful weighted search. Costs exclude warmup, installation and index construction; latency and token usage are descriptive. Requested priority is not independently verified as backend tier. See [frozen protocol](../CONTROLS.md).
