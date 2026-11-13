"""Prepare a registered video once, then serve its source-derived perspectives.

All input comments are frozen. A new execution window never creates a new money
owner, clears historical charges, retries a failed request, or admits a gate.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import os,re,sys,threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from tools import shared_factory_trial as shared,source_search_expansion as previous
from commentscope.agents import seed_policy
from commentscope.agents.grounded_web import GroundedApp
from commentscope.factory import minimal_pipeline,perspective_mining,source_evidence_graph as graph
from commentscope.factory import raw_membership_verification as raw,argument_observations as obs,jev_membership,minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources
from commentscope.factory.pipeline_work import ModelResponseUnavailable
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.product.analysis import from_factory
from commentscope.product.app import ProductApp
from commentscope.product.web import ProductServer
from commentscope.providers import host_resources,openrouter_decisions as decisions
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from tools.serve_mvp import ASSETS

e=shared.executor
VERSION='prepared-video-product-20261113-v1'
MAX_CALLS=2400
SEARCH={'version':perspective_mining.VERSION,'sources_per_candidate':12,
        'maximum_pairs':384,'maximum_sources':96,'maximum_snapshot_comments':3000}
FAMILIES=(*previous.FAMILIES,'embedding','membership-jev','runtime-verification')
TOOLS=('tools/prepared_video_trial.py','tools/shared_factory_trial.py','tools/source_search_expansion.py')


def window(auth,*,call_seconds=0,allow_expired=False,now=None):
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if start.utcoffset() is None or end.utcoffset() is None or end-start!=timedelta(hours=7):
        raise ValueError('Fixed seven-hour prepared-video window required')
    if not allow_expired and not start<=(now or datetime.now(timezone.utc))<end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Prepared-video execution window expired')


def prepare(directory,snapshot_file,reference_file,owner_file,policy_file,*,user_request):
    directory=Path(directory).resolve()
    paths=[Path(p).resolve() for p in (snapshot_file,reference_file,owner_file,policy_file)]
    for path in [directory,*paths]:e.private(path)
    snapshot_file,reference_file,owner_file,policy_file=paths
    if directory.exists() or not isinstance(user_request,str) or not user_request.strip():
        raise ValueError('Fresh explicit registered-video request required')
    snapshot=load_snapshot(snapshot_file).snapshot;registry=sources(snapshot,include_video_context=True)
    if not 1<=len(snapshot.comments)<=3000:raise ValueError('Fixed registered comment pool required')
    owner=read_json(owner_file);policy=read_json(policy_file);refs=read_json(reference_file)
    if (policy['maximum_usd']!='150' or owner['maximum_usd']!='150'
            or owner.get('historical_charges_preserved') is not True
            or Path(owner['shared_policy_file']).resolve()!=policy_file
            or owner['shared_policy_sha256']!=sha(policy_file)):
        raise ValueError('Original cumulative150 owner and policy required')
    for doc in refs['documents']:e.fact_checks.live(doc['expires_at'])
    for selection in refs['selections']:
        doc=next(d for d in refs['documents'] if d['id']==selection['document_id'])
        e.fact_checks.bound_span(doc['text'],selection['span'])
    money=e.ledger(policy);account=money.summary();own=money.summary(plan_sha256=sha(owner_file))
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled existing account')
    key=e.key_metadata()
    if key['limit']!=150:raise ValueError('Observed team150 limit required')
    providers={'generation':e.provider_preflight(e.remote.SOL),'embedding':e.embedding_preflight(),
               'typed':decisions.preflight(decisions.DEPLOYMENT)}
    cutoff,history=previous.history(policy);now=datetime.now(timezone.utc)
    auth={'version':VERSION,'user_request':user_request,'started_at':now.isoformat(),
          'deadline':(now+timedelta(hours=7)).isoformat(),
          'financial_owner':{'file':str(owner_file),'sha256':sha(owner_file),'authorization':owner},
          'opening_account':account,'opening_owner':own,'history_cutoff':cutoff,'history_sha256':history,
          'maximum_new_physical_calls':MAX_CALLS,'new_money_owner':False,'retries':0,'fallback':None,
          'key_observation':key,'providers':providers}
    directory.mkdir();write(directory/'authorization.json',auth)
    files=[*paths,*(ROOT/p for p in TOOLS),*ASSETS]
    plan={'artifact_kind':VERSION,'run_directory':str(directory),'snapshot':str(snapshot_file),
          'snapshot_sha256':sha(snapshot_file),'scope_ids':sorted(registry),
          'input_comment_count':len(snapshot.comments),'canonical_population':len(registry),
          'video_id':snapshot.to_dict()['video']['video_id'],'expires_at':snapshot.usage.expires_at,
          'authorization':{'file':str(directory/'authorization.json'),'sha256':sha(directory/'authorization.json')},
          'spend_policy':policy,'policy_file':str(policy_file),'spend_scope_sha256':sha(owner_file),
          'maximum_cost_usd':'150','subcap_usd':'150','opening_scope_charge_usd':'0',
          'deployment':deepcopy(e.remote.SOL),'verification_deployment':deepcopy(e.remote.SOL),
          'embedding_deployment':deepcopy(e.remote.EMBEDDING),'membership_deployment':deepcopy(decisions.DEPLOYMENT),
          'membership_judge_protocol':jev_membership.VERSION,'membership_search_policy':deepcopy(SEARCH),
          'source_evidence_protocol':graph.VERSION,'admission_policy':deepcopy(seed_policy.POLICY),
          'verification_policy':graph.VERIFICATION_POLICY,'role_registry':deepcopy(e.remote.ROLES),
          'billing_policy':e.remote.WIRE_BUDGET,'classifier':e.model_identity(),'model_files':{},
          'resource_policy':host_resources.HTTP_API_POLICY,'artifact_storage_policy':e.api_resources.STORAGE_POLICY,
          'documents':refs['documents'],'selections':refs['selections'],
          'reference_file':str(reference_file),
          'limits':{'call_seconds':180,'analysis_seconds':None},'session_ttl_seconds':86400,
          'room_maximum_usd':'150','code_sha256':source_code_hashes(),
          'inputs':{str(p):sha(p) for p in files},'formal_admission_eligible':False,
          'quality_gate_passed':False,'cross_run_response_reuse':False}
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    e.archive_sources(directory,plan['code_sha256']);guard(plan)
    return {'input_comments':len(snapshot.comments),'canonical_sources':len(registry),
            'deadline':auth['deadline'],'account':account,'new_model_calls':0}


def guard(plan,*,call_seconds=0,allow_expired=False,require_settled=True):
    directory=Path(plan['run_directory']);binding=plan['authorization'];auth=read_json(binding['file'])
    e.private(directory)
    if (read_json(directory/'plan.json')!=plan
            or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or sha(binding['file'])!=binding['sha256'] or auth['version']!=VERSION
            or plan['artifact_kind']!=VERSION or plan['code_sha256']!=source_code_hashes()
            or any(sha(p)!=h for p,h in plan['inputs'].items())
            or auth['maximum_new_physical_calls']!=MAX_CALLS or auth['new_money_owner'] is not False
            or auth['retries']!=0 or auth['fallback'] is not None):
        raise ValueError('Frozen prepared-video source/code/authorization changed')
    window(auth,call_seconds=call_seconds,allow_expired=allow_expired)
    owner=auth['financial_owner']
    if (sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']
            or plan['spend_scope_sha256']!=owner['sha256']
            or plan['spend_policy']!=read_json(plan['policy_file'])
            or plan['spend_policy']['maximum_usd']!='150'
            or any(plan[k]!='150' for k in ('maximum_cost_usd','subcap_usd','room_maximum_usd'))
            or plan['opening_scope_charge_usd']!='0' or plan['admission_policy']!=seed_policy.POLICY
            or plan['membership_search_policy']!=SEARCH or plan['membership_judge_protocol']!=jev_membership.VERSION
            or plan['source_evidence_protocol']!=graph.VERSION or plan['deployment']!=e.remote.SOL
            or plan['verification_policy']!=graph.VERIFICATION_POLICY or plan['role_registry']!=e.remote.ROLES
            or plan['verification_deployment']!=e.remote.SOL or plan['embedding_deployment']!=e.remote.EMBEDDING
            or plan['membership_deployment']!=decisions.DEPLOYMENT or plan['model_files']!={}
            or plan['billing_policy']!=e.remote.WIRE_BUDGET
            or plan['resource_policy']!=host_resources.HTTP_API_POLICY
            or plan['artifact_storage_policy']!=e.api_resources.STORAGE_POLICY
            or plan['formal_admission_eligible'] is not False or plan['quality_gate_passed'] is not False
            or plan['cross_run_response_reuse'] is not False):
        raise ValueError('Prepared-video inherited finance or role contract changed')
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;registry=sources(snapshot,include_video_context=True)
    refs=read_json(plan['reference_file'])
    if (plan['documents']!=refs['documents'] or plan['selections']!=refs['selections']
            or plan['classifier']!=e.model_identity()
            or plan['limits']!={'call_seconds':180,'analysis_seconds':None}
            or plan['session_ttl_seconds']!=86400):
        raise ValueError('Prepared-video reference or runtime settings changed')
    if (sha(plan['snapshot'])!=plan['snapshot_sha256'] or sorted(registry)!=plan['scope_ids']
            or len(snapshot.comments)!=plan['input_comment_count']
            or len(registry)!=plan['canonical_population']
            or snapshot.to_dict()['video']['video_id']!=plan['video_id']):
        raise ValueError('Entire registered comment input must be preserved')
    account=e.ledger(plan['spend_policy']).summary()
    own=e.ledger(plan['spend_policy']).summary(plan_sha256=owner['sha256'])
    if require_settled and (account['reserved_calls'] or account['uncertain_calls']):
        raise e.BudgetExhausted('Unsettled existing account')
    if (Decimal(account['charged_usd'])<Decimal(auth['opening_account']['charged_usd'])
            or Decimal(own['charged_usd'])<Decimal(auth['opening_owner']['charged_usd'])):
        raise ValueError('Historical finance regressed')
    new=own['calls']-auth['opening_owner']['calls']
    if new<0 or new>MAX_CALLS or call_seconds and new>=MAX_CALLS:
        raise e.BudgetExhausted('Prepared-video physical request bound exhausted')
    return auth


class Session(shared.Session):
    def __init__(self,directory,plan,dispatch):
        if Path(directory).resolve()!=Path(plan['run_directory']).resolve():
            raise ValueError('Use the original prepared-video directory')
        guard(plan,allow_expired=True)
        super().__init__(directory,plan,dispatch,authorization_guard=guard)
        self.registry=sources(load_snapshot(Path(plan['snapshot'])).snapshot,include_video_context=True)
        self.allowed=set(plan['scope_ids']);self.seen=set();self.counts=Counter();self.runtime_lock=threading.Lock()
        for p in self.directory.joinpath('calls').glob('*.request.json'):
            self.seen.add(read_json(p)['request_sha256'])

    def admit(self,family,payload):
        identity=digest(payload)
        if identity in self.seen:return
        if family not in FAMILIES or len(self.seen)>=MAX_CALLS:
            raise e.BudgetExhausted('Unregistered or exhausted prepared-video dispatch')
        self.seen.add(identity);self.counts[family]+=1

    def call(self,stage,request):
        stage=shared.mapped_stage(stage);family=re.sub(r'-[a-f0-9]{20}$','',stage)
        if family not in previous.FAMILIES:raise ValueError('Unregistered chat role')
        if family in previous.GRAPH and request['data']['ORIGINAL']['source_id'] not in self.allowed:
            raise ValueError('Graph source outside registered comment pool')
        role=e.remote.role(stage);field='deployment' if role=='interaction' else 'verification_deployment'
        self.admit(family,allocate(request,e.openrouter.generation_allocation(self.plan[field],require_explicit=True)))
        try:return super().call(stage,request)
        except ModelResponseUnavailable:
            if family not in previous.GRAPH:raise
            return previous.settled_hold(self,stage,request,self.save)

    def decide(self,stage,payload):
        data=payload['state']['READING_INPUT'];sid=data['ORIGINAL']['source_id']
        candidate=next((c for c in self.pin('initial-candidates') if c['text']==data['CANDIDATE']['text']),None)
        search=self.pin('membership-search')
        if (sid not in self.allowed or candidate is None or data['ORIGINAL']!=mc.packet(self.registry[sid])
                or {'source_id':sid,'candidate_id':candidate['id']} not in search['pairs']
                or search['policy']!=SEARCH or len(search['pairs'])>SEARCH['maximum_pairs']
                or len({p['source_id'] for p in search['pairs']})>SEARCH['maximum_sources']):
            raise ValueError('Typed membership outside frozen selected source/candidate pairs')
        self.admit('membership-jev',payload)
        return super().decide(stage,payload)

    def pin(self,name):
        if name not in ('initial-candidates','membership-search'):raise ValueError('Unknown generated inventory')
        path=self.directory/'artifacts'/(name+'.json');binding=self.directory/'registered-generated'/(name+'.json')
        expected={'file_sha256':sha(path)}
        if binding.exists():
            if read_json(binding)!=expected:raise ValueError('Generated frozen inventory changed')
        else:write(binding,expected)
        return read_json(path)

    def embed(self,stage,texts):
        if stage=='sources':expected={sid:self.registry[sid]['text'] for sid in self.allowed}
        elif stage=='candidates':expected={c['id']:c['text'] for c in self.pin('initial-candidates')}
        else:raise ValueError('Unknown embedding stage')
        if texts!=expected:raise ValueError('Embedding outside exact frozen inventory')
        for batch in e.remote.batches(texts):
            self.admit('embedding',{'system':e.remote.VERSION,'data':{'input':[p['text'] for p in batch]},'schema':{},'max_tokens':1})
        return super().embed(stage,texts)

    def charged(self):
        return Decimal(self.money.summary(plan_sha256=self.plan['spend_scope_sha256'])['charged_usd'])

    def accounting(self,callback):
        with self.runtime_lock:
            before=self.charged()
            try:result=callback()
            except Exception as exc:
                exc.new_cost_usd=str(self.charged()-before);raise
            return {**result,'new_cost_usd':str(self.charged()-before)}

    def generate(self,stage,request):
        return self.accounting(lambda:self.call('runtime-'+digest([stage,request])[:20],request))

    def reservation(self,request):
        req=allocate(request,e.openrouter.generation_allocation(self.plan['deployment'],require_explicit=True))
        return str(self.checkpoints['generation'].base.budget.maximum_charge(req))

    def verify(self,stage,payload):
        decisions.validate_request(payload,self.plan['membership_deployment'])
        self.admit('runtime-verification',payload)
        def invoke():
            self.dispatch.check();e.check_quota();guard(self.plan,call_seconds=30);self.storage.check()
            with self.dispatch.remote_call():
                result=self.membership_checkpoint.call('runtime-verification-'+
                    decisions.wire_sha256(payload,decisions.DEPLOYMENT)[:20],payload,provider=self.membership_client.generate)
            self.storage.check();return result
        return self.accounting(invoke)


def completed(directory):
    directory=Path(directory);value=read_json(directory/'completed.json')
    if (value['plan_sha256']!=sha(directory/'plan.json')
            or any(sha(directory/p)!=h for p,h in value['artifacts'].items())):
        raise ValueError('Completed registered-video artifacts changed')
    return value


def run(directory):
    directory=Path(directory).resolve()
    if (directory/'completed.json').exists():return completed(directory)['report']
    plan=read_json(directory/'plan.json');auth=guard(plan);e.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),e.quota_watch():
        if (directory/'started.json').exists():raise ValueError('Interrupted execution requires reconciliation; no automatic retry')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan artifact changed')
            else:session.storage.before_write(value);write(path,value)
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch);session.save=save
        with host_resources.watch(directory/'resources'/'factory',plan['resource_policy'],
                host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
            output=minimal_pipeline.process(load_snapshot(Path(plan['snapshot'])).snapshot,
                session,session.embed,session.inspect,lambda req:session.call('facts-'+digest(req)[:20],req),
                model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],
                scope_ids=plan['scope_ids'],save=save,discovery_mode='shared',membership_mode='raw',
                verification_contract=raw.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT,
                agent_source_policy='candidate_verified_subset',membership_evidence_protocol=raw.QUALIFIED_CONTEXT,
                membership_judge_protocol=jev_membership.VERSION,membership_search_policy=SEARCH,
                source_evidence_protocol=graph.VERSION,admission_policy=seed_policy.POLICY)
            save('output',output)
        guard(plan)
        if previous.history(plan['spend_policy'],auth['history_cutoff'])!=(auth['history_cutoff'],auth['history_sha256']):
            raise ValueError('Historical financial rows changed')
        own=session.money.summary(plan_sha256=plan['spend_scope_sha256'])
        report={'input_comments':plan['input_comment_count'],'canonical_sources':plan['canonical_population'],
                'candidates':len(output['candidates']),'profiles':[{'candidate_id':p['candidate_id'],
                'support_count':p['model_core_support_count']} for p in output['agent_inputs']['compiled']['profiles']],
                'new_calls':own['calls']-auth['opening_owner']['calls'],
                'new_charge_usd':str(Decimal(own['charged_usd'])-Decimal(auth['opening_owner']['charged_usd'])),
                'account':e.ledger(plan['spend_policy']).summary(),'quality_gate_passed':False,
                'independent_human_gold':False,'requires_source_and_utility_review':True}
        save('report',report)
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),'report':report,
            'artifacts':{str(p.relative_to(directory)):sha(p) for p in (directory/'artifacts').rglob('*.json')}})
        return report


def build(directory):
    directory=Path(directory);completed(directory);plan=read_json(directory/'plan.json');guard(plan,allow_expired=True)
    analysis=from_factory(directory);dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch)
    def status():
        with dispatch.lock:
            if dispatch.remote_active:return 'busy'
        try:guard(plan,call_seconds=180)
        except TimeoutError:return 'cycle_deadline'
        except e.BudgetExhausted:return 'reconcile_required'
        pending=[p for p in (directory/'checkpoints').glob('*.intent.json')
                 if not p.with_name(p.name.replace('.intent.json','.result.json')).exists()]
        if pending:return 'reconcile_required'
        return 'ready'
    product=ProductApp(directory/'product.sqlite',[analysis],session.generate,
        session_ttl_seconds=plan['session_ttl_seconds'],room_maximum_usd=plan['room_maximum_usd'],
        reservation=session.reservation,decision=session.verify,
        decision_reservation=lambda:str(decisions.reservation(decisions.DEPLOYMENT)),
        revalidate=lambda:guard(plan,allow_expired=True,require_settled=False),generation_status=status)
    def legacy_provider(system,data,schema,*,max_tokens):
        import json
        value=session.generate('legacy',{'system':system,'data':data,'schema':schema,'max_tokens':max_tokens})
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value['output'])}}]}
    class Legacy(GroundedApp):
        def public(self,item):
            value=super().public(item);value['remote_status']=status()
            if value['remote_status']!='ready':value['can_ask']=False
            return value
    legacy=Legacy(analysis.bundle,directory/'legacy-sessions',provider=legacy_provider,
        revalidate=lambda:guard(plan))
    return product,legacy,session


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--key-file',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('directory',type=Path)
    for name in ('snapshot','reference','owner','policy'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--user-request',required=True)
    p=sub.add_parser('run');p.add_argument('directory',type=Path)
    p=sub.add_parser('serve');p.add_argument('directory',type=Path);p.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    if args.key_file:os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip()
    if args.action=='prepare':result=prepare(args.directory,args.snapshot,args.reference,args.owner,args.policy,user_request=args.user_request)
    elif args.action=='run':result=run(args.directory)
    else:
        with experiment_lock(args.directory):
            product,legacy,session=build(args.directory);server=ProductServer(product,legacy,args.port)
            print(json.dumps({'origin':'http://127.0.0.1:'+str(server.server_address[1]),'preview':'/mvp','quality_gate_passed':False}),flush=True)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:server.server_close();product.close()
        return
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
