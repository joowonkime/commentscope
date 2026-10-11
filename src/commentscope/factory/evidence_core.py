"""Common propositions from literal retrieval units and their own-comment evidence.

Retrieval focus is not a second factual authority. Each member independently needs
source support, and the common proposition itself must be standalone substantive.
"""
from commentscope.factory import evidence_units as units, grounded_core as old
from commentscope.factory.automatic import checked_call
from commentscope.factory.automatic_contract import digest
from commentscope.factory.shared_core import source, validate_proposal, SCHEMA

VERSION = 'evidence-core-0.1'


def eligibility(text, calls):
    if not units.has_topic(text): return {'allowed': False, 'result': None, 'reason': 'no_lexical_content'}
    result = checked_call(calls, units.ELIGIBILITY_SYSTEM, {'OWN_COMMENT': text, 'FOCUS': text},
                          units.ELIGIBILITY_SCHEMA, lambda v: units.validate_eligibility(v, text))
    allowed = (not result['errors'] and result['output']['status'] == 'substantive' and
               units.has_topic(result['output']['topic_quote']))
    return {'allowed': allowed, 'result': result, 'reason': None if allowed else 'not_standalone_core'}


def check(unit, core, calls, score):
    independent = eligibility(core, calls)
    support = old.verify(source(unit), core, calls, score) if independent['allowed'] else None
    return {'unit_digest': digest(unit), 'core': core, 'eligibility': independent, 'support': support,
            'allowed': bool(support and support['allowed'])}


def discover(anchor, member, calls, score):
    trace = {'version': VERSION, 'input_digest': digest([anchor, member]), 'candidates': [],
             'proposal': None, 'selected_core': None}
    # Prefer an actual source expression if both authors support it; avoid
    # gratuitous rewording such as losing the noun that restricts a condition.
    literals = list(dict.fromkeys(u['statement'] for u in [anchor, member] if len(u['statement']) < 250))
    def test(core, origin):
        checks = [check(u, core, calls, score) for u in [anchor, member]]
        row = {'core': core, 'origin': origin, 'checks': checks, 'allowed': all(c['allowed'] for c in checks)}
        trace['candidates'].append(row)
        if row['allowed']: trace['selected_core'] = core
        return row['allowed']
    for core in literals:
        if test(core, 'literal'): return trace
    proposal = checked_call(calls, old.PROPOSE_SYSTEM, {'LEFT': source(anchor), 'RIGHT': source(member)},
                            SCHEMA, validate_proposal)
    trace['proposal'] = proposal
    if not proposal['errors'] and proposal['output']['core'] and proposal['output']['core'] not in literals:
        test(proposal['output']['core'], 'generated')
    return trace
