"""A source-bound extraction proposal, distinct from a candidate or a support.

This projection preserves the model's choices; it cannot establish that those
choices are complete or faithful. Parent/context text never becomes own evidence.
"""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import fields

VERSION = 'source-interpretation-20261104-v1'
OWN_PROPOSAL_SYSTEM = '''
OWN_INTERPRETATION_PROPOSAL contains untrusted extraction choices from the same
ORIGINAL. Check them against its full text. They cannot define a missing candidate
condition, approve support, establish completeness or certify truth.'''


def bind(source, proposal):
    mc.validate_source(source)
    fields(proposal, 'id text source_id source_sha256 record_id authorship evidence essential_conditions')
    ref = proposal['record_id']
    if (proposal['source_id'] != source['id'] or proposal['source_sha256'] != digest(source)
            or proposal['text'] != mc.normalize(proposal['text']) or len(proposal['text']) > 600
            or proposal['id'] != mc.claim_id(proposal['text'])
            or proposal['authorship'] not in mc.AUTHORSHIP
            or not isinstance(ref, str) or len(ref) != 66 or not ref.startswith('ME')
            or any(c not in '0123456789abcdef' for c in ref[2:])):
        raise ValueError('Exact normalized own-source proposal and extraction reference required')
    for key, minimum in [('evidence', 1), ('essential_conditions', 0)]:
        spans = proposal[key]
        if (not isinstance(spans, list) or any(not isinstance(s, dict) or 'id' not in s for s in spans)
                or mc.spans(source, [s['id'] for s in spans], minimum=minimum) != spans):
            raise ValueError('Interpretation selections must retain exact own-source spans')
    return {'artifact_kind': VERSION, 'id': 'SI'+digest([VERSION, source, proposal]),
            'source': deepcopy(source), 'proposal': deepcopy(proposal),
            'semantic_approval': False, 'factual_verification': False}


def validate(record):
    if (not isinstance(record, dict) or record.get('artifact_kind') != VERSION
            or bind(record['source'], record['proposal']) != record):
        raise ValueError('Source interpretation, attribution or context changed')
    return record


def packet(record, *, include_context=True):
    validate(record)
    proposal = record['proposal']
    result = {'proposed_text': proposal['text'], 'authorship_proposal': proposal['authorship'],
              'OWN_EVIDENCE_PROPOSALS': deepcopy(proposal['evidence']),
              'ESSENTIAL_CONDITION_PROPOSALS': deepcopy(proposal['essential_conditions']),
              'context_is_not_candidate_definition_or_support': True,
              'semantic_approval': False, 'factual_verification': False}
    if include_context:
        result['ORIGINAL_CONTEXT_ONLY'] = mc.packet(record['source'])
    return result


def own_packet(source, candidate):
    """Never supply another nominator's interpretation on the evidence side."""
    context = candidate.get('source_interpretation')
    if context is None or context['source'] != source:
        return {}
    return {'OWN_INTERPRETATION_PROPOSAL': packet(context, include_context=False)}
