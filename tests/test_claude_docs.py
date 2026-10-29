import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'evals'))
import claude_docs as c
import claude_docs_audit as a


def test_citation_limits_prevent_whole_corpus_credit():
    reply = json.dumps({'answer': 'x', 'citations': [
        {'path': 'docs/claude-code.md', 'start': 1, 'end': 1000},
        {'path': '../gold.json', 'start': 1, 'end': 2},
        {'path': '/workspace/docs/claude-code.md', 'start': 10, 'end': 49},
        {'path': 'docs/claude-code.md', 'start': True, 'end': 2}]})
    citations, invalid = c.parse(reply, 1000)
    assert invalid == 3 and citations == [{'path': 'docs/claude-code.md', 'start': 10, 'end': 49}]
    assert c.score({'reference_lines': [[10, 500], [50]]}, citations)['reference_coverage'] == .5


def test_fenced_reply_and_citation_budget():
    refs = [{'path': 'docs/claude-code.md', 'start': n, 'end': n} for n in range(1, 10)]
    citations, invalid = c.parse('```json\n' + json.dumps({'citations': refs}) + '\n```', 100)
    assert len(citations) == 8 and invalid == 1
    assert c.score({'reference_lines': [[9]]}, citations)['reference_coverage'] == 0


def test_alternative_evidence_requires_the_entire_reviewed_span():
    labels = [{'id': 'q', 'group': 0, 'alternatives': [{'start': 10, 'end': 14}]}]
    row = {'id': 'q', 'covered': [False], 'citations': [{'start': 10, 'end': 13}]}
    assert a.coverage(row, labels) == [False]
    row['citations'][0]['end'] = 14
    assert a.coverage(row, labels) == [True]
    assert row['covered'] == [False]
