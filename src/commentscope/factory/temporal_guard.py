"""Separate fallible time/modality labels from support. Never an entailment approval."""
from commentscope.factory import claim_frame
from commentscope.factory.automatic import checked_call
from commentscope.factory.automatic_contract import digest

VERSION = 'temporal-guard-0.1'
FIELDS = ('commitment', 'time')


def classify(calls, texts):
    parts, output, errors = {}, {}, []
    for field in FIELDS:
        data = {'TEXT': texts}
        if field == 'time': data['COMMITMENT'] = output.get('commitment', 'unclear')
        result = checked_call(calls, claim_frame.TASK_SYSTEMS[field], data, claim_frame.TASK_SCHEMAS[field],
                              lambda v, f=field: claim_frame.validate_part(f, v, texts))
        parts[field] = result
        errors.extend(field+':'+e for e in result['errors'])
        if not result['errors']: output.update(result['output'])
    return {'input_digest': digest(texts), 'parts': parts, 'output': output if not errors else None, 'errors': errors}


def compatible(left, right):
    if left['errors'] or right['errors']: return ['invalid_temporal_label']
    reasons = []
    for field in FIELDS:
        a, b = left['output'][field], right['output'][field]
        if 'unclear' in (a, b): reasons.append(field+'_unclear')
        elif a != b: reasons.append(field+'_mismatch')
    return reasons


def validate(texts, stored):
    if stored.get('input_digest') != digest(texts) or set(stored['parts']) != set(FIELDS):
        raise ValueError('Temporal input/components changed')
    output, errors = {}, []
    for field in FIELDS:
        part = stored['parts'][field]
        if not part['errors']:
            if claim_frame.validate_part(field, part['output'], texts): raise ValueError('Invalid temporal output')
            output.update(part['output'])
        errors.extend(field+':'+e for e in part['errors'])
    if stored['errors'] != errors or stored['output'] != (output if not errors else None):
        raise ValueError('Temporal assembly changed')
