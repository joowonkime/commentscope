"""Rebuild saved verified evidence for seeded dialogue, then bounded product QA.

Rebuild is entirely offline. A fresh execution window uses the existing account
and immutable financial owner; historical runs and charges are never reopened.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json,os,secrets,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))
from tools import first_functional_video as previous
from commentscope.agents import seed_policy
from commentscope.factory import minimal_agents
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.product.analysis import from_factory
from commentscope.product.app import ProductApp
from commentscope.providers import host_resources,openrouter_decisions as decisions,typed_membership_runner
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write

e=previous.e
VERSION=seed_policy.VERSION+'/product-trial'
MAX_CALLS=48
QUESTIONS=[
    'What position do you represent, and what conditions must be preserved?',
    'Develop a possible argument for this position. Distinguish it from the original commenters\' own reasons.',
    'What does the prepared UK research actually establish about a four-day week, and what does it not establish?',
    'What precise percentage productivity gain is guaranteed for every industry?']
GROUP_QUESTION='Discuss the strongest objection to your position and respond to the other perspectives without inventing comment support.'
ASSETS=tuple(ROOT/'src/commentscope/product'/name for name in ('mvp.html','mvp.js','mvp.css'))


def rebuild(directory,original,reference):
    directory=Path(directory).resolve();original=Path(original).resolve();reference=Path(reference).resolve()
    if directory.exists():raise ValueError('Fresh offline rebuild directory required')
    old=read_json(original/'plan.json');done=read_json(original/'completed.json')
    if (done['plan_sha256']!=sha(original/'plan.json') or
            any(sha(original/p)!=h for p,h in done['artifacts'].items()) or
            sha(old['snapshot'])!=old['snapshot_sha256']):raise ValueError('Saved execution evidence changed')
    output=read_json(original/'artifacts/output.json');refs=read_json(reference)
    prepared=minimal_agents.prepare(load_snapshot(Path(old['snapshot'])).snapshot,
        output['candidates'],output['memberships'],output['arguments'],output['cores'],output['audits'],
        model=old['classifier'],documents=refs['documents'],checks=output['agent_inputs']['bundle']['checks'],
        source_policy=output.get('agent_source_policy','all_members'),admission_policy=seed_policy.POLICY,
        reference_selections=refs['selections'])
    rebuilt={**output,'artifact_kind':VERSION+'/rebuild','agent_inputs':prepared,
             'admission_policy':deepcopy(seed_policy.POLICY),'quality_gate_passed':False,
             'reused_upstream_verdicts':True,'fresh_upstream_inference':False}
    inputs={str(p):sha(p) for p in (original/'plan.json',original/'completed.json',
        original/'artifacts/output.json',Path(old['snapshot']),reference)}
    plan={'artifact_kind':VERSION+'/rebuild','original_run':str(original),'inputs':inputs,
          'snapshot':old['snapshot'],'snapshot_sha256':old['snapshot_sha256'],
          'scope_ids':old['scope_ids'],'canonical_population':old['canonical_population'],
          'reference_file':str(reference),'admission_policy':deepcopy(seed_policy.POLICY),
          'new_model_calls':0,'quality_gate_passed':False,'code_sha256':source_code_hashes()}
    write(directory/'plan.json',plan);write(directory/'artifacts/agent-inputs.json',prepared)
    write(directory/'artifacts/output.json',rebuilt)
    analysis=from_factory(directory)
    write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),
        'artifacts':{str(p.relative_to(directory)):sha(p) for p in (directory/'artifacts').glob('*.json')},
        'new_model_calls':0,'profiles':analysis.public()['perspectives'],'quality_gate_passed':False})
    return {'profiles':analysis.public()['perspectives'],'new_model_calls':0}


def prepare(directory,rebuild_run,*,user_request):
    directory=Path(directory).resolve();rebuild_run=Path(rebuild_run).resolve()
    if directory.exists() or not user_request.strip():raise ValueError('Fresh explicit execution required')
    saved=read_json(rebuild_run/'plan.json');done=read_json(rebuild_run/'completed.json')
    if (done['plan_sha256']!=sha(rebuild_run/'plan.json') or
            any(sha(rebuild_run/p)!=h for p,h in done['artifacts'].items()) or
            saved['code_sha256']!=source_code_hashes() or
            any(sha(p)!=h for p,h in saved['inputs'].items())):raise ValueError('Offline rebuild changed')
    analysis=from_factory(rebuild_run);count=len(analysis.compiled['profiles'])
    if not count or 2*(count*len(QUESTIONS)+(2*min(3,count) if count>1 else 0))>MAX_CALLS:
        raise ValueError('All-profile fixed product probe does not fit48requests')
    old=read_json(Path(saved['original_run'])/'plan.json')
    original_auth=read_json(old['authorization']['file']);owner=original_auth['financial_owner']
    policy=read_json(old['policy_file'])
    if (sha(old['authorization']['file'])!=old['authorization']['sha256'] or
            policy!=old['spend_policy'] or policy['maximum_usd']!='150' or
            sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization']):
        raise ValueError('Same cumulative150 account and financial owner required')
    money=e.ledger(policy);account=money.summary();own=money.summary(plan_sha256=owner['sha256'])
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled account')
    providers={'chat':e.provider_preflight(e.remote.SOL),'typed':decisions.preflight(decisions.DEPLOYMENT)}
    key=e.key_metadata()
    if key['limit']!=150:raise ValueError('Observed team150 limit required')
    cutoff,history=previous.previous.history(policy);now=datetime.now(timezone.utc)
    auth={'version':VERSION,'user_request':user_request,'started_at':now.isoformat(),
          'deadline':(now+timedelta(hours=3)).isoformat(),'financial_owner':owner,
          'opening_account':account,'opening_owner':own,'history_cutoff':cutoff,'history_sha256':history,
          'maximum_new_physical_calls':MAX_CALLS,'new_money_owner':False,'retries':0,'fallback':None,
          'key_observation':key,'providers':providers}
    write(directory/'authorization.json',auth)
    files=[rebuild_run/'plan.json',rebuild_run/'completed.json',rebuild_run/'artifacts/agent-inputs.json',
           rebuild_run/'artifacts/output.json',Path(owner['file']),Path(old['policy_file']),ROOT/'tools/seeded_perspective_trial.py',*ASSETS]
    plan={'artifact_kind':VERSION,'run_directory':str(directory),'rebuild_run':str(rebuild_run),
          'authorization':{'file':str(directory/'authorization.json'),'sha256':sha(directory/'authorization.json')},
          'inputs':{**saved['inputs'],**{str(p):sha(p) for p in files}},'code_sha256':source_code_hashes(),
          'admission_policy':deepcopy(seed_policy.POLICY),'bundle_revision':analysis.revision,
          'candidate_ids':[p['candidate_id'] for p in analysis.compiled['profiles']],
          'questions':QUESTIONS,'group_question':GROUP_QUESTION,
          'group_ids':[p['candidate_id'] for p in analysis.compiled['profiles'][:3]] if count>1 else [],
          'spend_policy':policy,'spend_scope_sha256':owner['sha256'],'maximum_cost_usd':'150',
          'subcap_usd':'150','opening_scope_charge_usd':'0','deployment':deepcopy(e.remote.SOL),
          'verification_deployment':deepcopy(e.remote.SOL),'embedding_deployment':deepcopy(e.remote.EMBEDDING),
          'membership_deployment':deepcopy(decisions.DEPLOYMENT),'billing_policy':e.remote.WIRE_BUDGET,
          'limits':{'call_seconds':180,'analysis_seconds':None},'artifact_storage_policy':e.api_resources.STORAGE_POLICY,
          'resource_policy':host_resources.HTTP_API_POLICY,'formal_factory_eligible':False,'quality_gate_passed':False}
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    guard(plan)
    return {'profiles':count,'maximum_physical_calls':MAX_CALLS,'deadline':auth['deadline'],
            'opening_account':account,'new_model_calls':0}


def guard(plan,*,call_seconds=0):
    directory=Path(plan['run_directory']);auth=read_json(plan['authorization']['file'])
    if (read_json(directory/'plan.json')!=plan or
            read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')} or
            sha(plan['authorization']['file'])!=plan['authorization']['sha256'] or
            plan['artifact_kind']!=VERSION or auth['version']!=VERSION or
            plan['code_sha256']!=source_code_hashes() or any(sha(p)!=h for p,h in plan['inputs'].items()) or
            auth['maximum_new_physical_calls']!=MAX_CALLS or auth['retries']!=0 or auth['fallback'] is not None or
            auth['new_money_owner'] is not False or plan['admission_policy']!=seed_policy.POLICY or
            plan['questions']!=QUESTIONS or plan['group_question']!=GROUP_QUESTION or
            plan['deployment']!=e.remote.SOL or plan['verification_deployment']!=e.remote.SOL or
            plan['embedding_deployment']!=e.remote.EMBEDDING or plan['membership_deployment']!=decisions.DEPLOYMENT or
            plan['billing_policy']!=e.remote.WIRE_BUDGET or plan['limits']!={'call_seconds':180,'analysis_seconds':None} or
            plan['resource_policy']!=host_resources.HTTP_API_POLICY or plan['artifact_storage_policy']!=e.api_resources.STORAGE_POLICY or
            any(plan[k]!='150' for k in ('maximum_cost_usd','subcap_usd')) or plan['opening_scope_charge_usd']!='0' or
            plan['formal_factory_eligible'] is not False or plan['quality_gate_passed'] is not False):
        raise ValueError('Frozen seeded product execution changed')
    previous.window(auth,call_seconds=call_seconds)
    saved=read_json(Path(plan['rebuild_run'])/'plan.json')
    old=read_json(Path(saved['original_run'])/'plan.json')
    original_auth=read_json(old['authorization']['file'])
    owner=auth['financial_owner'];analysis=from_factory(plan['rebuild_run'])
    ids=[p['candidate_id'] for p in analysis.compiled['profiles']]
    if (sha(old['authorization']['file'])!=old['authorization']['sha256'] or
            owner!=original_auth['financial_owner'] or plan['spend_policy']!=old['spend_policy'] or
            plan['spend_policy']!=read_json(old['policy_file']) or
            sha(owner['file'])!=owner['sha256'] or read_json(owner['file'])!=owner['authorization'] or
            plan['spend_scope_sha256']!=owner['sha256'] or plan['spend_policy']['maximum_usd']!='150' or
            analysis.revision!=plan['bundle_revision'] or plan['candidate_ids']!=ids or
            plan['group_ids']!=(ids[:3] if len(ids)>1 else [])):
        raise ValueError('Source analysis or original financial owner changed')
    analysis.live();account=e.ledger(plan['spend_policy']).summary();own=e.ledger(plan['spend_policy']).summary(plan_sha256=owner['sha256'])
    if account['reserved_calls'] or account['uncertain_calls']:raise e.BudgetExhausted('Unsettled shared account')
    if Decimal(account['charged_usd'])<Decimal(auth['opening_account']['charged_usd']) or Decimal(own['charged_usd'])<Decimal(auth['opening_owner']['charged_usd']):
        raise ValueError('Historical charge regressed')
    new=own['calls']-auth['opening_owner']['calls']
    if new<0 or new>MAX_CALLS or call_seconds and new>=MAX_CALLS:raise e.BudgetExhausted('Fixed physical request bound exhausted')
    return auth


class Session(e.RemoteSession):
    def __init__(self,directory,plan,dispatch):
        super().__init__(directory,plan,dispatch,authorization_guard=guard)
        self.typed_client,self.typed=typed_membership_runner.build(directory,plan,self.time,self.money,e.key_metadata)

    def reservation(self,request):
        allocated=allocate(request,e.openrouter.generation_allocation(self.plan['deployment'],require_explicit=True))
        return str(self.checkpoints['generation'].base.budget.maximum_charge(allocated))

    def amount(self):return Decimal(self.money.summary(plan_sha256=self.plan['spend_scope_sha256'])['charged_usd'])

    def generate(self,stage,request):
        before=self.amount()
        try:result=self.call('runtime-'+digest(request)[:20],request)
        except Exception as exc:
            exc.new_cost_usd=str(self.amount()-before);raise
        return {**result,'new_cost_usd':str(self.amount()-before)}

    def verify(self,stage,payload):
        decisions.validate_request(payload,decisions.DEPLOYMENT)
        self.dispatch.check();e.check_quota();guard(self.plan,call_seconds=30);self.storage.check()
        before=self.amount()
        try:
            with self.dispatch.remote_call():
                raw=self.typed.call('seeded-verification-'+decisions.wire_sha256(payload,decisions.DEPLOYMENT)[:20],payload,provider=self.typed_client.generate)
            self.storage.check()
        except Exception as exc:
            exc.new_cost_usd=str(self.amount()-before);raise
        return {**raw,'new_cost_usd':str(self.amount()-before)}


def probe(app,analysis,save):
    token=secrets.token_urlsafe(32)
    def call(method,path,body=None):return app.handle(method,path,token,body)[1]
    session=call('POST','/api/v1/sessions',{'analysis_id':analysis.id,'bundle_revision':analysis.revision,
        'initial_opinion':'','request_id':'create'});base='/api/v1/sessions/'+session['session_id']
    def settle(job):
        while True:
            result=call('GET','/api/v1/jobs/'+job['job_id'])
            if result['state'] not in ('queued','running'):
                save('jobs/'+result['job_id'],result)
                if result['state']!='succeeded':raise ValueError('Product job failed; preserved, no retry')
                return
            time.sleep(.25)
    rooms=[]
    for i,cid in enumerate(p['candidate_id'] for p in analysis.compiled['profiles']):
        room=call('POST',base+'/rooms',{'mode':'one_to_one','participant_ids':[cid],
            'initial_revision':1,'request_id':'direct'+str(i)});path='/api/v1/rooms/'+room['room_id']
        for j,question in enumerate(QUESTIONS):
            args={'expected_revision':room['revision'],'request_id':f'q{i}_{j}'}
            if j:args.update(text=question,reply_to_message_id=None)
            else:args['opening_question']=question
            settle(call('POST',path+('/messages' if j else '/start'),args))
            room=call('GET',path);save(f'rooms/direct{i}/question{j}',room)
        rooms.append(room)
    ids=[p['candidate_id'] for p in analysis.compiled['profiles'][:3]]
    if len(ids)>1:
        room=call('POST',base+'/rooms',{'mode':'group','participant_ids':ids,'initial_revision':1,'request_id':'group'})
        path='/api/v1/rooms/'+room['room_id']
        settle(call('POST',path+'/start',{'opening_question':GROUP_QUESTION,'expected_revision':room['revision'],'request_id':'group-start'}))
        room=call('GET',path);rooms.append(room);save('rooms/group',room)
    return rooms


def run(directory):
    directory=Path(directory).resolve()
    if (directory/'completed.json').exists():
        done=read_json(directory/'completed.json')
        if done['plan_sha256']!=sha(directory/'plan.json') or any(sha(directory/p)!=h for p,h in done['artifacts'].items()):raise ValueError('Completed product trial changed')
        return done['report']
    plan=read_json(directory/'plan.json');auth=guard(plan)
    with experiment_lock(directory),e.quota_watch():
        if (directory/'started.json').exists():raise ValueError('Interrupted trial requires reconciliation; no automatic retry')
        write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
        def save(name,value):write(directory/'artifacts'/(name+'.json'),value)
        dispatch=host_resources.RemoteCallGuard();session=Session(directory,plan,dispatch)
        analysis=from_factory(plan['rebuild_run'])
        app=ProductApp(directory/'product.sqlite',[analysis],session.generate,session_ttl_seconds=10800,
            room_maximum_usd='150',reservation=session.reservation,decision=session.verify,
            decision_reservation=lambda:str(decisions.reservation(decisions.DEPLOYMENT)),revalidate=lambda:guard(plan))
        try:
            with host_resources.watch(previous.previous.resource_attempt(directory),plan['resource_policy'],host_resources.observe_wsl_host,interrupt=dispatch.request_stop,workload='http_api'):
                rooms=probe(app,analysis,save)
        finally:app.close()
        guard(plan)
        if previous.previous.history(plan['spend_policy'],auth['history_cutoff'])!=(auth['history_cutoff'],auth['history_sha256']):raise ValueError('Historical financial rows changed')
        own=session.money.summary(plan_sha256=plan['spend_scope_sha256']);messages=[m for r in rooms for m in r['messages'] if m['author_kind']=='agent']
        report={'version':VERSION,'profiles':analysis.public()['perspectives'],'rooms':len(rooms),
            'runtime_turns':len(messages),'answered':sum(bool(m['points']) for m in messages),
            'origins':{k:sum(p.get('origin')==k for m in messages for p in m['points']) for k in ('original_comment','ai_reasoning','external_evidence')},
            'new_calls':own['calls']-auth['opening_owner']['calls'],
            'new_charge_usd':str(Decimal(own['charged_usd'])-Decimal(auth['opening_owner']['charged_usd'])),
            'account':e.ledger(plan['spend_policy']).summary(),'quality_gate_passed':False,'requires_source_and_utility_review':True}
        save('report',report)
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),'report':report,
            'artifacts':{str(p.relative_to(directory)):sha(p) for p in (directory/'artifacts').rglob('*.json')}})
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--key-file',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    q=sub.add_parser('rebuild');q.add_argument('directory',type=Path);q.add_argument('--original',type=Path,required=True);q.add_argument('--reference',type=Path,required=True)
    q=sub.add_parser('prepare');q.add_argument('directory',type=Path);q.add_argument('--rebuild',type=Path,required=True);q.add_argument('--user-request',required=True)
    q=sub.add_parser('run');q.add_argument('directory',type=Path);args=parser.parse_args()
    if args.key_file:os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip()
    result=rebuild(args.directory,args.original,args.reference) if args.action=='rebuild' else prepare(args.directory,args.rebuild,user_request=args.user_request) if args.action=='prepare' else run(args.directory)
    print(json.dumps(result,ensure_ascii=False),flush=True)
