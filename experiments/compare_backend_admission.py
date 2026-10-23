"""Reuse real proposals, admit originals once, then prepare actual Agents.

Adaptive branch rules are frozen before inference. A completed execution still
needs its separate support/Agent/fact/runtime semantic review and HTTP test.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from commentscope.factory import shared_claims, shared_admission, minimal_pipeline
from commentscope.factory import minimal_membership as mm, candidate_consolidation as cc
from commentscope.factory import fact_checks, raw_membership_verification as verification
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources, normalized, similarity
from commentscope.ingestion import load_snapshot
from commentscope.providers import context_capacity, framed_embedding, evidence_nli, host_resources
from commentscope.providers.exclusive_models import ExclusiveModels
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.completed_shared_proposals import load as completed_proposals
from experiments.completed_model_responses import CompletedResponses, NLI
from experiments.compare_backend_discovery import check_quota, quota_watch, SCOPE, EMBEDDINGS
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.fresh_grounded_pipeline import Runner
from experiments.minimal_factory_pipeline import deployment_check
from experiments.audit_model_compare import file_hash, owned_server
from experiments.corpus_resource_guard import host_observation
from experiments.model_selection_20261016 import observe
from experiments.scoped_discovery_probe import code_hashes
from experiments.sequential_corpus_pipeline import SequentialRunner, runtime_check
from experiments.framed_agent_probe import runtime_probe

VERSION = 'compare-backend-original-admission-20261023-v3'
PROPOSALS = Path('runs/compare-backend-20261023-v1/M1-discovery-v2')
ROOT = Path('runs/compare-backend-20261023-v1')
PRIOR = ROOT/'M1-admission-v1'


def lifetimes(directory,plan,attempt):
    root=directory/'models'/f'{attempt:04}'
    @contextmanager
    def server(sequence):
        target=root/f'llm-{sequence:04}';observation_number=0
        while True:
            check_quota();observation=observe();observation_number+=1
            write(target/'preflight'/f'{observation_number:04}.json',observation)
            if not observation['refusal_reasons']:break
            time.sleep(15)
        with owned_server(plan['deployment'],'baseline',target/'server') as process:yield process
        if (read_json(target/'server/stopped.json')['returncode']!=0 or
                read_json(target/'server/resources/finished.json')['observer_stopped'] is not True):
            raise RuntimeError('Owned server/observer shutdown unconfirmed')
    @contextmanager
    def auxiliary(sequence):
        target=root/f'auxiliary-{sequence:04}'
        with host_resources.watch(target,plan['resource_policy'],host_observation):yield
        if read_json(target/'finished.json')['observer_stopped'] is not True:
            raise RuntimeError('Auxiliary resource observer shutdown unconfirmed')
    return ExclusiveModels(server,auxiliary)


def inputs(plan):
    snapshot = load_snapshot(Path(plan['snapshot'])).snapshot
    fact_checks.live(snapshot.usage.expires_at)
    registry = sources(snapshot, include_video_context=True)
    originals = [registry[sid] for sid in plan['scope_ids']]
    records, proof = completed_proposals(PROPOSALS, deployment=plan['deployment'], originals=originals)
    artifact = read_json(EMBEDDINGS)
    if (artifact['texts_sha256'] != digest({s['id']: s['text'] for s in originals})
            or artifact['model'] != framed_embedding.MODEL
            or artifact['revision'] != framed_embedding.REVISION
            or artifact['local_files_only'] is not True):
        raise ValueError('Exact cached source embeddings required')
    return snapshot, originals, records, proof, artifact['vectors']


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private admission run required')
    previous = read_json(SCOPE); deployment_check(previous['deployment'])
    prior=CompletedResponses(PRIOR,deployment=previous['deployment'])
    paths = [SCOPE, EMBEDDINGS, PROPOSALS/'plan.json', PROPOSALS/'completed.json',
             PROPOSALS/'artifacts/output.json', ROOT/'acceptance-profile.json',
             ROOT/'M1-discovery-v2-review.json', ROOT/'M1-reuse-result.json',
             PRIOR/'plan.json',ROOT/'M1-admission-v1-result.json',
             ROOT/'M1-admission-strategy-reassessment.json']
    plan = {'artifact_kind': VERSION, 'frozen_at': datetime.now(timezone.utc).isoformat(),
        'hypothesis': 'Route/core readiness and independent original admission can expose genuine shared cores without regenerating proposals or repeating source votes. Only actual compiled distinct Agents trigger runtime.',
        'decision': 'If shared support fails, inspect actual source comparisons; if arguments/facts hold, fix that boundary. No new global proposal prompt iteration.',
        'snapshot': previous['snapshot'], 'scope_ids': previous['scope_ids'],
        'deployment': previous['deployment'], 'classifier': previous['classifier'],
        'model_files': previous['model_files'], 'documents': previous['documents'],
        'selections': previous['selections'], 'budget': previous['budget'],
        'limits': previous['limits'], 'resource_policy': previous['resource_policy'],
        'admission_policy': deepcopy(shared_admission.POLICY),
        'candidate_order': 'descending nominee count then candidate ID; nominees never count as support',
        'retrieval': 'Screen nominees+6 nearest across all hypotheses first; then expansion rounds prioritize actual verified support count,2-source cores first. Stop candidate at3 or24 attempted sources; other pairs stay unassessed.',
        'fact_core_policy': 'Fact/uncertain cores retained as deferred, never relabeled; initial opinion-Agents use value/prediction cores. All factual units in actual Agents still use existing fact gates.',
        'resource_policy_application':'Cache processing requires existing basic host policy. Actual Qwen startup waits for unchanged4GiB available/8GiB commit/6400MiB GPU prerequisites; live host guard unchanged. Unknown quota waits before new tasks;<=40 still interrupts immediately.',
        'stop_rule': 'After each>=3-source core, run existing owned arguments/facts/compile on current verified memberships. Stop only after>=2 compiled profiles with a model-checked different/opposed core pair; then run all compiled profiles through3 questions each.',
        'inputs': {str(p): sha(p) for p in paths}, 'code_sha256': code_hashes(),
        'prior_response_cache':str(PRIOR),'prior_cache_proof_sha256':digest(prior.proof),
        'expected_calls': {'new_proposal_calls': 0, 'new_embedding_calls': 0,
            'previous_completed_responses':len(prior.results),
            'previous_unavailable_requests':len(prior.unavailable),
            'candidate_route_maximum': 36, 'candidate_core_maximum': 36,
            'original_comparisons_per_eligible_candidate': [8, 24],
            'own_evidence_calls': 'only positive raw proposals',
            'argument_fact_calls': 'only cores with>=3 independently verified original sources',
            'estimated_initial_gate_prompt_tokens': [10000, 40000],
            'total_is_not_a_new_budget': True},
        'evaluation': {'actual_compiled_agents_minimum': 2, 'distinct_pair_required': True,
            'valid_sources_per_agent_minimum': 3, 'all_counted_supports_reviewed_later': True,
            'zero_false_or_unreviewed_approvals': True, 'runtime_questions_per_compiled_agent': 3,
            'not_final_r5_g3_or_g4': True}, 'quality_gate_passed': False}
    snapshot, originals, records, proof, _ = inputs(plan)
    candidates = shared_claims.candidates(records)
    plan['candidate_sha256'] = digest(candidates)
    plan['candidate_ids'] = [c['id'] for c in candidates]
    plan['proposal_reuse_proof_sha256'] = digest(proof)
    for doc in plan['documents']: fact_checks.live(doc['expires_at'])
    write(directory/'plan.json', plan)
    return plan


def run(directory):
    check_quota()
    with experiment_lock(directory), quota_watch():
        plan = read_json(directory/'plan.json'); plan_hash = sha(directory/'plan.json')
        if plan['artifact_kind'] != VERSION or plan['admission_policy'] != shared_admission.POLICY:
            raise ValueError('Changed admission contract')
        for path, expected in {**plan['inputs'], **plan['code_sha256']}.items():
            if sha(path) != expected: raise ValueError('Frozen input/code changed: '+path)
        deployment_check(plan['deployment'])
        for item in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(item['path']) != item['sha256']: raise ValueError('Model/server changed')
        for path, expected in plan['model_files'].items():
            if file_hash(path) != expected: raise ValueError('Auxiliary model file changed')
        snapshot, originals, records, proof, source_vectors = inputs(plan)
        candidates = shared_claims.candidates(records)
        if digest(candidates) != plan['candidate_sha256'] or digest(proof) != plan['proposal_reuse_proof_sha256']:
            raise ValueError('Completed proposal reuse changed')
        prior=CompletedResponses(Path(plan['prior_response_cache']),deployment=plan['deployment'])
        if digest(prior.proof)!=plan['prior_cache_proof_sha256']:
            raise ValueError('Previous completed-response cache changed')
        if (directory/'completed.json').exists():
            done = read_json(directory/'completed.json')
            if done['plan_sha256'] != plan_hash or done['output_sha256'] != sha(directory/'artifacts/output.json'):
                raise ValueError('Completed admission output changed')
            return done
        pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
            if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
        if pending: raise RuntimeError('Pending calls require process/ledger reconciliation')
        attempt = len(list((directory/'preflight').glob('*.json')))+1
        observed = observe(); write(directory/'preflight'/f'{attempt:04}.json', observed)
        if host_resources.reasons(observed['host'],plan['resource_policy']):
            raise RuntimeError('Existing basic host resources refused cache processing')
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        write(directory/'attempts'/f'{attempt:04}.started.json',
              {'pid': os.getpid(), 'plan_sha256': plan_hash, 'budget_before': budget.summary()})
        started = time.monotonic()

        def save(name, value):
            path = directory/'artifacts'/(name+'.json')
            if path.exists():
                if read_json(path) != value: raise ValueError('Same-plan artifact changed: '+name)
            else: write(path, value)
        save('proposal-reuse', proof)
        save('prior-response-cache',prior.proof)
        try:
            with lifetimes(directory, plan, attempt) as models:
                sequential = SequentialRunner(Runner(directory, plan, budget), models,
                                              directory/'transitions'/f'{attempt:04}')
                checkpoint = CheckpointRunner(sequential, plan['deployment']['runtime'])
                capacity_cache = {}
                def inspect(req):
                    key = digest(req)
                    if key not in capacity_cache:
                        cached=prior.capacity(req)
                        capacity_cache[key] = cached if cached is not None else models.invoke('llm', lambda: context_capacity.measure(req))
                    return deepcopy(capacity_cache[key])
                class LogicalRunner:
                    def call(self, stage, req):
                        check_quota()
                        cached=prior.get(req)
                        if cached is not None:
                            save('prior-response-roles/'+digest([stage,req]),{'role':stage,'request_sha256':digest(req)})
                            return cached
                        measured = inspect(req)
                        if not measured['fits']: raise ValueError('Unsplit model request exceeds context')
                        save('logical-roles/'+digest([stage, req]), {'role': stage, 'request_sha256': digest(req)})
                        result = checkpoint.call('logical-'+digest(req)[:32], req)
                        check_quota()
                        usage = result.get('usage') or {}
                        if usage.get('prompt_tokens',0) > measured['input_tokens']+measured['safety_margin']:
                            raise ValueError('Actual prompt exceeds frozen template allocation')
                        return result
                runner = LogicalRunner()
                texts = {c['id']: c['text'] for c in candidates}
                result=prior.embedding(texts)
                embedding_path=Path(result['output'])
                save('embedding-reuse',result)
                artifact = read_json(embedding_path)
                if (result['sha256'] != sha(embedding_path) or artifact['texts_sha256'] != digest(texts)
                        or artifact['model'] != framed_embedding.MODEL or artifact['revision'] != framed_embedding.REVISION
                        or artifact['local_files_only'] is not True):
                    raise ValueError('Candidate embedding provenance changed')
                cv = normalized(artifact['vectors'], texts); sv = normalized(source_vectors, [s['id'] for s in originals])
                ranking = {c['id']: sorted(sv, key=lambda sid: (-similarity(sv[sid], cv[c['id']]), sid)) for c in candidates}
                save('frozen-source-rankings', {'source_texts_sha256': digest({s['id']:s['text'] for s in originals}),
                    'candidate_sha256': digest(candidates), 'rankings': ranking, 'retrieval_is_not_support': True})
                factories = []; distinct_checks = []; last_factory = None
                def facts(req):
                    check_quota()
                    cached=prior.get(req,provider=NLI)
                    if cached is not None:return cached
                    result=checkpoint.call('facts-'+digest(req)[:24], req, provider=evidence_nli.generate,
                                           maximum=plan['limits']['fact_batch_seconds'])
                    check_quota();return result
                def existing_sources(stage, texts):
                    if stage != 'sources' or digest(texts) != digest({s['id']:s['text'] for s in originals}):
                        raise ValueError('Staged Factory must not regenerate candidate/source embeddings')
                    return deepcopy(source_vectors)
                def on_shared(memberships, outcomes):
                    nonlocal last_factory
                    prefix = f'factory-{len(factories)+1:04}'
                    last_factory = minimal_pipeline.process(snapshot, runner, existing_sources, inspect, facts,
                        model=plan['classifier'], documents=plan['documents'], selections=plan['selections'],
                        scope_ids=plan['scope_ids'], save=lambda name,value:save(prefix+'/'+name,value),
                        discovery_mode='shared', membership_mode='raw', verification_contract=verification.ALIGNED,
                        shared_records=records, shared_memberships=memberships)
                    save(prefix+'/output', last_factory)
                    profiles = last_factory['agent_inputs']['compiled']['profiles']
                    factories.append({'prefix': prefix, 'compiled_agents': len(profiles),
                                      'candidate_ids': [p['candidate_id'] for p in profiles],
                                      'shared_cores': sum(len(o['supported_sources'])>=3 for o in outcomes)})
                    save(prefix+'/summary', factories[-1])
                    for i, left in enumerate(profiles):
                        for right in profiles[i+1:]:
                            pairs = [{'a':left['candidate_id'], 'b':right['candidate_id']}]
                            req = cc.equivalence_request(originals, candidates, memberships, pairs)
                            if not inspect(req)['fits']: continue
                            result = runner.call('distinct-compiled-cores', req)
                            record = cc.bind(originals, candidates, memberships, pairs, result)
                            save(prefix+'/distinct-'+digest(pairs)[:20], record); distinct_checks.append(record)
                            if record['relations'][0]['relation'] in ('different','opposed'): return True
                    return False
                admission = shared_admission.process(originals, candidates, source_vectors, artifact['vectors'],
                    runner, inspect, on_shared=on_shared, save=save)
                runtime = None
                if admission['stop_reason'] == 'downstream_compiled_distinct_agents_ready':
                    runtime = runtime_probe(last_factory['agent_inputs']['bundle'], runner)
                    runtime_check(runtime, last_factory['agent_inputs']['compiled'])
                    save('runtime', runtime)
                output = {'admission': admission, 'factory_attempts': factories, 'last_factory': last_factory,
                          'distinct_checks': distinct_checks, 'runtime': runtime, 'quality_gate_passed': False}
                save('output', output)
            report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash,
                'output_sha256': sha(directory/'artifacts/output.json'),
                'assessed_pairs': len(mm.collect(originals,candidates,admission['memberships'])),
                'shared_cores': sum(len(o['supported_sources'])>=3 for o in admission['outcomes']),
                'compiled_agents': len(last_factory['agent_inputs']['compiled']['profiles']) if last_factory else 0,
                'runtime_turns': len(runtime['turns']) if runtime else 0, 'stop_reason': admission['stop_reason'],
                'new_proposal_calls': 0, 'same_plan_reused_calls': checkpoint.reused,
                'previous_completed_response_hits':prior.hits,'previous_unique_responses_reused':len(prior.used),
                'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary(),
                'semantic_review_required': True, 'quality_gate_passed': False}
            write(directory/'completed.json', report)
            return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json',
                  {'exception': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
                   'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare','run']); parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = prepare(args.directory) if args.action=='prepare' else run(args.directory)
    print({k:result[k] for k in ('artifact_kind','quality_gate_passed')}, flush=True)
