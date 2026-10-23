"""Offline review packets for ALL minimal-Factory outputs; no inference or repair.

Blank verdicts are not success. Reviewer judgments are assistant evaluation,
not independent human gold. This module is never imported by the runtime.
"""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path

from commentscope.factory import minimal_membership as mm, comment_utilization as utilization
from commentscope.factory import acceptance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.position_frames import source_packet
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write
from experiments.framed_agent_probe import QUESTIONS
from experiments.sequential_mvp_readiness import replay_benchmark

VERSION = 'minimal-factory-offline-review-20261016-v2'
R5_VERSION = 'minimal-factory-offline-review-20261017-v3'
EXECUTORS = ('minimal-factory-executor-20261016-v1', 'minimal-factory-executor-20261017-v2',
             'minimal-factory-executor-20261017-v3','minimal-factory-executor-20261017-v4',
             'minimal-factory-executor-20261017-v5','minimal-factory-executor-20261017-v6',
             'minimal-factory-executor-20261017-v7','minimal-factory-executor-20261018-v8','minimal-factory-executor-20261018-v9')


def private(path):
    if not Path(path).resolve().is_relative_to(Path('runs').resolve()): raise ValueError('Private review path required')


def load_run(run):
    private(run); plan = read_json(run/'plan.json'); completion = read_json(run/'completed.json')
    if (plan['artifact_kind'] not in EXECUTORS
            or completion['execution_complete'] is not True or completion['plan_sha256'] != sha(run/'plan.json')
            or plan['reference_runtime_input'] is not False or plan['cross_run_response_reuse'] is not False
            or completion['output_sha256'] != sha(run/'artifacts/output.json')
            or completion['runtime_sha256'] != sha(run/'artifacts/runtime.json')):
        raise ValueError('Completed and immutable run required')
    profile = acceptance.from_plan(plan)
    if (plan['artifact_kind'] in EXECUTORS[2:]) != (profile is not None):
        raise ValueError('Cannot retroactively change a historical run acceptance contract')
    # Code may have since advanced. The run hashes identify its implementation;
    # review binds to immutable artifacts, never silently re-executes old logic.
    snapshot = load_snapshot(Path(plan['snapshot']))
    if snapshot.sha256 != plan['snapshot_sha256']: raise ValueError('Run original snapshot changed')
    output = read_json(run/'artifacts/output.json'); runtime = read_json(run/'artifacts/runtime.json')
    mapped = mm.assemble_map(snapshot.snapshot, output['candidates'], output['memberships'])
    if mapped != output['agent_inputs']['map']: raise ValueError('Support map changed')
    return plan, completion, snapshot.snapshot, output, runtime


def prepare(directory, run):
    private(directory)
    if directory.exists(): raise ValueError('Never overwrite review evidence')
    plan, completion, snapshot, output, runtime = load_run(run)
    profile = acceptance.from_plan(plan)
    version = R5_VERSION if profile is not None else VERSION
    opinion = output['agent_inputs']['map']['opinion_map']; lookup = {p['id']: p for p in opinion['perspectives']}
    original = {sid: source_packet(snapshot, sid) for sid in plan['scope_ids']}
    checks = output['agent_inputs']['bundle']['checks']
    fact_report = replay_benchmark(Path('runs/fact-nli-40-20261013'), plan, checks)
    rows = []
    def task(kind, key, data):
        rows.append({'id': kind+':'+digest(key), 'kind': kind, 'key': key, 'data': data})
    for sid in plan['scope_ids']:
        record = next((r for r in output['extractions'] if r['source']['id'] == sid), None)
        data = {'original': original[sid], 'extraction': record}
        if profile is not None:
            data['retained_memberships'] = [p for p in opinion['perspectives'] if sid in p['supported_canonical_ids']]
        task('source', sid, data)
    for p in opinion['perspectives']:
        task('candidate', p['id'], p)
    for r in opinion['assessments']:
        if r['relation'] == 'supported':
            sid, cid = r['canonical_source_id'], r['perspective_id']
            task('support', [cid, sid], {'original': original[sid], 'claim': lookup[cid]['claim'], 'assessment': r})
    for eq in output['equivalences']:
        for r in eq['relations']:
            task('equivalence', [r['a'], r['b']], {'a': next(c for c in read_json(run/'artifacts/initial-candidates.json') if c['id'] == r['a']),
                 'b': next(c for c in read_json(run/'artifacts/initial-candidates.json') if c['id'] == r['b']), 'decision': r})
    for record in output['arguments']:
        task('argument', record['source']['id'], record)
    for profile in output['agent_inputs']['compiled']['profiles']:
        task('agent', profile['candidate_id'], profile)
    for row in runtime['turns']:
        task('runtime', [row['candidate_id'], row['question_id']], row)
    packet = {'artifact_kind': version+'-packet', 'run': str(run), 'plan_sha256': sha(run/'plan.json'),
              'output_sha256': completion['output_sha256'], 'runtime_sha256': completion['runtime_sha256'],
              'tasks': rows, 'fact_benchmark': fact_report, 'runtime_input': False, 'independent_gold': False,
              'rubric': 'Every source/candidate/support/equivalence/argument/agent/turn. Review stance, author, conditions, reason ownership, facts and citations. '
                        'source pass requires at least one substantive faithfully retained proposition; report other omissions separately. '
                        'All counted support must pass; a correct edge never cancels an incorrect edge. '
                        'candidate pass means coherent full stance; equivalence pass means the recorded relation preserves full essential scope. '
                        'Agent pass includes core and all major arguments and external fact scope. Runtime pass requires question relevance, own citations, appropriate abstention and history isolation.'}
    write(directory/'packet.json', packet)
    write(directory/'template.json', {'artifact_kind': version+'-review', 'packet_sha256': digest(packet),
          'evaluator': 'assistant_offline_not_independent_human_gold', 'rows': [
              {'id': r['id'], 'verdict': None, 'reason': '', 'omissions': [], 'label': None} for r in rows]})
    return {'tasks': dict(Counter(r['kind'] for r in rows)), 'fact_benchmark_passed': fact_report['passed']}


def evaluate(directory, review_path, output_path):
    private(directory); private(review_path); private(output_path)
    packet = read_json(directory/'packet.json'); review = read_json(review_path)
    version = packet.get('artifact_kind', '').removesuffix('-packet')
    if (version not in (VERSION, R5_VERSION) or review.get('artifact_kind') != version+'-review' or review.get('packet_sha256') != digest(packet)
            or not isinstance(review.get('evaluator'), str) or not review['evaluator'].strip()):
        raise ValueError('Review must bind to the exact full packet')
    plan, completion, snapshot, output, runtime = load_run(Path(packet['run']))
    profile = acceptance.from_plan(plan)
    if (version == R5_VERSION) != (profile is not None):
        raise ValueError('Review and run acceptance contracts differ')
    if profile is not None and packet['plan_sha256'] != sha(Path(packet['run'])/'plan.json'):
        raise ValueError('Review plan changed')
    if packet['output_sha256'] != completion['output_sha256'] or packet['runtime_sha256'] != completion['runtime_sha256']:
        raise ValueError('Packet output changed')
    tasks = {r['id']: r for r in packet['tasks']}; reviewed = {}
    for row in review['rows']:
        if (set(row) != {'id','verdict','reason','omissions','label'} or row['id'] not in tasks or row['id'] in reviewed
                or row['verdict'] not in ('pass','fail','uncertain') or not isinstance(row['reason'], str) or not row['reason'].strip()
                or not isinstance(row['omissions'], list) or any(not isinstance(x, str) for x in row['omissions'])
                or row['label'] is not None and not isinstance(row['label'], str)):
            raise ValueError('Complete, unique, explained review verdicts required')
        reviewed[row['id']] = row
    counts = {}
    for kind in {r['kind'] for r in tasks.values()}:
        counts[kind] = dict(Counter(reviewed.get(r['id'], {}).get('verdict', 'unreviewed') for r in tasks.values() if r['kind'] == kind))
    def passed(kind):
        return all(reviewed.get(t['id'], {}).get('verdict') == 'pass' for t in tasks.values() if t['kind'] == kind)
    def rows(kind): return [t for t in tasks.values() if t['kind'] == kind]
    gates = {'execution_no_binding_failures': completion['binding_errors'] == 0,
             'all_counted_support_valid': bool(rows('support')) and passed('support'),
             'all_candidates_reviewed_coherent': passed('candidate'),
             'all_merging_equivalences_valid': all(reviewed.get(t['id'], {}).get('verdict') == 'pass'
                 for t in rows('equivalence') if t['data']['decision']['relation'] == 'equivalent'),
             'all_equivalence_decisions_reviewed': all(t['id'] in reviewed for t in rows('equivalence')),
             'all_extractions_reviewed': all(t['id'] in reviewed for t in rows('source')),
             'all_arguments_reviewed': all(t['id'] in reviewed for t in rows('argument')),
             'all_exposed_agents_valid': passed('agent'), 'all_runtime_turns_valid': passed('runtime'),
             'fixed_fact_benchmark': packet['fact_benchmark']['passed']}
    if profile is not None:
        # Incorrect proposals that received no votes remain visible for review,
        # but are not counted supports or exposed Agent content. Never repair an
        # admitted error by deleting its edge in this evaluator.
        del gates['all_candidates_reviewed_coherent']
        gates['all_candidates_reviewed'] = all(t['id'] in reviewed for t in rows('candidate'))
        gates['all_counted_candidates_coherent'] = all(reviewed.get(t['id'], {}).get('verdict') == 'pass'
            for t in rows('candidate') if t['data']['supported_canonical_ids'])
    preserved = {t['key'] for t in rows('source') if reviewed.get(t['id'], {}).get('verdict') == 'pass'}
    opinion = output['agent_inputs']['map']['opinion_map']; utilization_report = None
    if plan['gate'] == 'G1':
        if profile is not None: acceptance.check_scope(profile, 'G1', len(plan['scope_ids']), None)
        candidates_by_label = {}
        for task in rows('candidate'):
            label = reviewed.get(task['id'], {}).get('label')
            candidates_by_label.setdefault(label, []).append(task['data'])
        for label, expected in [('mandatory', {'A','B','C','I','J'}), ('voluntary', {'E','G','L'})]:
            matches = candidates_by_label.get(label, [])
            gates[label+'_support'] = any(set(p['supported_canonical_ids']) == expected for p in matches)
        gates['conditional_separate_and_F_H_preserved'] = {'D','K','F','H'} <= preserved
        agent_labels = {reviewed[t['id']]['label'] for t in rows('agent') if t['id'] in reviewed}
        gates['two_distinct_agents'] = {'mandatory','voluntary'} <= agent_labels
        gates['all_agent_fixed_questions'] = len(rows('runtime')) == 3*len(rows('agent')) and len(rows('agent')) >= 2
    else:
        samples = read_json(Path('runs/design-freeze-20261016/samples.json'))
        reference = read_json(samples['meaning_reference'])
        if sha(samples['meaning_reference']) != samples['meaning_reference_sha256']: raise ValueError('Fixed meaning reference changed')
        meaningful = {r['source_id'] for r in reference['rows'] if r['eligibility'] == 'meaningful'}
        if len(meaningful) != 755: raise ValueError('Meaning denominator changed')
        scope = set(plan['scope_ids']) & meaningful
        acceptance.check_scope(profile, plan['gate'], len(plan['scope_ids']), len(scope))
        numerator, denominator = acceptance.ratio(profile)
        gates[f'candidate_preservation_at_least_{numerator * 100 // denominator}_percent'] = bool(scope) and len(preserved & scope)*denominator >= len(scope)*numerator
        if plan['gate'] == 'G4':
            lookup = {p['id']: p for p in opinion['perspectives']}
            originals = utilization._canonical(snapshot)
            descriptions = [{k:p[k] for k in ('id','claim','upstream_agent_state')} for p in opinion['perspectives']]
            assessments = [{'perspective_id': r['perspective_id'], 'source_id': r['canonical_source_id'],
                            'claim_sha256': digest(lookup[r['perspective_id']]['claim']),
                            'source_sha256': digest(originals[r['canonical_source_id']]), 'relation': r['relation'], 'evidence_ref': ref}
                           for r in opinion['assessments'] for ref in r['evidence_refs']]
            offline = {'map_sha256': digest(opinion), 'evaluator': review['evaluator'], 'clusters': [], 'supports': []}
            for t in rows('candidate'):
                r = reviewed.get(t['id'])
                if r: offline['clusters'].append({'perspective_id': t['key'], 'claim_sha256': digest(t['data']['claim']),
                    'verdict': {'pass':'coherent','fail':'invalid','uncertain':'uncertain'}[r['verdict']], 'reason': r['reason']})
            for t in rows('support'):
                r = reviewed.get(t['id'])
                if r:
                    cid, sid = t['key']
                    offline['supports'].append({'perspective_id': cid, 'source_id': sid,
                        'claim_sha256': digest(lookup[cid]['claim']), 'source_sha256': digest(originals[sid]),
                        'verdict': {'pass':'supported','fail':'not_supported','uncertain':'uncertain'}[r['verdict']], 'reason': r['reason']})
            utilization_report = utilization.evaluate(snapshot, reference, descriptions, assessments, offline,
                expected_reference_sha256=digest(reference), acceptance_profile=profile,
                expected_acceptance_sha256=digest(profile) if profile is not None else None)
            minimum = acceptance.minimum(profile)
            gates[f'correct_utilization_{minimum}_of_755'] = utilization_report['coverage_target_met'] and len(utilization_report['utilized_source_ids']) >= minimum
            gates['all_counted_support_valid'] = utilization_report['support_validity_passed']
            distinct = {reviewed[t['id']]['label'] for t in rows('agent') if t['id'] in reviewed and reviewed[t['id']]['label']}
            gates['two_distinct_agents_valid_support'] = len(distinct) >= 2 and all(t['data']['model_core_support_count'] >= 3 for t in rows('agent'))
            handled = {r['source']['id'] for r in output['extractions']} | set(output['unextracted_source_ids'])
            gates['full_fresh_processing'] = completion['fresh_run'] and len(plan['scope_ids']) == 999 and handled == set(plan['scope_ids'])
            gates['all_agent_fixed_questions'] = len(rows('runtime')) == 3*len(rows('agent'))
    result = {'artifact_kind': version+'-result', 'gate': plan['gate'], 'gate_passed': all(gates.values()),
              'requirements': gates, 'review_counts': counts, 'preserved_source_ids': sorted(preserved),
              'review_sha256': sha(review_path), 'packet_sha256': digest(packet),
              'utilization': utilization_report, 'runtime_input': False, 'independent_gold': False,
              'omissions': {r['id']: r['omissions'] for r in reviewed.values() if r['omissions']},
              'factory_complete': plan['gate'] == 'G4' and all(gates.values())}
    if profile is not None:
        result.update(goal_revision=profile['goal_revision'], acceptance_profile_sha256=digest(profile))
    write(output_path, result); return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); s = p.add_subparsers(dest='action', required=True)
    a=s.add_parser('prepare'); a.add_argument('directory', type=Path); a.add_argument('--run', type=Path, required=True)
    a=s.add_parser('evaluate'); a.add_argument('directory', type=Path); a.add_argument('--review', type=Path, required=True); a.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    if args.action=='prepare': print(prepare(args.directory,args.run))
    else: print(evaluate(args.directory,args.review,args.output))
