"""Additional whole-original entailment for plain common-claim memberships.

Raw author/evidence checks remain necessary. Parents are preserved in the raw
proof but never concatenated to the NLI premise. This is a conservative model
comparison, not semantic approval, factual verification or reference resolution.
"""
from copy import deepcopy

from commentscope.factory import raw_membership_verification as raw
from commentscope.factory import nli_fact_records
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='whole-original-source-entailment-20261023-v2'
BASE_CONTRACT=raw.ALIGNED


def assessments(batches):
    if not isinstance(batches,list):raise ValueError('Bound original membership batches required')
    rows={}
    for batch in batches:
        if (batch.get('artifact_kind')!=BASE_CONTRACT+'-batch' or
                raw.batch(batch['sources'],batch['candidates'],batch['verified_assessments'],version=BASE_CONTRACT)!=batch):
            raise ValueError('Exact original/evidence verification contract required')
        for assessment,membership in zip(batch['verified_assessments'],batch['memberships'],strict=True):
            original=assessment['raw'];candidate=original['candidate']
            if 'meaning_context' in candidate:
                raise ValueError('Literal contextual cores need their own reference-bound comparator')
            key=(original['source']['id'],candidate['id'])
            if key in rows:raise ValueError('Duplicate source/core vote')
            rows[key]=(assessment,membership)
    return rows


def invocation(batches):
    cases=[]
    for (sid,cid),(assessment,_) in sorted(assessments(batches).items()):
        if not assessment['passed']:continue
        original=assessment['raw']
        cases.append({'id':'SP'+digest([sid,cid]),'text':original['candidate']['text'],
            'evidence':[{'id':sid,'text':original['source']['text']}]})
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':cases}}


def _case(assessment):
    original=assessment['raw'];sid=original['source']['id'];cid=original['candidate']['id']
    return {'id':'SP'+digest([sid,cid]),'text':original['candidate']['text'],
        'evidence':[{'id':sid,'text':original['source']['text']}]}


def _membership(proof):
    if set(proof)!={'raw','nli'}:raise ValueError('Exact original and comparator proof required')
    assessment=raw.validate(proof['raw']);original=assessment['raw']
    if assessment['artifact_kind']!=BASE_CONTRACT or 'meaning_context' in original['candidate']:
        raise ValueError('Plain common claim with exact base contract required')
    row=raw.batch([original['source']],[original['candidate']],[assessment],version=BASE_CONTRACT)['memberships'][0]
    comparator=proof['nli']
    if assessment['passed']:
        case=_case(assessment)
        if (not isinstance(comparator,dict) or set(comparator)!={'case','result','metadata','batch_request_sha256'}
                or comparator['case']!=case):raise ValueError('Whole own original/candidate comparison changed')
        key=comparator['batch_request_sha256']
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Missing classifier batch identity')
        nli_fact_records.validate_result(comparator['result'],case,comparator['metadata'])
        if any(not p['errors'] and (type(p.get('input_tokens')) is not int or
                not 1<=p['input_tokens']<=512) for p in comparator['result']['pairs']):
            raise ValueError('Whole original comparator exceeded its untruncated token boundary')
        if comparator['result']['state']!='supported':
            row['relation']='uncertain';row['guards'].append('whole_original_entailment_unproved')
    elif comparator is not None:raise ValueError('Negative/unapproved raw membership cannot be promoted by NLI')
    return {**row,'artifact_kind':VERSION,'proof_sha256':digest(proof)}


def _export(sources,candidates,proofs):
    from commentscope.factory import minimal_claims as mc
    ss=mc.source_index(sources);cs={c['id']:mc.validate_candidate(c) for c in candidates}
    if len(cs)!=len(candidates):raise ValueError('Duplicate common core')
    seen=set();memberships=[]
    for proof in proofs:
        row=_membership(proof);original=proof['raw']['raw'];key=(row['source_id'],row['candidate_id'])
        if key in seen or ss.get(key[0])!=original['source'] or cs.get(key[1])!=original['candidate']:
            raise ValueError('Unique exact source/core comparator binding required')
        seen.add(key);memberships.append(row)
    return {'artifact_kind':VERSION+'-batch','base_verification_contract':BASE_CONTRACT,
        'sources':deepcopy(sources),'candidates':deepcopy(candidates),'assessments':deepcopy(proofs),
        'memberships':memberships,'semantic_approval':False,'factual_verification':False}


def batch(sources,candidates,raw_batches,response):
    from commentscope.factory import minimal_membership as mm
    mm.collect(sources,candidates,raw_batches)
    lookup=assessments(raw_batches);request=invocation(raw_batches);cases=request['data']['cases']
    if cases:
        if (not isinstance(response,dict) or
                [r['id'] for r in response['results']]!=[c['id'] for c in cases] or
                response['forward_pairs']!=len(cases)):
            raise ValueError('All and only model-positive originals require a bound NLI result')
        compared={case['id']:{'case':case,'result':result,'metadata':response['metadata'],
            'batch_request_sha256':digest(request)} for case,result in zip(cases,response['results'],strict=True)}
    else:
        if response is not None:raise ValueError('No positive originals require no classifier result')
        compared={}
    proofs=[{'raw':assessment,'nli':compared[_case(assessment)['id']] if assessment['passed'] else None}
        for _,(assessment,_) in sorted(lookup.items())]
    return _export(sources,candidates,proofs)


def validate_batch(record):
    if _export(record['sources'],record['candidates'],record['assessments'])!=record:
        raise ValueError('Whole-original entailment provenance changed')
    return record


def from_completed_comparisons(sources,candidates,raw_batches,completed_request,response):
    """Reuse exact selected cases from a larger, preserved actual NLI request.

    The full request/response stays bound by its original batch hash; the caller
    must additionally verify its actual ledger receipt. This never claims that
    a smaller request was executed and never supplies a missing comparison.
    """
    return from_completed_batches(sources,candidates,raw_batches,[(completed_request,response)])


def from_completed_batches(sources,candidates,raw_batches,completed_batches):
    """Project actual disjoint calls without manufacturing a combined request.

    Every supplied batch is validated in full. Each retained comparison keeps
    its original request hash; duplicate case IDs across receipts are rejected.
    The caller verifies actual ledger receipts before supplying these pairs.
    """
    from commentscope.factory import minimal_membership as mm
    mm.collect(sources,candidates,raw_batches)
    if not isinstance(completed_batches,list) or not completed_batches:
        raise ValueError('Actual completed comparison batches required')
    compared={}
    for completed_request,response in completed_batches:
        for key,value in _completed_comparisons(completed_request,response).items():
            if key in compared:raise ValueError('Duplicate comparison across actual batches')
            compared[key]=value
    proofs=[]
    for _,(assessment,_) in sorted(assessments(raw_batches).items()):
        comparator=None
        if assessment['passed']:
            expected=_case(assessment);comparator=compared.get(expected['id'])
            if comparator is None or comparator['case']!=expected:
                raise ValueError('Exact original/core case missing from completed larger comparison')
        proofs.append({'raw':assessment,'nli':comparator})
    return _export(sources,candidates,proofs)


def _completed_comparisons(completed_request,response):
    if (set(completed_request)!={'system','schema','max_tokens','data'} or
            completed_request['system']!=evidence_nli.VERSION or completed_request['schema']!={} or
            completed_request['max_tokens']!=1 or set(completed_request['data'])!={'cases'}):
        raise ValueError('Exact existing whole-original comparator request required')
    cases=completed_request['data']['cases'];ids=[c['id'] for c in cases]
    if (len(ids)!=len(set(ids)) or [r['id'] for r in response['results']]!=ids or
            response['forward_pairs']!=sum(len(c['evidence']) for c in cases)):
        raise ValueError('Full completed comparator inventory changed')
    compared={}
    for case,result in zip(cases,response['results'],strict=True):
        nli_fact_records.validate_result(result,case,response['metadata'])
        compared[case['id']]={'case':case,'result':result,'metadata':response['metadata'],
            'batch_request_sha256':digest(completed_request)}
    return compared


def for_source(record,source_id,candidate_ids):
    validate_batch(record);ids=set(candidate_ids)
    proofs=[p for p in record['assessments'] if p['raw']['raw']['source']['id']==source_id
        and p['raw']['raw']['candidate']['id'] in ids]
    sources=[s for s in record['sources'] if s['id']==source_id]
    present={p['raw']['raw']['candidate']['id'] for p in proofs}
    candidates=[c for c in record['candidates'] if c['id'] in present]
    if len(sources)!=1 or not proofs:raise ValueError('Exact nonempty source/candidate projection required')
    return _export(sources,candidates,proofs)
