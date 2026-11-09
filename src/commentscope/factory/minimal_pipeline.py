"""Automatic minimal-claim Factory. Evaluation labels are absent from this API.

The entry point validates the source scope and orders the explicit stages.
Providers and per-run bookkeeping live behind PipelineWork; stage algorithms
remain in pipeline_stages and the existing focused domain modules.
"""
from commentscope.factory import candidate_consolidation as cc, explicit_discourse
from commentscope.factory import fact_checks, pipeline_stages
from commentscope.factory import raw_membership_verification as raw_verification
from commentscope.factory.framed_corpus import sources as source_registry
from commentscope.factory.pipeline_work import PipelineWork
from commentscope.factory.automatic_contract import digest

VERSION = 'minimal-factory-pipeline-20261110-v31'
SOURCE_SEMANTICS_VERSION = 'minimal-factory-pipeline-source-semantics-20261105-v1'
SCHEDULE = {'extraction_sources': 1, 'membership_pairs': 1, 'equivalence_pairs': 1, 'argument_sources': 1}


def process(snapshot, runner, embed, inspect, fact_check, *, model, documents=(), selections=(), scope_ids=None, save=None, discovery_mode='free', membership_mode='scoped', verification_contract=raw_verification.LEGACY, shared_records=None, shared_memberships=None, source_entailment_required=False, extraction_protocol=None, review_interpretations=False, source_review_protocol=None, argument_audit_protocol=None, agent_source_policy='all_members', membership_retrieval_policy=cc.ALIAS_RETRIEVAL,membership_evidence_protocol=None):
    if discovery_mode not in ('free','literal','contextual','shared'):raise ValueError('Unknown Factory discovery mode')
    if membership_mode not in ('scoped','raw'):raise ValueError('Unknown membership comparison mode')
    if membership_evidence_protocol is not None and (membership_evidence_protocol!=raw_verification.QUALIFIED_CONTEXT
            or membership_mode!='raw' or verification_contract!=raw_verification.FULL_SCOPE):
        raise ValueError('Source-context evidence requires explicit full-scope raw verification')
    if agent_source_policy not in ('all_members','verified_subset','candidate_verified_subset'):raise ValueError('Unknown Agent source policy')
    from commentscope.factory import candidate_hierarchy
    if (membership_retrieval_policy not in (cc.ALIAS_RETRIEVAL,candidate_hierarchy.VERSION)
            or membership_retrieval_policy==candidate_hierarchy.VERSION and (discovery_mode,membership_mode)!=('free','raw')):
        raise ValueError('Explicit supported membership retrieval policy required')
    from commentscope.factory import compact_claims
    from commentscope.factory import argument_observations
    shared_typed=discovery_mode=='shared' and argument_audit_protocol==argument_observations.SHARED_TYPED_CHAT
    if argument_audit_protocol==argument_observations.SHARED_TYPED_CHAT and not shared_typed:
        raise ValueError('Common-core directional audits require shared discovery')
    if argument_audit_protocol is not None and (argument_audit_protocol not in argument_observations.GRAPH_SPLITS
            or membership_mode!='raw' or not (shared_typed or discovery_mode=='free' and extraction_protocol in compact_claims.INDEPENDENT_CONTEXT)
            or argument_audit_protocol==argument_observations.JEV_SPLIT and not callable(getattr(runner,'decide',None))):
        raise ValueError('Jev graph audit requires explicit free/raw protocol and typed runner')
    if extraction_protocol is not None and (discovery_mode != 'free' or extraction_protocol not in compact_claims.VERSIONS):
        raise ValueError('Compact extraction requires its explicit free-discovery protocol')
    if type(review_interpretations) is not bool or (review_interpretations and
            (discovery_mode != 'free' or extraction_protocol != compact_claims.TRACED_PROPOSALS)):
        raise ValueError('Semantic interpretation review requires explicit traced free discovery')
    from commentscope.factory import source_interpretation
    if source_review_protocol is not None and (not review_interpretations
            or source_review_protocol not in source_interpretation.REVIEW_VERSIONS):
        raise ValueError('Explicit supported source review requires traced interpretation review')
    typed_source_review = source_review_protocol == source_interpretation.TYPED_REVIEW
    if discovery_mode=='shared' and membership_mode!='raw':
        raise ValueError('Shared proposals require independent original membership')
    if shared_records is not None and discovery_mode!='shared':
        raise ValueError('Shared proposal injection requires shared discovery')
    if shared_memberships is not None and (discovery_mode!='shared' or shared_records is None):
        raise ValueError('Staged memberships require rebound common proposals')
    if shared_memberships is not None and membership_evidence_protocol is not None:
        raise ValueError('Explicit evidence protocol requires fresh membership judging')
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
    execution = PipelineWork(runner, inspect, save, registry=registry,
                             membership_mode=membership_mode,
                             verification_contract=verification_contract, schedule=SCHEDULE,
                             extraction_protocol=extraction_protocol, review_interpretations=review_interpretations,
                             source_review_protocol=source_review_protocol)
    execution.argument_audit_protocol=argument_audit_protocol
    execution.shared_typed=shared_typed
    execution.membership_evidence_protocol=membership_evidence_protocol
    execution.membership_retrieval_policy=membership_retrieval_policy
    errors, holds, capacity = execution.errors, execution.holds, execution.capacity
    # Immutable syntax exists before any generated candidate or argument. This
    # artifact is not semantic approval. Argument text and ownership below must
    # be derived from these immutable source nodes.
    discourse = {s['id']: explicit_discourse.parse(s) for s in sources}
    save('source-discourse', discourse)

    vectors = embed('sources', {sid: registry[sid]['text'] for sid in ids})
    cc.vectors(vectors)
    if set(vectors) != set(ids): raise ValueError('Source embeddings changed')
    discovery = pipeline_stages.discover(sources, vectors, execution,
        discovery_mode=discovery_mode, shared_records=shared_records)
    records, engine = discovery.records, discovery.engine
    shared_discovery = discovery.shared_discovery
    execution.engine = engine

    source_records = None
    if typed_source_review:
        from commentscope.factory import source_semantics
        source_records = source_semantics.collect(records, discovery.interpretation_reviews,
                                                  snapshot_sha256=digest(snapshot.to_dict()))
        save('source-records', source_records)

    support = pipeline_stages.memberships(sources, ids, discovery.candidates, records,
        vectors, embed, execution, discovery_mode=discovery_mode,
        shared_memberships=shared_memberships, source_entailment_required=source_entailment_required)
    candidates, memberships = support.candidates, support.memberships
    nomination_batches, merged, equivalences = support.nomination_batches, support.consolidation, support.equivalences

    owned = pipeline_stages.arguments(snapshot, candidates, memberships, discourse, execution,
        discovery_mode=discovery_mode)
    arguments, cores, audits = owned.arguments, owned.cores, owned.audits
    agent_inputs, checks = pipeline_stages.compile_agents(snapshot, candidates, memberships,
        arguments, cores, audits, fact_check, model=model, documents=documents, selections=selections,source_policy=agent_source_policy)
    save('qualification-inventories',list(execution.shape_cache.values()));save('qualification-assessments',list(execution.assessment_cache.values()))
    save('fact-checks', checks); save('agent-inputs', agent_inputs)
    if engine is not None:
        errors.extend(engine.errors);holds.extend(engine.holds);capacity.extend(engine.capacity)
        save('contextual-engine',engine.diagnostics())
    return {'artifact_kind': SOURCE_SEMANTICS_VERSION if typed_source_review else VERSION,
            'canonical_population': len(registry), 'processing_ids': ids,
            **({'argument_audit_protocol':argument_audit_protocol} if argument_audit_protocol else {}),
            **({'membership_evidence_protocol':membership_evidence_protocol} if membership_evidence_protocol else {}),
            **({'agent_source_policy':agent_source_policy} if agent_source_policy!='all_members' else {}),
            **({'source_review_protocol': source_review_protocol, 'source_records': source_records}
               if typed_source_review else {}),
            **({'interpretation_review_required': True,
                'interpretation_reviews': discovery.interpretation_reviews,
                'interpretation_admission': discovery.interpretation_admission} if review_interpretations else {}),
            'discovery_mode':discovery_mode,
            'shared_discovery':shared_discovery,
            'source_discourse': discourse, 'argument_ownership_enforced': True,
            'extractions': records, 'candidates': candidates, 'memberships': memberships,
            'nomination_batches': nomination_batches, 'consolidation': merged, 'equivalences': equivalences,
            'arguments': arguments, 'cores': cores, 'audits': audits, 'agent_inputs': agent_inputs,
            'errors': errors, 'capacity_holds': holds, 'capacity_measurements': capacity,
            'unextracted_source_ids': sorted(set(ids)-({s['id'] for r in shared_discovery for s in r['sources']}
                if shared_typed else {r['source']['id'] for r in records})),
            'runtime_reference_labels': False, 'quality_gate_passed': False}
