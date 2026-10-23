"""Automatic minimal-claim Factory. Evaluation labels are absent from this API."""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc, minimal_membership as mm, proposition_requirements as pr
from commentscope.factory import candidate_consolidation as cc, source_arguments as sa, minimal_agents as ma
from commentscope.factory import fact_checks, nli_fact_records
from commentscope.factory import explicit_discourse, owned_arguments as oa
from commentscope.factory import qualification_ownership as qo
from commentscope.factory import shared_claims, shared_owned_positions
from commentscope.factory import raw_membership_verification as raw_verification
from commentscope.factory import contextual_runtime
from commentscope.factory.automatic_contract import digest
from commentscope.factory.framed_corpus import sources as source_registry
from commentscope.providers.context_capacity import partition

VERSION = 'minimal-factory-pipeline-20261023-v28'
SCHEDULE = {'extraction_sources': 1, 'membership_pairs': 1, 'equivalence_pairs': 1, 'argument_sources': 1}


def process(snapshot, runner, embed, inspect, fact_check, *, model, documents=(), selections=(), scope_ids=None, save=None, discovery_mode='free', membership_mode='scoped', verification_contract=raw_verification.LEGACY, shared_records=None, shared_memberships=None, source_entailment_required=False):
    if discovery_mode not in ('free','contextual','shared'):raise ValueError('Unknown Factory discovery mode')
    if membership_mode not in ('scoped','raw'):raise ValueError('Unknown membership comparison mode')
    if discovery_mode=='shared' and membership_mode!='raw':
        raise ValueError('Shared proposals require independent original membership')
    if shared_records is not None and discovery_mode!='shared':
        raise ValueError('Shared proposal injection requires shared discovery')
    if shared_memberships is not None and (discovery_mode!='shared' or shared_records is None):
        raise ValueError('Staged memberships require rebound common proposals')
    if type(source_entailment_required) is not bool or (source_entailment_required and shared_memberships is None):
        raise ValueError('Whole-original entailment requires explicit staged common memberships')
    if verification_contract not in raw_verification.VERSIONS:raise ValueError('Unknown raw verification contract')
    if verification_contract in raw_verification.TARGETED_CONTRACTS and (discovery_mode, membership_mode) != ('contextual', 'raw'):
        raise ValueError('Experimental target eligibility requires contextual discovery and raw membership')
    fact_checks.live(snapshot.usage.expires_at)
    registry = source_registry(snapshot, include_video_context=True)
    ids = sorted(registry) if scope_ids is None else sorted(scope_ids)
    if len(ids) != len(set(ids)) or any(sid not in registry for sid in ids) or not ids:
        raise ValueError('Nonempty unique canonical processing scope required')
    sources = [registry[sid] for sid in ids]; save = save or (lambda name, value: None)
    errors = []; holds = []; capacity = []
    # Immutable syntax exists before any generated candidate or argument. This
    # artifact is not semantic approval. Argument text and ownership below must
    # be derived from these immutable source nodes.
    discourse = {s['id']: explicit_discourse.parse(s) for s in sources}
    save('source-discourse', discourse)

    def work(stage, items, build, bind, size, *, minimum=1):
        results = []
        for offset in range(0, len(items), size):
            fitted, deferred = partition(items[offset:offset+size], build, inspect,minimum=minimum)
            holds.extend({'stage': stage, **d} for d in deferred)
            for task in fitted:
                req = task['request']; key = stage+'-'+digest(req)[:20]
                # Identical requests may bind different final candidate
                # provenance after consolidation. Keep the call checkpoint
                # identity, but never overwrite either bound input record.
                binding_key = key+'-'+digest(task['items'])[:20]
                capacity.append({'stage': stage, **task['capacity']}); save('capacity/'+key, task['capacity'])
                # Pending/transport ambiguity escapes: never turn it into permission
                # for a duplicate request. A returned malformed batch is preserved.
                from commentscope.factory.shared_admission import PriorRequestUnavailable
                try:result = runner.call(key, req)
                except PriorRequestUnavailable:
                    holds.append({'stage':stage,'task_sha256':digest(task['items']),
                        'request_sha256':digest(req),'reason':'prior_request_unavailable_no_retry'})
                    continue
                try:
                    bound = bind(task['items'], result)
                except (ValueError, KeyError, TypeError) as exc:
                    error = {'stage': stage, 'task_sha256': digest(task['items']),
                             'request_sha256': digest(req), 'exception': type(exc).__name__,
                             'message': str(exc), 'result': deepcopy(result), 'items': deepcopy(task['items'])}
                    errors.append(error); save('errors/'+binding_key, error)
                    if result.get('raw') is None and result.get('errors'):
                        raise RuntimeError('No completed model response; inspect process and ledger')
                    continue
                results.append(bound); save('bound/'+binding_key, bound)
        return results

    shape_cache={};assessment_cache={}
    def qualify(source,candidate):
        text=candidate['text']
        if text not in shape_cache:
            rows=work('qualification-inventory',[text],lambda group:pr.shape_request(group[0]),
                      lambda group,result:pr.bind_shape(group[0],result),1)
            shape_cache[text]=rows[0] if rows else None
        shape=shape_cache[text]
        if shape is None:return None
        key=digest([source,shape])
        if key not in assessment_cache:
            checks=[]
            if shape['status']=='complete':
                checks=work('qualification-detail',shape['details'],
                    lambda group:pr.detail_request(source,shape,group[0]),
                    lambda group,result:pr.bind_detail(source,shape,group[0],result),1)
            ownership=work('qualification-ownership',qo.pairs(source,text),
                lambda group:qo.pair_request(source,text,group[0]),
                lambda group,result:qo.bind_pair(source,text,group[0],result),1)
            assessment_cache[key]=pr.assessment(source,shape,checks,qo.assessment(source,text,ownership))
        return assessment_cache[key]

    vectors = embed('sources', {sid: registry[sid]['text'] for sid in ids})
    cc.vectors(vectors)
    if set(vectors) != set(ids): raise ValueError('Source embeddings changed')
    engine=None;shared_discovery=[]
    if discovery_mode=='contextual':
        from commentscope.factory.contextual_engine import Engine
        engine=Engine(sources,runner,inspect,save=lambda name,value:save('contextual/'+name,value),raw_membership=membership_mode=='raw',verification_contract=verification_contract)
        engine.discover();records=engine.records
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
    else:records = mc.extract_independently(sources, work)
    save('extractions', records)
    if discovery_mode=='shared':
        candidates=shared_claims.candidates(shared_discovery);save('shared-discovery',shared_discovery)
    else:candidates = mc.candidates(records)
    save('initial-candidates', candidates)
    raw_routes={}

    def judge(stage, pairs, targets):
        if engine is not None:return engine.judge(pairs,targets)
        target_lookup = {c['id']: c for c in targets}
        if membership_mode=='raw':
            from commentscope.factory import raw_membership as raw
            from commentscope.factory import raw_membership_verification as verification
            results=[]
            for pair in pairs:
                source,target=registry[pair['source_id']],target_lookup[pair['candidate_id']]
                proofs=work(stage+'-raw',[pair],lambda group:raw.request(source,target),
                            lambda group,result:raw.bind(source,target,result),1)
                for proof in proofs:
                    route=None;evidence=None
                    if proof['passed']:
                        target_key=digest(target)
                        if target_key not in raw_routes:
                            origin_id=min(target['nominees'])
                            if verification_contract in verification.INDEPENDENT and 'meaning_context' in target:
                                origin_id=target['meaning_context']['source']['id']
                            origin=registry[origin_id] if verification_contract in (verification.VERSION,*verification.INDEPENDENT) else None
                            route_version=verification_contract if verification_contract in verification.INDEPENDENT else None
                            rows=work('raw-candidate-route',[target],lambda group:verification.route_request(group[0],origin,version=route_version),
                                lambda group,result:verification.bind_route(group[0],result,origin,version=route_version),1)
                            raw_routes[target_key]=rows[0] if rows else None
                        route=raw_routes[target_key]
                        if route and route['passed']:
                            rows=work('raw-own-evidence',[proof],lambda group:verification.evidence_request(group[0],verification_contract),
                                lambda group,result:verification.bind_evidence(group[0],result,verification_contract),1)
                            evidence=rows[0] if rows else None
                    verified=verification.assessment(proof,route,evidence,version=verification_contract)
                    results.append(verification.batch([source],[target],[verified],version=verification_contract))
            return results
        def args(group):
            return ([registry[sid] for sid in sorted({p['source_id'] for p in group})],
                    [target_lookup[cid] for cid in sorted({p['candidate_id'] for p in group})], group)
        preliminary=work(stage,pairs,lambda group:mm.membership_request(*args(group)),
                         lambda group,result:mm.bind(*args(group),result),SCHEDULE['membership_pairs'])
        results=[]
        for batch in preliminary:
            qualifications=[]
            for row in batch['memberships']:
                decision=row['decision']
                if (decision['relation']=='supported' and decision['authorship']=='asserted_or_endorsed'
                        and decision['scope_preserved']=='yes'):
                    assessment=qualify(registry[row['source_id']],target_lookup[row['candidate_id']])
                    if assessment is not None:qualifications.append({'source_id':row['source_id'],
                        'candidate_id':row['candidate_id'],'assessment':assessment})
            bound=mm.bind(batch['sources'],batch['candidates'],batch['pairs'],{'output':batch['output']},qualifications)
            results.append(bound);save('bound/'+stage+'-qualified-'+digest(bound)[:20],bound)
        return results

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
        equivalences = [] if engine is not None else work('equivalence', pairs,
                            lambda group: cc.equivalence_request(sources, candidates, nomination_batches, group),
                            lambda group, result: cc.bind(sources, candidates, nomination_batches, group, result), SCHEDULE['equivalence_pairs'])
        index={c['id']:c for c in candidates};qualified_equivalences=[]
        for record in equivalences:
            qualifications=[]
            for row in record['relations']:
                if row['model_relation']!='equivalent':continue
                for left,right in ((row['a'],row['b']),(row['b'],row['a'])):
                    source={'id':left,'text':index[left]['text'],'parent':None}
                    assessment=qualify(source,index[right])
                    if assessment is not None:qualifications.append({'from_candidate_id':left,
                        'to_candidate_id':right,'assessment':assessment})
            bound=cc.bind(sources,candidates,nomination_batches,record['pairs'],{'output':record['output']},qualifications)
            qualified_equivalences.append(bound);save('bound/equivalence-qualified-'+digest(bound)[:20],bound)
        equivalences=engine.equivalences(pairs) if engine is not None else qualified_equivalences
        representative_scopes = ({c['id']:contextual_runtime.bind(c,engine.scope(c)) for c in candidates
                                  if c['id'] in engine.scopes} if engine is not None else None)
        merged = cc.consolidate(sources,candidates,nomination_batches,equivalences,runtime_scopes=representative_scopes)
        candidates = merged['candidates']; save('consolidation', merged); save('equivalences', equivalences)
        # Representative text is unchanged; reuse its embedding, never another's support vote.
        final_vectors = {c['id']: candidate_vectors[c['id']] for c in candidates}
        first = cc.membership_pairs(sources, candidates, vectors, final_vectors)
        memberships = judge('membership-initial', first, candidates)
        statuses = {r['source']['id']: r['status'] for r in records}
        statuses.update({sid: 'unresolved' for sid in ids if sid not in statuses})
        extra_pairs = cc.membership_pairs(sources, candidates, vectors, final_vectors,
                                         previous=memberships, statuses=statuses, expand=True)
        # A failed initial batch must not be silently retried as expansion.
        attempted = {(p['source_id'], p['candidate_id']) for p in first}
        extra_pairs = [p for p in extra_pairs if (p['source_id'], p['candidate_id']) not in attempted]
        memberships.extend(judge('membership-expanded', extra_pairs, candidates))
    else:
        memberships = []; equivalences = []; merged = None
    save('candidates', candidates); save('memberships', memberships)
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
    audits = work('argument-audit', tasks, lambda group: sa.audit_request(arguments, cores, group),
                  lambda group, result: sa.bind_audit(arguments, cores, group, result), 1)
    save('argument-audits', audits)
    agent_inputs = ma.prepare(snapshot, candidates, memberships, arguments, cores, audits, model=model, documents=documents)
    packets = [fact_checks.packet(c, list(documents), list(selections), snapshot.usage.expires_at)
               for c in agent_inputs['bundle']['claims'] if c['kind'] == 'fact']
    checks = []
    for offset in range(0, len(packets), 16):
        batch = packets[offset:offset+16]; req = nli_fact_records.invocation(batch)
        response = fact_check(req)
        records_nli = nli_fact_records.records(batch, model, response, batch_request=req)
        for packet, record in zip(batch, records_nli, strict=True):
            checks.append({'claim_id': packet['claim']['id'], 'selections': deepcopy(list(selections)), 'record': record})
    if checks:
        agent_inputs = ma.prepare(snapshot, candidates, memberships, arguments, cores, audits,
                                  model=model, documents=documents, checks=checks)
    save('qualification-inventories',list(shape_cache.values()));save('qualification-assessments',list(assessment_cache.values()))
    save('fact-checks', checks); save('agent-inputs', agent_inputs)
    if engine is not None:
        errors.extend(engine.errors);holds.extend(engine.holds);capacity.extend(engine.capacity)
        save('contextual-engine',engine.diagnostics())
    return {'artifact_kind': VERSION, 'canonical_population': len(registry), 'processing_ids': ids,
            'discovery_mode':discovery_mode,
            'shared_discovery':shared_discovery,
            'source_discourse': discourse, 'argument_ownership_enforced': True,
            'extractions': records, 'candidates': candidates, 'memberships': memberships,
            'nomination_batches': nomination_batches, 'consolidation': merged, 'equivalences': equivalences,
            'arguments': arguments, 'cores': cores, 'audits': audits, 'agent_inputs': agent_inputs,
            'errors': errors, 'capacity_holds': holds, 'capacity_measurements': capacity,
            'unextracted_source_ids': sorted(set(ids)-{r['source']['id'] for r in records}),
            'runtime_reference_labels': False, 'quality_gate_passed': False}
