"""Interpretation proposals with separate content routing and scope holds.

Content types, setting, attribution and paraphrases are model proposals. Code
checks their structure, never certifies those semantic labels or a membership.
The v1 quote/ownership binder is reused unchanged; old artifacts still replay.
"""
from copy import deepcopy
from collections import Counter
import json

from commentscope.contracts.perspective_draft import obj, array
from commentscope.factory import typed_interpretation as v1
from commentscope.factory import interpretation_scope as scope
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import fields

VERSION = 'typed-interpretation-20261017-v2'
CONTENT = ('topic_view', 'topic_experience', 'topic_inquiry', 'discussion_quality',
           'contextual_attitude', 'source_metadata', 'social_only', 'uncertain')
SETTINGS = ('real', 'fictional', 'unspecified')
SYSTEM = v1.SYSTEM.replace(
    'Creator metadata alone may be non_substantive. Difficulty is uncertain, not noise.',
    'Retain creator/video metadata in statements as source_metadata. Difficulty is uncertain, not noise.') + '''

V2 fields: do not output a case-level relevance or a statement world field.
Instead give each statement a content_type and a setting.
content_type: topic_view (claim/value/request about the discussed subject),
topic_experience (relevant personal experience), topic_inquiry (subject question),
discussion_quality (criticism of the analysis/evidence), contextual_attitude
(reaction to a substantive parent), source_metadata (creator identity/affiliation,
video date or production information alone), social_only, or uncertain.
These are semantic proposals, not keyword rules. A mention of the creator does
not make a subject claim metadata. Preserve separate types in mixed comments.
setting real/fictional/unspecified describes the world, NOT whether a condition
holds or a statement is true. A fictional statement can itself be conditional.
Keep each essential condition and each even-if concession separate. The code
may recover a limited explicit construction; never remove its full original.
Each statement has unresolved: an array of ambiguities affecting that statement.
If a pronoun is unresolved, retain its literal wording in meaning; do not select
one referent and attempt to cancel that choice with a caveat. Case unresolved is
for genuinely source-wide uncertainty/omissions, not an unaddressed S-number note.
Code will withhold uncertain paraphrases from comparison; originals are retained.
Do not return semantic approval, membership, or a truth verdict.'''


def schema(ids):
    value = v1.schema(ids)
    case = value['properties']['cases']['items']
    del case['properties']['relevance']; case['required'].remove('relevance')
    statement = case['properties']['statements']['items']
    del statement['properties']['world']; statement['required'].remove('world')
    statement['properties'].update({'content_type': {'type': 'string', 'enum': list(CONTENT)},
        'setting': {'type': 'string', 'enum': list(SETTINGS)},
        'unresolved': array({'type': 'string', 'minLength': 1}, maximum=12)})
    statement['required'].extend(['content_type', 'setting', 'unresolved'])
    return value


def request(sources):
    base = v1.request(sources)
    return {'system': SYSTEM, 'data': base['data'], 'schema': schema([s['id'] for s in sources]),
        'prompt': SYSTEM + '\nVIDEO_CONTEXT_ONLY is topic metadata, never an author reason.'
                  '\nINPUT:\n' + json.dumps(base['data'], ensure_ascii=False)}


def content_route(content_type):
    if content_type not in CONTENT:
        raise ValueError('Unknown contribution type')
    if content_type in ('source_metadata', 'social_only'):
        return 'context_only'
    return 'hold' if content_type == 'uncertain' else 'topic_proposal'


def bind(source, output):
    fields(output, 'id coverage statements attachments unresolved')
    if not isinstance(output['statements'], list):
        raise ValueError('Invalid statements')
    legacy = {**deepcopy(output), 'relevance': 'uncertain', 'statements': []}
    for statement in output['statements']:
        fields(statement, 'id quote occurrence meaning voice force setting content_type unresolved')
        content_route(statement['content_type'])
        if statement['setting'] not in SETTINGS:
            raise ValueError('Invalid setting')
        notes = statement['unresolved']
        if (not isinstance(notes, list) or len(notes) > 12
                or any(not isinstance(n, str) or not n.strip() for n in notes)):
            raise ValueError('Invalid statement uncertainty')
        raw = {k: deepcopy(statement[k]) for k in ('id', 'quote', 'occurrence', 'meaning', 'voice', 'force')}
        # Compatibility is only for exact spans/ownership. No v1 world is exported.
        raw['world'] = {'real': 'actual', 'fictional': 'fictional', 'unspecified': 'uncertain'}[statement['setting']]
        legacy['statements'].append(raw)
    bound = v1.bind(source, legacy)
    if output['coverage'] == 'complete' and not output['statements']:
        raise ValueError('Complete v2 must preserve even metadata/social contributions')
    statements = []
    for raw, original in zip(output['statements'], bound['statements']):
        links = [a for a in bound['attachments'] if a['statement_id'] == raw['id']]
        syntax = scope.audit(original, links)
        reasons = []
        route = content_route(raw['content_type'])
        if route != 'topic_proposal': reasons.append(route)
        if raw['voice'] != 'author': reasons.append('attribution_not_author')
        if raw['unresolved'] or output['unresolved']: reasons.append('unresolved_interpretation')
        if output['coverage'] != 'complete': reasons.append('coverage_not_complete')
        if syntax['conflicts']: reasons.append('condition_concession_conflict')
        if syntax['syntax']['status'] == 'requires_interpretation': reasons.append('scope_requires_interpretation')
        conditioned = any(a['kind'] == 'condition' for a in links + syntax['syntax']['scopes'])
        statements.append({**deepcopy(raw), 'span': deepcopy(original['span']), 'content_route': route,
            'scope': syntax, 'comparison_holds': reasons,
            'contingency': 'explicit_condition' if conditioned else
                           'hypothetical' if raw['force'] == 'hypothetical' else 'no_condition_identified',
            'semantic_approval': False})
    return {'artifact_kind': VERSION, 'source': deepcopy(source), 'source_sha256': digest(source),
        'output': deepcopy(output), 'output_sha256': digest(output), 'literal_binding': bound,
        'statements': statements, 'semantic_approval': False, 'coverage_verified': False,
        'factual_verification': False, 'quality_gate_passed': False, 'counted_supports': 0}


def validate(record):
    if bind(record['source'], record['output']) != record:
        raise ValueError('Typed scope/ownership provenance changed')
    return record


def comparison_view(record, statement_id):
    validate(record)
    statement = next((s for s in record['statements'] if s['id'] == statement_id), None)
    if statement is None:
        raise ValueError('Unknown local statement')
    old = v1.comparison_view(record['literal_binding'], statement_id)
    operand = None
    if not statement['comparison_holds']:
        operand = {'position_span': old['position_span'], 'full_original_span': statement['span'],
            'interpretation_proposal': statement['meaning'], 'voice': statement['voice'],
            'force': statement['force'], 'setting': statement['setting'],
            'contingency': statement['contingency'], 'model_scope': old['scope'],
            'surface_scope': statement['scope']['syntax']['scopes'], 'semantic_approval': False}
    return {'artifact_kind': VERSION + '-comparison', 'source_sha256': record['source_sha256'],
        'record_sha256': digest(record), 'statement_id': statement_id,
        'original_span': deepcopy(statement['span']), 'operand': deepcopy(operand),
        'holds': deepcopy(statement['comparison_holds']), 'membership_approved': False}


def raw_comparison_source(record):
    """Return immutable evidence even when a normalized proposal is held.

    No proposal, inferred referent, routing label or hold becomes an answer.
    A separate raw membership request must still compare a specific candidate.
    """
    validate(record)
    return deepcopy(record['source'])


def bind_batch(sources, output):
    request(sources); fields(output, 'cases')
    cases = output['cases']
    if not isinstance(cases, list) or any(not isinstance(c, dict) or not isinstance(c.get('id'), str) for c in cases):
        raise ValueError('Invalid case identities')
    counts = Counter(c['id'] for c in cases); expected = {s['id'] for s in sources}
    records = []; errors = [{'id': sid, 'error': 'Unknown source'} for sid in sorted(set(counts) - expected)]
    for source in sources:
        if counts[source['id']] != 1:
            errors.append({'id': source['id'], 'error': 'Missing or duplicate source output'}); continue
        try:
            records.append(bind(source, next(c for c in cases if c['id'] == source['id'])))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({'id': source['id'], 'error': str(exc)})
    return {'artifact_kind': VERSION + '-batch', 'records': records, 'errors': errors,
            'quality_gate_passed': False, 'counted_supports': 0}
