"""Freeze fidelity inputs and conservative costs without dispatch or authority.

No HTTP, key loading, paid reservation, model runner or authorization writer.
Read-only endpoint/account observations must be supplied as a separate input.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'src'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from commentscope.factory import source_evidence_graph as g,cost_planning as cost
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import openrouter,remote_verification as remote

VERSION='source-fidelity-validation-plan-20261112-v2'
CONTROL_VERSION='source-fidelity-controls-20261112-v2'
FAMILIES={'negation','possibility','desired_world','reported_ownership','missing_condition',
          'missing_reason','hidden_fact_premise','scope_qualifiers'}
VARIANTS=('faithful','distorted')


def reservation(request,deployment):
    capacity=openrouter.Client(deployment).measure(request)
    if not capacity['fits']:raise ValueError('Canonical request exceeds frozen context')
    prices={k:Decimal(str(v)) for k,v in openrouter.billing_prices(deployment).items()}
    value=(Decimal(capacity['input_upper_bound_tokens']+capacity['provider_margin'])*prices['prompt']
           +Decimal(capacity['output_reservation'])*prices['completion'])/1_000_000+prices['request']
    return dict(capacity=capacity,maximum_reservation_usd=str(value))


def controls(fixture,deployment):
    if (fixture.get('version')!=CONTROL_VERSION or fixture.get('source_kind')!='authored_synthetic'
            or fixture.get('annotation_kind')!='authored_reference_not_independent_human_gold'
            or len(fixture['families'])!=8 or {r['family'] for r in fixture['families']}!=FAMILIES):
        raise ValueError('All eight fixed authored control pairs required')
    if deployment!=remote.SOL:raise ValueError('Frozen fidelity reviewer deployment required')
    rows=[];source_ids=[]
    for family in fixture['families']:
        if set(family)!={'family','source','expected_detection',*VARIANTS} or family['faithful']==family['distorted']:
            raise ValueError('Distinct complete paired proposals required')
        expected=family['expected_detection']
        if (set(expected)!={'unit_failures','source_failures','coverage_failure','missing_units','missing_edges'}
                or any(not set(fields)<=set(g.UNIT_CHECKS) for fields in expected['unit_failures'].values())
                or not set(expected['source_failures'])<={'scope_coverage','ownership_coverage','dependency_coverage'}
                or any(type(expected[k]) is not bool for k in ('coverage_failure','missing_units','missing_edges'))):
            raise ValueError('Closed authored detection reference required')
        env=g.envelope(family['source'],snapshot_id=CONTROL_VERSION,snapshot_sha256=digest(fixture))
        source_ids.append(family['source']['id'])
        for variant in VARIANTS:
            proposal=g.bind_annotation(env,{'output':family[variant]});request=g.observation_request(proposal)
            rows.append(dict(case_id='C'+digest([family['family'],variant,proposal])[:20],family=family['family'],
                variant=variant,proposal=proposal,request=request,request_sha256=digest(request),
                expected_detection=deepcopy(expected),
                **reservation(request,deployment)))
    if len(source_ids)!=len(set(source_ids)):raise ValueError('Distinct synthetic family sources required')
    rows.sort(key=lambda r:digest(['source-fidelity-audit-order-v1',r['case_id']]))
    return dict(version=VERSION,source_evidence_protocol=g.VERSION,fixture=deepcopy(fixture),
        deployment=deepcopy(deployment),cases=rows,code_sha256=source_code_hashes(),planner_sha256=sha(Path(__file__)),
        dispatch_enabled=False,financial_authorization=False,semantic_adoption=False)


def validate_controls(pack):
    if controls(pack['fixture'],pack['deployment'])!=pack:raise ValueError('Frozen control/request/deployment/cost changed')


def cost_review(pack,*,proposed_usd,account_remaining_usd,key_remaining_usd):
    validate_controls(pack)
    cap=cost.amount(proposed_usd);account=cost.amount(account_remaining_usd);key=cost.amount(key_remaining_usd)
    if cap<=0:raise ValueError('Finite positive proposed cap required')
    values=[cost.amount(r['maximum_reservation_usd']) for r in pack['cases']]
    total=sum(values,Decimal(0));headroom=max(values)
    return dict(version=VERSION,pack_sha256=digest(pack),proposed_usd=str(cap),
        controls_maximum_reservation_usd=str(total),headroom_usd=str(headroom),
        controls_required_with_headroom_usd=str(total+headroom),
        controls_fit=total+headroom<=min(cap,account,key),
        full_comparison_estimated_usd=None,full_comparison_admitted=False,
        unmeasured_stages=[g.VERSION+' source proposal',g.VERSION+' source audit','candidate certificates','required facts','runtime'],
        cost_kind='conservative exact-wire reservation, not measured or predicted actual charge',
        financial_authorization=False,dispatch_enabled=False,new_model_calls=0)


def split_review(review,registry):
    def source(sid):
        if sid not in registry:raise ValueError('Split source missing from original registry')
        return registry[sid]['source']
    def thread(sid):
        s=source(sid);return s['parent']['id'] if s['parent'] else sid
    dev=review['development'];transfer=review['transfer']
    dids=[r['source']['id'] for r in dev];tids=[r['source_id'] for r in transfer]
    if len(dids)!=48 or len(tids)!=48 or len(set(dids))!=48 or len(set(tids))!=48 or set(dids)&set(tids):
        raise ValueError('Frozen distinct 48 development / 48 transfer sources required')
    for row in dev:
        sid=row['source']['id']
        if source(sid)!=row['source'] or digest(source(sid))!=row['source_sha256']:raise ValueError('Development source changed')
    for row in transfer:
        if digest(source(row['source_id']))!=row['source_sha256']:raise ValueError('Transfer source changed')
    overlap={thread(sid) for sid in dids}&{thread(sid) for sid in tids}
    if overlap:raise ValueError('Development/transfer thread leakage')
    n=sum(r.get('expected_semantics') is not None for r in dev)
    return dict(development_ids=dids,transfer_ids=tids,overlapping_threads=[],
        development_with_any_reference=n,development_unannotated=48-n,
        semantic_benchmark_ready=False,independent_human_gold=False,
        reference_status='Reference presence alone does not prove complete relation/proposition gold.',
        transfer_kind='annotation_blind_same_corpus_not_unseen_domain')


def score_controls(pack,answers):
    """Diagnostic scoring; receipt validity is distinct from a scripted output."""
    validate_controls(pack);ids={r['case_id'] for r in pack['cases']}
    if not isinstance(answers,dict) or not set(answers)<=ids:raise ValueError('Unknown control result identity')
    rows=[]
    for row in pack['cases']:
        result=answers.get(row['case_id']);valid=False;complete=False;detected=False;receipt=False;error=None
        if result is not None:
            try:
                observation=g.bind_observation(row['proposal'],result);verified=g.verify(row['proposal'],observation)
                valid=True;complete=verified['status']=='complete';o=observation['output']
                expected=row['expected_detection'];units={u['unit_id']:u for u in o['unit_observations']}
                detected=(any(units.get(uid,{}).get(field)=='fail' for uid,fields in expected['unit_failures'].items() for field in fields)
                    or any(o[field]=='fail' for field in expected['source_failures'])
                    or expected['coverage_failure'] and any(v['no_substantive_omission']=='fail' or v['missing_refs'] for v in o['coverage_observations'])
                    or expected['missing_units'] and bool(o['missing_units'])
                    or expected['missing_edges'] and bool(o['missing_edges']))
                try:remote.parsed_receipt(result,row['request'],pack['deployment']);receipt=True
                except (ValueError,KeyError,TypeError,IndexError):pass
            except (ValueError,KeyError,TypeError,IndexError) as exc:error=type(exc).__name__
        rows.append(dict(case_id=row['case_id'],family=row['family'],variant=row['variant'],present=result is not None,
            schema_valid=valid,receipt_valid=receipt,source_complete=complete,definite_problem_detected=detected,error=error))
    good=[r for r in rows if r['variant']=='faithful'];bad=[r for r in rows if r['variant']=='distorted']
    retained=sum(r['source_complete'] for r in good);false=sum(r['source_complete'] for r in bad)
    detected=sum(r['definite_problem_detected'] for r in bad)
    return dict(version=VERSION,planned_cases=len(rows),missing_cases=sum(not r['present'] for r in rows),
        invalid_cases=sum(r['present'] and not r['schema_valid'] for r in rows),
        unreceipted_cases=sum(r['present'] and not r['receipt_valid'] for r in rows),
        faithful_retained=retained,distorted_false_approvals=false,
        distorted_blocked=sum(r['schema_valid'] and not r['source_complete'] for r in bad),distorted_detected=detected,
        next_stage_ready=all(r['present'] and r['schema_valid'] and r['receipt_valid'] for r in rows)
            and not false and retained>=5 and detected>=5,
        profiling_floor=dict(faithful_retained=5,distorted_detected=5,distorted_false_approvals=0,denominator_per_variant=8),
        next_stage_scope='Only bounded source profiling; not full comparison, model adoption or spending permission.',
        semantic_adoption=False,financial_authorization=False,rows=rows)


def freeze(path,value):
    path=Path(path);payload=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if path.exists():
        if path.read_text(encoding='utf-8')!=payload:raise ValueError('Refusing changed frozen planning output')
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:f.write(payload)


def build(old_plan_file,review_file,fixture_file,observations_file,*,proposed_usd=None):
    paths=[Path(p).resolve() for p in (old_plan_file,review_file,fixture_file,observations_file)]
    old=read_json(paths[0]);review=read_json(paths[1]);observations=read_json(paths[3])
    previous_root=paths[0].parent.parent
    close_file=previous_root/'financial-close.json';outcome_file=previous_root/'outcome.json'
    closed=read_json(close_file);outcome=read_json(outcome_file)
    if (old.get('source_evidence_protocol')!='source-evidence-graph-20261111-v1'
            or outcome.get('status')!='budget_stopped_no_new_inference'
            or closed['phase']['reserved_calls'] or closed['phase']['uncertain_calls']):
        raise ValueError('Original v1 trial must remain closed and settled')
    for path,expected in old['inputs'].items():
        if sha(Path(path))!=expected:raise ValueError('Original comparison input changed')
    if observations.get('new_model_calls')!=0:raise ValueError('Read-only observations required')
    for field in ('generation_endpoint','verification_endpoint'):
        if 'error_type' in observations.get(field,{}):raise ValueError('Provider preflight failed')
    generation=old['deployment'];verification=remote.SOL
    for field,dep in [('generation_endpoint',generation),('verification_endpoint',verification)]:
        observed=observations[field];prices=openrouter.endpoint_price_ceiling(observed['pricing'])
        if (observed['tag']!='openai' or observed['context_length']!=dep['context']
                or not openrouter.required_parameters(dep)<=set(observed['supported_parameters'])
                or any(Decimal(str(observed['pricing'].get(k,0)))>Decimal(str(v))/(1 if k=='request' else 1_000_000)
                    for k,v in dep['provider']['max_price'].items())
                or any(prices[k]>Decimal(str(v)) for k,v in openrouter.billing_prices(dep).items())):
            raise ValueError('Observed endpoint differs from frozen route/capabilities/billing ceiling')
    artifacts=Path(old['baseline_artifacts']);registry=read_json(artifacts/'source-discourse.json')
    opinions=read_json(artifacts/'map.json')['opinion_map']['perspectives']
    eligible=[p for p in opinions if p['minimum_support_met']]
    pairs=sorted((p['id'],sid) for p in eligible for sid in p['supported_canonical_ids'])
    annotations=read_json(Path(old['annotations']))
    if set(pairs)!={(r['candidate_id'],r['source_id']) for r in annotations['cases']}:raise ValueError('Eligible pair inventory changed')
    ids=sorted({sid for _,sid in pairs});sources=[registry[sid]['source'] for sid in ids]
    chosen=[]
    for parents,label,median in ((False,'longest_root',False),(True,'longest_reply',False),(False,'median_root',True)):
        group=sorted((s for s in sources if bool(s['parent'])==parents and s['id'] not in {r['source_id'] for r in chosen}),key=lambda s:(len(s['text']),digest(s)))
        if group:
            s=group[len(group)//2] if median else group[-1]
            chosen.append(dict(source_id=s['id'],source_sha256=digest(s),selection=label))
    for s in sorted(sources,key=digest):
        if len(chosen)>=min(3,len(sources)):break
        if s['id'] not in {r['source_id'] for r in chosen}:chosen.append(dict(source_id=s['id'],source_sha256=digest(s),selection='coverage_fill'))
    pack=controls(read_json(paths[2]),verification)
    account=observations['account'];key=observations['key_metadata']
    if (account['reserved_calls'] or account['uncertain_calls']
            or cost.amount(account['maximum_usd'])>cost.amount(key['limit'])
            or key.get('limit')!=150):raise ValueError('Unsettled or changed account authority needs reconciliation')
    if cost.amount(account['charged_usd'])<cost.amount(closed['account']['charged_usd']):
        raise ValueError('Inherited account charges regressed; reconcile before planning')
    for name in ('candidates','memberships','source-discourse','map'):paths.append(artifacts/(name+'.json'))
    paths.append(Path(old['annotations']))
    paths.extend([close_file,outcome_file,Path(__file__).resolve()])
    available=min(cost.amount(account['remaining_usd']),cost.amount(key['limit_remaining']))
    return dict(version=VERSION,source_evidence_protocol=g.VERSION,inputs={str(p):sha(p) for p in paths},
        budget_policy=dict(mode='cumulative_team_credit',team_limit_usd=str(key['limit']),
            account_limit_usd=account['maximum_usd'],account_reconciliation_required=cost.amount(account['maximum_usd'])!=cost.amount(key['limit']),
            small_subcap_usd=None,historical_spending_preserved=True),
        controls=pack,cost_review=cost_review(pack,proposed_usd=available if proposed_usd is None else proposed_usd,account_remaining_usd=account['remaining_usd'],key_remaining_usd=key['limit_remaining']),
        source_inventory=dict(eligible_candidates=len(eligible),eligible_sources=len(ids),eligible_pairs=len(pairs),
            sources=[dict(source=s,source_sha256=digest(s)) for s in sources],pairs=[dict(candidate_id=c,source_id=s) for c,s in pairs],
            representative_profiling=chosen,whole999_fresh=False),
        split_review=split_review(review,registry),reference_provenance=annotations['reviewer_kind'],
        generation_deployment=deepcopy(generation),verification_deployment=deepcopy(verification),
        old_trial_closed=True,old_money_owner=old['spend_scope_sha256'],new_money_owner=None,
        started_at=None,deadline=None,authorization=None,dispatch_enabled=False,new_model_calls=0,semantic_adoption=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('old-plan','review','observations','output'):parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--controls',type=Path,default=ROOT/'tests/fixtures/source-fidelity-controls-v2.json')
    parser.add_argument('--proposed-usd',help='Optional what-if cap; default uses cumulative available balance');args=parser.parse_args()
    dest=args.output.resolve()
    if dest.is_relative_to(ROOT) and dest.relative_to(ROOT).parts[0] not in ('runs','artifacts'):
        parser.error('Private source planning output must stay outside tracked files')
    value=build(args.old_plan,args.review,args.controls,args.observations,proposed_usd=args.proposed_usd)
    freeze(dest,value)
    print(json.dumps(dict(controls=len(value['controls']['cases']),**value['cost_review'],
        source_counts={k:v for k,v in value['source_inventory'].items() if k.startswith('eligible_')},
        development_with_any_reference=value['split_review']['development_with_any_reference'])))


if __name__=='__main__':main()
