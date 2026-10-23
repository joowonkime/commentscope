"""Read-only review of ALL generated Agents and their recorded runtime turns.

This is an offline evaluator, never a runtime approval or repair input. Source
support/utilization and the fixed fact benchmark are separate evaluations.
Replay verifies structure and ownership, not semantic truth or model honesty.
"""
import argparse
from collections import Counter
from copy import deepcopy
import math
from pathlib import Path

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.factory import framed_agents
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_corpus_pipeline as pipeline
from experiments import sequential_corpus_review as corpus_review

VERSION = 'sequential-all-agent-offline-review-0.1'
VERDICTS = ('pass', 'fail', 'uncertain')
CHECKS = {
    'perspective_distinctness': 'Are the generated perspectives substantively distinct, rather than duplicate wording or arbitrary splitting?',
    'agent_contract': 'Against every counted original and source argument, preserve the core stance, source-owned reasons and essential restrictions. Inspect omitted entries and dependencies for deleted premises, reason transfer or unsupported factual promotion.',
    'entry': 'Check the full claim against its cited originals, attribution, declared role/type, scope and required premises. Exact citation offsets alone do not prove faithful meaning or a valid reason.',
    'fact': 'Check this exposed factual claim against the full selected external evidence, scope, conflicts and dependency context. NLI approval alone is not semantic verification.',
    'runtime_turn': 'Does the recorded response appropriately answer this fixed question or abstain, using only this Agent evidence without losing essential restrictions or transferring another source reason?',
}


def replay_runtime(bundle, runtime):
    """Reconstruct sessions from saved raw selections; no provider/model calls."""
    profiles = compile_inputs(bundle)['profiles']
    ids = [p['candidate_id'] for p in profiles]
    expected = [(cid, q) for cid in ids for q in pipeline.QUESTIONS]
    if (runtime['all_compiled_candidate_ids'] != ids or len(runtime['turns']) != len(expected)
            or runtime['quality_gate_passed'] is not False or runtime['requires_semantic_review'] is not True):
        raise ValueError('Runtime population or review state changed')
    sessions = {cid: GroundedSession(bundle, cid, provider=None) for cid in ids}
    for row, (cid, question) in zip(runtime['turns'], expected, strict=True):
        if (set(row) != {'candidate_id', 'question_id', 'turn', 'other_histories_unchanged'}
                or row['candidate_id'] != cid or row['question_id'] != question['id']):
            raise ValueError('Runtime question order or Agent identity changed')
        stored = row['turn']; raw = stored['result']['raw']
        seconds = stored['result']['seconds']
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid recorded runtime timing')

        def recorded_provider(system, data, schema, *, max_tokens):
            if raw is None: raise ValueError('Recorded failed response')
            return {'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}]}

        session = sessions[cid]; session.provider = recorded_provider
        before = {other: digest(s.history) for other, s in sessions.items() if other != cid}
        replayed = session.ask(question['text'])
        # Replaying selection/rendering does not reproduce wall-clock duration.
        replayed['result']['seconds'] = seconds
        isolated = all(digest(sessions[other].history) == h for other, h in before.items())
        if replayed != stored or row['other_histories_unchanged'] is not isolated:
            raise ValueError('Runtime selection, citation, request/history or isolation replay differs')
    return {'replayed_turns': len(expected),
            'all_histories_isolated': all(r['other_histories_unchanged'] for r in runtime['turns']),
            'error_turns': sum(bool(r['turn']['result']['errors']) or r['turn']['status'] == 'error'
                               for r in runtime['turns']),
            'semantic_approval': False}


def packet(plan, opinion, output, analyses, runtime, mechanical):
    inputs = output['agent_inputs']; bundle = inputs['bundle']; compiled = inputs['compiled']
    candidates = {c['id']: c for c in bundle['candidates']}
    perspectives = {p['id']: p for p in opinion['opinion_map']['perspectives']}
    profiles = compiled['profiles']; tasks = []

    def task(kind, **subject):
        body = {'kind': kind, 'subject': subject, 'checks': CHECKS[kind]}
        tasks.append({'id': 'T' + digest([kind, subject]), **body, 'task_sha256': digest(body)})

    task('perspective_distinctness', candidate_ids=[p['candidate_id'] for p in profiles])
    agent_records = []
    for profile in profiles:
        cid = profile['candidate_id']; candidate = candidates[cid]
        task('agent_contract', candidate_id=cid)
        agent_records.append({'profile': deepcopy(profile), 'candidate': deepcopy(candidate),
            'common_claim': deepcopy(perspectives[cid]['claim']),
            'counted_support_source_ids': perspectives[cid]['supported_canonical_ids'],
            'source_arguments': [{k: deepcopy(a[k]) for k in ('source_id', 'state', 'reason', 'typed') if k in a}
                                 for a in analyses if a['candidate_id'] == cid]})
        for entry in profile['prompt_entries']:
            task('entry', candidate_id=cid, claim_id=entry['claim_id'])
            if entry['kind'] == 'fact': task('fact', candidate_id=cid, claim_id=entry['claim_id'])
    for row in runtime['turns']:
        task('runtime_turn', candidate_id=row['candidate_id'], question_id=row['question_id'])
    return {'artifact_kind': VERSION + '-packet', 'execution_version': plan['artifact_kind'],
        'canonical_population': plan['canonical_population'], 'reference_sha256': plan['reference']['sha256'],
        'agents': agent_records, 'sources': opinion['sources'], 'claims': deepcopy(bundle['claims']),
        'documents': deepcopy(bundle['documents']), 'fact_checks': deepcopy(bundle['checks']),
        'runtime': deepcopy(runtime), 'mechanical_runtime_replay': mechanical,
        'argument_deferrals': deepcopy(inputs['argument_deferrals']),
        'fact_deferrals': deepcopy(compiled['deferred']), 'tasks': tasks,
        'review_template': [{'task_id': t['id'], 'task_sha256': t['task_sha256'], 'verdict': None, 'reason': ''}
                            for t in tasks],
        'runtime_input': False, 'independent_gold': False, 'quality_gate_passed': False}


def load_run(directory):
    snapshot, _, opinion, bindings = corpus_review.load_run(directory)
    plan = read_json(directory/'plan.json')
    paths = [directory/'completed.json', *[directory/'artifacts'/f'{n}.json'
             for n in ('output', 'agent-inputs', 'analyses', 'runtime')]]
    if any(not p.is_file() for p in paths):
        raise ValueError('Completed Agent/output/runtime artifacts required; prefixes are not sufficient')
    report, output, saved_inputs, analyses, runtime = [read_json(p) for p in paths]
    inputs = output['agent_inputs']
    if (report['artifact_kind'] != pipeline.VERSION or report['execution_complete'] is not True
            or report['plan_sha256'] != sha(directory/'plan.json')
            or report['quality_gate_passed'] is not False or report['semantic_review_required'] is not True
            or report['output_sha256'] != digest(output) or report['runtime_sha256'] != digest(runtime)
            or report['bundle_sha256'] != digest(inputs['bundle'])
            or report['compiled_sha256'] != digest(inputs['compiled']) or saved_inputs != inputs
            or report['compiled_profiles'] != len(inputs['compiled']['profiles'])
            or report['runtime_turns'] != len(runtime['turns'])
            or report['canonical_population'] != plan['canonical_population']):
        raise ValueError('Completed Agent artifact bindings changed')
    records, candidates, memberships = [read_json(directory/'artifacts'/f'{n}.json')
                                      for n in ('frames', 'candidates', 'memberships')]
    if output['candidates'] != candidates or output['memberships'] != memberships:
        raise ValueError('Agent output is not the complete membership output')
    rebuilt = framed_agents.bundle(snapshot, records, candidates, memberships, analyses,
        model=plan['classifier'], documents=plan['documents'], checks=inputs['bundle']['checks'])
    if rebuilt != inputs:
        raise ValueError('Agent bundle/compilation differs from original-source reconstruction')
    mechanical = replay_runtime(inputs['bundle'], runtime)
    bindings.update({str(p): sha(p) for p in paths})
    return packet(plan, opinion, output, analyses, runtime, mechanical), bindings


def code_hashes():
    return {**corpus_review.review_code(), str(Path(__file__)): sha(__file__)}


def prepare(directory, run_directory):
    pipeline.private(directory)
    if directory.exists(): raise ValueError('Never overwrite an Agent review packet')
    prepared, bindings = load_run(run_directory)
    write(directory/'packet.json', prepared)
    write(directory/'manifest.json', {'artifact_kind': VERSION, 'run_directory': str(run_directory),
        'inputs': bindings, 'review_code_sha256': code_hashes(), 'packet_sha256': digest(prepared)})
    write(directory/'part-template.json', {'artifact_kind': VERSION + '-part',
        'packet_sha256': digest(prepared), 'evaluator': 'assistant_offline_not_independent_human_gold',
        'rows': prepared['review_template']})
    return {'generated_agents': len(prepared['agents']), 'review_tasks': len(prepared['tasks']),
            'semantic_verdicts': 0, 'new_model_calls': 0}


def evaluate(directory, part_paths, output):
    pipeline.private(directory); pipeline.private(output)
    manifest = read_json(directory/'manifest.json')
    if (manifest['artifact_kind'] != VERSION or manifest['review_code_sha256'] != code_hashes()
            or any(sha(p) != h for p, h in manifest['inputs'].items())):
        raise ValueError('Frozen Agent review inputs/code changed')
    prepared, _ = load_run(Path(manifest['run_directory']))
    if prepared != read_json(directory/'packet.json') or digest(prepared) != manifest['packet_sha256']:
        raise ValueError('Agent review packet changed')
    tasks = {t['id']: t for t in prepared['tasks']}; reviewed = {}; evaluator = None
    for path in part_paths:
        part = read_json(path)
        if (set(part) != {'artifact_kind', 'packet_sha256', 'evaluator', 'rows'}
                or part['artifact_kind'] != VERSION + '-part' or part['packet_sha256'] != digest(prepared)
                or not isinstance(part['evaluator'], str) or not part['evaluator'].strip()
                or not isinstance(part['rows'], list)):
            raise ValueError('Invalid Agent review part')
        if evaluator is not None and evaluator != part['evaluator']:
            raise ValueError('Do not combine different evaluator protocols')
        evaluator = part['evaluator']
        for row in part['rows']:
            if (not isinstance(row, dict) or set(row) != {'task_id', 'task_sha256', 'verdict', 'reason'}
                    or not isinstance(row['task_id'], str) or row['task_id'] not in tasks
                    or row['task_id'] in reviewed or row['task_sha256'] != tasks[row['task_id']]['task_sha256']
                    or row['verdict'] not in VERDICTS or not isinstance(row['reason'], str) or not row['reason'].strip()):
                raise ValueError('Invalid, duplicate, unknown or changed Agent review task')
            reviewed[row['task_id']] = row['verdict']
    counts = Counter(reviewed.get(tid, 'unreviewed') for tid in tasks)
    mechanical = prepared['mechanical_runtime_replay']
    semantic_pass = bool(tasks) and counts['pass'] == len(tasks)
    agent_count = len(prepared['agents'])
    result = {'artifact_kind': VERSION + '-evaluation', 'packet_sha256': digest(prepared),
        'generated_agents': agent_count, 'total_review_tasks': len(tasks),
        'review_counts': {v: counts[v] for v in (*VERDICTS, 'unreviewed')},
        'unreviewed_task_ids': sorted(set(tasks) - set(reviewed)),
        'failed_task_ids': sorted(k for k, v in reviewed.items() if v == 'fail'),
        'uncertain_task_ids': sorted(k for k, v in reviewed.items() if v == 'uncertain'),
        'all_tasks_reviewed_pass': semantic_pass,
        'agent_content_runtime_review_passed': (agent_count >= 2 and semantic_pass
            and mechanical['all_histories_isolated'] and mechanical['error_turns'] == 0),
        'mechanical_runtime_replay': mechanical, 'evaluator': evaluator,
        'review_files_sha256': {str(p): sha(p) for p in part_paths},
        'source_support_validity': 'not_evaluated_here', 'correct_comment_utilization': None,
        'fixed_fact_benchmark': 'not_evaluated_here', 'mvp_acceptance': 'not_evaluated',
        'runtime_input': False, 'independent_gold': False}
    write(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--run', type=Path, required=True)
    p = sub.add_parser('evaluate'); p.add_argument('directory', type=Path)
    p.add_argument('--parts', type=Path, nargs='*', default=[]); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare': print(prepare(args.directory, args.run))
    else:
        result = evaluate(args.directory, args.parts, args.output)
        print({k: result[k] for k in ('generated_agents', 'review_counts', 'agent_content_runtime_review_passed', 'mvp_acceptance')})
