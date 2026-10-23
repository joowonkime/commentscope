"""Compose the existing whole-corpus and ALL-Agent offline reviews.

No inference, model-weight reads, automatic semantic judgments or runtime
repairs. Readiness describes the supplied assistant-reviewed fixed execution;
it is not independent gold, a universal accuracy claim, or paper validation.
"""
import argparse
from collections import Counter
import math
from pathlib import Path

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.nli_fact_records import validate_result
from commentscope.providers import evidence_nli, local_nli
from commentscope.storage import write_json_exclusive as write
from experiments import fact_nli_probe as benchmark
from experiments import sequential_agent_review as agents
from experiments import sequential_corpus_review as clusters
from experiments import sequential_corpus_pipeline as pipeline

VERSION = 'sequential-factory-offline-readiness-0.1'
FIXED_BENCHMARK_BINDINGS = {
    'plan_sha256': '19fcc086e6d40e4fdc715679e85670271a4f892bf6340123910191ab9e560680',
    'report_sha256': '3e5de5067fbe022ee16620567d516c88a5cd8d2c5b549830225df5167690ce04',
    'result_sha256': '3a92cf3c834a8a2a1bb489f9340b4ce4bb562ad4de6939c1d8b935a5f0dbfcea',
}


def replay_benchmark(directory, current_plan, actual_checks):
    """Narrow compatibility of the original fixed benchmark, not its old runner.

    Unrelated old code is allowed to change. Decision code, frozen cases,
    request, recorded logits, model identity and relevant runtime are not.
    Model file hashes are compared between pinned plans, never re-read here.
    """
    pipeline.private(directory)
    paths = {name: directory/(name + '.json') for name in ('plan', 'report', 'result', 'completed')}
    plan, saved, result, completed = [read_json(paths[k]) for k in paths]
    if (completed != FIXED_BENCHMARK_BINDINGS
            or completed != {k + '_sha256': sha(paths[k]) for k in ('plan', 'report', 'result')}
            or plan['artifact_kind'] != benchmark.VERSION
            or digest(plan['request']) != plan['request_sha256']):
        raise ValueError('Fixed fact benchmark identity or completion changed')
    live(plan['expires_at'])
    if any(sha(p) != h for p, h in plan['inputs'].items()):
        raise ValueError('Fixed benchmark source inputs changed')
    relevant = {'src/commentscope/providers/local_nli.py': local_nli,
                'src/commentscope/providers/evidence_nli.py': evidence_nli,
                'experiments/fact_nli_probe.py': benchmark}
    # WSL editable installs can spell the same NTFS path with different case.
    # Check filesystem identity, not lowercased paths (unsafe on case-sensitive disks).
    if any(not Path(p).samefile(m.__file__) for p, m in relevant.items()):
        raise ValueError('Loaded fact decision modules differ from the pinned repository')
    for pinned in (plan['code_sha256'], current_plan['code_sha256']):
        if any(pinned.get(p) != sha(p) for p in relevant):
            raise ValueError('Relevant fact decision code changed')
    expected = {'name': local_nli.MODEL, 'revision': local_nli.REVISION,
                'threshold': local_nli.THRESHOLD, 'device': 'cpu'}
    classifier = current_plan['classifier']
    weights = plan['model_sha256']
    weight_paths = [p for p in weights if Path(p).name == 'model.safetensors']
    if (plan['model'] != expected or classifier['name'] != expected['name']
            or classifier['revision'] != expected['revision'] or not weights
            or any(current_plan['model_files'].get(p) != h for p, h in weights.items())
            or len(weight_paths) != 1 or classifier['weights_sha256'] != weights[weight_paths[0]]):
        raise ValueError('Fixed benchmark and current classifier model differ')
    runtime_files = ['src/commentscope/providers/evidence_nli.py', 'src/commentscope/providers/local_nli.py']
    if classifier['runtime_sha256'] != digest({p: sha(p) for p in runtime_files}):
        raise ValueError('Current classifier decision runtime changed')
    metadata = result['metadata']
    required = {'model': local_nli.MODEL, 'revision': local_nli.REVISION, 'device': 'cpu',
                'dtype': 'float32', 'threads': 6, 'threshold': local_nli.THRESHOLD,
                'local_files_only': True, 'trust_remote_code': False, 'use_safetensors': True}
    if any(metadata.get(k) != v for k, v in required.items()):
        raise ValueError('Unexpected fixed benchmark runtime')
    cases = plan['request']['data']['cases']; lookup = {r['id']: r for r in result['results']}
    if len(cases) != 40 or len(lookup) != 40 or len(result['results']) != 40:
        raise ValueError('The entire fixed 40-case benchmark is required')
    for case in cases:
        validate_result(lookup[case['id']], case, metadata)
    replayed = benchmark.summarize(plan, result)
    if any(saved[k] != v for k, v in replayed.items()):
        raise ValueError('Fixed benchmark report does not replay')
    runtime_keys = (*required, 'torch', 'transformers', 'id2label')
    for check in actual_checks:
        observed = check['record']['metadata']
        if any(observed.get(k) != metadata[k] for k in runtime_keys):
            raise ValueError('Actual fact-check runtime differs from fixed benchmark')
    variant = replayed['variants']['nli_only']; rows = variant['rows']
    supported = sum(r['expected'] == 'supported' for r in rows)
    nonsupported = len(rows) - supported
    if supported != 10 or nonsupported != 30:
        raise ValueError('Fixed fact benchmark reference denominator changed')
    return {'artifact_kind': VERSION + '-fixed-facts',
        'inputs_sha256': {str(p): sha(p) for p in paths.values()},
        'source_inputs_sha256': plan['inputs'], 'relevant_code_sha256': {str(p): sha(p) for p in relevant},
        'pinned_model_files_sha256': weights, 'recorded_runtime': metadata,
        'supported_reference_cases': supported, 'unsupported_reference_cases': nonsupported,
        'supported_kept': variant['supported_kept'], 'unsupported_false_support': variant['unsupported_false_support'],
        'errors': variant['errors'], 'passed': variant['development_gate_passed'],
        'actual_fact_records_with_matching_runtime': len(actual_checks),
        'fresh_inference': False, 'new_model_calls': 0, 'actual_agent_fact_approval': 'separate_agent_review',
        'scope': 'Replay and compatibility of prior fixed component evidence, not fresh whole-run or Agent fact approval.'}


def summarize(plan, completion, output, cluster_report, agent_packet, agent_report, fact_report):
    """Combine re-evaluated evidence; this function does not create verdicts."""
    source_ids = set(agent_packet['sources'])
    states = output['source_states']
    if (len(states) != len(source_ids) or {r['source_id'] for r in states} != source_ids
            or len(source_ids) != plan['canonical_population']):
        raise ValueError('Complete canonical processing inventory required')
    seconds = completion['analysis_seconds_including_resume_downtime']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Finite nonnegative full-analysis timing required')
    by_cluster = {r['perspective_id']: r for r in cluster_report['per_cluster']}
    support_rows = []
    for agent in agent_packet['agents']:
        cid = agent['profile']['candidate_id']; reviewed = by_cluster[cid]
        counted = agent['counted_support_source_ids']
        support_rows.append({'candidate_id': cid, 'counted_source_ids': counted,
            'counted_support': len(counted), 'reviewed_supported': reviewed['reviewed_supported'],
            'passed': (len(counted) == len(set(counted)) == reviewed['counted_support']
                == reviewed['reviewed_supported'] and len(counted) >= 3
                and reviewed['cluster_review'] == 'coherent'
                and reviewed['incorrect_support'] == reviewed['unresolved_support'] == 0)})
    requirements = {
        'complete_fixed_execution': (completion['execution_complete'] is True
            and plan['runtime_reference_labels'] is False and plan['cross_run_response_reuse'] is False
            and cluster_report['scope'] == 'full_corpus'
            and cluster_report['canonical_population'] == cluster_report['evaluated_sources'] == len(source_ids)),
        'correct_meaningful_comment_utilization_at_least_80_percent': cluster_report['coverage_target_met'],
        'all_counted_supports_valid': cluster_report['support_validity_passed'],
        'at_least_two_agents_each_with_three_valid_supporters': len(support_rows) >= 2 and all(r['passed'] for r in support_rows),
        'all_agent_content_facts_and_fixed_runtime_reviewed_pass': agent_report['agent_content_runtime_review_passed'],
        'fixed_fact_benchmark_8_of_10_and_zero_of_30': fact_report['passed'],
    }
    return {'artifact_kind': VERSION, 'goal_revision': plan['goal_revision'],
        'factory_requirements_met': all(v is True for v in requirements.values()),
        'requirements': requirements, 'unmet_requirements': [k for k, v in requirements.items() if v is not True],
        'canonical_population': len(source_ids), 'meaningful_sources': cluster_report['meaningful_sources'],
        'correct_comment_utilization': cluster_report['correct_comment_utilization'],
        'utilized_source_ids': cluster_report['utilized_source_ids'],
        'unutilized_meaningful_ids': cluster_report['unutilized_meaningful_ids'],
        'excluded_source_ids': cluster_report['excluded_source_ids'],
        'support_counts': cluster_report['support_counts'], 'cluster_distribution': cluster_report['per_cluster'],
        'all_generated_agent_supports': support_rows, 'agent_review_counts': agent_report['review_counts'],
        'argument_deferrals': agent_packet['argument_deferrals'], 'fact_deferrals': agent_packet['fact_deferrals'],
        'processing_states': dict(Counter(r['state'] for r in states)), 'processing_errors': output['errors'],
        'analysis_seconds_including_resume_downtime': seconds, 'fixed_facts': fact_report,
        'new_model_calls': 0, 'runtime_input': False, 'independent_gold': False,
        'limitations': ['Assistant judgments are not independent gold or universal truth.',
            'All-artifact completion review is still required; this report does not certify paper or full-app completion.',
            'Fixed fact benchmark reuse is prior component evidence, not fresh actual-Agent fact verification.',
            'Comment utilization is not minority-viewpoint recall; small and unused groups remain reported.']}


def evaluate(directory, run, cluster_directory, cluster_parts, agent_directory, agent_parts, fact_directory):
    for path in (directory, run, cluster_directory, agent_directory, fact_directory, *cluster_parts, *agent_parts):
        pipeline.private(path)
    if directory.exists(): raise ValueError('Never overwrite readiness artifacts')
    for source in (cluster_directory, agent_directory):
        bound = Path(read_json(source/'manifest.json')['run_directory'])
        if not bound.is_dir() or not bound.samefile(run):
            raise ValueError('Both reviews must refer to the same completed run')
    prepared, bindings = agents.load_run(run)  # Reject prefixes before writing anything.
    plan = read_json(run/'plan.json'); completion = read_json(run/'completed.json')
    output = read_json(run/'artifacts/output.json')
    facts = replay_benchmark(fact_directory, plan, prepared['fact_checks'])
    cluster_report = clusters.evaluate(cluster_directory, cluster_parts, directory/'clusters-rechecked.json')
    agent_report = agents.evaluate(agent_directory, agent_parts, directory/'agents-rechecked.json')
    report = summarize(plan, completion, output, cluster_report, prepared, agent_report, facts)
    report.update(run_directory=str(run), inputs_sha256=bindings,
        review_inputs_sha256={str(p): sha(p) for root in (cluster_directory, agent_directory)
            for p in (root/'manifest.json', root/'packet.json')},
        review_parts_sha256={str(p): sha(p) for p in [*cluster_parts, *agent_parts]},
        review_code_sha256={**agents.code_hashes(), str(Path(__file__)): sha(__file__)},
        handoff_files={name: str(run/'artifacts'/(name + '.json'))
            for name in ('map', 'frames', 'memberships', 'agent-inputs', 'runtime', 'output')},
        rechecked_reports_sha256={str(p): sha(p) for p in
            (directory/'clusters-rechecked.json', directory/'agents-rechecked.json')})
    write(directory/'readiness.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--cluster-review', type=Path, required=True)
    parser.add_argument('--cluster-parts', type=Path, nargs='*', default=[])
    parser.add_argument('--agent-review', type=Path, required=True)
    parser.add_argument('--agent-parts', type=Path, nargs='*', default=[])
    parser.add_argument('--fact-benchmark', type=Path, default=Path('runs/fact-nli-40-20261013'))
    args = parser.parse_args()
    result = evaluate(args.directory, args.run, args.cluster_review, args.cluster_parts,
                      args.agent_review, args.agent_parts, args.fact_benchmark)
    print({k: result[k] for k in ('factory_requirements_met', 'unmet_requirements', 'correct_comment_utilization', 'new_model_calls')})
