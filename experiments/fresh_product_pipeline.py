"""Fresh snapshot to screened inputs using the integrated product architecture.

No historical model output is replayed. Existing configuration is imported through
an explicit allowlist; extraction, both retrievers, membership and profiling run
anew. A single deadline and ledger cover every stage. This is not quality approval.
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import argument_graph, membership_policy, product_evaluation
from commentscope.factory import semantic_neighborhood, target_ranking, grounded_factory, nli_fact_records
from commentscope.factory.core_admission_bound import CoreAdmissionBound
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.ingestion import load_snapshot
from commentscope.providers import fresh_embedding, source_first_candidates, target_ranking_nli, evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner, proposals_from_sources, source_rows
from experiments.argument_graph_probe import profile, profile_capacity
from experiments.scoped_discovery_probe import code_hashes
from experiments.target_ranking_probe import choose

VERSION = 'fresh-product-graph-pipeline-0.2'
LIMITS = {'analysis_seconds': 3600, 'source_analysis_seconds': 2100, 'groups': 20,
          'call_seconds': 90, 'embedding_seconds': 300, 'ranking_seconds': 600, 'fact_seconds': 240,
          'source_request_bytes': 27000, 'candidate_threshold': .45,
          'core_relations': 200, 'profile_candidates': 6, 'detail_relations': 120}


def combine(left, right, limit=6):
    """Merge only byte-identical core contracts, never semantic equivalents.

    Distinct canonical sources vote once. Shared judgments must agree (the runner
    reuses exact requests within this run). Bounded profile allocation happens
    before any type/fact outcome, without consulting content review labels.
    """
    if type(limit) is not int or not 1 <= limit <= 6: raise ValueError('Profile capacity must be 1..6')
    groups = {}; decisions = {}; origins = {}; seen = set()
    for selection in (left, right):
        if len({r['id'] for r in selection['rows']}) != len(selection['rows']) or set(selection['actual']) != {r['id'] for r in selection['rows']}:
            raise ValueError('Complete source decisions required')
        ids = {p['id'] for p in selection['proposals']}
        if len(ids) != len(selection['proposals']) or any(r['candidate_id'] not in ids for r in selection['rows']):
            raise ValueError('Invalid candidate population')
        for proposal in selection['proposals']:
            key = digest(proposal['claims']['C']); pid = proposal['id']
            if pid in seen: raise ValueError('Cross-retriever candidate ID collision')
            seen.add(pid)
            rows = [r for r in selection['rows'] if r['candidate_id'] == pid]
            if len({r['source_id'] for r in rows}) != len(rows) or {r['source_id'] for r in rows} != set(proposal['sources']):
                raise ValueError('Complete unique source population required')
            if key not in groups:
                groups[key] = deepcopy(proposal); origins[key] = []; decisions[key] = {}
            origins[key].append(pid)
            for row in rows:
                sid = row['source_id']; actual = selection['actual'][row['id']]
                if row['claim'] != proposal['claims']['C'] or row['text'] != proposal['sources'][sid] or digest(row['request']) != row['request_sha256']:
                    raise ValueError('Changed core/source request binding')
                if sid in decisions[key]:
                    old, state = decisions[key][sid]
                    if any(row[k] != old[k] for k in ('text','claim','request','request_sha256')) or actual != state:
                        raise ValueError('Conflicting duplicate source judgment')
                else: decisions[key][sid] = (row, actual)
                groups[key]['sources'][sid] = row['text']
    counts = {key: sum(state == 'supported' for _, state in rows.values()) for key, rows in decisions.items()}
    order = sorted(groups, key=lambda k: (-counts[k], groups[k]['id']))
    kept = []; deferred = []; rows = []; actual = {}
    for key in order:
        p = groups[key]; p['retrieval_candidate_ids'] = sorted(origins[key])
        reason = 'insufficient_core_support' if counts[key] < 3 else 'profile_capacity_budget' if len(kept) >= limit else None
        if reason:
            deferred.append({'id': p['id'], 'reason': reason, 'model_support_count': counts[key],
                             'support_count_complete': all(state != 'unassessed' for _, state in decisions[key].values()),
                             'support_upper_bound': counts[key] + sum(state == 'unassessed' for _, state in decisions[key].values()),
                             'retrieval_candidate_ids': p['retrieval_candidate_ids']}); continue
        kept.append(p)
        for sid, (row, state) in sorted(decisions[key].items()):
            rid = f'M{len(rows)+1:04}'
            rows.append({**deepcopy(row), 'id': rid, 'candidate_id': p['id']}); actual[rid] = state
    return {'proposals': kept, 'rows': rows, 'actual': actual, 'deferred': deferred}


class Relations:
    """Exact-request memoization only within one fresh run, including errors."""
    def __init__(self, runner):
        self.runner = runner; self.results = {}; self.trace = []

    def judge(self, rows, stage, *, admission_bound=None):
        actual = {}
        for row in rows:
            req = row['request']; key = digest(req)
            if key != row['request_sha256']: raise ValueError('Relation request changed')
            proof = admission_bound.skip_proof(row) if admission_bound is not None and key not in self.results else None
            if proof is not None:
                actual[row['id']] = 'unassessed'
                self.trace.append({'stage': stage, 'row_id': row['id'], 'candidate_id': row['candidate_id'],
                                  'request_sha256': key, 'call_sequence': None, 'reused_within_run': False,
                                  'unassessed_reason': 'pooled_support_upper_bound_below_minimum', 'bound': proof})
                continue
            reused = key in self.results
            if reused:
                old, result, sequence = self.results[key]
                if old != req: raise ValueError('Request digest collision')
            else:
                result = self.runner.call(stage, req); sequence = self.runner.seq
                self.results[key] = (deepcopy(req), result, sequence)
            actual[row['id']] = verdict(result)
            if admission_bound is not None: admission_bound.observe(row, actual[row['id']])
            self.trace.append({'stage': stage, 'row_id': row['id'], 'candidate_id': row['candidate_id'],
                              'request_sha256': key, 'call_sequence': sequence, 'reused_within_run': reused})
        return actual


def prepare(directory, snapshot, source_config, graph_config, *, gpu_layers):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    source = read_json(source_config); graph = read_json(graph_config)
    loaded = load_snapshot(snapshot); live(loaded.snapshot.usage.expires_at)
    if len(loaded.snapshot.comments) > 1000: raise ValueError('MVP comment cap exceeded')
    if (source['artifact_kind'] != 'fresh-grounded-pipeline-0.3'
            or graph['artifact_kind'] != 'cached-argument-graph-product-0.2'
            or graph['profile_capacity'] != 'expanded'):
        raise ValueError('Explicit known configuration sources required')
    for key in ('membership_policy','budget','classifier','documents','selections','model_files'):
        if source[key] != graph[key]: raise ValueError('Incompatible configuration '+key)
    membership_policy.validate(source['membership_policy'])
    deployments = {'extraction': deepcopy(source['deployments']['proposal']),
                   'membership': deepcopy(graph['deployment'])}
    if gpu_layers not in ('all', '32'): raise ValueError('Explicit supported GPU placement required')
    for value in deployments.values(): value['runtime']['gpu_layers'] = 'all' if gpu_layers == 'all' else 32
    deployments['profile'], extra = profile_capacity(deployments['membership'], 'expanded')
    for d in deployments.values():
        if d['models'] != deployments['membership']['models'] or d['server'] != deployments['membership']['server']:
            raise ValueError('One pinned local model and runtime required')
        for info in (d['server'], d['models']['baseline']):
            if file_hash(info['path']) != info['sha256']: raise ValueError('Model/runtime changed')
    if any(sha(p) != h for p, h in source['model_files'].items()): raise ValueError('Local classifier/embedding changed')
    # Import no cached units, membership decisions, selection, review or typing.
    plan = {k: deepcopy(source[k]) for k in ('membership_policy','budget','classifier','documents','selections','model_files','evaluation')}
    plan.update(artifact_kind=VERSION, snapshot=str(snapshot), expires_at=loaded.snapshot.usage.expires_at,
        inputs={str(p): sha(p) for p in (snapshot,source_config,graph_config)}, code_sha256=code_hashes(),
        deployments=deployments, profile_extra_tokens=extra, limits=deepcopy(LIMITS),
        retrieval_limits=deepcopy(semantic_neighborhood.LIMITS), fresh_analysis=True,
        runtime_reference_labels=False, quality_gate_passed=False,
        configuration_sources_only=[str(source_config),str(graph_config)],
        within_run_exact_request_reuse=True, cross_run_response_reuse=False)
    write(directory/'plan.json', plan)
    print({'prepared': True, 'fresh_analysis': True, 'gpu_layers': gpu_layers,
           'seconds_limit': LIMITS['analysis_seconds'], 'runtime_reference_labels': False}, flush=True)


def rank(proposals, units, candidates, sources, runner):
    scheduled = target_ranking.schedule(proposals, units)
    req = {'system': target_ranking_nli.VERSION, 'data': {'pairs': scheduled['pairs']}, 'schema': {}, 'max_tokens': 1}
    result = runner.call('target-ranking', req, provider=target_ranking_nli.generate, maximum=runner.plan['limits']['ranking_seconds'])
    ranked = target_ranking.assemble(proposals, units, scheduled, result)
    write(runner.directory/'target-ranking.json', {'scheduled': scheduled, 'result': ranked})
    scheduled = semantic_neighborhood.schedule(units, candidates, sources)
    req = {'system': target_ranking_nli.VERSION, 'data': {'pairs': scheduled['pairs']}, 'schema': {}, 'max_tokens': 1}
    result = runner.call('neighborhood-ranking', req, provider=target_ranking_nli.generate, maximum=runner.plan['limits']['ranking_seconds'])
    neighbors = semantic_neighborhood.assemble(units, candidates, sources, scheduled, result)
    write(runner.directory/'neighborhood-ranking.json', {'scheduled': scheduled, 'result': neighbors})
    return ranked['alternatives'], neighbors['proposals']


def execute(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or plan['limits'] != LIMITS or plan['retrieval_limits'] != semantic_neighborhood.LIMITS:
        raise ValueError('Unknown frozen fresh configuration')
    if product_evaluation.execution_state(plan['evaluation']['source_measurement'], 'product_diagnostic') != plan['evaluation']:
        raise ValueError('Fresh integration remains a product diagnostic')
    for field in ('inputs','code_sha256','model_files'):
        if any(sha(p) != h for p,h in plan[field].items()): raise ValueError('Frozen file changed')
    for d in plan['deployments'].values():
        for info in (d['server'],d['models']['baseline']):
            if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory,plan,budget); runner.started = started; relations = Relations(runner)
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'fresh_analysis': True, 'budget_before': budget.summary()})
    try:
        path = directory/'fresh-groups.json'
        req = {'system': fresh_embedding.VERSION, 'data': {'snapshot':plan['snapshot'],'snapshot_sha256':sha(plan['snapshot']),'output':str(path)},'schema':{},'max_tokens':1}
        embedded = runner.call('embedding',req,provider=fresh_embedding.generate,maximum=plan['limits']['embedding_seconds'])
        if embedded['sha256'] != sha(path): raise ValueError('Fresh embedding changed')
        with owned_server(plan['deployments']['extraction'],'baseline',directory/'extraction-server'):
            units,sources,coverage = proposals_from_sources(read_json(path),runner)
        req = {'system':source_first_candidates.VERSION,'data':{'units':units,'sources':sources,'threshold':plan['limits']['candidate_threshold']},'schema':{},'max_tokens':1}
        candidates = runner.call('unit-candidates',req,provider=source_first_candidates.generate,maximum=plan['limits']['embedding_seconds'])
        write(directory/'unit-candidates.json',candidates)
        # Existing stable source-count order; budget allocation is not approval.
        proposals = candidates['proposals'][:20]
        write(directory/'nomination-deferred.json', [{'id':p['id'],'reason':'target_ranking_candidate_budget'} for p in candidates['proposals'][20:]])
        alternatives,neighbors = rank(proposals,units,candidates,sources,runner)
        populations = {'baseline':proposals,'alternative':alternatives,'neighborhood':neighbors}
        rows = {name:source_rows(values,plan['membership_policy']) for name,values in populations.items()}
        if sum(map(len,rows.values())) > plan['limits']['core_relations']: raise ValueError('Core relation population exceeds budget')
        write(directory/'core-populations.json', {'proposals':populations,'rows':rows})
        admission_bound = CoreAdmissionBound([r for values in rows.values() for r in values])
        actual = {}
        with owned_server(plan['deployments']['membership'],'baseline',directory/'core-server'):
            for name,values in rows.items():
                actual[name] = relations.judge(values,'core-'+name,admission_bound=admission_bound)
        write(directory/'core-verdicts.json',actual)
        write(directory/'core-admission-bound.json',admission_bound.report())
        left = choose(proposals,rows['baseline'],actual['baseline'],alternatives,rows['alternative'],actual['alternative'])
        right = {'proposals':neighbors,'rows':rows['neighborhood'],'actual':actual['neighborhood']}
        selected = combine(left,right,plan['limits']['profile_candidates'])
        write(directory/'selection.json',selected)
        typed = []; deferred = []
        if selected['proposals']:
            with owned_server(plan['deployments']['profile'],'baseline',directory/'profile-server'):
                for p in selected['proposals']:
                    try: value,reason = profile(p,selected,units,plan['membership_policy'],runner,extra_tokens=plan['profile_extra_tokens'])
                    except (ValueError,TypeError,KeyError,AttributeError) as exc: value,reason = None,'profile_contract_'+type(exc).__name__
                    if value is None: deferred.append({'id':p['id'],'reason':reason})
                    else: typed.append(value)
        mapped = {p['id']:p for p in typed}
        derived = [{**deepcopy(r),'claim':deepcopy(mapped[r['candidate_id']]['claims']['C'])} for r in selected['rows'] if r['candidate_id'] in mapped]
        for r in derived:
            if membership_policy.invocation(plan['membership_policy'],r['text'],r['claim']) != r['request']:
                raise ValueError('Profiling changed core membership target')
        details = membership_policy.bind_rows(plan['membership_policy'],grounded_factory.detail_requests(typed,derived,selected['actual']))
        if len(details) > plan['limits']['detail_relations']: raise ValueError('Detail relation population exceeds budget')
        write(directory/'typed.json', {'proposals':typed,'core_rows':derived,'details':details,'deferred':deferred})
        detail_actual = {}
        if details:
            with owned_server(plan['deployments']['membership'],'baseline',directory/'detail-server'):
                detail_actual = relations.judge(details,'detail')
        write(directory/'detail-verdicts.json',detail_actual); write(directory/'relation-call-map.json',relations.trace)
        admitted,argument_deferred = argument_graph.admit(typed,details,detail_actual); ids = {p['id'] for p in admitted}
        write(directory/'admission.json', {'candidate_ids':sorted(ids),'deferred':argument_deferred})
        bundle = grounded_factory.bundle(admitted,[r for r in derived if r['candidate_id'] in ids],selected['actual'],
            [r for r in details if r['candidate_id'] in ids],detail_actual,expires_at=plan['expires_at'],model=plan['classifier'],documents=plan['documents'])
        packets = grounded_factory.fact_packets(bundle,plan['selections'])
        if packets:
            req = nli_fact_records.invocation(packets)
            result = runner.call('facts',req,provider=evidence_nli.generate,maximum=plan['limits']['fact_seconds'])
            bound = nli_fact_records.records(packets,bundle['model'],result,batch_request=req)
            bundle['checks'] = [{'claim_id':p['claim']['id'],'selections':plan['selections'],'record':r} for p,r in zip(packets,bound,strict=True)]
        compiled = compile_inputs(bundle); write(directory/'bundle.json',bundle); write(directory/'compiled.json',compiled)
        elapsed = time.monotonic()-started
        report = {'artifact_kind':VERSION,'fresh_analysis':True,'fresh_analysis_seconds':elapsed,'within_one_hour':elapsed<=3600,
            'coverage':coverage,'nominated_candidates':{k:len(v) for k,v in populations.items()},
            'profile_candidates':len(selected['proposals']),'typed_candidates':len(typed),'typing_deferred':deferred,
            'detail_relations':len(details),'fact_claims':len(packets),'screened_inputs':len(compiled['profiles']),
            'relation_reuse_within_run':sum(r['reused_within_run'] for r in relations.trace),
            'core_relations_unassessed_by_bound':sum(r['call_sequence'] is None for r in relations.trace),
            'qualified_agents':0,'quality_gate_passed':False,'runtime_reference_labels':False,
            'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
            'budget_after':budget.summary(), 'remaining_gates':['all_actual_input_content','actual_answers','actual_browser','fixed_relation_diagnostic']}
        write(directory/'completed.json',report)
        print({k:v for k,v in report.items() if k not in ('coverage','budget_after')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-started,
            'budget_after':budget.summary(),'quality_gate_passed':False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','run']); parser.add_argument('directory',type=Path)
    parser.add_argument('--snapshot',type=Path); parser.add_argument('--source-config',type=Path)
    parser.add_argument('--graph-config',type=Path); parser.add_argument('--gpu-layers',choices=['all','32'])
    args = parser.parse_args()
    if args.phase == 'prepare':
        if not all((args.snapshot,args.source_config,args.graph_config,args.gpu_layers)):
            parser.error('prepare requires snapshot, source-config, graph-config, gpu-layers')
        prepare(args.directory,args.snapshot,args.source_config,args.graph_config,gpu_layers=args.gpu_layers)
    else: execute(args.directory)
