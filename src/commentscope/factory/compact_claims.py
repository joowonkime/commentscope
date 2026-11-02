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
MASKED = 'compact-source-claims-20261102-v2'
INDEXED = 'compact-source-claims-20261102-v3'
VERSIONS = (VERSION, MASKED, INDEXED)
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
MASKED_WIRE = '''
Return s=status, c=free claims, and l=classification of each LOCKED_CONDITIONAL
only when l is present in the required schema (otherwise omit l).
For free claims use t=text, a=authorship; e and k are objects of supplied original
segment IDs to booleans. Select evidence with e=true and essential conditions with
k=true. Include every required key. Never put prose, numbers or strings in a mask.
LOCKED_CONDITIONALS were copied from this original before this request. Select
each complete literal statement's authorship in l, or omitted if not substantive.
The host preserves its whole text including its condition. Never generate a free
claim using ANY segment listed by a locked conditional, even for just its condition
or conclusion: those cannot become independent assertions. Use c=[] if there are
no other claims. Classifications nominate content; they do not establish truth,
correct attribution, relevance, source support or membership.
On a supplement, select omitted for literal claims already present in PREVIOUS;
their complete original text and authorship remain preserved by the host.
At most16 total selected and free claims,600 characters per text,24 selected IDs
per mask. All original source, completeness and attribution rules still apply.
'''
INDEXED_WIRE = MASKED_WIRE.replace(
    'e and k are objects of supplied original\nsegment IDs to booleans. Select evidence with e=true and essential conditions with\nk=true. Include every required key. Never put prose, numbers or strings in a mask.',
    'e and k are binary strings in ADDRESS_ORDER, one character per segment: '
    '1 selects that segment and 0 excludes it. For example, 101 selects the first '
    'and third segments in a three-segment original. Include every position exactly '
    'once. Never put prose or segment IDs in a mask. An all-zero k means no condition.')


def conditional_selections(source):
    """Recognize bounded syntax only; never infer endorsement or semantic support."""
    from commentscope.factory import explicit_discourse as ed
    graph = ed.parse(source)
    nodes = {n['id']: n for n in graph['nodes']}
    segments = mc.packet(source)['ORIGINAL_SEGMENTS']
    result = []
    for edge in graph['edges']:
        if edge['relation'] != 'necessary_condition': continue
        node = nodes[edge['parent_id']]; span = node['span']
        ids = [s['id'] for s in segments if s['start'] < span['end'] and span['start'] < s['end']]
        if not ids or len(ids) > 24 or len(span['text']) > 600: continue
        result.append({'id': f'C{len(result)+1}', 'text': span['text'],
                       'evidence_segment_ids': ids, 'essential_condition_segment_ids': ids,
                       'source_span': deepcopy(span)})
    return result


def addresses(mask, ids):
    if (not isinstance(mask, dict) or set(mask) != set(ids)
            or any(type(v) is not bool for v in mask.values())):
        raise ValueError('Exact original segment keys and boolean address selections required')
    return [sid for sid in ids if mask[sid]]


def indexed_addresses(mask, ids):
    if not isinstance(mask, str) or len(mask) != len(ids) or set(mask) - {'0', '1'}:
        raise ValueError('One exact binary selection per original segment required')
    return [sid for sid, selected in zip(ids, mask) if selected == '1']


def request(source, *, previous=None, protocol=VERSION):
    if protocol not in VERSIONS: raise ValueError('Unknown compact transport')
    prior = []
    if previous is not None:
        validate(previous)
        if previous['artifact_kind'] != protocol: raise ValueError('Compact supplement protocol changed')
        prior = [previous['canonical_record']]
    canonical = mc.extraction_request([source], prior)
    claim = obj({'t': {'type': 'string'}, 'e': {'type': 'string'}, 'k': {'type': 'string'},
                 'a': {'type': 'string', 'enum': list(mc.AUTHORSHIP)}})
    schema = obj({'s': {'type': 'string', 'enum': list(mc.STATUSES)},
                  'c': array(claim, minimum=0, maximum=16)})
    wire = WIRE
    if protocol in (MASKED, INDEXED):
        ids = [s['id'] for s in mc.packet(source)['ORIGINAL_SEGMENTS']]
        mask = obj({sid: {'type': 'boolean'} for sid in ids})
        if protocol == INDEXED:
            mask = {'type': 'string', 'pattern': f'^[01]{{{len(ids)}}}$'}
            canonical['data']['ADDRESS_ORDER'] = ids
        claim = obj({'t': {'type': 'string'}, 'e': mask, 'k': mask,
                     'a': {'type': 'string', 'enum': list(mc.AUTHORSHIP)}})
        locked = conditional_selections(source)
        previous_ids = {c['id'] for c in previous['claims']} if previous is not None else set()
        canonical['data']['LOCKED_CONDITIONALS'] = locked
        properties = {'s': {'type': 'string', 'enum': list(mc.STATUSES)},
                      'c': array(claim, minimum=0, maximum=16)}
        if locked:
            properties['l'] = obj({row['id']: {'type': 'string',
                'enum': ['omitted'] if mc.claim_id(row['text']) in previous_ids else [*mc.AUTHORSHIP, 'omitted']}
                for row in locked})
        schema = obj(properties)
        wire = INDEXED_WIRE if protocol == INDEXED else MASKED_WIRE
    system = mc.SUPPLEMENT_SYSTEM if previous is not None else mc.SYSTEM
    return mc.request(PREFIX+system+FIDELITY+wire, canonical['data'], schema, 3072)


def bind(source, result, *, previous=None, protocol=VERSION):
    req = request(source, previous=previous, protocol=protocol)
    if not isinstance(result, dict) or result.get('errors'):
        raise ValueError('Completed compact source extraction required')
    value = result.get('output'); fields(value, 's c l' if 'l' in req['schema']['properties'] else 's c')
    if not isinstance(value['c'], list) or len(value['c']) > 16:
        raise ValueError('Original sixteen-proposition capacity required')
    claims = []
    locked = req['data'].get('LOCKED_CONDITIONALS', [])
    locked_ids = {sid for row in locked for sid in row['evidence_segment_ids']}
    if locked:
        fields(value['l'], ' '.join(row['id'] for row in locked))
        for row in locked:
            author = value['l'][row['id']]
            if author not in (*mc.AUTHORSHIP, 'omitted'): raise ValueError('Unknown literal authorship')
            if author not in req['schema']['properties']['l']['properties'][row['id']]['enum']:
                raise ValueError('Supplement cannot repeat a previous literal selection')
            if author != 'omitted':
                claims.append({k: deepcopy(row[k]) for k in
                               ('text', 'evidence_segment_ids', 'essential_condition_segment_ids')})
                claims[-1]['authorship'] = author
    for row in value['c']:
        fields(row, 't e k a')
        if protocol in (MASKED, INDEXED):
            ids = [s['id'] for s in mc.packet(source)['ORIGINAL_SEGMENTS']]
            decode = indexed_addresses if protocol == INDEXED else addresses
            evidence, conditions = decode(row['e'], ids), decode(row['k'], ids)
            if locked_ids.intersection(evidence + conditions):
                raise ValueError('Complete locked conditional must be selected, never split into free claims')
        else:
            if not isinstance(row['e'], str) or not isinstance(row['k'], str):
                raise ValueError('Exact flat source address strings required')
            evidence, conditions = row['e'].split(' ') if row['e'] else [], row['k'].split(' ') if row['k'] else []
        claims.append({'text': row['t'], 'authorship': row['a'],
                       'evidence_segment_ids': evidence,
                       'essential_condition_segment_ids': conditions})
    normalized = {'sources': [{'source_id': source['id'], 'status': value['s'], 'claims': claims}]}
    canonical = mc.bind_extraction([source], {'output': normalized},
        [previous['canonical_record']] if previous is not None else [])[0]
    return {'artifact_kind': protocol, 'source': deepcopy(source), 'source_sha256': digest(source),
            'status': canonical['status'], 'claims': deepcopy(canonical['claims']),
            'additional_passes': canonical['additional_passes'], 'previous': deepcopy(previous),
            'canonical_record': canonical, 'canonical_record_is_normalization_only': True,
            'response': deepcopy(value), 'output_sha256': digest(value),
            'request_sha256': digest(req), 'semantic_approval': False}


def validate(record):
    if not isinstance(record, dict) or record.get('artifact_kind') not in VERSIONS:
        raise ValueError('Bound compact extraction required')
    if bind(record['source'], {'output': record['response']}, previous=record['previous'],
            protocol=record['artifact_kind']) != record:
        raise ValueError('Compact source, request, response or normalization binding changed')
    return record


def discover(sources, work, *, protocol=VERSION):
    mc.source_index(sources)
    batches = work('extract', sources, lambda group: request(group[0], protocol=protocol),
                   lambda group, result: [bind(group[0], result, protocol=protocol)], 1)
    records = [r for batch in batches for r in batch]
    partial = {r['source']['id']: r for r in records if r['status'] == 'partial'}
    extras = work('extract-additional', [s for s in sources if s['id'] in partial],
        lambda group: request(group[0], previous=partial[group[0]['id']], protocol=protocol),
        lambda group, result: [bind(group[0], result, previous=partial[group[0]['id']], protocol=protocol)], 1)
    replaced = {r['source']['id']: r for batch in extras for r in batch}
    return [replaced.get(r['source']['id'], r) for r in records]
