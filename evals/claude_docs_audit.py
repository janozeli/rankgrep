"""Apply disclosed post-hoc alternative evidence labels uniformly to every condition."""
import json
import statistics

import claude_docs as c
import freshstack_data as d


def coverage(row, additions):
    covered = row['covered'].copy()
    for label in additions:
        if label['id'] == row['id']:
            covered[label['group']] |= any(
                citation['start'] <= alternative['start'] <= alternative['end'] <= citation['end']
                for alternative in label['alternatives'] for citation in row['citations'])
    return covered


def main():
    c.report()  # Validate the original frozen metrics and citation parsing first.
    labels = json.loads((c.OUT / 'alternative-evidence.json').read_text())
    assert labels['manifest_sha256'] == d.sha(c.OUT / 'manifest.json')
    assert labels['runs_sha256'] == d.sha(c.OUT / 'runs.jsonl')
    corpus = c.corpus()
    qs = {q['id']: q for q in json.loads((c.OUT / 'questions.json').read_text())}
    assert len({(a['id'], a['group']) for a in labels['additions']}) == len(labels['additions'])
    for a in labels['additions']:
        assert 0 <= a['group'] < len(qs[a['id']]['reference_lines'])
        for alternative in a['alternatives']:
            assert 1 <= alternative['start'] <= alternative['end'] <= corpus['lines']
            assert alternative['rationale']
    rows = d.read_rows(c.OUT / 'runs.jsonl')
    lines = ['# Post-hoc citation audit', '',
        'Author-reviewed equivalent passages, pooled from all conditions and applied equally. '
        'Original labels and scores remain unchanged. This is not a preregistered or blinded metric, '
        'and it does not grade the generated answers.', '',
        '| Condition | Strict reference coverage | Audited evidence coverage | All groups supported |',
        '| --- | --- | --- | --- |']
    audits = []
    for r in rows:
        covered = coverage(r, labels['additions'])
        audits.append({'id': r['id'], 'arm': r['arm'], 'covered': covered,
                       'coverage': sum(covered) / len(covered)})
    for arm in c.ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        ars = [r for r in audits if r['arm'] == arm]
        lines.append(f"| {arm} | {statistics.mean(r['reference_coverage'] for r in rs):.2%} | "
                     f"{statistics.mean(r['coverage'] for r in ars):.2%} | "
                     f"{sum(all(r['covered']) for r in ars)}/{len(ars)} |")
    lines += ['', 'The evidence labels identify exact alternative spans and rationales in '
              '`alternative-evidence.json`. A citation must contain the whole alternative span. '
              'This audit repairs known reference omissions, not missing or invalid citations. '
              'It supports no population-level accuracy claim and no stable ranking from eight questions.']
    d.write_rows(c.OUT / 'citation-audit.jsonl', audits)
    (c.OUT / 'audited-summary.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
