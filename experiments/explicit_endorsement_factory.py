"""Actual whole-proposal endorsement discovery and reviewed Factory composition.

Scans the frozen entire snapshot before inference. Reuses the entire unchanged
accepted prior Factory, never a hand-authored successful source pack. Each new
source requires actual own-only NLI, complete-source audit and direct review.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import sqlite3
from contextlib import closing
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import explicit_endorsements as endorse, minimal_agents as ma
from commentscope.factory import owned_arguments as oa, source_arguments as sa
from commentscope.factory import explicit_discourse as ed, reviewed_source_admission as review_gate
from experiments import source_closed_policy as base

VERSION = 'actual-whole-proposal-endorsement-factory-20261023-v1'
ROOT = base.ROOT
PRIOR = ROOT / 'M1-source-closure-v7'
CACHES = [ROOT / 'M1-source-closure-v13', *base.PRIORS]
FIELDS = ['snapshot', 'scope_ids', 'deployment', 'classifier', 'model_files',
          'documents', 'selections', 'budget', 'limits', 'resource_policy']


def inputs(plan):
    snapshot = base.load_snapshot(Path(plan['snapshot'])).snapshot
    base.fact_checks.live(snapshot.usage.expires_at)
    lookup = base.registry(snapshot, include_video_context=True)
    sources = [lookup[sid] for sid in plan['scope_ids']]
    inventory = endorse.inventory(sources, plan['topic'], plan['alias'])
    previous = Path(plan['previous_factory'])
    done = base.read_json(previous / 'completed.json')
    output = base.read_json(previous / 'artifacts/output.json')
    if (done['plan_sha256'] != base.sha(previous / 'plan.json')
            or done['output_sha256'] != base.sha(previous / 'artifacts/output.json')):
        raise ValueError('Exact terminal prior automatic Factory required')
    factory = output['last_factory']
    if compile_inputs(factory['agent_inputs']['bundle']) != factory['agent_inputs']['compiled']:
        raise ValueError('Prior compiled Factory changed')
    for accepted in factory['accepted']:
        if accepted['record']['source'] != lookup[accepted['source_id']]:
            raise ValueError('Prior accepted original differs from snapshot')
    return snapshot, sources, inventory, factory


def prepare(directory):
    base.check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private run required')
    old = base.read_json(PRIOR / 'plan.json')
    census = base.read_json(base.CENSUS / 'plan.json')
    record = base.read_json(base.CENSUS / 'artifacts/combined-record.json')
    plan = {k: deepcopy(old[k]) for k in FIELDS}
    plan.update(artifact_kind=VERSION, at=datetime.now(timezone.utc).isoformat(),
        scope_ids=census['full_scope_ids'], topic=record['topic'], alias=record['alias'],
        previous_factory=str(PRIOR), prior_caches=[str(p) for p in CACHES],
        bottleneck='One reviewed actual Agent; free-form extraction has produced no second valid Agent.',
        hypothesis='Whole normative proposal plus unambiguous explicit agreement can preserve an actual second policy design without paraphrase or donated parental reasons.',
        selection='Scan every frozen source with the same generic rule before inference; process all discovered groups in parent-ID order. Preserve all accepted prior Factory sources unchanged.',
        comparison='Parent own original entails complete proposal; child own original entails its agreement act. Exact canonical reply edge binds referent separately. Parent is never a child NLI premise.',
        expected_calls={'per_group_Qwen':5, 'per_group_NLI':1, 'runtime':0},
        decision='Only directly reviewed actual sources count. Fewer than two compiled Agents remains failure; otherwise review complete profiles and run six actual answers then HTTP.',
        source_review_contract=review_gate.VERSION, source_review_wait_seconds=600,
        runtime_after_direct_review=True, independent_G3=False, quality_gate_passed=False)
    snapshot, sources, inventory, factory = inputs(plan)
    caches = [base.CompletedResponses(p, deployment=plan['deployment']) for p in CACHES]
    plan['prior_cache_proof_sha256'] = [base.digest(c.proof) for c in caches]
    plan['inventory_sha256'] = base.digest(inventory)
    plan['previous_factory_sha256'] = base.digest(factory)
    files = [Path(__file__), base.CENSUS/'plan.json', base.CENSUS/'artifacts/combined-record.json',
             PRIOR/'plan.json', PRIOR/'completed.json', PRIOR/'artifacts/output.json',
             ROOT/'acceptance-profile.json', Path(plan['snapshot'])]
    for accepted in factory['accepted']:
        rel = Path(accepted['candidate_id']) / (accepted['source_id'] + '.json')
        files.extend(PRIOR/'artifacts'/kind/rel for kind in review_gate.KINDS)
    for prior in CACHES:
        for path in sorted((prior/'semantic-review').glob('*/*.json')):
            review = base.read_json(path)
            files.append(path)
            if review_gate.complete_review(review):
                for evidence, expected in review['files_sha256'].items():
                    if base.sha(evidence) != expected:
                        raise ValueError('Prior review evidence changed')
                    files.append(Path(evidence))
    plan['inputs'] = {str(p): base.sha(p) for p in files}
    with closing(sqlite3.connect(Path(plan['budget']['ledger']).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        blocked = db.execute('SELECT id,request_sha,state FROM calls WHERE id IN (6974,7119)').fetchall()
    if len(blocked) != 2 or any(r[2] != 'interrupted' for r in blocked):
        raise ValueError('Interrupted requests must remain unavailable')
    plan['unavailable_requests'] = {r[1]: r[0] for r in blocked}
    plan['code_sha256'] = base.code_hashes()
    base.deployment_check(plan['deployment'])
    base.write(directory/'plan.json', plan)
    base.write(directory/'frozen-inventory.json', inventory)
    return {'prepared':True, 'sources':len(sources), 'groups':len(inventory['groups']),
            'prior_agents':len(factory['agent_inputs']['compiled']['profiles']), 'new_model_calls':0}


def run(directory):
    base.check_quota()
    with base.experiment_lock(directory), base.quota_watch():
        plan = base.read_json(directory/'plan.json')
        if plan['artifact_kind'] != VERSION or plan['source_review_contract'] != review_gate.VERSION:
            raise ValueError('Endorsement experiment contract changed')
        for field in ['inputs', 'code_sha256', 'model_files']:
            for path, expected in plan[field].items():
                if base.sha(path) != expected:
                    raise ValueError('Frozen input changed: '+path)
        snapshot, sources, inventory, previous = inputs(plan)
        caches = [base.CompletedResponses(Path(p), deployment=plan['deployment']) for p in plan['prior_caches']]
        if (base.digest(inventory) != plan['inventory_sha256']
                or base.digest(previous) != plan['previous_factory_sha256']
                or [base.digest(c.proof) for c in caches] != plan['prior_cache_proof_sha256']):
            raise ValueError('Exact input or response-cache proof changed')
        if (directory/'started.json').exists():
            raise RuntimeError('Existing attempt; reconcile without implicit retry')
        budget = base.InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        base.write(directory/'started.json', {'pid':os.getpid(), 'plan_sha256':base.sha(directory/'plan.json')})
        started = time.monotonic()
        def boundary():
            base.check_quota()
            if (directory/'stop-after-checkpoint').exists():
                raise RuntimeError('Graceful checkpoint stop requested')
        def save(name, value):
            path = directory/'artifacts'/(name+'.json')
            if path.exists():
                if base.read_json(path) != value:
                    raise ValueError('Immutable artifact changed: '+name)
            else:
                base.write(path, value)
        queue = base.SourceReviewQueue(directory, [Path(p) for p in plan['prior_caches']], boundary,
                                      wait_seconds=plan['source_review_wait_seconds'])
        accepted = []; decisions = []; statuses = []; candidates = deepcopy(previous['candidates'])
        cores = deepcopy(previous['cores']); errors = []
        try:
            # Byte-identical automatic prior artifacts; review reuse must still
            # pass the complete original/draft/four-file binding before counting.
            for item in previous['accepted']:
                rel = Path(item['candidate_id'])/(item['source_id']+'.json')
                for kind in review_gate.KINDS:
                    target = directory/'artifacts'/kind/rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(plan['previous_factory'])/'artifacts'/kind/rel, target)
                status = base.read_json(directory/'artifacts/source-status'/rel)
                packet, review = queue(item, status)
                decision = review_gate.bind(item, packet, review)
                decisions.append(decision); statuses.append(status)
                save('admission-reviews/'+str(rel.with_suffix('')), decision)
                if not decision['countable']:
                    raise ValueError('Prior accepted source no longer directly passes')
                accepted.append(deepcopy(item))
            for i, cache in enumerate(caches):
                save('prior-response-cache/'+str(i), cache.proof)
            with base.lifetimes(directory, plan, 1) as models:
                sequential = base.SequentialRunner(base.Runner(directory, plan, budget), models, directory/'transitions/0001')
                checkpoint = base.CheckpointRunner(sequential, plan['deployment']['runtime'])
                def call(role, req, *, nli=False):
                    boundary(); key = base.digest(req)
                    if key in plan['unavailable_requests']:
                        raise ValueError('Prior interrupted request cannot be repeated')
                    for cache in caches:
                        result = cache.get(req, provider=base.NLI) if nli else cache.get(req)
                        if result is not None:
                            save('prior-response-roles/'+base.digest([role, req]), {'role':role, 'request_sha256':key})
                            return result
                    save('logical-roles/'+base.digest([role, req]), {'role':role, 'request_sha256':key})
                    if nli:
                        result = checkpoint.call('classifier-'+key[:24], req, provider=base.evidence_nli.generate,
                                                 maximum=plan['limits']['fact_batch_seconds'])
                    else:
                        capacity = models.invoke('llm', lambda:base.context_capacity.measure(req))
                        save('admission-capacity/'+key, capacity)
                        if not capacity['fits']:
                            raise ValueError('Complete actual request exceeds capacity')
                        result = checkpoint.call('logical-'+key[:32], req)
                        if (result.get('usage') or {}).get('prompt_tokens',0)>capacity['input_tokens']+capacity['safety_margin']:
                            raise ValueError('Actual request exceeded allocation')
                    boundary(); return result
                for group in inventory['groups']:
                    candidate = endorse.candidate(group); cid = candidate['id']
                    candidates.append(candidate)
                    core = oa.bind_core(candidate, call('whole-proposal-core', oa.core_request(candidate)))
                    cores.append(core); save('cores/'+cid, core)
                    graph = ed.parse(group['parent']); node = graph['nodes'][0]
                    metadata = oa.bind_metadata(graph, node, call('whole-parent-metadata', oa.metadata_request(graph, node)))
                    save('parent-metadata/'+cid, metadata)
                    request = endorse.invocation(group)
                    response = call('own-position-or-agreement', request, nli=True)
                    save('endorsement-comparison/'+cid, {'request':request, 'response':response})
                    for source in [group['parent'], *group['children']]:
                        sid = source['id']; prefix = cid+'/'+sid
                        status = {'source_id':sid, 'candidate_id':cid, 'state':'held', 'reasons':[], 'semantic_approval':False}
                        batch = endorse.bind_batch(group, request, response, [sid]); save('memberships/'+prefix, batch)
                        if batch['memberships'][0]['relation'] != 'supported':
                            status['reasons'] = ['own_position_or_agreement_not_supported']
                        elif any(a['source_id'] == sid for a in accepted):
                            status['reasons'] = ['already_counted_for_prior_core']
                        else:
                            declared = endorse.declare(group, batch, core, metadata, sid)
                            save('declarations/'+prefix, declared)
                            linked = sa.bind_links(declared); tasks = sa.audit_tasks([linked], [core])
                            audit = sa.bind_audit([linked], [core], tasks,
                                call('whole-source-coverage', sa.audit_request([linked], [core], tasks)))
                            draft = ma.prepare(snapshot, [candidate], [batch], [linked], [core], [audit],
                                model=plan['classifier'], documents=plan['documents'], _draft_single_source=True)
                            if draft['compiled']['profiles']:
                                raise ValueError('Private source draft exposed public Agent')
                            if (draft['argument_holds'] or not draft['bundle']['candidates']
                                    or any(not d['eligible'] for d in draft['compiled']['claim_decisions'].values())):
                                status['reasons'] = ['whole_source_audit_or_core_not_eligible']
                            elif any(c['kind']=='fact' for c in draft['bundle']['claims']):
                                raise ValueError('Normative proposal introduced an unverified empirical fact')
                            else:
                                save('source-fact-closure/'+prefix, {'checks':[], 'draft':draft})
                                status['state'] = 'model_closed_pending_semantic_review'
                                save('source-status/'+prefix, status)
                                item = {'source_id':sid, 'candidate_id':cid, 'membership':batch, 'record':linked,
                                    'core':core, 'audit':audit, 'checks':[], 'draft_sha256':base.digest(draft), 'semantic_approval':False}
                                packet, review = queue(item, status)
                                decision = review_gate.bind(item, packet, review); decisions.append(decision)
                                save('admission-reviews/'+prefix, decision)
                                if decision['countable']:
                                    accepted.append(item)
                        statuses.append(status); save('source-status/'+prefix, status)
                        save('progress/'+f'{len(statuses):04}', {'last_source':status, 'accepted_sources':len(accepted)})
                retained = {a['candidate_id'] for a in accepted}
                final = ma.prepare(snapshot, [c for c in candidates if c['id'] in retained],
                    [a['membership'] for a in accepted], [a['record'] for a in accepted],
                    [c for c in cores if c['candidate']['id'] in retained],
                    [audit for a in accepted for audit in a.get('audits', [a['audit']])],
                    model=plan['classifier'], documents=plan['documents'], checks=[c for a in accepted for c in a['checks']])
                save('agent-inputs', final)
                factory = {'artifact_kind':VERSION, 'candidates':candidates, 'accepted':accepted, 'cores':cores,
                    'agent_inputs':final, 'source_scope':len(sources), 'source_statuses':statuses,
                    'census_status':[{'source_id':s['id'], 'closed_candidate_ids':[a['candidate_id'] for a in accepted if a['source_id']==s['id']]} for s in sources],
                    'outcomes':[{'candidate_id':c['id'], 'closed_source_ids':[a['source_id'] for a in accepted if a['candidate_id']==c['id']]} for c in candidates],
                    'previous_factory':{'path':plan['previous_factory'], 'sha256':base.digest(previous), 'all_accepted_reused':True},
                    'inventory_sha256':base.digest(inventory), 'errors':errors, 'holds':[], 'review_before_count':True,
                    'direct_source_reviews':decisions, 'semantic_review_required':True, 'quality_gate_passed':False}
                save('output', {'last_factory':factory, 'admission':factory, 'distinct_checks':[], 'runtime':None, 'quality_gate_passed':False})
            report = {'artifact_kind':VERSION, 'plan_sha256':base.sha(directory/'plan.json'),
                'output_sha256':base.sha(directory/'artifacts/output.json'), 'compiled_agents':len(final['compiled']['profiles']),
                'accepted_sources':len(accepted), 'runtime_turns':0, 'elapsed_seconds':time.monotonic()-started,
                'semantic_review_required':True, 'quality_gate_passed':False}
            base.write(directory/'completed.json', report); return report
        except BaseException as exc:
            base.write(directory/'failed.json', {'exception':type(exc).__name__, 'message':str(exc), 'elapsed_seconds':time.monotonic()-started})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run']); parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(prepare(args.directory) if args.action=='prepare' else run(args.directory), flush=True)
