"""Reuse source-first reason quotations, not every possible sentence range.

Extraction nominates reasons; full sources remain available for semantic choice
and detecting missing essential premises. Selection is not reason-role approval.
"""
import json
from commentscope.contracts.perspective_draft import obj, array
from commentscope.factory import perspective_typing as legacy
from commentscope.factory.automatic_contract import digest

VERSION = 'source-unit-reason-typing-0.1'
SYSTEM = legacy.SYSTEM.replace('using exact complete source\nquotes.',
    'by selecting reason_id from REASON_CANDIDATES. These are fallible prior extractions, '
    'not approved reasons for CORE. MEMBER_SOURCES contains full originals. '
    'The host copies the selected quotation without rewriting it. '
    'If an essential premise is absent from REASON_CANDIDATES, defer with missing_essential_ground.')
SYSTEM = SYSTEM.replace('required_fact_ids identify empirical premises whose failure defeats the core as\nworded,',
    'Set required_fact=true on an empirical reason whose failure defeats the core as worded,')


class UnitReasonTyping:
    VERSION = VERSION

    def __init__(self, units):
        self.units = units

    def inventory(self, sources):
        result = {}
        for unit in sorted(self.units, key=lambda u: u['claim_id']):
            sid = unit['source_comment_id']; quote = unit['reason_quote']
            if sid not in sources or quote is None: continue
            if not quote.strip() or quote not in sources[sid]: raise ValueError('Unbound original reason')
            rid = 'Q'+digest([sid, sources[sid], quote])[:24]
            row = {'source_id': sid, 'source_sha256': digest(sources[sid]), 'text': quote}
            if rid in result and result[rid] != row: raise ValueError('Reason identity collision')
            result[rid] = row
        return dict(sorted(result.items()))

    def invocation(self, claim, sources):
        menu = self.inventory(sources)
        detail = {'anyOf': [obj({'reason_id': {'$ref': '#/$defs/reason_id'},
            'kind': {'type': 'string', 'const': 'empirical_description'}, 'required_fact': {'type': 'boolean'}}),
            obj({'reason_id': {'$ref': '#/$defs/reason_id'},
                 'kind': {'type': 'string', 'enum': ['normative_preference', 'future_expectation']},
                 'required_fact': {'type': 'boolean', 'const': False}})]}
        details = array(detail, maximum=2) if menu else {'type': 'array', 'maxItems': 0, 'items': {'type': 'null'}}
        schema = {'anyOf': [obj({'status': {'type': 'string', 'const': 'defer'},
            'reason': {'type': 'string', 'enum': ['non_substantive', 'mixed_or_unclear',
                'essential_grounds_overflow', 'missing_essential_ground']}}),
            obj({'status': {'type': 'string', 'const': 'classified'},
                 'kind': {'type': 'string', 'enum': list(legacy.KINDS)}, 'details': details})]}
        if menu: schema['$defs'] = {'reason_id': {'type': 'string', 'enum': list(menu)}}
        req = {'system': SYSTEM+'\nRequired schema:\n'+json.dumps(schema),
               'data': {'CORE': claim['text'], 'MEMBER_SOURCES': sources, 'REASON_CANDIDATES': menu},
               'schema': schema, 'max_tokens': 650}
        if len(json.dumps(req).encode()) > 27000: raise ValueError('Typing request byte budget exceeded')
        return req

    def apply(self, proposal, value, members):
        if value == {'status': 'defer', 'reason': 'missing_essential_ground'}: return None
        if value.get('status') == 'defer': return legacy.apply(proposal, value, members)
        if set(value) != {'status', 'kind', 'details'} or value['status'] != 'classified':
            raise ValueError('Invalid typing envelope')
        if not isinstance(value['details'], list) or len(value['details']) > 2: raise ValueError('Reason limit')
        menu = self.inventory(members); seen = set(); details = []; required = []; selected = []
        for i, row in enumerate(value['details'], 1):
            if (set(row) != {'reason_id', 'kind', 'required_fact'} or type(row['required_fact']) is not bool
                    or row['kind'] not in legacy.KINDS): raise ValueError('Invalid reason decision')
            rid = row['reason_id']
            if not isinstance(rid, str) or rid not in menu or rid in seen: raise ValueError('Unknown or duplicate reason')
            if row['required_fact'] and row['kind'] != 'empirical_description': raise ValueError('Nonfactual dependency')
            seen.add(rid); quote = menu[rid]; did = f'D{i}'
            details.append({'id': did, 'kind': row['kind'], 'source_id': quote['source_id'], 'quote': quote['text']})
            selected.append({'detail_id': did, 'reason_id': rid, **quote})
            if row['required_fact']: required.append(did)
        result = legacy.apply(proposal, {'status': 'classified', 'kind': value['kind'],
            'details': details, 'required_fact_ids': required}, members)
        result.update(typing_version=VERSION, selected_reasons=selected,
                      typing_request_sha256=digest(self.invocation(proposal['claims']['C'], members)))
        return result
