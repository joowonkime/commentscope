"""Explicit new-protocol lowering into the existing Agent data interface.

New receipts stay new receipts. All-source completeness and required facts are
retained; inability to represent a literal claim holds the source, never trims it.
"""
from copy import deepcopy
from commentscope.factory import source_evidence_graph as g, source_evidence_requests as requests
from commentscope.factory import source_arguments as sa, argument_observations as obs
from commentscope.factory.automatic_contract import digest

VERSION=g.VERSION+'/arguments'
AUDIT=g.VERSION+'/audit'


def lower(batches):
    if not batches:raise ValueError('Complete candidate evidence batches required')
    for b in batches:requests.validate_batch(b)
    verified=batches[0]['verified'];source=verified['proposal']['source'];env=verified['proposal']['envelope']
    if any(b['verified']!=verified for b in batches):raise ValueError('Mixed source evidence graphs')
    certificates=[c for b in batches for c in b['certificates']];ids=[c['candidate']['id'] for c in certificates]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate candidate certificate')
    units={u['local_id']:u for u in verified['proposal']['output']['units']};edges=verified['proposal']['output']['edges']
    holds=list(verified['issues'])+[r for c in certificates for r in c['hold_reasons']]
    lowered=[]
    def text(refs):
        return '; '.join(env['source']['text'][r['start']:r['end']] for r in g.canonical_refs(refs))
    for lid,u in units.items():
        try:literal=g.literal(env,u['own_spans'])
        except ValueError:holds.append('unrepresentable_hold');literal=''
        related=[c for c in certificates if lid in requests.relevant_inventory(verified,c['output']['position_unit_ids'])]
        candidate_ids=[c['candidate']['id'] for c in related]
        roles={}
        for c in related:
            row=c['output'];cid=c['candidate']['id']
            roles[cid]=('core_restatement' if lid in row['position_unit_ids'] else
                'reason' if lid in row['reason_unit_ids'] else
                'concession' if lid in row['concession_unit_ids'] else
                'essential_condition' if lid in row['essential_condition_unit_ids'] else 'factual_premise')
        conditions=[units[e['from_unit']] for e in edges if e['to_unit']==lid and e['relation']=='necessary_condition_for']
        if any(any(e['to_unit']==c['local_id'] and e['relation']=='necessary_condition_for' for e in edges) for c in conditions):
            holds.append('unrepresentable_hold')  # Existing flat runtime scope cannot express nested qualification.
        scope=dict(entity=text(u['scope']['subject_refs']) or literal,
            time=text(u['scope']['time_refs']),conditions='; '.join(text(c['own_spans']) for c in conditions))
        # Qualifier/world/negation spans outside the chosen contiguous claim
        # cannot silently disappear into an unexposed internal graph.
        for field in ('polarity_refs','modality_refs','quantifier_refs','population_refs','world_refs','comparison_refs','change_refs','qualifier_refs'):
            if any(not any(s['start']<=r['start'] and r['end']<=s['end'] for s in u['own_spans']) for r in u['scope'][field]):
                holds.append('unrepresentable_hold')
        annotation=u['assertion_mode']=='conditional_antecedent'
        context=u['commitment']!='endorsed' or u['assertion_mode'] in ('quoted_content','question','non_assertive') or u['kind']=='not_applicable'
        if u['kind']=='fact' and not annotation and not context and u['world']!='actual':
            holds.append('nonactual_fact_unrepresentable')
        if (not literal.strip() or len(literal)>600 or any(len(v)>600 for v in scope.values())):
            holds.append('unrepresentable_hold')
        factual=[e['from_unit'] for e in edges if e['to_unit']==lid and e['relation']=='required_premise_for']
        if any(units[d]['kind']!='fact' or units[d]['assertion_mode']!='assertion' or units[d]['commitment']!='endorsed'
               or units[d]['world']!='actual' for d in factual):
            holds.append('required_premise_not_fact')
        lowered.append(dict(local_id=lid,id='SE'+digest([VERSION,digest(verified),lid]),
            text=literal,kind='uncertain' if annotation or context else u['kind'],scope=scope,
            role=next(iter(roles.values()),'additional_position'),candidate_roles=roles,
            candidate_ids=[] if context else sorted(candidate_ids),source_id=source['id'],source_sha256=digest(source),
            authorship='asserted_or_endorsed' if u['commitment']=='endorsed' else 'not_asserted',
            assertion_mode=u['assertion_mode'],epistemic=u['epistemic'],world=u['world'],
            runtime_exposure='scope_annotation_only' if annotation or context else 'claim',
            evidence=[dict(start=r['start'],end=r['end'],text=source['text'][r['start']:r['end']]) for r in u['own_spans']],
            requires=sorted(set(factual)),core_requires_for=sorted(c['candidate']['id'] for c in certificates if lid in c['output']['core_required_fact_unit_ids'])))
    language=verified['observation']['output']['source_language']
    if language=='unknown':holds.append('source_language_unresolved')
    return dict(artifact_kind=VERSION,source=deepcopy(source),candidate_ids=sorted(ids),source_language=language if language=='en' else 'other' if language!='unknown' else 'uncertain',
        status='unresolved' if holds else 'complete',units=lowered,additional_passes=0,
        dependency_status='unresolved' if holds else 'complete',hold_reasons=sorted(set(holds)),
        evidence_batches=deepcopy(batches),semantic_approval=False)


def validate(record):
    if lower(record['evidence_batches'])!=record:raise ValueError('Source evidence lowering changed')
    return record


def audit(records, cores, core_checks):
    from commentscope.factory import argument_observations
    for r in records:validate(r)
    cs={c['candidate']['id']:sa.validate_core(c) for c in cores}
    checks={c['core_id']:c for c in core_checks}
    if len(checks)!=len(core_checks) or set(checks)!=set(cs):raise ValueError('All current core fidelity observations required')
    for cid,c in checks.items():
        if argument_observations.bind_core(cs[cid],{'output':c['response']},protocol=c['artifact_kind'])!=c:
            raise ValueError('Core fidelity provenance changed')
    decisions=[];tasks=[]
    for r in records:
        good=r['status']=='complete'
        for u in r['units']:
            tasks.append(dict(task_id=u['id'],source_id=r['source']['id'],kind='unit'))
            decisions.append(dict(task_id=u['id'],verdict='supported' if good else 'uncertain'))
        key='AC'+digest(r);tasks.append(dict(task_id=key,source_id=r['source']['id'],kind='coverage'))
        decisions.append(dict(task_id=key,verdict='supported' if good else 'uncertain'))
    return dict(artifact_kind=AUDIT,records_sha256=digest(records),cores_sha256=digest(cores),
        tasks=tasks,core_checks=deepcopy(core_checks),output={'decisions':decisions},semantic_approval=False)


def verdicts(records, cores, artifact):
    if audit(records,cores,artifact['core_checks'])!=artifact:raise ValueError('Source evidence audit provenance changed')
    result={r['task_id']:r['verdict'] for r in artifact['output']['decisions']}
    result.update({obs.core_key(c['core_id']):'supported' if c['passed'] else 'unsupported' for c in artifact['core_checks']})
    return result


def process(snapshot, candidates, memberships, execution, cores, core_checks):
    from commentscope.factory.pipeline_stages import ArgumentResult
    rows=[r for b in memberships for r in b['memberships'] if r['relation']=='supported']
    cidset={c['id'] for c in candidates};supporting=sorted({r['source_id'] for r in rows if r['candidate_id'] in cidset})
    records=[]
    for sid in supporting:
        source=execution.registry[sid];needed=[c for c in candidates if any(r['source_id']==sid and r['candidate_id']==c['id'] for r in rows)]
        env=g.envelope(source,snapshot_id=snapshot.snapshot_id,snapshot_sha256=digest(snapshot.to_dict()))
        proposals=execution.work('source-evidence-proposal',[env],lambda a:g.proposal_request(a[0]),lambda a,r:g.bind_proposal(a[0],r),1)
        if not proposals:continue
        proposal=proposals[0]
        execution.save('source-evidence-workloads/'+sid,g.audit_workload(proposal,candidate_count=len(needed)))
        observations=execution.work('source-evidence-observation',[proposal],lambda a:g.observation_request(a[0]),lambda a,r:g.bind_observation(a[0],r),1)
        if not observations:continue
        verified=g.verify(proposal,observations[0]);execution.save('source-evidence-graphs/'+sid,verified)
        if verified['status']!='complete':
            execution.holds.append(dict(stage='source-evidence-observation',source_id=sid,
                reason='source_graph_unresolved_no_retry',issues=verified['issues']))
            continue
        batches=[]
        scoped=[b for b in memberships if any(r['source_id']==sid and r['candidate_id'] in {c['id'] for c in needed} for r in b['memberships'])]
        for start in range(0,len(needed),8):
            group=needed[start:start+8]
            batches.extend(execution.work('source-evidence-candidates',[group],lambda a:requests.candidate_request(verified,a[0]),
                lambda a,r:requests.bind_candidates(verified,a[0],scoped,r),1))
        if sum(len(b['candidates']) for b in batches)!=len(needed):continue
        record=lower(batches);records.append(record);execution.save('source-evidence-arguments/'+sid,record)
    # Include every adaptable core; missing source records must remain visible
    # to the existing Compiler and cannot be filled by a successful subset.
    artifacts=[audit(records,cores,core_checks)]
    execution.save('arguments',records);execution.save('cores',cores);execution.save('argument-audits',artifacts)
    return ArgumentResult(records,cores,artifacts)
