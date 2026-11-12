"""Frozen F4/Compiler/runtime comparison on an archived real membership map.

Fresh F4 responses, shared finite money owner; not a fresh whole-corpus run.
No retries, fallback, source rewriting or semantic-gate promotion.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'src'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from commentscope.factory import pipeline_stages, argument_observations as obs, source_evidence_graph as graph
from commentscope.factory import raw_membership_verification as raw, cost_planning as cost, fact_checks
from commentscope.factory.pipeline_work import PipelineWork
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write
from commentscope.providers import host_resources, api_resources, remote_verification as remote
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.budget import BudgetExhausted
from commentscope.agents.runtime_probe import runtime_probe, runtime_check
from experiments import remote_factory_pipeline as executor

VERSION='source-evidence-f4-comparison-20261112-v1'
ARMS=('B','A','C')


def archived_input(baseline_file,value,expected):
    candidates=[Path(value),*(parent/value for parent in Path(baseline_file).resolve().parents)]
    for path in candidates:
        if path.is_file() and sha(path)==expected:return path.resolve()
    raise ValueError('Archived input missing or changed: '+value)


def guard(plan,*,call_seconds=0,allow_expired=False):
    binding=plan['authorization'];auth=read_json(binding['file'])
    if sha(binding['file'])!=binding['sha256'] or auth!=binding['authorization']:raise ValueError('Comparison authorization changed')
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if (auth['version']!=VERSION or not auth['user_request'].strip() or not Decimal(0)<Decimal(auth['maximum_usd'])<=Decimal(5)
            or not timedelta(0)<end-start<=timedelta(hours=7) or auth['historical_charges_preserved'] is not True
            or plan['spend_scope_sha256']!=binding['sha256'] or plan['maximum_cost_usd']!=auth['maximum_usd']
            or plan['subcap_usd']!=auth['maximum_usd'] or plan['spend_policy']!=read_json(auth['shared_policy_file'])
            or sha(auth['shared_policy_file'])!=auth['shared_policy_sha256']
            or plan['cross_run_response_reuse'] is not False or plan['arm'] not in ARMS):
        raise ValueError('Frozen comparison scope/money required')
    now=datetime.now(timezone.utc)
    if not allow_expired and not start<=now<end-timedelta(seconds=call_seconds+3):raise TimeoutError('Comparison window expired')
    fact_checks.live(plan['expires_at'])
    for field,expected in plan['inputs'].items():
        if sha(field)!=expected:raise ValueError('Comparison input/tool changed')
    if plan['verification_deployment']!=remote.SOL:raise ValueError('Comparison reviewer changed')
    if plan['source_evidence_protocol']!=(None if plan['arm']=='A' else graph.VERSION):raise ValueError('Comparison protocol changed')
    expected=auth['generation_deployment'] if plan['arm']!='C' else remote.SOL
    if plan['deployment']!=expected:raise ValueError('Comparison generation role changed')
    if Decimal(executor.ledger(plan['spend_policy']).summary()['charged_usd'])<Decimal(auth['opening_account_charge_usd']):
        raise ValueError('Historical account charge regressed')


def prepare(directory, baseline_file, annotations_file, *, user_request, maximum_usd='5.00'):
    directory=Path(directory).resolve();executor.private(directory)
    partial=directory.exists() and {p.name for p in directory.iterdir()}=={'authorization.json'}
    if directory.exists() and not partial or not user_request.strip() or not Decimal(0)<Decimal(maximum_usd)<=5:raise ValueError('New finite comparison directory required')
    baseline_file=Path(baseline_file).resolve();old=read_json(baseline_file);a=read_json(annotations_file)
    if not a['cases'] or a['reviewer_kind']!='coding_agent_not_independent_human_gold':raise ValueError('Frozen source-target expectations required')
    artifacts=baseline_file.parent/'artifacts'
    expected={(p['id'],sid) for p in read_json(artifacts/'map.json')['opinion_map']['perspectives'] if p['minimum_support_met'] for sid in p['supported_canonical_ids']}
    actual=[(r['candidate_id'],r['source_id']) for r in a['cases']]
    if set(actual)!=expected or len(set(actual))!=len(actual):raise ValueError('Every eligible source-target relation must be annotated')
    snapshot=archived_input(baseline_file,old['snapshot'],old['snapshot_sha256'])
    inputs={str(baseline_file):sha(baseline_file),str(Path(annotations_file).resolve()):sha(annotations_file),str(ROOT/'tools/source_evidence_trial.py'):sha(ROOT/'tools/source_evidence_trial.py')}
    for name in ('candidates','memberships','source-discourse','map'):inputs[str(artifacts/(name+'.json'))]=sha(artifacts/(name+'.json'))
    inputs[str(snapshot)]=sha(snapshot)
    policy=executor.validate_spend_policy(old['spend_policy']);account=executor.ledger(policy).summary()
    if account['reserved_calls'] or account['uncertain_calls']:raise BudgetExhausted('Prior charge unresolved')
    if Decimal(account['remaining_usd'])<Decimal(maximum_usd):raise BudgetExhausted('Shared account cannot cover comparison cap')
    metadata=executor.key_metadata()
    if Decimal(str(metadata['limit_remaining']))<Decimal(maximum_usd):raise BudgetExhausted('Team key cannot cover comparison cap')
    providers={'generation':executor.provider_preflight(old['deployment']),'verification':executor.provider_preflight(remote.SOL)}
    now=datetime.now(timezone.utc);auth=dict(version=VERSION,user_request=user_request,started_at=now.isoformat(),deadline=(now+timedelta(hours=7)).isoformat(),
        maximum_usd=maximum_usd,shared_policy_file=old['authorization']['authorization']['shared_policy_file'],
        shared_policy_sha256=old['authorization']['authorization']['shared_policy_sha256'],generation_deployment=old['deployment'],
        historical_charges_preserved=True,opening_account_charge_usd=account['charged_usd'],previous_owner=deepcopy(old['authorization']),key_observation=metadata)
    if partial:
        previous=read_json(directory/'authorization.json')
        if (previous['version']!=VERSION or previous['user_request']!=user_request or previous['maximum_usd']!=maximum_usd
                or previous['generation_deployment']!=old['deployment']
                or executor.ledger(policy).summary(plan_sha256=sha(directory/'authorization.json'))['calls']!=0):
            raise ValueError('Cannot repair a used or changed partial authorization')
        auth=previous  # Preserve the originally started deadline and money owner.
    else:write(directory/'authorization.json',auth)
    binding=dict(file=str(directory/'authorization.json'),sha256=sha(directory/'authorization.json'),authorization=auth)
    for arm in ARMS:
        p=deepcopy(old);p.update(artifact_kind=VERSION,run_directory=str(directory/arm),arm=arm,authorization=binding,
            deployment=deepcopy(remote.SOL if arm=='C' else old['deployment']),verification_deployment=deepcopy(remote.SOL),role_registry=deepcopy(remote.ROLES),
            spend_scope_sha256=binding['sha256'],maximum_cost_usd=maximum_usd,subcap_usd=maximum_usd,opening_scope_charge_usd='0',
            inputs=inputs,code_sha256=source_code_hashes(),baseline_artifacts=str(artifacts),annotations=str(Path(annotations_file).resolve()),
            snapshot=str(snapshot),
            expires_at=old['expires_at'],limits={'analysis_seconds':None,'call_seconds':180},maximum_physical_requests=700 if arm=='A' else 140,
            source_evidence_protocol=None if arm=='A' else graph.VERSION,cross_run_response_reuse=False,archived_membership_inputs_reused=True,
            component_profiling_only=True,formal_admission_eligible=False,quality_gate_passed=False,providers_at_prepare=providers)
        write(directory/arm/'plan.json',p);write(directory/arm/'frozen.json',{'plan_sha256':sha(directory/arm/'plan.json')})
        executor.archive_sources(directory/arm,p['code_sha256'])
    write(directory/'comparison.json',dict(version=VERSION,arms=list(ARMS),authorization=binding,inputs=inputs,
        purpose='Bounded F4 profiling/comparison; full48/holdout and whole999 remain separate',maximum_total_usd=maximum_usd,
        worst_case_full_matrix_usd=None,completion_guaranteed=False))
    return dict(arms=list(ARMS),eligible_pairs=len(expected),model_calls=0,maximum_total_usd=maximum_usd,deadline=auth['deadline'])


class Session(executor.RemoteSession):
    def __init__(self,directory,plan,dispatch):
        super().__init__(directory,plan,dispatch,authorization_guard=guard);self.seen=set()
    def call(self,stage,request):
        family=cost.canonical(stage,request);key=(family,digest(request))
        if key not in self.seen and len(self.seen)>=self.plan['maximum_physical_requests']:raise BudgetExhausted('Frozen physical request cap')
        self.seen.add(key)
        return super().call(family+'-'+digest(request)[:20],request)


def validate(directory):
    directory=Path(directory);p=read_json(directory/'plan.json');guard(p)
    if (p['run_directory']!=str(directory.resolve()) or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or p['code_sha256']!=source_code_hashes()):raise ValueError('Frozen comparison code/directory changed')
    return p


def resource_attempt(directory):
    """Preserve legacy and interrupted logs; never reuse an observer's files."""
    root=Path(directory)/'resources';root.mkdir(parents=True,exist_ok=True)
    for number in range(1,10001):
        attempt=root/f'attempt-{number:04d}'
        try:attempt.mkdir()
        except FileExistsError:continue
        return attempt
    raise ValueError('Resource attempt capacity exceeded')


def run_arm(directory):
    directory=Path(directory)
    if (directory/'completed.json').exists():
        done=read_json(directory/'completed.json')
        if (done['plan_sha256']!=sha(directory/'plan.json')
                or any(sha(directory/path)!=expected for path,expected in done['artifacts'].items())
                or read_json(directory/'artifacts/report.json')!=done['report']):raise ValueError('Completed comparison artifacts changed')
        return done['report']
    p=validate(directory);executor.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),executor.quota_watch():
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,p,dispatch)
        def save(name,value):
            dest=directory/'artifacts'/(name+'.json')
            if dest.exists():
                if read_json(dest)!=value:raise ValueError('Same-plan artifact changed')
            else:session.storage.before_write(value);write(dest,value)
        baseline=Path(p['baseline_artifacts']);snapshot=load_snapshot(Path(p['snapshot'])).snapshot
        registry={sid:r['source'] for sid,r in read_json(baseline/'source-discourse.json').items()}
        candidates=read_json(baseline/'candidates.json');memberships=read_json(baseline/'memberships.json');discourse=read_json(baseline/'source-discourse.json')
        e=PipelineWork(session,session.inspect,save,registry=registry,membership_mode='raw',verification_contract=raw.FULL_SCOPE,schedule=executor.minimal_pipeline.SCHEDULE)
        e.shared_typed=True;e.argument_audit_protocol=obs.SHARED_TYPED_CHAT;e.source_evidence_protocol=p['source_evidence_protocol']
        with host_resources.watch(resource_attempt(directory),p['resource_policy'],host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
            result=pipeline_stages.arguments(snapshot,candidates,memberships,discourse,e,discovery_mode='shared')
            inputs,checks=pipeline_stages.compile_agents(snapshot,candidates,memberships,result.arguments,result.cores,result.audits,
                lambda req:session.call('facts',req),model=p['classifier'],documents=p['documents'],selections=p['selections'],source_policy='candidate_verified_subset')
            save('agent-inputs',inputs);save('fact-checks',checks)
            runtime=runtime_probe(inputs['bundle'],session,save_turn=lambda row:save('runtime/'+row['candidate_id']+'/'+row['question_id'],row))
            runtime_check(runtime,inputs['compiled']);save('runtime',runtime)
            save('errors',e.errors);save('holds',e.holds)
        published={r['candidate_id'] for r in inputs['compiled']['profiles']}
        bindings={(r['claim_id'][:-2],r['source_id']) for r in inputs['bundle']['relations'] if r['claim_id'].endswith(':C')}
        assessment=[dict(row,selected_for_bundle=(row['candidate_id'],row['source_id']) in bindings,
            published=(row['candidate_id'],row['source_id']) in bindings and row['candidate_id'] in published)
            for row in read_json(p['annotations'])['cases']]
        save('eligible-pair-assessment',assessment)
        report=dict(arm=p['arm'],plan_sha256=sha(directory/'plan.json'),fresh_f4=True,archived_membership_inputs_reused=True,
            profiles=len(inputs['compiled']['profiles']),source_arguments=len(result.arguments),complete_source_arguments=sum(r['status']=='complete' for r in result.arguments),
            profile_summaries=[dict(candidate_id=x['candidate_id'],support_count=x['model_core_support_count'],entries=len(x['prompt_entries'])) for x in inputs['compiled']['profiles']],
            errors=len(e.errors),holds=len(e.holds),runtime_turns=len(runtime['turns']),
            eligible_pair_assessments=assessment,
            runtime_statuses=[dict(candidate_id=r['candidate_id'],question_id=r['question_id'],status=r['turn']['status']) for r in runtime['turns']],
            account=executor.ledger(p['spend_policy']).summary(),shared_comparison_charge=session.money.summary(plan_sha256=p['spend_scope_sha256']),
            formal_admission=False,quality_gate_passed=False,requires_semantic_review=True)
        save('report',report)
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),'report':report,
            'artifacts':{str(path.relative_to(directory)):sha(path) for path in sorted((directory/'artifacts').rglob('*.json'))}})
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--key-file',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--baseline',type=Path,required=True);q.add_argument('--annotations',type=Path,required=True);q.add_argument('--user-request',required=True)
    q=sub.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--arm',choices=ARMS)
    args=parser.parse_args()
    if args.key_file:os.environ['OPENROUTER_API_KEY']=args.key_file.read_text(encoding='utf-8').strip()
    if args.action=='prepare':out=prepare(args.directory,args.baseline,args.annotations,user_request=args.user_request)
    else:
        out=[]
        for arm in [args.arm] if args.arm else ARMS:
            report=run_arm(args.directory/arm);out.append(report);print(json.dumps({'arm':arm,'profiles':report['profiles'],'errors':report['errors'],'charge':report['shared_comparison_charge']['charged_usd']}),flush=True)
    print(json.dumps(out,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
