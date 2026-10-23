"""Staged admission of original sources into untrusted common hypotheses.

Retrieval schedules independent original/evidence judgments; it never votes.
No discovery or evaluation labels enter this module. The downstream callback
decides whether actual compiled, distinct Agents exist, not mere support counts.
"""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import raw_membership as raw, raw_membership_verification as verification
from commentscope.factory import owned_arguments as oa
from commentscope.factory.automatic_contract import digest
from commentscope.factory.framed_corpus import normalized, similarity

VERSION = 'staged-common-original-admission-20261023-v2'
POLICY = {'nearest_initial': 6, 'nearest_expansion': 6, 'maximum_sources_per_candidate': 24,
          'minimum_core_support': 3, 'expand_after_support': 1,
          'core_kinds_before_facts': ['value', 'prediction'],
          'search_order': 'all_initial_prefixes_then_verified_support_priority',
          'verification_contract': verification.ALIGNED}


class PriorRequestUnavailable(RuntimeError):
    """An earlier unresolved/interrupted exact request must not be resent."""


def process(sources, candidates, source_vectors, candidate_vectors, runner, inspect, *, on_shared, save=None):
    save = save or (lambda name, value: None)
    registry = mc.source_index(sources)
    lookup = {c['id']: mc.validate_candidate(c) for c in candidates}
    if len(lookup) != len(candidates): raise ValueError('Duplicate common hypothesis')
    if any('meaning_context' in c for c in candidates):
        raise ValueError('Common admission cannot replace contextual discovery')
    sv = normalized(source_vectors, registry)
    cv = normalized(candidate_vectors, lookup) if lookup else {}
    if any(len(v) != len(next(iter(sv.values()))) for v in cv.values()):
        raise ValueError('Source and candidate embeddings differ')
    order = sorted(lookup, key=lambda cid: (-len(lookup[cid]['nominees']), cid))
    batches = []; routes = []; cores = []; errors = []; holds = []; outcomes = []

    def request(stage, req, bind):
        measured = inspect(req); key = digest(req)
        if measured['request_sha256'] != key: raise ValueError('Capacity identity changed')
        save('admission-capacity/'+key, measured)
        if not measured['fits']:
            holds.append({'stage': stage, 'request_sha256': key, 'reason': 'context_capacity'})
            return None
        try: result = runner.call(stage+'-'+key[:24], req)
        except PriorRequestUnavailable:
            holds.append({'stage':stage,'request_sha256':key,'reason':'prior_request_unavailable_no_retry'})
            return None
        try: record = bind(result)
        except (ValueError, KeyError, TypeError) as exc:
            error = {'stage': stage, 'request_sha256': key, 'exception': type(exc).__name__, 'message': str(exc)}
            errors.append(error); save('admission-errors/'+key, {'error': error, 'result': result})
            if result.get('raw') is None and result.get('errors'):
                raise RuntimeError('No completed response; inspect ledger before recovery')
            return None
        save('admission-bound/'+key+'-'+digest(record)[:16], record)
        return record

    states=[];stop_reason='candidate_inventory_exhausted';done=False

    def assess(state, until):
        candidate=state['candidate'];outcome=state['outcome'];cid=candidate['id']
        while state['cursor'] < min(until,len(state['ranked'])):
            if len(outcome['supported_sources'])>=POLICY['minimum_core_support']:break
            sid=state['ranked'][state['cursor']];state['cursor']+=1;source=registry[sid]
            outcome['attempted_sources'].append(sid)
            proposed=request('original',raw.request(source,candidate),
                             lambda result:raw.bind(source,candidate,result))
            if proposed is None:continue
            outcome['assessed_sources'].append(sid);evidence=None
            if proposed['passed']:
                evidence=request('own-evidence',verification.evidence_request(proposed,verification.ALIGNED),
                    lambda result:verification.bind_evidence(proposed,result,verification.ALIGNED))
            assessment=verification.assessment(proposed,state['route'],evidence,version=verification.ALIGNED)
            batch=verification.batch([source],[candidate],[assessment],version=verification.ALIGNED)
            batches.append(batch);save('admission-memberships/'+cid+'/'+sid,batch)
            if assessment['passed']:outcome['supported_sources'].append(sid)
        mm.collect(sources,candidates,batches)
        return len(outcome['supported_sources'])>=POLICY['minimum_core_support']

    def notify(state):
        return on_shared(deepcopy(batches),deepcopy(outcomes))

    for cid in order:
        candidate = lookup[cid]
        if any(sid not in registry or candidate['nominees'][sid] != digest(registry[sid])
               for sid in candidate['nominees']):
            raise ValueError('Current exact nomination originals required')
        origin = registry[min(candidate['nominees'])]
        route = request('route', verification.route_request(candidate, origin, version=verification.ALIGNED),
            lambda result: verification.bind_route(candidate, result, origin, version=verification.ALIGNED))
        if route is not None: routes.append(route)
        outcome = {'candidate_id': cid, 'attempted_sources': [], 'assessed_sources': [], 'supported_sources': [],
                   'hold_reasons': [], 'semantic_approval': False}
        outcomes.append(outcome)
        if route is None or not route['passed']:
            outcome['hold_reasons'].append('candidate_route_unapproved')
        else:
            core = request('core', oa.core_request(candidate), lambda result: oa.bind_core(candidate, result))
            if core is not None: cores.append(core)
            if core is None or core['hold_reasons'] or core['output']['kind'] not in POLICY['core_kinds_before_facts']:
                outcome['hold_reasons'].append('core_not_ready_for_opinion_admission')
            else:
                nominees = sorted(candidate['nominees'])
                nearest = sorted(set(registry)-set(nominees),
                    key=lambda sid: (-similarity(sv[sid], cv[cid]), sid))
                ranked = [*nominees, *nearest][:POLICY['maximum_sources_per_candidate']]
                initial = min(len(ranked), len(nominees)+POLICY['nearest_initial'])
                state={'candidate':candidate,'outcome':outcome,'route':route,'ranked':ranked,'cursor':0}
                states.append(state)
                if assess(state,initial) and notify(state):done=True
        save('admission-initial-candidates/'+cid,deepcopy(outcome))
        if done:break

    # A copied nominee's single support must not monopolize the search before
    # other hypotheses even receive their initial independent comparisons.
    while not done:
        expandable=[s for s in states if s['cursor']<len(s['ranked']) and
                    POLICY['expand_after_support']<=len(s['outcome']['supported_sources'])<POLICY['minimum_core_support']]
        if not expandable:break
        expandable.sort(key=lambda s:(-len(s['outcome']['supported_sources']),s['candidate']['id']))
        for state in expandable:
            reached=assess(state,state['cursor']+POLICY['nearest_expansion'])
            save('admission-expansion/'+state['candidate']['id']+'-'+str(state['cursor']),deepcopy(state['outcome']))
            if reached and notify(state):done=True;break
    if done:stop_reason='downstream_compiled_distinct_agents_ready'
    for outcome in outcomes:
        if not outcome['hold_reasons'] and len(outcome['supported_sources'])<POLICY['minimum_core_support']:
            outcome['hold_reasons'].append('fewer_than_three_assessed_core_sources')
        save('admission-candidates/'+outcome['candidate_id'],outcome)
    return {'artifact_kind': VERSION, 'policy': deepcopy(POLICY), 'processing_ids': sorted(registry),
            'candidate_order': order, 'outcomes': outcomes, 'memberships': batches, 'routes': routes,
            'cores': cores, 'errors': errors, 'capacity_holds': holds, 'stop_reason': stop_reason,
            'semantic_approval': False, 'quality_gate_passed': False}
