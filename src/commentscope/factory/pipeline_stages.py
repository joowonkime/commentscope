"""Explicit stages of candidate discovery through grounded Agent assembly.

Stage results preserve source identities and versioned evidence. Independent
review labels stay outside model inputs.
"""
from copy import deepcopy
from dataclasses import dataclass

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import candidate_consolidation as cc
from commentscope.factory import source_arguments as sa, minimal_agents as ma
from commentscope.factory import fact_checks, nli_fact_records, owned_arguments as oa
from commentscope.factory import shared_claims, shared_owned_positions, contextual_runtime
from commentscope.factory.automatic_contract import digest
from commentscope.factory import argument_observations
from commentscope.factory import compact_claims
from commentscope.factory import owner_observations
from commentscope.factory import assertion_counterexamples


@dataclass
class DiscoveryResult:
    records: list
    candidates: list
    engine: object
    shared_discovery: list
    interpretation_reviews: list | None = None
    interpretation_admission: dict | None = None


@dataclass
class MembershipResult:
    candidates: list
    memberships: list
    nomination_batches: list
    consolidation: object
    equivalences: list


@dataclass
class ArgumentResult:
    arguments: list
    cores: list
    audits: list


def discover(sources, vectors, execution, *, discovery_mode, shared_records):
    """Source registry/embeddings -> proposals, retaining each mode's provenance."""
    runner, inspect = execution.runner, execution.inspect
    work, save = execution.work, execution.save
    membership_mode = execution.membership_mode
    verification_contract = execution.verification_contract
    engine=None;shared_discovery=[]
    if discovery_mode=='contextual':
        from commentscope.factory.contextual_engine import Engine
        engine=Engine(sources,runner,inspect,save=lambda name,value:save('contextual/'+name,value),raw_membership=membership_mode=='raw',verification_contract=verification_contract)
        engine.discover();records=engine.records
    elif discovery_mode=='literal':
        from commentscope.factory import literal_discovery
        records=literal_discovery.discover(sources,work,save)
    elif discovery_mode=='shared':
        if shared_records is not None:
            shared_discovery=shared_claims.for_scope(shared_records,sources)
        else:
            for group in shared_claims.batches(sources,vectors):
                shared_discovery.extend(work('shared-discovery',group,
                    lambda rows:shared_claims.request(rows,version=shared_claims.COMMON),
                    lambda rows,result:shared_claims.bind(rows,result,version=shared_claims.COMMON),
                    shared_claims.BATCH_SIZE,minimum=2))
        records=[]  # A common proposal is not a per-source extraction/completeness approval.
    elif getattr(execution, 'extraction_protocol', None) in compact_claims.VERSIONS:
        records = compact_claims.discover(sources, work, protocol=execution.extraction_protocol)
    else:records = mc.extract_independently(sources, work)
    save('extractions', records)
    reviews = None; admission = None
    if getattr(execution, 'review_interpretations', False):
        from commentscope.factory import source_interpretation
        protocol = execution.source_review_protocol or source_interpretation.REVIEW
        reviews = work('source-interpretation-review', source_interpretation.review_tasks(records),
            lambda group: source_interpretation.review_request(group[0]['interpretations'], protocol=protocol),
            lambda group, result: source_interpretation.bind_review(group[0]['interpretations'], result,
                                                                   protocol=protocol), 1)
        admission = source_interpretation.nominate(records, reviews, protocol=protocol)
        candidates = admission['candidates']
        save('source-interpretation-reviews', reviews)
        save('source-interpretation-admission', admission)
    elif discovery_mode=='shared':
        candidates=shared_claims.candidates(shared_discovery);save('shared-discovery',shared_discovery)
    else:candidates = mc.candidates(records)
    save('initial-candidates', candidates)
    return DiscoveryResult(records, candidates, engine, shared_discovery, reviews, admission)


def memberships(sources, ids, candidates, records, vectors, embed, execution, *,
                discovery_mode, shared_memberships, source_entailment_required):
    """Proposals -> final wording, verified support and explicit merge evidence."""
    engine, verification_contract = execution.engine, execution.verification_contract
    work, qualify, judge = execution.work, execution.qualify, execution.judge
    save, SCHEDULE = execution.save, execution.schedule
    nominations = [{'source_id': sid, 'candidate_id': c['id']} for c in candidates for sid in sorted(c['nominees'])]
    nomination_batches = ([] if shared_memberships is not None else
        [engine.nominations] if engine is not None else judge('nomination', nominations, candidates))
    save('nomination-batches', nomination_batches)
    if shared_memberships is not None:
        from commentscope.factory import source_entailment
        def exact_contract(batch):
            if batch.get('artifact_kind')==source_entailment.VERSION+'-batch':
                return batch.get('base_verification_contract')==verification_contract
            return not source_entailment_required and batch.get('artifact_kind')==verification_contract+'-batch'
        if not isinstance(shared_memberships,list) or any(not exact_contract(b) for b in shared_memberships):
            raise ValueError('Staged memberships require the exact verified contract')
        mm.collect(sources,candidates,shared_memberships)
        memberships=deepcopy(shared_memberships);equivalences=[];merged=None
    elif candidates:
        candidate_vectors = embed('candidates', {c['id']: engine.embedding_text(c) if engine is not None else c['text'] for c in candidates})
        if set(candidate_vectors) != {c['id'] for c in candidates}: raise ValueError('Candidate embeddings changed')
        support = mm.collect(sources, candidates, nomination_batches)
        confirmed = {r['candidate_id'] for r in support if r['relation'] == 'supported'}
        # Shared discovery already proposes common positions. Keep exact-text
        # unions only; do not run the old full-proposition equivalence stage.
        pairs = cc.nearest_pairs({cid: candidate_vectors[cid] for cid in confirmed}) if confirmed and discovery_mode!='shared' else []
        equivalence_protocol = (cc.ASSERTION_ONLY if discovery_mode == 'literal'
            or getattr(execution, 'extraction_protocol', None) in compact_claims.VERSIONS else None)
        bilateral = getattr(execution, 'extraction_protocol', None) in compact_claims.WORLD_CONTEXT_PROTOCOLS
        if bilateral: equivalence_protocol = cc.BILATERAL
        equivalences = [] if engine is not None else work('equivalence', pairs,
                            lambda group: cc.equivalence_request(sources, candidates, nomination_batches, group,
                                                                  protocol=equivalence_protocol),
                            lambda group, result: cc.bind(sources, candidates, nomination_batches, group, result,
                                                          protocol=equivalence_protocol), SCHEDULE['equivalence_pairs'])
        index={c['id']:c for c in candidates};qualified_equivalences=[]
        for record in equivalences:
            qualifications=[]; assertion_checks=[]
            for row in record['relations']:
                if row['model_relation']!='equivalent':continue
                for left,right in ((row['a'],row['b']),(row['b'],row['a'])):
                    source={'id':left,'text':index[left]['text'],'parent':None}
                    assessment=qualify(source,index[right])
                    if assessment is not None:qualifications.append({'from_candidate_id':left,
                        'to_candidate_id':right,'assessment':assessment})
                matching = [q for q in qualifications if {q['from_candidate_id'], q['to_candidate_id']} == {row['a'], row['b']}]
                if bilateral and len(matching) == 2 and all(q['assessment']['passed'] for q in matching):
                    assertion_checks.extend(work('assertion-counterexample', [{'a': row['a'], 'b': row['b']}],
                        lambda group: assertion_counterexamples.request(index[group[0]['a']]['text'], index[group[0]['b']]['text']),
                        lambda group, result: {**group[0], 'check': assertion_counterexamples.bind(
                            index[group[0]['a']]['text'], index[group[0]['b']]['text'], result)}, 1))
            bound=cc.bind(sources,candidates,nomination_batches,record['pairs'],{'output':record['output']},qualifications,
                          protocol=record.get('protocol'), assertion_checks=assertion_checks)
            qualified_equivalences.append(bound);save('bound/equivalence-qualified-'+digest(bound)[:20],bound)
        equivalences=engine.equivalences(pairs) if engine is not None else qualified_equivalences
        representative_scopes = ({c['id']:contextual_runtime.bind(c,engine.scope(c)) for c in candidates
                                  if c['id'] in engine.scopes} if engine is not None else None)
        merged = cc.consolidate(sources,candidates,nomination_batches,equivalences,runtime_scopes=representative_scopes)
        candidates = merged['candidates']; save('consolidation', merged); save('equivalences', equivalences)
        # Keep equivalent wording searchable; only the canonical wording is
        # judged. Reusing a retrieval vector never transfers a source vote.
        final_vectors = {c['id']: candidate_vectors[c['id']] for c in candidates}
        retrieval_index={'vectors':candidate_vectors,'alias_to_final':merged['alias_to_final']}
        save('membership-retrieval',{'version':cc.ALIAS_RETRIEVAL,'alias_to_final':merged['alias_to_final'],
            'candidate_vectors_sha256':digest(candidate_vectors),'source_vectors_sha256':digest(vectors),'semantic_approval':False})
        first = cc.membership_pairs(sources, candidates, vectors, final_vectors,retrieval_index=retrieval_index)
        memberships = judge('membership-initial', first, candidates)
        statuses = {r['source']['id']: r['status'] for r in records}
        statuses.update({sid: 'unresolved' for sid in ids if sid not in statuses})
        extra_pairs = cc.membership_pairs(sources, candidates, vectors, final_vectors,
                                         previous=memberships, statuses=statuses, expand=True,retrieval_index=retrieval_index)
        # A failed initial batch must not be silently retried as expansion.
        attempted = {(p['source_id'], p['candidate_id']) for p in first}
        extra_pairs = [p for p in extra_pairs if (p['source_id'], p['candidate_id']) not in attempted]
        memberships.extend(judge('membership-expanded', extra_pairs, candidates))
    else:
        memberships = []; equivalences = []; merged = None
    save('candidates', candidates); save('memberships', memberships)
    return MembershipResult(candidates, memberships, nomination_batches, merged, equivalences)


def arguments(snapshot, candidates, memberships, discourse, execution, *, discovery_mode):
    """Verified supports -> source-owned arguments, cores and audit records."""
    engine = execution.engine
    work, qualify, save = execution.work, execution.qualify, execution.save
    holds, errors = execution.holds, execution.errors
    mapped = mm.assemble_map(snapshot, candidates, memberships); save('map', mapped)
    eligible_ids = {p['id'] for p in mapped['opinion_map']['perspectives'] if p['minimum_support_met']}
    eligible = [c for c in candidates if c['id'] in eligible_ids]
    members = {p['id']: p['supported_canonical_ids'] for p in mapped['opinion_map']['perspectives']}
    runtime_scopes = {c['id']: contextual_runtime.bind(c,engine.scope(c)) for c in eligible
                      if engine is not None and c['id'] in engine.scopes}
    save('contextual-runtime-scopes',runtime_scopes)
    cores = work('core', eligible, lambda group: oa.core_request(group[0],runtime_scopes.get(group[0]['id'])),
                 lambda group, result: oa.bind_core(group[0],result,runtime_scopes.get(group[0]['id'])), 1)
    # A held core remains held in the map. It cannot contaminate the separate
    # argument declaration for a usable core supported by the same source.
    adaptable_ids = {r['candidate']['id'] for r in cores if not r.get('hold_reasons') and r['output']['kind']!='uncertain'}
    eligible = [c for c in eligible if c['id'] in adaptable_ids]
    eligible_ids = adaptable_ids
    observed = all('meaning_context' not in c['candidate'] for c in cores)
    split = observed and execution.extraction_protocol in compact_claims.INDEPENDENT_CONTEXT
    core_protocol = argument_observations.CORE_CODED if split else argument_observations.CORE_VERSION
    core_checks = (work('core-fidelity', [c for c in cores if c['candidate']['id'] in adaptable_ids],
                       lambda group: argument_observations.core_request(group[0], protocol=core_protocol),
                       lambda group, result: argument_observations.bind_core(group[0], result, protocol=core_protocol), 1)
                   if observed else [])
    save('core-fidelity-checks', core_checks)
    supporting = sorted({sid for cid in eligible_ids for sid in members[cid]})
    arguments = []
    for sid in supporting:
        graph=discourse[sid]
        needed=[c for c in eligible if sid in members[c['id']]]
        needed_ids={c['id'] for c in needed}
        batches=[b for b in memberships if any(r['source_id']==sid and r['candidate_id'] in needed_ids
            and r['relation']=='supported' for r in b['memberships'])]
        from commentscope.factory import source_entailment
        batches=[source_entailment.for_source(b,sid,needed_ids)
                 if b.get('artifact_kind')==source_entailment.VERSION+'-batch' else b for b in batches]
        # Literal units must remain intact. Oversized text is retained in the
        # source graph, with an explicit hold; never truncate it into a claim.
        if any(len(n['span']['text'])>600 for n in graph['nodes']):
            holds.append({'stage':'owned-arguments','source_id':sid,'reason':'literal_node_exceeds_claim_capacity'})
            continue
        metadata=work('argument-node-metadata',graph['nodes'],lambda group:oa.metadata_request(graph,group[0]),
            lambda group,result:oa.bind_metadata(graph,group[0],result),1)
        save('argument-node-metadata/'+sid,metadata)
        if len(metadata)!=len(graph['nodes']):continue
        typed={m['node_id']:m for m in metadata};alignments=[]
        for node in graph['nodes']:
            if node['kind']!='statement' or typed[node['id']]['output']['authorship']!='asserted_or_endorsed':continue
            for candidate in needed:
                if discovery_mode=='shared':
                    alignments.extend(work('shared-owned-position',[candidate],
                        lambda group:shared_owned_positions.request(graph,node,group[0]),
                        lambda group,result:shared_owned_positions.bind(graph,node,group[0],result),1))
                    continue
                rows=work('argument-position-alignment',[candidate],lambda group:oa.alignment_request(graph,node,group[0],runtime_scopes.get(group[0]['id'])),
                    lambda group,result:oa.bind_alignment(graph,node,group[0],result,runtime_scope=runtime_scopes.get(group[0]['id'])),1)
                if not rows:continue
                row=rows[0];checks=[]
                if row['output']['relation']=='equivalent':
                    for source,target in (({'id':node['id'],'text':node['span']['text'],'parent':None},candidate),
                        ({'id':candidate['id'],'text':candidate['text'],'parent':None},{'text':node['span']['text']})):
                        check=qualify(source,target)
                        if check is None:break
                        checks.append(check)
                alignments.append(oa.bind_alignment(graph,node,candidate,{'output':row['output']},checks,runtime_scopes.get(candidate['id'])))
        save('argument-position-alignments/'+sid,alignments)
        try:arguments.append(oa.declare(graph,needed,batches,metadata,alignments))
        except (ValueError,KeyError,TypeError) as exc:
            error={'stage':'owned-arguments','source_id':sid,'exception':type(exc).__name__,'message':str(exc)}
            errors.append(error);save('errors/owned-arguments-'+sid,error)
    save('argument-extractions', arguments)
    no_facts = [r for r in arguments if sa.link_request(r) is None]
    with_facts = [r for r in arguments if sa.link_request(r) is not None]
    linked = work('argument-dependencies', with_facts, lambda group: sa.link_request(group[0]),
                  lambda group, result: sa.bind_links(group[0],result), 1)
    arguments = sorted([*(sa.bind_links(r) for r in no_facts), *linked], key=lambda r:r['source']['id'])
    save('arguments', arguments); save('cores', cores)
    tasks = sa.audit_tasks(arguments, cores)
    typed=getattr(execution,'argument_audit_protocol',None)==argument_observations.TYPED_CHAT
    owner_protocol=owner_observations.SOURCE_BOUND if typed else owner_observations.VERSION
    owner_checks = work('argument-owner', owner_observations.tasks(arguments, cores, tasks,protocol=owner_protocol),
                        lambda group: owner_observations.request(group[0]),
                        lambda group, result: owner_observations.bind(group[0], result), 1) if split else []
    if split: save('argument-owner-checks', owner_checks)
    protocol = sa.SPLIT_AUDIT if split else sa.OBSERVED_AUDIT if observed else sa.ADDRESSED_AUDIT
    dependency_checks=[]
    if getattr(execution,'argument_audit_protocol',None):
        from commentscope.factory import argument_dependencies as deps
        from commentscope.providers import openrouter_decisions as decisions
        if not split:raise ValueError('Typed dependencies require split source audits')
        protocol=execution.argument_audit_protocol
        chat=protocol in (argument_observations.CHAT_SPLIT,argument_observations.TYPED_CHAT)
        for record in arguments:
            for task in deps.tasks(record,cores,typed=typed):
                try:requests=deps.chat_requests(task) if chat else deps.requests(task)
                except ValueError:
                    holds.append({'stage':'argument-dependency','source_id':record['source']['id'],
                                  'reason':'complete_dependency_input_exceeds_capacity'})
                    continue
                if chat:
                    from commentscope.providers.remote_verification import SOL
                    responses=[execution.runner.call('argument-dependency-'+digest(p)[:20],p) for p in requests]
                    dependency_checks.append(deps.bind_chat(task,responses,SOL))
                else:
                    responses=[execution.runner.decide('argument-dependency-'+decisions.wire_sha256(p,decisions.DEPLOYMENT)[:20],p)
                               for p in requests]
                    dependency_checks.append(deps.bind(task,responses))
        save('argument-dependency-checks',dependency_checks)
    audit_groups = [(arguments, cores, tasks, core_checks, owner_checks)]
    if split:
        # Close each original before hashing/replaying its audit. Rebuilding
        # every author's declarations per unit grows quadratically with corpus
        # size. Model input already contains only this original: keep its exact
        # request while binding just the current source and its relevant cores.
        audit_groups = []
        for record in arguments:
            sid = record['source']['id']; cids = set(record['candidate_ids'])
            audit_groups.append(([record], [c for c in cores if c['candidate']['id'] in cids],
                [t for t in tasks if t['source_id'] == sid],
                [c for c in core_checks if c['core_id'] in cids],
                [c for c in owner_checks if c['task']['source']['id'] == sid]))
    audits = []
    for scoped_records, scoped_cores, scoped_tasks, scoped_checks, scoped_owners in audit_groups:
        dependencies=[c for c in dependency_checks if c['task']['source_id'] in {r['source']['id'] for r in scoped_records}]
        if protocol in argument_observations.GRAPH_SPLITS:
            from commentscope.factory import argument_dependencies as deps
            try:deps.select(scoped_records,scoped_cores,scoped_tasks,dependencies,typed=typed)
            except ValueError:
                holds.append({'stage':'argument-audit','source_ids':[r['source']['id'] for r in scoped_records],
                              'reason':'incomplete_dependency_observations'})
                continue
        audits.extend(work('argument-audit', scoped_tasks,
            lambda group: sa.audit_request(scoped_records, scoped_cores, group,
                                          protocol=protocol, core_checks=scoped_checks),
            lambda group, result: sa.bind_audit(scoped_records, scoped_cores, group, result,
                protocol=protocol, core_checks=scoped_checks, owner_checks=scoped_owners, dependency_checks=dependencies), 1))
    save('argument-audits', audits)
    return ArgumentResult(arguments, cores, audits)


def compile_agents(snapshot, candidates, memberships, arguments, cores, audits,
                   fact_check, *, model, documents, selections, source_policy='all_members'):
    """Owned arguments -> fact-screened bundle/profiles plus bound NLI checks."""
    agent_inputs = ma.prepare(snapshot, candidates, memberships, arguments, cores, audits, model=model, documents=documents,source_policy=source_policy)
    packets = [fact_checks.packet(c, list(documents), list(selections), snapshot.usage.expires_at)
               for c in agent_inputs['bundle']['claims'] if c['kind'] == 'fact']
    checks = []
    if model.get('kind') == 'remote_llm':
        from commentscope.factory import remote_fact_records
        for bound in packets:
            if not bound['evidence']:continue
            req=remote_fact_records.invocation(bound,model)
            record=remote_fact_records.bind(bound,model,fact_check(req))
            checks.append({'claim_id':bound['claim']['id'],'selections':deepcopy(list(selections)),'record':record})
        if checks:
            agent_inputs=ma.prepare(snapshot,candidates,memberships,arguments,cores,audits,
                model=model,documents=documents,checks=checks,source_policy=source_policy)
        return agent_inputs,checks
    for offset in range(0, len(packets), 16):
        batch = packets[offset:offset+16]; req = nli_fact_records.invocation(batch)
        response = fact_check(req)
        records_nli = nli_fact_records.records(batch, model, response, batch_request=req)
        for packet, record in zip(batch, records_nli, strict=True):
            checks.append({'claim_id': packet['claim']['id'], 'selections': deepcopy(list(selections)), 'record': record})
    if checks:
        agent_inputs = ma.prepare(snapshot, candidates, memberships, arguments, cores, audits,
                                  model=model, documents=documents, checks=checks,source_policy=source_policy)
    return agent_inputs, checks
