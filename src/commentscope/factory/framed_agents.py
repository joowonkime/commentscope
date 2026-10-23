"""Connect a shared-stance map to source-owned arguments and grounded inputs.

Every counted member is checked separately; there is no two-grounds-for-the-whole
cluster truncation or fixed Agent cap. Failure defers the Agent, not its map.
No generated frame reason becomes an allowed Agent entry. All selected grounds
are exact originals, independently typed and audited in their author's context.
"""
from copy import deepcopy
import json

from commentscope.factory import stance_membership as stance, position_frames as frames
from commentscope.factory import direct_arguments as direct, argument_graph as graph
from commentscope.factory import candidate_completion as completion, grounded_factory, fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.agents.grounded_inputs import compile_inputs

VERSION = 'framed-source-owned-agent-inputs-0.1'


def core(candidate):
    c = stance.claim(candidate)
    return {'id': 'C', 'text': c['text'], 'scope': c['scope'], 'kind': 'value', 'requires': []}


def contextual(request, source):
    """Parent is context, never an inventory node or counted member."""
    out = deepcopy(request)
    out['data']['PARENT_CONTEXT_ONLY'] = deepcopy(source['parent'])
    out['system'] += '\nPARENT_CONTEXT_ONLY resolves explicit references; never attribute its grounds to this author.'
    if len(json.dumps(out).encode()) > 27000: raise ValueError('Request byte budget exceeded')
    return out


def analyse_source(source, candidate, runner):
    """Call the existing bounded selection/type/audit modules; never repair."""
    frames.validate_source(source); target = core(candidate); sources = {source['id']: source['text']}
    stages = []; result = {'artifact_kind': VERSION + '-source', 'source_id': source['id'],
        'source_sha256': digest(source), 'candidate_id': candidate['id'], 'candidate_sha256': digest(candidate),
        'stages': stages, 'state': 'deferred', 'reason': None}

    def call(stage, req):
        req = contextual(req, source)
        value = runner.call('argument-' + stage, req)
        stages.append({'stage': stage, 'request_sha256': digest(req), 'result': deepcopy(value)})
        return value

    try:
        kind = graph.kind(call('core-type', graph.type_request(target['text'], sources)))
        if kind not in ('fact', 'value', 'prediction'):
            result['reason'] = 'unresolved_core_type'; return result
        target['kind'] = kind
        inv = direct.inventory(target, sources)
        selected = direct.selection(call('select', direct.select_request(target, sources)), inv)
        if selected['status'] != 'selected':
            result['reason'] = selected['reason']; return result
        kinds = {}
        for nid in selected['node_ids']:
            kinds[nid] = graph.kind(call('ground-type-' + nid, graph.type_request(inv['nodes'][nid]['text'], sources)))
        if any(k not in ('fact', 'value', 'prediction') for k in kinds.values()):
            result['reason'] = 'unresolved_ground_type'; return result
        proposal = {'id': candidate['id'], 'claims': {'C': target}, 'sources': sources}
        typed = direct.assemble(proposal, sources, kind, selected, kinds)
        audit = call('audit', direct.audit_request(typed, sources))
        if not completion.audit_passed(typed, audit):
            result['reason'] = 'argument_audit_failed'; return result
        result.update(state='audited', typed=typed)
    except (ValueError, KeyError, TypeError):
        result['reason'] = 'argument_contract_failed'
    return result


def validate_source_analysis(source, candidate, record):
    """Replay only declared results through the exact request-building code."""
    class Replay:
        def __init__(self): self.offset = 0
        def call(self, stage, req):
            if self.offset >= len(record['stages']): raise ValueError('Missing argument stage')
            row = record['stages'][self.offset]; self.offset += 1
            if row['stage'] != stage.removeprefix('argument-') or row['request_sha256'] != digest(req):
                raise ValueError('Argument stage request changed')
            return deepcopy(row['result'])
    replay = Replay(); expected = analyse_source(source, candidate, replay)
    if expected != record or replay.offset != len(record['stages']):
        raise ValueError('Source argument record changed')


def bundle(snapshot, records, candidates, memberships, analyses, *, model, documents=(), checks=()):
    """Preserve complete map; emit grounded bundle plus explicit Agent deferrals."""
    mapped = stance.assemble_map(snapshot, records, candidates, memberships)
    fact_checks.model_identity(model)
    indexed = {c['id']: c for c in candidates}; available = {}; seen = set()
    members = {p['id']: p['supported_canonical_ids'] for p in mapped['opinion_map']['perspectives']}
    for a in analyses:
        key = (a['candidate_id'], a['source_id'])
        if key in seen or key[0] not in indexed or key[1] not in members[key[0]]:
            raise ValueError('Argument from duplicate, outsider or non-supporting source')
        seen.add(key)
        validate_source_analysis(frames.source_packet(snapshot, key[1]), indexed[key[0]], a)
        available[key] = a
    sources = {}; claims = []; relations = []; prepared = []; deferred = []
    membership_lookup = {(m['candidate_id'], m['source_id']): m for m in memberships}
    for candidate in candidates:
        cid = candidate['id']; sids = members[cid]
        if len(sids) < 3:
            deferred.append({'candidate_id': cid, 'reason': 'fewer_than_three_core_sources', 'source_ids': sids}); continue
        missing = [sid for sid in sids if (cid, sid) not in available]
        failed = [sid for sid in sids if (cid, sid) in available and available[cid, sid]['state'] != 'audited']
        if missing or failed:
            deferred.append({'candidate_id': cid, 'reason': 'member_arguments_incomplete',
                             'unassessed_source_ids': missing, 'failed_source_ids': failed}); continue
        types = {available[cid, sid]['typed']['claims']['C']['kind'] for sid in sids}
        if len(types) != 1:
            deferred.append({'candidate_id': cid, 'reason': 'conflicting_core_types', 'source_ids': sids}); continue
        target = {**core(candidate), 'id': cid + ':C', 'kind': next(iter(types))}
        grounds = []; required = []; ground_relations = []
        for sid in sids:
            source = frames.source_packet(snapshot, sid)
            sources[sid] = {'id': sid, 'text': source['text'], 'canonical_id': sid}
            a = available[cid, sid]; typed = a['typed']; inv = direct.bound_inventory(typed, {sid: source['text']})
            for i, nid in enumerate(typed['selected_nodes']['node_ids'], 1):
                original = typed['claims'][f'R{i}']; node = inv['nodes'][nid]
                gid = cid + ':G' + digest([sid, node['start'], node['end']])[:24]
                ground = {**deepcopy(original), 'id': gid}
                grounds.append(ground)
                if f'R{i}' in typed['claims']['C']['requires']: required.append(gid)
                relation = grounded_factory.relation(ground, sid, source['text'], 'supported', digest(a))
                relation['span'] = {k: node[k] for k in ('start', 'end', 'text')}
                ground_relations.append(relation)
        target['requires'] = sorted(required)
        claims.extend([target, *grounds]); relations.extend(ground_relations)
        for sid in sids:
            relations.append(grounded_factory.relation(target, sid, sources[sid]['text'], 'supported',
                                                      digest(membership_lookup[cid, sid])))
        prepared.append({'id': cid, 'core_claim_id': target['id'],
                         'reason_claim_ids': [g['id'] for g in grounds],
                         'major_fact_ids': [g['id'] for g in [target, *grounds] if g['kind'] == 'fact']})
    grounding = {'expires_at': snapshot.usage.expires_at, 'sources': list(sources.values()), 'claims': claims,
                 'relations': relations, 'candidates': prepared, 'documents': deepcopy(list(documents)),
                 'checks': deepcopy(list(checks)), 'model': deepcopy(model)}
    # Invalid/absent fact checks cannot be bypassed by calling this adapter.
    compiled = compile_inputs(grounding)
    return {'artifact_kind': VERSION, 'map': mapped, 'bundle': grounding, 'compiled': compiled,
            'argument_deferrals': deferred, 'analyses_sha256': digest(analyses),
            'quality_gate_passed': False, 'runtime_verified': False}


def prepare_arguments(snapshot, records, candidates, memberships, runner):
    """No human selection, fixed Agent count or nominal support-count override."""
    mapped = stance.assemble_map(snapshot, records, candidates, memberships)
    lookup = {c['id']: c for c in candidates}; analyses = []
    for perspective in mapped['opinion_map']['perspectives']:
        if not perspective['minimum_support_met']: continue
        for sid in perspective['supported_canonical_ids']:
            analyses.append(analyse_source(frames.source_packet(snapshot, sid), lookup[perspective['id']], runner))
    return analyses
