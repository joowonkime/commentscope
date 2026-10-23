"""Embedding-first whole-corpus clustering, with no per-comment frame calls.

The caller owns model lifetimes, durable calls, budget and resource enforcement.
This stage emits a map, not Agent approval or a measured utilization score.
"""
import json

from commentscope.factory import batch_stances as batch
from commentscope.factory.automatic_contract import digest
from commentscope.factory.framed_corpus import sources, normalized, similarity, RETRIEVAL

VERSION = 'batched-raw-corpus-clustering-0.1'


def discovery_schedule(originals, vectors):
    vectors = normalized(vectors, originals)
    remaining = set(originals); batches = []; deferred = []
    while remaining:
        seed = min(remaining)
        ranked = sorted(remaining, key=lambda sid: (-similarity(vectors[seed], vectors[sid]), sid))
        ranked.remove(seed); ranked.insert(0, seed)
        selected = []
        for sid in ranked:
            try:
                batch.discovery_request([originals[i] for i in [*selected, sid]])
            except ValueError:
                if sid == seed:
                    deferred.append({'source_id': sid, 'reason': 'discovery_request_capacity'})
                    remaining.remove(sid)
                continue
            selected.append(sid)
            if len(selected) == batch.SOURCE_LIMIT: break
        if selected:
            batches.append(sorted(selected)); remaining.difference_update(selected)
    return {'batches': batches, 'deferred_sources': deferred, 'membership_approval': False}


def membership_schedule(originals, candidates, source_vectors, candidate_vectors, *, limits=RETRIEVAL):
    if (set(limits) != {'initial', 'fallback'}
            or any(type(n) is not int or not 1 <= n <= 16 for n in limits.values())):
        raise ValueError('Finite positive retrieval widths required')
    lookup = {}
    for candidate in candidates:
        batch.validate_candidate(candidate)
        if candidate['id'] in lookup: raise ValueError('Duplicate candidate')
        lookup[candidate['id']] = candidate
        for sid in candidate['nominee_source_ids']:
            if sid not in originals or candidate['source_sha256'][sid] != digest(originals[sid]):
                raise ValueError('Nominee source changed')
    sv = normalized(source_vectors, originals); cv = normalized(candidate_vectors, lookup)
    nominated = {sid: set() for sid in originals}
    for candidate in candidates:
        for sid in candidate['nominee_source_ids']: nominated[sid].add(candidate['id'])
    initial = []; fallback = []; rankings = []
    for sid in sorted(originals):
        ranked = sorted(cv, key=lambda cid: (-similarity(sv[sid], cv[cid]), cid))
        first = set(ranked[:limits['initial']]) | nominated[sid]
        later = [cid for cid in ranked if cid not in first][:limits['fallback']]
        initial.extend({'source_id': sid, 'candidate_id': cid} for cid in ranked if cid in first)
        fallback.extend({'source_id': sid, 'candidate_id': cid} for cid in later)
        rankings.append({'source_id': sid, 'initial_candidate_ids': [cid for cid in ranked if cid in first],
                         'fallback_candidate_ids': later, 'nominated_candidate_ids': sorted(nominated[sid])})
    return {'initial': initial, 'fallback_if_unlinked': fallback, 'rankings': rankings,
            'canonical_sources': len(originals), 'candidate_count': len(candidates), 'membership_approval': False}


def admission_batches(originals, candidates, pairs):
    """Split requests without cutting originals or automatically retrying calls."""
    registry = list(originals.values()); batches = []; deferred = []; current = []
    for pair in pairs:
        try:
            batch.membership_request(registry, candidates, [*current, pair])
        except ValueError:
            if current: batches.append(current); current = []
            try: batch.membership_request(registry, candidates, [pair])
            except ValueError:
                deferred.append({**pair, 'reason': 'membership_request_capacity'}); continue
        current.append(pair)
    if current: batches.append(current)
    return {'batches': batches, 'deferred_pairs': deferred}


def process(snapshot, runner, embed, *, save=None, limits=RETRIEVAL, source_ids=None):
    save = save or (lambda name, value: None)
    population = sources(snapshot)
    if source_ids is not None:
        if (not isinstance(source_ids, list) or not source_ids
                or any(not isinstance(sid, str) or sid not in population for sid in source_ids)
                or len(set(source_ids)) != len(source_ids)):
            raise ValueError('Pilot source IDs must be unique canonical originals')
        originals = {sid: population[sid] for sid in sorted(source_ids)}
    else: originals = population
    packets = list(originals.values()); errors = []; discoveries = []
    # Every canonical original is embedded once here, not once per frame/purpose.
    vectors = embed('sources', {sid: p['text'] for sid, p in originals.items()}) if originals else {}
    schedule = discovery_schedule(originals, vectors); save('discovery-schedule', schedule)
    states = {sid: {'source_id': sid, 'source_sha256': digest(p),
                    'discovery_state': 'unprocessed' if sid in originals else 'not_scheduled'}
              for sid, p in population.items()}
    for item in schedule['deferred_sources']:
        states[item['source_id']]['discovery_state'] = 'capacity_deferred'
        errors.append({'stage': 'discovery', **item})
    for i, ids in enumerate(schedule['batches']):
        selected = [originals[sid] for sid in ids]
        try:
            result = runner.call(f'discovery-{i:04}', batch.discovery_request(selected))
            record = batch.bind_discovery(selected, result)
            discoveries.append(record); save(f'discoveries/{i:04}', record)
            aliases = {f'S{j}': sid for j, sid in enumerate(record['source_ids'])}
            for row in record['decision']['sources']:
                states[aliases[row['source_key']]]['discovery_state'] = row['state']
        except (ValueError, KeyError, TypeError):
            errors.append({'stage': 'discovery', 'batch': i, 'source_ids': ids, 'reason': 'discovery_contract_error'})
            for sid in ids: states[sid]['discovery_state'] = 'discovery_contract_error'
    candidates = batch.candidates_from(packets, discoveries)
    save('discoveries', discoveries); save('candidates', candidates)
    cv = embed('candidates', {c['id']: json.dumps(c['contract'], ensure_ascii=False, sort_keys=True)
                              for c in candidates}) if candidates else {}
    search = membership_schedule(originals, candidates, vectors, cv, limits=limits)
    save('membership-schedule', search)
    decisions = []; execution = []
    for phase in ('initial', 'fallback_if_unlinked'):
        linked = {m['source_id'] for b in decisions for m in b['memberships'] if m['relation'] == 'supported'}
        pairs = [p for p in search[phase] if phase == 'initial' or p['source_id'] not in linked]
        packed = admission_batches(originals, candidates, pairs)
        execution.append({'phase': phase, **packed})
        for item in packed['deferred_pairs']: errors.append({'stage': 'membership', 'phase': phase, **item})
        for i, selected in enumerate(packed['batches']):
            try:
                result = runner.call(f'{phase}-{i:04}', batch.membership_request(packets, candidates, selected))
                record = batch.bind_membership(packets, candidates, selected, result)
                decisions.append(record); save(f'memberships/{phase}-{i:04}', record)
            except (ValueError, KeyError, TypeError):
                errors.append({'stage': 'membership', 'phase': phase, 'batch': i,
                               'pairs': selected, 'reason': 'membership_contract_error'})
    mapped = batch.assemble_map(snapshot, discoveries, candidates, decisions)
    assessed = {m['source_id'] for m in mapped['memberships']}
    linked = {m['source_id'] for m in mapped['memberships'] if m['relation'] == 'supported'}
    for sid, row in states.items():
        row['membership_state'] = 'supported' if sid in linked else 'assessed_without_support' if sid in assessed else 'unassessed'
    inventory = [states[sid] for sid in sorted(states)]
    save('source-states', inventory); save('membership-batches', decisions); save('map', mapped)
    return {'artifact_kind': VERSION, 'snapshot_sha256': digest(snapshot.to_dict()),
            'processing_scope': {'source_ids': sorted(originals), 'canonical_population': len(population),
                                 'whole_corpus_scheduled': set(originals) == set(population)},
            'source_states': inventory, 'discovery_schedule': schedule, 'discoveries': discoveries,
            'candidates': candidates, 'membership_schedule': search, 'admission_execution': execution,
            'membership_batches': decisions, 'map': mapped, 'errors': errors,
            'runtime_reference_labels': False, 'quality_gate_passed': False,
            'correct_comment_utilization': None, 'agent_generation_state': 'requires_argument_adapter',
            'per_comment_frame_calls': 0}
