"""Offline upper bound for a deterministic veto before model inference.

Reference labels are used ONLY by this experimental eligibility check. They must
never become runtime features or selective per-row bypasses. A perfect model
cannot recover a supported relation that the host always vetoes. This bound is
not measured model accuracy and cannot qualify an agent or a source gate.
"""
import argparse
import json
from pathlib import Path

from commentscope.factory import condition_guard as guard, membership_policy
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write


def ceiling(plan):
    if plan.get('membership_guard') != guard.VERSION:
        raise ValueError('This audit only covers the versioned condition veto')
    ids = plan['evaluation_ids']
    if len(ids) != 100 or len(set(ids)) != 100:
        raise ValueError('Fixed100 evaluation required')
    source = Path(plan['reference_source'])
    ref_path = source/'references.json'
    expected = read_json(source/'reference-frozen.json')['sha256']
    if sha(ref_path) != expected or plan['inputs'].get(str(ref_path)) != expected:
        raise ValueError('Frozen references changed or are not bound to plan')
    refs = read_json(ref_path)
    if refs.get('runtime_input') is not False or set(refs['labels']) != set(ids):
        raise ValueError('Exactly100 offline references required')
    membership_policy.from_rows(plan['rows'])
    rows = {r['id']: r for r in plan['rows']}
    if len(rows) != len(plan['rows']) or not set(ids) <= rows.keys():
        raise ValueError('Unique bound source rows required')
    positives = [i for i in ids if refs['labels'][i] == 'supported']
    if not positives:
        raise ValueError('No normal-support references')
    vetoes = {i: guard.check(rows[i]['text'], rows[i]['claim']['text'])['veto'] for i in ids}
    vetoed = [i for i in positives if vetoes[i]]
    upper = (len(positives)-len(vetoed))/len(positives)
    return {'artifact_kind': 'deterministic-veto-retention-ceiling-0.1',
            'guard': guard.VERSION, 'reference_sha256': expected,
            'evaluation_size': len(ids), 'reference_positives': len(positives),
            'positive_veto_ids': vetoed, 'all_evaluation_veto_ids': [i for i in ids if vetoes[i]],
            'positive_retention_upper': upper, 'minimum_positive_retention': .8,
            'cannot_pass': upper < .8, 'quality_gate_passed': False,
            'independent_gold': False, 'runtime_input_labels': False, 'new_model_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path); p.add_argument('--output', type=Path)
    a = p.parse_args(); plan = read_json(a.directory/'plan.json')
    code = 'src/commentscope/factory/condition_guard.py'
    if plan['code_sha256'].get(code) != sha(code):
        raise ValueError('Guard implementation changed since plan freeze')
    result = {**ceiling(plan), 'plan_sha256': sha(a.directory/'plan.json'), 'guard_sha256': sha(code)}
    if a.output: write(a.output, result)
    print(json.dumps(result, indent=2))
