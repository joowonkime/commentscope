"""Diagnostic three-option routing using OpenJev's documented hypothesis form.

Normalized entailment is a relative option score, not calibrated confidence.
Routing never edits a comment or approves cluster membership.
"""
from commentscope.providers.local_nli import decide

QUESTION = 'Does this comment contain an independent substantive assertion?'
RUBRICS = {
    'substantive': 'An opinion, experience, prediction, recommendation or explanation about an identifiable topic is asserted. Necessary references resolve within this comment.',
    'non_substantive': 'Only questions, jokes, video-arrival chatter, bare agreement or unendorsed quotations, without a substantive assertion.',
    'context_dependent': 'A proposed assertion needs an absent referent or missing context from outside this comment.',
}


def hypotheses():
    return {label: f'The answer to "{QUESTION}" is {label}: {criterion}' for label, criterion in RUBRICS.items()}


def combine(checks):
    if set(checks) != set(RUBRICS): raise ValueError('Option inventory changed')
    result = {'checks': checks, 'option_scores': None, 'selected': None, 'strict_eligible': False,
              'errors': [], 'calibrated': False, 'service_approval': False}
    if any(r['errors'] for r in checks.values()): return {**result, 'errors': ['option_inference_error']}
    for r in checks.values():
        if decide(r['scores']) != r['relation']: raise ValueError('NLI decision changed')
    values = {name: r['scores']['entailment'] for name, r in checks.items()}
    total = sum(values.values())
    if total <= 1e-9: return {**result, 'errors': ['no_option_support']}
    scores = {name: value/total for name, value in values.items()}
    ranked = sorted(scores, key=lambda name: (-scores[name], name))
    selected = ranked[0] if scores[ranked[0]]-scores[ranked[1]] > 1e-9 else None
    return {**result, 'option_scores': scores, 'selected': selected,
            'strict_eligible': bool(selected == 'substantive' and scores['substantive'] >= .8 and values['substantive'] >= .8)}
