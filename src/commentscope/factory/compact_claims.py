"""Single-source wire format with the unchanged canonical claim checks.

Provider requests and replies bind separately from their normalized records.
Neither a valid transport nor a source nomination establishes semantic support.
"""
from copy import deepcopy

from commentscope.contracts.perspective_draft import obj, array
from commentscope.factory import minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import fields

VERSION = 'compact-source-claims-20261102-v1'
PREFIX = 'Extract one fixed original through a compact source transport.\n'
FIDELITY = '''
Authorship identifies the speaker inside the original, not the analyst reading it.
asserted means the comment author's own assertion, request, criticism or allegation;
it does not certify truth. reported assigns the proposition to another speaker
within the comment. Reading an author's words secondhand does not make those
words reported. Attribution of one sentence does not spill into neighboring ones.
Preserve quoted content without reversing its negation or inferring endorsement.
Keep each claim's world and voice. A preceding short title or proper-name fragment
can frame following sentences. Carry a fictional or hypothetical setting into
every affected claim, even when the setting was introduced in a separate sentence.
Relevant personal work experiences or aversion to inactivity can be substantive
without a policy endorsement. A summary of competing positions can be a substantive
report without endorsing its quoted views. Do not confuse absent endorsement with
non-substantive content. Keep ambiguity or a stated critique rather than inventing
the opposite position when irony or sincerity is unclear.
Prefer original wording for self-contained assertions. Rewrite only to resolve
clearly established references or preserve their full scope; never strengthen a
personal experience into a general claim or change the scope of all/only/if.
Use a supplied policy name when the source/context clearly identifies it. Do not
expand unexplained acronyms using outside knowledge. Missing comparison amounts
remain unresolved; do not invent quantities or render placeholders as known facts.
Context identifies a reply's object but cannot donate another person's reasons.
Essential conditions remain in the text and in k, including when their segment
also appears in e. A conditional demand cannot become an unconditional one.
'''
WIRE = '''
Exactly one original is supplied. Return s=status and c=claims. Each claim uses
t=text, e=space-separated evidence segment IDs, k=space-separated essential-condition
segment IDs (empty string when none), a=authorship. Use supplied segment IDs exactly
once per address list. The host binds source_id: omit source_id and sources.
At most16 claims,600 characters per text,24 unique IDs per address list. All source,
attribution, completeness, condition and capacity rules above still apply.
'''


def request(source, *, previous=None):
    prior = []
    if previous is not None:
        validate(previous)
        prior = [previous['canonical_record']]
    canonical = mc.extraction_request([source], prior)
    claim = obj({'t': {'type': 'string'}, 'e': {'type': 'string'}, 'k': {'type': 'string'},
                 'a': {'type': 'string', 'enum': list(mc.AUTHORSHIP)}})
    schema = obj({'s': {'type': 'string', 'enum': list(mc.STATUSES)},
                  'c': array(claim, minimum=0, maximum=16)})
    system = mc.SUPPLEMENT_SYSTEM if previous is not None else mc.SYSTEM
    return mc.request(PREFIX+system+FIDELITY+WIRE, canonical['data'], schema, 3072)


def bind(source, result, *, previous=None):
    req = request(source, previous=previous)
    if not isinstance(result, dict) or result.get('errors'):
        raise ValueError('Completed compact source extraction required')
    value = result.get('output'); fields(value, 's c')
    if not isinstance(value['c'], list) or len(value['c']) > 16:
        raise ValueError('Original sixteen-proposition capacity required')
    claims = []
    for row in value['c']:
        fields(row, 't e k a')
        if not isinstance(row['e'], str) or not isinstance(row['k'], str):
            raise ValueError('Exact flat source address strings required')
        claims.append({'text': row['t'], 'authorship': row['a'],
                       'evidence_segment_ids': row['e'].split(' ') if row['e'] else [],
                       'essential_condition_segment_ids': row['k'].split(' ') if row['k'] else []})
    normalized = {'sources': [{'source_id': source['id'], 'status': value['s'], 'claims': claims}]}
    canonical = mc.bind_extraction([source], {'output': normalized},
        [previous['canonical_record']] if previous is not None else [])[0]
    return {'artifact_kind': VERSION, 'source': deepcopy(source), 'source_sha256': digest(source),
            'status': canonical['status'], 'claims': deepcopy(canonical['claims']),
            'additional_passes': canonical['additional_passes'], 'previous': deepcopy(previous),
            'canonical_record': canonical, 'canonical_record_is_normalization_only': True,
            'response': deepcopy(value), 'output_sha256': digest(value),
            'request_sha256': digest(req), 'semantic_approval': False}


def validate(record):
    if not isinstance(record, dict) or record.get('artifact_kind') != VERSION:
        raise ValueError('Bound compact extraction required')
    if bind(record['source'], {'output': record['response']}, previous=record['previous']) != record:
        raise ValueError('Compact source, request, response or normalization binding changed')
    return record


def discover(sources, work):
    mc.source_index(sources)
    batches = work('extract', sources, lambda group: request(group[0]),
                   lambda group, result: [bind(group[0], result)], 1)
    records = [r for batch in batches for r in batch]
    partial = {r['source']['id']: r for r in records if r['status'] == 'partial'}
    extras = work('extract-additional', [s for s in sources if s['id'] in partial],
        lambda group: request(group[0], previous=partial[group[0]['id']]),
        lambda group, result: [bind(group[0], result, previous=partial[group[0]['id']])], 1)
    replaced = {r['source']['id']: r for batch in extras for r in batch}
    return [replaced.get(r['source']['id'], r) for r in records]
