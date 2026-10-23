"""Reject exact source reference cycles without repairing semantic outputs.

Only addressed occurrences in the selected assertion form this graph. No cycle
does not establish semantic closure, and broader indirect links are not proved.
"""
from copy import deepcopy

from commentscope.factory import authored_reference as ar
from commentscope.factory.automatic_contract import digest

VERSION = 'addressed-reference-cycle-guard-20261018-v1'


def _cycles(edges):
    done = set(); result = []
    for start in sorted(edges):
        path = []; positions = {}; node = start
        while node in edges and node not in done and node not in positions:
            positions[node] = len(path); path.append(node); node = edges[node]
        if node in positions: result.append(sorted(path[positions[node]:]))
        done.update(path)
    return sorted(result)


def bind(proof):
    ar.validate(proof)
    spans = {(m['span']['start'], m['span']['end']): m['id']
             for m in ar.inventory(proof['candidate'], proof['origin'])}
    edges = {}
    for link in proof['links']:
        proposal = link['proposal']; context = proposal['context']
        if context and context['origin']=='source':
            span = context['span']; target = spans.get((span['start'], span['end']))
            if target is not None: edges[proposal['mention']['id']] = target
    cycles = _cycles(edges)
    guards = ([] if proof['passed'] else ['upstream_proposition_unapproved'])
    guards += ['reference_cycle:'+','.join(cycle) for cycle in cycles]
    return {'artifact_kind': VERSION, 'proof': deepcopy(proof), 'proof_sha256': digest(proof),
            'edges': edges, 'cycles': cycles, 'guards': guards, 'passed': not guards,
            'scope': 'exact_source_reference_occurrences_only',
            'semantic_approval': False, 'factual_verification': False}


def validate(record):
    if record.get('artifact_kind')!=VERSION or bind(record['proof']) != record:
        raise ValueError('Addressed reference cycle proof changed')
    return record
