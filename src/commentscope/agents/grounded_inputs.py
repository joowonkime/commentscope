"""Compile fact-screened, source-faithful candidate inputs; no agent publication.

Source judgments, claim typing and premise dependency declarations are upstream
model decisions, NOT established truth. This compiler enforces the declared
boundary and never invents a replacement argument for a rejected premise.
"""
from copy import deepcopy

from commentscope.factory.automatic_contract import digest
from commentscope.factory import fact_checks as facts
from commentscope.factory import nli_fact_records

VERSION = 'fact-screened-agent-inputs-0.2'


def indexed(rows, name):
    result = {}
    for row in rows:
        if not facts.nonempty(row.get('id')) or row['id'] in result:
            raise ValueError('Duplicate/invalid '+name+' ID')
        result[row['id']] = row
    return result


def compile_inputs(bundle):
    required = {'expires_at','sources','claims','relations','documents','checks','candidates','model'}
    if set(bundle) != required:
        raise ValueError('Unexpected grounding bundle fields')
    expiry = facts.live(bundle['expires_at']); facts.model_identity(bundle['model'])
    sources = indexed(bundle['sources'],'source')
    claims = indexed(bundle['claims'],'claim')
    candidates = indexed(bundle['candidates'],'candidate')
    indexed(bundle['documents'],'document')
    for source in sources.values():
        if set(source) != {'id','text','canonical_id'} or not facts.nonempty(source['text']) or source['canonical_id'] not in sources:
            raise ValueError('Invalid source registry')
        if sources[source['canonical_id']]['canonical_id'] != source['canonical_id']:
            raise ValueError('Canonical source chain is not allowed')
    for claim in claims.values():
        facts.claim_identity(claim)
        if any(cid not in claims or claims[cid]['kind'] != 'fact' for cid in claim['requires']):
            raise ValueError('Premise must reference an existing fact claim')
    visited, visiting = set(), set()
    def visit(cid):
        if cid in visiting:
            raise ValueError('Cyclic premise dependency')
        if cid not in visited:
            visiting.add(cid)
            for dep in claims[cid]['requires']: visit(dep)
            visiting.remove(cid); visited.add(cid)
    for cid in claims: visit(cid)

    bindings = {cid:[] for cid in claims}
    pairs = set()
    for relation in bundle['relations']:
        if set(relation) != {'claim_id','claim_sha256','source_id','source_sha256','span','verdict','trace_id','origin'}:
            raise ValueError('Unexpected source relation fields')
        cid, sid = relation['claim_id'], relation['source_id']
        claim, source = claims[cid], sources[sid]
        key = (cid,sid)
        if key in pairs:
            raise ValueError('Duplicate claim/source judgment')
        pairs.add(key)
        if source['canonical_id'] != sid:
            raise ValueError('Duplicate alias cannot vote')
        if relation['claim_sha256'] != facts.claim_identity(claim) or relation['source_sha256'] != digest(source['text']):
            raise ValueError('Source/target judgment binding changed')
        facts.bound_span(source['text'],relation['span'])
        if relation['verdict'] not in {'supported','partial','unsupported','unclear','error','unassessed'} or not facts.nonempty(relation['trace_id']) or relation['origin'] not in {'local_model','synthetic_fixture'}:
            raise ValueError('Invalid source judgment')
        if relation['verdict'] == 'supported':
            bindings[cid].append(deepcopy(relation))

    fact_status = {}; external = {}; check_records = {}
    for check in bundle['checks']:
        if set(check) != {'claim_id','selections','record'}:
            raise ValueError('Unexpected fact check fields')
        cid = check['claim_id']
        if cid in fact_status:
            raise ValueError('Ambiguous multiple fact judgments')
        bound = facts.packet(claims[cid],bundle['documents'],check['selections'],bundle['expires_at'])
        validator = (nli_fact_records.validate_record
                     if check['record'].get('artifact_kind') == nli_fact_records.VERSION
                     else facts.validate_record)
        passed = validator(check['record'],bound,bundle['model'])
        expiry = min(expiry, facts.live(bound['expires_at']))
        fact_status[cid] = 'supported' if passed else check['record']['state']
        check_records[cid] = digest(check['record'])
        external[cid] = bound['evidence']

    eligibility = {}
    def eligible(cid):
        if cid in eligibility: return eligibility[cid]
        claim = claims[cid]
        if not bindings[cid]: reason = 'no_source_support'
        elif claim['kind'] == 'fact' and fact_status.get(cid) != 'supported':
            reason = 'fact_'+fact_status.get(cid,'unassessed')
        elif any(not eligible(dep)[0] for dep in claim['requires']): reason = 'required_premise_unavailable'
        else: reason = None
        eligibility[cid] = (reason is None,reason)
        return eligibility[cid]
    for cid in claims: eligible(cid)

    profiles = []; deferred = []
    for candidate in candidates.values():
        if set(candidate) != {'id','core_claim_id','reason_claim_ids','major_fact_ids'}:
            raise ValueError('Unexpected perspective candidate fields')
        core_id = candidate['core_claim_id']; claims[core_id]
        reasons = candidate['reason_claim_ids']
        if not isinstance(reasons,list) or any(cid not in claims for cid in reasons) or len(set(reasons)) != len(reasons) or core_id in reasons:
            raise ValueError('Invalid perspective reason IDs')
        declared = set()
        def gather(cid):
            if cid not in declared:
                declared.add(cid)
                for dep in claims[cid]['requires']: gather(dep)
        for cid in [core_id,*reasons]: gather(cid)
        factual = {cid for cid in declared if claims[cid]['kind']=='fact'}
        major = candidate['major_fact_ids']
        if not isinstance(major,list) or any(cid not in factual for cid in major) or len(set(major)) != len(major) or (factual and not major):
            raise ValueError('Factual perspectives must declare major fact IDs')
        core_sources = {r['source_id'] for r in bindings[core_id]}
        reason = ('fewer_than_three_core_sources' if len(core_sources) < 3 else eligibility[core_id][1])
        if reason:
            deferred.append({'candidate_id':candidate['id'],'core_claim_id':core_id,'reason':reason,
                             'model_core_support_count':len(core_sources)})
            continue
        omitted = []; selected = set()
        def include(cid):
            if cid not in selected:
                selected.add(cid)
                for dep in claims[cid]['requires']: include(dep)
        include(core_id)
        for cid in reasons:
            # A reason from outsiders cannot be attached to this perspective.
            if not any(r['source_id'] in core_sources for r in bindings[cid]):
                omitted.append({'claim_id':cid,'reason':'no_member_source_for_reason'})
            elif not eligible(cid)[0]:
                omitted.append({'claim_id':cid,'reason':eligible(cid)[1]})
            else:
                include(cid)
        # Dependencies also require a source in this perspective, not a generic fact library.
        if any(not any(r['source_id'] in core_sources for r in bindings[cid]) for cid in selected):
            deferred.append({'candidate_id':candidate['id'],'core_claim_id':core_id,
                             'reason':'required_premise_has_no_member_source','model_core_support_count':len(core_sources)})
            continue
        if major and not any(cid in selected for cid in major):
            deferred.append({'candidate_id':candidate['id'],'core_claim_id':core_id,
                             'reason':'no_verified_major_fact','model_core_support_count':len(core_sources)})
            continue
        entries = []; citations = {}
        for cid in sorted(selected):
            claim = claims[cid]
            relevant = [r for r in bindings[cid] if r['source_id'] in core_sources]
            entries.append({'claim_id':cid,'text':claim['text'],'kind':claim['kind'],
                            'scope':deepcopy(claim['scope']),'requires':claim['requires'][:],
                            'member_source_count':len(relevant),
                            'epistemic_status':'evidence_supported_provisional' if claim['kind']=='fact' else 'attributed_'+claim['kind']+'_not_verified_fact'})
            citations[cid] = {'comment_evidence':[{'source_id':r['source_id'],'span':deepcopy(r['span'])} for r in relevant],
                             'verification_evidence':deepcopy(external.get(cid,[])),
                             'check_sha256':check_records.get(cid)}
        profiles.append({'candidate_id':candidate['id'],'core_claim_id':core_id,
                         'status':'fact_screened_input_not_runtime_approved',
                         'model_core_support_count':len(core_sources),
                         'prompt_entries':entries,'citations':citations,'omitted':omitted})
    return {'artifact_kind':VERSION,'input_sha256':digest(bundle),'expires_at':expiry.isoformat(),
            'profiles':profiles,'deferred':deferred,'claim_decisions':{
                cid:{'eligible':v[0],'reason':v[1],'fact_state':fact_status.get(cid,'not_applicable' if claims[cid]['kind']!='fact' else 'unassessed')}
                for cid,v in eligibility.items()},
            'source_judgment_origins':sorted({r['origin'] for r in bundle['relations']}),
            'quality_gate_passed':False,'agents':[],
            'limitations':['Input policy enforcement, not fact-check accuracy or automatic clustering proof.',
                           'Claim typing/dependencies/source judgments remain fallible upstream decisions.',
                           'Omitted evidence may change perspective representativeness; runtime approval is pending.']}


def prompt_input(compiled, candidate_id, *, bundle):
    """Model input allowlist; rejected claims and full raw comments stay outside."""
    facts.live(compiled['expires_at'])
    if compiled != compile_inputs(bundle):
        raise ValueError('Compiled input changed; rebuild from original bound artifacts')
    profile = next((p for p in compiled['profiles'] if p['candidate_id']==candidate_id),None)
    if profile is None: raise ValueError('Perspective is deferred or missing')
    return {'core_claim_id':profile['core_claim_id'],
            'allowed_entries':deepcopy(profile['prompt_entries']),
            'constraints':['Only these entries may ground an answer; no outside claims.',
                           'Values and predictions are attributed positions, not verified facts.',
                           'Preserve conditions; approved facts do not license a new causal conclusion.',
                           'Do not attribute an individual reason to all members; abstain when evidence is absent.']}
