"""Strict draft coverage and citation boundary, not semantic entailment validation."""
from collections import Counter

VERSION = 'perspective-draft-0.1'


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def array(items, minimum=0, maximum=20):
    return {'type': 'array', 'items': items, 'minItems': minimum, 'maxItems': maximum}


def schema(member_ids):
    string = {'type': 'string', 'minLength': 1}
    ref = {'type': 'string', 'enum': list(member_ids)}
    citation = obj({'member_id': ref, 'quote': string})
    statement = obj({'text': string, 'evidence': array(citation, 1)})
    detail = obj({'kind': {'type': 'string', 'enum': ['reason', 'condition', 'variation']},
                  'text': string, 'evidence': array(citation, 1)})
    group = obj({'members': array(ref, 1), 'common': statement, 'details': array(detail, maximum=4)})
    return obj({'groups': array(group, maximum=20), 'excluded': array(obj({'member_id': ref, 'reason': string}))})


def validate(value, members):
    errors = []
    def keys(item, expected):
        return isinstance(item, dict) and set(item) == set(expected)
    def text(item):
        return isinstance(item, str) and bool(item.strip())
    if not keys(value, ['groups', 'excluded']):
        return ['envelope_keys']
    if any(not isinstance(value[k], list) or len(value[k]) > 20 for k in ['groups', 'excluded']):
        return ['envelope_arrays']
    assigned = []
    for index, group in enumerate(value['groups']):
        prefix = f'groups[{index}]'
        if not keys(group, ['members', 'common', 'details']):
            errors.append(prefix+'.keys'); continue
        ids = group['members']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or any(not isinstance(i, str) or i not in members for i in ids):
            errors.append(prefix+'.members'); continue
        assigned.extend(ids)
        if not isinstance(group['details'], list) or len(group['details']) > 4:
            errors.append(prefix+'.details'); continue
        for number, statement in enumerate([group['common'], *group['details']]):
            path = prefix + ('.common' if number == 0 else f'.details[{number-1}]')
            expected = ['text', 'evidence'] if number == 0 else ['kind', 'text', 'evidence']
            if not keys(statement, expected) or not text(statement.get('text')):
                errors.append(path+'.keys_or_text'); continue
            if number and statement['kind'] not in ['reason', 'condition', 'variation']:
                errors.append(path+'.kind')
            evidence = statement['evidence']
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
                errors.append(path+'.evidence'); continue
            cited = []
            for citation in evidence:
                if not keys(citation, ['member_id', 'quote']) or not isinstance(citation.get('member_id'), str) or citation['member_id'] not in ids:
                    errors.append(path+'.foreign_citation'); continue
                mid = citation['member_id']; cited.append(mid)
                if not text(citation['quote']) or citation['quote'] not in members[mid]['target']:
                    errors.append(path+'.quote_not_in_target')
            if len(cited) != len(set(cited)):
                errors.append(path+'.duplicate_citation')
            if number == 0 and set(cited) != set(ids):
                errors.append(path+'.common_does_not_cover_group')
    for item in value['excluded']:
        if not keys(item, ['member_id', 'reason']) or not isinstance(item.get('member_id'), str) or item['member_id'] not in members or not text(item.get('reason')):
            errors.append('invalid_exclusion'); continue
        assigned.append(item['member_id'])
    if Counter(assigned) != Counter({mid: 1 for mid in members}):
        errors.append('partition_not_exact')
    return errors


def bind(value, members):
    """Only the host attaches claim/source IDs and status. Never approved here."""
    errors = validate(value, members)
    if errors:
        raise ValueError('; '.join(errors))
    def citation(c):
        member = members[c['member_id']]
        return {**c, 'claim_id': member['claim_id'], 'source_comment_id': member['source_comment_id']}
    def statement(s):
        return {**s, 'evidence': [citation(c) for c in s['evidence']]}
    groups = []
    for index, group in enumerate(value['groups'], 1):
        source_ids = sorted({members[mid]['source_comment_id'] for mid in group['members']})
        groups.append({'draft_id': f'D{index:02d}', 'members': group['members'], 'source_ids': source_ids,
                       'status': 'needs_semantic_review' if len(source_ids) >= 3 else 'rare_needs_review',
                       'common': statement(group['common']), 'details': [statement(d) for d in group['details']]})
    return {'groups': groups, 'excluded': [{**e, 'claim_id': members[e['member_id']]['claim_id'],
                'source_comment_id': members[e['member_id']]['source_comment_id']} for e in value['excluded']],
            'semantic_review_status': 'pending', 'accepted_perspectives': 0}
