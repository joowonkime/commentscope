"""Fresh bounded first-video development: fixed sample and original money owner."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import hashlib,json,os,re,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))
from tools import source_search_expansion as previous,shared_factory_trial as shared
from commentscope.factory import minimal_pipeline,perspective_mining,source_evidence_graph as graph
from commentscope.factory import raw_membership_verification as raw,argument_observations as obs,jev_membership,minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources
from commentscope.factory.pipeline_work import ModelResponseUnavailable
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import host_resources,openrouter_decisions as decisions
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.agents.runtime_probe import QUESTIONS as STANDARD,runtime_check

e=shared.executor
VERSION='first-functional-video-20261113-v1'
VIDEO='RrFaNO3rTaA'
SEARCH=dict(version=perspective_mining.VERSION,sources_per_candidate=12,maximum_pairs=192,maximum_sources=48,maximum_snapshot_comments=240)
MAX_CALLS=1200
CAPS={**dict.fromkeys(previous.FAMILIES,MAX_CALLS),'embedding':16,'source-context':48,'source-world':48,
      'candidate-world':32,'core':64,'core-fidelity':32,'raw-candidate-route':32,'raw-own-evidence':192,
      'source-evidence-proposal':48,'source-evidence-observation':48,'source-evidence-candidates':48,'runtime':224,'membership-jev':800}
QUESTIONS=[*deepcopy(STANDARD),
 dict(id='work_hours',text='Does this position mean four ten-hour days or a thirty-two-hour week? Which does its evidence actually state?'),
 dict(id='sectors',text='Would this position apply to grocery stores, hospitals, and customer-facing work? Which restrictions are actually stated?'),
 dict(id='objections',text="What objection or limitation is actually present in this position's own sources?"),
 dict(id='guaranteed_productivity',text='What precise percentage productivity gain is guaranteed for every industry?')]
TOOLS=('tools/first_functional_video.py','tools/shared_factory_trial.py','tools/source_search_expansion.py','tools/source_fidelity_continuation.py','tools/source_evidence_trial.py')


def scope(registry):
    def ordered(root):return sorted((sid for sid,s in registry.items() if (s['parent'] is None)==root),key=lambda sid:hashlib.sha256(('functional-fourday-v1:'+sid).encode()).hexdigest())
    roots,replies=ordered(True),ordered(False)
    if len(roots)<80 or len(replies)<40:raise ValueError('Fixed root/reply development and held-out inventory unavailable')
    return sorted(roots[:64]+replies[:32]),sorted(roots[64:80]+replies[32:40])


def window(auth,*,call_seconds=0,now=None):
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if start.utcoffset() is None or end.utcoffset() is None or end-start!=timedelta(hours=3):raise ValueError('Fixed three-hour grant required')
    if not start<=(now or datetime.now(timezone.utc))<end-timedelta(seconds=call_seconds+3):raise TimeoutError('First-video window expired')


def prepare(directory,snapshot_file,scope_file,reference_file,template_file,policy_file,*,user_request):
    directory=Path(directory).resolve();paths=[Path(p).resolve() for p in (snapshot_file,scope_file,reference_file,template_file,policy_file)]
    snapshot_file,scope_file,reference_file,template_file,policy_file=paths
    if directory.exists() or not user_request.strip():raise ValueError('Fresh explicitly requested video execution required')
    snapshot=load_snapshot(snapshot_file).snapshot;registry=sources(snapshot,include_video_context=True);selected,held=scope(registry);selection=read_json(scope_file)
    if (selection['video_id']!=VIDEO or selected!=selection['processing_ids'] or held!=selection['holdout_ids']
            or selection['source_snapshot_sha256']!=sha(snapshot_file) or len(registry)>240):raise ValueError('Registered96/24 first-video inputs changed')
    # Video identity comes from the snapshot, not just the external selection note.
    if snapshot.to_dict()['video']['video_id']!=VIDEO:raise ValueError('Different video cannot borrow this grant')
    template=read_json(template_file);old=read_json(template_file.parent/'completed.json')
    if old['plan_sha256']!=sha(template_file):raise ValueError('Original configuration completion changed')
    owner=template['authorization']['authorization']['money_owner'];policy=read_json(policy_file);refs=read_json(reference_file)
    if (sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']
            or policy['maximum_usd']!='150' or {k:v for k,v in policy.items() if k!='maximum_usd'}!={k:v for k,v in template['spend_policy'].items() if k!='maximum_usd'}):raise ValueError('Original150account/owner required')
    for doc in refs['documents']:e.fact_checks.live(doc['expires_at'])
    for ref in refs['selections']:
        doc=next(d for d in refs['documents'] if d['id']==ref['document_id']);e.fact_checks.bound_span(doc['text'],ref['span'])
    money=e.ledger(policy);account=money.summary();own=money.summary(plan_sha256=owner['sha256'])
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled existing account blocks execution')
    key=e.key_metadata()
    if key['limit']!=150:raise ValueError('Observed team150 limit required')
    providers=dict(chat=e.provider_preflight(e.remote.SOL),embedding=e.embedding_preflight(),membership=decisions.preflight(decisions.DEPLOYMENT))
    cutoff,history=previous.history(policy);now=datetime.now(timezone.utc)
    auth=dict(version=VERSION,user_request=user_request,started_at=now.isoformat(),deadline=(now+timedelta(hours=3)).isoformat(),
        financial_owner=owner,opening_account=account,opening_owner=own,history_cutoff=cutoff,history_sha256=history,
        maximum_new_physical_calls=MAX_CALLS,stage_caps=CAPS,new_money_owner=False,retries=0,fallback=None,key_observation=key,providers=providers)
    directory.mkdir();write(directory/'authorization.json',auth)
    inputs={str(p):sha(p) for p in [*paths,template_file.parent/'completed.json',Path(owner['file']),*(ROOT/t for t in TOOLS)]}
    plan=dict(artifact_kind=VERSION,run_directory=str(directory),mode='development',gate='first-functional-video',video_id=VIDEO,
        snapshot=str(snapshot_file),snapshot_sha256=sha(snapshot_file),scope_ids=selected,holdout_ids=held,scope_file=str(scope_file),
        processing_count=96,canonical_population=len(registry),expires_at=snapshot.usage.expires_at,
        authorization=dict(file=str(directory/'authorization.json'),sha256=sha(directory/'authorization.json')),
        spend_policy=policy,policy_file=str(policy_file),spend_scope_sha256=owner['sha256'],maximum_cost_usd='150',subcap_usd='150',opening_scope_charge_usd='0',
        deployment=deepcopy(e.remote.SOL),verification_deployment=deepcopy(e.remote.SOL),embedding_deployment=deepcopy(e.remote.EMBEDDING),
        membership_deployment=deepcopy(decisions.DEPLOYMENT),membership_judge_protocol=jev_membership.VERSION,role_registry=deepcopy(e.remote.ROLES),
        source_evidence_protocol=graph.VERSION,verification_policy=graph.VERIFICATION_POLICY,membership_search_policy=SEARCH,
        billing_policy=e.remote.WIRE_BUDGET,classifier=e.model_identity(),reference_file=str(reference_file),documents=refs['documents'],selections=refs['selections'],
        model_files={},resource_policy=host_resources.HTTP_API_POLICY,artifact_storage_policy=e.api_resources.STORAGE_POLICY,
        limits=dict(call_seconds=180,analysis_seconds=None),questions=QUESTIONS,code_sha256=source_code_hashes(),inputs=inputs,
        formal_admission_eligible=False,quality_gate_passed=False,cross_run_response_reuse=False)
    write(directory/'plan.json',plan);write(directory/'frozen.json',dict(plan_sha256=sha(directory/'plan.json')));guard(plan)
    return dict(scope=96,holdout=24,canonical_population=len(registry),maximum_search_pairs=192,maximum_search_sources=48,account=account,new_model_calls=0,deadline=auth['deadline'])


def guard(plan,*,call_seconds=0):
    directory=Path(plan['run_directory']);binding=plan['authorization'];auth=read_json(binding['file'])
    if (read_json(directory/'plan.json')!=plan or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or sha(binding['file'])!=binding['sha256'] or auth['version']!=VERSION or plan['artifact_kind']!=VERSION
            or plan['code_sha256']!=source_code_hashes() or any(previous.reuse.file_sha(p)!=h for p,h in plan['inputs'].items())
            or auth['maximum_new_physical_calls']!=MAX_CALLS or auth['stage_caps']!=CAPS or auth['new_money_owner'] is not False or auth['retries']!=0 or auth['fallback'] is not None):raise ValueError('Frozen first-video authorization/input/code changed')
    window(auth,call_seconds=call_seconds);owner=auth['financial_owner'];selected=read_json(plan['scope_file']);refs=read_json(plan['reference_file'])
    if (plan['spend_scope_sha256']!=owner['sha256'] or sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']
            or plan['spend_policy']!=read_json(plan['policy_file']) or plan['spend_policy']['maximum_usd']!='150'
            or any(plan[k]!='150' for k in ('maximum_cost_usd','subcap_usd')) or plan['opening_scope_charge_usd']!='0'
            or plan['deployment']!=e.remote.SOL or plan['verification_deployment']!=e.remote.SOL or plan['embedding_deployment']!=e.remote.EMBEDDING
            or plan['membership_deployment']!=decisions.DEPLOYMENT or plan['membership_judge_protocol']!=jev_membership.VERSION
            or plan['role_registry']!=e.remote.ROLES or plan['billing_policy']!=e.remote.WIRE_BUDGET or plan['classifier']!=e.model_identity()
            or plan['documents']!=refs['documents'] or plan['selections']!=refs['selections'] or plan['limits']!=dict(call_seconds=180,analysis_seconds=None)
            or plan['source_evidence_protocol']!=graph.VERSION or plan['verification_policy']!=graph.VERIFICATION_POLICY or plan['membership_search_policy']!=SEARCH
            or plan['resource_policy']!=host_resources.HTTP_API_POLICY or plan['artifact_storage_policy']!=e.api_resources.STORAGE_POLICY
            or plan['questions']!=QUESTIONS or plan['model_files']!={} or plan['formal_admission_eligible'] is not False or plan['quality_gate_passed'] is not False
            or plan['cross_run_response_reuse'] is not False or plan['video_id']!=VIDEO or plan['processing_count']!=96 or len(set(plan['scope_ids']))!=96
            or plan['scope_ids']!=selected['processing_ids'] or plan['holdout_ids']!=selected['holdout_ids']
            or len(set(plan['holdout_ids']))!=24 or set(plan['scope_ids'])&set(plan['holdout_ids'])):raise ValueError('Registered scope/roles/finance/quality changed')
    for expiry in [plan['expires_at'],*(d['expires_at'] for d in plan['documents'])]:e.fact_checks.live(expiry)
    account=e.ledger(plan['spend_policy']).summary();own=e.ledger(plan['spend_policy']).summary(plan_sha256=plan['spend_scope_sha256'])
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled financial state stops work')
    if Decimal(account['charged_usd'])<Decimal(auth['opening_account']['charged_usd']) or Decimal(own['charged_usd'])<Decimal(auth['opening_owner']['charged_usd']):raise ValueError('Historical charge regressed')
    if own['calls']>auth['opening_owner']['calls']+MAX_CALLS:raise e.BudgetExhausted('Physical request bound exhausted')
    return auth


class Session(shared.Session):
    def __init__(self,directory,plan,dispatch,save):
        guard(plan);super().__init__(directory,plan,dispatch,authorization_guard=guard)
        self.save=save;self.registry=sources(load_snapshot(Path(plan['snapshot'])).snapshot,include_video_context=True);self.allowed=set(plan['scope_ids']);self.seen=set();self.counts=Counter()
        for f in self.directory.joinpath('calls').glob('*.request.json'):
            stage=f.name.split('-',1)[1].removesuffix('.request.json');role=next((r for r in ('generation','verification','embedding') if stage.startswith(r+'-')),'typed')
            family='embedding' if role=='embedding' else re.sub(r'-[a-f0-9]{20}$','',stage[len(role)+1:] if role!='typed' else stage)
            self.seen.add((family,role,read_json(f)['request_sha256']));self.counts[family]+=1

    def admit(self,family,role,actual):
        key=(family,role,digest(actual))
        if key in self.seen:return
        if family not in CAPS or len(self.seen)>=MAX_CALLS or self.counts[family]>=CAPS[family]:raise e.BudgetExhausted('Fixed physical/stage bound exhausted')
        self.seen.add(key);self.counts[family]+=1

    def pin(self,name):
        f=self.directory/'artifacts'/(name+'.json');binding=self.directory/'registered-generated'/(name+'.json');value=dict(file_sha256=sha(f))
        if binding.exists():
            if read_json(binding)!=value:raise ValueError('Generated fixed execution inventory changed')
        else:write(binding,value)
        return read_json(f)

    def call(self,stage,request):
        stage=shared.mapped_stage(stage);family=re.sub(r'-[a-f0-9]{20}$','',stage)
        if family not in previous.FAMILIES:raise ValueError('Unregistered chat family')
        if family in previous.GRAPH and request['data']['ORIGINAL']['source_id'] not in self.allowed:raise ValueError('Graph source outside processing96')
        role=e.remote.role(stage);key='generation' if role=='interaction' else role;deployment=self.plan['deployment' if key=='generation' else 'verification_deployment']
        actual=allocate(request,e.openrouter.generation_allocation(deployment,require_explicit=True));self.admit(family,key,actual)
        try:return super().call(stage,request)
        except ModelResponseUnavailable:
            if family not in previous.GRAPH:raise
            return previous.settled_hold(self,stage,request,self.save)

    def decide(self,stage,payload):
        data=payload['state']['READING_INPUT'];sid=data['ORIGINAL']['source_id'];text=data['CANDIDATE']['text'];cs=self.pin('initial-candidates');search=self.pin('membership-search')
        c=next((c for c in cs if c['text']==text),None)
        if (sid not in self.allowed or c is None or data['ORIGINAL']!=mc.packet(self.registry[sid])
                or {'source_id':sid,'candidate_id':c['id']} not in search['pairs'] or search['policy']!=SEARCH
                or len(search['pairs'])>SEARCH['maximum_pairs'] or len({p['source_id'] for p in search['pairs']})>SEARCH['maximum_sources']):raise ValueError('Typed packet outside registered video search')
        self.admit('membership-jev','typed',payload);return super().decide(stage,payload)

    def embed(self,stage,texts):
        if stage=='sources':expected={sid:self.registry[sid]['text'] for sid in self.allowed}
        elif stage=='candidates':expected={c['id']:c['text'] for c in self.pin('initial-candidates')}
        else:raise ValueError('Unregistered embedding stage')
        if texts!=expected:raise ValueError('Embedding outside exact registered inventory')
        for batch in e.remote.batches(texts):
            req=dict(system=e.remote.VERSION,data={'input':[p['text'] for p in batch]},schema={},max_tokens=1);self.admit('embedding','embedding',req)
        return super().embed(stage,texts)


def probe(bundle,runner,save):
    from commentscope.agents.grounded_inputs import compile_inputs
    compiled=compile_inputs(bundle);sessions={};rows=[]
    def provider(system,data,schema,*,max_tokens):
        req=dict(system=system,data=data,schema=schema,max_tokens=max_tokens);result=runner.call('runtime-'+digest(req)[:20],req)
        return {'choices':[{'message':{'content':json.dumps(result['output'])},'finish_reason':'stop'}]}
    groups={'standard':QUESTIONS[:3],'functional':QUESTIONS[3:]}
    for profile in compiled['profiles']:
        for group in groups:sessions[(profile['candidate_id'],group)]=GroundedSession(bundle,profile['candidate_id'],provider=provider)
    for key,session in sessions.items():
        cid,group=key
        for q in groups[group]:
            before={k:digest(v.history) for k,v in sessions.items() if k!=key};turn=session.ask(q['text'])
            row=dict(candidate_id=cid,question_id=q['id'],session_group=group,turn=turn,other_histories_unchanged=all(digest(sessions[k].history)==h for k,h in before.items()));rows.append(row);save('runtime/'+cid+'/'+q['id'],row)
            if turn['status']=='error':raise ValueError('Actual runtime error persisted; no automatic retry')
    result=dict(all_compiled_candidate_ids=[p['candidate_id'] for p in compiled['profiles']],turns=rows,independent_session_groups=list(groups),quality_gate_passed=False,requires_semantic_review=True);runtime_check(result,compiled,questions=QUESTIONS);return result


def run(directory):
    directory=Path(directory).resolve()
    if (directory/'completed.json').exists():
        done=read_json(directory/'completed.json')
        if done['plan_sha256']!=sha(directory/'plan.json') or any(previous.reuse.file_sha(directory/p)!=h for p,h in done['artifacts'].items()):raise ValueError('Completed video execution changed')
        return done['report']
    plan=read_json(directory/'plan.json');auth=guard(plan);e.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),e.quota_watch():
        def save(name,value):
            f=directory/'artifacts'/(name+'.json')
            if not f.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if f.exists():
                if read_json(f)!=value:raise ValueError('Same execution artifact changed')
            else:write(f,value)
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch,save)
        with host_resources.watch(previous.resource_attempt(directory),plan['resource_policy'],host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
            output=minimal_pipeline.process(load_snapshot(Path(plan['snapshot'])).snapshot,session,session.embed,session.inspect,
                lambda req:session.call('facts-'+digest(req)[:20],req),model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],
                scope_ids=plan['scope_ids'],save=save,discovery_mode='shared',membership_mode='raw',verification_contract=raw.FULL_SCOPE,
                argument_audit_protocol=obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset',membership_evidence_protocol=raw.QUALIFIED_CONTEXT,
                membership_judge_protocol=jev_membership.VERSION,membership_search_policy=SEARCH,source_evidence_protocol=graph.VERSION)
            save('output',output);runtime=probe(output['agent_inputs']['bundle'],session,save);save('runtime',runtime)
        guard(plan)
        if previous.history(plan['spend_policy'],auth['history_cutoff'])!=(auth['history_cutoff'],auth['history_sha256']):raise ValueError('Historical finance changed')
        owner=session.money.summary(plan_sha256=plan['spend_scope_sha256']);compiled=output['agent_inputs']['compiled'];search=read_json(directory/'artifacts/membership-search.json')
        report=dict(version=VERSION,processing_count=96,holdout_count=24,candidates=len(output['candidates']),selected_pairs=len(search['pairs']),selected_sources=len({p['source_id'] for p in search['pairs']}),
            profiles=[dict(candidate_id=p['candidate_id'],support_count=p['model_core_support_count'],entries=len(p['prompt_entries'])) for p in compiled['profiles']],
            runtime_turns=len(runtime['turns']),runtime_statuses=[dict(candidate_id=r['candidate_id'],question=r['question_id'],status=r['turn']['status']) for r in runtime['turns']],
            binding_errors=len(output['errors']),holds=len(output['capacity_holds']),new_calls=owner['calls']-auth['opening_owner']['calls'],
            new_charge_usd=str(Decimal(owner['charged_usd'])-Decimal(auth['opening_owner']['charged_usd'])),new_confirmed_usd=str(Decimal(owner['confirmed_usd'])-Decimal(auth['opening_owner']['confirmed_usd'])),
            new_conservative_usd=str(Decimal(owner['conservative_usd'])-Decimal(auth['opening_owner']['conservative_usd'])),account=e.ledger(plan['spend_policy']).summary(),owner=owner,
            quality_gate_passed=False,fresh_factory_gate=False,independent_human_gold=False,requires_source_and_utility_review=True)
        save('report',report);write(directory/'completed.json',dict(plan_sha256=sha(directory/'plan.json'),report=report,artifacts={str(p.relative_to(directory)):previous.reuse.file_sha(p) for p in (directory/'artifacts').rglob('*.json')}));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--key-file',type=Path);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('directory',type=Path)
    for name in ('snapshot','scope','reference','template','policy'):q.add_argument('--'+name,type=Path,required=True)
    q.add_argument('--user-request',required=True);q=sub.add_parser('run');q.add_argument('directory',type=Path);a=p.parse_args()
    if a.key_file:os.environ['OPENROUTER_API_KEY']=a.key_file.read_text().strip()
    result=prepare(a.directory,a.snapshot,a.scope,a.reference,a.template,a.policy,user_request=a.user_request) if a.action=='prepare' else run(a.directory)
    print(json.dumps(result,ensure_ascii=False),flush=True)
