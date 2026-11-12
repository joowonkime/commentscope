"""Audit saved API costs and prepare a full-stage preview without API calls."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.factory import cost_planning as cost
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write


def call_rows(directory,plan,*,require_settled=False):
    directory=Path(directory);plan_sha=sha(directory/'plan.json');rows=[]
    for path in sorted((directory/'calls').glob('*.request.json')):
        saved=read_json(path);request=saved['request']
        if saved['plan_sha256']!=plan_sha or saved['request_sha256']!=digest(request):
            raise cost.CostPlanError('Saved request differs from its frozen plan/hash')
        stage=re.sub(r'^\d+-','',path.name.removesuffix('.request.json'))
        result_path=path.with_name(path.name.replace('.request.json','.result.json'))
        if require_settled and not result_path.exists():
            raise cost.CostPlanError('Pending original request; no automatic paid retry')
        rows.append((stage,request,read_json(result_path) if result_path.exists() else None))
    return rows


def audit(directory):
    directory=Path(directory);plan=read_json(directory/'plan.json')
    if read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}:
        raise cost.CostPlanError('Immutable original plan required for cost reference')
    if any(sha(directory/'frozen-code'/p)!=h for p,h in plan['code_sha256'].items()):
        raise cost.CostPlanError('Original source archive changed')
    checkpoints={}
    for path in (directory/'checkpoints').glob('*.result.json'):
        r=read_json(path);identity=r['identity']
        if (identity['plan_sha256']!=sha(directory/'plan.json') or r['result_sha256']!=digest(r['result'])
                or read_json(path.with_name(path.name.replace('.result.json','.intent.json')))!=identity):
            raise cost.CostPlanError('Cost reference checkpoint changed')
        checkpoints[(identity['stage'],identity['request_sha256'])]=r['result_sha256']
    stages={};other={};total=Decimal(0);pending=0;completed=0
    for stage,request,result in call_rows(directory,plan):
        if result is None:pending+=1;continue
        if checkpoints.get((stage,digest(request)))!=digest(result):
            raise cost.CostPlanError('Cost result lacks its exact original checkpoint')
        charge=cost.amount((result.get('usage') or {})['cost']);total+=charge;completed+=1
        try:family=cost.canonical(stage,request)
        except cost.CostPlanError:
            legacy=re.sub(r'-[a-f0-9]{20}$','',stage)
            row=other.setdefault(legacy,{'calls':0,'cost_usd':Decimal(0)})
            row['calls']+=1;row['cost_usd']+=charge;continue
        deployment=cost.deployment(plan,family)
        raw=result if family.startswith('embedding-') or family=='membership-jev' else result.get('transport',{}).get('provider_response')
        if family=='membership-jev':
            from commentscope.factory import jev_membership
            from commentscope.providers import openrouter_decisions
            if plan.get('membership_judge_protocol')!=jev_membership.VERSION or deployment!=openrouter_decisions.DEPLOYMENT:
                raise cost.CostPlanError('Typed membership deployment/protocol differs from frozen plan')
            openrouter_decisions.answers(request,result,deployment)
        model=(raw or {}).get('model','')
        allowed=deployment.get('response_models',[deployment['model']])
        provider='TypeSafe' if family=='membership-jev' else 'OpenAI'
        if (raw is None or raw.get('provider')!=provider and not family.startswith('embedding-')
                or not any(model==m or re.fullmatch(re.escape(m)+r'-\d{8}',model) for m in allowed)
                or cost.amount(raw['usage']['cost'])!=charge):
            raise cost.CostPlanError('Original model/provider/cost receipt required')
        row=stages.setdefault(family,{'calls':0,'cost_usd':Decimal(0),'maximum_cost_usd':Decimal(0),
            'deployment_sha256':digest(deployment),'model':deployment['model'],
            'prompt_tokens':0,'completion_tokens':0,'cached_prompt_tokens':0,'cache_write_tokens':0,
            'cache_detail_responses':0})
        if family in cost.GRAPH_STAGES:
            protocol=plan.get('source_evidence_protocol')
            # Historical requests without a wire tag remain historical; a new
            # profile must bind both its frozen plan and exact request protocol.
            declared=request.get('data',{}).get('EVIDENCE_PROTOCOL')
            historical=('source-evidence-graph-20261111-v1','source-evidence-graph-20261112-v2')
            if not protocol or declared!=protocol and not (declared is None and protocol in historical):
                raise cost.CostPlanError('Source evidence cost protocol differs from frozen request/plan')
            row['source_evidence_protocol']=protocol
        row['calls']+=1;row['cost_usd']+=charge;row['maximum_cost_usd']=max(row['maximum_cost_usd'],charge)
        if family=='membership-source-batch':
            row['maximum_batch_targets']=max(row.get('maximum_batch_targets',0),len(request['data']['CANDIDATE_TARGETS']))
        if family=='membership-jev':
            row['maximum_questions']=max(row.get('maximum_questions',0),len(request['questions']))
        usage=raw['usage']
        row['prompt_tokens']+=usage.get('prompt_tokens',0);row['completion_tokens']+=usage.get('completion_tokens',0)
        details=usage.get('prompt_tokens_details')
        if isinstance(details,dict):
            row['cache_detail_responses']+=1;row['cached_prompt_tokens']+=details.get('cached_tokens',0)
            row['cache_write_tokens']+=details.get('cache_write_tokens',0)
    for row in (*stages.values(),*other.values()):
        for key in ('cost_usd','maximum_cost_usd'):
            if key in row:row[key]=str(row[key])
    return {'artifact_kind':cost.PROFILE,'origin':str(directory.resolve()),'plan_sha256':sha(directory/'plan.json'),
        'stages':stages,'other_historical_stages':other,'total_confirmed_usd':str(total),
        'completed_responses':completed,'pending_requests':pending,'new_model_calls':0,
        'semantic_input_reuse':False,'quality_approval':False}


def available(plan):
    p=plan['spend_policy'];money=SpendLedger(p['ledger'],p['account_id'],maximum_usd=p['maximum_usd'],
                                         opening_charge_usd=p['opening_charge_usd'])
    shared=money.summary();own=money.summary(plan_sha256=plan['spend_scope_sha256'])
    if shared['reserved_calls'] or shared['uncertain_calls']:
        raise cost.CostPlanError('Active or uncertain money must settle before full execution')
    charge=cost.amount(own['charged_usd'])
    if charge<cost.amount(plan['opening_scope_charge_usd']):
        raise cost.CostPlanError('Inherited money history cannot be reset')
    trial=cost.amount(plan['subcap_usd'])-(charge-cost.amount(plan['opening_scope_charge_usd']))
    return max(Decimal(0),min(trial,cost.amount(plan['maximum_cost_usd'])-charge,cost.amount(shared['remaining_usd'])))


def verify_profile(profile):
    if audit(Path(profile['origin']))!=profile:
        raise cost.CostPlanError('Cost reference differs from its original archived requests/receipts')


def completed_counts(directory,plan,*,allow_pending=False):
    counts=Counter()
    directory=Path(directory)
    if not allow_pending and any(not p.with_name(p.name.replace('.intent.json','.result.json')).exists()
            for p in (directory/'checkpoints').glob('*.intent.json')):
        raise cost.CostPlanError('Pending original checkpoint; no automatic paid retry')
    for stage,request,result in call_rows(directory,plan,require_settled=not allow_pending):
        if result is not None:counts[cost.canonical(stage,request)]+=1
    return counts


def calculate(directory,workload,profiles,available_usd,*,allow_pending=False):
    directory=Path(directory);plan=read_json(directory/'plan.json');candidates=read_json(directory/'artifacts/initial-candidates.json')
    if workload.get('version')!=cost.VERSION or not isinstance(workload.get('assumptions'),list) or not workload['assumptions']:
        raise cost.CostPlanError('Versioned workload with explicit assumptions required')
    if (workload.get('target_plan_sha256',sha(directory/'plan.json'))!=sha(directory/'plan.json')
            or workload.get('candidate_sha256',sha(directory/'artifacts/initial-candidates.json'))
                !=sha(directory/'artifacts/initial-candidates.json')):
        raise cost.CostPlanError('Workload template belongs to another plan or candidate version')
    return cost.estimate(plan,candidates,workload['counts'],profiles,
        completed=completed_counts(directory,plan,allow_pending=allow_pending),available_usd=available_usd,
        multiplier=workload['multiplier'],headroom_usd=workload['headroom_usd'],goal=workload['goal'])


def template(directory):
    from commentscope.providers.remote_verification import batches
    directory=Path(directory);plan=read_json(directory/'plan.json')
    candidates=read_json(directory/'artifacts/initial-candidates.json');n=len(plan['scope_ids']);k=len(candidates)
    completed=completed_counts(directory,plan,allow_pending=True)
    counts=dict.fromkeys(cost.STAGES,None)
    counts.update({'shared-discovery':max((n+11)//12,completed['shared-discovery']),
        'source-context':n if k else 0,'source-world':n if k else 0,'candidate-world':k,
        'membership-raw':cost.pair_schedule(plan['scope_ids'],candidates)['total_upper_bound'],
        'raw-candidate-route':k,'core':k,'core-fidelity':k,'runtime':3*k,
        'embedding-sources':completed['embedding-sources'] or None,
        'embedding-candidates':len(batches({c['id']:c['text'] for c in candidates})) if k else 0})
    counts['membership-source-batch']=0
    counts['membership-jev']=0
    if plan.get('membership_search_policy') is not None:
        from commentscope.factory import perspective_mining
        selected=perspective_mining.bounds(plan['membership_search_policy'],n,k)
        counts['source-context']=selected['source_upper_bound']
        counts['source-world']=selected['source_upper_bound']
        counts['membership-raw']=selected['pair_upper_bound']
    if plan.get('membership_batch_protocol'):
        counts['membership-raw']=0
        counts['membership-source-batch']=cost.packet_schedule(plan['scope_ids'],candidates)['total_upper_bound']
    if plan.get('membership_judge_protocol'):
        counts['membership-raw']=0
        counts['membership-jev']=None # Physical packet count depends on every segment/descriptor question.
    return {'version':cost.VERSION,'goal':'mvp','target_plan_sha256':sha(directory/'plan.json'),
        'candidate_sha256':sha(directory/'artifacts/initial-candidates.json'),
        'counts':counts,'multiplier':'1.25','headroom_usd':'0.15',
        'assumptions':['Shared retrieval schedule; no semantic success predicted.',
            'Unknown downstream counts remain null; measure or declare a justified finite cap before full execution.',
            'Historical prices include cache effects; this template is not financial authorization.']}


def prepare_review(directory,workload_file,profile_files):
    directory=Path(directory);plan=read_json(directory/'plan.json')
    ready=read_json(directory/'proposal-ready.json')
    if (ready['plan_sha256']!=sha(directory/'plan.json')
            or ready['candidates_sha256']!=sha(directory/'artifacts/initial-candidates.json')):
        raise cost.CostPlanError('Same-plan frozen proposals required')
    workload=read_json(workload_file);profiles=[read_json(p) for p in profile_files]
    for profile in profiles:verify_profile(profile)
    preview=calculate(directory,workload,profiles,available(plan))
    report={'artifact_kind':cost.VERSION+'-review','plan_sha256':sha(directory/'plan.json'),
        'candidates_sha256':sha(directory/'artifacts/initial-candidates.json'),
        'workload_file':str(Path(workload_file).resolve()),
        'profile_files':[str(Path(p).resolve()) for p in profile_files],
        'workload':workload,'profiles':profiles,
        'inputs':{str(Path(p).resolve()):sha(p) for p in (workload_file,*profile_files)},'preview':preview}
    report['integrity_sha256']=digest(report)
    path=(directory/'cost-preflight.json' if preview['estimated_feasible'] else
          directory/('cost-preflight-rejected-'+report['integrity_sha256'][:20]+'.json'))
    if path.exists():
        if read_json(path)!=report:raise cost.CostPlanError('Accepted cost review is immutable')
    else:write(path,report)
    return report


def require_review(directory,plan):
    directory=Path(directory);path=directory/'cost-preflight.json'
    if not path.exists():raise cost.CostPlanError('Full execution requires cost-preflight.json after proposal review')
    report=read_json(path);body={k:v for k,v in report.items() if k!='integrity_sha256'}
    if (report['artifact_kind']!=cost.VERSION+'-review' or digest(body)!=report['integrity_sha256']
            or report['plan_sha256']!=sha(directory/'plan.json')
            or report['candidates_sha256']!=sha(directory/'artifacts/initial-candidates.json')
            or any(sha(p)!=h for p,h in report['inputs'].items())
            or report['workload']!=read_json(report['workload_file'])
            or report['profiles']!=[read_json(p) for p in report['profile_files']]
            or not report['preview']['estimated_feasible']):
        raise cost.CostPlanError('Changed or infeasible full-stage cost review')
    for profile in report['profiles']:verify_profile(profile)
    now=calculate(directory,report['workload'],report['profiles'],available(plan))
    if not now['estimated_feasible']:raise cost.CostPlanError('Full execution cost is no longer covered: '+', '.join(now['issues']))
    prior=[(stage,request) for stage,request,_ in call_rows(directory,plan,require_settled=True)]
    return cost.CallLimits(report['workload']['counts'],prior)


def main():
    p=argparse.ArgumentParser(description=__doc__);a=p.add_subparsers(dest='action',required=True)
    q=a.add_parser('audit');q.add_argument('directory',type=Path);q.add_argument('--output',type=Path,required=True)
    q=a.add_parser('template');q.add_argument('directory',type=Path);q.add_argument('--output',type=Path,required=True)
    q=a.add_parser('review');q.add_argument('directory',type=Path);q.add_argument('--workload',type=Path,required=True)
    q.add_argument('--profiles',type=Path,nargs='+',required=True)
    q=a.add_parser('preview');q.add_argument('directory',type=Path);q.add_argument('--workload',type=Path,required=True)
    q.add_argument('--profiles',type=Path,nargs='+',required=True);q.add_argument('--available-usd',required=True)
    q.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    from experiments.openrouter_factory_probe import private
    private(args.directory)
    if hasattr(args,'output'):private(args.output)
    if args.action=='audit':result=audit(args.directory);write(args.output,result)
    elif args.action=='template':result=template(args.directory);write(args.output,result)
    elif args.action=='preview':
        result=calculate(args.directory,read_json(args.workload),[read_json(p) for p in args.profiles],
                         args.available_usd,allow_pending=True)
        result.update(new_model_calls=0,financial_authorization=False,execution_ready=False,preview_only=True,
            pending_requests=sum(r is None for _,_,r in call_rows(args.directory,read_json(args.directory/'plan.json'))))
        write(args.output,result)
    else:result=prepare_review(args.directory,args.workload,args.profiles)
    print(json.dumps({'action':args.action,'new_model_calls':0,
        'completed_responses':result.get('completed_responses'),
        'total_confirmed_usd':result.get('total_confirmed_usd'),
        'preview':result if args.action=='preview' else result.get('preview')},ensure_ascii=False))


if __name__=='__main__':main()
