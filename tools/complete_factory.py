"""Pinned G4 execution policy around the unchanged qualified Factory pipeline.

No model runs at import, authorization or preparation. Every live request uses
the shared account ledger, role-specific wire budgets and durable checkpoints.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.factory import acceptance,argument_observations,candidate_hierarchy,compact_claims,minimal_pipeline
from commentscope.factory import fact_checks,raw_membership_verification
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import api_resources,host_resources,openrouter,remote_verification as remote,scoped_authorization
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner,run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import units
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.agents.runtime_probe import runtime_probe,runtime_check,QUESTIONS
from commentscope.storage import write_json_exclusive as write
from experiments import remote_factory_pipeline as executor
from experiments.minimal_factory_pipeline import check_admission
from tools import cohort_refresh

AUTH_VERSION='factory-completion-phase-20261110-v1'
TOOLS_VERSION='factory-completion-tools-20261110-v1'
TOOL_FILES=('tools/complete_factory.py','tools/cohort_refresh.py')
STORAGE_POLICY={**api_resources.STORAGE_POLICY,'version':'factory-completion-artifact-space-0.1',
                'maximum_run_bytes':4*1024**3}
SAME_FIELDS=('deployment','verification_deployment','embedding_deployment','role_registry','classifier',
             'documents','selections','code_sha256','spend_policy','fact_benchmark','membership_retrieval_policy',
             'argument_audit_protocol','agent_source_policy','verification_contract','extraction_protocol','questions','schedule')


def private(path):executor.private(path)


def authorization(auth,*,call_seconds=0,allow_expired=False,observed_at=None):
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    parent=auth['parent_money_owner'];private(parent['file'])
    if sha(parent['file'])!=parent['sha256']:raise ValueError('Original money owner changed')
    original=read_json(parent['file']);scoped_authorization.guard(original,allow_expired=True)
    policy=executor.validate_spend_policy(read_json(auth['shared_policy_file']))
    if (auth.get('version')!=AUTH_VERSION or auth.get('tasks')!=['TASK-007'] or auth.get('gates')!=['G4']
            or not isinstance(auth.get('user_request'),str) or not auth['user_request'].strip()
            or auth.get('historical_charges_preserved') is not True
            or auth['shared_policy_sha256']!=sha(auth['shared_policy_file'])
            or auth['generation_deployment']!=original['chat_deployment']
            or policy!=read_json(original['shared_policy_file']) or units(policy['maximum_usd'])!=units('50')
            or not 0<units(auth['maximum_additional_usd'])<=units(auth['opening_account_remaining_usd'])<=units('50')
            or start.utcoffset() is None or end.utcoffset() is None
            or not timedelta(0)<end-start<=timedelta(hours=7)):
        raise ValueError('Explicit bounded G4 completion authorization required')
    now=observed_at or datetime.now(timezone.utc)
    if not allow_expired and not start<=now<end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Completion phase cannot cover another bounded request')
    return policy


def authorize(path,parent_file,cohort_file,*,maximum_usd,user_request):
    for name in (path,parent_file,cohort_file):private(name)
    if Path(path).exists():raise ValueError('Never overwrite a phase authorization')
    parent=read_json(parent_file);scoped_authorization.guard(parent,allow_expired=True)
    _,_,_,cohort=cohort_refresh.bind(cohort_file)
    policy=executor.validate_spend_policy(read_json(parent['shared_policy_file']));money=executor.ledger(policy)
    summary=money.summary()
    if (summary['reserved_calls'] or summary['uncertain_calls']
            or not 0<units(maximum_usd)<=units(summary['remaining_usd'])):
        raise ValueError('Settled shared money must cover the explicit completion cap')
    now=datetime.now(timezone.utc)
    auth={'version':AUTH_VERSION,'tasks':['TASK-007'],'gates':['G4'],'user_request':user_request,
          'started_at':now.isoformat(),'deadline':(now+timedelta(hours=7)).isoformat(),
          'maximum_additional_usd':str(maximum_usd),'opening_account_remaining_usd':summary['remaining_usd'],
          'shared_policy_file':parent['shared_policy_file'],'shared_policy_sha256':sha(parent['shared_policy_file']),
          'parent_money_owner':{'file':str(Path(parent_file).resolve()),'sha256':sha(parent_file)},
          'generation_deployment':deepcopy(parent['chat_deployment']),
          'cohort':cohort,'historical_charges_preserved':True}
    authorization(auth);write(path,auth);return auth


def guard(plan,*,call_seconds=0,allow_expired=False):
    binding=plan['authorization']
    if sha(binding['file'])!=binding['sha256'] or read_json(binding['file'])!=binding['authorization']:
        raise ValueError('Completion authorization changed')
    auth=binding['authorization'];policy=authorization(auth,call_seconds=call_seconds,allow_expired=allow_expired)
    if (plan['gate']!='G4' or plan['mode']!='factory' or plan['spend_policy']!=policy
            or plan['spend_scope_sha256']!=binding['sha256']
            or plan['maximum_cost_usd']!=auth['maximum_additional_usd']
            or not 0<units(plan['subcap_usd'])<=units(plan['maximum_cost_usd'])
            or plan['cohort_refresh']!=auth['cohort']
            or plan['deployment']!=auth['generation_deployment']
            or plan['verification_deployment']!=remote.SOL or plan['embedding_deployment']!=remote.EMBEDDING
            or plan['role_registry']!=remote.ROLES or plan['classifier']!=executor.model_identity()
            or plan['membership_retrieval_policy']!=candidate_hierarchy.VERSION
            or plan['argument_audit_protocol']!=argument_observations.TYPED_CHAT
            or plan['verification_contract']!=raw_membership_verification.FULL_SCOPE
            or plan['agent_source_policy']!='verified_subset' or plan['extraction_protocol']!=compact_claims.PROPOSALS):
        raise ValueError('Frozen completion roles, input or inherited accounting changed')


def admissions(path,plan):
    check_admission('G4',plan['deployment'],Path(path),'free','raw')
    entries=read_json(path)['gates']
    for gate in ('G1','G2','G3'):
        previous=read_json(Path(entries[gate]['run'])/'plan.json')
        if any(previous[key]!=plan[key] for key in SAME_FIELDS):
            raise ValueError('Completion qualification differs from '+gate)
        if gate!='G1' and previous['scope_refresh']!=plan['scope_refresh']:
            raise ValueError('Fixed actual sources use another revalidation')


def prepare(directory,auth_file,admission_file):
    directory=Path(directory)
    for name in (directory,auth_file,admission_file):private(name)
    if directory.exists():raise ValueError('Fresh completion directory required')
    auth=read_json(auth_file);policy=authorization(auth)
    snapshot,snapshot_file,inputs,cohort=cohort_refresh.bind(auth['cohort']['file'])
    if cohort!=auth['cohort']:raise ValueError('Completion cohort changed before preparation')
    prior=read_json(Path(read_json(admission_file)['gates']['G3']['run'])/'plan.json')
    plan=deepcopy(prior);owner=sha(auth_file);money=executor.ledger(policy)
    tool_files={name:sha(ROOT/name) for name in TOOL_FILES}
    inputs.update(prior['inputs']);inputs.update({str(auth_file):owner,str(admission_file):sha(admission_file),**tool_files})
    plan.update(artifact_kind=executor.VERSION,mode='factory',gate='G4',run_directory=str(directory.resolve()),
        authorization={'file':str(auth_file),'sha256':owner,'authorization':auth},spend_scope_sha256=owner,
        maximum_cost_usd=auth['maximum_additional_usd'],subcap_usd=auth['maximum_additional_usd'],
        opening_scope_charge_usd=money.summary(plan_sha256=owner)['charged_usd'],spend_policy=policy,
        completion_execution={'version':TOOLS_VERSION,'tool_files':tool_files},cohort_refresh=cohort,
        scope_refresh=cohort['base_scope_refresh'],snapshot=str(snapshot_file),snapshot_sha256=sha(snapshot_file),
        scope_ids=sorted(sources(snapshot)),canonical_population=999,processing_count=999,
        expires_at=snapshot.usage.expires_at,inputs=inputs,code_sha256=source_code_hashes(),
        artifact_storage_policy=deepcopy(STORAGE_POLICY),resource_policy=deepcopy(host_resources.HTTP_API_POLICY),
        admission_file=str(admission_file),quality_gate_passed=False,cross_run_response_reuse=False)
    guard(plan);admissions(admission_file,plan);acceptance.check_scope(acceptance.from_plan(plan),'G4',999,755)
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    plan['providers_at_prepare']={'generation':executor.provider_preflight(plan['deployment']),
        'verification':executor.provider_preflight(remote.SOL),'embedding':executor.embedding_preflight()}
    for document in plan['documents']:fact_checks.live(document['expires_at'])
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    executor.archive_sources(directory,plan['code_sha256']);executor.archive_sources(directory,tool_files)
    return plan


def validate(directory,*,allow_expired=False):
    directory=Path(directory);private(directory);plan=read_json(directory/'plan.json')
    if (read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['artifact_kind']!=executor.VERSION or plan['code_sha256']!=source_code_hashes()
            or plan['completion_execution']!={'version':TOOLS_VERSION,'tool_files':{p:sha(ROOT/p) for p in TOOL_FILES}}
            or any(sha(name)!=expected for name,expected in plan['inputs'].items())
            or plan['artifact_storage_policy']!=STORAGE_POLICY or plan['resource_policy']!=host_resources.HTTP_API_POLICY
            or plan['billing_policy']!=remote.WIRE_BUDGET or plan['model_files']!={}):
        raise ValueError('Frozen completion implementation, inputs or resource policy changed')
    run_origin(plan,directory,attempt=1);guard(plan,allow_expired=allow_expired)
    snapshot,path,_,binding=cohort_refresh.bind(plan['cohort_refresh']['file'])
    if (binding!=plan['cohort_refresh'] or str(path)!=plan['snapshot']
            or sha(path)!=plan['snapshot_sha256'] or sorted(sources(snapshot))!=plan['scope_ids']):
        raise ValueError('Completion source or denominator binding changed')
    profile=acceptance.from_plan(plan)
    if profile is None:raise ValueError('Completion requires the approved r5 profile')
    acceptance.check_scope(profile,'G4',len(plan['scope_ids']),755)
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    admissions(plan['admission_file'],plan)
    return plan


def review_reference(plan):
    """Pure adapter called by the full-output evaluator, never by a model."""
    validated=validate(Path(plan['run_directory']),allow_expired=True)
    if validated!=plan:raise ValueError('Review differs from frozen completion plan')
    return read_json(plan['cohort_refresh']['meaning_reference_file'])


class CompletionStorage(api_resources.SpaceGuard):
    def __init__(self,directory,policy,**kwargs):
        if policy!=STORAGE_POLICY:raise ValueError('Explicit completion record policy required')
        super().__init__(directory,api_resources.STORAGE_POLICY,**kwargs)
        self.policy=deepcopy(policy)


class CompletionSession(executor.RemoteSession):
    """Same transport methods, with separately pinned phase/resource setup."""
    def __init__(self,directory,plan,dispatch):
        self.directory=Path(directory);self.plan=plan;self.dispatch=dispatch;self.authorization_guard=guard
        self.storage=CompletionStorage(directory,plan['artifact_storage_policy'])
        self.plan_sha=sha(self.directory/'plan.json');self.money=executor.SubcapLedger(executor.ledger(plan['spend_policy']),plan)
        self.time=InferenceBudget(self.directory/'inference.sqlite',executor.VERSION,limit_seconds=None)
        self.clients={};self.checkpoints={}
        for key,field in (('generation','deployment'),('verification','verification_deployment')):
            client=openrouter.Client(plan[field]);self.clients[key]=client
            budget=remote.WireBudget(self.time,self.money,plan_sha256=self.plan_sha,deployment=plan[field],
                maximum_run_usd=plan['maximum_cost_usd'],paid_provider=client.generate,key_metadata=executor.key_metadata,
                spend_scope_sha256=plan['spend_scope_sha256'])
            base=openrouter.Runner(directory,plan,budget,client,deployment_key=field)
            self.checkpoints[key]=CheckpointRunner(base,openrouter.generation_allocation(plan[field],require_explicit=True))
        client=remote.EmbeddingClient(plan['embedding_deployment']);self.clients['embedding']=client
        budget=remote.EmbeddingBudget(self.time,self.money,plan_sha256=self.plan_sha,
            spend_scope_sha256=plan['spend_scope_sha256'],maximum_run_usd=plan['maximum_cost_usd'],
            paid_provider=client.generate,key_metadata=executor.key_metadata)
        self.checkpoints['embedding']=CheckpointRunner(RuntimeRunner(directory,plan,budget,client,
            deployment_key='embedding_deployment'),{})


def run(directory):
    directory=Path(directory)
    with experiment_lock(directory),executor.quota_watch():
        plan=validate(directory)
        if (directory/'completed.json').exists():
            done=read_json(directory/'completed.json')
            if (done['plan_sha256']!=sha(directory/'plan.json')
                    or done['output_sha256']!=sha(directory/'artifacts/output.json')
                    or done['runtime_sha256']!=sha(directory/'artifacts/runtime.json')):
                raise ValueError('Completed artifacts changed')
            return done
        attempt=len(list((directory/'attempts').glob('*.started.json')))+1
        origin=run_origin(plan,directory,attempt=attempt);dispatch=host_resources.RemoteCallGuard()
        session=CompletionSession(directory,plan,dispatch)
        write(directory/'attempts'/f'{attempt:04}.started.json',{'at':datetime.now(timezone.utc).isoformat(),**origin})
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Foreign artifact path')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan completion artifact changed')
            else:session.storage.before_write(value);write(path,value)
        try:
            for deployment in (plan['deployment'],plan['verification_deployment']):executor.provider_preflight(deployment)
            executor.embedding_preflight()
            with host_resources.watch(directory/'resources'/f'{attempt:04}',plan['resource_policy'],
                    host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
                snapshot,_,_,_=cohort_refresh.bind(plan['cohort_refresh']['file'])
                output=minimal_pipeline.process(snapshot,session,session.embed,session.inspect,
                    lambda request:session.call('facts-'+digest(request)[:20],request),model=plan['classifier'],
                    documents=plan['documents'],selections=plan['selections'],scope_ids=plan['scope_ids'],save=save,
                    discovery_mode='free',membership_mode='raw',verification_contract=plan['verification_contract'],
                    extraction_protocol=plan['extraction_protocol'],argument_audit_protocol=plan['argument_audit_protocol'],
                    agent_source_policy=plan['agent_source_policy'],membership_retrieval_policy=plan['membership_retrieval_policy'])
                save('output',output)
                runtime=runtime_probe(output['agent_inputs']['bundle'],session,
                    save_turn=lambda row:save('runtime-turns/'+row['candidate_id']+'/'+row['question_id'],row))
                save('runtime',runtime);runtime_check(runtime,output['agent_inputs']['compiled'],questions=plan['questions'])
            done={'artifact_kind':executor.VERSION,'execution_complete':True,'plan_sha256':sha(directory/'plan.json'),
                'gate':'G4','compiled_agents':len(output['agent_inputs']['compiled']['profiles']),
                'runtime_turns':len(runtime['turns']),'binding_errors':len(output['errors']),
                'capacity_holds':len(output['capacity_holds']),'unextracted':len(output['unextracted_source_ids']),
                'output_sha256':sha(directory/'artifacts/output.json'),'runtime_sha256':sha(directory/'artifacts/runtime.json'),
                'quality_gate_passed':False,'local_model_loaded':False,'data_revision':cohort_refresh.VERSION,
                'artifact_storage':session.storage.summary(),'spending':session.money.summary(),
                'run_spending':session.money.summary(plan_sha256=plan['spend_scope_sha256']),**origin}
            write(directory/'completed.json',done);return done
        except BaseException as error:
            write(directory/'attempts'/f'{attempt:04}.failed.json',{'exception':type(error).__name__,
                'spending':session.money.summary(),'time_budget':session.time.summary()})
            raise


def main(argv=None):
    import json
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True)
    p=actions.add_parser('authorize');p.add_argument('file',type=Path);p.add_argument('--parent-owner',type=Path,required=True)
    p.add_argument('--cohort',type=Path,required=True);p.add_argument('--maximum-usd',required=True);p.add_argument('--user-request',required=True)
    p=actions.add_parser('prepare');p.add_argument('directory',type=Path);p.add_argument('--authorization',type=Path,required=True);p.add_argument('--admission',type=Path,required=True)
    p=actions.add_parser('run');p.add_argument('directory',type=Path);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--live',action='store_true',required=True)
    args=parser.parse_args(argv)
    if args.action=='authorize':
        auth=authorize(args.file,args.parent_owner,args.cohort,maximum_usd=args.maximum_usd,user_request=args.user_request)
        print(json.dumps({'authorization':str(args.file),'maximum_usd':auth['maximum_additional_usd'],'deadline':auth['deadline'],'new_model_calls':0}));return
    if args.action=='prepare':
        plan=prepare(args.directory,args.authorization,args.admission)
        print(json.dumps({'prepared':str(args.directory),'scope':len(plan['scope_ids']),'new_model_calls':0}));return
    os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip()
    result=run(args.directory)
    print(json.dumps({k:result[k] for k in ('gate','execution_complete','compiled_agents','runtime_turns','binding_errors','spending','run_spending')}))


if __name__=='__main__':main()
