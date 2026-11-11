"""Full-stage cost estimates and request caps; never semantic or money approval."""
from collections import Counter
from decimal import Decimal
import re

from commentscope.factory.automatic_contract import digest

VERSION='factory-full-cost-plan-20261110-v3'
PROFILE=VERSION+'-profile'
STAGES=('shared-discovery','source-context','source-world','candidate-world','membership-raw','membership-source-batch','membership-jev',
        'raw-candidate-route','raw-own-evidence','core','core-fidelity','argument-node-metadata',
        'argument-position-alignment','argument-dependencies','argument-owner','argument-dependency',
        'argument-audit','facts','runtime','embedding-sources','embedding-candidates')
GENERATION={'argument-node-metadata','argument-position-alignment','argument-dependencies','runtime'}
GRAPH_STAGES=('source-evidence-proposal','source-evidence-observation','source-evidence-candidates')
GENERATION.add('source-evidence-proposal')


def stages(plan):
    protocol=plan.get('source_evidence_protocol')
    if protocol is None:return STAGES
    from commentscope.factory.source_evidence_graph import VERSION as GRAPH_VERSION
    if protocol!=GRAPH_VERSION:raise CostPlanError('Unknown source evidence cost protocol')
    return (*STAGES,*GRAPH_STAGES)


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
    data=(request or {}).get('data',{})
    if not isinstance(data,dict):data={}
    if family=='core' and isinstance(data.get('ORIGINALS'),list):
        family='shared-discovery'
    if family in ('nomination-raw','membership-initial-raw','membership-expanded-raw'):family='membership-raw'
    if family=='membership-raw' and isinstance(data.get('CANDIDATE_TARGETS'),list):
        family='membership-source-batch'
    if family=='shared-owned-position':family='argument-position-alignment'
    if family not in (*STAGES,*GRAPH_STAGES):raise CostPlanError('Unplanned cost stage: '+family)
    return family


def deployment(plan,stage):
    if stage=='membership-jev':return plan.get('membership_deployment',plan['verification_deployment'])
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


def packet_schedule(source_ids, candidates):
    """Safe physical upper bound across nomination, initial and expansion phases.

    Exact pair cache hits may reduce this bound; they are never assumed to
    survive consolidation's changes to candidate provenance.
    """
    from commentscope.factory.source_membership_batch import MAX_TARGETS
    pair_schedule(source_ids,candidates)
    nominations=Counter(sid for c in candidates for sid in c['nominees'])
    k=len(candidates);width=MAX_TARGETS
    counts=[nominations[sid] for sid in source_ids]
    initial=[min(k,3+count) for count in counts]
    expand=[min(k,3)]*len(source_ids)
    sizes=counts+initial+expand
    return {'total_upper_bound':sum((count+width-1)//width for count in sizes),
            'maximum_targets':max((min(width,count) for count in sizes),default=0),
            'semantic_approval':False}


def estimate(plan,candidates,counts,profiles,*,completed=None,available_usd,
             multiplier='1.25',headroom_usd='0.15',goal='mvp'):
    if set(counts)!=set(stages(plan)):raise CostPlanError('Every cost stage must be explicit, including unknown/null')
    if goal not in ('mvp','development'):raise CostPlanError('Explicit cost goal required')
    if any(v is not None and (type(v) is not int or v<0) for v in counts.values()):
        raise CostPlanError('Nonnegative integer stage cap or null required')
    factor=amount(multiplier);headroom=amount(headroom_usd);available=amount(available_usd)
    if factor<1 or headroom<=0:raise CostPlanError('Safety factor >=1 and positive next-request headroom required')
    completed=completed or {};schedule=pair_schedule(plan['scope_ids'],candidates)
    n,k=schedule['sources'],schedule['candidates'];issues=[];unknown=[];rows=[]
    from commentscope.factory import perspective_mining
    mining = plan.get('membership_search_policy')
    search_bounds = perspective_mining.bounds(mining,n,k) if mining is not None else None
    from commentscope.factory.source_membership_batch import VERSION as BATCH_VERSION
    protocol=plan.get('membership_batch_protocol')
    if protocol not in (None,BATCH_VERSION):raise CostPlanError('Unknown membership batch protocol')
    packets=packet_schedule(plan['scope_ids'],candidates) if protocol else None
    from commentscope.factory import jev_membership
    typed=plan.get('membership_judge_protocol')
    if typed not in (None,jev_membership.VERSION) or typed and packets:
        raise CostPlanError('Explicit exclusive membership protocol required')
    if search_bounds and packets:
        raise CostPlanError('Candidate-first search does not use source-batch transport')
    if typed:
        from commentscope.providers import openrouter_decisions
        if plan.get('membership_deployment')!=openrouter_decisions.DEPLOYMENT:
            raise CostPlanError('Frozen Jev membership deployment required')
    observed_sources = search_bounds['source_upper_bound'] if search_bounds else n
    raw_pairs = search_bounds['pair_upper_bound'] if search_bounds else schedule['total_upper_bound']
    minimum={'shared-discovery':(n+11)//12,'source-context':observed_sources if k else 0,
        'source-world':observed_sources if k else 0,'candidate-world':k,'membership-raw':0 if packets or typed else raw_pairs,
        'membership-source-batch':packets['total_upper_bound'] if packets else 0,
        'membership-jev':raw_pairs if typed else 0,
        'raw-candidate-route':k,'embedding-sources':1,'embedding-candidates':int(k>0)}
    if goal=='mvp':
        if k<2:issues.append('fewer_than_two_candidates')
        minimum.update(core=2,**{'core-fidelity':2,'raw-own-evidence':6,'argument-node-metadata':3,
            'argument-position-alignment':6,'argument-owner':6,'argument-dependency':3,
            'argument-audit':6,'runtime':6})
        if plan.get('source_evidence_protocol'):
            for stage in ('argument-node-metadata','argument-position-alignment','argument-dependencies','argument-owner','argument-dependency','argument-audit'):
                minimum.pop(stage,None)
            minimum.update({stage:6 for stage in GRAPH_STAGES})
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
            if (stage=='membership-source-batch' and packets
                    and observed.get('maximum_batch_targets',0)<packets['maximum_targets']):continue
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
    return {'artifact_kind':VERSION,'schedule':schedule,**({'mining_bounds':search_bounds} if search_bounds else {}),'goal':goal,'stages':rows,
        'known_remaining_estimate_usd':str(known),'estimated_remaining_usd':str(total) if total is not None else None,
        'required_with_margin_usd':str(required) if required is not None else None,
        'available_usd':str(available),'multiplier':str(factor),'headroom_usd':str(headroom),
        'unknown_stages':unknown,'issues':issues,'estimated_feasible':not issues,
        'cost_basis':'historical actual charges; source size, contract and cache behavior may differ',
        'financial_authorization':False,'semantic_approval':False,'completion_guaranteed':False}


class CallLimits:
    """Count physical request identities; same-stage checkpoint reuse costs zero."""
    def __init__(self,counts,existing=()):
        if set(counts) not in (set(STAGES),set(STAGES)|set(GRAPH_STAGES)) or any(type(v) is not int or v<0 for v in counts.values()):
            raise CostPlanError('Complete finite stage caps required')
        self.caps=dict(counts);self.seen=set();self.used=Counter()
        for stage,req in existing:self.admit(stage,req)

    def admit(self,stage,request):
        family=canonical(stage,request);key=(stage,digest(request))
        if key in self.seen:return
        if family not in self.caps:raise CostPlanError('Stage absent from frozen call caps: '+family)
        if self.used[family]>=self.caps[family]:raise CostPlanError('Stage call cap reached: '+family)
        self.seen.add(key);self.used[family]+=1
