"""Fresh source-isolated discovery diagnostic; no support or quality approval."""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
from shutil import copy2
import time

from commentscope.factory import minimal_claims as mc, fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.context_capacity import measure
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.fresh_grounded_pipeline import Runner
from experiments.minimal_factory_pipeline import BASE, CYCLE, private, deployment_check
from experiments.model_selection_20261016 import observe
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'minimal-discovery-diagnostic-20261017-v6'


def prepare(directory, source_run, mode='free'):
    private(directory); private(source_run)
    if directory.exists(): raise ValueError('Fresh diagnostic directory required')
    if mode not in ('free','literal','contextual','contextual-scoped'): raise ValueError('Known discovery mode required')
    original = read_json(source_run/'plan.json')
    snapshot_path = Path(original['snapshot'])
    if sha(snapshot_path) != original['snapshot_sha256']:
        raise ValueError('Original snapshot changed')
    settings = read_json(CYCLE); deployment = read_json(BASE)['deployment']
    deployment_check(deployment)
    if settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None:
        raise ValueError('Existing uncapped ledger required')
    snapshot = load_snapshot(snapshot_path).snapshot; fact_checks.live(snapshot.usage.expires_at)
    scope = original['scope_ids']; registry = sources(snapshot)
    if not scope or len(set(scope)) != len(scope) or any(sid not in registry for sid in scope):
        raise ValueError('Original complete canonical scope required')
    paths = [source_run/'plan.json', source_run/'completed.json', snapshot_path, BASE, CYCLE]
    plan = {'artifact_kind': VERSION, 'mode':mode, 'snapshot': str(snapshot_path), 'scope_ids': scope,
            'source_run': str(source_run), 'deployment': deployment,
            'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 600},
            'inputs': {str(p): sha(p) for p in paths}, 'code_sha256': code_hashes(),
            'runtime_reference_labels': False, 'cross_run_response_reuse': False,
            'extraction_sources_per_call': 1, 'partial_additional_passes': 1 if mode=='free' else 0,
            'video_context': 'snapshot metadata for reference resolution only',
            'full_factory_run': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    for path, expected in plan['code_sha256'].items():
        if sha(path) != expected: raise ValueError('Code changed while freezing')
        target = directory/'frozen-code'/path
        target.parent.mkdir(parents=True, exist_ok=True); copy2(path, target)
    return {'prepared': True, 'sources': len(scope), 'full_factory_run': False}


def extract(directory, runner, originals, inspect=measure, mode='free'):
    if mode=='contextual-scoped':
        from commentscope.factory.contextual_engine import Engine
        engine=Engine(originals,runner,inspect,save=lambda name,value:write(directory/(name+'.json'),value))
        output=engine.discover()
        write(directory/'engine.json',engine.diagnostics());write(directory/'output.json',output)
        return output
    errors = []; holds = []
    def work(stage, items, build, bind, size):
        if size != 1: raise ValueError('Source-local extraction required')
        results = []
        for item in items:
            req = build([item]); key = stage+'-'+digest(req)[:20]
            capacity = inspect(req)
            if capacity['request_sha256'] != digest(req): raise ValueError('Unbound capacity measurement')
            write(directory/'capacity'/(key+'.json'), capacity)
            if not capacity['fits']:
                holds.append({'source_id': item['id'], 'stage': stage, 'reason': 'context_capacity'})
                continue
            result = runner.call(key, req)
            try:
                bound = bind([item], result)
            except (ValueError, KeyError, TypeError) as exc:
                error = {'source_id': item['id'], 'stage': stage, 'exception': type(exc).__name__,
                         'message': str(exc), 'request_sha256': digest(req), 'result': deepcopy(result)}
                errors.append(error); write(directory/'errors'/(key+'.json'), error)
                if result.get('raw') is None and result.get('errors'):
                    raise RuntimeError('Incomplete transport; inspect process and ledger before recovery')
                continue
            results.append(bound); write(directory/'bound'/(key+'.json'), bound)
        return results
    if mode=='literal':
        from commentscope.factory import literal_discovery
        records = literal_discovery.discover(originals, work,
            save=lambda name,value:write(directory/(name+'.json'),value))
    elif mode=='contextual':
        from commentscope.factory import contextual_propositions
        records=contextual_propositions.discover(originals,work,
            save=lambda name,value:write(directory/(name+'.json'),value))
    elif mode=='free': records = mc.extract_independently(originals, work)
    else: raise ValueError('Known discovery mode required')
    candidates=mc.candidates(records);witnesses=[]
    if mode=='contextual':
        from commentscope.factory import contextual_witness as cw
        from commentscope.factory import contextual_qualifications as cq
        registry={s['id']:s for s in originals};lookup={c['id']:c for c in candidates}
        tasks=[{'id':sid,'candidate_id':c['id']} for c in candidates for sid in sorted(c['nominees'])]
        interpretations={(r['source']['id'],i['node_id']):i for r in records for i in r['interpretations']}
        for task in tasks:
            candidate=lookup[task['candidate_id']];source=registry[task['id']]
            key=(source['id'],candidate['meaning_context']['node_id'])
            witness=cw.identity(source,candidate,interpretations[key]);witnesses.append(witness)
            write(directory/'bound'/('contextual-identity-'+digest(witness)[:20]+'.json'),witness)
        contextual_assessments=[]
        for w in witnesses:
            target=w['candidate']['meaning_context'];source_key=(w['source']['id'],w['node_id'])
            target_key=(target['source']['id'],target['node_id'])
            if source_key in interpretations and source_key==target_key:
                contextual_assessments.append(cq.assessment(w,interpretations[source_key],interpretations[target_key]))
    output = {'extractions': records, 'candidates': candidates, 'errors': errors,
              'capacity_holds': holds,
              'unextracted_source_ids': sorted(set(s['id'] for s in originals)-set(r['source']['id'] for r in records
                  if mode=='free' or r['selection_batches'] or r.get('interpretations'))),
              'quality_gate_passed': False, 'semantic_review_required': True}
    if mode=='contextual':output.update(position_witnesses=witnesses,
        contextual_assessments=contextual_assessments,counted_contextual_supports=0)
    write(directory/'output.json', output)
    return output


def run(directory):
    private(directory)
    with experiment_lock(directory):
        plan = read_json(directory/'plan.json')
        if plan['artifact_kind'] != VERSION or (directory/'started.json').exists():
            raise ValueError('Fresh frozen diagnostic required')
        for group in ('inputs', 'code_sha256'):
            if any(sha(p) != h for p, h in plan[group].items()): raise ValueError('Frozen input/code changed')
        deployment_check(plan['deployment'])
        for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(info['path']) != info['sha256']: raise ValueError('Model/server changed')
        observation = observe(); write(directory/'preflight.json', observation)
        if observation['refusal_reasons']: raise RuntimeError('Resource preflight refused')
        snapshot = load_snapshot(Path(plan['snapshot'])).snapshot; fact_checks.live(snapshot.usage.expires_at)
        registry = sources(snapshot, include_video_context=True)
        originals = [registry[sid] for sid in sorted(plan['scope_ids'])]
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        runner = Runner(directory, plan, budget); started = time.monotonic()
        write(directory/'started.json', {'plan_sha256': sha(directory/'plan.json'), 'budget_before': budget.summary()})
        try:
            with owned_server(plan['deployment'], 'baseline', directory/'server'):
                output = extract(directory, runner, originals, mode=plan['mode'])
            report = {'artifact_kind': VERSION, 'plan_sha256': sha(directory/'plan.json'),
                      'output_sha256': sha(directory/'output.json'), 'execution_complete': True,
                      'sources': len(originals), 'bound_sources':len(originals)-len(output['unextracted_source_ids']),
                      'status_counts': dict(Counter(r['status'] for r in output['extractions'])),
                      'binding_errors': len(output['errors']), 'capacity_holds': len(output['capacity_holds']),
                      'candidates': len(output['candidates']), 'calls': runner.seq,
                      'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary(),
                      'full_factory_run': False, 'quality_gate_passed': False, 'semantic_review_required': True}
            write(directory/'completed.json', report)
            print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
            return report
        except BaseException as exc:
            write(directory/'failed.json', {'exception': type(exc).__name__, 'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path); p.add_argument('--source-run', type=Path, required=True)
    p.add_argument('--mode', choices=['free','literal','contextual','contextual-scoped'], default='free')
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': print(prepare(args.directory, args.source_run, args.mode))
    else: run(args.directory)
