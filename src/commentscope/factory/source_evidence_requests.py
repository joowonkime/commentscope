"""Candidate-scoped evidence observations; no upstream verdict in model inputs."""
from copy import deepcopy
from commentscope.contracts.perspective_draft import obj, array
from commentscope.factory import source_evidence_graph as g, minimal_claims as mc, minimal_membership as mm
from commentscope.factory.automatic_contract import digest

SYSTEM = '''Observe each candidate against the author's whole ORIGINAL and bound
source graph. Graph units are fallible source-bound evidence, not support votes.
Return exact owned position IDs and directional alignment, without rewriting.
Preserve essential conditions, modality, population, time, world and quantities.
No prior membership verdict is supplied. Parent resolves references only.
Return ALL source-owned reasons/concessions/conditions linked to that position,
not a convenient subset. A reason is not a condition or a core factual premise.
condition_for preserves a qualification; necessary_condition_for asserts a
necessary prerequisite. Keep both in essential_condition_unit_ids without
converting one into the other. Do not invent necessity for ordinary reasons.
dependency_edge_ids select existing SOURCE_EDGES, without regenerating their
spans or relations, to retain local factual/condition requirements; core_required_fact
IDs name direct factual bases for this CORE, never the union of private motives.
Independently inspect ORIGINAL for omitted conditions, reasons or prerequisites,
including when the graph declares zero facts. unknown/unassessed is not pass.
Value/prediction is not verified empirical truth; no external evidence here.
An assertion can have no reasons. Do not invent any to complete the candidate.
issue_codes contains blocking problems; use [] when none. Informational status
codes never override a failed, unknown, unassessed or missing obligation.'''

SCOPED_SYSTEM = SYSTEM + '''
Identify the owned position and all context units needed to resolve its target
and scope. A fact that only identifies what "it" or a named proposal refers to
belongs in reference_unit_ids. Such a unit must occur in the same author's
selected own evidence; it is never a separate claim or fact required to prove
the position. An asserted factual part of the actual core is different and
belongs in position_unit_ids and core_required_fact_unit_ids.
Keep verified elaborations in elaboration_unit_ids. Do not mark an elaboration
as a causal reason or omit a concession that applies through a chain of units.
If an essential qualification, relation or rationale is missing in the graph,
mark candidate_original_coverage fail and identify the issue. That field is
about this candidate's complete support in the whole ORIGINAL. Record issues
that affect the position, its reference units, or its supporting evidence.
An invalid unrelated assertion does not license rewriting or hiding any
element needed by this candidate.'''
SCOPED_BATCH = g.VERSION+'/scoped-candidate-batch-v2'


def scoped(candidates):
    return bool(candidates) and all('qualifications' in c for c in candidates)

def candidate_request(verified, candidates):
    g.validate_verified(verified)
    cs={c['id']:mc.validate_candidate(c) for c in candidates}
    if len(cs)!=len(candidates) or not 1<=len(cs)<=8:raise ValueError('Unique bounded candidate batch required')
    units=verified['proposal']['output']['units'];ids=[u['local_id'] for u in units]
    edges=verified['proposal']['output']['edges'];edge_ids=[e['local_id'] for e in edges if e['relation'] in ('required_premise_for',*g.CONDITION_RELATIONS)]
    fact_ids=[u['local_id'] for u in units if u['kind']=='fact' and u['commitment']=='endorsed' and u['assertion_mode']=='assertion' and u['world']=='actual']
    id_list=lambda:array(g.choice(ids),maximum=len(ids))
    fields=dict(candidate_id=g.choice(sorted(cs)),position_unit_ids=id_list(),
        alignment=g.choice(('supports_core','equivalent','conditional','opposed','unrelated','uncertain')),
        reason_unit_ids=id_list(),concession_unit_ids=id_list(),essential_condition_unit_ids=id_list(),
        dependency_edge_ids=array(g.choice(edge_ids),maximum=len(edge_ids)),core_required_fact_unit_ids=array(g.choice(fact_ids),maximum=len(fact_ids)),
        full_original_coverage=g.choice(g.VERDICTS),ownership=g.choice(g.VERDICTS),scope_preserved=g.choice(g.VERDICTS),
        issue_codes=array(g.choice(g.CODES),maximum=16))
    versioned=scoped(candidates)
    if versioned:
        fields['candidate_original_coverage']=fields.pop('full_original_coverage')
        fields.update(reference_unit_ids=id_list(),elaboration_unit_ids=id_list())
    return mc.request(SCOPED_SYSTEM if versioned else SYSTEM,{'EVIDENCE_PROTOCOL':SCOPED_BATCH if versioned else g.VERSION,
        'ORIGINAL':mc.packet(verified['proposal']['source']),
        'UNITS':deepcopy(units),'SOURCE_EDGES':deepcopy(verified['proposal']['output']['edges']),
        'CANDIDATES':[{'id':cid,**mc.candidate_packet(cs[cid])} for cid in sorted(cs)]},
        obj({'candidates':array(obj(fields),minimum=len(cs),maximum=len(cs))}),8192)


def relevant_inventory(verified, positions):
    edges=verified['proposal']['output']['edges'];active=set(positions)
    for _ in range(33):
        found={e['from_unit'] for e in edges if e['to_unit'] in active and e['relation'] in
               ('reason_for','required_premise_for',*g.CONDITION_RELATIONS,'concession_to','elaborates')}
        if found<=active:break
        active|=found
    return active


def covered(span, evidence):
    end=span['start']
    for ref in sorted(evidence,key=lambda r:r['start']):
        if ref['start']>end:
            break
        end=max(end,ref['end'])
        if end>=span['end']:
            return True
    return False


def bind_candidates(verified, candidates, support_batches, result):
    req=candidate_request(verified,candidates)
    if result.get('errors'):raise ValueError('Failed candidate evidence observation')
    out=result.get('output');g.check(req['schema'],out)
    cs={c['id']:c for c in candidates};source=verified['proposal']['source'];sid=source['id']
    # Receipts must be current independently verified supports, never nominations.
    support={r['candidate_id']:r for r in mm.collect([source],candidates,support_batches) if r['relation']=='supported'}
    if set(support)!=set(cs):raise ValueError('Exact current verified membership required')
    ids=[r['candidate_id'] for r in out['candidates']]
    if sorted(ids)!=sorted(cs):raise ValueError('Every candidate requires one certificate')
    units={u['local_id']:u for u in verified['proposal']['output']['units']};edges=verified['proposal']['output']['edges'];bound=[]
    edge_map={e['local_id']:e for e in edges}
    versioned=scoped(candidates)
    unsafe_units=g.local_unit_holds(verified) if versioned else None
    for row in out['candidates']:
        reasons=[];cid=row['candidate_id'];positions=set(row['position_unit_ids']);active=relevant_inventory(verified,positions)
        extra_fields=('reference_unit_ids','elaboration_unit_ids') if versioned else ()
        for field in ('position_unit_ids','reason_unit_ids','concession_unit_ids','essential_condition_unit_ids','core_required_fact_unit_ids',*extra_fields):
            if len(set(row[field]))!=len(row[field]):raise ValueError('Duplicate candidate evidence unit')
        if len(set(row['dependency_edge_ids']))!=len(row['dependency_edge_ids']):raise ValueError('Duplicate dependency edge selection')
        selected=[deepcopy(edge_map[eid]) for eid in row['dependency_edge_ids']]
        for field,rels in [('reason_unit_ids',('reason_for',)),('concession_unit_ids',('concession_to',)),('essential_condition_unit_ids',g.CONDITION_RELATIONS)]:
            expected={e['from_unit'] for e in edges if e['to_unit'] in active and e['relation'] in rels}
            if set(row[field])!=expected:reasons.append('candidate_inventory_incomplete')
        references=set()
        if versioned:
            references=set(row['reference_unit_ids'])
            aligned_roles=positions|set(row['reason_unit_ids']+row['concession_unit_ids']+
                                        row['essential_condition_unit_ids']+row['core_required_fact_unit_ids'])
            elaborations={e['from_unit'] for e in edges if e['to_unit'] in active and e['relation']=='elaborates'}-aligned_roles
            if set(row['elaboration_unit_ids'])!=elaborations:
                reasons.append('candidate_inventory_incomplete')
            if references&(aligned_roles|elaborations) or any(
                    u['commitment']!='endorsed' or u['assertion_mode']!='assertion'
                    or not all(covered(span,support[cid]['evidence']) for span in u['own_spans'])
                    for lid,u in units.items() if lid in references):
                reasons.append('candidate_reference_unverified')
        expected_edges=[e for e in edges if e['to_unit'] in active and e['relation'] in ('required_premise_for',*g.CONDITION_RELATIONS)]
        if {e['local_id'] for e in expected_edges}!=set(row['dependency_edge_ids']):reasons.append('candidate_dependencies_changed')
        if any(units[u]['kind']!='fact' or units[u]['commitment']!='endorsed' or units[u]['assertion_mode']!='assertion'
               or units[u]['world']!='actual'
               for u in row['core_required_fact_unit_ids']):reasons.append('invalid_core_factual_basis')
        if not set(row['core_required_fact_unit_ids'])<=positions:reasons.append('personal_premise_promoted_to_core')
        if set(row['core_required_fact_unit_ids'])!={u for u in positions if units[u]['kind']=='fact'}:reasons.append('direct_core_fact_omitted')
        if any(units[u]['commitment']!='endorsed' or units[u]['assertion_mode']!='assertion'
               for u in row['reason_unit_ids']+row['concession_unit_ids']):reasons.append('reason_ownership_unverified')
        if (not positions or any(units[u]['commitment']!='endorsed' or units[u]['assertion_mode']!='assertion' for u in positions)
                or row['alignment'] not in ('supports_core','equivalent')):reasons.append('owned_position_unverified')
        coverage='candidate_original_coverage' if versioned else 'full_original_coverage'
        if any(row[k]!='pass' for k in (coverage,'ownership','scope_preserved')) or g.blocking_codes(row['issue_codes']):reasons.append('candidate_obligations_unresolved')
        if verified['status']!='complete' and (unsafe_units is None
                or unsafe_units&relevant_inventory(verified,active|references)):
            reasons.append('source_graph_unresolved')
        bound.append(dict(artifact_kind=g.VERSION+('/scoped-candidate-certificate-v2' if versioned else '/candidate-certificate'),
            candidate=deepcopy(cs[cid]),source_id=sid,
            verified_sha256=digest(verified),request_sha256=digest(req),output={**deepcopy(row),'dependency_edges':selected},
            status='held' if reasons else 'eligible_for_existing_checks',hold_reasons=sorted(set(reasons)),semantic_approval=False))
    return dict(artifact_kind=SCOPED_BATCH if versioned else g.VERSION+'/candidate-batch',verified=deepcopy(verified),candidates=deepcopy(candidates),
        support_batches=deepcopy(support_batches),response=deepcopy(out),request_sha256=digest(req),certificates=bound)


def validate_batch(value):
    if bind_candidates(value['verified'],value['candidates'],value['support_batches'],{'output':value['response']})!=value:
        raise ValueError('Candidate evidence provenance changed')
    return value
