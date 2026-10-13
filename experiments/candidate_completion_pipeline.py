"""Fresh discovery, whole-corpus search, then finish one candidate at a time.

Every attempted candidate has a complete downstream time slot before starting.
No historical responses, manual candidate selection or runtime reference labels.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import candidate_completion as completion
from commentscope.factory import grounded_factory, argument_graph, membership_policy, source_first
from commentscope.factory import source_index, support_retrieval, nli_fact_records, product_evaluation
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.core_admission_bound import CoreAdmissionBound
from commentscope.factory.fact_checks import live
from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.providers import fresh_embedding, completion_candidates, target_ranking_nli, evidence_nli
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import fresh_product_pipeline as legacy
from experiments.fresh_grounded_pipeline import Runner, proposals_from_sources, source_rows
from experiments.argument_graph_probe import profile, members, allocate
from experiments.audit_model_compare import owned_server, file_hash

VERSION = 'candidate-atomic-fresh-pipeline-0.1'
LIMITS = {'analysis_seconds': 3600, 'source_analysis_seconds': 600, 'groups': 20,
          'call_seconds': 90, 'embedding_seconds': 300, 'ranking_seconds': 300, 'fact_seconds': 240,
          'source_request_bytes': 27000, 'candidate_threshold': .45, 'discovery_targets': 24,
          'core_relations': 200, 'candidate_slot_seconds': completion.SLOT_SECONDS,
          'candidate_work_seconds': completion.WORK_SECONDS, 'max_attempts': completion.MAX_ATTEMPTS,
          'finalize_seconds': completion.FINALIZE_SECONDS}


class CompletionRunner(Runner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.allocation = completion.Allocation(self)

    def timeout(self, maximum):
        return self.allocation.timeout(super().timeout(maximum))


def prepare(directory, snapshot, source_config, graph_config, *, gpu_layers):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    # Reuse the explicit configuration allowlist; this child plan executes no calls.
    legacy.prepare(directory/'configuration', snapshot, source_config, graph_config, gpu_layers=gpu_layers)
    plan = read_json(directory/'configuration'/'plan.json')
    plan.update(artifact_kind=VERSION, limits=deepcopy(LIMITS),
                retrieval_limits=deepcopy(support_retrieval.LIMITS),
                candidate_contract=completion.VERSION, discovery_min_sources=1, admission_min_sources=3,
                detail_scope='selected_ground_original_author_only',
                source_argument_audit=True, quality_gate_passed=False)
    write(directory/'plan.json', plan)
    print({'prepared': True, 'fresh_analysis': True, 'candidate_atomic': True}, flush=True)


def complete_candidate(p, directory, plan, runner, relations, records):
    cd = directory/'candidates'/p['id']; write(cd/'proposal.json', p)
    rows = source_rows([p], plan['membership_policy'])
    for row in rows: row['id'] = p['id']+'-'+row['id']
    bound = CoreAdmissionBound(rows)
    with owned_server(plan['deployments']['membership'], 'baseline', cd/'core-server'):
        actual = relations.judge(rows, 'core-'+p['id'], admission_bound=bound)
    selection = {'proposals': [p], 'rows': rows, 'actual': actual}
    write(cd/'membership.json', {**selection, 'admission_bound': bound.report()})
    if sum(v == 'supported' for v in actual.values()) < 3:
        return None, 'insufficient_core_support'
    supported = members(p, selection, plan['membership_policy'])
    missing = [sid for sid in sorted(supported) if sid not in records]
    if missing:
        with owned_server(plan['deployments']['extraction'], 'baseline', cd/'source-server'):
            for sid in missing:
                req = source_first.invocation(supported[sid])
                if len(json.dumps(req).encode()) > plan['limits']['source_request_bytes']:
                    record = {'source_id': sid, 'source_sha256': digest(supported[sid]),
                              'status': 'unprocessed_size_budget', 'units': [], 'errors': ['size_budget']}
                else: record = source_first.bind(sid, supported[sid], runner.call('member-extraction', req))
                records[sid] = record
                write(directory/'member-source-results'/(digest(sid)+'.json'), record)
    selected_records = [records[sid] for sid in sorted(supported)]
    write(cd/'source-analysis.json', selected_records)
    if any(r['source_sha256'] != digest(supported[r['source_id']]) for r in selected_records):
        raise ValueError('Source analysis binding changed')
    if any(r['errors'] or not r['units'] for r in selected_records):
        return None, 'member_argument_analysis_unavailable'
    units = [u for r in selected_records for u in r['units']]
    with owned_server(plan['deployments']['profile'], 'baseline', cd/'profile-server'):
        typed, reason = profile(p, selection, units, plan['membership_policy'], runner,
                                extra_tokens=plan['profile_extra_tokens'])
        if typed is None: return None, reason
        write(cd/'typed.json', typed)
        req = allocate(completion.audit_request(typed, supported, units), plan['profile_extra_tokens'])
        audited = runner.call('argument-audit', req)
        write(cd/'argument-audit.json', {'request_sha256': digest(req), 'result': audited,
                                       'passed': completion.audit_passed(typed, audited)})
        if not completion.audit_passed(typed, audited): return None, 'argument_audit_failed'
    derived = [{**deepcopy(r), 'claim': deepcopy(typed['claims']['C'])} for r in rows]
    if any(membership_policy.invocation(plan['membership_policy'], r['text'], r['claim']) != r['request'] for r in derived):
        raise ValueError('Typing changed core target')
    details = completion.origin_details(typed, supported, units, plan['membership_policy'])
    detail_actual = {}
    if details:
        with owned_server(plan['deployments']['membership'], 'baseline', cd/'detail-server'):
            detail_actual = relations.judge(details, 'detail-'+p['id'])
    write(cd/'details.json', {'rows': details, 'actual': detail_actual})
    # No selected ground is deleted to rescue a candidate, essential or otherwise.
    if any(v != 'supported' for v in detail_actual.values()): return None, 'selected_ground_not_supported_by_author'
    bundle = grounded_factory.bundle([typed], derived, actual, details, detail_actual,
        expires_at=plan['expires_at'], model=plan['classifier'], documents=plan['documents'])
    packets = grounded_factory.fact_packets(bundle, plan['selections'])
    if packets:
        req = nli_fact_records.invocation(packets)
        result = runner.call('facts-'+p['id'], req, provider=evidence_nli.generate, maximum=plan['limits']['fact_seconds'])
        checked = nli_fact_records.records(packets, bundle['model'], result, batch_request=req)
        bundle['checks'] = [{'claim_id': packet['claim']['id'], 'selections': plan['selections'], 'record': record}
                            for packet, record in zip(packets, checked, strict=True)]
    compiled = compile_inputs(bundle)
    write(cd/'bundle.json', bundle); write(cd/'compiled.json', compiled)
    if any(profile['omitted'] for profile in compiled['profiles']):
        return None, 'selected_argument_would_be_omitted'
    return bundle, 'screened_input' if compiled['profiles'] else 'fact_or_compilation_deferred'


def merge_bundles(bundles, plan):
    merged = grounded_factory.bundle([], [], {}, [], {}, expires_at=plan['expires_at'],
                                     model=plan['classifier'], documents=plan['documents'])
    sources = {}
    for b in bundles:
        if any(b[k] != merged[k] for k in ('expires_at', 'model', 'documents')): raise ValueError('Bundle configuration changed')
        for row in b['sources']:
            if row['id'] in sources and sources[row['id']] != row: raise ValueError('Source identity collision')
            sources[row['id']] = row
        for key in ('claims', 'relations', 'candidates', 'checks'): merged[key].extend(deepcopy(b[key]))
    merged['sources'] = [sources[k] for k in sorted(sources)]
    compile_inputs(merged)
    return merged


def execute(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    if (plan['artifact_kind'] != VERSION or plan['limits'] != LIMITS
            or plan['retrieval_limits'] != support_retrieval.LIMITS or plan['candidate_contract'] != completion.VERSION):
        raise ValueError('Unknown frozen completion configuration')
    if product_evaluation.execution_state(plan['evaluation']['source_measurement'], 'product_diagnostic') != plan['evaluation']:
        raise ValueError('Product diagnostic evaluation required')
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen file changed')
    for d in plan['deployments'].values():
        for info in (d['server'], d['models']['baseline']):
            if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = CompletionRunner(directory, plan, budget); runner.started = started; relations = legacy.Relations(runner)
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'fresh_analysis': True, 'budget_before': budget.summary()})
    try:
        path = directory/'fresh-groups.json'
        req = {'system': fresh_embedding.VERSION, 'data': {'snapshot': plan['snapshot'],
               'snapshot_sha256': sha(plan['snapshot']), 'output': str(path)}, 'schema': {}, 'max_tokens': 1}
        embedded = runner.call('embedding', req, provider=fresh_embedding.generate, maximum=plan['limits']['embedding_seconds'])
        if embedded['sha256'] != sha(path): raise ValueError('Embedding artifact changed')
        raw = read_json(path); loaded = load_snapshot(plan['snapshot'])
        canonical = sorted((c for c in normalize_snapshot(loaded.snapshot) if c.duplicate_of is None and c.text_analysis), key=lambda c: c.comment_id)
        sources = {sid: row['text'] for sid, row in raw['sources'].items()}
        source_index.validate(raw['source_index'], canonical, loaded.sha256, MODEL, REVISION, sources=sources)
        with owned_server(plan['deployments']['extraction'], 'baseline', directory/'discovery-server'):
            units, discovery_sources, coverage = proposals_from_sources(raw, runner)
        records = {r['source_id']: r for r in read_json(directory/'source-analysis.json')['records']}
        req = {'system': completion_candidates.VERSION, 'data': {'units': units, 'sources': discovery_sources,
               'threshold': plan['limits']['candidate_threshold']}, 'schema': {}, 'max_tokens': 1}
        cache = runner.call('discovery-candidates', req, provider=completion_candidates.generate, maximum=plan['limits']['embedding_seconds'])
        write(directory/'unit-candidates.json', cache)
        proposals = cache['proposals'][:plan['limits']['discovery_targets']]
        write(directory/'discovery-deferred.json', [{'id': p['id'], 'reason': 'discovery_target_budget'} for p in cache['proposals'][len(proposals):]])
        scheduled = support_retrieval.schedule(proposals, units, cache, raw['source_index'], sources)
        write(directory/'retrieval-schedule.json', scheduled)
        req = {'system': target_ranking_nli.VERSION, 'data': {'pairs': scheduled['pairs']}, 'schema': {}, 'max_tokens': 1}
        ranked = runner.call('support-ranking', req, provider=target_ranking_nli.generate, maximum=plan['limits']['ranking_seconds'])
        broad = support_retrieval.assemble(proposals, units, cache, raw['source_index'], sources, scheduled, ranked)
        union = support_retrieval.union_nominations(proposals, broad)
        write(directory/'retrieval.json', broad); write(directory/'nominations.json', union)
        queue = completion.queue(proposals, broad, union); write(directory/'candidate-queue.json', queue)
        bundles = []; outcomes = []; reserved_relations = 0
        for task in queue:
            p = task['proposal']
            if reserved_relations+len(p['sources']) > plan['limits']['core_relations']:
                outcomes.append({'id': p['id'], 'state': 'unprocessed_core_capacity'}); continue
            if not runner.allocation.begin(p['id']):
                outcomes.append({'id': p['id'], 'state': 'unprocessed_completion_budget'}); continue
            reserved_relations += len(p['sources'])
            try:
                bundle, state = complete_candidate(p, directory, plan, runner, relations, records)
                if bundle is not None: bundles.append(bundle)
            except BudgetExhausted: raise
            except (TimeoutError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
                state = 'candidate_failed_'+type(exc).__name__
                write(directory/'candidates'/p['id']/'failed.json', {'exception_type': type(exc).__name__, 'quality_gate_passed': False})
            runner.allocation.finish(state)
            outcomes.append({'id': p['id'], 'state': state})
            write(directory/'candidates'/p['id']/'outcome.json', outcomes[-1])
        bundle = merge_bundles(bundles, plan); compiled = compile_inputs(bundle)
        write(directory/'bundle.json', bundle); write(directory/'compiled.json', compiled)
        write(directory/'relation-call-map.json', relations.trace)
        write(directory/'all-source-analysis.json', list(records.values()))
        elapsed = time.monotonic()-started
        report = {'artifact_kind': VERSION, 'fresh_analysis': True, 'fresh_analysis_seconds': elapsed,
            'within_one_hour': elapsed <= 3600, 'coverage': coverage, 'analyzed_unique_sources': len(records),
            'queue_candidates': len(queue), 'attempts': runner.allocation.attempts, 'outcomes': outcomes,
            'reserved_core_relations': reserved_relations, 'screened_inputs': len(compiled['profiles']),
            'qualified_agents': 0, 'quality_gate_passed': False, 'runtime_reference_labels': False,
            'bundle_sha256': sha(directory/'bundle.json'), 'compiled_sha256': sha(directory/'compiled.json'),
            'budget_after': budget.summary()}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k not in ('coverage', 'attempts', 'outcomes', 'budget_after')}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
              'budget_after': budget.summary(), 'quality_gate_passed': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    for key in ('snapshot', 'source-config', 'graph-config'): p.add_argument('--'+key, type=Path, required=True)
    p.add_argument('--gpu-layers', choices=['all', '32'], required=True)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.snapshot, args.source_config, args.graph_config, gpu_layers=args.gpu_layers)
    else: execute(args.directory)
