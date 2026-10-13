"""One local, fresh snapshot-to-screened-input run, without runtime labels.

Explicit diagnostic mode preserves a failed/partial source measurement while
allowing a product integration experiment. Neither mode approves output. Agents need their
separate final audit and answer/latency evaluation. No artifact replay is counted
as fresh analysis; errors and elapsed deadlines remain explicit failures.
Run using the local clustering venv (embedding and NLI dependencies installed).
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.runtime import request
from commentscope.factory import scoped_discovery as discovery
from commentscope.factory import membership_policy
from commentscope.factory import product_evaluation
from commentscope.factory import source_first
from commentscope.factory import grounded_factory as factory, perspective_typing as typing
from commentscope.factory import nli_fact_records as records
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot
from commentscope.providers import fresh_embedding, evidence_nli
from commentscope.providers import source_first_candidates
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import atomic_discovery_probe as atomic, fact_evidence_probe as base
from experiments.audit_model_compare import owned_server, file_hash
from experiments.membership_checkpoint import checkpoint
from experiments.scoped_discovery_probe import code_hashes


def prepare(directory, snapshot, source_gate, proposal_plan, evidence_plan, nli_records, *, purpose='qualified_configuration', algorithm='raw-core-0.1'):
    if directory.exists(): raise ValueError('Never overwrite a run')
    gate=checkpoint(source_gate)
    evaluation=product_evaluation.execution_state(gate,purpose)
    if algorithm not in ('raw-core-0.1',source_first.VERSION):
        raise ValueError('Explicit known candidate algorithm required')
    if algorithm==source_first.VERSION and purpose!='product_diagnostic':
        raise ValueError('New source-first algorithm requires diagnostic evaluation')
    membership=read_json(source_gate/'plan.json'); proposal=read_json(proposal_plan)
    if membership.get('membership_guard') is not None:
        raise ValueError('Experimental guarded policy is not bound to the fresh runtime')
    policy=membership_policy.from_rows(membership['rows'])
    evidence=read_json(evidence_plan); classifier=read_json(nli_records)['model']
    loaded=load_snapshot(snapshot); live(loaded.snapshot.usage.expires_at)
    if len(loaded.snapshot.comments)>1000: raise ValueError('MVP comment cap exceeded')
    for deployment in [membership,proposal]:
        for info in [deployment['models']['baseline'],deployment['server']]:
            if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    from commentscope.cluster_baseline import MODEL as EMBED_MODEL, REVISION as EMBED_REV
    from commentscope.providers.local_nli import MODEL as NLI_MODEL, REVISION as NLI_REV
    # Resolve only already cached model files. No download or remote code.
    hub=Path('/home/taeng/.cache/huggingface/hub')
    model_files={}
    for name,revision in [(EMBED_MODEL,EMBED_REV),(NLI_MODEL,NLI_REV)]:
        root=hub/('models--'+name.replace('/','--'))/'snapshots'/revision
        if not root.is_dir(): raise ValueError('Required local model cache missing')
        model_files.update({str(p):sha(p) for p in root.rglob('*') if p.is_file()})
    classifier['runtime_sha256']=digest({p:sha(p) for p in ['src/commentscope/providers/evidence_nli.py','src/commentscope/providers/local_nli.py']})
    nli_weight=hub/('models--'+NLI_MODEL.replace('/','--'))/'snapshots'/NLI_REV/'model.safetensors'
    if sha(nli_weight)!=classifier['weights_sha256']: raise ValueError('Classifier weights changed')
    paths=[snapshot,source_gate/'plan.json',source_gate/'started.json',proposal_plan,evidence_plan,nli_records]
    # Bind partial as well as complete source measurements, without fabricating
    # completion records. The runtime receives no labels or repair decisions.
    paths += [source_gate/name for name in ('completed.json','report.json','early-stopped.json') if (source_gate/name).exists()]
    paths += [source_gate/(row['id']+'.json') for row in membership['rows'] if (source_gate/(row['id']+'.json')).exists()]
    reference=Path(membership['reference_source'])
    paths += [reference/'references.json',reference/'reference-frozen.json']
    plan={'artifact_kind':'fresh-grounded-pipeline-0.3','snapshot':str(snapshot),
          'evaluation':evaluation,'candidate_algorithm':algorithm,
          'membership_policy':policy,
          'expires_at':loaded.snapshot.usage.expires_at,'code_sha256':code_hashes(),
          'inputs':{str(p):sha(p) for p in paths},'model_files':model_files,
          'deployments':{'proposal':{k:deepcopy(proposal[k]) for k in ['server','models','runtime']},
                         'membership':{k:deepcopy(membership[k]) for k in ['server','models','runtime']}},
          'classifier':classifier,'documents':[evidence['document']],'selections':evidence['selections'],
          'limits':{'analysis_seconds':3600,'groups':20,'min_sources':3,'call_seconds':90,'embedding_seconds':300,'fact_seconds':240,
                    'source_analysis_seconds':1800,'candidate_threshold':.45,'source_request_bytes':27000},
          'budget':{'cycle_id':base.CYCLE,'ledger':str(base.DEFAULT_BUDGET)},
          'retrieval_scope':'Configured frozen Kela evidence library; no universal retrieval',
          'source_configuration_gate':{k:v for k,v in gate.items() if k!='unexecuted_evaluation'},
          'quality_gate_passed':False,'runtime_reference_labels':False}
    if algorithm==source_first.VERSION:
        plan['deployments']['proposal']['runtime']['max_tokens']=1200
        plan['source_configuration_gate_scope']='Historical fixed100 membership deployment diagnostic; different generated targets are not a matched quality improvement.'
    write(directory/'plan.json',plan)
    print({'prepared':True,'fresh_embedding':True,'runtime_labels':False},flush=True)


class Runner:
    def __init__(self,directory,plan,budget,*,clock=time.monotonic):
        self.directory=directory; self.plan=plan; self.budget=budget; self.clock=clock
        self.started=clock(); self.plan_sha=sha(directory/'plan.json'); self.seq=0

    def timeout(self,maximum):
        remaining=self.plan['limits']['analysis_seconds']-(self.clock()-self.started)
        if remaining<=3: raise TimeoutError('Fresh analysis deadline reached')
        return min(maximum,remaining-3)

    def call(self,stage,req,*,provider=None,maximum=None):
        self.seq+=1; prefix=f'{self.seq:04}-{stage}'
        timeout=self.timeout(maximum or self.plan['limits']['call_seconds'])
        write(self.directory/'calls'/(prefix+'.request.json'),{'request':req,'request_sha256':digest(req),
              'plan_sha256':self.plan_sha,'timeout_seconds':timeout})
        def invoke(s,d,c):
            kwargs={} if provider is None else {'provider':provider}
            return self.budget.call(req,self.plan_sha,timeout_seconds=timeout,**kwargs)
        if provider is not None:
            result=invoke(None,None,None)
        else:
            try:result=request(req['system'],req['data'],req['schema'],invoke)
            except BudgetExhausted:raise
            except RuntimeError:
                result={'raw':None,'output':None,'errors':['bounded_call_failed'],'seconds':None,'usage':None}
        write(self.directory/'calls'/(prefix+'.result.json'),result)
        print({'stage':stage,'call':self.seq,'elapsed_seconds':round(self.clock()-self.started,2)},flush=True)
        return result


def proposals_from_groups(raw,runner):
    groups=sorted((g for g in raw['clusters'] if len(g['members'])>=3),key=lambda g:(-len(g['members']),g['id']))[:20]
    proposals=[];deferred=[]
    for group in groups:
        sources={sid:raw['sources'][sid]['text'] for sid in group['members']}
        req=atomic.invocation(sources)
        if len(json.dumps(req).encode())>27000:
            deferred.append({'id':group['id'],'reason':'request_size_budget'});continue
        result=runner.call('proposal',req);value=result['output']
        try:
            if result['errors'] or not isinstance(value,dict):raise ValueError('proposal_error')
            if value=={'decision':'no_claim'}:
                deferred.append({'id':group['id'],'reason':'no_claim'});continue
            if set(value)!={'decision','text','anchor_id','quote'} or value['decision']!='candidate':raise ValueError('proposal_contract')
            shaped={'claims':[{'id':'C','text':value['text'],'kind':'fact','scope':{'entity':'','time':'','conditions':''},
                              'requires':[],'anchor_id':value['anchor_id'],'quote':value['quote']}]}
            claims=discovery.validate_proposal(shaped,sources)
            proposals.append({'id':group['id'],'claims':claims,'sources':sources})
        except (ValueError,KeyError,TypeError):deferred.append({'id':group['id'],'reason':'proposal_contract'})
    return proposals,deferred


def proposals_from_sources(raw,runner):
    """One source-only analysis per scheduled source; no prompt repairs."""
    selected=source_first.schedule(raw,runner.plan['limits']['groups'])
    write(runner.directory/'source-analysis-plan.json',{
        'algorithm':source_first.VERSION,'source_order':selected,'parent_context':'not_supplied',
        'raw_sha256':sha(runner.directory/'fresh-groups.json'),'runtime_reference_labels':False})
    results=[];units=[];skipped=[]
    for sid in selected:
        if runner.clock()-runner.started>=runner.plan['limits']['source_analysis_seconds']:
            skipped.append(sid);continue
        text=raw['sources'][sid]['text'];req=source_first.invocation(text)
        if len(json.dumps(req).encode())>runner.plan['limits']['source_request_bytes']:
            record={'source_id':sid,'source_sha256':digest(text),'status':'unprocessed_size_budget','units':[],'errors':[]}
        else:
            record=source_first.bind(sid,text,runner.call('source-extraction',req))
        write(runner.directory/'source-results'/(digest(sid)+'.json'),record)
        results.append(record);units.extend(record['units'])
    # The registry also retains duplicate/empty originals for provenance.
    # Clusters partition the canonical nonempty embedding population.
    canonical={sid for group in raw['clusters'] for sid in group['members']}
    if not canonical <= raw['sources'].keys():
        raise ValueError('Canonical population contains unknown source')
    excluded=sorted(canonical-set(selected))
    coverage={'version':'source-coverage-0.2','registry_source_count':len(raw['sources']),
              'canonical_available':len(canonical),'scheduled':len(selected),
              'noncanonical_or_empty':sorted(set(raw['sources'])-canonical),
              'source_records':len(results),'model_calls':sum(r['status']!='unprocessed_size_budget' for r in results),
              'valid_units':len(units),'unprocessed_budget':skipped,'not_scheduled':excluded,
              'unprocessed_size_budget':[r['source_id'] for r in results if r['status']=='unprocessed_size_budget'],
              'failed_sources':[r['source_id'] for r in results if r['errors']],
              'semantic_approval':False}
    write(runner.directory/'source-analysis.json',{'records':results,'coverage':coverage})
    return units,{sid:raw['sources'][sid]['text'] for sid in selected},coverage


def source_rows(proposals,policy):
    membership_policy.validate(policy)
    queues=[];rows=[]
    for proposal in proposals:
        queue=[]
        for sid,text in sorted(proposal['sources'].items(),key=lambda x:digest(x[0])):
            claim=proposal['claims']['C'];req=membership_policy.invocation(policy,text,claim)
            queue.append({'candidate_id':proposal['id'],'source_id':sid,'text':text,'claim':claim,
                          'request':req,'request_sha256':digest(req)})
        queues.append(queue)
    while any(queues):
        for queue in queues:
            if queue:rows.append({'id':f'J{len(rows)+1:03}',**queue.pop(0)})
    return rows


def classify(proposals,rows,actual,runner,*,typer=typing):
    policy=membership_policy.from_rows(rows) if rows else None
    typed=[];deferred=[]
    for proposal in proposals:
        members={r['source_id']:r['text'] for r in rows if r['candidate_id']==proposal['id'] and actual[r['id']]=='supported'}
        if len(members)<3:
            deferred.append({'id':proposal['id'],'reason':'insufficient_core_support'});continue
        result=runner.call('typing',typer.invocation(proposal['claims']['C'],members))
        try:
            if result['errors']:raise ValueError('typing_error')
            value=typer.apply(proposal,result['output'],members)
            if value is None:deferred.append({'id':proposal['id'],'reason':result['output']['reason']})
            else:typed.append(value)
        except (ValueError,TypeError,KeyError,AttributeError):deferred.append({'id':proposal['id'],'reason':'typing_contract'})
    byid={p['id']:p for p in typed};derived=[]
    for row in rows:
        if row['candidate_id'] not in byid:continue
        claim=byid[row['candidate_id']]['claims']['C']
        req=membership_policy.invocation(policy,row['text'],claim)
        if req!=row['request']:raise ValueError('Typing changed membership target')
        derived.append({**deepcopy(row),'claim':deepcopy(claim)})
    return typed,derived,deferred


def execute(directory):
    analysis_started=time.monotonic()
    plan=read_json(directory/'plan.json');live(plan['expires_at'])
    if plan.get('artifact_kind')!='fresh-grounded-pipeline-0.3':
        raise ValueError('Prepare a new plan with an explicit membership policy')
    evaluation=plan['evaluation']
    if product_evaluation.execution_state(evaluation['source_measurement'],evaluation['purpose'])!=evaluation:
        raise ValueError('Evaluation policy changed')
    membership_policy.validate(plan['membership_policy'])
    if plan['candidate_algorithm'] not in ('raw-core-0.1',source_first.VERSION):
        raise ValueError('Unknown candidate algorithm')
    if plan['candidate_algorithm']==source_first.VERSION and evaluation['purpose']!='product_diagnostic':
        raise ValueError('Source-first candidate algorithm remains diagnostic')
    # Include integrity checks, model startup, fresh embedding, and all stages.
    for field in ['inputs','code_sha256','model_files']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen input/code/model changed')
    for deployment in plan['deployments'].values():
        for info in [deployment['models']['baseline'],deployment['server']]:
            if file_hash(info['path'])!=info['sha256']:raise ValueError('Deployment changed')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=Runner(directory,plan,budget)
    runner.started=analysis_started
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'fresh_embedding':True,'budget_before':budget.summary()})
    try:
        artifact=directory/'fresh-groups.json'
        req={'system':fresh_embedding.VERSION,'data':{'snapshot':plan['snapshot'],'snapshot_sha256':sha(plan['snapshot']),'output':str(artifact)},'schema':{},'max_tokens':1}
        embedded=runner.call('embedding',req,provider=fresh_embedding.generate,maximum=plan['limits']['embedding_seconds'])
        if sha(artifact)!=embedded['sha256']:raise ValueError('Embedding result changed')
        raw=read_json(artifact);runner.timeout(90)
        with owned_server(plan['deployments']['proposal'],'baseline',directory/'proposal-server'):
            if plan['candidate_algorithm']==source_first.VERSION:
                units,sources,coverage=proposals_from_sources(raw,runner)
            else:
                proposals,deferred=proposals_from_groups(raw,runner)
                coverage={'scope':'raw-core historical baseline','semantic_approval':False}
        if plan['candidate_algorithm']==source_first.VERSION:
            req={'system':source_first_candidates.VERSION,'data':{'units':units,'sources':sources,
                  'threshold':plan['limits']['candidate_threshold']},'schema':{},'max_tokens':1}
            candidates=runner.call('unit-candidates',req,provider=source_first_candidates.generate,
                                   maximum=plan['limits']['embedding_seconds'])
            write(directory/'unit-candidates.json',candidates)
            proposals,deferred=candidates['proposals'],candidates['deferred']
        write(directory/'proposals.json',{'proposals':proposals,'deferred':deferred})
        membership=plan['deployments']['membership'];policy=plan['membership_policy']
        rows=source_rows(proposals,policy);write(directory/'source-requests.json',rows)
        actual={};detail_actual={}
        runner.timeout(90)
        with owned_server(membership,'baseline',directory/'membership-server'):
            for row in rows:actual[row['id']]=discovery.verdict(runner.call('membership',row['request']))
            write(directory/'source-verdicts.json',actual)
            typed,core_rows,type_deferred=classify(proposals,rows,actual,runner)
            details=membership_policy.bind_rows(policy,factory.detail_requests(typed,core_rows,actual))
            write(directory/'typed.json',{'proposals':typed,'core_rows':core_rows,'details':details,'deferred':type_deferred})
            for row in details:detail_actual[row['id']]=discovery.verdict(runner.call('detail',row['request']))
        bundle=factory.bundle(typed,core_rows,actual,details,detail_actual,expires_at=plan['expires_at'],model=plan['classifier'],documents=plan['documents'])
        packets=factory.fact_packets(bundle,plan['selections'])
        if packets:
            req=records.invocation(packets)
            judged=runner.call('facts',req,provider=evidence_nli.generate,maximum=plan['limits']['fact_seconds'])
            bound=records.records(packets,bundle['model'],judged,batch_request=req)
            bundle['checks']=[{'claim_id':p['claim']['id'],'selections':plan['selections'],'record':r} for p,r in zip(packets,bound,strict=True)]
        compiled=compile_inputs(bundle)
        write(directory/'bundle.json',bundle);write(directory/'compiled.json',compiled)
        elapsed=runner.clock()-runner.started
        report={'fresh_analysis_seconds':elapsed,'within_one_hour':elapsed<=3600,
                'evaluation':evaluation,
                'candidate_algorithm':plan['candidate_algorithm'],'coverage':coverage,
                'screened_inputs':len(compiled['profiles']),'qualified_agents':0,'quality_gate_passed':False,
                'remaining_gates':['actual_core_and_reason_audit','actual_answers_and_abstention','actual_comparison_latency'],
                'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
                'budget_after':budget.summary(),'runtime_reference_labels':False}
        write(directory/'completed.json',report)
        brief={k:v for k,v in report.items() if k not in {'budget_after','coverage'}}
        brief['coverage']={k:len(v) if isinstance(v,list) else v for k,v in coverage.items()}
        print(brief,flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':runner.clock()-runner.started,
              'quality_gate_passed':False,'budget_after':budget.summary()})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--snapshot',type=Path,default=Path('data/ubi-research-20261010.json'))
    p.add_argument('--source-gate',type=Path)
    p.add_argument('--proposal-plan',type=Path)
    p.add_argument('--purpose',choices=product_evaluation.PURPOSES)
    p.add_argument('--algorithm',choices=['raw-core-0.1',source_first.VERSION])
    p.add_argument('--evidence-plan',type=Path,default=Path('runs/fact-evidence-development-20261013/plan.json'))
    p.add_argument('--nli-records',type=Path,default=Path('runs/mvp-agreed-20261013/nli-bound-records.json'))
    a=p.parse_args()
    if a.phase=='prepare' and a.source_gate is None:p.error('prepare requires --source-gate')
    if a.phase=='prepare' and a.proposal_plan is None:p.error('prepare requires --proposal-plan; never silently select a historical deployment')
    if a.phase=='prepare' and a.purpose is None:p.error('prepare requires --purpose; diagnostic execution is not quality qualification')
    if a.phase=='prepare' and a.algorithm is None:p.error('prepare requires --algorithm; never silently change candidate construction')
    if a.phase=='prepare':prepare(a.directory,a.snapshot,a.source_gate,a.proposal_plan,a.evidence_plan,a.nli_records,purpose=a.purpose,algorithm=a.algorithm)
    else:execute(a.directory)
