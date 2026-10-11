"""Fixed member coverage, with host-bound full-target evidence, revision 0.2."""
from commentscope.contracts.perspective_draft import obj, array, validate as validate_canonical

VERSION = 'perspective-assignment-0.2'


def schema(member_ids):
    ids = list(member_ids)
    groups = [f'G{i+1}' for i in range(len(ids))]
    string = {'type': 'string', 'minLength': 1}
    assignment = obj({'group_id': {'type': 'string', 'enum': groups+['X']},
                      'exclusion_reason': {'type': ['string', 'null']}})
    detail = obj({'kind': {'type': 'string', 'enum': ['reason', 'condition', 'variation']},
                  'text': string, 'member_ids': array({'type': 'string', 'enum': ids}, 1)})
    group = obj({'group_id': {'type': 'string', 'enum': groups}, 'common': string,
                 'details': array(detail, maximum=4)})
    return obj({'assignments': obj({mid: assignment for mid in ids}), 'groups': array(group)})


def canonicalize(value, members):
    """Explicit wire conversion, not repair: invalid assignments are rejected."""
    def keys(x, expected): return isinstance(x, dict) and set(x) == set(expected)
    if not keys(value, ['assignments', 'groups']) or not keys(value['assignments'], members):
        raise ValueError('assignment_keys')
    if not isinstance(value['groups'], list) or len(value['groups']) > 20:
        raise ValueError('groups_array')
    allowed = {f'G{i+1}' for i in range(len(members))}
    assignments, excluded = {}, []
    for mid, item in value['assignments'].items():
        if not keys(item, ['group_id', 'exclusion_reason']) or not isinstance(item['group_id'], str) or item['group_id'] not in allowed | {'X'}:
            raise ValueError('invalid_assignment')
        if item['group_id'] == 'X':
            if not isinstance(item['exclusion_reason'], str) or not item['exclusion_reason'].strip():
                raise ValueError('missing_exclusion_reason')
            excluded.append({'member_id': mid, 'reason': item['exclusion_reason']})
        else:
            if item['exclusion_reason'] is not None:
                raise ValueError('unexpected_exclusion_reason')
            assignments.setdefault(item['group_id'], []).append(mid)
    groups, seen = [], set()
    def citation(mid): return {'member_id': mid, 'quote': members[mid]['target']}
    for group in value['groups']:
        if not keys(group, ['group_id', 'common', 'details']) or not isinstance(group['group_id'], str) or group['group_id'] not in assignments or group['group_id'] in seen:
            raise ValueError('invalid_group_reference')
        gid = group['group_id']; seen.add(gid)
        if not isinstance(group['details'], list) or len(group['details']) > 4:
            raise ValueError('details_array')
        details = []
        for detail in group['details']:
            if not keys(detail, ['kind', 'text', 'member_ids']) or not isinstance(detail['member_ids'], list) or not detail['member_ids']:
                raise ValueError('invalid_detail')
            ids = detail['member_ids']
            if any(not isinstance(mid, str) or mid not in assignments[gid] for mid in ids) or len(ids) != len(set(ids)):
                raise ValueError('foreign_or_duplicate_detail_evidence')
            details.append({'kind': detail['kind'], 'text': detail['text'], 'evidence': [citation(mid) for mid in ids]})
        groups.append({'members': assignments[gid], 'common': {'text': group['common'], 'evidence': [citation(mid) for mid in assignments[gid]]}, 'details': details})
    if seen != set(assignments):
        raise ValueError('missing_group')
    result = {'groups': groups, 'excluded': excluded}
    errors = validate_canonical(result, members)
    if errors: raise ValueError('; '.join(errors))
    return result
