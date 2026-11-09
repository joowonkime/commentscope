"""Full-stage cost estimates and request caps; never semantic or money approval."""
from collections import Counter
from decimal import Decimal
import re

from commentscope.factory.automatic_contract import digest

VERSION='factory-full-cost-plan-20261110-v1'
PROFILE=VERSION+'-profile'
STAGES=('shared-discovery','source-context','source-world','candidate-world','membership-raw',
        'raw-candidate-route','raw-own-evidence','core','core-fidelity','argument-node-metadata',
        'argument-position-alignment','argument-dependencies','argument-owner','argument-dependency',
        'argument-audit','facts','runtime','embedding-sources','embedding-candidates')
GENERATION={'argument-node-metadata','argument-position-alignment','argument-dependencies','runtime'}


class CostPlanError(ValueError):pass


def amount(value):
    try:result=Decimal(str(value))
    except Exception:raise CostPlanError('Finite nonnegative cost required') from None
    if not result.is_finite() or result<0 or isinstance(value,bool):
        raise CostPlanError('Finite nonnegative cost required')
    return result


def canonical(stage,request=None):
    family=re.sub(r'^(?:generation|verification)-','',stage)
    family=re.sub(r'-[a-f0-9]{20}$','',family)
    if family=='core' and isinstance((request or {}).get('data',{}).get('ORIGINALS'),list):
        family='shared-discovery'
    if family in ('nomination-raw','membership-initial-raw','membership-expanded-raw'):family='membership-raw'
    if family=='shared-owned-position':family='argument-position-alignment'
    if family not in STAGES:raise CostPlanError('Unplanned cost stage: '+family)
    return family


def deployment(plan,stage):
    field=('embedding_deployment' if stage.startswith('embedding-') else
           'deployment' if stage in GENERATION else 'verification_deployment')
    return plan[field]


def pair_schedule(source_ids,candidates):
    """Current shared top3+nominees then up-to3 expansion; no support prediction."""
    ids=set(source_ids)
    if len(ids)!=len(source_ids) or not ids:raise CostPlanError('Unique nonempty processing scope required')
    nominations=Counter()
    for c in candidates:
        for sid in c['nominees']:
            if sid not in ids:raise CostPlanError('Nominee outside processing scope')
            nominations[sid]+=1
    k=len(candidates)
    upper=sum(min(k,6+nominations[sid]) for sid in ids)
    return {'sources':len(ids),'candidates':k,'initial_minimum':len(ids)*min(k,3),
            'total_upper_bound':upper,'exact_total':len(ids)*k if k<=6 else None,
            'nomination_edges':sum(nominations.values()),'semantic_approval':False}


def estimate(plan,candidates,counts,profiles,*,completed=None,available_usd,
             multiplier='1.25',headroom_usd='0.15',goal='mvp'):
    if set(counts)!=set(STAGES):raise CostPlanError('Every cost stage must be explicit, including unknown/null')
    if goal not in ('mvp','development'):raise CostPlanError('Explicit cost goal required')
    if any(v is not None and (type(v) is not int or v<0) for v in counts.values()):
        raise CostPlanError('Nonnegative integer stage cap or null required')
    factor=amount(multiplier);headroom=amount(headroom_usd);available=amount(available_usd)
    if factor<1 or headroom<=0:raise CostPlanError('Safety factor >=1 and positive next-request headroom required')
    completed=completed or {};schedule=pair_schedule(plan['scope_ids'],candidates)
    n,k=schedule['sources'],schedule['candidates'];issues=[];unknown=[];rows=[]
    minimum={'shared-discovery':(n+11)//12,'source-context':n if k else 0,
        'source-world':n if k else 0,'candidate-world':k,'membership-raw':schedule['total_upper_bound'],
        'raw-candidate-route':k,'embedding-sources':1,'embedding-candidates':int(k>0)}
    if goal=='mvp':
        if k<2:issues.append('fewer_than_two_candidates')
        minimum.update(core=2,**{'core-fidelity':2,'raw-own-evidence':6,'argument-node-metadata':3,
            'argument-position-alignment':6,'argument-owner':6,'argument-dependency':3,
            'argument-audit':6,'runtime':6})
    for stage,cap in counts.items():
        done=completed.get(stage,0)
        if type(done) is not int or done<0:raise CostPlanError('Invalid completed call count')
        if cap is not None and cap<max(minimum.get(stage,0),done):issues.append('stage_cap_too_small:'+stage)
        remaining=None if cap is None else max(0,cap-done)
        choices=[]
        for profile in profiles:
            if profile.get('artifact_kind')!=PROFILE:raise CostPlanError('Versioned cost-only profile required')
            observed=profile['stages'].get(stage)
            if observed is None:continue
            if observed['deployment_sha256']!=digest(deployment(plan,stage)):continue
            if type(observed['calls']) is not int or observed['calls']<=0:raise CostPlanError('Measured sample count required')
            mean=amount(observed['cost_usd'])/observed['calls'];maximum=amount(observed['maximum_cost_usd'])
            if mean<=0 or maximum<mean:raise CostPlanError('Positive measured costs and consistent maximum required')
            choices.append((mean,maximum,profile['origin'],observed['calls']))
        # Do not dilute a larger-input observation with cheaper small fixtures.
        selected=max(choices,key=lambda row:row[0]) if choices else None
        cost=Decimal(0) if remaining==0 else selected[0]*remaining if selected and remaining is not None else None
        if cost is None:unknown.append(stage)
        rows.append({'stage':stage,'call_cap':cap,'completed_calls':done,'remaining_calls':remaining,
            'unit_mean_usd':str(selected[0]) if selected else None,
            'reference':selected[2] if selected else None,'reference_samples':selected[3] if selected else 0,
            'estimated_remaining_usd':str(cost) if cost is not None else None,
            'maximum_observed_projection_usd':str(selected[1]*remaining) if selected and remaining is not None else None})
    known=sum((amount(r['estimated_remaining_usd']) for r in rows if r['estimated_remaining_usd'] is not None),Decimal(0))
    total=None if unknown else known
    needs_calls=any(r['remaining_calls'] is None or r['remaining_calls']>0 for r in rows)
    required=None if total is None else total*factor+(headroom if needs_calls else 0)
    if unknown:issues.append('unmeasured_or_unplanned_stages')
    if total is None and known*factor+(headroom if needs_calls else 0)>available:
        issues.append('known_subtotal_exceeds_remaining_budget')
    if required is not None and required>available:issues.append('insufficient_remaining_budget')
    return {'artifact_kind':VERSION,'schedule':schedule,'goal':goal,'stages':rows,
        'known_remaining_estimate_usd':str(known),'estimated_remaining_usd':str(total) if total is not None else None,
        'required_with_margin_usd':str(required) if required is not None else None,
        'available_usd':str(available),'multiplier':str(factor),'headroom_usd':str(headroom),
        'unknown_stages':unknown,'issues':issues,'estimated_feasible':not issues,
        'cost_basis':'historical actual charges; source size, contract and cache behavior may differ',
        'financial_authorization':False,'semantic_approval':False,'completion_guaranteed':False}


class CallLimits:
    """Count physical request identities; same-stage checkpoint reuse costs zero."""
    def __init__(self,counts,existing=()):
        if set(counts)!=set(STAGES) or any(type(v) is not int or v<0 for v in counts.values()):
            raise CostPlanError('Complete finite stage caps required')
        self.caps=dict(counts);self.seen=set();self.used=Counter()
        for stage,req in existing:self.admit(stage,req)

    def admit(self,stage,request):
        family=canonical(stage,request);key=(stage,digest(request))
        if key in self.seen:return
        if self.used[family]>=self.caps[family]:raise CostPlanError('Stage call cap reached: '+family)
        self.seen.add(key);self.used[family]+=1
