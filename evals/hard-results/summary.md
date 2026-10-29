# Hard documentation lookup

914 files, 24,354,998 bytes. Python 3.14.0 and PostgreSQL 18.0. Agent and judge: `claude-sonnet-5-5`, Claude Code 2.1.312. Plugin `7983ad0122a0ae9d8a5ab3d163ab29ba1fea5b6d`; 2026-10-29. One run per question per arm.

Correct requires every part of the question, consistent with the reference evidence. Supported requires correct plus citations supporting every part. Gold recall measures overlap with curated evidence ranges, not correctness; alternative valid passages can score low. Counts are descriptive: six curated questions per axis, overlapping topics, no population-level significance claim.

| Axis | Arm | Correct | Supported | Gold recall, mean | Cost/question | Seconds, median | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| direct | closed-book | 6/6 | 0/6 | 0% | $0.008 | 5.1 | 0 |
| direct | rg | 6/6 | 6/6 | 92% | $0.032 | 7.65 | 0 |
| direct | rankgrep | 6/6 | 6/6 | 75% | $0.041 | 10.5 | 0 |
| vague | closed-book | 5/6 | 0/6 | 0% | $0.013 | 9.4 | 0 |
| vague | rg | 6/6 | 6/6 | 100% | $0.036 | 10.15 | 0 |
| vague | rankgrep | 6/6 | 5/6 | 83% | $0.045 | 12.85 | 0 |
| constraints | closed-book | 5/6 | 0/6 | 0% | $0.014 | 10.1 | 0 |
| constraints | rg | 6/6 | 5/6 | 83% | $0.030 | 11.25 | 0 |
| constraints | rankgrep | 6/6 | 4/6 | 67% | $0.063 | 14.75 | 0 |
| multi-hop | closed-book | 6/6 | 0/6 | 0% | $0.015 | 10.2 | 0 |
| multi-hop | rg | 6/6 | 5/6 | 83% | $0.043 | 12.8 | 0 |
| multi-hop | rankgrep | 6/6 | 6/6 | 100% | $0.064 | 13.75 | 0 |

## Per question

| Question | Axis | closed-book | rg | rankgrep |
| --- | --- |  --- | --- | --- |
| direct-01 | direct | correct only | supported | supported |
| direct-02 | direct | correct only | supported | supported |
| direct-03 | direct | correct only | supported | supported |
| direct-04 | direct | correct only | supported | supported |
| direct-05 | direct | correct only | supported | supported |
| direct-06 | direct | correct only | supported | supported |
| vague-01 | vague | correct only | supported | supported |
| vague-02 | vague | correct only | supported | supported |
| vague-03 | vague | incorrect | supported | supported |
| vague-04 | vague | correct only | supported | supported |
| vague-05 | vague | correct only | supported | supported |
| vague-06 | vague | correct only | supported | correct only |
| constraints-01 | constraints | correct only | supported | supported |
| constraints-02 | constraints | incorrect | supported | correct only |
| constraints-03 | constraints | correct only | correct only | correct only |
| constraints-04 | constraints | correct only | supported | supported |
| constraints-05 | constraints | correct only | supported | supported |
| constraints-06 | constraints | correct only | supported | supported |
| multi-hop-01 | multi-hop | correct only | supported | supported |
| multi-hop-02 | multi-hop | correct only | correct only | supported |
| multi-hop-03 | multi-hop | correct only | supported | supported |
| multi-hop-04 | multi-hop | correct only | supported | supported |
| multi-hop-05 | multi-hop | correct only | supported | supported |
| multi-hop-06 | multi-hop | correct only | supported | supported |
