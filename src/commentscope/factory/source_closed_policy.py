"""Close each source's evidence, arguments and facts before counting a vote.

The full frozen census stays visible. Syntax holds and unprocessed nominations
never become votes. Selection is deterministic and stops at three closed sources
per proposed core; semantic review of every final source remains mandatory.
"""
from copy import deepcopy
from commentscope.factory import explicit_discourse as ed,owned_arguments as oa
from commentscope.factory import owned_node_entailment as own,source_arguments as sa,minimal_agents as ma
from commentscope.factory import minimal_membership as mm,policy_stance_union as union
from commentscope.factory import policy_stance_hypotheses as stance,policy_attitude as attitude
from commentscope.factory import raw_membership as raw,raw_membership_verification as verification
from commentscope.factory import source_entailment as se,fact_checks,nli_fact_records
from commentscope.factory import policy_target,source_discourse,source_argument_fidelity,atomic_source_arguments
from commentscope.factory import literal_source_arguments as literal
from commentscope.factory import sentence_source_arguments as sentence
from commentscope.factory import reviewed_source_admission as source_review
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.factory.automatic_contract import digest

VERSION='source-closed-policy-admission-20261023-v9'


def syntax_holds(graph):
    ed.validate(graph);reasons=[]
    if graph['holds']:reasons.append('source_syntax_unresolved')
    if not any(n['kind']=='statement' for n in graph['nodes']):reasons.append('no_fixed_statement')
    if any(len(n['span']['text'])>600 for n in graph['nodes']):reasons.append('literal_node_exceeds_claim_capacity')
    return reasons


def process(snapshot,record,completed_batches,runner,inspect,classify,*,model,documents=(),selections=(),save=None,
            interpret_unparsed=False,atomic_arguments=False,literal_arguments=False,sentence_arguments=False,
            review_source=None,require_direct_review=False):
    if any(type(v) is not bool for v in (interpret_unparsed,atomic_arguments,literal_arguments,sentence_arguments)):
        raise ValueError('Explicit source route required')
    if type(require_direct_review) is not bool or (require_direct_review and not callable(review_source)):
        raise ValueError('Review-before-count admission requires an exact source reviewer')
    from commentscope.factory import named_candidate_census as common
    general=record.get('artifact_kind') in (common.VERSION,common.UNNAMED)
    named_path=record.get('artifact_kind')!=common.UNNAMED
    census=common if general else union
    census.validate(record);sources=record['sources'];lookup={s['id']:s for s in sources}
    candidates=census.candidates(record);polarities={c['id']:c['polarity'] for c in
        stance.hypotheses(sources,record['topic'],record['alias'])}
    # Validate all actual full batches once before any source-specific work.
    se.from_completed_batches(sources,candidates,[],completed_batches)
    save=save or (lambda name,value:None);graphs={s['id']:ed.parse(s) for s in sources}
    errors=[];holds=[];accepted=[];cores=[];routes=[];attitudes={};outcomes=[];statuses=[];direct_reviews=[]

    def request(stage,req,bind):
        key=digest(req);capacity=inspect(req)
        if capacity['request_sha256']!=key:raise ValueError('Capacity request changed')
        save('capacity/'+key,capacity)
        if not capacity['fits']:
            holds.append({'stage':stage,'request_sha256':key,'reason':'context_capacity'});return None
        try:result=runner.call(stage,req)
        except PriorRequestUnavailable:
            holds.append({'stage':stage,'request_sha256':key,'reason':'prior_request_unavailable_no_retry'});return None
        if result.get('raw') is None and result.get('errors'):
            raise RuntimeError('Incomplete call requires ledger reconciliation')
        try:bound=bind(result)
        except (ValueError,KeyError,TypeError) as exc:
            error={'stage':stage,'request_sha256':key,'exception':type(exc).__name__,'message':str(exc)}
            errors.append(error);save('errors/'+key,{'error':error,'result':result});return None
        save('bound/'+key+'-'+digest(bound)[:16],bound);return bound

    def close(source,candidate,core,route,status):
        sid=source['id'];cid=candidate['id'];graph=graphs[sid];prefix=cid+'/'+sid
        if cid in polarities and sid not in attitudes:
            attitudes[sid]=request('own-policy-evaluation',attitude.request(source,record['topic']),
                lambda result:attitude.bind(source,record['topic'],result))
        evaluation=attitudes.get(sid)
        if cid in polarities and (evaluation is None or polarities[cid] not in evaluation['passed_polarities']):
            status['reasons']=['own_policy_evaluation_unproved'];return
        proposed=request('policy-original',raw.request(source,candidate),lambda result:raw.bind(source,candidate,result))
        if proposed is None:status['reasons']=['original_assessment_unavailable'];return
        evidence=None
        if proposed['passed']:
            evidence=request('policy-own-evidence',verification.evidence_request(proposed,verification.ALIGNED),
                lambda result:verification.bind_evidence(proposed,result,verification.ALIGNED))
        assessment=verification.assessment(proposed,route,evidence,version=verification.ALIGNED)
        batch=verification.batch([source],[candidate],[assessment],version=verification.ALIGNED)
        member=se.from_completed_batches([source],[candidate],[batch],completed_batches)
        save('memberships/'+prefix,member)
        if mm.collect([source],[candidate],[member])[0]['relation']!='supported':
            status['reasons']=['raw_own_evidence_or_whole_original_entailment_unproved'];return
        fidelity=None
        if interpret_unparsed and syntax_holds(graph):
            # A bounded syntax recognizer is a routing optimization, not a
            # semantic rejection of the author's complete original.
            if literal_arguments or sentence_arguments:
                if sentence_arguments:
                    try:graph_request=sentence.request(source)
                    except ValueError:
                        status['reasons']=['complete_sentence_capacity_unavailable'];return
                    own_graph=request('complete-sentence-source-relations',graph_request,
                        lambda result:sentence.bind(source,result))
                else:
                    own_graph=request('literal-own-source-graph',literal.graph_request(source),
                        lambda result:literal.bind_graph(source,result))
                if own_graph is None:
                    status['reasons']=['literal_own_source_graph_unavailable'];return
                save('literal-graphs/'+sid,own_graph)
                if own_graph['output']['status']!='complete' or own_graph['hold_reasons']:
                    status['reasons']=own_graph['hold_reasons'] or ['literal_graph_incomplete'];return
                typings=[]
                for unit in own_graph['units']:
                    lid=unit['local_id']
                    typing=request('literal-target-only-typing',literal.typing_request(own_graph,lid),
                        lambda result,lid=lid:literal.bind_typing(own_graph,lid,result))
                    if typing is None:
                        status['reasons']=['literal_target_typing_unavailable'];return
                    typings.append(typing)
                    if typing['hold_reasons'] and not sentence_arguments:
                        save('literal-typings/'+sid,typings)
                        status['reasons']=typing['hold_reasons'];return
                typing_holds=[reason for t in typings for reason in t['hold_reasons']]
                save('literal-typings/'+sid,typings)
                if typing_holds and not sentence_arguments:
                    status['reasons']=typing_holds;return
                declaration=request('literal-candidate-association',literal.association_request(own_graph,typings,[candidate],[member]),
                    lambda result:literal.declare(own_graph,typings,[candidate],[member],result))
                if declaration is None:
                    status['reasons']=['literal_candidate_association_unavailable'];return
            elif atomic_arguments:
                nomination=request('atomic-original-arguments',atomic_source_arguments.nomination_request(source,[candidate],[member]),
                    lambda result:atomic_source_arguments.bind_nomination(source,[candidate],[member],result))
                if nomination is None:
                    status['reasons']=['atomic_original_arguments_unavailable'];return
                if nomination['output']['status']!='complete':
                    status['reasons']=['whole_original_argument_coverage_unresolved'];return
                typings=[]
                for unit in nomination['units']:
                    lid=unit['local_id']
                    typing=request('source-only-argument-typing',atomic_source_arguments.typing_request(nomination,lid),
                        lambda result,lid=lid:atomic_source_arguments.bind_typing(nomination,lid,result))
                    if typing is None:
                        status['reasons']=['source_only_argument_typing_unavailable'];return
                    typings.append(typing)
                declaration=atomic_source_arguments.declare(nomination,typings)
            else:
                declared=request('whole-original-arguments',sa.extraction_request([source],[candidate],[member]),
                    lambda result:sa.bind([source],[candidate],[member],result))
                if declared is None:
                    status['reasons']=['whole_original_arguments_unavailable'];return
                declaration=declared[0]
            save('declarations/'+prefix,declaration)
            if declaration['status']!='complete':
                status['reasons']=declaration.get('hold_reasons') or ['whole_original_argument_coverage_unresolved'];return
            req=source_argument_fidelity.invocation(declaration)
            response=classify(req) if req['data']['cases'] else None
            fidelity=source_argument_fidelity.bind(declaration,response)
            save('argument-fidelity/'+prefix,fidelity)
            if not fidelity['passed']:
                status['reasons']=fidelity['hold_reasons'];return
        else:
            try:discourse_request=source_discourse.request(graph)
            except ValueError:
                status['reasons']=['complete_source_discourse_capacity_unavailable'];return
            discourse=None;additional=[]
            if discourse_request is not None:
                discourse=request('source-only-discourse',discourse_request,lambda result:source_discourse.bind(graph,result))
                if discourse is None:status['reasons']=['source_discourse_assessment_unavailable'];return
                save('source-discourse/'+prefix,discourse)
                if discourse['hold_reasons']:status['reasons']=discourse['hold_reasons'];return
                additional=source_discourse.usable_edges(graph,discourse)
            children={e['ground_id'] for e in additional}
            metadata=[]
            for node in graph['nodes']:
                context=source_discourse.metadata_context(graph,node,discourse) if discourse is not None else None
                bound=request('argument-node-metadata',oa.metadata_request(graph,node,context),
                    lambda result,node=node,context=context:oa.bind_metadata(graph,node,result,context))
                if bound is None:status['reasons']=['node_metadata_unavailable'];return
                metadata.append(bound)
            typed={m['node_id']:m for m in metadata}
            jobs=[{'graph':graph,'node':n,'candidate':candidate,'metadata':typed[n['id']],
                **({'named_target':(policy_target.bind_general if general else policy_target.bind)(
                    graph,n,candidate,record['topic'],record['alias'])} if named_path else {})}
                for n in graph['nodes'] if n['kind']=='statement' and n['id'] not in children and
                typed[n['id']]['output']['authorship']=='asserted_or_endorsed']
            req=own.invocation(jobs);response=classify(req) if req['data']['cases'] else None
            alignments=own.records(jobs,response);save('own-node-proofs/'+prefix,alignments)
            declaration=oa.declare(graph,[candidate],[member],metadata,alignments,discourse=discourse)
        save('declarations/'+prefix,declaration)
        if declaration['status']!='complete':status['reasons']=declaration.get('hold_reasons',['source_arguments_unresolved']);return
        req=sa.link_request(declaration)
        linked=sa.bind_links(declaration) if req is None else request('argument-dependencies',req,
            lambda result:sa.bind_links(declaration,result))
        if linked is None or linked['dependency_status']!='complete':
            status['reasons']=['source_dependencies_unresolved'];return
        tasks=sa.audit_tasks([linked],[core])
        audits=[]
        for offset in range(0,len(tasks),8):
            group=tasks[offset:offset+8]
            audit=request('source-argument-audit',sa.audit_request([linked],[core],group),
                lambda result,group=group:sa.bind_audit([linked],[core],group,result))
            if audit is None:status['reasons']=['source_audit_unavailable'];return
            audits.append(audit)
        draft=ma.prepare(snapshot,[candidate],[member],[linked],[core],audits,model=model,
            documents=documents,_draft_single_source=True)
        save('source-drafts/'+prefix,draft)
        if draft['argument_holds'] or not draft['bundle']['candidates']:
            status['reasons']=sorted({r for h in draft['argument_holds'] for r in h['reasons']});return
        packets=[fact_checks.packet(c,list(documents),list(selections),snapshot.usage.expires_at)
            for c in draft['bundle']['claims'] if c['kind']=='fact']
        checks=[]
        for offset in range(0,len(packets),16):
            group=packets[offset:offset+16];req=nli_fact_records.invocation(group)
            result=classify(req)
            for packet,proof in zip(group,nli_fact_records.records(group,model,result,batch_request=req),strict=True):
                checks.append({'claim_id':packet['claim']['id'],'selections':deepcopy(list(selections)),'record':proof})
        if checks:
            draft=ma.prepare(snapshot,[candidate],[member],[linked],[core],audits,model=model,
                documents=documents,checks=checks,_draft_single_source=True)
        closure={'checks':checks,'draft':draft}
        if fidelity is not None:closure['argument_fidelity']=fidelity
        if len(audits)>1:closure['argument_audits']=audits
        save('source-fact-closure/'+prefix,closure)
        if any(not d['eligible'] for d in draft['compiled']['claim_decisions'].values()):
            status['reasons']=['source_argument_or_fact_not_eligible'];return
        # No 1-source Agent is ever exposed, and no failed factual argument is
        # silently omitted to let its author's vote count.
        if draft['compiled']['profiles']:raise ValueError('Private draft exposed an Agent')
        status.update(state='model_closed_pending_semantic_review',reasons=[])
        accepted_source={'source_id':sid,'candidate_id':cid,'membership':member,'record':linked,'core':core,
            'audit':audits[0],'checks':checks,'draft_sha256':digest(draft),'semantic_approval':False}
        if fidelity is not None:accepted_source['argument_fidelity']=fidelity
        if len(audits)>1:accepted_source['audits']=audits
        return accepted_source

    for candidate in candidates:
        cid=candidate['id'];outcome={'candidate_id':cid,'polarity':polarities.get(cid),
            'nominees':len(candidate['nominees']),'closed_source_ids':[],'semantic_approval':False}
        outcomes.append(outcome)
        origin=lookup[min(candidate['nominees'])]
        route=request('policy-route',verification.route_request(candidate,origin,version=verification.ALIGNED),
            lambda result:verification.bind_route(candidate,result,origin,version=verification.ALIGNED))
        core=request('policy-core',oa.core_request(candidate),lambda result:oa.bind_core(candidate,result))
        if route is not None:routes.append(route)
        if core is not None:cores.append(core)
        allowed_kinds=('value','prediction') if general else ('value',)
        ready=route is not None and route['passed'] and core is not None and not core['hold_reasons'] and core['output']['kind'] in allowed_kinds
        ordered=sorted(candidate['nominees'],key=lambda sid:((bool(syntax_holds(graphs[sid])),) if interpret_unparsed else ())+
            (len(graphs[sid]['nodes']),len(lookup[sid]['text']),sid))
        for sid in ordered:
            status={'source_id':sid,'candidate_id':cid,'state':'held','reasons':[] if interpret_unparsed else syntax_holds(graphs[sid]),'semantic_approval':False}
            if interpret_unparsed:
                status['syntax_diagnostics']=syntax_holds(graphs[sid])
                status['argument_route']='semantic_whole_original' if status['syntax_diagnostics'] else 'fixed_literal_nodes'
            statuses.append(status)
            if named_path and not policy_target.anchors(lookup[sid],record['topic'],record['alias']):
                status['reasons'].append('own_named_policy_reference_unbound')
            if not ready:status['reasons'].append('named_common_route_or_core_unapproved' if general else 'policy_value_route_or_core_unapproved')
            elif status['reasons']:pass
            elif len(outcome['closed_source_ids'])>=3:
                status.update(state='not_processed_after_three_closed_sources',reasons=[])
            elif any(a['source_id']==sid for a in accepted):
                status['reasons']=['already_closed_for_another_core_no_duplicated_argument_record']
            else:
                result=close(lookup[sid],candidate,core,route,status)
                if result is not None:
                    if require_direct_review:
                        # Persist the immutable model-level artifacts before the
                        # external review. Failed/unreviewed sources never fill
                        # one of the3slots, and source text is never repaired.
                        save('source-status/'+cid+'/'+sid,status)
                        packet,review=review_source(result,status)
                        decision=source_review.bind(result,packet,review)
                        direct_reviews.append(decision);save('admission-reviews/'+cid+'/'+sid,decision)
                        if not decision['countable']:result=None
                if result is not None:
                    accepted.append(result);outcome['closed_source_ids'].append(sid)
            save('source-status/'+cid+'/'+sid,status)
            save('progress/'+f'{len(statuses):04}',{'last_source':status,'outcomes':outcomes,'errors':len(errors)})
        save('outcomes/'+cid,outcome)
    retained={a['candidate_id'] for a in accepted}
    final=ma.prepare(snapshot,[c for c in candidates if c['id'] in retained],
        [a['membership'] for a in accepted],[a['record'] for a in accepted],
        [c for c in cores if c['candidate']['id'] in retained],
        [audit for a in accepted for audit in a.get('audits',[a['audit']])],
        model=model,documents=documents,checks=[check for a in accepted for check in a['checks']])
    save('agent-inputs',final)
    census_status=[{'source_id':s['id'],'nominee_candidate_ids':[c['id'] for c in candidates if s['id'] in c['nominees']],
        'closed_candidate_ids':[a['candidate_id'] for a in accepted if a['source_id']==s['id']]} for s in sources]
    return {'artifact_kind':VERSION,'candidates':candidates,'source_scope':len(sources),'source_statuses':statuses,
        'census_status':census_status,'outcomes':outcomes,'accepted':accepted,'routes':routes,'cores':cores,
        'agent_inputs':final,'errors':errors,'holds':holds,'quality_gate_passed':False,
        'semantic_review_required':True,'runtime_reference_labels':False,
        'review_before_count':require_direct_review,'direct_source_reviews':direct_reviews}
