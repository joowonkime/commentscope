"""Literal named-policy anchors for the plain, reference-free admission path.

The full topic/acronym must be bound by video metadata. Generic partial names,
pronouns and the video title alone need a separate reference interpretation;
they cannot borrow that interpretation from a classifier's positive score.
This is a necessary target guard, never proof of endorsement or policy fidelity.
"""
from copy import deepcopy
import re
from commentscope.factory import explicit_discourse as ed,minimal_claims as mc
from commentscope.factory import policy_stance_hypotheses as stance
from commentscope.factory.automatic_contract import digest

VERSION='literal-own-named-policy-target-20261023-v1'


def anchors(source,topic,alias,*,start=0,end=None):
    stance.hypotheses([source],topic,alias)
    text=source['text'];end=len(text) if end is None else end
    if type(start) is not int or type(end) is not int or not 0<=start<=end<=len(text):
        raise ValueError('Exact own target range required')
    result=[]
    for name in [topic,alias]:
        pattern=r'(?<!\w)'+r'\s+'.join(re.escape(w) for w in name.split())+r'(?!\w)'
        for match in re.finditer(pattern,text[start:end],re.I):
            a=start+match.start();b=start+match.end()
            if any(r['start']==a and r['end']==b for r in result):continue
            result.append({'start':a,'end':b,'text':text[a:b],'metadata_name':name})
    return sorted(result,key=lambda r:(r['start'],r['end']))


def bind(graph,node,candidate,topic,alias):
    ed.validate(graph);mc.validate_candidate(candidate)
    if node not in graph['nodes']:raise ValueError('Exact immutable own target node required')
    hypotheses=stance.hypotheses([graph['source']],topic,alias)
    if not any(c['id']==candidate['id'] and c['text']==candidate['text'] for c in hypotheses):
        raise ValueError('Candidate must be the exact metadata-bound policy hypothesis')
    matches=anchors(graph['source'],topic,alias,start=node['span']['start'],end=node['span']['end'])
    return {'artifact_kind':VERSION,'graph_sha256':digest(graph),'node_id':node['id'],
        'candidate_sha256':digest(candidate),'topic':topic,'alias':alias,'anchors':deepcopy(matches),
        'passed':node['kind']=='statement' and bool(matches),'reference_interpretation_supplied':False,
        'semantic_approval':False}


def validate(graph,node,candidate,record):
    binder=bind_general if record.get('artifact_kind')==GENERAL else bind
    if binder(graph,node,candidate,record['topic'],record['alias'])!=record:
        raise ValueError('Own named-policy target binding changed')
    return record


GENERAL='literal-own-named-policy-target-general-20261023-v1'


def bind_general(graph,node,candidate,topic,alias):
    """Bind a named common hypothesis without restricting its predicate/valence.

    Literal names only establish the common object. Neither a matching name nor
    a nomination proves author commitment, the predicate, scope or truth.
    Historical two-template records retain their exact original contract.
    """
    ed.validate(graph);mc.validate_candidate(candidate)
    if node not in graph['nodes']:raise ValueError('Exact immutable own target node required')
    if not anchors({**graph['source'],'text':candidate['text']},topic,alias):
        raise ValueError('Common hypothesis must name the exact metadata-bound policy')
    matches=anchors(graph['source'],topic,alias,start=node['span']['start'],end=node['span']['end'])
    return {'artifact_kind':GENERAL,'graph_sha256':digest(graph),'node_id':node['id'],
        'candidate_sha256':digest(candidate),'topic':topic,'alias':alias,'anchors':deepcopy(matches),
        'passed':node['kind']=='statement' and bool(matches),'reference_interpretation_supplied':False,
        'semantic_approval':False}
