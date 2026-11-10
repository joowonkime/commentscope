"""Registered whole-cohort development; never substitutes fixed G1/G2 samples."""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from tools import shared_factory_trial as trial,cohort_refresh
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.factory.framed_corpus import sources
from commentscope.providers.openrouter_budget import units
from commentscope.storage import write_json_exclusive as write

executor=trial.executor
VERSION='registered-wide-mining-development-20261111-v1'
AUTH=VERSION+'-authorization'
GATE='development-wide'
MAXIMUM='15'
POLICY={'version':trial.perspective_mining.VERSION,'sources_per_candidate':16,
        'maximum_pairs':1536,'maximum_sources':120,'maximum_snapshot_comments':3000}
TOOL_FILES=('tools/wide_mining_trial.py','tools/shared_factory_trial.py','tools/cohort_refresh.py','tools/plan_factory_cost.py')


def authorization(auth,*,call_seconds=0,allow_expired=False):
    parent=auth['parent_money_owner'];original=read_json(parent['file'])
    if sha(parent['file'])!=parent['sha256']:raise ValueError('Original money history changed')
    executor.scoped_authorization.guard(original,allow_expired=True)
    evidence=auth['key_observation'];observed=read_json(evidence['file'])
    if sha(evidence['file'])!=evidence['sha256'] or observed!=evidence['observation']:
        raise ValueError('Explicit team budget observation changed')
    policy=executor.validate_spend_policy(read_json(auth['shared_policy_file']))
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if (auth.get('version')!=AUTH or auth.get('tasks')!=['TASK-018'] or auth.get('gate')!=GATE
            or not isinstance(auth.get('user_request'),str) or not auth['user_request'].strip()
            or auth.get('historical_charges_preserved') is not True
            or auth['shared_policy_sha256']!=sha(auth['shared_policy_file'])
            or policy!=read_json(original['shared_policy_file'])
            or not 0<units(auth['maximum_additional_usd'])<=units(MAXIMUM)
            or units(auth['maximum_additional_usd'])>units(auth['opening_account_remaining_usd'])
            or units(observed['key_metadata']['limit'])<units('150')
            or units(observed['key_metadata']['limit_remaining'])<units(auth['maximum_additional_usd'])
            or auth['generation_deployment']!=original['chat_deployment']
            or auth['retries']!=0 or auth['fallback'] is not None
            or start.utcoffset() is None or end.utcoffset() is None
            or not timedelta(0)<end-start<=timedelta(hours=7)):
        raise ValueError('Closed whole-pool phase and unchanged money history required')
    money=executor.ledger(policy);shared=money.summary();old=money.summary(plan_sha256=parent['sha256'])
    if (units(shared['charged_usd'])<units(auth['opening_account_charge_usd'])
            or units(old['charged_usd'])<units(auth['opening_parent_scope_charge_usd'])):
        raise ValueError('Prior account or owner charge cannot be refunded')
    if not allow_expired and not start<=datetime.now(timezone.utc)<end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Wide phase cannot cover the next bounded request')
    return policy


def authorize(path,parent_file,cohort_file,observation_file,*,maximum_usd=MAXIMUM,user_request):
    for p in (path,parent_file,cohort_file,observation_file):executor.private(p)
    if Path(path).exists():raise ValueError('Never replace a phase grant')
    original=read_json(parent_file);executor.scoped_authorization.guard(original,allow_expired=True)
    snapshot,_,_,cohort=cohort_refresh.bind(cohort_file)
    if len(sources(snapshot))!=999:raise ValueError('Registered whole999 required')
    policy=executor.validate_spend_policy(read_json(original['shared_policy_file']))
    money=executor.ledger(policy);shared=money.summary();old=money.summary(plan_sha256=sha(parent_file))
    if (shared['reserved_calls'] or shared['uncertain_calls']
            or not 0<units(maximum_usd)<=min(units(MAXIMUM),units(shared['remaining_usd']))):
        raise ValueError('Settled shared account must cover the additional phase')
    now=datetime.now(timezone.utc)
    auth={'version':AUTH,'tasks':['TASK-018'],'gate':GATE,'user_request':user_request,
          'started_at':now.isoformat(),'deadline':(now+timedelta(hours=7)).isoformat(),
          'maximum_additional_usd':str(maximum_usd),'opening_account_charge_usd':shared['charged_usd'],
          'opening_account_remaining_usd':shared['remaining_usd'],'opening_parent_scope_charge_usd':old['charged_usd'],
          'shared_policy_file':original['shared_policy_file'],'shared_policy_sha256':sha(original['shared_policy_file']),
          'parent_money_owner':{'file':str(Path(parent_file).resolve()),'sha256':sha(parent_file)},
          'key_observation':{'file':str(Path(observation_file).resolve()),'sha256':sha(observation_file),
                             'observation':read_json(observation_file)},
          'generation_deployment':deepcopy(original['chat_deployment']),'cohort':cohort,
          'historical_charges_preserved':True,'retries':0,'fallback':None}
    authorization(auth);write(path,auth);return auth


def guard(plan,*,call_seconds=0,allow_expired=False):
    binding=plan['authorization'];auth=read_json(binding['file'])
    if sha(binding['file'])!=binding['sha256'] or auth!=binding['authorization']:
        raise ValueError('Wide authorization changed')
    policy=authorization(auth,call_seconds=call_seconds,allow_expired=allow_expired)
    if (plan['artifact_kind']!=VERSION or plan['mode']!='development' or plan['gate']!=GATE
            or plan['formal_admission_eligible'] is not False or plan['quality_gate_passed'] is not False
            or plan['admission_file'] is not None or plan['spend_scope_sha256']!=binding['sha256']
            or plan['spend_policy']!=policy or plan['maximum_cost_usd']!=auth['maximum_additional_usd']
            or plan['subcap_usd']!=auth['maximum_additional_usd'] or plan['opening_scope_charge_usd']!='0'
            or plan['deployment']!=auth['generation_deployment'] or plan['verification_deployment']!=executor.remote.SOL
            or plan['embedding_deployment']!=executor.remote.EMBEDDING or plan['role_registry']!=executor.remote.ROLES
            or plan['membership_deployment']!=trial.decisions.DEPLOYMENT
            or plan['membership_judge_protocol']!=trial.jev_membership.VERSION
            or plan['membership_search_policy']!=POLICY or plan.get('membership_batch_protocol') is not None
            or plan['argument_audit_protocol']!=trial.obs.SHARED_TYPED_CHAT
            or plan['agent_source_policy']!='candidate_verified_subset' or plan['extraction_protocol'] is not None
            or plan['membership_retrieval_policy']!=trial.cc.ALIAS_RETRIEVAL
            or plan['discovery_mode']!='shared' or plan['membership_mode']!='raw'
            or plan['membership_evidence_protocol']!=executor.raw_membership_verification.QUALIFIED_CONTEXT
            or plan['stage_aliases']!=trial.ALIASES or plan['cohort_refresh']!=auth['cohort']
            or plan['processing_count']!=999 or plan['canonical_population']!=999
            or len(plan['scope_ids'])!=999 or len(set(plan['scope_ids']))!=999):
        raise ValueError('Closed full-input development contract changed')


def prepare(directory,template_file,auth_file):
    directory=Path(directory)
    for p in (directory,template_file,auth_file):executor.private(p)
    if directory.exists():raise ValueError('Fresh registered wide run required')
    auth=read_json(auth_file);policy=authorization(auth)
    snapshot,path,inputs,cohort=cohort_refresh.bind(auth['cohort']['file'])
    original=read_json(template_file);done=read_json(Path(template_file).parent/'completed.json')
    if (original['artifact_kind']!=executor.VERSION or original['mode']!='factory' or original['gate']!='G1'
            or done['plan_sha256']!=sha(template_file)
            or done['output_sha256']!=sha(Path(template_file).parent/'artifacts/output.json')
            or any(sha(Path(template_file).parent/'frozen-code'/p)!=h for p,h in original['code_sha256'].items())
            or original['classifier']!=executor.model_identity() or cohort!=auth['cohort']):
        raise ValueError('Original configuration or registered cohort changed')
    ids=sorted(sources(snapshot))
    if len(ids)!=999:raise ValueError('Do not replace the whole input with G1/G2 samples')
    plan=deepcopy(original);files={p:sha(ROOT/p) for p in TOOL_FILES}
    inputs={**original['inputs'],**inputs,str(template_file):sha(template_file),str(auth_file):sha(auth_file),**files}
    plan.update(artifact_kind=VERSION,mode='development',gate=GATE,run_directory=str(directory.resolve()),
        authorization={'file':str(auth_file),'sha256':sha(auth_file),'authorization':auth},
        spend_scope_sha256=sha(auth_file),spend_policy=policy,maximum_cost_usd=auth['maximum_additional_usd'],
        subcap_usd=auth['maximum_additional_usd'],opening_scope_charge_usd='0',
        formal_admission_eligible=False,quality_gate_passed=False,admission_file=None,
        discovery_mode='shared',membership_mode='raw',extraction_protocol=None,
        argument_audit_protocol=trial.obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset',
        membership_retrieval_policy=trial.cc.ALIAS_RETRIEVAL,stage_aliases=deepcopy(trial.ALIASES),
        membership_evidence_protocol=executor.raw_membership_verification.QUALIFIED_CONTEXT,
        membership_judge_protocol=trial.jev_membership.VERSION,membership_deployment=deepcopy(trial.decisions.DEPLOYMENT),
        membership_search_policy=deepcopy(POLICY),snapshot=str(path),snapshot_sha256=sha(path),scope_ids=ids,
        canonical_population=999,processing_count=999,cohort_refresh=cohort,scope_refresh=cohort['base_scope_refresh'],
        expires_at=snapshot.usage.expires_at,code_sha256=source_code_hashes(),inputs=inputs,
        wide_execution={'version':VERSION,'tool_files':files})
    for field in ('trial','shared_execution','scoped_authorization','execution_cycle','membership_batch_protocol'):
        plan.pop(field,None)
    guard(plan);executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    for doc in plan['documents']:executor.fact_checks.live(doc['expires_at'])
    plan['providers_at_prepare']={'generation':executor.provider_preflight(plan['deployment']),
        'verification':executor.provider_preflight(plan['verification_deployment']),
        'embedding':executor.embedding_preflight(),'membership':trial.decisions.preflight(trial.decisions.DEPLOYMENT)}
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    executor.archive_sources(directory,plan['code_sha256']);executor.archive_sources(directory,files)
    validate(directory);return plan


def validate(directory):
    directory=Path(directory);executor.private(directory);plan=read_json(directory/'plan.json')
    if (read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['code_sha256']!=source_code_hashes() or any(sha(p)!=h for p,h in plan['inputs'].items())
            or plan['wide_execution']!={'version':VERSION,'tool_files':{p:sha(ROOT/p) for p in TOOL_FILES}}
            or plan['resource_policy']!=trial.host_resources.HTTP_API_POLICY
            or plan['artifact_storage_policy']!=executor.api_resources.STORAGE_POLICY
            or plan['billing_policy']!=executor.remote.WIRE_BUDGET or plan['model_files']!={}
            or plan['classifier']!=executor.model_identity() or plan['questions']!=executor.QUESTIONS
            or plan['verification_contract']!=executor.raw_membership_verification.FULL_SCOPE
            or plan['schedule']!=trial.minimal_pipeline.SCHEDULE
            or plan['reference_runtime_input'] is not False or plan['cross_run_response_reuse'] is not False):
        raise ValueError('Frozen wide implementation/input contract changed')
    guard(plan);trial.run_origin(plan,directory,attempt=1)
    snapshot,path,_,cohort=cohort_refresh.bind(plan['cohort_refresh']['file'])
    if (cohort!=plan['cohort_refresh'] or str(path)!=plan['snapshot'] or sha(path)!=plan['snapshot_sha256']
            or sorted(sources(snapshot))!=plan['scope_ids']):raise ValueError('Whole registered999 scope changed')
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent,plan,[])
    return plan


class Session(trial.Session):
    def __init__(self,directory,plan,dispatch):
        super().__init__(directory,plan,dispatch,authorization_guard=guard)


def run(directory,*,proposals_only=False):
    return trial.run(directory,proposals_only=proposals_only,_validate=validate,_kind=VERSION,_session=Session)


def main():
    p=argparse.ArgumentParser(description=__doc__);a=p.add_subparsers(dest='action',required=True)
    q=a.add_parser('authorize');q.add_argument('file',type=Path);q.add_argument('--parent',type=Path,required=True)
    q.add_argument('--cohort',type=Path,required=True);q.add_argument('--observation',type=Path,required=True)
    q.add_argument('--maximum-usd',default=MAXIMUM);q.add_argument('--user-request',required=True)
    q=a.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--template',type=Path,required=True);q.add_argument('--authorization',type=Path,required=True)
    q=a.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--proposals-only',action='store_true');q.add_argument('--live',action='store_true');q.add_argument('--key-file',type=Path)
    args=p.parse_args()
    if args.action=='authorize':result=authorize(args.file,args.parent,args.cohort,args.observation,maximum_usd=args.maximum_usd,user_request=args.user_request)
    elif args.action=='prepare':
        plan=prepare(args.directory,args.template,args.authorization);result={'scope':len(plan['scope_ids']),'plan_sha256':sha(args.directory/'plan.json'),'new_model_calls':0}
    else:
        if not args.live or not args.key_file:p.error('Paid execution requires explicit --live and private key file')
        os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip();result=run(args.directory,proposals_only=args.proposals_only)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
