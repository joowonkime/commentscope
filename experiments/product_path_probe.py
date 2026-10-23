"""One bounded product-path trial: cached units -> candidates -> grounded inputs.

Two declared changes: cross-frame sparse retrieval and reusing extracted reasons.
No claim of isolated causal improvement, fresh timing or automatic quality pass.
Every nominated candidate is processed; no selection using review labels.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import source_first, semantic_neighborhood as retrieval
from commentscope.factory import grounded_factory as factory, membership_policy, nli_fact_records as records
from commentscope.factory.unit_reason_typing import UnitReasonTyping
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.providers import target_ranking_nli, evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import file_hash, owned_server
from experiments.fresh_grounded_pipeline import Runner, source_rows, classify
from experiments.scoped_discovery_probe import code_hashes
from experiments.span_integration_probe import deployment_for_trial

VERSION = 'cached-product-path-0.1'


def prepare(directory, source, gpu_layers=32):
    if directory.exists(): raise ValueError('Never overwrite a run')
    original = read_json(source/'plan.json'); live(original['expires_at'])
    if original['candidate_algorithm'] != source_first.VERSION: raise ValueError('Expected source-first baseline')
    files = dict(original['inputs'])
    if any(sha(p) != h for p, h in files.items()): raise ValueError('Historical input changed')
    analysis = read_json(source/'source-analysis.json'); raw = read_json(source/'fresh-groups.json')
    sources = {sid: row['text'] for sid, row in raw['sources'].items()}
    units = [u for row in analysis['records'] for u in row['units']]
    cache = read_json(source/'unit-candidates.json')
    files.update({str(source/name): sha(source/name) for name in
                  ('plan.json', 'completed.json', 'source-analysis.json', 'fresh-groups.json', 'unit-candidates.json')})
    for record, path in zip(analysis['records'], sorted((source/'calls').glob('*-source-extraction.request.json')), strict=True):
        result_path = path.with_name(path.name.replace('.request.', '.result.'))
        req = read_json(path); result = read_json(result_path)
        expected = source_first.invocation(sources[record['source_id']])
        if (req['plan_sha256'] != sha(source/'plan.json') or req['request'] != expected
                or req['request_sha256'] != digest(expected)
                or source_first.bind(record['source_id'], sources[record['source_id']], result) != record
                or (not result['errors'] and json.loads(result['raw']) != result['output'])):
            raise ValueError('Extraction replay changed')
        files.update({str(p): sha(p) for p in (path, result_path)})
    # Bind vectors to the original provider response, not just convenient IDs.
    paths = list((source/'calls').glob('*-unit-candidates.request.json'))
    if len(paths) != 1: raise ValueError('Expected one embedding call')
    path = paths[0]; result_path = path.with_name(path.name.replace('.request.', '.result.'))
    req = read_json(path)
    if (req['plan_sha256'] != sha(source/'plan.json') or req['request_sha256'] != digest(req['request'])
            or req['request']['data']['units'] != units or read_json(result_path) != cache
            or any(sources[sid] != text for sid, text in req['request']['data']['sources'].items())):
        raise ValueError('Cached embedding provenance changed')
    files.update({str(p): sha(p) for p in (path, result_path)})
    scheduled = retrieval.schedule(units, cache, sources)
    deployment, change = deployment_for_trial(original['deployments']['membership'], gpu_layers)
    plan = {'artifact_kind': VERSION, 'expires_at': original['expires_at'], 'source': str(source),
            'inputs': files, 'code_sha256': code_hashes(), 'model_files': original['model_files'],
            'units': units, 'cache': cache, 'sources': sources, 'scheduled': scheduled,
            'deployment': deployment, 'deployment_change': change,
            'membership_policy': original['membership_policy'], 'classifier': original['classifier'],
            'documents': original['documents'], 'selections': original['selections'],
            'budget': original['budget'], 'retrieval_limits': retrieval.LIMITS,
            'limits': {'analysis_seconds': 1800, 'call_seconds': 90, 'ranking_seconds': 600, 'fact_seconds': 240},
            'evaluation': original['evaluation'], 'typing_version': UnitReasonTyping.VERSION,
            'fresh_analysis': False, 'runtime_reference_labels': False, 'quality_gate_passed': False,
            'acceptance': {'distinct_agents_min': 2, 'canonical_support_min': 3,
                'actual_core_and_reason_audit': 'all automatically compiled profiles, not best two',
                'critical_distortions_max': 0, 'new_retries': 0,
                'continue_to_actual_qa_only_after_content_review': True}}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'units': len(units), 'ranking_pairs': len(scheduled['pairs']),
           'cross_frame_pairs': sum(p['crosses_frame'] for p in scheduled['pairs']),
           'max_candidates': retrieval.LIMITS['candidates'], 'fresh_analysis': False}, flush=True)


def execute(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or plan['retrieval_limits'] != retrieval.LIMITS:
        raise ValueError('Trial version changed')
    for key in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[key].items()): raise ValueError('Frozen input/code/model changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    if plan['scheduled'] != retrieval.schedule(plan['units'], plan['cache'], plan['sources']):
        raise ValueError('Frozen retrieval changed')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary(), 'fresh_analysis': False})
    try:
        req = {'system': target_ranking_nli.VERSION, 'data': {'pairs': plan['scheduled']['pairs']}, 'schema': {}, 'max_tokens': 1}
        ranked = retrieval.assemble(plan['units'], plan['cache'], plan['sources'], plan['scheduled'],
            runner.call('ranking', req, provider=target_ranking_nli.generate, maximum=plan['limits']['ranking_seconds']))
        write(directory/'ranking.json', ranked)
        proposals = ranked['proposals']; rows = source_rows(proposals, plan['membership_policy'])
        write(directory/'source-requests.json', rows)
        actual = {}; detail_actual = {}; typed = []; derived = []; details = []; deferred = []
        if rows:
            with owned_server(plan['deployment'], 'baseline', directory/'membership-server'):
                for row in rows: actual[row['id']] = verdict(runner.call('membership', row['request']))
                write(directory/'source-verdicts.json', actual)
                typed, derived, deferred = classify(proposals, rows, actual, runner, typer=UnitReasonTyping(plan['units']))
                details = membership_policy.bind_rows(plan['membership_policy'], factory.detail_requests(typed, derived, actual))
                write(directory/'typed.json', {'proposals': typed, 'core_rows': derived, 'details': details, 'deferred': deferred})
                for row in details: detail_actual[row['id']] = verdict(runner.call('detail', row['request']))
        else:
            write(directory/'source-verdicts.json', actual)
            write(directory/'typed.json', {'proposals': [], 'core_rows': [], 'details': [], 'deferred': []})
        write(directory/'detail-verdicts.json', detail_actual)
        bundle = factory.bundle(typed, derived, actual, details, detail_actual,
            expires_at=plan['expires_at'], model=plan['classifier'], documents=plan['documents'])
        packets = factory.fact_packets(bundle, plan['selections'])
        if packets:
            req = records.invocation(packets)
            judged = runner.call('facts', req, provider=evidence_nli.generate, maximum=plan['limits']['fact_seconds'])
            bound = records.records(packets, bundle['model'], judged, batch_request=req)
            bundle['checks'] = [{'claim_id': p['claim']['id'], 'selections': plan['selections'], 'record': r}
                                for p, r in zip(packets, bound, strict=True)]
        compiled = compile_inputs(bundle)
        write(directory/'bundle.json', bundle); write(directory/'compiled.json', compiled)
        counts = Counter(r['candidate_id'] for r in rows if actual[r['id']] == 'supported')
        report = {'artifact_kind': VERSION, 'elapsed_seconds': time.monotonic()-started,
            'fresh_analysis': False, 'source_units_reused': len(plan['units']),
            'ranking_pairs': len(plan['scheduled']['pairs']), 'ranking_errors': len(ranked['pair_errors']),
            'nominated_candidates': len(proposals), 'core_support_counts': dict(counts),
            'candidates_ge3': sum(n >= 3 for n in counts.values()), 'typed_candidates': len(typed),
            'typing_deferred': deferred, 'detail_relations': len(details), 'fact_claims': len(packets),
            'screened_inputs': len(compiled['profiles']), 'qualified_agents': 0, 'quality_gate_passed': False,
            'runtime_reference_labels': False, 'bundle_sha256': sha(directory/'bundle.json'),
            'compiled_sha256': sha(directory/'compiled.json'), 'budget_after': budget.summary(),
            'remaining_gates': ['all_actual_core_and_reason_audit', 'distinctness', 'actual_qa', 'actual_ui', 'fresh_analysis']}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
                                      'budget_after': budget.summary(), 'quality_gate_passed': False})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'run']); p.add_argument('directory', type=Path)
    p.add_argument('--source', type=Path); p.add_argument('--gpu-layers', type=int, choices=range(33), default=32)
    args = p.parse_args()
    if args.phase == 'prepare':
        if args.source is None: p.error('prepare requires --source')
        prepare(args.directory, args.source, args.gpu_layers)
    else: execute(args.directory)
