"""Versioned extraction boundary; structural validation is NOT semantic approval."""
import hashlib
import json

VERSION = 'claims-0.2'
ELIGIBILITY = ['argument_or_experience', 'contextual_reaction', 'question_or_request',
               'non_substantive', 'spam_or_duplicate', 'unclear']
STANCES = ['support', 'oppose', 'conditional', 'mixed', 'neutral', 'unclear']
SCOPES = ['personal', 'general', 'unclear']
MODALITIES = ['asserted', 'possible', 'conditional', 'unclear']


def string(nullable=False):
    return {'type': ['string', 'null'] if nullable else 'string', 'minLength': 1}


PROPERTIES = {
    'issue': string(), 'claim': string(), 'quote': string(),
    'stance_target': string(True), 'stance': {'type':'string', 'enum':STANCES},
    'reason': string(True), 'reason_quote': string(True),
    'condition': string(True), 'condition_quote': string(True),
    'scope': {'type':'string', 'enum':SCOPES},
    'modality': {'type':'string', 'enum':MODALITIES},
}
SCHEMA = {'type':'object','additionalProperties':False,
          'required':['eligibility','claims'],
          'properties':{'eligibility':{'type':'string','enum':ELIGIBILITY},
                        'claims':{'type':'array','maxItems':6,'items':{
                            'type':'object','additionalProperties':False,
                            'required':list(PROPERTIES),'properties':PROPERTIES}}}}


def validate_extraction(value, source):
    """Return errors without silently fixing or dropping model output."""
    errors=[]
    if not isinstance(value,dict) or set(value) != {'eligibility','claims'}:
        return ['envelope_keys']
    if value['eligibility'] not in ELIGIBILITY:
        errors.append('eligibility_enum')
    if not isinstance(value['claims'],list) or len(value['claims'])>6:
        return errors+['claims_array']
    substantive=value['eligibility']=='argument_or_experience'
    if substantive != bool(value['claims']):
        errors.append('eligibility_claims_inconsistent')
    for i,c in enumerate(value['claims']):
        prefix=f'claims[{i}]'
        if not isinstance(c,dict) or set(c)!=set(PROPERTIES):
            errors.append(prefix+'.keys')
            continue
        for key in ['issue','claim','quote']:
            if not isinstance(c[key],str) or not c[key].strip():
                errors.append(prefix+'.'+key)
        for key in ['stance_target','reason','reason_quote','condition','condition_quote']:
            if c[key] is not None and (not isinstance(c[key],str) or not c[key].strip()):
                errors.append(prefix+'.'+key)
        for key,choices in [('stance',STANCES),('scope',SCOPES),('modality',MODALITIES)]:
            if c[key] not in choices:
                errors.append(prefix+'.'+key)
        for key in ['quote','reason_quote','condition_quote']:
            if c[key] is not None and (not isinstance(c[key],str) or c[key] not in source):
                errors.append(prefix+'.'+key+'_not_in_target')
        for key in ['reason','condition']:
            if (c[key] is None)!=(c[key+'_quote'] is None):
                errors.append(prefix+'.'+key+'_evidence_pair')
        if c['stance'] in ['support','oppose','conditional','mixed'] and c['stance_target'] is None:
            errors.append(prefix+'.missing_stance_target')
    return errors


def bind_source(value, source_id, source):
    """Orchestrator, not model, assigns source provenance and deterministic IDs."""
    errors=validate_extraction(value,source)
    if errors:
        raise ValueError('; '.join(errors))
    units=[]
    for index,claim in enumerate(value['claims']):
        digest=hashlib.sha256(json.dumps([VERSION,source_id,source,claim,index],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        units.append({**claim,'claim_id':'claim-'+digest[:24],'source_comment_id':source_id})
    return {'schema_version':VERSION,'source_comment_id':source_id,'eligibility':value['eligibility'],
            'claims':units,'semantic_review_status':'pending'}
