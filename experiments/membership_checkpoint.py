"""Read-only source-gate checkpoint; missing work is never a true negative.

Keeps the preregistered denominator and computes an optimistic impossibility
bound. Does not stop a process, promote agents, or consume model inference.
"""
import argparse
import json
from pathlib import Path
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.scoped_discovery import verdict
from commentscope.storage import write_json_exclusive as write


def checkpoint(directory):
    plan = read_json(directory/'plan.json')
    source = Path(plan['reference_source'])
    if sha(source/'references.json') != read_json(source/'reference-frozen.json')['sha256']:
        raise ValueError('Reference changed')
    refs = read_json(source/'references.json')
    ids = plan['evaluation_ids']
    if len(ids) != 100 or len(set(ids)) != 100 or set(refs['labels']) != set(ids) or refs['runtime_input'] is not False:
        raise ValueError('Exactly the fixed 100 offline references are required')
    if read_json(directory/'started.json')['plan_sha256'] != sha(directory/'plan.json'):
        raise ValueError('Started plan changed')
    rows = {r['id']:r for r in plan['rows']}
    if len(rows) != len(plan['rows']) or not set(ids) <= rows.keys():
        raise ValueError('Invalid row identities')
    actual = {}
    for rid, row in rows.items():
        if row['request_sha256'] != digest(row['request']):
            raise ValueError('Frozen request changed')
        path = directory/(rid+'.json')
        if not path.exists():
            continue
        record = read_json(path)
        if record['request_sha256'] != row['request_sha256']:
            raise ValueError('Recorded request changed')
        result = record['result']
        if result['raw'] is not None:
            try:
                parsed = json.loads(result['raw'])
            except (ValueError, TypeError):
                if not result['errors'] or result['output'] is not None:
                    raise ValueError('Invalid raw response marked usable') from None
            else:
                if parsed != result['output']:
                    raise ValueError('Parsed response changed')
        elif not result['errors']:
            raise ValueError('Missing raw response marked usable')
        actual[rid] = verdict(result)
    positives = {i for i in ids if refs['labels'][i] == 'supported'}
    accepted = {i for i in ids if actual.get(i) == 'supported'}
    true = len(accepted & positives)
    false = sorted(accepted - positives)
    remaining = [i for i in ids if i not in actual]
    missed = sorted(i for i in positives if i in actual and actual[i] != 'supported')
    best_true = len(positives) - len(missed)
    precision_upper = best_true/(best_true+len(false)) if best_true+len(false) else 0
    retention_upper = best_true/len(positives) if positives else 0
    complete = not remaining
    precision = true/len(accepted) if accepted else 0
    retention = true/len(positives) if positives else 0
    return {'planned_evaluation':len(ids), 'observed_evaluation':len(ids)-len(remaining),
            'observed_total':len(actual), 'planned_total':len(rows),
            'reference_positive':len(positives), 'accepted_observed':len(accepted),
            'true_accepted_observed':true, 'false_accepted_observed':false,
            'missed_positive_observed':missed, 'unexecuted_evaluation':remaining,
            'errors_observed':[i for i in ids if actual.get(i)=='error'],
            'precision_observed':precision, 'positive_retention_fixed_denominator':retention,
            'precision_best_possible':precision_upper, 'retention_best_possible':retention_upper,
            'cannot_pass':precision_upper<.95 or retention_upper<.8,
            'evaluation_complete':complete, 'all_relations_complete':len(actual)==len(rows),
            'development_gate_passed':complete and precision>=.95 and retention>=.8,
            'quality_gate_passed':False, 'independent_gold':False, 'new_model_calls':0}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path); p.add_argument('--output',type=Path)
    a=p.parse_args(); value=checkpoint(a.directory)
    if a.output: write(a.output,value)
    print(json.dumps(value,indent=2))
