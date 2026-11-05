"""Single authorized Jev-only diagnostic; never production or fresh G1 admission."""
import argparse
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from commentscope.factory import dependency_decisions as dd
from commentscope.providers import openrouter_decisions as od,host_resources
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.providers.checkpoint_calls import CheckpointRunner,run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.storage import write_json_exclusive as write
from experiments.openrouter_factory_probe import private,key_metadata,validate_spend_policy
from experiments.openrouter_factory_pipeline import archive_sources

VERSION='jev-first-argument-controls-20261105-v1'
FIXTURE=Path('tests/fixtures/argument-dependency-controls.json')


def ledger_for(policy):
    return SpendLedger(policy['ledger'],policy['account_id'],maximum_usd=policy['maximum_usd'],opening_charge_usd=policy['opening_charge_usd'])


def clock_guard(authorization,*,call_seconds=0,now=None,allow_expired=False):
    start=datetime.fromisoformat(authorization['started_at']);end=datetime.fromisoformat(authorization['deadline'])
    now=now or datetime.now(timezone.utc)
    if (start.utcoffset() is None or end.utcoffset() is None or end-start!=timedelta(minutes=15)
            or authorization['maximum_new_usd']!='0.10' or authorization['maximum_requests']!=2
            or authorization['model']!=od.DEPLOYMENT['model']):raise ValueError('Fixed first-trial authorization required')
    if not allow_expired and not start<=now<end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('First-trial deadline cannot cover another bounded request')


def prepare(directory,parent_cycle_file):
    directory=Path(directory);parent_cycle_file=Path(parent_cycle_file)
    private(directory);private(parent_cycle_file)
    if directory.exists():raise ValueError('First-trial output must be new; never overwrite a paid attempt')
    parent=read_json(parent_cycle_file);policy=validate_spend_policy(read_json(parent['shared_policy_file']))
    if (parent['maximum_additional_usd']!='5' or policy['maximum_usd']!='50'
            or parent.get('version')!='commentscope-autonomous-cycle-20261105-v1'):
        raise ValueError('Preserve original monetary envelope')
    scope=sha(parent_cycle_file);ledger=ledger_for(policy);before=ledger.summary(plan_sha256=scope)
    if ledger.summary()['reserved_calls'] or ledger.summary()['uncertain_calls'] or before['maximum_usd']!='5':
        raise ValueError('Original accounted money owner must be settled and unchanged')
    fixture=read_json(FIXTURE);deployment=od.validate(od.DEPLOYMENT);requests={};mapping={}
    for o in fixture['observations']:
        req=dd.request(o,deployment);key=od.wire_sha256(req,deployment);mapping[o['id']]=key;requests[key]=req
    if len(requests)!=2 or len(fixture['cases'])!=4:raise ValueError('Only the fixed first controls are authorized')
    ceiling=od.reservation(deployment)*len(requests)
    if ceiling>min(Decimal('0.10'),Decimal(before['remaining_usd']),Decimal(ledger.summary()['remaining_usd'])):
        raise ValueError('Entire worst-case first trial cannot fit existing balances')
    provider=od.preflight(deployment);now=datetime.now(timezone.utc)
    authorization={'version':VERSION+'-authorization','user_request':'어차피 첫 검증용이니 좀 해보셈',
        'run_directory':str(directory.resolve()),'started_at':now.isoformat(),'deadline':(now+timedelta(minutes=15)).isoformat(),
        'maximum_new_usd':'0.10','maximum_requests':2,'model':deployment['model'],
        'parent_cycle_sha256':scope,'parent_limit_usd':'5','opening_scope_charge_usd':before['charged_usd'],
        'parent_time_window_modified':False,'new_monetary_owner':False,'scope':'Jev-only development controls, no G1/production adoption'}
    write(directory/'authorization.json',authorization)
    plan={'artifact_kind':VERSION,'run_directory':str(directory.resolve()),'cross_run_response_reuse':False,
        'authorization':authorization,'authorization_sha256':sha(directory/'authorization.json'),
        'parent_cycle_file':str(parent_cycle_file.resolve()),'parent_cycle_sha256':scope,
        'spend_policy':policy,'deployment':deployment,'fixture':fixture,'requests':requests,'observation_requests':mapping,
        'worst_batch_reservation_usd':str(ceiling),'provider_at_prepare':provider,
        'limits':{'analysis_seconds':None,'call_seconds':deployment['call_seconds']},
        'inputs':{str(parent_cycle_file.resolve()):scope,str(Path(parent['shared_policy_file']).resolve()):sha(parent['shared_policy_file']),
                  str(FIXTURE.resolve()):sha(FIXTURE)},'code_sha256':source_code_hashes(),
        'quality_gate_passed':False,'production_admission':False}
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    archive_sources(directory,plan['code_sha256'])
    return {'prepared':str(directory),'maximum_paid_calls':2,'controls':4,'worst_reservation_usd':str(ceiling),'maximum_new_usd':'0.10','inference_calls':0}


def validate(directory,*,allow_expired=False):
    plan=read_json(directory/'plan.json');run_origin(plan,directory,attempt=1)
    if (plan['artifact_kind']!=VERSION or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['code_sha256']!=source_code_hashes()
            or read_json(directory/'authorization.json')!=plan['authorization']
            or sha(directory/'authorization.json')!=plan['authorization_sha256']
            or plan['authorization']['run_directory']!=str(directory.resolve())
            or plan['authorization']['parent_cycle_sha256']!=plan['parent_cycle_sha256']
            or plan['authorization']['parent_limit_usd']!='5'
            or any(sha(p)!=h for p,h in plan['inputs'].items())):raise ValueError('Frozen first-trial inputs, scope or code changed')
    od.validate(plan['deployment']);fixture=read_json(FIXTURE)
    expected={od.wire_sha256(dd.request(o,plan['deployment']),plan['deployment']):dd.request(o,plan['deployment']) for o in fixture['observations']}
    if (plan['fixture']!=fixture or plan['requests']!=expected or len(expected)!=2
            or plan['parent_cycle_sha256']!=sha(plan['parent_cycle_file'])):raise ValueError('Fixed requests changed')
    clock_guard(plan['authorization'],allow_expired=allow_expired)
    return plan


def run(directory):
    directory=Path(directory);private(directory)
    with experiment_lock(directory):
        plan=validate(directory,allow_expired=(directory/'report.json').exists())
        if (directory/'report.json').exists():return read_json(directory/'report.json')
        deployment=plan['deployment'];od.preflight(deployment);authorization=plan['authorization']
        ledger=ledger_for(plan['spend_policy']);scope=plan['parent_cycle_sha256'];before=ledger.summary(plan_sha256=scope)
        if ledger.summary()['reserved_calls'] or ledger.summary()['uncertain_calls']:raise ValueError('Reconcile existing requests first')
        metadata=key_metadata()
        if Decimal(str(metadata['limit_remaining']))<Decimal(plan['worst_batch_reservation_usd']):raise ValueError('Key cannot cover first trial')
        write(directory/'before.json',{'scope':before,'shared':ledger.summary(),'provider':metadata})
        client=od.Client(deployment)
        paid=od.PaidDecisions(InferenceBudget(directory/'inference.sqlite',VERSION,limit_seconds=None),ledger,
            plan_sha256=sha(directory/'plan.json'),deployment=deployment,spend_scope_sha256=scope,parent_limit_usd='5',
            opening_scope_charge_usd=authorization['opening_scope_charge_usd'],trial_limit_usd=authorization['maximum_new_usd'],
            paid_provider=client.generate,key_metadata=key_metadata)
        runner=CheckpointRunner(RuntimeRunner(directory,plan,paid,client),{})
        results={};observed={};rows=[];guard=host_resources.RemoteCallGuard()
        with host_resources.watch(directory/'resources',host_resources.POLICY,host_resources.observe_wsl_host,interrupt=guard.request_stop):
            for o in plan['fixture']['observations']:
                clock_guard(authorization,call_seconds=deployment['call_seconds']);guard.check()
                key=plan['observation_requests'][o['id']];payload=plan['requests'][key]
                if key not in results:
                    with guard.remote_call():results[key]=runner.call('J4-'+key[:20],payload,provider=client.generate)
                bound=dd.observe(o,results[key],deployment);observed[o['id']]=bound
                write(directory/('observation-'+o['id']+'.json'),bound)
                print(json.dumps({'observation':o['id'],'request_questions':len(payload['questions']),
                    'kind':bound['kind'],'function':bound['function'],'requires':bound['requires'],'guards':bound['guards'],
                    'actual_cost_usd':results[key]['usage']['cost']}),flush=True)
                for c in plan['fixture']['cases']:
                    if c['observation_id']!=o['id']:continue
                    verdict=dd.compare(o,bound,c['declared']);row={'case_id':c['id'],'expected_admitted':c['expected_admitted'],
                        **verdict,'matches_expected':verdict['admitted']==c['expected_admitted']};rows.append(row)
                if any(r['admitted'] and not r['expected_admitted'] for r in rows):break
        after=ledger.summary(plan_sha256=scope)
        report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'controls':rows,
            'all_controls_match':len(rows)==4 and all(r['matches_expected'] for r in rows),
            'independent_source_observations':len(results),'logical_declaration_checks':len(rows),
            'new_paid_calls':after['calls']-before['calls'],'new_cost_usd':str(Decimal(after['charged_usd'])-Decimal(before['charged_usd'])),
            'scope_after':after,'shared_after':ledger.summary(),'provider_after':key_metadata(),
            'calibrated':False,'paired_GPT_comparison':False,'quality_gate_passed':False,'production_admission':False,
            'next':'Hold default; verify held-out/control ordering and full audit integration before fresh G1.'}
        write(directory/'report.json',report)
        return report


def main():
    parser=argparse.ArgumentParser();p=parser.add_subparsers(dest='action',required=True)
    q=p.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--parent-cycle',type=Path,required=True)
    q=p.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--key-file',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='prepare':result=prepare(args.directory,args.parent_cycle)
    else:
        os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip();result=run(args.directory)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
