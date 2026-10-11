"""Unattended source -> claims -> bounded candidate gate -> evidence-bound agent profiles.

No assistant-reviewed file is accepted. Model gates are provisional, not quality certification.
"""
from collections import Counter
from dataclasses import asdict, dataclass
import math
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.agents.runtime import request
from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.factory.automatic_contract import (VERSION, LEGACY_VERSION, EXTRACT, GATE, GATE_SCHEMA, digest,
    segments, extraction_schema, validate_extraction, validate_gate, passed,
    SOURCE_AUDIT, SOURCE_SCHEMA, validate_source, source_passed)
from commentscope.factory.claim_clusters import embed, read_json, sha
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.providers.local_llama import generate
from commentscope.storage import write_json_exclusive

BUNDLE_VERSION = 'automatic-perspective-bundle-0.1'
PROFILE_STATUS = 'auto_accepted_unvalidated'


@dataclass(frozen=True)
class Config:
    limit: int = 1000
    neighbors: int = 8
    min_similarity: float = 0.55
    max_gate_calls: int = 2000
    max_source_chars: int = 4000
    max_group_chars: int = 10000

    def validate(self):
        for name, low, high in [('limit', 1, 1000), ('neighbors', 2, 12), ('max_gate_calls', 1, 20000),
                                ('max_source_chars', 100, 4000), ('max_group_chars', 1000, 12000)]:
            v = getattr(self, name)
            if type(v) is not int or not low <= v <= high:
                raise ValueError('Invalid config: ' + name)
        if type(self.min_similarity) not in (float, int) or not math.isfinite(self.min_similarity) or not 0 < self.min_similarity < 1:
            raise ValueError('Invalid minimum similarity')


def local_provider(system, data, schema):
    return generate(system, data, schema, max_tokens=900)


def select_sources(snapshot, config):
    aliases = {r.comment_id: r.duplicate_of for r in normalize_snapshot(snapshot)}
    canonical = sorted((s for s in snapshot.comments if not aliases[s.comment_id]),
                       key=lambda s: (digest(s.comment_id), s.comment_id))
    return canonical[:config.limit], aliases


def bind_claims(source, output):
    parts = segments(source.text_original)
    errors = validate_extraction(output, parts)
    if errors:
        raise ValueError('Invalid extraction: ' + ','.join(errors))
    return [{'claim_id': 'U' + digest([source.comment_id, i])[:20], 'source_comment_id': source.comment_id,
             'statement': c['statement'], 'mode': c['mode'],
             'spans': [p for p in parts if p['id'] in c['segment_ids']]}
            for i, c in enumerate(output['claims'])]


def neighbors(units, vectors, config):
    """Blockwise cosine search: O(n²) arithmetic, O(n*k) results; no transitive merges."""
    if len(vectors) != len(units):
        raise ValueError('Embedding count mismatch')
    if not units:
        return {}
    try:
        import numpy as np
    except ImportError:
        # Dependency-free contract tests/small injected embedders; real runs use the clustering extra.
        normalized, dimension = [], None
        for row in vectors:
            if (not isinstance(row, list) or not row or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                    or dimension is not None and len(row) != dimension):
                raise ValueError('Invalid embeddings')
            dimension = len(row)
            norm = math.sqrt(sum(v*v for v in row))
            if not norm or not math.isfinite(norm):
                raise ValueError('Invalid embedding norms')
            normalized.append([v/norm for v in row])
        result = {}
        for i, unit in enumerate(units):
            candidates = []
            for j, other in enumerate(units):
                if i == j or unit['source_comment_id'] == other['source_comment_id'] or unit['mode'] != other['mode'] or unit['mode'] == 'unclear':
                    continue
                score = sum(a*b for a,b in zip(normalized[i], normalized[j]))
                if score >= config.min_similarity:
                    candidates.append({'claim_id': other['claim_id'], 'cosine': score})
            result[unit['claim_id']] = sorted(candidates, key=lambda r: (-r['cosine'], r['claim_id']))[:config.neighbors]
        return result
    try:
        rows = np.asarray(vectors, dtype=float)
    except (TypeError, ValueError):
        raise ValueError('Invalid embeddings') from None
    if rows.ndim != 2 or rows.shape[1] < 1 or not np.isfinite(rows).all():
        raise ValueError('Invalid embeddings')
    norms = np.linalg.norm(rows, axis=1)
    if not np.isfinite(norms).all() or (norms == 0).any():
        raise ValueError('Invalid embedding norms')
    rows = rows / norms[:, None]
    result = {}
    for start in range(0, len(units), 128):
        scores = rows[start:start+128] @ rows.T
        for offset, score_row in enumerate(scores):
            i = start + offset
            eligible = [j for j, u in enumerate(units) if j != i
                        and u['source_comment_id'] != units[i]['source_comment_id']
                        and u['mode'] == units[i]['mode'] != 'unclear'
                        and score_row[j] >= config.min_similarity]
            ranked = sorted(eligible, key=lambda j: (-float(score_row[j]), units[j]['claim_id']))[:config.neighbors]
            result[units[i]['claim_id']] = [{'claim_id': units[j]['claim_id'], 'cosine': float(score_row[j])} for j in ranked]
    return result


class Calls:
    """Immutable, input-hashed requests. Reopening the same run reuses exact prior results."""
    def __init__(self, directory, manifest, provider):
        self.directory = Path(directory)
        path = self.directory / 'manifest.json'
        if path.exists():
            if read_json(path) != manifest:
                raise ValueError('Run configuration/source/code changed; choose a new run directory')
        else:
            write_json_exclusive(path, manifest)
        self.provider = provider
        self.expiry = manifest['expires_at']
        self.new_calls = 0

    def __call__(self, system, data, schema):
        require_live(self.expiry)
        identity = {'system': system, 'data': data, 'schema': schema}
        key = digest(identity)
        path = self.directory / ('call-' + key + '.json')
        if path.exists():
            stored = read_json(path)
            if stored['request'] != identity or digest(stored['result']) != stored['result_sha256']:
                raise ValueError('Checkpoint changed')
            return stored['result']
        result = request(system, data, schema, self.provider)
        write_json_exclusive(path, {'request': identity, 'result': result, 'result_sha256': digest(result)})
        self.new_calls += 1
        return result


def checked_call(calls, system, data, schema, validator):
    """One structural repair at most. Never retry a semantic rejection until it passes."""
    attempts = []
    for attempt in range(2):
        result = calls(system, data, schema)
        result = {**result, 'errors': list(result['errors'])}
        if not result['errors']:
            result['errors'] = validator(result['output'])
        attempts.append(result)
        if not result['errors'] or 'transport_error' in result['errors']:
            break
        data = {**data, 'FORMAT_REPAIR': {'errors': result['errors'], 'attempt': attempt + 1}}
    return {**attempts[-1], 'attempts': attempts}


def gate_data(anchor, member, sources):
    return {'COMMON_CLAIM': anchor['statement'], 'MEMBER_CLAIM': member['statement'],
            'MEMBER_SPANS': [p['text'] for p in member['spans']]}


def source_data(unit):
    return {'PROPOSED_CLAIM': unit['statement'], 'SOURCE_SPANS': [p['text'] for p in unit['spans']]}


def isolated_judge(calls, anchor, member, sources):
    # Cached by exact payload: the same member is checked once across different anchors.
    audit = checked_call(calls, SOURCE_AUDIT, source_data(member), SOURCE_SCHEMA, validate_source)
    if not source_passed(audit):
        return {'output': None, 'errors': ['source_audit_rejected'], 'attempts': [], 'source_audit': audit}
    result = checked_call(calls, GATE, gate_data(anchor, member, sources), GATE_SCHEMA, validate_gate)
    return {**result, 'source_audit': audit}


def group_claims(units, candidates, sources, config, judge):
    """Greedy disjoint support stars; every member has a direct gate to the shared core."""
    by_id = {u['claim_id']: u for u in units}
    remaining = set(by_id)
    gates, groups = [], []
    budget_hit = False
    order = sorted(by_id, key=lambda i: (-len(candidates[i]), i))
    for aid in order:
        if aid not in remaining or by_id[aid]['mode'] == 'unclear':
            continue
        choices = [r['claim_id'] for r in candidates[aid] if r['claim_id'] in remaining]
        if len({by_id[i]['source_comment_id'] for i in [aid, *choices]}) < 3:
            continue
        accepted, seen_sources, chars = [], set(), 0
        for mid in [aid, *choices]:
            unit = by_id[mid]
            cid = unit['source_comment_id']
            if cid in seen_sources:
                continue
            cost = sum(len(p['text']) for p in unit['spans'])
            if chars + cost > config.max_group_chars:
                continue
            if len(gates) >= config.max_gate_calls:
                budget_hit = True
                break
            decision = judge(by_id[aid], unit)
            gates.append({'anchor_id': aid, 'member_id': mid, 'result': decision})
            if passed(decision):
                accepted.append(mid)
                seen_sources.add(cid)
                chars += cost
            elif mid == aid:
                break
        if aid in accepted and len(seen_sources) >= 3:
            groups.append({'cluster_id': f'AC{len(groups)+1:03d}', 'anchor_id': aid,
                           'member_ids': accepted, 'common_claim': by_id[aid]['statement'],
                           'status': PROFILE_STATUS})
            remaining.difference_update(accepted)
        if budget_hit:
            break
    inspected = {g['member_id'] for g in gates}
    unresolved = []
    for uid in sorted(remaining):
        count = len({by_id[i]['source_comment_id'] for i in [uid, *[v['claim_id'] for v in candidates[uid]]]})
        reason = ('unclear_mode' if by_id[uid]['mode'] == 'unclear' else
                  'insufficient_neighbors_unverified' if count < 3 else
                  'gate_budget_exhausted' if budget_hit and uid not in inspected else 'no_accepted_group')
        unresolved.append({'claim_id': uid, 'reason': reason})
    return groups, gates, unresolved, budget_hit


def accounting(snapshot, selected, aliases, records, units, groups, gates, unresolved, budget_hit):
    assigned = {uid for g in groups for uid in g['member_ids']}
    covered = {u['source_comment_id'] for u in units if u['claim_id'] in assigned}
    selected_ids = {s.comment_id for s in selected}
    canonical_count = sum(not a for a in aliases.values())
    summary = {'source_count': len(snapshot.comments), 'canonical_sources': canonical_count,
               'selected_sources': len(selected), 'duplicate_aliases': sum(bool(a) for a in aliases.values()),
               'source_statuses': dict(Counter(r['status'] for r in records)), 'claims': len(units),
               'auto_agents': len(groups), 'covered_unique_sources': len(covered),
               'coverage_of_selected': len(covered)/len(selected) if selected else 0,
               'coverage_of_canonical': len(covered)/canonical_count if canonical_count else 0,
               'unassigned_claims': len(unresolved), 'gate_decisions': len(gates), 'gate_budget_exhausted': budget_hit,
               'accepted_perspectives': 0, 'quality_status': 'not_independently_evaluated'}
    dispositions = [{'source_comment_id': s.comment_id,
                     'status': 'duplicate_alias' if aliases[s.comment_id] else 'not_selected' if s.comment_id not in selected_ids
                     else 'represented' if s.comment_id in covered else 'selected_not_represented',
                     'duplicate_of': aliases[s.comment_id]} for s in snapshot.comments]
    return summary, dispositions


def run(snapshot_path, directory, config=Config(), *, provider=local_provider, embedder=embed,
        metadata=None, progress=lambda value: None):
    config.validate()
    loaded = load_snapshot(snapshot_path)
    snapshot = loaded.snapshot
    require_live(snapshot.usage.expires_at)
    if len(snapshot.comments) > 1000:
        raise ValueError('Snapshot limited to 1000 comments in this phase')
    selected, aliases = select_sources(snapshot, config)
    sources = {s.comment_id: s for s in snapshot.comments}
    manifest = {'artifact_kind': VERSION, 'snapshot_sha256': loaded.sha256,
                'expires_at': snapshot.usage.expires_at, 'config': asdict(config),
                'selection': 'canonical IDs sorted by SHA256, first limit; not a representative sample',
                'selected_ids': [s.comment_id for s in selected], 'model': metadata or {},
                'embedding': {'model': MODEL, 'revision': REVISION},
                'code_sha256': {name: sha(Path(__file__).parent.parent / name) for name in
                               ['factory/automatic.py', 'factory/automatic_contract.py', 'factory/claim_clusters.py',
                                'cluster_baseline.py', 'agents/runtime.py', 'providers/local_llama.py']},
                'prompt_sha256': {'extract': digest(EXTRACT), 'gate': digest(GATE), 'source': digest(SOURCE_AUDIT)},
                'isolation_policy': 'no_parent_text; source_audit_before_common_claim; context_relations_not_evidence',
                'request_settings': {'temperature': 0, 'seed': 407, 'max_tokens': 900},
                'human_handling': False, 'semantic_guarantee': False}
    calls = Calls(directory, manifest, provider)
    records, units = [], []
    for index, source in enumerate(selected):
        parent = sources.get(source.parent_id)
        if len(source.text_original) > config.max_source_chars:
            records.append({'source_comment_id': source.comment_id, 'status': 'context_budget_exceeded', 'claims': []})
            continue
        parts = segments(source.text_original)
        if not parts or len(parts) > 80:
            records.append({'source_comment_id': source.comment_id, 'status': 'segmentation_limit', 'claims': []})
            continue
        data = {'COMMENT': parts}
        result = checked_call(calls, EXTRACT, data, extraction_schema(parts), lambda v: validate_extraction(v, parts))
        claims = [] if result['errors'] else bind_claims(source, result['output'])
        records.append({'source_comment_id': source.comment_id,
                        'status': 'extraction_failed' if result['errors'] else result['output']['status'],
                        'claims': claims, 'result': result})
        units.extend(claims)
        progress({'stage': 'extract', 'processed': index+1, 'selected': len(selected), 'claims': len(units)})
    vectors_path = Path(directory) / 'embeddings.json'
    texts = [u['statement'] for u in units]
    if vectors_path.exists():
        cached = read_json(vectors_path)
        if cached['texts'] != texts or digest(cached['vectors']) != cached['vectors_sha256']:
            raise ValueError('Embedding checkpoint changed')
        vectors = cached['vectors']
    else:
        vectors = embedder(texts) if texts else []
        write_json_exclusive(vectors_path, {'texts': texts, 'vectors': vectors, 'vectors_sha256': digest(vectors)})
    candidates = neighbors(units, vectors, config)
    checked = 0
    def judge(anchor, member):
        nonlocal checked
        result = isolated_judge(calls, anchor, member, sources)
        checked += 1
        progress({'stage': 'gate', 'checked': checked, 'budget': config.max_gate_calls})
        return result
    groups, gates, unresolved, budget_hit = group_claims(units, candidates, sources, config, judge)
    summary, dispositions = accounting(snapshot, selected, aliases, records, units, groups, gates, unresolved, budget_hit)
    return {**manifest, 'records': records, 'units': units, 'candidates': candidates,
            'groups': groups, 'gates': gates, 'unresolved': unresolved, 'summary': summary,
            'source_disposition': dispositions,
            'limitations': ['Same-model gates are not independent evaluation',
                            'Top-k and modality filters can miss compatible claims; disjoint stars are order sensitive',
                            'Coverage is not accuracy; insufficient neighbors do not establish a rare viewpoint',
                            'No service-time human handling; offline quality evaluation remains required']}


def build_bundle(snapshot_path, report):
    """Replay structural gates/source binding; never read or synthesize manual review files."""
    loaded = load_snapshot(snapshot_path)
    snapshot = loaded.snapshot
    require_live(snapshot.usage.expires_at)
    if (report.get('artifact_kind') not in [VERSION, LEGACY_VERSION] or report.get('snapshot_sha256') != loaded.sha256
            or report.get('expires_at') != snapshot.usage.expires_at or report.get('human_handling') is not False):
        raise ValueError('Automatic report provenance mismatch')
    config = Config(**report['config']); config.validate()
    selected, aliases = select_sources(snapshot, config)
    if report['selected_ids'] != [s.comment_id for s in selected]:
        raise ValueError('Selection changed')
    sources = {s.comment_id: s for s in snapshot.comments}
    if [r['source_comment_id'] for r in report['records']] != report['selected_ids']:
        raise ValueError('Source coverage changed')
    rebound = []
    for record in report['records']:
        source = sources[record['source_comment_id']]
        parent = sources.get(source.parent_id)
        result = record.get('result')
        expected = []
        if len(source.text_original) > config.max_source_chars or (report['artifact_kind'] == LEGACY_VERSION
                and parent and len(parent.text_original) > config.max_source_chars):
            expected_status = 'context_budget_exceeded'
            if result: raise ValueError('Oversize source unexpectedly processed')
        elif not segments(source.text_original) or len(segments(source.text_original)) > 80:
            expected_status = 'segmentation_limit'
            if result: raise ValueError('Over-segmented source unexpectedly processed')
        else:
            if not isinstance(result, dict): raise ValueError('Missing extraction result')
            expected_status = 'extraction_failed' if result['errors'] else result['output'].get('status')
        if result and not result['errors']:
            expected = bind_claims(source, result['output'])
        if record['claims'] != expected or record['status'] != expected_status:
            raise ValueError('Claim source binding changed')
        rebound.extend(expected)
    if rebound != report['units']:
        raise ValueError('Claim set changed')
    by_id = {u['claim_id']: u for u in rebound}
    if set(report['candidates']) != set(by_id):
        raise ValueError('Candidate coverage changed')
    for aid, rows in report['candidates'].items():
        seen = set()
        for row in rows:
            mid = row['claim_id']
            if (mid not in by_id or mid in seen or mid == aid or by_id[mid]['source_comment_id'] == by_id[aid]['source_comment_id']
                    or by_id[mid]['mode'] != by_id[aid]['mode'] or not math.isfinite(row['cosine'])
                    or not config.min_similarity <= row['cosine'] <= 1.000001):
                raise ValueError('Invalid candidate edge')
            seen.add(mid)
        if len(rows) > config.neighbors:
            raise ValueError('Too many candidate edges')
    stream = iter(report['gates'])
    def replay(anchor, member):
        try:
            item = next(stream)
        except StopIteration:
            raise ValueError('Missing gate decision') from None
        if item['anchor_id'] != anchor['claim_id'] or item['member_id'] != member['claim_id']:
            raise ValueError('Gate edge changed')
        if report['artifact_kind'] == VERSION and 'source_audit' not in item['result']:
            raise ValueError('Missing isolated source audit')
        return item['result']
    groups, gates, unresolved, hit = group_claims(rebound, report['candidates'], sources, config, replay)
    if next(stream, None) is not None or groups != report['groups'] or unresolved != report['unresolved']:
        raise ValueError('Group decisions changed')
    summary, dispositions = accounting(snapshot, selected, aliases, report['records'], rebound, groups, gates, unresolved, hit)
    if summary != report['summary'] or dispositions != report['source_disposition']:
        raise ValueError('Coverage accounting changed')
    agents = []
    for group in groups:
        cards = []
        for uid in group['member_ids']:
            unit = by_id[uid]; source = sources[unit['source_comment_id']]; parent = sources.get(source.parent_id)
            cards.append({'evidence_id': uid, 'source_comment_id': source.comment_id,
                          'original_text': source.text_original, 'source_url': source.source_url,
                          'support_spans': unit['spans'], 'allowed_claim': unit['statement'],
                          'reviewer_reading_ko': '', 'cautions_ko': '자동 추출·검사 결과입니다. 조건과 개별 이유를 다른 근거에 일반화하지 마세요.',
                          'interpretation_origin': 'automatic_model_not_human_review',
                          'parent_context': {'comment_id': source.parent_id, 'status': source.parent_status,
                                             'text': parent.text_original if parent else None, 'may_cite_as_support': False}})
        agents.append({'agent_id': f'A{len(agents)+1:03d}', 'title': group['common_claim'],
                       'assertion_family': by_id[group['anchor_id']]['mode'], 'status': PROFILE_STATUS,
                       'evidence': cards, 'human_approved': False,
                       'constraints': ['Represent only the shared core and assigned claim spans, not the entire comment.',
                                       'Reasons and conditions belong only to their source; preserve all restrictions.',
                                       'Automatic model acceptance is provisional, not independent validation or population consensus.']})
    non_agents = [{'title': u['claim_id'], 'reason': u['reason'], 'member_ids': [u['claim_id']]} for u in unresolved]
    non_agents += [{'title': r['source_comment_id'], 'reason': r['status'], 'member_ids': []}
                   for r in report['records'] if not r['claims']]
    return {'artifact_kind': BUNDLE_VERSION, 'snapshot_sha256': loaded.sha256, 'factory_report_digest': digest(report),
            'expires_at': snapshot.usage.expires_at, 'agents': agents, 'non_agents': non_agents,
            'dataset': {'video': snapshot.to_dict()['video'], 'captured_at': snapshot.captured_at,
                        'sample_size': len(snapshot.comments), 'processed_sources': len(selected),
                        'sampling': snapshot.to_dict()['sampling'], 'factory_summary': report['summary']},
            'human_approved': False, 'human_handling': False, 'accepted_perspectives': 0,
            'limitations': report['limitations']}


def load_bundle(snapshot_path, report_path, bundle_path):
    bundle = read_json(bundle_path)
    if bundle != build_bundle(snapshot_path, read_json(report_path)):
        raise ValueError('Automatic bundle changed; rebuild from its source-bound report')
    return bundle
