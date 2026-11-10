"""One capped shared-discovery development trial; no formal gate admission."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.factory import argument_observations as obs,candidate_consolidation as cc,minimal_pipeline
from commentscope.factory import source_membership_batch
from commentscope.factory import jev_membership, perspective_mining
from commentscope.providers import openrouter_decisions as decisions,typed_membership_runner
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import host_resources
from commentscope.providers.checkpoint_calls import run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import units,dollars
from commentscope.agents.runtime_probe import runtime_probe,runtime_check
from commentscope.storage import write_json_exclusive as write
from experiments import remote_factory_pipeline as executor
from tools import actual24_development
from tools import plan_factory_cost as cost_review
from commentscope.providers.generation_limits import allocate

VERSION='shared-factory-development-20261110-v1'
MAXIMUM='1.50'
TOOL_FILES=('tools/shared_factory_trial.py','tools/actual24_development.py','tools/plan_factory_cost.py')
ALIASES={'shared-discovery':'core','shared-owned-position':'argument-position-alignment',
         'nomination-raw':'membership-initial-raw','membership-expanded-raw':'membership-initial-raw'}
BATCH_ALIASES={**ALIASES,'membership-source-batch':'membership-initial-raw'}


def mapped_stage(stage):
    family=re.sub(r'-[a-f0-9]{20}$','',stage)
    return BATCH_ALIASES[family]+stage[len(family):] if family in BATCH_ALIASES else stage


def authorize(path,authorization_file,*,user_request):
    for name in (path,authorization_file):executor.private(name)
    if Path(path).exists() or not isinstance(user_request,str) or not user_request.strip():
        raise ValueError('Fresh explicit shared trial required')
    auth=read_json(authorization_file);owner=read_json(auth['money_owner']['file'])
    money=executor.ledger(read_json(owner['shared_policy_file']));summary=money.summary()
    scope=money.summary(plan_sha256=auth['money_owner']['sha256'])
    if (summary['reserved_calls'] or summary['uncertain_calls']
            or units(MAXIMUM)>min(units(owner['maximum_additional_usd'])-units(scope['charged_usd']),units(summary['remaining_usd']))):
        raise ValueError('Settled original scope/global money must cover the trial')
    trial={'artifact_kind':VERSION+'-authorization','user_request':user_request,
        'authorization_file':str(authorization_file),'authorization_sha256':sha(authorization_file),
        'money_owner_sha256':auth['money_owner']['sha256'],'maximum_usd':MAXIMUM,
        'opening_scope_charge_usd':scope['charged_usd'],'historical_charges_preserved':True,
        'started_at':datetime.now(timezone.utc).isoformat()}
    write(path,trial);return trial


def validate_trial(trial):
    if trial.get('artifact_kind')==VERSION+'-authorization':
        if trial.get('maximum_usd')!=MAXIMUM:raise ValueError('Original trial cap changed')
        return trial
    if trial.get('artifact_kind')!=VERSION+'-budget-extension':raise ValueError('Registered trial authorization required')
    parent=trial['base_trial'];original=read_json(parent['file'])
    if sha(parent['file'])!=parent['sha256'] or original!=parent['authorization']:
        raise ValueError('Original trial budget history changed')
    validate_trial(original)
    evidence=trial['budget_increase_evidence'];observed=read_json(evidence['file'])
    if sha(evidence['file'])!=evidence['sha256'] or observed!=evidence['observation']:
        raise ValueError('Budget-increase observation changed')
    additional=units(trial['additional_maximum_usd'])
    if (original['artifact_kind']!=VERSION+'-authorization' or not 0<additional<=units(MAXIMUM)
            or trial['money_owner_sha256']!=original['money_owner_sha256']
            or trial['opening_scope_charge_usd']!=original['opening_scope_charge_usd']
            or units(trial['authorized_scope_charge_usd'])<units(original['opening_scope_charge_usd'])
            or units(trial['maximum_usd'])!=units(trial['authorized_scope_charge_usd'])-units(original['opening_scope_charge_usd'])+additional
            or units(observed['key_metadata']['limit'])<=units('50')
            or units(observed['key_metadata']['limit_remaining'])<additional):
        raise ValueError('Explicit bounded extension must preserve original money history')
    return trial


def extend_budget(path,trial_file,authorization_file,budget_observation_file,*,additional_usd,user_request):
    for name in (path,trial_file,authorization_file,budget_observation_file):executor.private(name)
    if Path(path).exists() or not isinstance(user_request,str) or not user_request.strip():
        raise ValueError('Fresh explicit budget-increase request required')
    original=validate_trial(read_json(trial_file));auth=read_json(authorization_file)
    if original['artifact_kind']!=VERSION+'-authorization' or auth['money_owner']['sha256']!=original['money_owner_sha256']:
        raise ValueError('Budget extension must retain its original money owner')
    owner=read_json(auth['money_owner']['file']);money=executor.ledger(read_json(owner['shared_policy_file']))
    shared=money.summary();scope=money.summary(plan_sha256=original['money_owner_sha256']);additional=units(additional_usd)
    if (not 0<additional<=units(MAXIMUM) or shared['reserved_calls'] or shared['uncertain_calls']
            or units(scope['charged_usd'])<units(original['opening_scope_charge_usd'])
            or additional>min(units(owner['maximum_additional_usd'])-units(scope['charged_usd']),units(shared['remaining_usd']))):
        raise ValueError('Settled original owner/global money must cover the additional bound')
    observed=read_json(budget_observation_file)
    value={'artifact_kind':VERSION+'-budget-extension','user_request':user_request,
        'authorization_file':str(authorization_file),'authorization_sha256':sha(authorization_file),
        'money_owner_sha256':original['money_owner_sha256'],
        'maximum_usd':dollars(units(scope['charged_usd'])-units(original['opening_scope_charge_usd'])+additional),
        'opening_scope_charge_usd':original['opening_scope_charge_usd'],
        'authorized_scope_charge_usd':scope['charged_usd'],'additional_maximum_usd':dollars(additional),
        'base_trial':{'file':str(trial_file),'sha256':sha(trial_file),'authorization':original},
        'budget_increase_evidence':{'file':str(budget_observation_file),'sha256':sha(budget_observation_file),'observation':observed},
        'historical_charges_preserved':True,'started_at':datetime.now(timezone.utc).isoformat()}
    validate_trial(value);write(path,value);return value


def guard(plan,*,call_seconds=0,allow_expired=False):
    if plan.get('membership_search_policy') is not None:
        perspective_mining.policy(plan['membership_search_policy'])
        if plan.get('membership_batch_protocol'):
            raise ValueError('Candidate-first search requires scalar or typed membership')
    executor.guard(plan,call_seconds=call_seconds,allow_expired=allow_expired)
    binding=plan['trial'];trial=read_json(binding['file'])
    validate_trial(trial)
    if (sha(binding['file'])!=binding['sha256'] or trial!=binding['authorization']
            or not trial['user_request'].strip() or trial['historical_charges_preserved'] is not True
            or trial['authorization_sha256']!=plan['authorization']['sha256']
            or trial['money_owner_sha256']!=plan['spend_scope_sha256']
            or plan['opening_scope_charge_usd']!=trial['opening_scope_charge_usd']
            or plan['subcap_usd']!=trial['maximum_usd'] or plan['artifact_kind']!=VERSION or plan['mode']!='development'
            or plan['gate'] not in ('G1','G2','G3') or plan['formal_admission_eligible'] is not False
            or plan['quality_gate_passed'] is not False or plan['admission_file'] is not None
            or plan['discovery_mode']!='shared' or plan['membership_mode']!='raw'
            or plan['extraction_protocol'] is not None or plan['argument_audit_protocol']!=obs.SHARED_TYPED_CHAT
            or plan['agent_source_policy']!='candidate_verified_subset'
            or plan.get('membership_evidence_protocol') not in (None,executor.raw_membership_verification.QUALIFIED_CONTEXT)
            or plan.get('membership_batch_protocol') not in (None,source_membership_batch.VERSION)
            or plan.get('membership_judge_protocol') not in (None,jev_membership.VERSION)
            or plan.get('membership_deployment')!=(decisions.DEPLOYMENT if plan.get('membership_judge_protocol') else None)
            or plan.get('membership_judge_protocol') and plan.get('membership_batch_protocol')
            or plan['membership_retrieval_policy']!=cc.ALIAS_RETRIEVAL
            or plan['stage_aliases']!=(BATCH_ALIASES if plan.get('membership_batch_protocol') else ALIASES)):
        raise ValueError('Frozen shared development scope, roles or cumulative cap changed')


def prepare(directory,template_file,trial_file,*,gate='G2',scope_refresh_file=None,batch_membership=False,jev_judging=False,membership_search_policy=None):
    if membership_search_policy is not None:
        membership_search_policy = perspective_mining.policy(membership_search_policy)
        if batch_membership: raise ValueError('Candidate-first search cannot select chat batch')
    if type(jev_judging) is not bool or jev_judging and batch_membership:
        raise ValueError('Choose one explicit membership transport')
    if type(batch_membership) is not bool:raise ValueError('Explicit batch membership flag required')
    directory=Path(directory)
    for name in (directory,template_file,trial_file):executor.private(name)
    if directory.exists() or gate not in ('G1','G2','G3'):raise ValueError('Fresh supported shared run required')
    old=read_json(template_file);old_dir=Path(template_file).parent
    done=read_json(old_dir/'completed.json')
    if (old['artifact_kind']!=executor.VERSION or old['gate']!='G1' or old['mode']!='factory'
            or read_json(old_dir/'frozen.json')!={'plan_sha256':sha(template_file)}
            or done['plan_sha256']!=sha(template_file)
            or done['output_sha256']!=sha(old_dir/'artifacts/output.json')
            or any(sha(old_dir/'frozen-code'/path)!=expected for path,expected in old['code_sha256'].items())
            or old['classifier']!=executor.model_identity()):
        raise ValueError('Immutable original configuration and compatible fact runtime required')
    trial=read_json(trial_file);auth_file=Path(trial['authorization_file']);auth=read_json(auth_file)
    if gate in ('G2','G3'):
        if scope_refresh_file is None:raise ValueError('Fixed actual scope revalidation required')
        original,scope,registered=executor.fixed_scope(gate)
        snapshot,path,extra,binding=executor.revalidated_snapshot.bind(scope_refresh_file,original,sha(registered),scope)
        extra={str(registered):sha(registered),**extra}
    else:
        snapshot,scope,_=executor.fixed_scope('G1');path=directory/'snapshot.json';extra={};binding=None
        write(path,snapshot.to_dict())
    plan=deepcopy(old);files={p:sha(ROOT/p) for p in TOOL_FILES}
    inputs={**old['inputs'],**extra,str(template_file):sha(template_file),str(trial_file):sha(trial_file),
        str(auth_file):sha(auth_file),**files}
    plan.update(artifact_kind=VERSION,mode='development',gate=gate,run_directory=str(directory.resolve()),
        formal_admission_eligible=False,admission_file=None,quality_gate_passed=False,
        authorization={'file':str(auth_file),'sha256':sha(auth_file),'authorization':auth},
        trial={'file':str(trial_file),'sha256':sha(trial_file),'authorization':trial},
        subcap_usd=trial['maximum_usd'],opening_scope_charge_usd=trial['opening_scope_charge_usd'],
        discovery_mode='shared',membership_mode='raw',extraction_protocol=None,
        argument_audit_protocol=obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset',
        membership_retrieval_policy=cc.ALIAS_RETRIEVAL,stage_aliases=deepcopy(ALIASES),
        membership_evidence_protocol=executor.raw_membership_verification.QUALIFIED_CONTEXT,
        snapshot=str(path),snapshot_sha256=sha(path),scope_ids=scope,scope_refresh=binding,
        processing_count=len(scope),canonical_population=len(executor.sources(snapshot)),
        expires_at=snapshot.usage.expires_at,code_sha256=source_code_hashes(),inputs=inputs,
        shared_execution={'version':VERSION,'tool_files':files})
    if batch_membership:
        plan.update(membership_batch_protocol=source_membership_batch.VERSION,stage_aliases=deepcopy(BATCH_ALIASES))
    else:
        plan.pop('membership_batch_protocol',None)
    if jev_judging:
        plan.update(membership_judge_protocol=jev_membership.VERSION,membership_deployment=deepcopy(decisions.DEPLOYMENT))
    else:
        plan.pop('membership_judge_protocol',None);plan.pop('membership_deployment',None)
    if membership_search_policy is not None:
        plan['membership_search_policy']=deepcopy(membership_search_policy)
    else:
        plan.pop('membership_search_policy',None)
    guard(plan);executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    for d in plan['documents']:executor.fact_checks.live(d['expires_at'])
    plan['providers_at_prepare']={'generation':executor.provider_preflight(plan['deployment']),
        'verification':executor.provider_preflight(plan['verification_deployment']),
        'embedding':executor.embedding_preflight()}
    if jev_judging:plan['providers_at_prepare']['membership']=decisions.preflight(decisions.DEPLOYMENT)
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    executor.archive_sources(directory,plan['code_sha256']);executor.archive_sources(directory,files)
    validate(directory);return plan


def validate(directory):
    directory=Path(directory);plan=read_json(directory/'plan.json')
    if (read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['code_sha256']!=source_code_hashes() or any(sha(p)!=expected for p,expected in plan['inputs'].items())
            or plan['shared_execution']!={'version':VERSION,'tool_files':{p:sha(ROOT/p) for p in TOOL_FILES}}
            or plan['resource_policy']!=host_resources.HTTP_API_POLICY
            or plan['artifact_storage_policy']!=executor.api_resources.STORAGE_POLICY
            or plan['billing_policy']!=executor.remote.WIRE_BUDGET or plan['model_files']!={}
            or plan['classifier']!=executor.model_identity()
            or plan['verification_contract']!=executor.raw_membership_verification.FULL_SCOPE
            or plan['questions']!=executor.QUESTIONS or plan['schedule']!=minimal_pipeline.SCHEDULE
            or plan['reference_runtime_input'] is not False or plan['cross_run_response_reuse'] is not False):
        raise ValueError('Shared development implementation or evidence changed')
    guard(plan);run_origin(plan,directory,attempt=1)
    snapshot=load_snapshot(Path(plan['snapshot']))
    if snapshot.sha256!=plan['snapshot_sha256']:raise ValueError('Snapshot changed')
    if plan['gate'] in ('G2','G3'):
        original,scope,registered=executor.fixed_scope(plan['gate'])
        _,path,_,binding=executor.revalidated_snapshot.bind(plan['scope_refresh']['file'],original,sha(registered),scope)
        if (str(path)!=plan['snapshot'] or scope!=plan['scope_ids'] or binding!=plan['scope_refresh']):
            raise ValueError('Fixed actual source IDs/context changed')
    else:
        original,scope,_=executor.fixed_scope('G1')
        if original.to_dict()!=snapshot.snapshot.to_dict() or scope!=plan['scope_ids']:raise ValueError('Synthetic12 changed')
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    executor.acceptance.check_scope(executor.acceptance.from_plan(plan),plan['gate'],len(plan['scope_ids']),
        19 if plan['gate']=='G2' else 74 if plan['gate']=='G3' else 12)
    return plan


class Session(executor.RemoteSession):
    def __init__(self,directory,plan,dispatch,*,authorization_guard=None):
        super().__init__(directory,plan,dispatch,authorization_guard=guard if authorization_guard is None else authorization_guard)
        if plan.get('membership_judge_protocol'):
            self.membership_client,self.membership_checkpoint=typed_membership_runner.build(
                self.directory,plan,self.time,self.money,executor.key_metadata)

    def decide(self,stage,payload):
        if (not self.plan.get('membership_judge_protocol')
                or stage!='membership-jev-'+decisions.wire_sha256(payload,decisions.DEPLOYMENT)[:20]):
            raise ValueError('Typed membership is not selected in the frozen plan')
        self.dispatch.check();executor.check_quota();self.authorization_guard(self.plan,call_seconds=decisions.DEPLOYMENT['call_seconds'])
        if not jev_membership.measure(payload)['fits']:raise ValueError('Typed membership context exceeded')
        limits=getattr(self,'cost_limits',None)
        if limits is not None:limits.admit(stage,payload)
        self.storage.check()
        with self.dispatch.remote_call():
            result=self.membership_checkpoint.call(stage,payload,provider=self.membership_client.generate)
        self.storage.check();decisions.answers(payload,result,decisions.DEPLOYMENT)
        return result
    def call(self,stage,request):
        stage=mapped_stage(stage);limits=getattr(self,'cost_limits',None)
        if limits is not None:
            role=executor.remote.role(stage);key='generation' if role=='interaction' else role
            field='deployment' if key=='generation' else 'verification_deployment'
            actual=allocate(request,executor.openrouter.generation_allocation(self.plan[field],require_explicit=True))
            limits.admit(key+'-'+stage,actual)
        return super().call(stage,request)

    def embed(self,stage,texts):
        limits=getattr(self,'cost_limits',None)
        if limits is not None:
            for batch in executor.remote.batches(texts):
                req={'system':executor.remote.VERSION,'data':{'input':[p['text'] for p in batch]},'schema':{},'max_tokens':1}
                limits.admit('embedding-'+stage+'-'+digest(req)[:20],req)
        return super().embed(stage,texts)


class ProposalReady(Exception):pass


def run(directory,*,proposals_only=False,_validate=None,_kind=None,_session=None):
    # Registered development entry points supply their own closed scope/phase
    # validator. CLI callers retain this module's original fixed-sample guard.
    validate_plan=validate if _validate is None else _validate
    kind=VERSION if _kind is None else _kind
    session_type=Session if _session is None else _session
    directory=Path(directory)
    with experiment_lock(directory),executor.quota_watch():
        plan=validate_plan(directory)
        if (directory/'completed.json').exists():
            done=read_json(directory/'completed.json')
            if (done.get('artifact_kind')!=kind or done.get('formal_admission_eligible') is not False
                    or done.get('quality_gate_passed') is not False
                    or done['plan_sha256']!=sha(directory/'plan.json') or done['output_sha256']!=sha(directory/'artifacts/output.json')
                    or done['runtime_sha256']!=sha(directory/'artifacts/runtime.json')):raise ValueError('Completed artifacts changed')
            return done
        if proposals_only and (directory/'proposal-ready.json').exists():
            ready=read_json(directory/'proposal-ready.json')
            if (ready.get('artifact_kind')!=kind+'-proposal-ready' or ready.get('formal_admission_eligible') is not False
                    or ready['plan_sha256']!=sha(directory/'plan.json')
                    or ready['candidates_sha256']!=sha(directory/'artifacts/initial-candidates.json')
                    or ready['candidate_count']!=len(read_json(directory/'artifacts/initial-candidates.json'))):
                raise ValueError('Completed proposal artifacts changed')
            return ready
        limits=None if proposals_only else cost_review.require_review(directory,plan)
        attempt=len(list((directory/'attempts').glob('*.started.json')))+1
        origin=run_origin(plan,directory,attempt=attempt);dispatch=host_resources.RemoteCallGuard();session=session_type(directory,plan,dispatch)
        session.cost_limits=limits
        write(directory/'attempts'/f'{attempt:04}.started.json',{'at':datetime.now(timezone.utc).isoformat(),**origin})
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan artifact changed')
            else:session.storage.before_write(value);write(path,value)
            if proposals_only and name=='initial-candidates':raise ProposalReady()
        try:
            for d in (plan['deployment'],plan['verification_deployment']):executor.provider_preflight(d)
            executor.embedding_preflight()
            with host_resources.watch(directory/'resources'/f'{attempt:04}',plan['resource_policy'],
                    host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
                output=minimal_pipeline.process(load_snapshot(Path(plan['snapshot'])).snapshot,
                    session,session.embed,session.inspect,lambda req:session.call('facts-'+digest(req)[:20],req),
                    model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],scope_ids=plan['scope_ids'],save=save,
                    discovery_mode='shared',membership_mode='raw',verification_contract=plan['verification_contract'],
                    membership_evidence_protocol=plan.get('membership_evidence_protocol'),
                    membership_batch_protocol=plan.get('membership_batch_protocol'),
                    membership_judge_protocol=plan.get('membership_judge_protocol'),
                    membership_search_policy=plan.get('membership_search_policy'),
                    argument_audit_protocol=obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset')
                save('output',output)
                runtime=runtime_probe(output['agent_inputs']['bundle'],session,
                    save_turn=lambda row:save('runtime-turns/'+row['candidate_id']+'/'+row['question_id'],row))
                save('runtime',runtime);runtime_check(runtime,output['agent_inputs']['compiled'],questions=plan['questions'])
            done={'artifact_kind':kind,'execution_complete':True,'formal_admission_eligible':False,'quality_gate_passed':False,
                'plan_sha256':sha(directory/'plan.json'),'compiled_agents':len(output['agent_inputs']['compiled']['profiles']),
                'runtime_turns':len(runtime['turns']),'binding_errors':len(output['errors']),
                'capacity_holds':len(output['capacity_holds']),'unextracted':len(output['unextracted_source_ids']),
                'output_sha256':sha(directory/'artifacts/output.json'),'runtime_sha256':sha(directory/'artifacts/runtime.json'),
                'spending':session.money.summary(),'run_spending':session.money.summary(plan_sha256=plan['spend_scope_sha256']),**origin}
            write(directory/'completed.json',done);return done
        except ProposalReady:
            report={'artifact_kind':kind+'-proposal-ready','execution_complete':False,'formal_admission_eligible':False,
                'plan_sha256':sha(directory/'plan.json'),'candidate_count':len(read_json(directory/'artifacts/initial-candidates.json')),
                'candidates_sha256':sha(directory/'artifacts/initial-candidates.json'),'spending':session.money.summary()}
            write(directory/'proposal-ready.json',report);return report
        except BaseException as error:
            write(directory/'attempts'/f'{attempt:04}.failed.json',{'exception':type(error).__name__,'spending':session.money.summary()})
            raise


def main():
    p=argparse.ArgumentParser(description=__doc__);a=p.add_subparsers(dest='action',required=True)
    q=a.add_parser('authorize');q.add_argument('file',type=Path);q.add_argument('--authorization',type=Path,required=True);q.add_argument('--user-request',required=True)
    q=a.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--template',type=Path,required=True);q.add_argument('--trial',type=Path,required=True);q.add_argument('--gate',choices=('G1','G2','G3'),default='G2');q.add_argument('--scope-refresh',type=Path)
    q.add_argument('--batch-membership',action='store_true')
    q.add_argument('--jev-membership',action='store_true')
    q.add_argument('--mining-policy',type=Path)
    q=a.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--proposals-only',action='store_true');q.add_argument('--live',action='store_true',required=True);q.add_argument('--key-file',type=Path,required=True)
    args=p.parse_args()
    if args.action=='authorize':result=authorize(args.file,args.authorization,user_request=args.user_request)
    elif args.action=='prepare':
        plan=prepare(args.directory,args.template,args.trial,gate=args.gate,scope_refresh_file=args.scope_refresh,batch_membership=args.batch_membership,jev_judging=args.jev_membership,membership_search_policy=read_json(args.mining_policy) if args.mining_policy else None)
        result={'prepared':str(args.directory),'scope':len(plan['scope_ids']),'new_model_calls':0}
    else:
        os.environ['OPENROUTER_API_KEY']=args.key_file.read_text(encoding='utf-8').strip()
        result=run(args.directory,proposals_only=args.proposals_only)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
