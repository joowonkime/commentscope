"""Bounded product profiling from all qualified candidates of two cached retrievers.

Replay source decisions, never previous type/fact outcomes or development labels.
Ground selection sees original argument links; separate calls classify each text.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from commentscope.factory import argument_graph as graph, grounded_factory as factory
from commentscope.factory import membership_policy, nli_fact_records as records, bounded_span_typing
from commentscope.factory import semantic_neighborhood
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.providers import evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash, command
from experiments.fresh_grounded_pipeline import Runner, source_rows
from experiments.scoped_discovery_probe import code_hashes
from experiments import span_integration_probe as prior

VERSION = 'cached-argument-graph-product-0.2'
CONTROLS = Path('tests/fixtures/epistemic-type-controls.json')
CAPACITIES = {'baseline': (4096, 256, 0), 'expanded': (8192, 1024, 768)}


def profile_capacity(deployment, mode):
    if mode not in CAPACITIES: raise ValueError('Explicit known profile capacity required')
    if deployment['runtime']['context'] != 4096 or deployment['runtime']['reasoning_budget'] != 256:
        raise ValueError('Capacity comparison requires the frozen 4096/256 baseline')
    context, reasoning, extra = CAPACITIES[mode]
    result = deepcopy(deployment)
    result['runtime'].update(context=context, reasoning_budget=reasoning)
    return result, extra


def allocate(req, extra):
    if type(extra) is not int or extra not in {0, 768}: raise ValueError('Unknown token allocation')
    return {**deepcopy(req), 'max_tokens': req['max_tokens']+extra}


def union_selections(left, right):
    proposals = deepcopy(left['proposals'])+deepcopy(right['proposals']); rows = []; actual = {}
    if len(proposals) > 6 or len({p['id'] for p in proposals}) != len(proposals):
        raise ValueError('Unique bounded candidate population required')
    # No semantic merge/dedup based on earlier quality outcomes.
    for prefix, selection in [('R-', left), ('N-', right)]:
        if set(selection['actual']) != {r['id'] for r in selection['rows']}: raise ValueError('Incomplete membership')
        for row in selection['rows']:
            rid = prefix+row['id']; rows.append({**deepcopy(row), 'id': rid})
            actual[rid] = selection['actual'][row['id']]
    return {'proposals': proposals, 'rows': rows, 'actual': actual}


def members(proposal, selection, policy):
    result = {}; seen = set()
    for row in selection['rows']:
        if row['candidate_id'] != proposal['id']: continue
        sid = row['source_id']; req = membership_policy.invocation(policy, row['text'], proposal['claims']['C'])
        if (sid in seen or row['text'] != proposal['sources'][sid] or row['claim'] != proposal['claims']['C']
                or req != row['request'] or digest(req) != row['request_sha256']):
            raise ValueError('Membership source/claim/request binding changed')
        seen.add(sid)
        if selection['actual'][row['id']] == 'supported': result[sid] = row['text']
    if seen != set(proposal['sources']) or len(result) < 3: raise ValueError('Insufficient complete canonical membership')
    return result


def prepare(directory, ranked_source, neighborhood_source, *, capacity='baseline'):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    # Reuse the existing strict provenance verifier. Its prepared-only manifest
    # does not execute typing or reuse its previous outputs.
    cache_dir = directory/'ranked-provenance'
    prior.prepare(cache_dir, ranked_source, typing_version=bounded_span_typing.VERSION, gpu_layers=32)
    base = read_json(cache_dir/'plan.json'); current = read_json(neighborhood_source/'plan.json')
    completed = read_json(neighborhood_source/'completed.json'); live(current['expires_at'])
    if current['artifact_kind'] != 'cached-product-path-0.1': raise ValueError('Unexpected neighborhood trial')
    for key in ['expires_at', 'membership_policy', 'budget', 'classifier', 'documents', 'selections', 'deployment']:
        if base[key] != current[key]: raise ValueError('Incompatible cached configurations: '+key)
    files = {**base['inputs'], **current['inputs'], str(cache_dir/'plan.json'): sha(cache_dir/'plan.json')}
    if any(sha(p) != h for p, h in files.items()): raise ValueError('Historical input changed')
    for name in ['plan.json', 'completed.json', 'ranking.json', 'source-requests.json', 'source-verdicts.json',
                 'bundle.json', 'compiled.json', 'membership-server/runtime.json', 'membership-server/stopped.json']:
        path = neighborhood_source/name; files[str(path)] = sha(path)
    for name in ('bundle', 'compiled'):
        if completed[name+'_sha256'] != sha(neighborhood_source/(name+'.json')): raise ValueError('Completion changed')
    path = neighborhood_source/'calls/0001-ranking.result.json'
    ranked = semantic_neighborhood.assemble(current['units'], current['cache'], current['sources'],
                current['scheduled'], read_json(path))
    if ranked != read_json(neighborhood_source/'ranking.json'): raise ValueError('Neighborhood ranking changed')
    files[str(path)] = sha(path)
    rows = read_json(neighborhood_source/'source-requests.json'); actual = read_json(neighborhood_source/'source-verdicts.json')
    if rows != source_rows(ranked['proposals'], current['membership_policy']): raise ValueError('Source request population changed')
    if set(actual) != {r['id'] for r in rows}: raise ValueError('Incomplete source outcomes')
    for row, path in zip(rows, sorted((neighborhood_source/'calls').glob('*-membership.request.json')), strict=True):
        rp = path.with_name(path.name.replace('.request.', '.result.')); req = read_json(path); result = read_json(rp)
        if (req['plan_sha256'] != sha(neighborhood_source/'plan.json') or req['request'] != row['request']
                or req['request_sha256'] != digest(row['request']) or verdict(result) != actual[row['id']]
                or (not result['errors'] and json.loads(result['raw']) != result['output'])):
            raise ValueError('Neighborhood membership replay changed')
        files.update({str(p): sha(p) for p in (path, rp)})
    if (read_json(neighborhood_source/'membership-server/runtime.json')['command'] != command(current['deployment'], 'baseline')
            or read_json(neighborhood_source/'membership-server/stopped.json')['returncode'] != 0):
        raise ValueError('Expected clean historical deployment')
    counts = Counter(r['candidate_id'] for r in rows if actual[r['id']] == 'supported')
    ids = {pid for pid, n in counts.items() if n >= 3}
    right = {'proposals': [p for p in ranked['proposals'] if p['id'] in ids],
             'rows': [r for r in rows if r['candidate_id'] in ids]}
    right['actual'] = {r['id']: actual[r['id']] for r in right['rows']}
    selection = union_selections(base['selection'], right)
    original_units = read_json(ranked_source/'plan.json')['units']
    if original_units != current['units']: raise ValueError('Different source extraction populations')
    graphs = {}; maximum = 0
    for p in selection['proposals']:
        supported = members(p, selection, base['membership_policy'])
        graphs[p['id']] = graph.inventory(current['units'], supported)
        graph.select_request(p['claims']['C'], supported, graphs[p['id']])
        maximum += 2*len(supported)
    if maximum > 40: raise ValueError('Detail budget exceeded')
    controls = read_json(CONTROLS); files[str(CONTROLS)] = sha(CONTROLS)
    plan = {k: deepcopy(base[k]) for k in ['expires_at', 'deployment', 'membership_policy', 'classifier',
            'documents', 'selections', 'budget', 'evaluation', 'model_files']}
    profiling, extra = profile_capacity(base['deployment'], capacity)
    plan.update(artifact_kind=VERSION, inputs=files, code_sha256=code_hashes(), selection=selection,
        units=current['units'], graphs=graphs, controls=controls,
        profile_capacity=capacity, profile_deployment=profiling, profile_extra_tokens=extra,
        limits={'analysis_seconds': 1800, 'call_seconds': 90, 'fact_seconds': 240, 'detail_relations': maximum},
        fresh_analysis=False, runtime_reference_labels=False, quality_gate_passed=False,
        acceptance={'distinct_agents_min': 2, 'canonical_support_min': 3, 'review_all_compiled_profiles': True,
                    'critical_distortions_max': 0, 'type_controls_are_diagnostic_not_independent_gold': True})
    write(directory/'plan.json', plan)
    print({'prepared': True, 'all_candidates': len(selection['proposals']), 'cached_core_relations': len(selection['rows']),
           'max_detail_relations': maximum, 'type_controls': len(controls), 'profile_capacity': capacity}, flush=True)


def profile(proposal, selection, units, policy, runner, *, extra_tokens=0):
    supported = members(proposal, selection, policy); evidence = graph.inventory(units, supported)
    core_req = allocate(graph.type_request(proposal['claims']['C']['text'], supported), extra_tokens)
    core_kind = graph.kind(runner.call('core-kind', core_req))
    if core_kind not in {'fact', 'value', 'prediction'}: return None, 'core_'+core_kind
    select_req = allocate(graph.select_request(proposal['claims']['C'], supported, evidence), extra_tokens)
    chosen = graph.selection(runner.call('argument-selection', select_req), evidence)
    if chosen['status'] == 'defer': return None, chosen['reason']
    kinds = {}; traces = {'core_type': digest(core_req), 'argument_selection': digest(select_req)}
    for nid in chosen['node_ids']:
        node = evidence['nodes'][nid]
        req = allocate(graph.type_request(node['text'], {node['source_id']: supported[node['source_id']]}), extra_tokens)
        kinds[nid] = graph.kind(runner.call('ground-kind', req)); traces[nid] = digest(req)
    if any(k not in {'fact', 'value', 'prediction'} for k in kinds.values()): return None, 'ground_type_unresolved'
    typed = graph.assemble(proposal, supported, units, core_kind, chosen, kinds)
    typed['decision_request_hashes'] = traces
    return typed, None


def execute(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION: raise ValueError('Unknown graph trial')
    profiling, extra = profile_capacity(plan['deployment'], plan['profile_capacity'])
    if profiling != plan['profile_deployment'] or extra != plan['profile_extra_tokens']:
        raise ValueError('Frozen profile capacity changed')
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen input/code/model changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary(), 'fresh_analysis': False})
    try:
        selected = plan['selection']; typed = []; deferred = []; detail_actual = {}; controls = []
        with owned_server(plan['profile_deployment'], 'baseline', directory/'profile-server'):
            for row in plan['controls']:
                req = allocate(graph.type_request(row['target'], {'synthetic': row['source']}), extra)
                result = runner.call('type-control', req)
                try: actual = graph.kind(result)
                except ValueError: actual = 'error'
                controls.append({'id': row['id'], 'expected': row['expected'], 'actual': actual, 'passed': actual == row['expected']})
            write(directory/'type-controls.json', controls)
            for proposal in selected['proposals']:
                if graph.inventory(plan['units'], members(proposal, selected, plan['membership_policy'])) != plan['graphs'][proposal['id']]:
                    raise ValueError('Argument population changed')
                try: value, reason = profile(proposal, selected, plan['units'], plan['membership_policy'], runner, extra_tokens=extra)
                except (ValueError, TypeError, KeyError, AttributeError) as exc: value, reason = None, 'profile_contract_'+type(exc).__name__
                if value is None: deferred.append({'id': proposal['id'], 'reason': reason})
                else: typed.append(value)
            mapped = {p['id']: p for p in typed}; derived = []
            for row in selected['rows']:
                if row['candidate_id'] not in mapped: continue
                claim = mapped[row['candidate_id']]['claims']['C']
                if membership_policy.invocation(plan['membership_policy'], row['text'], claim) != row['request']:
                    raise ValueError('Profiling changed membership target')
                derived.append({**deepcopy(row), 'claim': deepcopy(claim)})
            details = membership_policy.bind_rows(plan['membership_policy'], factory.detail_requests(typed, derived, selected['actual']))
            if len(details) > plan['limits']['detail_relations']: raise ValueError('Detail population exceeded')
            write(directory/'typed.json', {'proposals': typed, 'core_rows': derived, 'details': details, 'deferred': deferred})
        if details:
            # Membership keeps its evaluated context/reasoning/token limits.
            # A profiling budget increase must not consume its answer allowance.
            with owned_server(plan['deployment'], 'baseline', directory/'membership-server'):
                for row in details: detail_actual[row['id']] = verdict(runner.call('detail', row['request']))
        write(directory/'detail-verdicts.json', detail_actual)
        admitted, argument_deferred = graph.admit(typed, details, detail_actual)
        admitted_ids = {p['id'] for p in admitted}
        write(directory/'admission.json', {'candidate_ids': sorted(admitted_ids), 'deferred': argument_deferred})
        bundle = factory.bundle(admitted, [r for r in derived if r['candidate_id'] in admitted_ids], selected['actual'],
            [r for r in details if r['candidate_id'] in admitted_ids], detail_actual,
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
        report = {'artifact_kind': VERSION, 'elapsed_seconds': time.monotonic()-started,
            'profile_capacity': plan['profile_capacity'],
            'fresh_analysis': False, 'candidates': len(selected['proposals']), 'typed_candidates': len(typed),
            'typing_deferred': deferred, 'detail_relations': len(details), 'fact_claims': len(packets),
            'argument_deferred': argument_deferred,
            'type_controls': {'total': len(controls), 'passed': sum(r['passed'] for r in controls)},
            'screened_inputs': len(compiled['profiles']), 'qualified_agents': 0, 'quality_gate_passed': False,
            'bundle_sha256': sha(directory/'bundle.json'), 'compiled_sha256': sha(directory/'compiled.json'),
            'budget_after': budget.summary(), 'runtime_reference_labels': False,
            'remaining_gates': ['all_actual_core_and_reason_audit', 'distinctness', 'actual_qa', 'actual_ui', 'fresh_analysis']}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
                                      'budget_after': budget.summary(), 'quality_gate_passed': False})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('phase', choices=['prepare', 'run'])
    p.add_argument('directory', type=Path); p.add_argument('--ranked-source', type=Path); p.add_argument('--neighborhood-source', type=Path)
    p.add_argument('--profile-capacity', choices=list(CAPACITIES), default='baseline')
    args = p.parse_args()
    if args.phase == 'prepare':
        if args.ranked_source is None or args.neighborhood_source is None: p.error('prepare requires both cached sources')
        prepare(args.directory, args.ranked_source, args.neighborhood_source, capacity=args.profile_capacity)
    else: execute(args.directory)
