"""Independent own-policy evaluation, original admission and completed NLI gate."""
from copy import deepcopy
from collections import Counter
from commentscope.factory import minimal_claims as mc,minimal_membership as mm,owned_arguments as oa
from commentscope.factory import policy_stance_hypotheses as stance,policy_attitude as attitude
from commentscope.factory import raw_membership as raw,raw_membership_verification as verification
from commentscope.factory import source_entailment
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.factory.automatic_contract import digest

VERSION='qualified-policy-admission-20261023-v1'


def process(sources,record,completed_request,response,runner,inspect,*,save=None):
    save=save or (lambda name,value:None);registry=mc.source_index(sources)
    stance.validate(record)
    if record['sources']!=sources or stance.invocation(sources,record['topic'],record['alias'])!=completed_request or record['response']!=response:
        raise ValueError('Every original and exact completed comparison must remain bound')
    candidates=stance.candidates(record);lookup={c['id']:c for c in candidates}
    polarities={c['id']:c['polarity'] for c in stance.hypotheses(sources,record['topic'],record['alias'])}
    errors=[];holds=[];raw_batches=[];attitudes={};routes=[];cores=[];outcomes=[]
    def request(stage,req,bind):
        key=digest(req);capacity=inspect(req)
        if capacity['request_sha256']!=key:raise ValueError('Capacity request changed')
        save('policy-admission-capacity/'+key,capacity)
        if not capacity['fits']:
            holds.append({'stage':stage,'request_sha256':key,'reason':'context_capacity'});return None
        try:result=runner.call(stage+'-'+key[:24],req)
        except PriorRequestUnavailable:
            holds.append({'stage':stage,'request_sha256':key,'reason':'prior_request_unavailable_no_retry'});return None
        if result.get('raw') is None and result.get('errors'):
            raise RuntimeError('Incomplete request requires process/ledger reconciliation')
        try:bound=bind(result)
        except (ValueError,KeyError,TypeError) as exc:
            error={'stage':stage,'request_sha256':key,'exception':type(exc).__name__,'message':str(exc)}
            errors.append(error);save('policy-admission-errors/'+key,{'error':error,'result':result});return None
        save('policy-admission-bound/'+key+'-'+digest(bound)[:16],bound);return bound
    nominee_ids={sid for c in candidates for sid in c['nominees']}
    for sid in sorted(nominee_ids,key=lambda sid:(len(registry[sid]['text']),sid)):
        source=registry[sid]
        bound=request('own-policy-evaluation',attitude.request(source,record['topic']),
            lambda result:attitude.bind(source,record['topic'],result))
        if bound is not None:attitudes[sid]=bound
        save('policy-attitudes/'+sid,bound)
    for cid,candidate in sorted(lookup.items()):
        polarity=polarities[cid];outcome={'candidate_id':cid,'polarity':polarity,'nominees':sorted(candidate['nominees']),
            'own_evaluation_holds':[],'attempted_source_ids':[],'qualified_sources':[],'semantic_approval':False}
        outcomes.append(outcome)
        eligible=[]
        for sid in candidate['nominees']:
            own=attitudes.get(sid)
            if own is None or polarity not in attitude.validate(own)['passed_polarities']:
                outcome['own_evaluation_holds'].append(sid)
            else:eligible.append(sid)
        if not eligible:save('policy-admission-candidates/'+cid,outcome);continue
        origin=registry[min(candidate['nominees'])]
        route=request('policy-route',verification.route_request(candidate,origin,version=verification.ALIGNED),
            lambda result:verification.bind_route(candidate,result,origin,version=verification.ALIGNED))
        core=request('policy-core',oa.core_request(candidate),lambda result:oa.bind_core(candidate,result))
        if route is not None:routes.append(route)
        if core is not None:cores.append(core)
        if route is None or not route['passed'] or core is None or core['hold_reasons'] or core['output']['kind']!='value':
            holds.append({'candidate_id':cid,'reason':'policy_value_route_or_core_unapproved'})
            save('policy-admission-candidates/'+cid,outcome);continue
        for sid in sorted(eligible,key=lambda sid:(len(registry[sid]['text']),sid)):
            source=registry[sid];outcome['attempted_source_ids'].append(sid)
            proposed=request('policy-original',raw.request(source,candidate),lambda result:raw.bind(source,candidate,result))
            if proposed is None:continue
            evidence=None
            if proposed['passed']:
                evidence=request('policy-own-evidence',verification.evidence_request(proposed,verification.ALIGNED),
                    lambda result:verification.bind_evidence(proposed,result,verification.ALIGNED))
            assessment=verification.assessment(proposed,route,evidence,version=verification.ALIGNED)
            batch=verification.batch([source],[candidate],[assessment],version=verification.ALIGNED)
            raw_batches.append(batch);save('policy-raw-memberships/'+cid+'/'+sid,batch)
        save('policy-admission-candidates/'+cid,outcome)
    qualified=source_entailment.from_completed_comparisons(sources,candidates,raw_batches,completed_request,response)
    rows=mm.collect(sources,candidates,[qualified]);counts=Counter(r['candidate_id'] for r in rows if r['relation']=='supported')
    for outcome in outcomes:
        outcome['qualified_sources']=[r['source_id'] for r in rows if r['candidate_id']==outcome['candidate_id'] and r['relation']=='supported']
    save('policy-qualified-memberships',qualified);save('policy-final-outcomes',outcomes)
    return {'artifact_kind':VERSION,'candidates':candidates,'source_attitudes':attitudes,'raw_memberships':raw_batches,
        'qualified_memberships':[qualified],'outcomes':outcomes,'routes':routes,'cores':cores,
        'ready_candidate_ids':sorted(cid for cid,n in counts.items() if n>=3),
        'errors':errors,'holds':holds,'semantic_approval':False,'quality_gate_passed':False}
