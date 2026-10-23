"""One frozen condition-veto trial; no new prompts, repairs or labels.

Replay the already completed 8B/off controls without inference, retaining raw
failures. Only their derived binary pass permits the same fixed100 comparison.
This is known-case development, not held-out validation. Failed trials must not
start a new keyword/threshold search. Downstream integration is explicitly closed
until it implements and validates the same host policy.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from commentscope.factory import condition_guard as guard, membership_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.directed_off_deployment import control_rows
from experiments.reasoning_membership_probe import execute
from experiments.policy_retention_ceiling import ceiling
from experiments.scoped_discovery_probe import code_hashes, validate


def completed_records(directory, plan):
    done = read_json(directory/'completed.json')
    if (done['plan_sha256'] != sha(directory/'plan.json')
            or done['report_sha256'] != sha(directory/'report.json')
            or set(done['records']) != {r['id'] for r in plan['rows']}):
        raise ValueError('Control completion changed')
    records = {}
    for row in plan['rows']:
        path = directory/(row['id']+'.json')
        record = read_json(path)
        if (sha(path) != done['records'][row['id']]
                or row['request_sha256'] != digest(row['request'])
                or record['request_sha256'] != row['request_sha256']):
            raise ValueError('Control request or record changed')
        result = record['result']
        if result['errors'] or result['raw'] is None or json.loads(result['raw']) != result['output']:
            raise ValueError('Completed error-free control records required')
        records[row['id']] = {'path': str(path), 'sha256': sha(path)}
    return records


def prepare_controls(directory, source):
    if directory.exists():
        raise ValueError('Never overwrite an attempt')
    original = read_json(source/'plan.json')
    policy = membership_policy.from_rows(original['rows'])
    if (not original.get('plumbing_only') or original['rows'] != control_rows(policy)
            or original.get('membership_guard') is not None
            or original['runtime']['reasoning'] != 'off'
            or original['models']['baseline']['name'] != 'Qwen3-8B-Q4_K_M'):
        raise ValueError('Unmodified completed 8B/off controls required')
    records = completed_records(source, original)
    plan = deepcopy(original)
    plan.update(artifact_kind='guarded-membership-development-0.1', membership_guard=guard.VERSION,
                code_sha256=code_hashes(), reused_records=records,
                comparison='Replay existing 8B/off outputs with a lexical condition veto. New model calls0; original failure preserved.')
    plan['inputs'] = {**original['inputs'],
                      **{str(source/n): sha(source/n) for n in ('plan.json', 'completed.json', 'report.json')},
                      **{r['path']: r['sha256'] for r in records.values()}}
    validate(plan)
    write(directory/'plan.json', plan)


def verify_controls(directory, plan):
    prior = read_json(directory/'plan.json')
    validate(prior)
    if (prior.get('membership_guard') != guard.VERSION or not prior.get('plumbing_only')
            or prior['rows'] != control_rows(membership_policy.from_rows(plan['rows']))
            or any(prior[k] != plan[k] for k in ('models', 'server', 'runtime', 'membership_guard'))):
        raise ValueError('Guarded controls do not match this deployment')
    completed_records(directory, prior)
    report = read_json(directory/'report.json')
    if report['precision'] != 1 or report['positive_retention'] != 1 or report['errors']:
        raise ValueError('Guarded controls failed')
    for row in prior['rows']:
        record = read_json(directory/(row['id']+'.json'))
        actual = guard.effective(record['result'], row['text'], row['claim'], guard.VERSION)
        if actual != report['actual'][row['id']] or (actual == 'supported') != (row['expected'] == 'supported'):
            raise ValueError('Guarded report does not replay')


def prepare_trial(directory, source, controls):
    if directory.exists():
        raise ValueError('Never overwrite an attempt')
    parent = read_json(source/'plan.json')
    for p, h in parent['inputs'].items():
        if sha(p) != h:
            raise ValueError('Frozen source input changed')
    if (parent.get('directionality_variant') != 'asymmetric-entailment-clarification-0.1'
            or len(parent['evaluation_ids']) != 100 or len(set(parent['evaluation_ids'])) != 100):
        raise ValueError('Same directed fixed100 required')
    control = read_json(controls/'plan.json')
    policy = membership_policy.from_rows(parent['rows'])
    policy['max_tokens'] = 180
    plan = deepcopy(parent)
    for key in ('reused_records', 'continuation_of'):
        plan.pop(key, None)
    plan.update(artifact_kind='guarded-membership-development-0.1', membership_guard=guard.VERSION,
                rows=membership_policy.bind_rows(policy, parent['rows']),
                runtime=deepcopy(control['runtime']), budget=deepcopy(control['budget']),
                code_sha256=code_hashes(), plumbing_only=False, stop_on_impossible=True,
                comparison='One lexical-veto8B/off fixed100 trial; unchanged sources/targets/references/system/schema. No further tuning on failure.')
    plan['inputs'] = {**parent['inputs'], str(source/'plan.json'): sha(source/'plan.json'),
                      **{str(controls/n): sha(controls/n) for n in ('plan.json', 'completed.json', 'report.json')}}
    if ceiling(plan)['cannot_pass']:
        raise ValueError('Deterministic veto cannot retain80% even with a perfect model; no trial')
    verify_controls(controls, plan)
    validate(plan)
    write(directory/'plan.json', plan)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare-controls', 'prepare-trial', 'run'])
    p.add_argument('directory', type=Path)
    p.add_argument('--source', type=Path)
    p.add_argument('--controls', type=Path)
    a = p.parse_args()
    if a.phase == 'prepare-controls':
        if a.source is None: p.error('prepare-controls requires --source')
        prepare_controls(a.directory, a.source)
    elif a.phase == 'prepare-trial':
        if a.source is None or a.controls is None: p.error('prepare-trial requires --source and --controls')
        prepare_trial(a.directory, a.source, a.controls)
    else:
        execute(a.directory)
