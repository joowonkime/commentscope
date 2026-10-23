"""Whole-corpus scheduling of discovery, original admission and Agent preparation.

Evaluation references are intentionally absent from this API. Retrieval ranks
only schedule independent judgments; all unexamined pairs remain unassessed.
Callbacks own durable execution/checkpoints, model budgets and transport.
"""
from copy import deepcopy
import json
import math

from commentscope.factory import position_frames as frames, framed_clusters as clusters
from commentscope.factory import stance_membership as stance, framed_agents as agents
from commentscope.factory import grounded_factory, nli_fact_records
from commentscope.factory.automatic_contract import digest
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.ingestion import normalize_snapshot

VERSION = 'whole-framed-corpus-factory-0.1'
RETRIEVAL = {'initial': 2, 'fallback': 2}


def sources(snapshot, *, include_video_context=False):
    if len(snapshot.comments) > 1000: raise ValueError('MVP snapshot cap exceeded')
    if len({c.comment_id for c in snapshot.comments}) != len(snapshot.comments):
        raise ValueError('Duplicate raw source identity')
    canonical = {c.comment_id for c in normalize_snapshot(snapshot) if c.text_analysis and c.duplicate_of is None}
    return {c.comment_id: frames.source_packet(snapshot, c.comment_id, include_video_context=include_video_context)
            for c in snapshot.comments if c.comment_id in canonical}


def normalized(vectors, ids):
    if set(vectors) != set(ids): raise ValueError('Complete embedding inventory required')
    output = {}; dimension = None
    for sid in ids:
        vector = vectors[sid]
        if (not isinstance(vector, list) or not vector
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
            raise ValueError('Invalid embedding vector')
        if dimension is not None and dimension != len(vector): raise ValueError('Embedding dimensions differ')
        dimension = len(vector); norm = math.sqrt(sum(x*x for x in vector))
        if not math.isfinite(norm) or norm == 0: raise ValueError('Invalid embedding norm')
        output[sid] = [x/norm for x in vector]
    return output


def similarity(left, right):
    if len(left) != len(right): raise ValueError('Search vector spaces differ')
    return sum(x*y for x, y in zip(left, right, strict=True))


def discovery_batches(records, vectors):
    clusters.index(records)
    lookup = {r['source']['id']: r for r in records if r['positions']}
    vectors = normalized(vectors, lookup); remaining = set(lookup); batches = []; deferred = []
    while remaining:
        seed = min(remaining)
        ranked = sorted(remaining, key=lambda sid: (-similarity(vectors[seed], vectors[sid]), sid))
        # The seed must be processed even when a different ID ties its score.
        ranked.remove(seed); ranked.insert(0, seed)
        batch = []
        for sid in ranked:
            proposed = [lookup[i] for i in [*batch, sid]]
            try: clusters.proposal_request(proposed)
            except ValueError:
                if sid == seed:
                    deferred.append({'source_id': sid, 'reason': 'discovery_request_capacity'})
                    remaining.remove(sid)
                continue
            batch.append(sid)
            if sum(len(lookup[i]['positions']) for i in batch) == 24: break
        if batch:
            batches.append(batch); remaining.difference_update(batch)
    return {'batches': batches, 'deferred_sources': deferred}


def merge_exact(candidates):
    """No semantic union or votes from similarity; only identical contracts."""
    merged = {}
    for candidate in candidates:
        clusters.validate_candidate(candidate)
        cid = candidate['id']
        if cid not in merged: merged[cid] = deepcopy(candidate); continue
        target = merged[cid]
        if target['contract'] != candidate['contract']: raise ValueError('Candidate identity collision')
        for sid, h in candidate['frame_sha256'].items():
            if sid in target['frame_sha256'] and target['frame_sha256'][sid] != h:
                raise ValueError('Conflicting nomination frames')
            target['frame_sha256'][sid] = h
        target['nominees'] = sorted(set(target['nominees']) | set(candidate['nominees']))
    return [merged[cid] for cid in sorted(merged)]


def membership_schedule(source_ids, records, candidates, source_vectors, candidate_vectors, *, limits=RETRIEVAL):
    if (set(limits) != {'initial', 'fallback'}
            or any(type(n) is not int or not 1 <= n <= 16 for n in limits.values())):
        raise ValueError('Finite positive retrieval widths required')
    if len(set(source_ids)) != len(source_ids): raise ValueError('Unique canonical sources required')
    units = clusters.index(records); candidates = merge_exact(candidates)
    sv = normalized(source_vectors, source_ids); cv = normalized(candidate_vectors, [c['id'] for c in candidates])
    nominated = {sid: set() for sid in source_ids}
    for candidate in candidates:
        for uid in candidate['nominees']:
            if uid not in units: raise ValueError('Unknown nomination')
            record, _ = units[uid]; sid = record['source']['id']
            if candidate['frame_sha256'].get(sid) != digest(record): raise ValueError('Nomination frame changed')
            nominated[sid].add(candidate['id'])
    initial = []; fallback = []; rankings = []
    for sid in source_ids:
        ranked = sorted(cv, key=lambda cid: (-similarity(sv[sid], cv[cid]), cid))
        first = set(ranked[:limits['initial']]) | nominated[sid]
        later = [cid for cid in ranked if cid not in first][:limits['fallback']]
        initial.extend({'source_id': sid, 'candidate_id': cid} for cid in ranked if cid in first)
        fallback.extend({'source_id': sid, 'candidate_id': cid} for cid in later)
        rankings.append({'source_id': sid, 'initial_candidate_ids': [cid for cid in ranked if cid in first],
                         'fallback_candidate_ids': later, 'nominated_candidate_ids': sorted(nominated[sid])})
    return {'initial': initial, 'fallback_if_unlinked': fallback, 'rankings': rankings,
            'canonical_sources': len(source_ids), 'candidate_count': len(candidates),
            'membership_approval': False}


def process(snapshot, runner, embed, fact_check, *, model, documents=(), selections=(), save=None, limits=RETRIEVAL):
    """Run a complete fixed snapshot; callbacks must enforce frozen plan/resource rules.

    ``embed(stage, {id:text})`` returns every ID's vector, never gold labels.
    ``fact_check(request)`` returns the existing NLI provider's raw batch result.
    No overall time limit, fixed Agent count, manual candidate or cache from a
    different run is introduced here. Runtime smoke tests remain a caller step.
    """
    save = save or (lambda name, value: None)
    originals = sources(snapshot); records = []; source_states = []; errors = []
    for sid, packet in originals.items():
        row = {'source_id': sid, 'source_sha256': digest(packet)}
        try:
            result = runner.call('frame-' + digest(sid)[:20], frames.invocation(packet))
            record = frames.bind(packet, result); records.append(record)
            row.update(state=record['extraction']['status'], positions=len(record['positions']))
            save('frames/' + digest(sid), record)
        except (ValueError, KeyError, TypeError):
            row.update(state='frame_contract_error', positions=0); errors.append({**row, 'stage': 'frame'})
        source_states.append(row)
    save('source-states', source_states); save('frames', records)
    nonempty = {r['source']['id']: r for r in records if r['positions']}
    # IDs/ownership fields should not influence semantic similarity.
    frame_texts = {sid: '\n'.join(json.dumps({**{k: p[k] for k in ('target', 'statement', 'entity', 'time')},
                                           'restrictions': [{'text': q['text'], 'role': q['role']} for q in p['restrictions']]},
                                          ensure_ascii=False, sort_keys=True) for p in frames.stance_view(record))
                   for sid, record in nonempty.items()}
    schedule = discovery_batches(records, embed('discovery', frame_texts) if frame_texts else {})
    save('discovery-schedule', schedule); proposals = []; batch_states = []
    for i, batch in enumerate(schedule['batches']):
        selected = [nonempty[sid] for sid in batch]
        try:
            result = runner.call(f'proposal-{i:04}', clusters.proposal_request(selected))
            proposed = clusters.proposals(selected, result); proposals.extend(proposed)
            batch_states.append({'batch': i, 'state': 'processed', 'candidate_ids': [c['id'] for c in proposed]})
            save(f'proposals/{i:04}', proposed)
        except (ValueError, KeyError, TypeError):
            batch_states.append({'batch': i, 'state': 'proposal_contract_error', 'source_ids': batch})
            errors.append({'stage': 'proposal', 'batch': i})
    candidates = merge_exact(proposals)
    # Validate source/nominee binding before scheduling anything against them.
    clusters.assemble_map(snapshot, records, candidates, [])
    units = clusters.index(records)
    discovery = {'schedule': schedule, 'batch_states': batch_states,
                 'unproposed_position_ids': sorted(set(units)-{uid for c in candidates for uid in c['nominees']})}
    save('discovery', discovery); save('candidates', candidates)
    sv = embed('sources', {sid: p['text'] for sid, p in originals.items()}) if originals and candidates else {}
    cv = embed('candidates', {c['id']: json.dumps(c['contract'], ensure_ascii=False, sort_keys=True) for c in candidates}) if candidates else {}
    if candidates:
        search = membership_schedule(list(originals), records, candidates, sv, cv, limits=limits)
    else:
        search = {'initial': [], 'fallback_if_unlinked': [], 'rankings': [],
                  'canonical_sources': len(originals), 'candidate_count': 0, 'membership_approval': False}
    save('membership-schedule', search)
    lookup = {c['id']: c for c in candidates}; memberships = []
    for phase in ('initial', 'fallback_if_unlinked'):
        linked = {m['source_id'] for m in memberships if m['relation'] == 'supported'}
        for pair in search[phase]:
            sid, cid = pair['source_id'], pair['candidate_id']
            if phase == 'fallback_if_unlinked' and sid in linked: continue
            try:
                result = runner.call('membership-' + digest(pair)[:24], stance.invocation(originals[sid], lookup[cid]))
                bound = stance.bind(originals[sid], lookup[cid], result); memberships.append(bound)
                save('memberships/' + digest(pair), bound)
            except (ValueError, KeyError, TypeError):
                errors.append({'stage': 'membership', **pair})
    save('memberships', memberships)
    mapped = stance.assemble_map(snapshot, records, candidates, memberships); save('map', mapped)
    analyses = []
    class ScopedRunner:
        def __init__(self, cid, sid): self.prefix = digest([cid, sid])[:24]
        def call(self, stage, request): return runner.call(self.prefix + '-' + stage, request)
    for perspective in mapped['opinion_map']['perspectives']:
        if not perspective['minimum_support_met']: continue
        cid = perspective['id']
        for sid in perspective['supported_canonical_ids']:
            analysis = agents.analyse_source(originals[sid], lookup[cid], ScopedRunner(cid, sid))
            analyses.append(analysis); save('arguments/' + digest([cid, sid]), analysis)
    save('analyses', analyses)
    output = agents.bundle(snapshot, records, candidates, memberships, analyses, model=model, documents=documents)
    packets = grounded_factory.fact_packets(output['bundle'], selections)
    checks = []
    for offset in range(0, len(packets), 16):
        batch = packets[offset:offset+16]
        req = nli_fact_records.invocation(batch)
        try:
            response = fact_check(req)
            judgments = nli_fact_records.records(batch, model, response, batch_request=req)
            checks.extend({'claim_id': packet['claim']['id'], 'selections': deepcopy(list(selections)), 'record': record}
                          for packet, record in zip(batch, judgments, strict=True))
        except (ValueError, KeyError, TypeError):
            errors.append({'stage': 'facts', 'reason': 'fact_contract_failed', 'batch_offset': offset})
    save('fact-checks', checks)
    output['bundle']['checks'] = checks
    output['compiled'] = compile_inputs(output['bundle'])
    save('agent-inputs', output)
    return {'artifact_kind': VERSION, 'snapshot_sha256': digest(snapshot.to_dict()),
            'source_states': source_states, 'discovery': discovery, 'membership_schedule': search,
            'candidates': candidates, 'memberships': memberships, 'agent_inputs': output,
            'errors': errors, 'runtime_reference_labels': False, 'quality_gate_passed': False,
            'correct_comment_utilization': None, 'fresh_semantic_outputs_required': True}
