"""Separate fallible time/modality labels from support. Never an entailment approval."""
import re
from commentscope.factory import claim_frame
from commentscope.factory.automatic import checked_call
from commentscope.factory.automatic_contract import digest

VERSION = 'temporal-guard-0.2'
FIELDS = ('commitment', 'time')


def lexical_prediction(texts):
    """Narrow English modal correction, not a general parser; preserve witnesses for audit.

    'd is ambiguous (had/would). Only a fixed set of bare action verbs licenses this correction.
    Competing modal/hope or explicit past markers disable it rather than guessing clause scope.
    """
    text='\n'.join(texts)
    if re.search(r"\b(should|ought|must|may|might|could|hope|wish|yesterday)\b|\blast (year|month|week)\b",text,re.I):
        return {'overrides':{},'witnesses':[]}
    pattern=(r"\b(?:will|would)\b|\bwon['’]t\b|\b(?:I|you|we|they|he|she|it)['’]ll\b|"
             r"\b(?:I|you|we|they|he|she)['’]d\s+(?:(?:still|also|rather|always|never)\s+)?"
             r"(?:work|take|choose|continue|stop|keep|go|travel|do|be|get)\b")
    witnesses=[{'start':m.start(),'end':m.end(),'text':m.group()} for m in re.finditer(pattern,text,re.I)]
    # Would have + past participle is outside this future correction.
    if re.search(r'\bwould\s+have\s+(?:been|\w+ed)\b',text,re.I): witnesses=[]
    return {'overrides':{'commitment':'prediction','time':'future'} if witnesses else {},'witnesses':witnesses}


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
    lexical=lexical_prediction(texts)
    return {'version':VERSION, 'input_digest': digest(texts), 'parts': parts, 'lexical':lexical,
            'output': {**output,**lexical['overrides']} if not errors else None, 'errors': errors}


def compatible(left, right):
    if left['errors'] or right['errors']: return ['invalid_temporal_label']
    reasons = []
    for field in FIELDS:
        a, b = left['output'][field], right['output'][field]
        if 'unclear' in (a, b): reasons.append(field+'_unclear')
        elif a != b: reasons.append(field+'_mismatch')
    return reasons


def validate(texts, stored):
    if (stored.get('version')!=VERSION or stored.get('input_digest') != digest(texts)
            or set(stored['parts']) != set(FIELDS)):
        raise ValueError('Temporal input/components changed')
    output, errors = {}, []
    for field in FIELDS:
        part = stored['parts'][field]
        if not part['errors']:
            if claim_frame.validate_part(field, part['output'], texts): raise ValueError('Invalid temporal output')
            output.update(part['output'])
        errors.extend(field+':'+e for e in part['errors'])
    lexical=lexical_prediction(texts)
    if (stored.get('lexical')!=lexical or stored['errors'] != errors
            or stored['output'] != ({**output,**lexical['overrides']} if not errors else None)):
        raise ValueError('Temporal assembly changed')
