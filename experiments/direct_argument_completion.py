"""Post-membership completion from full originals, without whole-source extraction."""
from copy import deepcopy

from commentscope.factory import direct_arguments as direct,argument_graph as graph
from commentscope.factory import candidate_completion as completion,grounded_factory,membership_policy,nli_fact_records
from commentscope.factory.automatic_contract import digest
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.providers import evidence_nli
from commentscope.storage import write_json_exclusive as write
from experiments.argument_graph_probe import members,allocate
from experiments.audit_model_compare import owned_server


def finish(proposal,selection,directory,plan,runner,relations):
    sources=members(proposal,selection,plan['membership_policy']);cd=directory/'candidates'/proposal['id']
    inv=direct.inventory(proposal['claims']['C'],sources)
    write(cd/'direct-inventory.json',inv)
    with owned_server(plan['deployments']['profile'],'baseline',cd/'profile-server'):
        def call(stage,req):return runner.call(stage,allocate(req,plan['profile_extra_tokens']))
        core_kind=graph.kind(call('core-kind',graph.type_request(proposal['claims']['C']['text'],sources)))
        if core_kind not in {'fact','value','prediction'}:return None,'core_'+core_kind
        req=direct.select_request(proposal['claims']['C'],sources)
        result=call('direct-ground-selection',req);chosen=direct.selection(result,inv)
        write(cd/'direct-selection.json',{'result':result,'selection':chosen})
        if chosen['status']=='defer':return None,chosen['reason']
        kinds={}
        for nid in chosen['node_ids']:
            n=inv['nodes'][nid]
            kinds[nid]=graph.kind(call('ground-kind',graph.type_request(n['text'],{n['source_id']:sources[n['source_id']]})))
        if any(k not in {'fact','value','prediction'} for k in kinds.values()):return None,'ground_type_unresolved'
        typed=direct.assemble(proposal,sources,core_kind,chosen,kinds);write(cd/'typed.json',typed)
        req=direct.audit_request(typed,sources);audited=call('argument-audit',req)
        passed=completion.audit_passed(typed,audited)
        write(cd/'argument-audit.json',{'request_sha256':digest(allocate(req,plan['profile_extra_tokens'])),
                                       'result':audited,'passed':passed})
        if not passed:return None,'argument_audit_failed'
    derived=[{**deepcopy(r),'claim':deepcopy(typed['claims']['C'])} for r in selection['rows']]
    if any(membership_policy.invocation(plan['membership_policy'],r['text'],r['claim'])!=r['request'] for r in derived):
        raise ValueError('Typing changed core target')
    details=direct.origin_details(typed,sources,plan['membership_policy']);actual={}
    if details:
        with owned_server(plan['deployments']['membership'],'baseline',cd/'detail-server'):
            actual=relations.judge(details,'detail-'+proposal['id'])
    write(cd/'details.json',{'rows':details,'actual':actual})
    if any(v!='supported' for v in actual.values()):return None,'selected_ground_not_supported_by_author'
    bundle=grounded_factory.bundle([typed],derived,selection['actual'],details,actual,
        expires_at=plan['expires_at'],model=plan['classifier'],documents=plan['documents'])
    packets=grounded_factory.fact_packets(bundle,plan['selections'])
    if packets:
        req=nli_fact_records.invocation(packets)
        result=runner.call('facts-'+proposal['id'],req,provider=evidence_nli.generate,maximum=plan['limits']['fact_seconds'])
        checked=nli_fact_records.records(packets,bundle['model'],result,batch_request=req)
        bundle['checks']=[{'claim_id':p['claim']['id'],'selections':plan['selections'],'record':r}
                          for p,r in zip(packets,checked,strict=True)]
    compiled=compile_inputs(bundle);write(cd/'bundle.json',bundle);write(cd/'compiled.json',compiled)
    if any(p['omitted'] for p in compiled['profiles']):return None,'selected_argument_would_be_omitted'
    return bundle,'screened_input' if compiled['profiles'] else 'fact_or_compilation_deferred'
