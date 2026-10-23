"""One frozen local model probe of source frames, discovery and admission.

Six authored controls, not a real-corpus success claim or independent gold.
Expected labels are used only AFTER all runtime outputs have been collected.
The fixed-target admission diagnostic is separate from automatic discovery.
"""
import argparse
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import time

from commentscope.factory import position_frames as frames, framed_clusters as clusters
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.ingestion import load_snapshot
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'framed-cluster-synthetic-controls-0.2'
FIXTURE = Path('tests/fixtures/synthetic-snapshot.json')
CASES = [
    ('A', 'Safety reviews should be mandatory. I would like this rule to start immediately because accountability matters.', True),
    ('B', 'I support mandatory safety reviews because public safety is important.', True),
    ('C', 'Require safety reviews. The process should also be transparent.', True),
    ('D', 'Safety reviews should be mandatory only if small labs receive fee waivers.', False),
    ('E', 'Safety reviews should remain voluntary because freedom of choice matters.', False),
    ('F', 'Public meeting notices should be accessible to blind residents.', False),
]
TARGET = {'target': 'mandatory safety reviews', 'statement': 'Safety reviews should be mandatory.',
          'entity': 'safety reviews', 'time': '', 'conditions': ''}


class AllocatedRunner(Runner):
    def call(self, stage, req, **kwargs):
        # Frame bindings identify logical requests. The call record/ledger bind
        # the actual allocated payload, including its total generation ceiling.
        allocated = allocate(req, self.plan['deployment']['runtime'])
        return super().call(stage, allocated, **kwargs)


def synthetic_snapshot():
    original = load_snapshot(FIXTURE).snapshot
    return replace(original, snapshot_id=VERSION,
                   usage=replace(original.usage, expires_at='2099-01-01T00:00:00Z'),
                   comments=tuple(replace(original.comments[0], comment_id=sid, text_original=text)
                                  for sid, text, _ in CASES))


def prepare(directory, deployment_plan, cycle, *, deployment_key='extraction'):
    if directory.exists(): raise ValueError('Never overwrite an experiment')
    settings = read_json(cycle)
    if (settings['goal_revision'] != 'factory-goal-20261014-r4'
            or settings['cycle_id'] != 'mvp-factory-20261014'
            or settings['analysis_seconds'] is not None or settings['limit_seconds'] is not None):
        raise ValueError('Current uncapped Factory cycle required')
    source = read_json(deployment_plan)
    if deployment_key not in ('extraction', 'profile'):
        raise ValueError('Use one of the existing fixed local deployments')
    deployment = deepcopy(source['deployments'][deployment_key])
    deployment['runtime']['max_tokens'] = 4096
    deployment['runtime']['max_seconds_per_model'] = None
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    snapshot = synthetic_snapshot()
    plan = {'artifact_kind': VERSION, 'goal_revision': settings['goal_revision'],
            'deployment': deployment, 'deployment_key': deployment_key,
            'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 180,
                       'generation_tokens': 'logical_final_answer_plus_explicit_reasoning_allowance'},
            'inputs': {str(p): sha(p) for p in (FIXTURE, deployment_plan, cycle,
                                              Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'))},
            'code_sha256': code_hashes(), 'snapshot_sha256': digest(snapshot.to_dict()),
            'cases': [{'id': sid, 'expected_fixed_target_support': expected} for sid, _, expected in CASES],
            'fixed_target': TARGET, 'criteria': {'positive_retained': 3, 'false_supports': 0,
                'valid_frame_sources': 6, 'semantic_discovery_requires_output_review': True},
            'hypothesis': 'Separate shared stance from source-owned reasons/additional requests; preserve restrictive conditions.',
            'synthetic': True, 'runtime_reference_labels': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'synthetic_sources': 6, 'analysis_seconds': None, 'new_model_calls': 0}, flush=True)


def run(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json')
    if plan['artifact_kind'] != VERSION or plan['fixed_target'] != TARGET:
        raise ValueError('Unknown/changed control plan')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen file changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Model/runtime changed')
    snapshot = synthetic_snapshot()
    if digest(snapshot.to_dict()) != plan['snapshot_sha256']: raise ValueError('Synthetic input changed')
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
    runner = AllocatedRunner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary()})
    records = []; errors = []; memberships = []; discovered = []; fixed = None
    try:
        with owned_server(plan['deployment'], 'baseline', directory/'model-server'):
            for source in snapshot.comments:
                packet = frames.source_packet(snapshot, source.comment_id)
                result = runner.call('frame-' + source.comment_id, frames.invocation(packet))
                try: record = frames.bind(packet, result)
                except (ValueError, KeyError, TypeError):
                    errors.append({'source_id': source.comment_id, 'stage': 'frame_contract'}); continue
                records.append(record)
                write(directory/'frames'/(source.comment_id + '.json'), record)
            units = clusters.index(records)
            if units:
                result = runner.call('automatic-discovery', clusters.proposal_request(records))
                try: discovered = clusters.proposals(records, result)
                except (ValueError, KeyError, TypeError): errors.append({'stage': 'proposal_contract'})
                write(directory/'automatic-proposals.json', discovered)
                # Fixed target exists only for this admission control, not a
                # manually selected runtime candidate for the UBI corpus.
                fixed = clusters.proposals(records, {'errors': [], 'output': {'candidates': [{
                    'contract': TARGET, 'nominees': list(units)}]}})[0]
                write(directory/'fixed-target.json', fixed)
                for uid, (record, _) in units.items():
                    result = runner.call('membership-' + uid, clusters.membership_request(record, uid, fixed))
                    try: memberships.append(clusters.bind_membership(record, uid, fixed, result))
                    except (ValueError, KeyError, TypeError):
                        errors.append({'position_id': uid, 'stage': 'membership_contract'})
        output = clusters.assemble_map(snapshot, records, [fixed] if fixed else [], memberships)
        write(directory/'memberships.json', memberships); write(directory/'cluster-output.json', output)
        actual = {r['canonical_source_id']: r['relation'] for r in output['opinion_map']['assessments']}
        rows = [{'source_id': r['id'], 'expected_support': r['expected_fixed_target_support'],
                 'actual_relation': actual.get(r['id'], 'unassessed')} for r in plan['cases']]
        retained = sum(r['expected_support'] and r['actual_relation'] == 'supported' for r in rows)
        false = sum(not r['expected_support'] and r['actual_relation'] == 'supported' for r in rows)
        report = {'artifact_kind': VERSION, 'plan_sha256': runner.plan_sha, 'rows': rows,
                  'valid_frame_sources': len(records), 'position_count': len(clusters.index(records)),
                  'automatic_candidate_count': len(discovered), 'positive_retained': retained, 'false_supports': false,
                  'errors': errors, 'fixed_target_controls_passed': len(records) == 6 and retained == 3 and false == 0 and not errors,
                  'automatic_discovery_quality': 'requires_semantic_review',
                  'quality_gate_passed': False, 'independent_gold': False,
                  'fresh_corpus_analysis': False, 'elapsed_seconds': time.monotonic()-started,
                  'budget_after': budget.summary()}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__,
              'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--deployment-plan', type=Path, required=True)
    p.add_argument('--deployment-key', choices=['extraction', 'profile'], default='extraction')
    p.add_argument('--cycle', type=Path, default=Path('runs/mvp-factory-20261014/cycle.json'))
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.deployment_plan, args.cycle, deployment_key=args.deployment_key)
    else: run(args.directory)
