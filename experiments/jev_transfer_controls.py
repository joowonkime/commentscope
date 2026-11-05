"""Frozen transfer cases for the opt-in J4 graph adapter, before any G1 call."""
import argparse
from copy import deepcopy
from decimal import Decimal
from datetime import datetime,timezone
import json
import os
from pathlib import Path

from commentscope.factory import argument_dependencies as deps
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import scoped_authorization as auth,openrouter_decisions as od,host_resources
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.providers.checkpoint_calls import CheckpointRunner,run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.storage import write_json_exclusive as write
from experiments.jev_argument_controls import ledger_for
from experiments.openrouter_factory_pipeline import archive_sources
from experiments.openrouter_factory_probe import private,key_metadata,validate_spend_policy

VERSION='jev-transfer-experiment-20261106-v2'
FIXTURE=Path('tests/fixtures/jev-transfer-controls.json')
SEMANTIC_FILES=('src/commentscope/factory/argument_dependencies.py',
    'src/commentscope/factory/dependency_decisions.py','src/commentscope/factory/automatic_contract.py',
    'src/commentscope/providers/openrouter_decisions.py')


def assess(case,checks):
    failures=[];local=next(c for c in checks if c['task']['kind']=='local')
    labels=local['labels']
    for prefix,expected in (('kind_',case['expected_kinds']),('authorship_',case['expected_authorship'])):
        for alias,value in expected.items():
            if labels[prefix+alias]!=value:failures.append(prefix+alias)
    for check in checks:
        expected=case['expected_local'] if check['task']['kind']=='local' else case['expected_core']
        for target,required in expected.items():
            observed=sorted(u['id'] for u in check['task']['units']
                if 'relation_'+target+'_'+u['id'] in check['labels']
                and check['labels']['relation_'+target+'_'+u['id']]=='necessary_fact')
            if observed!=sorted(required):failures.append('requires_'+target)
            if check['labels']['coverage_'+target]!='complete':failures.append('coverage_'+target)
        if any(v=='uncertain' for k,v in check['labels'].items() if k.startswith('relation_')):
            failures.append('uncertain_relation')
    # Correct graph plus missing/wrong mutations share these exact raw observations.
    base=deps.guards(case['record'],case['cores'],checks)
    if any(base.values()):failures.append('correct_declaration_rejected')
    mutations=[]
    for u in case['record']['units']:
        if not u['requires']:continue
        changed=json.loads(json.dumps(case['record']));target=next(x for x in changed['units'] if x['id']==u['id'])
        target['requires']=[]
        missing=deps.guards(changed,case['cores'],checks)
        target['requires']=[next(x['id'] for x in changed['units'] if x['id'] not in (u['id'],*u['requires']))]
        wrong=deps.guards(changed,case['cores'],checks)
        passed='missing_factual_prerequisite' in missing[u['id']] and 'wrong_factual_prerequisite' in wrong[u['id']]
        mutations.append({'target':u['id'],'missing_and_wrong_rejected':passed})
        if not passed:failures.append('mutation_not_rejected')
    return {'case_id':case['id'],'passed':not failures,'failures':failures,'graph_guards':base,'mutations':mutations}


def prepare(directory,scope_file):
    private(directory);private(scope_file)
    if directory.exists():raise ValueError('New immutable transfer run required')
    authorization=read_json(scope_file);policy=validate_spend_policy(read_json(authorization['shared_policy_file']))
    binding=auth.bind(scope_file,authorization['chat_deployment'],policy,'8','G1')
    fixture=read_json(FIXTURE);requests={}
    for case in fixture['sources']:
        for task in deps.tasks(case['record'],case['cores']):
            for payload in deps.requests(task):requests[od.wire_sha256(payload,od.DEPLOYMENT)]=payload
    if len(requests)>18 or od.reservation(od.DEPLOYMENT)*len(requests)>Decimal('0.20'):
        raise ValueError('Transfer request/reservation cap exceeded')
    plan={'artifact_kind':VERSION,'run_directory':str(directory.resolve()),'cross_run_response_reuse':False,
          'workload':'remote_decisions_only','resource_policy':deepcopy(host_resources.HTTP_ONLY_POLICY),
          'deployment':od.DEPLOYMENT,'authorization':binding,'spend_policy':policy,'fixture':fixture,
          'requests':requests,'maximum_new_usd':'0.20','maximum_requests':len(requests),
          'inputs':{str(scope_file.resolve()):sha(scope_file),str(FIXTURE.resolve()):sha(FIXTURE),
                    str(Path(authorization['shared_policy_file']).resolve()):sha(authorization['shared_policy_file'])},
          'code_sha256':source_code_hashes(),'provider_at_prepare':od.preflight(od.DEPLOYMENT),
          'limits':{'analysis_seconds':None,'call_seconds':od.DEPLOYMENT['call_seconds']}}
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    archive_sources(directory,plan['code_sha256'])
    return {'prepared':str(directory),'sources':len(fixture['sources']),'maximum_paid_calls':len(requests),'maximum_new_usd':'0.20'}


def validate(directory,*,allow_expired=False,historical_diagnostic=False):
    plan=read_json(directory/'plan.json');run_origin(plan,directory,attempt=1)
    allowed=(VERSION,'jev-transfer-experiment-20261106-v1') if historical_diagnostic else (VERSION,)
    if (plan['artifact_kind'] not in allowed or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or any(sha(p)!=v for p,v in plan['inputs'].items())
            or plan['fixture']!=read_json(FIXTURE) or plan['maximum_new_usd']!='0.20'):
        raise ValueError('Frozen transfer code/input changed')
    if plan['artifact_kind']==VERSION and (plan.get('workload')!='remote_decisions_only'
            or plan.get('resource_policy')!=host_resources.HTTP_ONLY_POLICY):raise ValueError('Frozen workload changed')
    if historical_diagnostic:
        if not (directory/'report.json').exists():raise ValueError('Only completed diagnostics can be read historically')
        if any(plan['code_sha256'].get(p)!=sha(p) or sha(directory/'frozen-code'/p)!=sha(p) for p in SEMANTIC_FILES):
            raise ValueError('Diagnostic semantic contract changed')
    elif plan['code_sha256']!=source_code_hashes():raise ValueError('Frozen transfer code/input changed')
    auth.guard(plan['authorization']['authorization'],allow_expired=allow_expired)
    expected={od.wire_sha256(p,od.DEPLOYMENT):p for c in plan['fixture']['sources']
        for t in deps.tasks(c['record'],c['cores']) for p in deps.requests(t)}
    if plan['requests']!=expected or plan['maximum_requests']!=len(expected):raise ValueError('Transfer requests changed')
    return plan


def replay_report(directory,*,historical_diagnostic=False):
    plan=validate(directory,allow_expired=True,historical_diagnostic=historical_diagnostic);report=read_json(directory/'report.json')
    checks=read_json(directory/'checks.json')
    rows=[assess(case,[c for c in checks if c['task']['source_id']==case['id']]) for case in plan['fixture']['sources']
          if any(c['task']['source_id']==case['id'] for c in checks)]
    if (report['plan_sha256']!=sha(directory/'plan.json') or report['cases']!=rows
            or report['all_passed']!=(len(rows)==len(plan['fixture']['sources']) and all(r['passed'] for r in rows))):
        raise ValueError('Transfer report no longer matches raw observations')
    for case in plan['fixture']['sources']:
        selected=[c for c in checks if c['task']['source_id']==case['id']]
        if selected:deps.select([case['record']],case['cores'],[{'source_id':case['id']}],selected)
    return report


def run(directory):
    private(directory)
    with experiment_lock(directory):
        plan=validate(directory,allow_expired=(directory/'report.json').exists())
        if (directory/'report.json').exists():return replay_report(directory)
        if any(not p.with_name(p.name.replace('.intent.json','.result.json')).exists()
               for p in (directory/'checkpoints').glob('*.intent.json')):raise ValueError('Reconcile pending transfer request')
        ledger=ledger_for(plan['spend_policy']);status=ledger.summary()
        if status['reserved_calls'] or status['uncertain_calls']:raise ValueError('Reconcile shared charge before transfer')
        od.preflight(od.DEPLOYMENT);scope=plan['authorization']['sha256'];before=ledger.summary(plan_sha256=scope)
        if (directory/'before.json').exists():
            before=read_json(directory/'before.json')['scope']
        else:write(directory/'before.json',{'scope':before,'shared':status,'provider':key_metadata()})
        client=od.Client(od.DEPLOYMENT)
        paid=auth.PaidDecisions(InferenceBudget(directory/'inference.sqlite',VERSION,limit_seconds=None),ledger,
            plan_sha256=sha(directory/'plan.json'),binding=plan['authorization'],paid_provider=client.generate,key_metadata=key_metadata)
        runner=CheckpointRunner(RuntimeRunner(directory,plan,paid,client),{})
        results={};checks=[];rows=[];dispatch=host_resources.RemoteCallGuard()
        attempt=len(list((directory/'attempts').glob('*.started.json')))+1
        write(directory/'attempts'/f'{attempt:04}.started.json',{'at':datetime.now(timezone.utc).isoformat(),
            'plan_sha256':sha(directory/'plan.json'),'scope_before':ledger.summary(plan_sha256=scope)})
        try:
            with host_resources.watch(directory/'resources'/f'{attempt:04}',plan['resource_policy'],host_resources.observe_wsl_host,
                                      interrupt=dispatch.request_stop,workload='http_only'):
                for case in plan['fixture']['sources']:
                    selected=[]
                    for task in deps.tasks(case['record'],case['cores']):
                        responses=[]
                        for payload in deps.requests(task):
                            key=od.wire_sha256(payload,od.DEPLOYMENT)
                            delta=Decimal(ledger.summary(plan_sha256=scope)['charged_usd'])-Decimal(before['charged_usd'])
                            if delta+od.reservation(od.DEPLOYMENT)>Decimal(plan['maximum_new_usd']):raise BudgetExhausted('Transfer subcap')
                            dispatch.check()
                            if key not in results:
                                with dispatch.remote_call():results[key]=runner.call('J4-transfer-'+key[:20],payload,provider=client.generate)
                            responses.append(results[key])
                        selected.append(deps.bind(task,responses))
                    checks.extend(selected);row=assess(case,selected);rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
                    if not row['passed']:break
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json',{'exception':type(exc).__name__,
                'scope_after':ledger.summary(plan_sha256=scope),'automatic_retry':False})
            raise
        after=ledger.summary(plan_sha256=scope)
        report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'cases':rows,
            'all_passed':len(rows)==len(plan['fixture']['sources']) and all(r['passed'] for r in rows),
            'independent_sources':len(rows),'physical_requests':len(results),
            'new_paid_calls':after['calls']-before['calls'],'new_cost_usd':str(Decimal(after['charged_usd'])-Decimal(before['charged_usd'])),
            'scope_after':after,'shared_after':ledger.summary(),'quality_gate_passed':False,'production_admission':False}
        write(directory/'checks.json',checks);write(directory/'report.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='action',required=True)
    q=s.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--scope-file',type=Path,required=True)
    q=s.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--key-file',type=Path,required=True)
    args=p.parse_args()
    if args.action=='prepare':result=prepare(args.directory,args.scope_file)
    else:
        os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip();result=run(args.directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
