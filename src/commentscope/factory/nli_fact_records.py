"""Evidence-NLI records with honest classifier provenance (not LLM messages)."""
from copy import deepcopy
import math
from commentscope.factory import fact_checks as facts
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli as nli
from commentscope.providers.local_nli import MODEL, REVISION, THRESHOLD, decide

VERSION = 'evidence-nli-fact-record-0.1'


def invocation(packets):
    for bound in packets:
        facts.live(bound['expires_at'])
        if bound['claim_sha256'] != facts.claim_identity(bound['claim']): raise ValueError('Claim changed')
    return {'system':nli.VERSION,'schema':{},'max_tokens':1,
            'data':{'cases':[{'id':b['claim']['id'],'text':b['claim']['text'],
                              'evidence':[{'id':e['id'],'text':e['text']} for e in b['evidence']]} for b in packets]}}


def validate_result(result, case, metadata):
    if metadata.get('model') != MODEL or metadata.get('revision') != REVISION or metadata.get('threshold') != THRESHOLD or metadata.get('local_files_only') is not True:
        raise ValueError('Classifier identity changed')
    if result['id'] != case['id'] or [p['id'] for p in result['pairs']] != [e['id'] for e in case['evidence']]:
        raise ValueError('Classifier evidence inventory changed')
    labels = {int(k):v for k,v in metadata['id2label'].items()}
    if set(labels) != {0,1,2} or set(labels.values()) != {'entailment','neutral','contradiction'}:
        raise ValueError('Classifier label mapping changed')
    for row in result['pairs']:
        if row['errors']:
            if row['relation'] is not None: raise ValueError('Errored pair promoted')
            continue
        raw = row['raw']
        if not isinstance(raw,list) or len(raw) != 3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in raw):
            raise ValueError('Missing classifier logits')
        probs = [math.exp(x-max(raw)) for x in raw]; total=sum(probs)
        if any(abs(row['scores'][labels[i]]-v/total)>1e-5 for i,v in enumerate(probs)):
            raise ValueError('Classifier scores changed')
        if row['relation'] != decide(row['scores'],THRESHOLD): raise ValueError('Classifier verdict changed')
    if any(result[k] != v for k,v in nli.aggregate(result['pairs']).items()):
        raise ValueError('Classifier aggregation changed')


def records(packets, model, response, *, batch_request=None):
    facts.model_identity(model)
    if model['name'] != MODEL or model['revision'] != REVISION: raise ValueError('Wrong classifier model')
    request = invocation(packets)
    if batch_request is not None and request != batch_request: raise ValueError('Batch request changed')
    if [r['id'] for r in response['results']] != [c['id'] for c in request['data']['cases']]:
        raise ValueError('Batch case inventory changed')
    out=[]
    for bound,case,result in zip(packets,request['data']['cases'],response['results'],strict=True):
        validate_result(result,case,response['metadata'])
        out.append({'artifact_kind':VERSION,'packet_sha256':digest(bound),'model':deepcopy(model),
                    'case':deepcopy(case),'batch_request_sha256':digest(request),
                    'metadata':deepcopy(response['metadata']),'result':deepcopy(result),'state':result['state'],
                    'expires_at':bound['expires_at'],'human_approved':False,'quality_gate_passed':False,
                    'judgment_origin':'local_classifier_not_independent_verification'})
    return out


def validate_record(record, bound, model):
    facts.live(bound['expires_at']); facts.model_identity(model)
    if (record.get('artifact_kind') != VERSION or record.get('packet_sha256') != digest(bound)
            or record.get('model') != model or model['name'] != MODEL or model['revision'] != REVISION
            or record.get('expires_at') != bound['expires_at']
            or record.get('case') != invocation([bound])['data']['cases'][0]
            or record.get('human_approved') is not False or record.get('quality_gate_passed') is not False
            or record.get('judgment_origin') != 'local_classifier_not_independent_verification'):
        raise ValueError('NLI fact provenance changed')
    batch_hash = record.get('batch_request_sha256')
    if not isinstance(batch_hash,str) or len(batch_hash)!=64 or any(c not in '0123456789abcdef' for c in batch_hash):
        raise ValueError('Missing batch identity')
    validate_result(record['result'],record['case'],record['metadata'])
    if record['state'] != record['result']['state']: raise ValueError('Record state changed')
    return record['state']=='supported'
