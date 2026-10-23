"""Frozen local integration of cached discovery, new admission, arguments, runtime.

All automatic proposals and all six synthetic sources are evaluated. The fixed
target is a separate diagnostic, never an Agent candidate. No runtime gold input,
manual candidate selection or cached membership/argument answers are used.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from commentscope.factory import position_frames as frames, framed_clusters as clusters
from commentscope.factory import stance_membership as stance, framed_agents as agents
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.framed_cluster_controls import AllocatedRunner, synthetic_snapshot, CASES, TARGET
from experiments.audit_model_compare import owned_server, file_hash
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'framed-agent-synthetic-integration-0.1'
EXPECTED_RELATIONS = dict(A='supported', B='supported', C='supported',
                          D='conditional', E='opposed', F='unrelated')
QUESTIONS = [
    {'id': 'position', 'text': 'What is the central position represented here?'},
    {'id': 'reasons', 'text': 'What reasons and conditions are actually available for this position?'},
    {'id': 'missing', 'text': 'What are the exact annual implementation cost and measured percentage reduction in accidents?'}]


def prepare(directory, source, cycle):
    if directory.exists(): raise ValueError('Never overwrite an experiment')
    original = read_json(source/'plan.json'); completed = read_json(source/'completed.json')
    if (completed['plan_sha256'] != sha(source/'plan.json')
            or original['artifact_kind'] != 'framed-cluster-synthetic-controls-0.2'):
        raise ValueError('Expected completed, bound source frame probe')
    settings = read_json(cycle)
    if (settings['goal_revision'] != 'factory-goal-20261014-r4'
            or settings['cycle_id'] != 'mvp-factory-20261014'
            or settings['analysis_seconds'] is not None or settings['limit_seconds'] is not None):
        raise ValueError('Current uncapped cycle required')
    snapshot = synthetic_snapshot()
    if digest(snapshot.to_dict()) != original['snapshot_sha256']: raise ValueError('Source snapshot changed')
    records = [read_json(source/'frames'/(sid + '.json')) for sid, _, _ in CASES]
    candidates = read_json(source/'automatic-proposals.json')
    clusters.assemble_map(snapshot, records, candidates, [])
    deployment = deepcopy(original['deployment'])
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    paths = [source/n for n in ('plan.json', 'completed.json', 'automatic-proposals.json')]
    paths += [source/'frames'/(sid + '.json') for sid, _, _ in CASES]
    paths += [cycle, Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md')]
    plan = {'artifact_kind': VERSION, 'goal_revision': settings['goal_revision'], 'source': str(source),
            'snapshot_sha256': digest(snapshot.to_dict()), 'inputs': {str(p): sha(p) for p in paths},
            'code_sha256': code_hashes(), 'deployment': deployment,
            'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 180, 'retries': 0},
            'fixed_target': deepcopy(TARGET), 'questions': deepcopy(QUESTIONS),
            'fixed_expected_relations': deepcopy(EXPECTED_RELATIONS),
            'hypothesis': 'Separate original stance admission from source-owned argument preparation; preserve both scope and major premises.',
            'automatic_candidate_ids': [c['id'] for c in candidates],
            'admission_schedule': 'all six sources against every automatic candidate',
            'argument_schedule': 'all counted members of all candidates with at least three supporters',
            'runtime_schedule': 'every compiled profile, three fixed questions, separate history',
            'cached_discovery': True, 'fresh_corpus_analysis': False, 'independent_gold': False,
            'runtime_reference_labels': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'automatic_candidates': len(candidates), 'membership_calls': 6*(1+len(candidates)),
           'new_model_calls': 0, 'analysis_seconds': None}, flush=True)


def runtime_probe(bundle, runner, *, save_turn=None):
    from commentscope.agents.grounded_inputs import compile_inputs
    profiles = compile_inputs(bundle)['profiles']; sessions = {}; rows = []
    def provider(system, data, schema, *, max_tokens):
        result = runner.call('runtime', {'system': system, 'data': data, 'schema': schema, 'max_tokens': max_tokens})
        if result.get('errors'): raise ValueError('Bounded runtime inference failed')
        return {'choices': [{'message': {'content': json.dumps(result['output'])}, 'finish_reason': 'stop'}]}
    for p in profiles:
        cid = p['candidate_id']; sessions[cid] = GroundedSession(bundle, cid, provider=provider)
    for cid, session in sessions.items():
        for question in QUESTIONS:
            before = {other: digest(s.history) for other, s in sessions.items() if other != cid}
            turn = session.ask(question['text'])
            isolated = all(digest(sessions[other].history) == h for other, h in before.items())
            row={'candidate_id': cid, 'question_id': question['id'], 'turn': turn,
                 'other_histories_unchanged': isolated}
            rows.append(row)
            if save_turn is not None:
                save_turn(row)
                if turn['status']=='error':
                    raise ValueError('Actual runtime turn failed; exact turn persisted: '+cid+'/'+question['id'])
    return {'all_compiled_candidate_ids': list(sessions), 'turns': rows,
            'quality_gate_passed': False, 'requires_semantic_review': True}


def run(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json')
    if (plan['artifact_kind'] != VERSION or plan['questions'] != QUESTIONS or plan['fixed_target'] != TARGET
            or plan['fixed_expected_relations'] != EXPECTED_RELATIONS):
        raise ValueError('Unknown or changed plan')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen input/code changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    source = Path(plan['source']); snapshot = synthetic_snapshot()
    if digest(snapshot.to_dict()) != plan['snapshot_sha256']: raise ValueError('Snapshot changed')
    records = [read_json(source/'frames'/(sid + '.json')) for sid, _, _ in CASES]
    candidates = read_json(source/'automatic-proposals.json')
    if [c['id'] for c in candidates] != plan['automatic_candidate_ids']: raise ValueError('Candidate population changed')
    clusters.assemble_map(snapshot, records, candidates, [])
    fixed = clusters.proposals(records, {'output': {'candidates': [{
        'contract': TARGET, 'nominees': list(clusters.index(records))}]}})[0]
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
    runner = AllocatedRunner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary()})
    fixed_rows = []; memberships = []; analyses = []; errors = []
    model = {'name': 'Qwen3-8B-local', 'revision': 'frozen-integration-deployment',
             'weights_sha256': plan['deployment']['models']['baseline']['sha256'],
             'runtime_sha256': digest(plan['deployment']['runtime'])}
    try:
        with owned_server(plan['deployment'], 'baseline', directory/'model-server'):
            def judge(candidate, comment, stage):
                packet = frames.source_packet(snapshot, comment.comment_id)
                result = runner.call(stage, stance.invocation(packet, candidate))
                try: return stance.bind(packet, candidate, result)
                except (ValueError, KeyError, TypeError):
                    errors.append({'candidate_id': candidate['id'], 'source_id': comment.comment_id, 'stage': stage})
                    return None
            for comment in snapshot.comments:
                row = judge(fixed, comment, 'fixed-membership')
                if row is not None: fixed_rows.append(row)
            write(directory/'fixed-memberships.json', fixed_rows)
            print({'stage': 'fixed_membership_finished', 'assessed': len(fixed_rows)}, flush=True)
            for candidate in candidates:
                local = []
                for comment in snapshot.comments:
                    row = judge(candidate, comment, 'automatic-membership')
                    if row is not None: memberships.append(row); local.append(row)
                write(directory/'memberships'/(candidate['id'] + '.json'), local)
                print({'stage': 'candidate_membership_finished', 'candidate_id': candidate['id']}, flush=True)
            mapped = stance.assemble_map(snapshot, records, candidates, memberships)
            write(directory/'memberships.json', memberships); write(directory/'map.json', mapped)
            candidate_lookup = {c['id']: c for c in candidates}
            for perspective in mapped['opinion_map']['perspectives']:
                if not perspective['minimum_support_met']: continue
                cid = perspective['id']
                for sid in perspective['supported_canonical_ids']:
                    analysis = agents.analyse_source(frames.source_packet(snapshot, sid), candidate_lookup[cid], runner)
                    analyses.append(analysis)
                    write(directory/'arguments'/cid/(sid + '.json'), analysis)
            write(directory/'analyses.json', analyses)
            output = agents.bundle(snapshot, records, candidates, memberships, analyses, model=model)
            # No external material is asserted to verify synthetic facts. Any
            # factual claims remain unassessed under the real compiler policy.
            write(directory/'agent-inputs.json', output)
            write(directory/'bundle.json', output['bundle']); write(directory/'compiled.json', output['compiled'])
            runtime = runtime_probe(output['bundle'], runner)
            write(directory/'runtime.json', runtime)
        actual = {r['source_id']: r['relation'] for r in fixed_rows}
        rows = [{'source_id': sid, 'expected': expected, 'actual': actual.get(sid, 'unassessed')}
                for sid, expected in plan['fixed_expected_relations'].items()]
        report = {'artifact_kind': VERSION, 'plan_sha256': runner.plan_sha, 'fixed_rows': rows,
                  'fixed_controls_passed': all(r['actual'] == r['expected'] for r in rows),
                  'automatic_candidate_count': len(candidates), 'automatic_membership_count': len(memberships),
                  'candidate_support_counts': {p['id']: p['counts']['supported'] for p in mapped['opinion_map']['perspectives']},
                  'compiled_profiles': len(output['compiled']['profiles']),
                  'argument_deferrals': output['argument_deferrals'], 'fact_deferrals': output['compiled']['deferred'],
                  'runtime_turns': len(runtime['turns']), 'errors': errors,
                  'quality_gate_passed': False, 'semantic_review_required': True,
                  'cached_discovery': True, 'fresh_corpus_analysis': False, 'independent_gold': False,
                  'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary()}
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
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--cycle', type=Path, default=Path('runs/mvp-factory-20261014/cycle.json'))
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.source, args.cycle)
    else: run(args.directory)
