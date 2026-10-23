"""Directional fidelity of semantic argument units to their own literal evidence.

This never verifies external truth or argument roles. Whole-original membership,
an independent full-source coverage/role audit and factual checks stay required.
Parent/video context cannot enter these comparator premises.
"""
from copy import deepcopy
from commentscope.factory import source_arguments as sa,nli_fact_records
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='own-original-argument-fidelity-20261023-v1'


def invocation(record):
    sa.validate_extraction(record);source=record['source'];cases=[]
    for unit in record['units']:
        evidence=[]
        for index,span in enumerate(unit['evidence']):
            if source['text'][span['start']:span['end']]!=span['text']:
                raise ValueError('Literal evidence must belong to the same original')
            evidence.append({'id':unit['id']+':'+str(index),'text':span['text']})
        cases.append({'id':'AF'+digest([VERSION,unit]),'text':unit['text'],'evidence':evidence})
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':cases}}


def bind(record,response):
    request=invocation(record);cases=request['data']['cases'];reasons=[]
    if not cases:
        if response is not None:raise ValueError('No units require no argument comparator invocation')
    else:
        if (not isinstance(response,dict) or [r['id'] for r in response['results']]!=[c['id'] for c in cases]
                or response['forward_pairs']!=sum(len(c['evidence']) for c in cases)):
            raise ValueError('Every exact source argument requires its completed comparator result')
        for case,result in zip(cases,response['results'],strict=True):
            nli_fact_records.validate_result(result,case,response['metadata'])
            if any(not p['errors'] and (type(p.get('input_tokens')) is not int or not 1<=p['input_tokens']<=512)
                    for p in result['pairs']):
                raise ValueError('Untruncated argument comparator token boundary exceeded')
            if result['state']!='supported':reasons.append('own_literal_argument_entailment_unproved:'+case['id'])
    return {'artifact_kind':VERSION,'source_argument_sha256':digest(record),'source_sha256':digest(record['source']),
        'request_sha256':digest(request),'response':deepcopy(response),'passed':not reasons,
        'hold_reasons':reasons,'semantic_approval':False,'factual_verification':False}


def validate(record,proof):
    if bind(record,proof['response'])!=proof:raise ValueError('Own original argument fidelity changed')
    return proof
