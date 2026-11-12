"""Frozen fidelity validation under the already extended cumulative team credit.

One owner/window/request inventory; no per-experiment small cap, retries or
automatic model/criteria changes. Historical owners and charges stay intact.
"""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'src'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from commentscope.factory import source_evidence_graph as g,cost_planning as cost,fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import remote_verification as remote,host_resources
from commentscope.providers.openrouter_budget import SpendLedger,dollars
from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.execution_lock import experiment_lock
from commentscope.storage import write_json_exclusive as write
from experiments import remote_factory_pipeline as executor
from tools import prepare_source_fidelity_validation as preparation,source_evidence_trial as previous

VERSION='source-fidelity-cumulative-validation-20261112-v2'
OWNER_VERSIONS=('source-fidelity-cumulative-validation-20261112-v1',VERSION)
ALLOWED=('source-evidence-proposal','source-evidence-observation','source-evidence-candidates','core','core-fidelity','facts','runtime')


def reconcile(old_plan_file,output,*,user_request):
    """Apply an explicit audited account revision, never overwrite old policy."""
    output=Path(output).resolve();executor.private(output)
    if not user_request.strip():raise ValueError('Existing user credit/continuation instruction required')
    old=read_json(old_plan_file);policy=old['spend_policy'];metadata=executor.key_metadata()
    if metadata['limit']!=150:raise ValueError('Observed team credit differs from accepted150')
    with closing(sqlite3.connect(Path(policy['ledger']).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        current=db.execute('SELECT maximum FROM policy WHERE id=1').fetchone()[0]
    ledger=SpendLedger(policy['ledger'],policy['account_id'],maximum_usd=dollars(current),opening_charge_usd=policy['opening_charge_usd'])
    auth_file=output.with_name('credit-revision-authorization.json')
    if auth_file.exists():
        auth=read_json(auth_file)
        if auth['old_plan_sha256']!=sha(old_plan_file) or auth['user_request']!=user_request:raise ValueError('Credit revision binding changed')
    else:
        auth=dict(version=VERSION+'/credit',old_plan_sha256=sha(old_plan_file),user_request=user_request,
            account_id=policy['account_id'],ledger=policy['ledger'],opening_charge_usd=policy['opening_charge_usd'],
            new_maximum_usd='150',key_observation=metadata,created_at=datetime.now(timezone.utc).isoformat())
        write(auth_file,auth)
    revision=ledger.increase_limit(maximum_usd='150',observed_key_limit_usd=metadata['limit'],authorization_sha256=sha(auth_file),user_request=user_request)
    current_policy={**policy,'maximum_usd':'150'};preparation.freeze(output,current_policy)
    preparation.freeze(output.with_name('credit-revision-record.json'),revision)
    return dict(current_policy_file=str(output),revision=revision,account=ledger.summary(),key_metadata=metadata,new_model_calls=0)


def guard(plan,*,call_seconds=0,allow_expired=False):
    directory=Path(plan['run_directory'])
    if (read_json(directory/'plan.json')!=plan or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['code_sha256']!=source_code_hashes()):raise ValueError('Frozen validation plan/code changed')
    binding=plan['authorization'];auth=read_json(binding['file'])
    if sha(binding['file'])!=binding['sha256'] or auth!=binding['authorization']:raise ValueError('Cumulative authorization changed')
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    owner=binding
    if auth.get('money_owner'):
        owner=auth['money_owner'];original=read_json(owner['file'])
        if (sha(owner['file'])!=owner['sha256'] or original!=owner['authorization'] or original['version'] not in OWNER_VERSIONS
                or original['maximum_usd']!='150' or original['shared_policy_sha256']!=auth['shared_policy_sha256']
                or original['generation_deployment']!=auth['generation_deployment']
                or start<datetime.fromisoformat(original['started_at']) or end>datetime.fromisoformat(original['deadline'])):
            raise ValueError('Supplement cannot change original owner, credit or deadline')
    if (auth['version']!=VERSION or not auth['user_request'].strip() or auth['maximum_usd']!='150'
            or not timedelta(0)<end-start<=timedelta(hours=7) or plan['spend_scope_sha256']!=owner['sha256']
            or plan['maximum_cost_usd']!='150' or plan['subcap_usd']!='150' or plan['opening_scope_charge_usd']!='0'
            or plan['spend_policy']!=read_json(auth['shared_policy_file']) or sha(auth['shared_policy_file'])!=auth['shared_policy_sha256']
            or plan['spend_policy']['maximum_usd']!='150' or plan['source_evidence_protocol']!=g.VERSION
            or plan['verification_deployment']!=remote.SOL or plan['deployment']!=auth['generation_deployment']
            or plan['cross_run_response_reuse'] is not False or plan['maximum_physical_requests']!=800
            or plan.get('opening_scope_calls',0)!=auth.get('opening_scope_calls',0)
            or type(plan.get('opening_scope_calls',0)) is not int or not 0<=plan.get('opening_scope_calls',0)<=800
            or plan.get('opening_owner_charge_usd','0')!=auth.get('opening_owner_charge_usd','0')
            or plan['allowed_stage_families']!=list(ALLOWED) or auth.get('historical_charges_preserved') is not True):
        raise ValueError('Cumulative budget, scope or role contract changed')
    if not allow_expired and not start<=datetime.now(timezone.utc)<end-timedelta(seconds=call_seconds+3):raise TimeoutError('Fixed validation window expired')
    fact_checks.live(plan['expires_at'])
    for path,expected in plan['inputs'].items():
        if sha(Path(path))!=expected:raise ValueError('Frozen validation input/tool changed')
    money=executor.ledger(plan['spend_policy'])
    if Decimal(money.summary()['charged_usd'])<Decimal(auth['opening_account_charge_usd']):
        raise ValueError('Historical account charges regressed')
    owner_summary=money.summary(plan_sha256=plan['spend_scope_sha256'])
    if (Decimal(owner_summary['charged_usd'])<Decimal(auth.get('opening_owner_charge_usd','0'))
            or owner_summary['calls']<auth.get('opening_scope_calls',0)):
        raise ValueError('Historical owner charges or calls regressed')


def prepare(directory,old_plan_file,packet_file,policy_file,*,user_request,money_owner=None):
    directory=Path(directory).resolve();executor.private(directory)
    if directory.exists() or not user_request.strip():raise ValueError('New fixed execution directory/instruction required')
    old=read_json(old_plan_file);packet=read_json(packet_file);policy=read_json(policy_file)
    preparation.validate_controls(packet['controls'])
    for path,expected in packet['inputs'].items():
        if sha(Path(path))!=expected:raise ValueError('Planning inputs changed')
    if policy!={**old['spend_policy'],'maximum_usd':'150'}:raise ValueError('Same historical account/opening/ledger required')
    account=executor.ledger(policy).summary();key=executor.key_metadata()
    if account['reserved_calls'] or account['uncertain_calls']:raise BudgetExhausted('Prior uncertain money needs reconciliation')
    review=preparation.cost_review(packet['controls'],proposed_usd=account['remaining_usd'],account_remaining_usd=account['remaining_usd'],key_remaining_usd=key['limit_remaining'])
    if key['limit']!=150 or not review['controls_fit']:raise BudgetExhausted('Cumulative balance cannot cover whole controls')
    endpoints={'generation':executor.provider_preflight(old['deployment']),'verification':executor.provider_preflight(remote.SOL)}
    now=datetime.now(timezone.utc)
    parent=None;deadline=now+timedelta(hours=7)
    if money_owner is not None:
        original=read_json(money_owner)
        if (original['version'] not in OWNER_VERSIONS or original['maximum_usd']!='150'
                or original['shared_policy_sha256']!=sha(policy_file) or original['generation_deployment']!=old['deployment']):
            raise ValueError('Existing cumulative owner must match account and generation')
        parent=dict(file=str(Path(money_owner).resolve()),sha256=sha(money_owner),authorization=original)
        deadline=datetime.fromisoformat(original['deadline'])
        if not now<deadline-timedelta(seconds=183):raise TimeoutError('Original owner window expired')
    opening_owner=executor.ledger(policy).summary(plan_sha256=parent['sha256']) if parent else {'calls':0,'charged_usd':'0'}
    auth=dict(version=VERSION,user_request=user_request,started_at=now.isoformat(),deadline=(now+timedelta(hours=7)).isoformat(),
        maximum_usd='150',shared_policy_file=str(Path(policy_file).resolve()),shared_policy_sha256=sha(policy_file),
        opening_account_charge_usd=account['charged_usd'],generation_deployment=old['deployment'],
        historical_owner=old['spend_scope_sha256'],historical_charges_preserved=True,key_observation=key)
    auth['deadline']=deadline.isoformat();auth['opening_scope_calls']=opening_owner['calls']
    auth['opening_owner_charge_usd']=opening_owner['charged_usd']
    if parent:auth['money_owner']=parent
    write(directory/'authorization.json',auth);binding=dict(file=str(directory/'authorization.json'),sha256=sha(directory/'authorization.json'),authorization=auth)
    inputs={**packet['inputs'],str(Path(old_plan_file).resolve()):sha(old_plan_file),str(Path(packet_file).resolve()):sha(packet_file),
        str(Path(__file__).resolve()):sha(Path(__file__)),str(ROOT/'tools/source_evidence_trial.py'):sha(ROOT/'tools/source_evidence_trial.py')}
    if parent:inputs[parent['file']]=parent['sha256']
    plan={**deepcopy(old), 'artifact_kind':VERSION,'arm':'B-'+g.VERSION.rsplit('-',1)[-1],'run_directory':str(directory),'authorization':binding,
        'spend_policy':policy,'spend_scope_sha256':parent['sha256'] if parent else binding['sha256'],'maximum_cost_usd':'150','subcap_usd':'150',
        'opening_scope_charge_usd':'0','source_evidence_protocol':g.VERSION,'inputs':inputs,'code_sha256':source_code_hashes(),
        'verification_deployment':deepcopy(remote.SOL),'role_registry':deepcopy(remote.ROLES),
        'controls_packet':str(Path(packet_file).resolve()),'maximum_physical_requests':800,
        'limits':{'analysis_seconds':None,'call_seconds':180},'cross_run_response_reuse':False,
        'allowed_stage_families':list(ALLOWED),'eligible_source_ids':[r['source']['id'] for r in packet['source_inventory']['sources']],
        'component_profiling_only':True,'formal_admission_eligible':False,'quality_gate_passed':False,'providers_at_prepare':endpoints}
    plan.update(opening_scope_calls=opening_owner['calls'],opening_owner_charge_usd=opening_owner['charged_usd'])
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    executor.archive_sources(directory,plan['code_sha256'])
    guard(plan)
    return dict(run_directory=str(directory),controls=len(packet['controls']['cases']),cumulative_maximum_usd='150',small_subcap_usd=None,new_model_calls=0)


class Session(executor.RemoteSession):
    def __init__(self,directory,plan,dispatch):
        super().__init__(directory,plan,dispatch,authorization_guard=guard)
        self.seen=set();self.phase='controls';packet=read_json(plan['controls_packet'])
        self.control_requests={r['request_sha256'] for r in packet['controls']['cases']}
        self.pilot_ids={r['source_id'] for r in packet['source_inventory']['representative_profiling']}

    def call(self,stage,request):
        if self.phase not in ('controls','profiling','factory'):raise ValueError('Unregistered validation phase')
        family=cost.canonical(stage,request);key=(family,digest(request))
        if family not in ALLOWED:raise ValueError('Stage outside fixed validation')
        if self.phase=='controls':
            if family!='source-evidence-observation' or digest(request) not in self.control_requests:raise ValueError('Unregistered control request')
        elif family.startswith('source-evidence-'):
            sid=request.get('data',{}).get('ORIGINAL',{}).get('source_id')
            allowed=self.pilot_ids if self.phase=='profiling' else set(self.plan['eligible_source_ids'])
            if sid not in allowed:raise ValueError('Source outside frozen validation inventory')
        elif self.phase!='factory':raise ValueError('Only graph profiling allowed before Factory')
        if key not in self.seen and self.plan.get('opening_scope_calls',0)+len(self.seen)>=800:raise BudgetExhausted('Frozen physical request inventory cap')
        self.seen.add(key)
        return super().call(family+'-'+digest(request)[:20],request)


def run(directory):
    directory=Path(directory)
    if (directory/'completed.json').exists():
        done=read_json(directory/'completed.json')
        if (done['plan_sha256']!=sha(directory/'plan.json') or any(sha(directory/p)!=h for p,h in done['artifacts'].items())
                or read_json(directory/'artifacts/validation-report.json')!=done['report']):raise ValueError('Completed validation changed')
        return done['report']
    plan=read_json(directory/'plan.json');guard(plan)
    if plan['code_sha256']!=source_code_hashes() or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}:raise ValueError('Frozen validation code/plan changed')
    executor.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),executor.quota_watch():
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch)
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan validation artifact changed')
            else:session.storage.before_write(value);write(path,value)
        packet=read_json(plan['controls_packet']);answers={};pilot=[]
        with host_resources.watch(previous.resource_attempt(directory),plan['resource_policy'],host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
            for row in packet['controls']['cases']:
                result=session.call('source-evidence-observation',row['request']);answers[row['case_id']]=result;save('controls/'+row['case_id'],result)
            score=preparation.score_controls(packet['controls'],answers);save('control-score',score)
            if score['next_stage_ready']:
                session.phase='profiling';snapshot=load_snapshot(Path(plan['snapshot'])).snapshot
                registry=read_json(Path(plan['baseline_artifacts'])/'source-discourse.json')
                for row in packet['source_inventory']['representative_profiling']:
                    sid=row['source_id'];env=g.envelope(registry[sid]['source'],snapshot_id=snapshot.snapshot_id,snapshot_sha256=digest(snapshot.to_dict()))
                    try:
                        p=g.bind_proposal(env,session.call('source-evidence-proposal',g.proposal_request(env)))
                        verified=g.verify(p,g.bind_observation(p,session.call('source-evidence-observation',g.observation_request(p))))
                        save('profiling/'+sid,verified);pilot.append(dict(source_id=sid,status=verified['status']))
                    except (ValueError,KeyError,TypeError) as exc:
                        pilot.append(dict(source_id=sid,status='binding_error',exception=type(exc).__name__))
                save('profiling-summary',pilot)
        factory=None
        if score['next_stage_ready']:
            session.phase='factory';factory=previous.execute_factory(directory,plan,session,dispatch,complete=False)
        owner_total=session.money.summary(plan_sha256=plan['spend_scope_sha256'])
        report=dict(version=VERSION,controls={k:v for k,v in score.items() if k!='rows'},profiling=pilot,factory=factory,
            account=executor.ledger(plan['spend_policy']).summary(),validation_charge=session.money.summary(plan_sha256=plan['spend_scope_sha256']),
            supplement_charge_delta_usd=str(Decimal(owner_total['charged_usd'])-Decimal(plan.get('opening_owner_charge_usd','0'))),
            cumulative_maximum_usd='150',small_subcap_usd=None,formal_admission=False,semantic_adoption=False,requires_source_review=True)
        save('validation-report',report)
        write(directory/'completed.json',dict(plan_sha256=sha(directory/'plan.json'),report=report,
            artifacts={str(p.relative_to(directory)):sha(p) for p in sorted((directory/'artifacts').rglob('*.json'))}))
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--key-file',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('reconcile');p.add_argument('--old-plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--user-request',required=True)
    p=sub.add_parser('prepare');p.add_argument('directory',type=Path);p.add_argument('--old-plan',type=Path,required=True);p.add_argument('--packet',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--user-request',required=True);p.add_argument('--money-owner',type=Path)
    p=sub.add_parser('run');p.add_argument('directory',type=Path);args=parser.parse_args()
    if args.key_file:os.environ['OPENROUTER_API_KEY']=args.key_file.read_text(encoding='utf-8').strip()
    if args.action=='reconcile':result=reconcile(args.old_plan,args.output,user_request=args.user_request)
    elif args.action=='prepare':result=prepare(args.directory,args.old_plan,args.packet,args.policy,user_request=args.user_request,money_owner=args.money_owner)
    else:
        report=run(args.directory);factory=report.get('factory') or {}
        result=dict(controls=report['controls'],profiling_sources=len(report['profiling']),
            profiles=factory.get('profiles'),runtime_turns=factory.get('runtime_turns'),
            validation_charge=report['validation_charge'],account=report['account'],semantic_adoption=False)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
