"""Small same-input comparison-contract diagnostic; never a complete G1 run."""
import argparse
from copy import deepcopy
from pathlib import Path
from shutil import copy2
import time

from commentscope.factory import minimal_membership as mm, candidate_consolidation as cc
from commentscope.factory import proposition_fidelity as pf, proposition_requirements as pr
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.position_frames import source_packet
from commentscope.ingestion import load_snapshot
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.context_capacity import measure
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.model_selection_20261016 import observe
from experiments.minimal_factory_pipeline import BASE, CYCLE, private, deployment_check
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'minimal-comparison-diagnostic-20261016-v4'
TEXTS = {
    'freedom': 'Safety reviews should remain voluntary because freedom of choice matters.',
    'voluntary': 'Safety reviews should not be mandatory; they should remain voluntary.',
    'safety': 'Safety reviews should be mandatory because public safety is important.',
    'accountability': 'Safety reviews should be mandatory because accountability matters.',
    'mandatory': 'Safety reviews should be mandatory.',
    'required': 'Safety reviews should be required.',
    'conditional': 'Safety reviews should be mandatory only if small labs receive fee waivers.'}
CASES = [('A','accountability',False),('A','safety',False),('B','accountability',False),('G','freedom',False),('L','freedom',False),
         ('A','mandatory',True),('B','mandatory',True),('I','mandatory',True),('J','mandatory',True),
         ('E','voluntary',True),('D','mandatory',False),('K','mandatory',False),('H','mandatory',False),
         ('D','required',False),('K','required',False),('I','required',True),('J','required',True)]
EQUIVALENCES = [('freedom','voluntary',False),('safety','mandatory',False),
                ('conditional','mandatory',False),('required','mandatory',True)]
QUALIFIER_POSITIVES = [('B','safety',True),('J','safety',True),('E','freedom',True),
                      ('D','conditional',True),('K','conditional',True)]


def prepare(directory, source, mode='comparison', runtime_bundle=None, reuse_memberships=None, case_set='all', content_run=None, clause_controls=None):
    private(directory);private(source)
    if directory.exists(): raise ValueError('New diagnostic directory required')
    source_plan=read_json(source/'plan.json'); snapshot_path=Path(source_plan['snapshot'])
    candidates=read_json(source/'artifacts/initial-candidates.json')
    selected={name:next(c for c in candidates if c['text']==text) for name,text in TEXTS.items()}
    deployment=read_json(BASE)['deployment'];deployment_check(deployment)
    settings=read_json(CYCLE)
    if settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None: raise ValueError('Uncapped current ledger required')
    paths=[source/'plan.json',source/'completed.json',source/'artifacts/initial-candidates.json',snapshot_path,BASE,CYCLE]
    if mode=='runtime':
        if runtime_bundle is None:raise ValueError('Frozen runtime bundle required')
        private(runtime_bundle);paths.append(runtime_bundle)
    if reuse_memberships is not None:
        if mode!='content':raise ValueError('Membership reuse is scoped to content component only')
        private(reuse_memberships);old=reuse_memberships.parent.parent
        paths.extend([reuse_memberships,old/'plan.json',old/'completed.json'])
        requests=sorted((old/'calls').glob('*content-member-*.request.json'))
        paths.extend(requests);paths.extend(p.with_name(p.name.replace('.request.json','.result.json')) for p in requests)
    if clause_controls is not None:
        if mode!='clauses':raise ValueError('Clause controls only apply to clause diagnostics')
        private(clause_controls);paths.append(clause_controls)
    if mode=='judgments':
        if content_run is None:raise ValueError('Completed content run required')
        private(content_run)
        paths.extend([content_run/'plan.json',content_run/'completed.json',content_run/'content/memberships.json'])
        paths.extend(sorted((content_run/'content/extractions').glob('*.json')))
    if case_set!='all' and mode!='requirements':raise ValueError('Case subset only applies to requirements diagnostics')
    plan={'artifact_kind':VERSION,'mode':mode,'case_set':case_set,
          'clause_controls':str(clause_controls) if clause_controls else None,
          'content_run':str(content_run) if content_run else None,
          'reuse_memberships':str(reuse_memberships) if reuse_memberships else None,
          'runtime_bundle':str(runtime_bundle) if runtime_bundle else None,'source':str(source),'snapshot':str(snapshot_path),'candidates':selected,
          'deployment':deployment,'classifier':deepcopy(source_plan['classifier']),'budget':{k:settings[k] for k in ('cycle_id','ledger')},
          'limits':{'analysis_seconds':None,'call_seconds':600},'inputs':{str(p):sha(p) for p in paths},
          'code_sha256':code_hashes(),'comparison_cases':deepcopy(CASES if case_set=='all' else QUALIFIER_POSITIVES),
          'equivalence_cases':deepcopy(EQUIVALENCES if case_set=='all' else []),
          'evaluation_labels_in_runtime':False,'full_G1_run':False,'quality_gate_passed':False,
          'purpose':'Test complete-proposition comparison, including explicit rationale, with fresh nomination and pair calls.'}
    write(directory/'plan.json',plan)
    for path,h in plan['code_sha256'].items():
        if sha(path)!=h:raise ValueError('Code changed while freezing')
        target=directory/'frozen-code'/path;target.parent.mkdir(parents=True,exist_ok=True);copy2(path,target)
    return plan


def checked_call(directory,runner,stage,req):
    capacity=measure(req)
    # runtime_probe uses the same stage name for all questions. Preserve every
    # measurement without overwriting or mistaking the second question for retry.
    name=f'{runner.seq+1:04}-{stage}-{digest(req)[:16]}.json'
    write(directory/'capacity'/name,capacity)
    if not capacity['fits']:raise ValueError('Diagnostic capacity exceeded')
    return runner.call(stage,req)


def run(directory):
    private(directory);plan=read_json(directory/'plan.json')
    if plan['artifact_kind']!=VERSION or (directory/'started.json').exists():raise ValueError('Fresh frozen diagnostic required')
    for group in ('inputs','code_sha256'):
        if any(sha(p)!=h for p,h in plan[group].items()):raise ValueError('Frozen diagnostic input changed')
    deployment_check(plan['deployment'])
    for info in (plan['deployment']['server'],plan['deployment']['models']['baseline']):
        if file_hash(info['path'])!=info['sha256']:raise ValueError('Model/server changed')
    observation=observe();write(directory/'preflight.json',observation)
    if observation['refusal_reasons']:raise RuntimeError('Diagnostic resource preflight refused')
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot
    sources=[source_packet(snapshot,c.comment_id) for c in snapshot.comments]
    lookup={s['id']:s for s in sources};selected=plan['candidates'];candidates=list(selected.values())
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
    runner=Runner(directory,plan,budget);started=time.monotonic()
    write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json'),'budget_before':budget.summary()})
    members=[];assessed=[];equivalences=[];component=None
    try:
        with owned_server(plan['deployment'],'baseline',directory/'server'):
            def call(stage,req):
                return checked_call(directory,runner,stage,req)
            if plan['mode']=='owned':
                component=owned_component(call,selected,lookup,directory)
            elif plan['mode']=='clauses':
                component=clause_component(call,{s['id']:s for s in read_json(Path(plan['clause_controls']))} if plan['clause_controls'] else lookup,directory)
            elif plan['mode']=='trees':
                component=tree_component(call,lookup,directory)
            elif plan['mode']=='judgments':
                component=judgment_component(call,plan,selected,directory)
            elif plan['mode']=='content':
                component=content_component(call,plan,selected,lookup,directory)
            elif plan['mode']=='runtime':
                from experiments.framed_agent_probe import runtime_probe
                inputs=read_json(Path(plan['runtime_bundle']))
                class Guarded:
                    def call(self,stage,req):return call(stage,req)
                runtime=runtime_probe(inputs['bundle'],Guarded());write(directory/'runtime.json',runtime)
                component={'runtime_only':True,'known_input_semantic_failures':True,
                    'profiles':len(runtime['all_compiled_candidate_ids']),'runtime_turns':len(runtime['turns']),
                    'all_histories_isolated':all(t['other_histories_unchanged'] for t in runtime['turns']),
                    'full_G1_passed':False,'semantic_review_required':True}
            elif plan['mode']=='arguments':
                component=argument_component(call,plan,selected,lookup,snapshot,directory)
            elif plan['mode']=='requirements':
                shapes={}
                for name,candidate in selected.items():
                    shapes[name]=pr.bind_shape(candidate['text'],call('shape-'+name,pr.shape_request(candidate['text'])))
                    write(directory/'shapes'/(name+'.json'),shapes[name])
                def qualification(source,name,stage):
                    from commentscope.factory import qualification_ownership as qo
                    shape=shapes[name]; checks=[]
                    if shape['status']=='complete':
                        for i,detail in enumerate(shape['details']):
                            checks.append(pr.bind_detail(source,shape,detail,call(stage+f'-detail-{i}',pr.detail_request(source,shape,detail))))
                    text=selected[name]['text']
                    witnesses=[qo.bind_pair(source,text,p,call(stage+'-owner-'+digest(p)[:12],
                        qo.pair_request(source,text,p))) for p in qo.pairs(source,text)]
                    bound=pr.assessment(source,shape,checks,qo.assessment(source,text,witnesses))
                    return {'passed':bound['passed'],'checks':checks,'assessment':bound}
                for index,(sid,name,expected) in enumerate(plan['comparison_cases']):
                    cs=[selected[name]];ss=[lookup[sid]];pairs=[{'source_id':sid,'candidate_id':cs[0]['id']}]
                    primary=mm.bind(ss,cs,pairs,call(f'membership-{index}',mm.membership_request(ss,cs,pairs)))
                    requirement=qualification(lookup[sid],name,f'membership-{index}')
                    actual=primary['memberships'][0]['decision']['relation']=='supported' and primary['memberships'][0]['decision']['authorship']=='asserted_or_endorsed' and primary['memberships'][0]['decision']['scope_preserved']=='yes' and requirement['passed']
                    row={'source_id':sid,'candidate':name,'expected_support':expected,'actual_support':actual,'primary':primary,'requirement':requirement,'passed':actual==expected}
                    assessed.append(row);write(directory/'memberships'/f'{index}.json',row)
                for index,(left,right,expected) in enumerate(plan['equivalence_cases']):
                    checks=[]
                    for n,(a,b) in enumerate(((left,right),(right,left))):
                        source={'id':selected[a]['id'],'text':selected[a]['text'],'parent':None}
                        checks.append(qualification(source,b,f'equivalence-{index}-{n}'))
                    actual=all(r['passed'] for r in checks)
                    row={'left':left,'right':right,'expected_qualifications_compatible':expected,'actual_qualifications_compatible':actual,'checks':checks,'base_equivalence_not_checked':True,'passed':actual==expected}
                    equivalences.append(row);write(directory/'equivalences'/f'{index}.json',row)
            elif plan['mode']=='fidelity':
                for index,(sid,name,expected) in enumerate(plan['comparison_cases']):
                    record=pf.bind(lookup[sid],selected[name]['text'],call(f'fidelity-{index}',pf.request(lookup[sid],selected[name]['text'])))
                    actual=record['verdict']=='faithful'
                    row={'source_id':sid,'candidate':name,'expected_support':expected,'actual_support':actual,'record':record,'passed':actual==expected}
                    assessed.append(row);write(directory/'memberships'/f'{index}.json',row)
                for index,(left,right,expected) in enumerate(plan['equivalence_cases']):
                    records=[]
                    for n,(a,b) in enumerate(((left,right),(right,left))):
                        source={'id':selected[a]['id'],'text':selected[a]['text'],'parent':None}
                        records.append(pf.bind(source,selected[b]['text'],call(f'fidelity-equivalence-{index}-{n}',pf.request(source,selected[b]['text']))))
                    actual=all(r['verdict']=='faithful' for r in records)
                    row={'left':left,'right':right,'expected_equivalent':expected,'actual_equivalent':actual,'records':records,'passed':actual==expected}
                    equivalences.append(row);write(directory/'equivalences'/f'{index}.json',row)
            else:
                comparison(call,plan,selected,candidates,lookup,sources,members,assessed,equivalences,directory)
        report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'membership_passed':sum(r['passed'] for r in assessed),
                'membership_cases':len(assessed),'equivalence_passed':sum(r['passed'] for r in equivalences),'equivalence_cases':len(equivalences),
                'diagnostic_passed':bool(assessed) and all(r['passed'] for r in [*assessed,*equivalences]),'argument_component':component,'full_G1_passed':False,
                'elapsed_seconds':time.monotonic()-started,'budget_after':budget.summary()}
        write(directory/'completed.json',report);print({k:v for k,v in report.items() if k!='budget_after'},flush=True)
        return report
    except BaseException as exc:
        write(directory/'failed.json',{'exception':type(exc).__name__,'budget_after':budget.summary()});raise


def comparison(call,plan,selected,candidates,lookup,sources,members,assessed,equivalences,directory):
            for index,candidate in enumerate(candidates):
                sid=min(candidate['nominees']);ss=[lookup[sid]];cs=[candidate]
                pairs=[{'source_id':sid,'candidate_id':candidate['id']}]
                result=call(f'nominate-{index}',mm.membership_request(ss,cs,pairs))
                batch=qualified_membership(call,ss,cs,pairs,result);members.append(batch)
                write(directory/'nominations'/f'{index}.json',batch)
            for index,(sid,name,expected) in enumerate(plan['comparison_cases']):
                cs=[selected[name]];ss=[lookup[sid]];pairs=[{'source_id':sid,'candidate_id':cs[0]['id']}]
                batch=qualified_membership(call,ss,cs,pairs,call(f'membership-{index}',mm.membership_request(ss,cs,pairs)))
                actual=batch['memberships'][0]['relation']=='supported'
                row={'source_id':sid,'candidate':name,'expected_support':expected,'actual_support':actual,'batch':batch,'passed':actual==expected}
                assessed.append(row);write(directory/'memberships'/f'{index}.json',row)
            for index,(left,right,expected) in enumerate(plan['equivalence_cases']):
                a,b=sorted((selected[left]['id'],selected[right]['id']));pairs=[{'a':a,'b':b}]
                req=cc.equivalence_request(sources,candidates,members,pairs)
                record=cc.bind(sources,candidates,members,pairs,call(f'equivalence-{index}',req))
                quals=[]
                for left_id,right_id in ((a,b),(b,a)):
                    left_c=next(c for c in candidates if c['id']==left_id);right_c=next(c for c in candidates if c['id']==right_id)
                    assessment=qualification_assessment(call,{'id':left_id,'text':left_c['text'],'parent':None},right_c)
                    quals.append({'from_candidate_id':left_id,'to_candidate_id':right_id,'assessment':assessment})
                record=cc.bind(sources,candidates,members,pairs,{'output':record['output']},quals)
                actual=record['relations'][0]['relation']=='equivalent'
                row={'left':left,'right':right,'expected_equivalent':expected,'actual_equivalent':actual,'record':record,'passed':actual==expected}
                equivalences.append(row);write(directory/'equivalences'/f'{index}.json',row)


def qualification_assessment(call,source,candidate):
    from commentscope.factory import qualification_ownership as qo
    if not hasattr(call,'shape_cache'):call.shape_cache={};call.assessment_cache={}
    text=candidate['text'];key=digest([source,text])
    if key not in call.assessment_cache:
        if text not in call.shape_cache:
            call.shape_cache[text]=pr.bind_shape(text,call('qualification-shape-'+digest(text)[:12],pr.shape_request(text)))
        shape=call.shape_cache[text];checks=[]
        if shape['status']=='complete':
            for detail in shape['details']:
                checks.append(pr.bind_detail(source,shape,detail,call('qualification-detail-'+key[:12]+'-'+detail['id'][:12],pr.detail_request(source,shape,detail))))
        witnesses=[qo.bind_pair(source,text,p,call('qualification-owner-'+digest([source,text,p])[:16],
            qo.pair_request(source,text,p))) for p in qo.pairs(source,text)]
        call.assessment_cache[key]=pr.assessment(source,shape,checks,qo.assessment(source,text,witnesses))
    return call.assessment_cache[key]


def qualified_membership(call,sources,candidates,pairs,result):
    primary=mm.bind(sources,candidates,pairs,result);quals=[]
    for row in primary['memberships']:
        d=row['decision']
        if d['relation']=='supported' and d['authorship']=='asserted_or_endorsed' and d['scope_preserved']=='yes':
            source=next(s for s in sources if s['id']==row['source_id']);candidate=next(c for c in candidates if c['id']==row['candidate_id'])
            quals.append({'source_id':source['id'],'candidate_id':candidate['id'],
                'assessment':qualification_assessment(call,source,candidate)})
    return mm.bind(sources,candidates,pairs,result,quals)


def owned_component(call,selected,lookup,directory):
    from commentscope.factory import explicit_discourse as ed, owned_arguments as oa
    # Fixed earlier automatic candidate texts exercise this adapter only. No
    # reviewed source labels enter metadata, membership, or alignment requests.
    candidates=[selected[k] for k in ('required','voluntary','conditional')]
    cores=[oa.bind_core(c,call('owned-core-'+c['id'][:12],oa.core_request(c))) for c in candidates]
    write(directory/'owned/cores.json',cores)
    records=[];members=[];graphs={};typed={};alignments={}
    for sid,source in sorted(lookup.items()):
        graph=ed.parse(source);graphs[sid]=graph;write(directory/'owned/graphs'/f'{sid}.json',graph)
        metadata=[oa.bind_metadata(graph,n,call('owned-metadata-'+sid+'-'+str(i),oa.metadata_request(graph,n)))
            for i,n in enumerate(graph['nodes'])]
        typed[sid]=metadata;write(directory/'owned/metadata'/f'{sid}.json',metadata)
        own=[]
        for c in candidates:
            pairs=[{'source_id':sid,'candidate_id':c['id']}]
            batch=qualified_membership(call,[source],[c],pairs,call('owned-member-'+sid+'-'+c['id'][:12],
                mm.membership_request([source],[c],pairs)))
            own.append(batch);members.append(batch)
        write(directory/'owned/memberships'/f'{sid}.json',own)
        needed=[c for c,b in zip(candidates,own,strict=True) if b['memberships'][0]['relation']=='supported']
        nodes={m['node_id']:m for m in metadata};aligned=[]
        for n in graph['nodes']:
            if n['kind']!='statement' or nodes[n['id']]['output']['authorship']!='asserted_or_endorsed':continue
            for c in needed:
                result=call('owned-align-'+sid+'-'+digest([n,c])[:12],oa.alignment_request(graph,n,c));quals=[]
                if result.get('output',{}).get('relation')=='equivalent':
                    quals=[qualification_assessment(call,{'id':n['id'],'text':n['span']['text'],'parent':None},c),
                        qualification_assessment(call,{'id':c['id'],'text':c['text'],'parent':None},{'text':n['span']['text']})]
                aligned.append(oa.bind_alignment(graph,n,c,result,quals))
        alignments[sid]=aligned;write(directory/'owned/alignments'/f'{sid}.json',aligned)
        if needed:
            active=[b for b in own if b['memberships'][0]['relation']=='supported']
            record=oa.declare(graph,needed,active,metadata,aligned)
            records.append(record);write(directory/'owned/records'/f'{sid}.json',record)
    comparisons=[]
    for sid,name in (('A','accountability'),('B','safety')):
        c=selected[name];source=lookup[sid]
        assessment=qualification_assessment(call,source,c)
        comparisons.append({'source_id':sid,'candidate':name,'assessment':assessment})
    write(directory/'owned/compound-checks.json',comparisons)
    write(directory/'owned/memberships.json',members)
    return {'source_count':len(graphs),'node_count':sum(len(g['nodes']) for g in graphs.values()),
        'records':len(records),'complete_records':sum(r['status']=='complete' for r in records),
        'metadata_count':sum(map(len,typed.values())),'full_G1_passed':False,'semantic_review_required':True,
        'agent_compilation_performed':False,'fact_verification_performed':False,
        'generated_argument_text':False,'code_owned_parents_and_conditions':True}


def clause_component(call,lookup,directory):
    from commentscope.factory import source_clause_graph as cg
    nodes=0
    for sid,source in sorted(lookup.items()):
        record=cg.bind(source,call('clauses-'+sid,cg.request(source)))
        if record['status']=='partial':
            record=cg.bind(source,call('clauses-extra-'+sid,cg.request(source,record)),record)
        write(directory/'clauses'/f'{sid}.json',record)
        nodes+=len(record['nodes'])
    return {'source_count':len(lookup),'node_count':nodes,'full_G1_passed':False,'semantic_review_required':True,
        'candidates_supplied_to_runtime':False,'agent_compilation_performed':False,'generated_assertion_text':False}


def tree_component(call,lookup,directory):
    from commentscope.factory import argument_trees as at
    nodes=0
    for sid,source in sorted(lookup.items()):
        record=at.bind(source,call('tree-'+sid,at.request(source)))
        if record['status']=='partial':
            record=at.bind(source,call('tree-extra-'+sid,at.request(source,record)),record)
        write(directory/'trees'/f'{sid}.json',record)
        nodes+=sum(1+len(p['grounds']) for p in record['positions'])
    return {'source_count':len(lookup),'node_count':nodes,'full_G1_passed':False,'semantic_review_required':True,
        'candidates_supplied_to_runtime':False,'agent_compilation_performed':False}


def argument_component(call,plan,selected,lookup,snapshot,directory):
    from commentscope.factory import source_arguments as sa, minimal_agents as ma
    from experiments.framed_agent_probe import runtime_probe
    # Component inputs are two automatically extracted propositions from the
    # prior run. This is never the automatic discovery or full G1 acceptance run.
    candidates=[selected['required'],selected['voluntary']];members=[];cores=[];records=[]
    for c in candidates:
        for sid in sorted(lookup):
            ss=[lookup[sid]];pairs=[{'source_id':sid,'candidate_id':c['id']}]
            batch=qualified_membership(call,ss,[c],pairs,call('arg-member-'+sid+'-'+c['id'][:10],mm.membership_request(ss,[c],pairs)))
            members.append(batch)
    write(directory/'argument-component/memberships.json',members)
    for c in candidates:
        cores.append(sa.bind_core(c,call('arg-core-'+c['id'][:10],sa.core_request(c))))
    rows=[r for b in members for r in b['memberships']]
    for sid in sorted(lookup):
        needed=[c for c in candidates if any(r['source_id']==sid and r['candidate_id']==c['id'] and r['relation']=='supported' for r in rows)]
        if not needed:continue
        batches=[b for b in members if any(r['source_id']==sid and r['candidate_id'] in {c['id'] for c in needed} and r['relation']=='supported' for r in b['memberships'])]
        ss=[lookup[sid]]
        record=sa.bind(ss,needed,batches,call('arguments-'+sid,sa.extraction_request(ss,needed,batches)))[0]
        if record['status']=='partial':
            record=sa.bind(ss,needed,batches,call('arguments-extra-'+sid,sa.extraction_request(ss,needed,batches,[record])),[record])[0]
        write(directory/'argument-component/extractions'/f'{sid}.json',record)
        req=sa.link_request(record)
        linked=sa.bind_links(record,call('dependencies-'+sid,req) if req else None)
        records.append(linked);write(directory/'argument-component/linked'/f'{sid}.json',linked)
    tasks=sa.audit_tasks(records,cores);audits=[]
    # One source at a time to keep comparison ownership clear. Capacity splitting
    # still applies; no original or candidate is truncated.
    from commentscope.providers.context_capacity import partition
    for sid in sorted({t['source_id'] for t in tasks}):
        own=[t for t in tasks if t['source_id']==sid]
        for offset in range(0,len(own),8):
            fits,holds=partition(own[offset:offset+8],lambda ts:sa.audit_request(records,cores,ts),measure)
            if holds:raise ValueError('Argument component audit capacity hold')
            for n,task in enumerate(fits):
                audits.append(sa.bind_audit(records,cores,task['items'],call(f'argument-audit-{sid}-{offset}-{n}',task['request'])))
    inputs=ma.prepare(snapshot,candidates,members,records,cores,audits,model=plan['classifier'])
    write(directory/'argument-component/cores.json',cores);write(directory/'argument-component/audits.json',audits)
    write(directory/'argument-component/agent-inputs.json',inputs)
    class Guarded:
        def call(self,stage,req):return call(stage,req)
    runtime=runtime_probe(inputs['bundle'],Guarded());write(directory/'argument-component/runtime.json',runtime)
    report={'profiles':len(inputs['compiled']['profiles']),'source_records':len(records),
        'runtime_turns':len(runtime['turns']),'all_histories_isolated':all(t['other_histories_unchanged'] for t in runtime['turns']),
        'full_G1_passed':False,'semantic_review_required':True,'fact_verification_not_run':True}
    write(directory/'argument-component/result.json',report)
    return report


def reused_content_memberships(path,sources,candidates,deployment):
    old=path.parent.parent;old_plan=read_json(old/'plan.json');done=read_json(old/'completed.json')
    if old_plan['deployment']!=deployment or done['plan_sha256']!=sha(old/'plan.json'):
        raise ValueError('Completed membership model/settings changed')
    batches=read_json(path);rows=mm.collect(sources,candidates,batches)
    expected={(s['id'],c['id']) for s in sources for c in candidates}
    if {(r['source_id'],r['candidate_id']) for r in rows}!=expected:
        raise ValueError('Completed membership source/candidate coverage changed')
    requests={}
    for p in sorted((old/'calls').glob('*content-member-*.request.json')):
        req=read_json(p);result=read_json(p.with_name(p.name.replace('.request.json','.result.json')))
        if req['plan_sha256']!=done['plan_sha256'] or req['request_sha256']!=digest(req['request']):
            raise ValueError('Completed request binding changed')
        if req['request_sha256'] in requests:raise ValueError('Ambiguous repeated completed request')
        requests[req['request_sha256']]=(req,result)
    for batch in batches:
        req=mm.membership_request(batch['sources'],batch['candidates'],batch['pairs'])
        prior,result=requests[digest(req)]
        if prior['request']!=req or result.get('errors') or result['output']!=batch['output']:
            raise ValueError('Membership lacks exact completed request/response')
    return batches,{'source_run':str(old),'plan_sha256':done['plan_sha256'],'memberships_sha256':sha(path),
                    'requests_validated':len(batches),'fresh_membership_calls':0,'full_G1_reuse':False}


def content_component(call,plan,selected,lookup,directory):
    from commentscope.factory import argument_content as ac
    candidates=[selected['required'],selected['voluntary']];members=[];needed={sid:[] for sid in lookup}
    if plan['reuse_memberships']:
        members,reuse=reused_content_memberships(Path(plan['reuse_memberships']),list(lookup.values()),candidates,plan['deployment'])
        write(directory/'content/membership-reuse.json',reuse)
    else:
        for c in candidates:
            for sid in sorted(lookup):
                ss=[lookup[sid]];pairs=[{'source_id':sid,'candidate_id':c['id']}]
                batch=qualified_membership(call,ss,[c],pairs,call('content-member-'+sid+'-'+c['id'][:10],mm.membership_request(ss,[c],pairs)))
                members.append(batch)
    for batch in members:
        for row in batch['memberships']:
            if row['relation']=='supported':needed[row['source_id']].append(next(c for c in candidates if c['id']==row['candidate_id']))
    write(directory/'content/memberships.json',members)
    extraction_count=unit_count=0
    for sid,targets in sorted(needed.items()):
        if not targets:continue
        source=lookup[sid]
        record=ac.bind_extraction(source,call('content-extract-'+sid,ac.extract_request(source)))
        if record['status']=='partial':
            record=ac.bind_extraction(source,call('content-extra-'+sid,ac.extract_request(source,record)),record)
        write(directory/'content/extractions'/f'{sid}.json',record);extraction_count+=1
        typed=[];roles=[]
        for unit in record['units']:
            typed.append(ac.bind_type(record,unit,call('content-type-'+sid+'-'+unit['local_id'],ac.type_request(record,unit))))
            for c in targets:
                roles.append(ac.bind_role(record,unit,c,call('content-role-'+sid+'-'+unit['local_id']+'-'+c['id'][:10],ac.role_request(record,unit,c))))
        write(directory/'content/types'/f'{sid}.json',typed);write(directory/'content/roles'/f'{sid}.json',roles)
        unit_count+=len(record['units'])
    report={'extraction_count':extraction_count,'unit_count':unit_count,'full_G1_passed':False,
            'semantic_review_required':True,'agent_compilation_performed':False}
    write(directory/'content/result.json',report);return report


def judgment_component(call,plan,selected,directory):
    from commentscope.factory import argument_content as ac, argument_judgments as aj
    old=Path(plan['content_run']);prior=read_json(old/'plan.json')
    if prior['deployment']!=plan['deployment'] or read_json(old/'completed.json')['plan_sha256']!=sha(old/'plan.json'):
        raise ValueError('Completed content model/plan changed')
    candidates=[selected['required'],selected['voluntary']]
    members=read_json(old/'content/memberships.json');needed={}
    for batch in members:
        for row in mm.validate_batch(batch):
            if row['relation']=='supported':needed.setdefault(row['source_id'],[]).append(row['candidate_id'])
    count=0
    for sid,cids in sorted(needed.items()):
        record=ac.validate_extraction(read_json(old/'content/extractions'/f'{sid}.json'))
        results=[]
        for unit in record['units']:
            typed=aj.bind(record,unit,call('judgment-type-'+sid+'-'+unit['local_id'],aj.type_request(record,unit)))
            roles=[]
            for c in candidates:
                if c['id'] in cids:
                    roles.append(aj.bind(record,unit,call('judgment-role-'+sid+'-'+unit['local_id'],aj.role_request(record,unit,c)),c))
            results.append({'unit':unit,'type':typed,'roles':roles});count+=1
        write(directory/'judgments'/f'{sid}.json',{'source':record['source'],'units':results})
    return {'unit_count':count,'source_count':len(needed),'full_G1_passed':False,'semantic_review_required':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('directory',type=Path);a.add_argument('--source',type=Path,required=True)
    a.add_argument('--mode',choices=['comparison','fidelity','requirements','arguments','runtime','content','judgments','trees','clauses','owned'],default='comparison')
    a.add_argument('--clause-controls',type=Path)
    a.add_argument('--content-run',type=Path)
    a.add_argument('--runtime-bundle',type=Path)
    a.add_argument('--reuse-memberships',type=Path)
    a.add_argument('--case-set',choices=['all','qualifier_positive'],default='all')
    a=sub.add_parser('run');a.add_argument('directory',type=Path)
    args=p.parse_args()
    if args.action=='prepare':prepare(args.directory,args.source,args.mode,args.runtime_bundle,args.reuse_memberships,args.case_set,args.content_run,args.clause_controls);print({'prepared':str(args.directory),'model_calls':0})
    else:run(args.directory)
