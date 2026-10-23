"""Bounded, literal agreement/disagreement syntax; no stance inversion.

The operator addresses another utterance. A following colon introduces a
separately located own utterance, not an automatic negation of that utterance.
Parsing does not identify the target, approve authorship or invent an opposite.
"""
import re
from commentscope.factory import contextual_propositions as cp, explicit_discourse as ed

VERSION='source-discourse-acts-20261017-v1'
PREFIX=re.compile(r"^\s*(?:I|we)\s+(?P<neg>do\s+not\s+|don't\s+|don’t\s+)?(?P<verb>agree|disagree)\s*(?P<end>:|[.!?]\s*$)",re.I)


def structure(bundle):
    cp.validate_bundle(bundle);part=bundle['assertion'];match=PREFIX.match(part['text'])
    if match is None:return None
    graph=ed.parse(bundle['source']);text=bundle['source']['text']
    a=part['start'];b=a+match.end()
    if any(q['start']<b and a<q['end'] for q in graph['quotation_ranges']):return None
    operator=ed.span(text,a,b)
    body=ed.span(text,b,part['end']) if match['end']==':' else None
    if body is not None and not body['text']:body=None
    # "not disagree" is kept as such; it is not silently strengthened to agree.
    return {'artifact_kind':VERSION,'operator':operator,
        'relation':('not_' if match['neg'] else '')+match['verb'].lower(),
        'following_own_utterance':body,'target_unassessed':True,
        'negates_following_utterance':False,'semantic_approval':False}
