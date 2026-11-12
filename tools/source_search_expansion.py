"""Closed development expansion: fixed new pairs, exact reuse, one money owner."""
import argparse
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from html.parser import HTMLParser
import json,os,re,sqlite3,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'src'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from commentscope.factory import observation_reuse as reuse,minimal_membership as mm,minimal_pipeline,pipeline_stages
from commentscope.factory import raw_membership_verification as raw,argument_observations as obs,jev_membership,source_evidence_graph as graph,minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.factory.pipeline_work import PipelineWork,ModelResponseUnavailable
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import host_resources,openrouter_decisions as decisions
from commentscope.providers.generation_limits import allocate
from commentscope.providers.execution_lock import experiment_lock
from commentscope.agents.runtime_probe import runtime_probe,runtime_check,QUESTIONS
from commentscope.storage import write_json_exclusive as write
from experiments import remote_factory_pipeline as e
from tools import shared_factory_trial as shared
from tools.source_evidence_trial import resource_attempt
from tools.source_fidelity_continuation import saved_length

VERSION='registered-source-search-expansion-20261113-v1'
CONTEXT=('source-context','source-world','candidate-world','raw-candidate-route','qualification-inventory')
GRAPH=('source-evidence-proposal','source-evidence-observation','source-evidence-candidates')
FAMILIES=(*CONTEXT,'raw-own-evidence','qualification-detail','qualification-ownership','assertion-counterexample','core','core-fidelity',*GRAPH,'facts','runtime')
MAX_CALLS=1800
CAPS={**dict.fromkeys(FAMILIES,MAX_CALLS),'source-context':69,'source-world':69,'candidate-world':6,
      'raw-candidate-route':6,'raw-own-evidence':104,'core':6,'core-fidelity':6,
      'source-evidence-proposal':69,'source-evidence-observation':69,'source-evidence-candidates':88,'runtime':18,'membership-jev':1200}
TOOLS=('tools/source_search_expansion.py','tools/shared_factory_trial.py','tools/source_fidelity_continuation.py','tools/source_evidence_trial.py')


def refreshed_documents(documents,manifest):
    """Revalidate the same registered primary text; never edit facts or spans."""
    record=read_json(manifest);body=Path(record['body_file']);now=datetime.now(timezone.utc)
    if (record['version']!='same-document-primary-revalidation-20261113-v1' or len(documents)!=1
            or reuse.file_sha(body)!=record['body_sha256'] or digest(documents[0])!=record['old_document_sha256']
            or record['url']!=documents[0]['url'] or record['final_url']!='https://tietotarjotin.fi/api/node-cache/articles/158070'):
        raise ValueError('Exact registered primary document retrieval required')
    at=datetime.fromisoformat(record['retrieved_at'])
    if at.utcoffset() is None or not now-timedelta(days=1)<=at<=now:raise ValueError('Fresh aware retrieval time required')
    article=read_json(body)
    if (len(article)!=1 or article[0]['articleId']!='158070' or article[0]['title_en']!=documents[0]['title']
            or article[0]['publishDate']!=documents[0]['published_at']):raise ValueError('Primary article identity changed')
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for child in value.values():yield from strings(child)
        elif isinstance(value,list):
            for child in value:yield from strings(child)
    class Visible(HTMLParser):
        def __init__(self):super().__init__();self.text=[]
        def handle_data(self,value):self.text.append(value)
    parser=Visible();parser.feed(' '.join(t for k,v in article[0].items() if k.endswith('_en') for t in strings(v)))
    visible=' '.join(' '.join(parser.text).split())
    if any(' '.join(part.split()) not in visible for part in documents[0]['text'].splitlines() if part.strip()):
        raise ValueError('Frozen primary text is absent from current original')
    return [{**deepcopy(documents[0]),'retrieved_at':at.isoformat(),'expires_at':(at+timedelta(days=30)).isoformat()}]


def checked_pairs(proposal,old_search,candidates,registry):
    targets=set(proposal['candidate_ids']);known={c['id']:c for c in candidates}
    if not targets<=set(known) or len(targets)!=len(proposal['candidate_ids']):raise ValueError('Fixed unique known candidates required')
    pairs=proposal['new_pairs'];keys={(p['source_id'],p['candidate_id']) for p in pairs}
    old={(p['source_id'],p['candidate_id']) for p in old_search['pairs']}
    if (len(keys)!=len(pairs) or keys&old or any(s not in registry or c not in targets for s,c in keys)
            or len(pairs)!=proposal['new_pair_count'] or len({s for s,c in keys})!=proposal['new_source_count']):
        raise ValueError('New registered pair inventory changed or retries an old attempt')
    return deepcopy(pairs)


def selected_memberships(path,target_ids):
    selected=[]
    for batch in reuse.object_array(path):
        ids={r['candidate_id'] for r in batch['memberships']}
        if not ids&target_ids:continue
        if not ids<=target_ids or any(c['id'] not in target_ids for c in batch['candidates']):
            raise ValueError('Mixed batches require an explicit provenance-preserving projection')
        mm.validate_batch(batch);selected.append(batch)
    return selected


def history(policy,cutoff=None):
    with closing(sqlite3.connect(Path(policy['ledger']).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if cutoff is None:cutoff=db.execute('SELECT COALESCE(MAX(id),0) FROM calls').fetchone()[0]
        rows={t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ('policy','plans')}
        rows['calls']=db.execute('SELECT * FROM calls WHERE id<=? ORDER BY id',(cutoff,)).fetchall()
        for t in ('resolutions','receipt_bindings'):
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()
            rows[t]=db.execute('SELECT * FROM '+t+' WHERE call_id<=? ORDER BY call_id',(cutoff,)).fetchall() if exists else []
    return cutoff,digest(rows)


def window(auth,*,call_seconds=0,now=None):
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if start.utcoffset() is None or end.utcoffset() is None or not timedelta(0)<end-start<=timedelta(hours=4):raise ValueError('Finite expansion execution window required')
    if not start<= (now or datetime.now(timezone.utc)) <end-timedelta(seconds=call_seconds+3):raise TimeoutError('Expansion window expired')


def prepare(directory,proposal_file,c_run,policy_file,*,user_request,fact_refresh):
    directory=Path(directory).resolve();c_run=Path(c_run).resolve();proposal_file=Path(proposal_file).resolve();policy_file=Path(policy_file).resolve()
    if directory.exists() or not user_request.strip():raise ValueError('New immutable development execution required')
    proposal=read_json(proposal_file)
    for p,h in proposal['inputs'].items():
        if reuse.file_sha(p)!=h:raise ValueError('Original search evidence changed')
    parent=read_json(c_run/'plan.json');done=read_json(c_run/'completed.json')
    if done['plan_sha256']!=sha(c_run/'plan.json') or any(reuse.file_sha(c_run/p)!=h for p,h in done['artifacts'].items()):raise ValueError('Completed original C changed')
    documents=refreshed_documents(parent['documents'],fact_refresh)
    baseline=Path(proposal['original_run']);b=baseline/'artifacts';registry={sid:r['source'] for sid,r in read_json(b/'source-discourse.json').items()}
    candidates=read_json(b/'candidates.json');pairs=checked_pairs(proposal,read_json(b/'membership-search.json'),candidates,registry)
    targets=set(proposal['candidate_ids'])
    if (len(pairs),len({p['source_id'] for p in pairs}),len(targets),len(registry))!=(104,69,6,999):raise ValueError('Registered104/69/6/999 scope required')
    policy=read_json(policy_file);old_policy=read_json(baseline/'plan.json')['spend_policy'];owner=parent['authorization']['authorization']['money_owner']
    if (policy!={**old_policy,'maximum_usd':'150'} or owner['sha256']!=parent['spend_scope_sha256']
            or sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']):raise ValueError('Original financial owner/account changed')
    money=e.ledger(policy);account=money.summary();own=money.summary(plan_sha256=owner['sha256']);cutoff,history_sha=history(policy)
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled account blocks new work')
    metadata=e.key_metadata()
    if metadata['limit']!=150 or parent['deployment']!=e.remote.SOL or read_json(baseline/'plan.json')['membership_deployment']!=decisions.DEPLOYMENT:raise ValueError('Registered team limit/model roles changed')
    providers=dict(chat=e.provider_preflight(e.remote.SOL),membership=decisions.preflight(decisions.DEPLOYMENT))
    index=reuse.build_index([(baseline,set(CONTEXT)),(c_run,set((*GRAPH,'core','core-fidelity')))])
    directory.mkdir();frozen=directory/'fixed-inputs'
    def fixed(name,value):p=frozen/(name+'.json');write(p,value);return str(p)
    inputs={}
    files=dict(registry=fixed('registry',registry),candidates=fixed('candidates',[c for c in candidates if c['id'] in targets]),
        pairs=fixed('pairs',pairs),memberships=fixed('memberships',selected_memberships(b/'memberships.json',targets)),
        cache=fixed('original-observations',index),proposal=fixed('search-proposal',proposal),snapshot=fixed('snapshot',read_json(parent['snapshot'])))
    for p in files.values():inputs[p]=sha(p)
    for p in (proposal_file,policy_file,Path(fact_refresh),Path(read_json(fact_refresh)['body_file']),c_run/'plan.json',c_run/'completed.json',Path(owner['file']),*(ROOT/p for p in TOOLS)):inputs[str(p.resolve())]=reuse.file_sha(p)
    started=datetime.now(timezone.utc)
    auth=dict(version=VERSION,user_request=user_request,started_at=started.isoformat(),deadline=(started+timedelta(hours=4)).isoformat(),
        financial_owner=owner,opening_account=account,opening_owner=own,history_cutoff=cutoff,history_sha256=history_sha,
        maximum_new_physical_calls=MAX_CALLS,stage_caps=CAPS,key_observation=metadata,providers=providers,
        prior_C_deadline=parent['authorization']['authorization']['deadline'],new_execution_time=True,new_money_owner=False,retries=0,fallback=None)
    write(directory/'authorization.json',auth)
    plan={**deepcopy(parent),'artifact_kind':VERSION,'run_directory':str(directory),'files':files,'inputs':inputs,
        'authorization':dict(file=str(directory/'authorization.json'),sha256=sha(directory/'authorization.json')),
        'documents':documents,'fact_refresh':str(Path(fact_refresh).resolve()),
        'spend_policy':policy,'policy_file':str(policy_file),'spend_scope_sha256':owner['sha256'],'maximum_cost_usd':'150','subcap_usd':'150','opening_scope_charge_usd':'0',
        'deployment':e.remote.SOL,'verification_deployment':e.remote.SOL,'membership_judge_protocol':jev_membership.VERSION,'membership_deployment':decisions.DEPLOYMENT,
        'snapshot':files['snapshot'],'snapshot_sha256':sha(files['snapshot']),'code_sha256':source_code_hashes(),'cross_run_response_reuse':True,'formal_admission_eligible':False,
        'maximum_physical_requests':MAX_CALLS,'allowed_stage_families':list(FAMILIES)+['membership-jev'],
        'allowed_source_ids':sorted({p['source_id'] for p in pairs}),
        'f4_source_ids':sorted(set(parent['eligible_source_ids'])|{p['source_id'] for p in pairs}),
        'candidate_ids':sorted(targets),'source_evidence_protocol':graph.VERSION,'verification_policy':graph.VERIFICATION_POLICY}
    write(directory/'plan.json',plan);write(directory/'frozen.json',dict(plan_sha256=sha(directory/'plan.json')))
    guard(plan,full=True)
    return dict(directory=str(directory),new_pairs=104,sources=69,account=account,max_new_physical=MAX_CALLS,deadline=auth['deadline'],new_calls=0)


def guard(plan,*,call_seconds=0,full=False):
    directory=Path(plan['run_directory']);binding=plan['authorization'];auth=read_json(binding['file'])
    if (read_json(directory/'plan.json')!=plan or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or sha(binding['file'])!=binding['sha256'] or auth['version']!=VERSION or plan['artifact_kind']!=VERSION
            or source_code_hashes()!=plan['code_sha256'] or auth['maximum_new_physical_calls']!=MAX_CALLS or auth['stage_caps']!=CAPS):raise ValueError('Frozen source expansion execution changed')
    window(auth,call_seconds=call_seconds)
    for p,h in plan['inputs'].items():
        if full or p not in plan['files'].values():
            if reuse.file_sha(p)!=h:raise ValueError('Frozen expansion input/tool changed')
    owner=auth['financial_owner']
    if (plan['spend_scope_sha256']!=owner['sha256'] or sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']
            or plan['spend_policy']!=read_json(plan['policy_file']) or plan['spend_policy']['maximum_usd']!='150' or any(plan[k]!='150' for k in ('maximum_cost_usd','subcap_usd'))
            or plan['opening_scope_charge_usd']!='0' or plan['deployment']!=e.remote.SOL or plan['verification_deployment']!=e.remote.SOL
            or plan['membership_deployment']!=decisions.DEPLOYMENT or plan['membership_judge_protocol']!=jev_membership.VERSION
            or plan['source_evidence_protocol']!=graph.VERSION or plan['verification_policy']!=graph.VERIFICATION_POLICY
            or plan['formal_admission_eligible'] is not False or plan['cross_run_response_reuse'] is not True):raise ValueError('Role, finance or evidence contract changed')
    if full and sha(plan['snapshot'])!=plan['snapshot_sha256']:raise ValueError('Registered snapshot changed')
    for expiry in [plan['expires_at'],*(d['expires_at'] for d in plan['documents'])]:e.fact_checks.live(expiry)
    money=e.ledger(plan['spend_policy']);account=money.summary();own=money.summary(plan_sha256=plan['spend_scope_sha256'])
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled money blocks expansion')
    if Decimal(account['charged_usd'])<Decimal(auth['opening_account']['charged_usd']) or Decimal(own['charged_usd'])<Decimal(auth['opening_owner']['charged_usd']):raise ValueError('Historical money regressed')
    if own['calls']>auth['opening_owner']['calls']+MAX_CALLS:raise e.BudgetExhausted('Fixed physical request cap exceeded')
    return auth


def settled_hold(session,stage,request,save):
    result=saved_length(session,stage,request)
    save('settled-length/'+digest(request),dict(stage=stage,result_sha256=digest(result),result=result,automatic_retry=False))
    raise PriorRequestUnavailable('Proven settled length response remains failed without retry')


class Session(shared.Session):
    def __init__(self,directory,plan,dispatch,save):
        guard(plan,full=True)
        super().__init__(directory,plan,dispatch,authorization_guard=guard);self.save=save
        self.original=reuse.OriginalObservations(read_json(plan['files']['cache']),save);self.seen=set();self.counts=Counter()
        self.registry=read_json(plan['files']['registry']);self.targets=read_json(plan['files']['candidates'])
        self.pairs={(p['source_id'],p['candidate_id']) for p in read_json(plan['files']['pairs'])}
        for p in self.directory.joinpath('calls').glob('*.request.json'):
            stage=p.name.split('-',1)[1].removesuffix('.request.json');role=next((r for r in ('generation','verification') if stage.startswith(r+'-')),None)
            family=re.sub(r'-[a-f0-9]{20}$','',stage[len(role)+1:] if role else stage)
            q=read_json(p);self.seen.add((family,role or 'typed',q['request_sha256']));self.counts[family]+=1

    def admit(self,family,role,actual):
        key=(family,role,digest(actual))
        if key in self.seen:return
        if family not in CAPS or len(self.seen)>=MAX_CALLS or self.counts[family]>=CAPS[family]:raise e.BudgetExhausted('Registered stage/physical inventory exhausted')
        self.seen.add(key);self.counts[family]+=1

    def call(self,stage,request):
        guard(self.plan)
        stage=shared.mapped_stage(stage);family=re.sub(r'-[a-f0-9]{20}$','',stage)
        if family not in FAMILIES:raise ValueError('Chat stage outside expansion')
        role=e.remote.role(stage);key='generation' if role=='interaction' else role;deployment=self.plan['deployment' if key=='generation' else 'verification_deployment']
        if family in GRAPH and request['data']['ORIGINAL']['source_id'] not in self.plan['f4_source_ids']:raise ValueError('Source outside fixed F4 inventory')
        cached=self.original.lookup(family,request,deployment)
        if cached is not None:return cached
        actual=allocate(request,e.openrouter.generation_allocation(deployment,require_explicit=True));self.admit(family,key,actual)
        try:return super().call(stage,request)
        except ModelResponseUnavailable:
            if family not in GRAPH:raise
            return settled_hold(self,stage,request,self.save)

    def decide(self,stage,payload):
        data=payload['state']['READING_INPUT'];sid=data['ORIGINAL']['source_id'];text=data['CANDIDATE']['text']
        target=next((c for c in self.targets if c['text']==text),None)
        if target is None or (sid,target['id']) not in self.pairs or data['ORIGINAL']!=mc.packet(self.registry[sid]):raise ValueError('Typed membership outside registered new pair')
        self.admit('membership-jev','typed',payload);return super().decide(stage,payload)

    def embed(self,*args,**kwargs):raise ValueError('New embedding is outside source expansion')


def run(directory):
    directory=Path(directory).resolve()
    if (directory/'completed.json').exists():
        done=read_json(directory/'completed.json')
        if done['plan_sha256']!=sha(directory/'plan.json') or any(reuse.file_sha(directory/p)!=h for p,h in done['artifacts'].items()):raise ValueError('Completed expansion changed')
        return done['report']
    plan=read_json(directory/'plan.json');auth=guard(plan,full=True);e.check_quota(wait_for_fresh=False)
    with experiment_lock(directory),e.quota_watch():
        def save(name,value):
            p=directory/'artifacts'/(name+'.json')
            if not p.resolve().is_relative_to((directory/'artifacts').resolve()):raise ValueError('Invalid artifact path')
            if p.exists():
                if read_json(p)!=value:raise ValueError('Same execution artifact changed')
            else:write(p,value)
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch,save)
        registry=read_json(plan['files']['registry']);candidates=read_json(plan['files']['candidates']);pairs=read_json(plan['files']['pairs'])
        snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;old=read_json(plan['files']['memberships'])
        execution=PipelineWork(session,session.inspect,save,registry=registry,membership_mode='raw',verification_contract=raw.FULL_SCOPE,schedule=minimal_pipeline.SCHEDULE)
        execution.shared_typed=True;execution.argument_audit_protocol=obs.SHARED_TYPED_CHAT;execution.source_evidence_protocol=graph.VERSION
        execution.membership_judge_protocol=jev_membership.VERSION;execution.membership_evidence_protocol=raw.QUALIFIED_CONTEXT
        with host_resources.watch(resource_attempt(directory),plan['resource_policy'],host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
            new=execution.judge('membership-initial',pairs,candidates);save('new-memberships',new);memberships=old+new;save('memberships',memberships);save('candidates',candidates)
            result=pipeline_stages.arguments(snapshot,candidates,memberships,{},execution,discovery_mode='shared')
            inputs,checks=pipeline_stages.compile_agents(snapshot,candidates,memberships,result.arguments,result.cores,result.audits,
                lambda request:session.call('facts-'+digest(request)[:20],request),model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],source_policy='candidate_verified_subset')
            save('agent-inputs',inputs);save('fact-checks',checks)
            runtime=runtime_probe(inputs['bundle'],session,save_turn=lambda row:save('runtime/'+row['candidate_id']+'/'+row['question_id'],row));runtime_check(runtime,inputs['compiled']);save('runtime',runtime)
        save('errors',execution.errors);save('holds',execution.holds)
        guard(plan,full=True)
        if history(plan['spend_policy'],auth['history_cutoff'])!=(auth['history_cutoff'],auth['history_sha256']):raise ValueError('Historical financial rows changed')
        owner=session.money.summary(plan_sha256=plan['spend_scope_sha256'])
        report=dict(version=VERSION,development_reuse=True,fresh_factory_gate=False,selected_new_pairs=len(pairs),selected_new_sources=len(plan['allowed_source_ids']),
            new_relations=dict(Counter(r['relation'] for b in new for r in b['memberships'])),new_assessed_pairs=sum(len(b['memberships']) for b in new),
            profiles=[dict(candidate_id=p['candidate_id'],support_count=p['model_core_support_count'],entries=len(p['prompt_entries'])) for p in inputs['compiled']['profiles']],
            graph_records=len(result.arguments),complete_records=sum(r['status']=='complete' for r in result.arguments),runtime_turns=len(runtime['turns']),
            runtime_statuses=[dict(candidate_id=r['candidate_id'],question=r['question_id'],status=r['turn']['status']) for r in runtime['turns']],
            reused=len(session.original.reused),old_requests_held=len(session.original.blocked),new_calls=owner['calls']-auth['opening_owner']['calls'],
            new_charge_usd=str(Decimal(owner['charged_usd'])-Decimal(auth['opening_owner']['charged_usd'])),account=e.ledger(plan['spend_policy']).summary(),owner=owner,
            requires_source_review=True,quality_gate_passed=False,independent_human_gold=False)
        save('report',report)
        write(directory/'completed.json',dict(plan_sha256=sha(directory/'plan.json'),report=report,artifacts={str(p.relative_to(directory)):reuse.file_sha(p) for p in (directory/'artifacts').rglob('*.json')}))
        return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--key-file',type=Path);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--proposal',type=Path,required=True);q.add_argument('--C-run',dest='c_run',type=Path,required=True);q.add_argument('--policy',type=Path,required=True);q.add_argument('--user-request',required=True);q.add_argument('--fact-refresh',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('directory',type=Path);a=p.parse_args()
    if a.key_file:os.environ['OPENROUTER_API_KEY']=a.key_file.read_text(encoding='utf-8').strip()
    result=prepare(a.directory,a.proposal,a.c_run,a.policy,user_request=a.user_request,fact_refresh=a.fact_refresh) if a.action=='prepare' else run(a.directory)
    print(json.dumps(result,ensure_ascii=False),flush=True)
