"""Frozen M1 cost/accuracy component; same original trial, no Factory admission."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import json
import os
import re
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.factory import jev_membership as j,raw_membership as raw,minimal_claims as mc
from commentscope.factory import source_context_observations as contexts,statement_worlds as worlds,fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import openrouter_decisions as od,host_resources,api_resources,typed_membership_runner
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from tools import shared_factory_trial as trial,plan_factory_cost as cost_tool

VERSION='jev-membership-component-20261110-v1'
FIXTURE=ROOT/'tests/fixtures/jev-membership-controls.json'
TOOL=ROOT/'tools/jev_membership_probe.py'


def synthetic(case):
    text=case['text'];source={'id':'synthetic-'+digest(text)[:16],'text':text,'parent':None}
    target={'id':mc.claim_id(case['candidate']),
        'text':case['candidate'],'aliases':[],'nominees':{source['id']:digest(source)},
        'extraction_refs':['authored-component-fixture'],'equivalence_refs':[]}
    target['aliases']=[target['id']]
    context=contexts.bind(source,{'output':{'source_use':case['source_use'],'reported_descriptors':[]}})
    sw=worlds.bind(text,{'output':{'world':case['world'],'anchor':''}})
    cw=worlds.bind(target['text'],{'output':{'world':'real_world','anchor':''}})
    return {'id':case['id'],'origin_kind':'synthetic_control','source':source,'candidate':target,
        'source_context':context,'source_world':sw,'candidate_world':cw,
        'expected_relations':[case['expected_relation']],'expected_passed':case['expected_passed'],
        'annotation_kind':'authored control expectation; not independent human gold'}


def case_task(case):
    return j.task(case['source'],case['candidate'],source_context=case['source_context'],
                  source_world=case['source_world'],candidate_world=case['candidate_world'])


def archived_case(annotation,parent_file):
    allowed={'id','origin_kind','raw_proof_file','expected_relations','expected_passed','annotation_note','baseline_label'}
    if set(annotation)!=allowed or annotation['origin_kind']!='archived_real':raise ValueError('Closed real-case annotation required')
    path=Path(annotation['raw_proof_file']).resolve();v=read_json(path);raw.validate(v)
    if annotation['baseline_label']!=v['output']['relation']:raise ValueError('Original model label changed')
    parent=read_json(parent_file);directory=Path(parent_file).parent
    logical=raw.request(v['source'],v['candidate'],version=raw.WORLD_CONTEXT,source_context=v['source_context'],
                        source_world=v['source_world'],candidate_world=v['candidate_world'])
    actual=allocate(logical,trial.executor.openrouter.generation_allocation(parent['verification_deployment']))
    found=[]
    for request in (directory/'calls').glob('*.request.json'):
        saved=read_json(request)
        if saved['request_sha256']!=digest(actual):continue
        if saved['plan_sha256']!=sha(parent_file) or saved['request']!=actual:
            raise ValueError('Original Sol request/plan mismatch')
        result_file=request.with_name(request.name.replace('.request.json','.result.json'))
        result=read_json(result_file)
        trial.executor.remote.parsed_receipt(result,logical,parent['verification_deployment'])
        if result['output']!=v['output']:raise ValueError('Original Sol logical observation changed')
        found.append((request,result_file,result))
    if len(found)!=1:raise ValueError('One original physical Sol receipt required')
    request,result_file,result=found[0]
    return {**{k:deepcopy(v[k]) for k in ('source','candidate','source_context','source_world','candidate_world')},
        **deepcopy(annotation),'annotation_kind':'predeclared coding-agent development annotation; not independent human gold',
        'baseline':{'relation':v['output']['relation'],'passed':v['passed'],'cost_usd':str(result['usage']['cost']),
                    'request_sha256':digest(actual),'result_file':str(result_file),
                    'raw_proof_sha256':sha(path),'response_sha256':sha(result_file)},
        'input_files':{str(path):sha(path),str(request):sha(request),str(result_file):sha(result_file)}}


def assess(case,proof):
    return {'case_id':case['id'],'origin_kind':case['origin_kind'],'expected_relations':case['expected_relations'],
        'expected_passed':case['expected_passed'],'actual_relation':proof['output']['relation'],
        'actual_passed':proof['passed'],'relation_correct':proof['output']['relation'] in case['expected_relations'],
        'support_correct':proof['passed']==case['expected_passed'],
        'invalid_support':proof['passed'] and not case['expected_passed'],
        'raw_false_support':proof['output']['relation']=='supported' and not case['expected_passed'],
        'missed_valid_support':not proof['passed'] and case['expected_passed'],'guards':proof['guards'],
        'baseline_relation':case.get('baseline',{}).get('relation'),
        'baseline_relation_correct':(case['baseline']['relation'] in case['expected_relations']) if 'baseline' in case else None}


def parent(plan):
    binding=plan['financial_parent'];p=read_json(binding['file'])
    if sha(binding['file'])!=binding['sha256'] or p!=binding['plan']:raise ValueError('Original financial plan changed')
    trial.guard(p,allow_expired=True)
    return p


def guard(plan,*,allow_expired=False,call_seconds=0):
    p=parent(plan);binding=plan['resume_authorization'];auth=read_json(binding['file'])
    if sha(binding['file'])!=binding['sha256'] or auth!=binding['authorization']:
        raise ValueError('Explicit resume authorization changed')
    resumed=deepcopy(p);resumed['authorization']=deepcopy(binding)
    trial.executor.guard(resumed,call_seconds=call_seconds,allow_expired=allow_expired)
    if (auth['money_owner']['sha256']!=p['spend_scope_sha256']
            or sha(auth['money_owner']['file'])!=p['spend_scope_sha256']
            or plan['spend_scope_sha256']!=p['spend_scope_sha256'] or plan['spend_policy']!=p['spend_policy']
            or plan['maximum_cost_usd']!=p['maximum_cost_usd']
            or plan['artifact_kind']!=VERSION or plan['formal_admission_eligible'] is not False
            or plan['quality_gate_passed'] is not False or plan['membership_deployment']!=od.DEPLOYMENT
            or plan['membership_judge_protocol']!=j.VERSION or auth['historical_charges_preserved'] is not True):
        raise ValueError('Frozen component role or original money changed')
    if not allow_expired:fact_checks.live(plan['expires_at'])


def prepare(directory,financial_file,annotation_file,*,resume_request):
    directory=Path(directory).resolve();financial_file=Path(financial_file).resolve();annotation_file=Path(annotation_file).resolve()
    trial.executor.private(directory)
    if directory.exists() or not isinstance(resume_request,str) or not resume_request.strip():
        raise ValueError('New component and explicit current user resume required')
    p=read_json(financial_file);trial.guard(p,allow_expired=True);fact_checks.live(p['expires_at'])
    # Audit immutable original Sol receipts/archive, including the recorded
    # budget-denied old request. Never resume or clear that request.
    cost_tool.audit(financial_file.parent)
    cases=[synthetic(c) for c in read_json(FIXTURE)['cases']]
    cases.extend(archived_case(a,financial_file) for a in read_json(annotation_file)['cases'])
    if len({c['id'] for c in cases})!=len(cases) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',c['id']) for c in cases):
        raise ValueError('Unique safe evaluation case IDs required')
    requests={};tasks={}
    for case in cases:
        task=case_task(case);tasks[case['id']]=task
        for payload in task['requests']:requests[od.wire_sha256(payload,od.DEPLOYMENT)]=payload
    maximum=od.reservation(od.DEPLOYMENT)*len(requests)
    available=cost_tool.available(p)
    if len(cases)!=11 or maximum>available:
        raise BudgetExhausted('All planned packets must fit the existing cumulative trial remainder')
    resume_file=directory/'resume-authorization.json'
    auth=trial.executor.authorize(resume_file,Path(p['authorization']['authorization']['money_owner']['file']),resume_request=resume_request)
    inputs={str(financial_file):sha(financial_file),str(annotation_file):sha(annotation_file),str(FIXTURE):sha(FIXTURE),str(TOOL):sha(TOOL)}
    for case in cases:inputs.update(case.get('input_files',{}))
    money=trial.executor.ledger(p['spend_policy']);opening=money.summary(plan_sha256=p['spend_scope_sha256'])['charged_usd']
    if maximum>cost_tool.available(p):raise BudgetExhausted('Original trial changed before freezing')
    plan={'artifact_kind':VERSION,'run_directory':str(directory),'formal_admission_eligible':False,'quality_gate_passed':False,
        'membership_judge_protocol':j.VERSION,'membership_deployment':deepcopy(od.DEPLOYMENT),
        'deployment':deepcopy(p['deployment']),'verification_deployment':deepcopy(p['verification_deployment']),
        'embedding_deployment':deepcopy(p['embedding_deployment']),
        'financial_parent':{'file':str(financial_file),'sha256':sha(financial_file),'plan':p},
        'resume_authorization':{'file':str(resume_file),'sha256':sha(resume_file),'authorization':auth},
        'spend_policy':p['spend_policy'],'spend_scope_sha256':p['spend_scope_sha256'],'maximum_cost_usd':p['maximum_cost_usd'],
        'opening_scope_charge_usd':opening,'subcap_usd':str(maximum),'maximum_requests':len(requests),
        'full_reservation_usd':str(maximum),'available_at_prepare_usd':str(available),
        'cases':cases,'tasks':tasks,'requests':requests,'inputs':inputs,'code_sha256':source_code_hashes(),
        'expires_at':p['expires_at'],'resource_policy':deepcopy(host_resources.HTTP_API_POLICY),
        'artifact_storage_policy':deepcopy(p['artifact_storage_policy']),
        'limits':{'analysis_seconds':None,'call_seconds':od.DEPLOYMENT['call_seconds']},
        'archived_upstream_observation_input_reuse':True,'fresh_membership_responses':True,
        'baseline_comparison':'historical Sol actual costs; different time/cache, not a contemporaneous price experiment'}
    guard(plan);plan['provider_at_prepare']=od.preflight(od.DEPLOYMENT)
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    trial.executor.archive_sources(directory,plan['code_sha256']);trial.executor.archive_sources(directory,{str(TOOL.relative_to(ROOT)):sha(TOOL)})
    return {'cases':len(cases),'maximum_requests':len(requests),'maximum_new_usd':str(maximum),'new_model_calls':0}


def validate(directory,*,allow_expired=False):
    directory=Path(directory).resolve();plan=read_json(directory/'plan.json')
    if (plan['run_directory']!=str(directory) or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or any(sha(path)!=expected for path,expected in plan['inputs'].items())
            or plan['code_sha256']!=source_code_hashes()
            or any(sha(directory/'frozen-code'/path)!=expected for path,expected in plan['code_sha256'].items())):
        raise ValueError('Frozen component inputs/code/directory changed')
    guard(plan,allow_expired=allow_expired)
    regenerated={};tasks={}
    for case in plan['cases']:
        if not case['expected_relations'] or any(v not in raw.RELATIONS for v in case['expected_relations']) or type(case['expected_passed']) is not bool:
            raise ValueError('Frozen development annotation required')
        task=case_task(case);tasks[case['id']]=task
        for payload in task['requests']:regenerated[od.wire_sha256(payload,od.DEPLOYMENT)]=payload
    if (regenerated!=plan['requests'] or tasks!=plan['tasks'] or len(regenerated)!=plan['maximum_requests']
            or Decimal(plan['subcap_usd'])!=od.reservation(od.DEPLOYMENT)*len(regenerated)):
        raise ValueError('Complete question plan or reservation changed')
    return plan


def run(directory):
    directory=Path(directory).resolve()
    if (directory/'completed.json').exists():return replay(directory)
    plan=validate(directory)
    trial.executor.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),trial.executor.quota_watch():
        storage=api_resources.SpaceGuard(directory,plan['artifact_storage_policy']);dispatch=host_resources.RemoteCallGuard()
        money=trial.executor.SubcapLedger(trial.executor.ledger(plan['spend_policy']),parent(plan))
        inference=InferenceBudget(directory/'inference.sqlite',VERSION,limit_seconds=None)
        client,runner=typed_membership_runner.build(directory,plan,inference,money,trial.executor.key_metadata)
        attempt=len(list((directory/'attempts').glob('*.started.json')))+1
        write(directory/'attempts'/f'{attempt:04}.started.json',{'plan_sha256':sha(directory/'plan.json')})
        def save(path,value):
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan component artifact changed')
                return
            storage.before_write(value);write(path,value)
        results={};rows=[]
        with host_resources.watch(directory/'resources'/f'{attempt:04}',plan['resource_policy'],host_resources.observe_wsl_host,
                                  interrupt=dispatch.request_stop,workload='http_api'):
            for case in plan['cases']:
                validate(directory);responses=[]
                for payload in plan['tasks'][case['id']]['requests']:
                    key=od.wire_sha256(payload,od.DEPLOYMENT)
                    if key not in results:
                        guard(plan,call_seconds=od.DEPLOYMENT['call_seconds']);dispatch.check();trial.executor.check_quota(wait_for_fresh=False);storage.check()
                        with dispatch.remote_call():results[key]=runner.call('membership-jev-'+key[:20],payload,provider=client.generate)
                        storage.check()
                    responses.append(results[key])
                try:
                    proof=j.bind(plan['tasks'][case['id']],responses)
                    save(directory/'proofs'/(case['id']+'.json'),proof)
                    row=assess(case,proof)
                except (ValueError,KeyError,TypeError) as exc:
                    row={'case_id':case['id'],'origin_kind':case['origin_kind'],'binding_error':type(exc).__name__+': '+str(exc),
                         'relation_correct':False,'support_correct':False,'invalid_support':False,'raw_false_support':False,'missed_valid_support':case['expected_passed']}
                rows.append(row);save(directory/'assessments'/(case['id']+'.json'),row)
        def cost_for(selected):
            keys={od.wire_sha256(p,od.DEPLOYMENT) for c in selected for p in plan['tasks'][c['id']]['requests']}
            return sum((Decimal(str(results[k]['usage']['cost'])) for k in keys),Decimal(0))
        paired=[c for c in plan['cases'] if 'baseline' in c]
        baseline=sum((Decimal(c['baseline']['cost_usd']) for c in paired),Decimal(0));paired_cost=cost_for(paired)
        report={'artifact_kind':VERSION+'-report','plan_sha256':sha(directory/'plan.json'),'cases':rows,
            'case_count':len(rows),'relation_correct':sum(r['relation_correct'] for r in rows),
            'support_correct':sum(r['support_correct'] for r in rows),'invalid_supports':sum(r['invalid_support'] for r in rows),
            'raw_false_supports':sum(r['raw_false_support'] for r in rows),
            'missed_valid_supports':sum(r['missed_valid_support'] for r in rows),'binding_errors':sum('binding_error' in r for r in rows),
            'physical_responses':len(results),'actual_new_usd':str(cost_for(plan['cases'])),
            'paired_real_cases':len(paired),'historical_sol_raw_usd':str(baseline),'paired_jev_raw_usd':str(paired_cost),
            'paired_raw_cost_reduction_fraction':str(1-paired_cost/baseline) if baseline else None,
            'baseline_real_relation_correct':sum(r.get('baseline_relation_correct') is True for r in rows),
            'jev_real_relation_correct':sum(r['relation_correct'] for r in rows if r['origin_kind']=='archived_real'),
            'current_spending':money.summary(),'original_trial_opening_usd':parent(plan)['opening_scope_charge_usd'],
            'annotations':'predeclared authored controls/coding-agent annotations; not independent human gold',
            'historical_baseline_cache_and_time_differ':True,'archived_upstream_observations_reused':True,
            'fresh_factory_gate':False,'production_model_adopted':False,'quality_gate_passed':False,
            'all_planned_cases_processed':len(rows)==len(plan['cases'])}
        save(directory/'report.json',report)
        try:
            profile=cost_tool.audit(directory);save(directory/'cost-profile.json',profile)
        except (ValueError,KeyError,TypeError) as exc:
            save(directory/'cost-profile-rejected.json',{'reason':str(exc),'price_profile_adopted':False})
        done={k:report[k] for k in ('case_count','relation_correct','support_correct','invalid_supports','missed_valid_supports',
            'binding_errors','physical_responses','actual_new_usd','paired_real_cases','historical_sol_raw_usd','paired_jev_raw_usd',
            'paired_raw_cost_reduction_fraction','baseline_real_relation_correct','jev_real_relation_correct','quality_gate_passed')}
        done.update(plan_sha256=sha(directory/'plan.json'),report_sha256=sha(directory/'report.json'))
        save(directory/'completed.json',done);return done


def replay(directory):
    directory=Path(directory);plan=validate(directory,allow_expired=True)
    done=read_json(directory/'completed.json');report=read_json(directory/'report.json')
    if done['plan_sha256']!=sha(directory/'plan.json') or done['report_sha256']!=sha(directory/'report.json'):
        raise ValueError('Original component completion receipt changed')
    if (directory/'cost-profile.json').exists() and cost_tool.audit(directory)!=read_json(directory/'cost-profile.json'):
        raise ValueError('Original checkpoint/cost profile changed')
    observed={}
    for _,payload,result in cost_tool.call_rows(directory,plan,require_settled=True):
        key=od.wire_sha256(payload,od.DEPLOYMENT)
        if key in observed:raise ValueError('Duplicate physical membership request')
        observed[key]=result
    rows=[]
    for case in plan['cases']:
        responses=[observed[od.wire_sha256(p,od.DEPLOYMENT)] for p in plan['tasks'][case['id']]['requests']]
        try:row=assess(case,j.bind(plan['tasks'][case['id']],responses))
        except (ValueError,KeyError,TypeError) as exc:
            row={'case_id':case['id'],'origin_kind':case['origin_kind'],'binding_error':type(exc).__name__+': '+str(exc),
                 'relation_correct':False,'support_correct':False,'invalid_support':False,'raw_false_support':False,
                 'missed_valid_support':case['expected_passed']}
        rows.append(row)
    actual=sum((Decimal(str(result['usage']['cost'])) for result in observed.values()),Decimal(0))
    if rows!=report['cases'] or str(actual)!=report['actual_new_usd'] or done['quality_gate_passed'] is not False:
        raise ValueError('Component accuracy/cost differs from original model receipts')
    for key in ('relation_correct','support_correct'):
        if done[key]!=sum(r[key] for r in rows):raise ValueError('Component scores changed')
    if done['invalid_supports']!=sum(r['invalid_support'] for r in rows):raise ValueError('Support scores changed')
    return done


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--financial-plan',type=Path,required=True)
    q.add_argument('--annotations',type=Path,required=True);q.add_argument('--resume-request',required=True)
    q=sub.add_parser('run');q.add_argument('directory',type=Path);q.add_argument('--key-file',type=Path,required=True);q.add_argument('--live',action='store_true',required=True)
    args=parser.parse_args()
    if args.action=='prepare':result=prepare(args.directory,args.financial_plan,args.annotations,resume_request=args.resume_request)
    else:
        os.environ['OPENROUTER_API_KEY']=args.key_file.read_text(encoding='utf-8').strip();result=run(args.directory)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
