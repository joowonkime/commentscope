"""Check synthetic DS-v2 DESIGN fixtures; no product, model, DB or network run.

Semantic observations in these fixtures are prescribed inputs, never inferred
gold. This oracle checks the documented shape/reference/aggregation examples.
The proposed service, API, migration and agent compiler remain unimplemented.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from commentscope.contracts.structured_output import check_output  # noqa: E402
from commentscope.providers import openrouter_decisions as decisions  # noqa: E402


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def draft_digest(value):
    return digest({key: value[key] for key in ('transcript_sha256', 'proposals', 'pair_checks')})


def expand_local_schema(schema):
    """Resolve only acyclic local defs into the repo's explicit schema subset."""
    definitions = schema['$defs']
    def expand(node, visiting=()):
        if isinstance(node, list):
            return [expand(item, visiting) for item in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            name = node['$ref'].removeprefix('#/$defs/')
            if node['$ref'] != '#/$defs/' + name or name not in definitions or name in visiting:
                raise ValueError('Only existing acyclic local definitions supported')
            if set(node) != {'$ref'}:
                raise ValueError('Unexpected reference sibling')
            return expand(definitions[name], (*visiting, name))
        return {key: expand(value, visiting) for key, value in node.items()}
    return expand({'$ref': schema['$ref']})


def materialize(pack, case):
    value = deepcopy(case.get('fixture', pack['base_fixture']))
    for change in case['changes']:
        path = change['path'].strip('/').split('/')
        parent = value
        for part in path[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = path[-1]
        if isinstance(parent, list):
            if key == '-' and change['op'] == 'add':
                parent.append(deepcopy(change['value'])); continue
            key = int(key)
        if change['op'] == 'remove':
            del parent[key]
        elif change['op'] in ('add', 'replace'):
            parent[key] = deepcopy(change['value'])
        else:
            raise ValueError('Unknown fixture patch')
    if case['binding'] in ('all', 'transcript_only'):
        value['transcript_sha256'] = digest(value['points'])
    if case['binding'] in ('all', 'draft_only'):
        for row in value['ratifications']:
            row['draft_sha256'] = draft_digest(value)
    return value


class Invalid(ValueError):
    pass


def require(condition):
    if not condition:
        raise Invalid('Synthetic reference or policy mismatch')


def evaluate(value, schema):
    def result(outcome, accepted=()):
        return {'outcome': outcome, 'accepted_proposal_ids': list(accepted),
                'final_conclusion_available': outcome in ('consensus_ready', 'no_consensus', 'verification_hold', 'no_proposal', 'incomplete'),
                'synthesis_agent_created': outcome == 'consensus_ready' and bool(accepted)}
    checked = check_output(schema, value)
    if not checked['checked'] or checked['errors']:
        return result('invalid')
    try:
        require(value['owner_session_id'] == value['request_session_id'])
        require(bool(value['question'].strip()))
        require(value['transcript_sha256'] == digest(value['points']))
        actors = {p['agent_id']: p for p in value['participants']}
        require(len(actors) == len(value['participants']))
        qualifications = {r['agent_id']: r['status'] for r in value['qualification_records']}
        require(len(qualifications) == len(value['qualification_records']))
        eligible = {a for a, status in qualifications.items() if status == 'passed'}
        require(set(value['catalog_agent_ids']) == eligible)
        require(set(actors) <= eligible)

        sources, refs, conditions = map(set, (value['source_ids'], value['reference_ids'], value['condition_ids']))
        for actor in actors.values():
            require(set(actor['source_ids']) <= sources and set(actor['condition_ids']) <= conditions)
        points = {p['point_id']: p for p in value['points']}
        require(len(points) == len(value['points']))
        for p in points.values():
            require(p['agent_id'] in actors and 1 < p['seq'] <= value['cutoff_seq'])
            require(set(p['condition_ids']) <= conditions and set(p['reference_ids']) <= refs)
            require(all(r in points and points[r]['seq'] < p['seq'] for r in p['requires_point_ids']))
            if p['origin'] == 'original_comment':
                require(bool(p['source_ids']) and not p['reference_ids'])
                require(set(p['source_ids']) <= set(actors[p['agent_id']]['source_ids']))
            else:
                require(not p['source_ids'] and len(p['text']) <= 600)
                require(bool(p['reference_ids']) == (p['origin'] == 'external_evidence'))
            if p['phase'] == 'opening':
                require(p['seq'] <= value['opening_cutoff_seq'] and not p['target_point_ids'])
            else:
                require(p['seq'] > value['opening_cutoff_seq'])
                require(all(r in points and points[r]['phase'] == 'opening'
                            and points[r]['agent_id'] != p['agent_id'] for r in p['target_point_ids']))
        try:
            current, expiry = map(datetime.fromisoformat, (value['evaluation_time'], value['expires_at']))
            require(current.tzinfo is not None and expiry.tzinfo is not None)
        except ValueError as exc:
            raise Invalid('Invalid fixture timestamp') from exc
        if current >= expiry:
            return result('expired')
        surviving = [p for p in points.values() if p['verification'] == 'passed' and p['task_fit'] == 'adequate']
        primary = {}
        for actor in actors:
            opening = sorted((p for p in surviving if p['agent_id'] == actor and p['phase'] == 'opening'), key=lambda p: p['seq'])
            if not opening:
                return result('incomplete')
            primary[actor] = opening[0]['point_id']
        for actor in actors:
            targets = {primary[a] for a in actors if a != actor}
            covered = {r for p in surviving if p['agent_id'] == actor and p['phase'] == 'reply' for r in p['target_point_ids']}
            if not targets <= covered:
                return result('incomplete')
        proposals = {p['proposal_id']: p for p in value['proposals']}
        require(len(proposals) == len(value['proposals']))
        for p in proposals.values():
            require(set(p['condition_ids']) <= conditions)
            require(all(r in points and points[r]['verification'] == 'passed' for r in p['premise_point_ids']))
            available = {r for point in p['premise_point_ids'] for r in points[point]['reference_ids']}
            require(set(p['reference_ids']) <= available)
            require(bool(p['reference_ids']) == (p['origin'] == 'external_evidence'))
        pairs, blocked = set(), set()
        eligible = {pid for pid, p in proposals.items() if p['verification'] == 'passed'}
        for pair in value['pair_checks']:
            key = frozenset((pair['left'], pair['right']))
            require(len(key) == 2 and key <= eligible and key not in pairs)
            pairs.add(key)
            if pair['choice'] != 'compatible':
                blocked.update(key)
        require(pairs == {frozenset((a, b)) for a in eligible for b in eligible if a != b})
        votes = {}
        for row in value['ratifications']:
            key = row['agent_id'], row['proposal_id']
            require(key not in votes and key[0] in actors and key[1] in proposals)
            require(proposals[key[1]]['verification'] == 'passed' and key[1] not in blocked)
            require(row['draft_sha256'] == draft_digest(value))
            require(all(r in points and points[r]['agent_id'] == key[0]
                        and points[r]['verification'] == 'passed' for r in row['reason_point_ids']))
            require(set(row['missing_condition_ids']) <= set(actors[key[0]]['condition_ids']))
            require(bool(row['missing_condition_ids']) == (row['decision'] == 'needs_condition'))
            votes[key] = row
        if not proposals:
            return result('no_proposal')
        accepted, held = [], False
        for pid, p in proposals.items():
            if p['verification'] != 'passed' or pid in blocked:
                held = True; continue
            rows = [votes.get((actor, pid)) for actor in actors]
            if any(r is None or r['verification'] != 'passed' for r in rows):
                held = True; continue
            if all(r['decision'] == 'accept' for r in rows):
                accepted.append(pid)
        return result('consensus_ready', accepted) if accepted else result('verification_hold' if held else 'no_consensus')
    except Invalid:
        return result('invalid')


def bounded_choice_examples():
    counts = {'turn': 16, 'draft': 15, 'ratification': 12}
    for stage, count in counts.items():
        payload = {'model': decisions.DEPLOYMENT['model'], 'provider': decisions.routing(decisions.DEPLOYMENT),
                   'state': {'SYNTHETIC_ONLY': True, 'STAGE': stage},
                   'questions': {f'q{i}': {'type': 'choice', 'instructions': 'Inspect only the synthetic addressed item.',
                       'criteria': {'pass': 'Fits the supplied item.', 'hold': 'Does not fit or is uncertain.'}} for i in range(count)}}
        decisions.validate_request(payload, decisions.DEPLOYMENT)
        oversized = deepcopy(payload); oversized['state']['SYNTHETIC_TEXT'] = '가' * 10000
        try:
            decisions.validate_request(oversized, decisions.DEPLOYMENT)
        except ValueError:
            pass
        else:
            raise AssertionError('Oversized UTF-8 fixture was accepted')
    assert [6*n+2 for n in (2, 3)] == [14, 20]
    return counts


def main():
    directory = ROOT / 'docs/design/contracts'
    schema = expand_local_schema(json.loads((directory / 'debate-synthesis-v2.schema.json').read_text(encoding='utf-8')))
    pack = json.loads((directory / 'debate-synthesis-v2.examples.json').read_text(encoding='utf-8'))
    if pack['synthetic_only'] is not True:
        raise ValueError('Only public synthetic design inputs allowed')
    failures = []
    for case in pack['cases']:
        actual = evaluate(materialize(pack, case), schema)
        if actual != case['expected']:
            failures.append({'id': case['id'], 'expected': case['expected'], 'actual': actual})
    print(json.dumps({'design_cases': len(pack['cases']), 'failures': failures,
                      'choice_counts': bounded_choice_examples(), 'model_calls': 0, 'network_calls': 0,
                      'product_implementation_checked': False, 'semantic_accuracy_checked': False}, ensure_ascii=False))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
