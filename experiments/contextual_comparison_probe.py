"""Fresh cross-source contextual contracts; synthetic controls, not full G1."""
import argparse
from copy import deepcopy
from pathlib import Path
from shutil import copy2
import time

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import contextual_witness as cw, contextual_qualifications as cq
from commentscope.factory import candidate_consolidation as cc, literal_discovery as ld, fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.context_capacity import measure
from commentscope.storage import write_json_exclusive as write
from experiments.minimal_discovery_probe import extract
from experiments.minimal_factory_pipeline import BASE,CYCLE,private,deployment_check
from experiments.audit_model_compare import owned_server,file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.model_selection_20261016 import observe
from experiments.scoped_discovery_probe import code_hashes

VERSION='contextual-comparison-diagnostic-20261017-v6'


def prepare(directory,controls,mode='comparison'):
    private(directory);private(controls)
    if directory.exists():raise ValueError('Fresh diagnostic required')
    if mode not in ('comparison','scoped-literal','scoped-semantic'):raise ValueError('Unknown contextual diagnostic mode')
    data=read_json(controls)
    if set(data)!={'sources','membership_pairs','equivalence_pairs'}:raise ValueError('Only unlabeled control inputs allowed')
    mc.source_index(data['sources']);deployment=read_json(BASE)['deployment'];deployment_check(deployment)
    settings=read_json(CYCLE)
    if settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None:raise ValueError('Uncapped current ledger required')
    plan={'artifact_kind':VERSION,'mode':mode,'controls':str(controls),'deployment':deployment,
        'budget':{k:settings[k] for k in ('cycle_id','ledger')},'limits':{'analysis_seconds':None,'call_seconds':600},
        'inputs':{str(p):sha(p) for p in (controls,BASE,CYCLE)},'code_sha256':code_hashes(),
        'runtime_reference_labels':False,'cross_run_response_reuse':False,'full_factory_run':False,'quality_gate_passed':False}
    write(directory/'plan.json',plan)
    for path,h in plan['code_sha256'].items():
        if sha(path)!=h:raise ValueError('Code changed while freezing')
        target=directory/'frozen-code'/path;target.parent.mkdir(parents=True,exist_ok=True);copy2(path,target)
    return {'prepared':True,'sources':len(data['sources']),'membership_pairs':len(data['membership_pairs']),
            'equivalence_pairs':len(data['equivalence_pairs'])}


def component(directory,runner,controls,inspect=measure):
    discovery=extract(directory/'discovery',runner,controls['sources'],inspect=inspect,mode='contextual')
    sources=controls['sources'];registry=mc.source_index(sources);candidates=discovery['candidates']
    source_records={r['source']['id']:r for r in discovery['extractions']}
    interpretations={(r['source']['id'],i['node_id']):i for r in discovery['extractions'] for i in r['interpretations']}
    lookup={(c['meaning_context']['source']['id'],c['meaning_context']['node_id']):c for c in candidates}
    errors=[];holds=[];shapes={};comparisons={};attempted=set();called=set()
    nominations=mm.bind_contextual(sources,candidates,discovery['contextual_assessments'])
    supported={r['candidate_id'] for r in nominations['memberships'] if r['relation']=='supported'}

    def resolve(address):
        sid,index=address
        record=source_records[sid];node=ld.roots(record['graph'])[index]
        return lookup.get((sid,node['id']))

    def call(stage,req):
        key=stage+'-'+digest(req)[:20];capacity=inspect(req)
        if key in called:raise ValueError('Request already attempted; no diagnostic retries')
        called.add(key)
        if capacity['request_sha256']!=digest(req):raise ValueError('Unbound context measurement')
        write(directory/'capacity'/(key+'.json'),capacity)
        if not capacity['fits']:
            holds.append({'stage':stage,'request_sha256':digest(req),'reason':'context_capacity'})
            raise ValueError('Diagnostic context capacity')
        result=runner.call(key,req)
        if result.get('raw') is None and result.get('errors'):
            raise RuntimeError('Incomplete transport; inspect live process and ledger')
        return result

    def compare(sid,target):
        key=(sid,target['id'])
        if key in comparisons:return comparisons[key]
        if key in attempted:raise ValueError('Prior comparison attempt failed; do not repeat it')
        attempted.add(key)
        source=registry[sid];w=cw.bind(source,target,call('position',cw.request(source,target)))
        target_context=target['meaning_context'];source_key=(sid,w['node_id'])
        target_key=(target_context['source']['id'],target_context['node_id'])
        a=None
        if source_key in interpretations and target_key in interpretations:
            shape=None;checks=[]
            if w['relation']=='supported':
                if target['id'] not in shapes:
                    shapes[target['id']]=None
                    shapes[target['id']]=cq.bind_shape(target,call('qualification-inventory',cq.shape_request(target)))
                shape=shapes[target['id']]
                if shape is None:raise ValueError('Prior qualification inventory failed')
                if shape['literal_inventory']['status']=='complete':
                    for detail in shape['literal_inventory']['details']:
                        checks.append(cq.bind_detail(w,shape,detail,
                            call('qualification-detail',cq.detail_request(w,shape,detail))))
            a=cq.assessment(w,interpretations[source_key],interpretations[target_key],shape,checks)
        result={'source_id':sid,'candidate_id':target['id'],'witness':w,'assessment':a}
        comparisons[key]=result;write(directory/'comparisons'/(digest(key)+'.json'),result)
        return result

    memberships=[]
    for pair in controls['membership_pairs']:
        target=resolve(pair['target'])
        if target is None:
            holds.append({'stage':'membership','pair':pair,'reason':'target_not_nominated'});continue
        try:
            result=compare(pair['source_id'],target)
            batch=mm.bind_contextual(sources,[target],[result['assessment']]) if result['assessment'] else None
            memberships.append({'pair':pair,'comparison':result,'batch':batch})
        except (ValueError,KeyError,TypeError) as exc:
            errors.append({'stage':'membership','pair':pair,'exception':type(exc).__name__,'message':str(exc)})
    equivalences=[]
    for pair in controls['equivalence_pairs']:
        left,right=resolve(pair['a']),resolve(pair['b'])
        if left is None or right is None or any(c['id'] not in supported for c in (left,right)):
            holds.append({'stage':'equivalence','pair':pair,'reason':'own_candidate_not_confirmed'});continue
        pairs=[dict(zip(('a','b'),sorted((left['id'],right['id']))))]
        try:
            response=call('equivalence',cc.equivalence_request(sources,candidates,[nominations],pairs));proofs=[]
            preliminary=cc.bind(sources,candidates,[nominations],pairs,response)
            if preliminary['relations'][0]['model_relation']=='equivalent':
                for a,b in ((left,right),(right,left)):
                    context=a['meaning_context'];result=compare(context['source']['id'],b)
                    if result['assessment'] and result['witness']['node_id']==context['node_id']:
                        proofs.append({'from_candidate_id':a['id'],'to_candidate_id':b['id'],'assessment':result['assessment']})
                    else:holds.append({'stage':'equivalence-direction','pair':pair,'reason':'exact_left_position_unconfirmed'})
            bound=cc.bind(sources,candidates,[nominations],pairs,response,contextual_assessments=proofs)
            equivalences.append({'pair':pair,'record':bound})
        except (ValueError,KeyError,TypeError) as exc:
            errors.append({'stage':'equivalence','pair':pair,'exception':type(exc).__name__,'message':str(exc)})
    result={'discovery':discovery,'nominations':nominations,'memberships':memberships,'equivalences':equivalences,
        'comparisons':list(comparisons.values()),'shapes':list(shapes.values()),'errors':errors,'holds':holds,
        'counted_corpus_supports':0,'semantic_review_required':True,'full_factory_run':False,'quality_gate_passed':False}
    write(directory/'output.json',result)
    return result


def scoped_component(directory,runner,controls,inspect=measure,semantic=False):
    """The diagnostic uses the same scope and comparison engine as Factory."""
    from commentscope.factory.contextual_engine import Engine
    engine=Engine(controls['sources'],runner,inspect,
        save=lambda name,value:write(directory/(name+'.json'),value))
    discovery=engine.discover();write(directory/'discovery'/'output.json',discovery)
    records={r['source']['id']:r for r in engine.records}
    lookup={(c['meaning_context']['source']['id'],c['meaning_context']['node_id']):c for c in engine.candidates}
    def resolve(address):
        sid,index=address;node=ld.roots(records[sid]['graph'])[index]
        return lookup.get((sid,node['id']))
    memberships=[]
    for pair in controls['membership_pairs']:
        target=resolve(pair['target'])
        result=engine.support(pair['source_id'],target,semantic=semantic) if target else {
            'assessments':[],'batch':None,'accepted':False,'semantic_relation':'unassessed'}
        memberships.append({'pair':pair,**result})
    equivalences=[]
    for pair in controls['equivalence_pairs']:
        left,right=resolve(pair['a']),resolve(pair['b'])
        if not left or not right or any(c['id'] not in engine.scopes for c in (left,right)):
            engine.holds.append({'stage':'equivalence','pair':pair,'reason':'operand_scope_unavailable'});continue
        pairs=[dict(zip(('a','b'),sorted((left['id'],right['id']))))]
        for bound in engine.equivalences(pairs,semantic=semantic):
            equivalences.append({'pair':pair,'record':bound})
    state=engine.diagnostics()
    result={'discovery':discovery,'nominations':engine.nominations,'scopes':state['scopes'],
        'memberships':memberships,'equivalences':equivalences,'errors':engine.errors,'holds':engine.holds,
        'comparisons':state['comparisons'],'shapes':state['shapes'],
        'completed_request_reuse':state['completed_request_reuse'],
        'comparison_model_calls':sum(stage.startswith('scoped-') for stage in engine.call_stages),
        'counted_corpus_supports':0,'semantic_review_required':True,
        'full_factory_run':False,'quality_gate_passed':False,
        'scope':'shared Factory contextual comparison component'}
    write(directory/'output.json',result);return result


def run(directory):
    private(directory)
    with experiment_lock(directory):
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION or (directory/'started.json').exists():raise ValueError('Fresh frozen diagnostic required')
        for group in ('inputs','code_sha256'):
            if any(sha(p)!=h for p,h in plan[group].items()):raise ValueError('Frozen code/input changed')
        deployment_check(plan['deployment'])
        for info in (plan['deployment']['server'],plan['deployment']['models']['baseline']):
            if file_hash(info['path'])!=info['sha256']:raise ValueError('Model/server changed')
        observation=observe();write(directory/'preflight.json',observation)
        if observation['refusal_reasons']:raise RuntimeError('Resource preflight refused')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        runner=Runner(directory,plan,budget);start=time.monotonic()
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json'),'budget_before':budget.summary()})
        try:
            with owned_server(plan['deployment'],'baseline',directory/'server'):
                if plan['mode'].startswith('scoped-'):
                    output=scoped_component(directory,runner,read_json(plan['controls']),semantic=plan['mode']=='scoped-semantic')
                else:output=component(directory,runner,read_json(plan['controls']))
            report={'artifact_kind':VERSION,'execution_complete':True,'calls':runner.seq,
                'elapsed_seconds':time.monotonic()-start,'budget_after':budget.summary(),
                'output_sha256':sha(directory/'output.json'),'discovery_errors':len(output['discovery']['errors']),
                'errors':len(output['errors']),'holds':len(output['holds']),
                'full_factory_run':False,'quality_gate_passed':False,'semantic_review_required':True}
            write(directory/'completed.json',report);print({k:v for k,v in report.items() if k!='budget_after'},flush=True)
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'budget_after':budget.summary()});raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('directory',type=Path);p.add_argument('--controls',type=Path,required=True)
    p.add_argument('--mode',choices=('comparison','scoped-literal','scoped-semantic'),default='comparison')
    p=sub.add_parser('run');p.add_argument('directory',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':print(prepare(args.directory,args.controls,args.mode))
    else:run(args.directory)
