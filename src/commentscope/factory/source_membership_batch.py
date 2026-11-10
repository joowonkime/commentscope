"""One author's independent candidate decisions in one physical request.

Rows retain the whole batch witness. They are never scalar API receipts or
semantic approval; positive rows still need independent own-evidence review.
"""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc, raw_membership as raw
from commentscope.factory.automatic_contract import digest, obj, array
from commentscope.factory.position_frames import fields

VERSION = 'source-membership-batch-20261110-v1'
PROJECTION = VERSION + '-row'
MAX_TARGETS = 6
INSTRUCTION = '''\nJudge every CANDIDATE_TARGETS row independently against this one ORIGINAL.
Only this author's original segments may support that row. Other candidate
targets are NOT evidence, context, alternatives to choose from, or endorsements.
Apply the original single-candidate instructions to each row's CANDIDATE and
CANDIDATE_WORLD_OBSERVATION. All rows may be unrelated or uncertain. Do not
force agreement, a winning candidate, a minimum count or a binary decision.
Return every supplied row ID exactly once, with its independent observations.'''


def logical_requests(source, candidates, source_context, source_world, candidate_worlds):
    if not 1 <= len(candidates) <= MAX_TARGETS:
        raise ValueError('One to six candidate targets required per author')
    if len({c['id'] for c in candidates}) != len(candidates):
        raise ValueError('Unique candidate targets required')
    if set(candidate_worlds) != {c['id'] for c in candidates}:
        raise ValueError('Exact candidate world registry required')
    return [raw.request(source, c, version=raw.WORLD_CONTEXT,
                        source_context=source_context, source_world=source_world,
                        candidate_world=candidate_worlds[c['id']]) for c in candidates]


def request(source, candidates, *, source_context, source_world, candidate_worlds):
    logical = logical_requests(source, candidates, source_context, source_world, candidate_worlds)
    return from_logical_requests(logical)


def from_logical_requests(logical):
    """Build transport only; also used for offline archived-request sizing.

    This function neither binds proofs nor reuses old semantic decisions.
    """
    if not 1 <= len(logical) <= MAX_TARGETS:
        raise ValueError('One to six logical requests required')
    shared = {k: deepcopy(v) for k, v in logical[0]['data'].items()
              if k not in ('CANDIDATE', 'CANDIDATE_WORLD_OBSERVATION')}
    # The shared path has no candidate-owned interpretation proposals. Do not
    # silently share any future candidate-dependent fields across rows.
    if set(shared) != {'ORIGINAL', 'SOURCE_CONTEXT_OBSERVATION', 'SOURCE_WORLD_OBSERVATION'}:
        raise ValueError('Only shared independent source observations can be batched')
    for req in logical:
        if (set(req['data']) != set(shared)|{'CANDIDATE','CANDIDATE_WORLD_OBSERVATION'}
                or {k: v for k, v in req['data'].items() if k in shared} != shared
                or req['schema'] != logical[0]['schema'] or req['system'] != logical[0]['system']):
            raise ValueError('Candidate decisions do not share an exact source contract')
    ids = ['C'+str(i+1) for i in range(len(logical))]
    shared['CANDIDATE_TARGETS'] = [
        {'id': key, 'CANDIDATE': req['data']['CANDIDATE'],
         'CANDIDATE_WORLD_OBSERVATION': req['data']['CANDIDATE_WORLD_OBSERVATION']}
        for key, req in zip(ids, logical)]
    schema = obj({'decisions': array(obj({'id': {'type': 'string', 'enum': ids},
                                        **logical[0]['schema']['properties']}),
                                     minimum=len(ids), maximum=len(ids))})
    # mc.request appends its metadata boundary and output schema once.
    system = logical[0]['system'].split('\nVIDEO_CONTEXT_ONLY, when present,', 1)[0]
    return mc.request(system+INSTRUCTION, shared, schema, 384*len(ids))


def bind(source, candidates, result, *, source_context, source_world, candidate_worlds,
         deployment=None):
    req = request(source, candidates, source_context=source_context,
                  source_world=source_world, candidate_worlds=candidate_worlds)
    if result.get('errors'):
        raise ValueError('Failed source membership packet')
    if 'transport' in result:
        if deployment is None:
            raise ValueError('Actual batch transport requires its frozen deployment')
        from commentscope.providers.remote_verification import parsed_receipt
        parsed_receipt(result, req, deployment)
    elif deployment is not None:
        raise ValueError('Actual batch deployment requires original transport receipt')
    value = result.get('output'); fields(value, 'decisions')
    rows = value['decisions']
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError('Every batch target requires one decision')
    expected = {'C'+str(i+1): c for i, c in enumerate(candidates)}
    seen = set(); outputs = {}
    for row in rows:
        fields(row, ' '.join(req['schema']['properties']['decisions']['items']['properties']))
        key = row['id']
        if key not in expected or key in seen:
            raise ValueError('Duplicate or foreign batch target')
        seen.add(key); outputs[key] = {k: v for k, v in row.items() if k != 'id'}
    witness = {'source': deepcopy(source), 'candidates': deepcopy(candidates),
               'source_context': deepcopy(source_context), 'source_world': deepcopy(source_world),
               'candidate_worlds': deepcopy(candidate_worlds), 'result': deepcopy(result),
               'deployment': deepcopy(deployment), 'request_sha256': digest(req)}
    projections = []
    for key, c in expected.items():
        proof = raw.bind(source, c, {'output': outputs[key]}, version=raw.WORLD_CONTEXT,
                         source_context=source_context, source_world=source_world,
                         candidate_world=candidate_worlds[c['id']])
        proof.update(artifact_kind=PROJECTION, logical_request_sha256=proof['request_sha256'],
                     request_sha256=digest(req), batch_row_id=key, batch_witness=witness)
        projections.append(proof)
    return projections


def validate(record):
    witness = record['batch_witness']
    rows = bind(witness['source'], witness['candidates'], witness['result'],
                source_context=witness['source_context'], source_world=witness['source_world'],
                candidate_worlds=witness['candidate_worlds'], deployment=witness['deployment'])
    if (record.get('artifact_kind') != PROJECTION
            or witness['request_sha256'] != rows[0]['request_sha256']
            or record not in rows):
        raise ValueError('Batch row or full provider/input provenance changed')
    return record
