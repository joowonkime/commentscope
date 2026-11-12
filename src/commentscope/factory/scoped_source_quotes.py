"""Display an audited clause with its exact source qualification fragments.

No paraphrase, reference resolution, sibling assertion or parent text is added.
The graph and candidate audit remain responsible for semantic attachment.
"""
from copy import deepcopy
from commentscope.factory import source_evidence_graph as g

VERSION = 'scoped-source-quotes-20261112-v1'
QUALIFIERS = ('polarity_refs','modality_refs','quantifier_refs','population_refs',
              'world_refs','comparison_refs','change_refs','qualifier_refs')
OMISSION = ' […] '


def quote(env, unit):
    # A discontinuous assertion still requires an expressible representation.
    literal = g.literal(env, unit['own_spans'])
    source = env['source'];text = source['text'];own = unit['own_spans'][0]
    qualifiers = {field:deepcopy(unit['scope'][field]) for field in QUALIFIERS}
    refs = [own]
    for values in qualifiers.values():
        g.spans(env, values)  # Deliberately forbids parent evidence.
        refs.extend(values)
    outside = any(not own['start'] <= r['start'] < r['end'] <= own['end'] for r in refs)
    if outside and unit['kind'] not in ('value','prediction'):
        raise ValueError('Discontinuous factual qualification requires its own verifier')
    fragments = []
    for ref in g.canonical_refs(refs):
        if fragments and (ref['start'] <= fragments[-1]['end']
                          or text[fragments[-1]['end']:ref['start']].isspace()):
            fragments[-1]['end'] = max(fragments[-1]['end'], ref['end'])
        else:fragments.append(deepcopy(ref))
    evidence = [dict(start=r['start'],end=r['end'],text=text[r['start']:r['end']]) for r in fragments]
    rendered = OMISSION.join(e['text'] for e in evidence) if outside else literal
    if not rendered.strip() or len(rendered)>600:
        raise ValueError('Source quote cannot fit runtime claim capacity')
    return dict(artifact_kind=VERSION,own_spans=deepcopy(unit['own_spans']),
                qualifier_refs=qualifiers,text=rendered,evidence=evidence)
