"""Fresh all-HTTP Factory and fixed fact benchmark under the original money owner.

Run as a module: multiprocessing workers must never be launched from stdin.
Execution is not semantic admission; the existing full-output review is required.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler

from commentscope.factory import acceptance, argument_observations, compact_claims, minimal_pipeline
from commentscope.factory import fact_checks, remote_fact_records, raw_membership_verification
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import openrouter, remote_verification as remote, host_resources
from commentscope.providers import scoped_authorization
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.providers.checkpoint_calls import CheckpointRunner, run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.openrouter_budget import SpendLedger, units
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.agents.runtime_probe import runtime_probe, runtime_check, QUESTIONS
from commentscope.factory.pipeline_work import ModelResponseUnavailable
from commentscope.storage import write_json_exclusive as write
from experiments.openrouter_factory_probe import private, key_metadata, validate_spend_policy
from experiments.openrouter_factory_pipeline import fixed_scope, provider_preflight, archive_sources
from experiments.compare_backend_discovery import check_quota, quota_watch

VERSION='minimal-factory-remote-verification-20261106-v1'
AUTH='remote-verification-linked-authorization-20261106-v1'
FACT_SOURCE=Path('runs/fact-gate-40-20261013/plan.json')
RUNTIME_FILES=('src/commentscope/factory/remote_fact_records.py',
               'src/commentscope/factory/fact_checks.py','src/commentscope/providers/openai_schema.py',
               'src/commentscope/contracts/structured_output.py',
               'src/commentscope/providers/remote_verification.py','src/commentscope/providers/openrouter.py')


def guard(plan,*,call_seconds=0,allow_expired=False):
    binding=plan['authorization'];auth=binding['authorization']
    if sha(binding['file'])!=binding['sha256'] or read_json(binding['file'])!=auth:
        raise ValueError('Remote role authorization changed')
    owner=auth['money_owner'];original=read_json(owner['file'])
    if sha(owner['file'])!=owner['sha256']:raise ValueError('Original money owner changed')
    scoped_authorization.guard(original,allow_expired=True)
    if (auth.get('version')!=AUTH or auth['verification_deployment']!=remote.SOL
            or auth['embedding_deployment']!=remote.EMBEDDING or auth['role_registry']!=remote.ROLES
            or auth['generation_deployment']!=original['chat_deployment']
            or auth['deadline']!=original['deadline'] or auth['maximum_usd']!=original['maximum_additional_usd']
            or plan['deployment']!=auth['generation_deployment'] or plan['verification_deployment']!=remote.SOL
            or plan['embedding_deployment']!=remote.EMBEDDING
            or plan['role_registry']!=remote.ROLES or plan['spend_scope_sha256']!=owner['sha256']
            or plan['maximum_cost_usd']!=original['maximum_additional_usd']
            or plan['spend_policy']!=read_json(original['shared_policy_file'])
            or units(plan['subcap_usd'])>units(original['maximum_additional_usd'])
            or units(plan['subcap_usd'])<=0):raise ValueError('Remote roles, deadline or inherited money changed')
    if not allow_expired:
        scoped_authorization.guard(original,call_seconds=call_seconds)


def authorize(path,owner_file):
    private(path);owner_file=Path(owner_file).resolve();old=read_json(owner_file)
    scoped_authorization.guard(old)
    value={'version':AUTH,'user_request':'검증은 gpt6.1sol 사용; 로컬 정확성/메모리 문제 해소',
           'money_owner':{'file':str(owner_file),'sha256':sha(owner_file)},
           'deadline':old['deadline'],'maximum_usd':old['maximum_additional_usd'],
           'generation_deployment':old['chat_deployment'],'verification_deployment':deepcopy(remote.SOL),
           'embedding_deployment':deepcopy(remote.EMBEDDING),'role_registry':deepcopy(remote.ROLES),
           'retries':0,'fallback':None,'historical_charges_preserved':True}
    write(path,value);return value


def ledger(policy):
    return SpendLedger(Path(policy['ledger']),policy['account_id'],maximum_usd=policy['maximum_usd'],
                       opening_charge_usd=policy['opening_charge_usd'])


def embedding_preflight():
    url='https://openrouter.ai/api/v1/models/'+quote(remote.EMBEDDING['model'],safe='/')+'/endpoints'
    with build_opener(ProxyHandler({}),NoRedirect()).open(url,timeout=30) as r:endpoints=json.load(r)['data']['endpoints']
    selected=[e for e in endpoints if e['tag']=='openai']
    if len(selected)!=1:raise ValueError('Pinned embedding endpoint unavailable')
    e=selected[0];rates=openrouter.endpoint_price_ceiling(e['pricing'])
    if e.get('status')!=0 or e['context_length']!=8192 or any(rates[k]>Decimal(str(v))
          for k,v in {'prompt':0.02,'completion':0,'request':0}.items()):
        raise ValueError('Embedding availability/context/price changed')
    return {k:e[k] for k in ('tag','provider_name','context_length','pricing')}


def model_identity():
    return {'kind':'remote_llm','name':remote.SOL['model'],'revision':remote.SOL['model'],
            'provider':'OpenAI','deployment_sha256':digest(remote.SOL),
            'runtime_sha256':digest({p:sha(p) for p in RUNTIME_FILES}),'language_scope':'multilingual'}


def admission(gate,path,profile):
    if gate=='G1':return
    if path is None:raise ValueError('Larger gates require existing reviewed admissions')
    manifest=read_json(path)
    from experiments.minimal_factory_review import load_run
    from experiments.minimal_factory_pipeline import check_admission
    check_admission(gate,profile['deployment'],path,'free','raw')
    required={'G2':['G1'],'G3':['G1','G2']}[gate]
    for prior in required:
        entry=manifest['gates'][prior];run=Path(entry['run'])
        previous=load_run(run)[0]
        if (previous['gate']!=prior or previous['artifact_kind']!=VERSION
                or any(previous[k]!=profile[k] for k in ('deployment','verification_deployment','embedding_deployment',
                    'role_registry','classifier','documents','selections','code_sha256','spend_policy','fact_benchmark'))):
            raise ValueError('Prior remote gate uses different roles/code/evidence or failed review')


def prepare(directory,auth_file,materials_file,*,mode='factory',gate='G1',subcap_usd='0.5',
            fact_benchmark=None,admission_file=None):
    directory=Path(directory);auth_file=Path(auth_file).resolve();materials_file=Path(materials_file)
    for p in (directory,auth_file,materials_file):private(p)
    if directory.exists() or mode not in ('factory','benchmark') or gate not in ('G1','G2','G3'):
        raise ValueError('Fresh supported remote run required')
    auth=read_json(auth_file);old=read_json(auth['money_owner']['file'])
    policy=validate_spend_policy(read_json(old['shared_policy_file']));money=ledger(policy)
    if money.summary()['reserved_calls'] or money.summary()['uncertain_calls']:raise BudgetExhausted('Existing money hold')
    materials=read_json(materials_file)
    inputs={str(materials_file):sha(materials_file),str(auth_file):sha(auth_file)}
    if mode=='benchmark':inputs[str(FACT_SOURCE)]=sha(FACT_SOURCE)
    for p in (fact_benchmark,admission_file):
        if p is not None:private(p);inputs[str(p)]=sha(p)
    plan={'artifact_kind':VERSION,'run_directory':str(directory.resolve()),'mode':mode,'gate':gate,
          'authorization':{'file':str(auth_file),'sha256':sha(auth_file),'authorization':auth},
          'deployment':auth['generation_deployment'],'verification_deployment':deepcopy(remote.SOL),
          'embedding_deployment':deepcopy(remote.EMBEDDING),'role_registry':deepcopy(remote.ROLES),
          'spend_policy':policy,'spend_scope_sha256':auth['money_owner']['sha256'],
          'maximum_cost_usd':old['maximum_additional_usd'],'subcap_usd':subcap_usd,
          'opening_scope_charge_usd':money.summary(plan_sha256=auth['money_owner']['sha256'])['charged_usd'],
          'billing_policy':remote.WIRE_BUDGET,'classifier':model_identity(),
          'documents':materials['documents'],'selections':materials['selections'],'model_files':{},
          'inputs':inputs,'code_sha256':source_code_hashes(),
          'resource_policy':deepcopy(host_resources.HTTP_ONLY_POLICY),
          'limits':{'analysis_seconds':None,'call_seconds':180},
          'discovery_mode':'free','membership_mode':'raw','extraction_protocol':compact_claims.PROPOSALS,
          'verification_contract':raw_membership_verification.FULL_SCOPE,
          'argument_audit_protocol':argument_observations.CHAT_SPLIT,'agent_source_policy':'verified_subset',
          'component_diagnostic_policy':'record_and_continue','fact_benchmark':str(fact_benchmark) if fact_benchmark else None,
          'admission_file':str(admission_file) if admission_file else None,
          'questions':deepcopy(QUESTIONS),'schedule':deepcopy(minimal_pipeline.SCHEDULE),
          'goal_revision':acceptance.R5,'acceptance_profile':acceptance.validate(read_json('tests/fixtures/factory-acceptance-r5.json'),acceptance.R5_DIGEST),
          'reference_runtime_input':False,'cross_run_response_reuse':False,'quality_gate_passed':False}
    plan['acceptance_profile_sha256']=digest(plan['acceptance_profile'])
    guard(plan)
    plan['providers_at_prepare']={'generation':provider_preflight(plan['deployment']),
        'verification':provider_preflight(remote.SOL),'embedding':embedding_preflight()}
    for doc in plan['documents']:fact_checks.live(doc['expires_at'])
    if mode=='factory':
        if fact_benchmark is None:raise ValueError('Fresh remote fact benchmark required')
        replay_benchmark(Path(fact_benchmark).parent,plan,[])
        admission(gate,admission_file,plan)
        snapshot,scope,original=fixed_scope(gate);fact_checks.live(snapshot.usage.expires_at)
        if gate=='G1':write(directory/'snapshot.json',snapshot.to_dict())
        snapshot_path=directory/'snapshot.json' if gate=='G1' else original
        plan.update(snapshot=str(snapshot_path),snapshot_sha256=sha(snapshot_path),scope_ids=scope,
            expires_at=snapshot.usage.expires_at,processing_count=len(scope),
            canonical_population=len(sources(snapshot)))
        if gate!='G1':plan['inputs'][str(Path('runs/design-freeze-20261016/samples.json'))]=sha('runs/design-freeze-20261016/samples.json')
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    archive_sources(directory,plan['code_sha256']);return plan


class SubcapLedger:
    """The sublimit never creates a new money owner or refunds prior calls."""
    def __init__(self,base,plan):self.base=base;self.plan=plan
    def __getattr__(self,name):return getattr(self.base,name)
    def reserve(self,scope,request,maximum,**kwargs):
        p=self.plan
        if scope!=p['spend_scope_sha256']:raise ValueError('Wrong inherited money owner')
        charged=units(self.base.summary(plan_sha256=scope)['charged_usd'])
        if charged+units(maximum)>units(p['opening_scope_charge_usd'])+units(p['subcap_usd']):
            raise BudgetExhausted('Frozen run subcap cannot cover next request')
        return self.base.reserve(scope,request,maximum,**kwargs)


class RemoteSession:
    def __init__(self,directory,plan,dispatch):
        self.directory=Path(directory);self.plan=plan;self.dispatch=dispatch
        self.plan_sha=sha(self.directory/'plan.json');self.money=SubcapLedger(ledger(plan['spend_policy']),plan)
        self.time=InferenceBudget(self.directory/'inference.sqlite',VERSION,limit_seconds=None)
        self.clients={};self.checkpoints={}
        for key,field in (('generation','deployment'),('verification','verification_deployment')):
            client=openrouter.Client(plan[field]);self.clients[key]=client
            budget=remote.WireBudget(self.time,self.money,plan_sha256=self.plan_sha,deployment=plan[field],
                maximum_run_usd=plan['maximum_cost_usd'],paid_provider=client.generate,key_metadata=key_metadata,
                spend_scope_sha256=plan['spend_scope_sha256'])
            base=openrouter.Runner(directory,plan,budget,client,deployment_key=field)
            self.checkpoints[key]=CheckpointRunner(base,openrouter.generation_allocation(plan[field],require_explicit=True))
        client=remote.EmbeddingClient(plan['embedding_deployment']);self.clients['embedding']=client
        budget=remote.EmbeddingBudget(self.time,self.money,plan_sha256=self.plan_sha,
            spend_scope_sha256=plan['spend_scope_sha256'],maximum_run_usd=plan['maximum_cost_usd'],
            paid_provider=client.generate,key_metadata=key_metadata)
        self.checkpoints['embedding']=CheckpointRunner(RuntimeRunner(directory,plan,budget,client,
            deployment_key='embedding_deployment'),{})

    def inspect(self,request):
        self.dispatch.check();check_quota();guard(self.plan,call_seconds=180)
        # Capacity partition must fit either potential route. Dispatch checks
        # the actual route independently, with its own allocation and receipt.
        return self.clients['generation'].measure(request)

    def call(self,stage,request):
        selected=remote.role(stage);key='generation' if selected=='interaction' else selected
        self.dispatch.check();check_quota();guard(self.plan,call_seconds=180)
        measured=self.clients[key].measure(request)
        if not measured['fits']:raise ValueError('Remote request exceeds capacity')
        with self.dispatch.remote_call():result=self.checkpoints[key].call(key+'-'+stage,request)
        if result.get('errors'):raise ModelResponseUnavailable(stage,digest(request),digest(request['data']))
        remote.parsed_receipt(result,request,self.clients[key].deployment)
        count=(result.get('usage') or {}).get('prompt_tokens')
        if type(count) is not int or not 0<=count<=measured['input_upper_bound_tokens']+measured['provider_margin']:
            raise ValueError('Actual remote input exceeds reserved wire bound')
        return result

    def embed(self,stage,texts):
        responses=[];client=self.clients['embedding']
        for batch in remote.batches(texts):
            req={'system':remote.VERSION,'data':{'input':[p['text'] for p in batch]},'schema':{},'max_tokens':1}
            self.dispatch.check();check_quota();guard(self.plan,call_seconds=180)
            with self.dispatch.remote_call():
                result=self.checkpoints['embedding'].call('embedding-'+stage+'-'+digest(req)[:20],req,
                    provider=client.generate,maximum=180)
            remote.embedding_vectors(result,len(batch));responses.append(result)
        return remote.combine(texts,responses)


def benchmark_rows(plan,records):
    source=read_json(FACT_SOURCE);rows=source['rows']
    if len(rows)!=40 or len(records)!=40:raise ValueError('Fixed 40-case fact denominator changed')
    kept=wrong=errors=0;out=[]
    for row,saved in zip(rows,records,strict=True):
        if saved['id']!=row['id'] or saved['expected']!=row['expected']:raise ValueError('Fixed fact labels changed')
        passed=remote_fact_records.validate_record(saved['record'],row['packet'],plan['classifier'])
        kept+=int(row['expected']=='supported' and passed)
        wrong+=int(row['expected']!='supported' and passed)
        out.append({'id':row['id'],'expected':row['expected'],'observed':saved['record']['state']})
    if sum(r['expected']=='supported' for r in rows)!=10:raise ValueError('Fixed supported denominator changed')
    return {'artifact_kind':VERSION+'-fixed-facts','supported_reference_cases':10,'unsupported_reference_cases':30,
            'supported_kept':kept,'unsupported_false_support':wrong,'errors':errors,
            'passed':kept>=8 and wrong==0,'rows':out,'model':plan['classifier'],
            'independent_gold':False,'actual_agent_fact_approval':'separate_agent_review'}


def replay_benchmark(directory,current_plan,actual_checks):
    private(directory);plan=read_json(directory/'plan.json');completed=read_json(directory/'completed.json')
    if (plan.get('artifact_kind')!=VERSION or plan['mode']!='benchmark'
            or completed['plan_sha256']!=sha(directory/'plan.json')
            or completed['report_sha256']!=sha(directory/'artifacts/fact-report.json')
            or completed['records_sha256']!=sha(directory/'artifacts/fact-records.json')
            or plan['inputs'].get(str(FACT_SOURCE))!=sha(FACT_SOURCE)
            or plan['classifier']!=current_plan['classifier']):raise ValueError('Remote fact benchmark provenance changed')
    guard(plan,allow_expired=True)
    relevant={p:sha(p) for p in RUNTIME_FILES}
    if any(pinned.get(p)!=h for pinned in (plan['code_sha256'],current_plan['code_sha256']) for p,h in relevant.items()):
        raise ValueError('Remote fact decision code changed')
    records=read_json(directory/'artifacts/fact-records.json');report=benchmark_rows(plan,records)
    if report!=read_json(directory/'artifacts/fact-report.json'):raise ValueError('Remote fact report does not replay')
    if any(c['record'].get('model')!=plan['classifier'] or c['record'].get('artifact_kind')!=remote_fact_records.VERSION
           for c in actual_checks):raise ValueError('Actual fact checks use another classifier')
    return {**report,'fresh_inference':False,'new_model_calls':0,
            'inputs_sha256':{str(directory/p):sha(directory/p) for p in ('plan.json','completed.json','artifacts/fact-records.json','artifacts/fact-report.json')},
            'actual_fact_records_with_matching_runtime':len(actual_checks)}


def validate(directory,plan):
    if (read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan.get('artifact_kind')!=VERSION or plan['code_sha256']!=source_code_hashes()
            or any(sha(p)!=h for p,h in plan['inputs'].items())
            or plan['resource_policy']!=host_resources.HTTP_ONLY_POLICY
            or plan['classifier']!=model_identity() or plan['model_files']!={}
            or plan['billing_policy']!=remote.WIRE_BUDGET
            or plan['argument_audit_protocol']!=argument_observations.CHAT_SPLIT
            or plan['agent_source_policy']!='verified_subset'):
        raise ValueError('Frozen remote code/input/execution contract changed')
    run_origin(plan,directory,attempt=1);guard(plan)
    if plan['mode']=='factory':admission(plan['gate'],Path(plan['admission_file']) if plan['admission_file'] else None,plan)
    if 'torch' in sys.modules or 'transformers' in sys.modules:raise ValueError('All-HTTP executor imported local model runtime')


def run(directory):
    directory=Path(directory);private(directory)
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json');validate(directory,plan)
        if (directory/'completed.json').exists():
            completed=read_json(directory/'completed.json')
            files=({'report_sha256':'artifacts/fact-report.json','records_sha256':'artifacts/fact-records.json'}
                   if plan['mode']=='benchmark' else {'output_sha256':'artifacts/output.json','runtime_sha256':'artifacts/runtime.json'})
            if completed['plan_sha256']!=sha(directory/'plan.json') or any(completed[k]!=sha(directory/p) for k,p in files.items()):
                raise ValueError('Completed remote artifacts changed')
            return completed
        attempt=len(list((directory/'attempts').glob('*.started.json')))+1
        origin=run_origin(plan,directory,attempt=attempt);dispatch=host_resources.RemoteCallGuard()
        session=RemoteSession(directory,plan,dispatch)
        write(directory/'attempts'/f'{attempt:04}.started.json',{'at':datetime.now(timezone.utc).isoformat(),**origin})
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan artifact changed')
            else:write(path,value)
        try:
            for profile in (plan['deployment'],plan['verification_deployment']):provider_preflight(profile)
            embedding_preflight()
            with host_resources.watch(directory/'resources'/f'{attempt:04}',plan['resource_policy'],
                    host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_only'):
                if plan['mode']=='benchmark':
                    # Also exercises actual embedding HTTP/usage before Factory work.
                    vectors=session.embed('smoke',{'en':'Public education should be accessible.','ko':'교육은 누구나 접근할 수 있어야 한다.'})
                    save('embedding-smoke',{'model':remote.EMBEDDING['model'],'vectors':vectors})
                    records=[]
                    for row in read_json(FACT_SOURCE)['rows']:
                        req=remote_fact_records.invocation(row['packet'],plan['classifier'])
                        result=session.call('facts-'+digest(req)[:20],req)
                        records.append({'id':row['id'],'expected':row['expected'],
                            'record':remote_fact_records.bind(row['packet'],plan['classifier'],result)})
                    save('fact-records',records);report=benchmark_rows(plan,records);save('fact-report',report)
                    completion={'execution_complete':True,'plan_sha256':sha(directory/'plan.json'),
                        'records_sha256':sha(directory/'artifacts/fact-records.json'),
                        'report_sha256':sha(directory/'artifacts/fact-report.json'),'fact_benchmark_passed':report['passed']}
                else:
                    replay=replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
                    if not replay['passed']:raise ValueError('Remote fixed fact benchmark failed')
                    snapshot=load_snapshot(Path(plan['snapshot']))
                    if snapshot.sha256!=plan['snapshot_sha256']:raise ValueError('Snapshot changed')
                    output=minimal_pipeline.process(snapshot.snapshot,session,session.embed,session.inspect,
                        lambda req:session.call('facts-'+digest(req)[:20],req),model=plan['classifier'],
                        documents=plan['documents'],selections=plan['selections'],scope_ids=plan['scope_ids'],save=save,
                        discovery_mode='free',membership_mode='raw',verification_contract=plan['verification_contract'],
                        extraction_protocol=plan['extraction_protocol'],argument_audit_protocol=plan['argument_audit_protocol'],
                        agent_source_policy=plan['agent_source_policy'])
                    save('output',output)
                    runtime=runtime_probe(output['agent_inputs']['bundle'],session,
                        save_turn=lambda row:save('runtime-turns/'+row['candidate_id']+'/'+row['question_id'],row))
                    save('runtime',runtime);runtime_check(runtime,output['agent_inputs']['compiled'],questions=plan['questions'])
                    completion={'execution_complete':True,'plan_sha256':sha(directory/'plan.json'),'gate':plan['gate'],
                        'compiled_agents':len(output['agent_inputs']['compiled']['profiles']),'runtime_turns':len(runtime['turns']),
                        'binding_errors':len(output['errors']),'capacity_holds':len(output['capacity_holds']),
                        'unextracted':len(output['unextracted_source_ids']),
                        'output_sha256':sha(directory/'artifacts/output.json'),'runtime_sha256':sha(directory/'artifacts/runtime.json')}
            completion.update(artifact_kind=VERSION,quality_gate_passed=False,local_model_loaded=False,
                spending=session.money.summary(),run_spending=session.money.summary(plan_sha256=plan['spend_scope_sha256']),**origin)
            write(directory/'completed.json',completion);return completion
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json',{'exception':type(exc).__name__,
                **({'diagnostic':exc.diagnostic} if isinstance(exc,ModelResponseUnavailable) else {}),
                'spending':session.money.summary(),'time_budget':session.time.summary()})
            raise


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('authorize','prepare','run'))
    p.add_argument('directory',type=Path);p.add_argument('--owner',type=Path);p.add_argument('--authorization',type=Path)
    p.add_argument('--materials',type=Path);p.add_argument('--mode',choices=('factory','benchmark'),default='factory')
    p.add_argument('--gate',choices=('G1','G2','G3'),default='G1');p.add_argument('--subcap-usd',default='0.5')
    p.add_argument('--fact-benchmark',type=Path);p.add_argument('--admission',type=Path)
    a=p.parse_args()
    if a.action=='authorize':result=authorize(a.directory,a.owner)
    elif a.action=='prepare':result=prepare(a.directory,a.authorization,a.materials,mode=a.mode,gate=a.gate,
        subcap_usd=a.subcap_usd,fact_benchmark=a.fact_benchmark,admission_file=a.admission)
    else:result=run(a.directory)
    print(json.dumps({k:v for k,v in result.items() if k not in ('code_sha256','inputs','documents','selections')},ensure_ascii=False))


if __name__=='__main__':main()
