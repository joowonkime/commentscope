"""Run the three product workflows on a generated development analysis."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.agents.grounded_web import GroundedApp
from commentscope.agents.web import WebError
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.product.analysis import Analysis,from_factory
from commentscope.product.app import ProductApp
from commentscope.product.web import ProductServer
from commentscope.providers import openrouter
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.providers.checkpoint_calls import CheckpointRunner,PendingCallError,run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import SpendLedger,units
from commentscope.providers.remote_verification import WireBudget,WIRE_BUDGET
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from experiments.openrouter_factory_pipeline import provider_preflight,archive_sources
from experiments.openrouter_factory_probe import key_metadata,private,validate_spend_policy
from experiments.source_semantics_diagnostic import CYCLE_VERSION,cycle_guard
from tools import product_trial_budget as trial_budget

VERSION='commentscope-product-server-20261105-v1'
ASSETS=[ROOT/'src/commentscope/product'/name for name in ('mvp.html','mvp.js','mvp.css')]
ASSETS+=sorted((ROOT/'src/commentscope/product/assets').glob('*'))


def prepare(directory,factory_run,cycle_file,*,session_ttl_seconds,room_maximum_usd,factory_trial=None):
    directory=Path(directory);factory_run=Path(factory_run);cycle_file=Path(cycle_file)
    for path in (directory,factory_run,cycle_file):private(path)
    cycle=read_json(cycle_file);cycle_guard(cycle)
    deployment=openrouter.validate(cycle['selected_deployment'])
    allocation=openrouter.generation_allocation(deployment,require_explicit=True)
    policy=validate_spend_policy(read_json(Path(cycle['shared_policy_file'])))
    if (type(session_ttl_seconds) is not int or not 0<session_ttl_seconds<=86400
            or not 0<units(room_maximum_usd)<=units(cycle['maximum_additional_usd'])):
        raise ValueError('Explicit product lifetime and bounded room budget required')
    if directory.exists():raise ValueError('New product server plan required')
    analysis=from_factory(factory_run);factory_plan=read_json(factory_run/'plan.json')
    files=[factory_run/'plan.json',factory_run/'artifacts/agent-inputs.json',
           factory_run/'artifacts/output.json',Path(factory_plan['snapshot']),cycle_file,
           Path(cycle['shared_policy_file'])]
    link=None
    if factory_trial is not None:
        private(Path(factory_trial))
        money=SpendLedger(policy['ledger'],policy['account_id'],maximum_usd=policy['maximum_usd'],
                          opening_charge_usd=policy['opening_charge_usd'])
        link=trial_budget.bind(factory_run,cycle_file,factory_trial,money)
        files.extend([Path(link['file']),factory_run/'completed.json',factory_run/'artifacts/runtime.json',
                      Path(factory_trial),ROOT/'tools/product_trial_budget.py'])
        files.extend(ROOT/p for p in trial_budget.shared.TOOL_FILES)
    provider=provider_preflight(deployment)
    plan={'artifact_kind':VERSION,'run_directory':str(directory.resolve()),
          'factory_run':str(factory_run.resolve()),'cycle_file':str(cycle_file.resolve()),'cycle':cycle,
          'spend_scope_sha256':sha(cycle_file),'maximum_cost_usd':cycle['maximum_additional_usd'],
          'spend_policy':policy,'deployment':deployment,'provider_at_prepare':provider,
          'generation_allocation':allocation,'inputs':{str(p.resolve()):sha(p) for p in files},
          'code_sha256':source_code_hashes(),'entrypoint_sha256':sha(Path(__file__)),
          'assets_sha256':{str(p.relative_to(ROOT)):sha(p) for p in ASSETS},
          'analysis':{'bundle':deepcopy(analysis.bundle),'provenance':deepcopy(analysis.provenance),
                      'analysis_id':analysis.id,'bundle_revision':analysis.revision},
          'session_ttl_seconds':session_ttl_seconds,'room_maximum_usd':str(room_maximum_usd),
          'limits':{'analysis_seconds':None,'call_seconds':deployment['call_seconds']},
          'quality_gate_passed':False,'semantic_reliability':'not_assessed',
          'cross_run_response_reuse':False,'development_product_scope':True}
    plan['billing_policy']=WIRE_BUDGET
    if link is not None:
        plan.update(factory_trial=link,spend_scope_sha256=factory_plan['spend_scope_sha256'],
                    money_owner_limit_usd=factory_plan['maximum_cost_usd'])
    write(directory/'plan.json',plan);write(directory/'frozen.json',{'plan_sha256':sha(directory/'plan.json')})
    archive_sources(directory,plan['code_sha256'])
    return plan


def validate(directory):
    directory=Path(directory);private(directory)
    plan=read_json(directory/'plan.json');run_origin(plan,directory,attempt=1)
    if (plan['artifact_kind']!=VERSION or read_json(directory/'frozen.json')!={'plan_sha256':sha(directory/'plan.json')}
            or plan['entrypoint_sha256']!=sha(Path(__file__)) or plan['code_sha256']!=source_code_hashes()
            or set(plan['assets_sha256'])!={str(p.relative_to(ROOT)) for p in ASSETS}
            or any(sha(ROOT/path)!=h for path,h in plan['assets_sha256'].items())
            or any(sha(path)!=h for path,h in plan['inputs'].items())
            or plan['cycle']!=read_json(plan['cycle_file'])
            or plan['maximum_cost_usd']!=plan['cycle']['maximum_additional_usd']
            or plan['deployment']!=plan['cycle']['selected_deployment']
            or plan['quality_gate_passed'] is not False or plan.get('billing_policy')!=WIRE_BUDGET):
        raise ValueError('Frozen product server, source analysis, budget or implementation changed')
    cycle_guard(plan['cycle'],allow_expired=True)
    if 'factory_trial' in plan:
        binding=plan['factory_trial'];factory=read_json(binding['factory_plan_file'])
        trial_budget.check(binding,factory,plan['cycle'],plan['cycle_file'])
        if (plan['spend_scope_sha256']!=factory['spend_scope_sha256']
                or plan['money_owner_limit_usd']!=factory['maximum_cost_usd']):
            raise ValueError('Original Factory money owner changed')
    elif plan['spend_scope_sha256']!=sha(plan['cycle_file']):raise ValueError('Product cycle money changed')
    if plan['generation_allocation']!=openrouter.generation_allocation(plan['deployment'],require_explicit=True):
        raise ValueError('Product generation allocation changed')
    return plan


class Broker:
    def __init__(self,directory,plan):
        self.directory=Path(directory);self.plan=plan;self.lock=threading.Lock();self.inflight=False
        policy=plan['spend_policy'];self.ledger=SpendLedger(policy['ledger'],policy['account_id'],
            maximum_usd=policy['maximum_usd'],opening_charge_usd=policy['opening_charge_usd'])
        self.factory=None
        if 'factory_trial' in plan:
            self.factory=read_json(plan['factory_trial']['factory_plan_file'])
            self.ledger=trial_budget.ledger(self.ledger,plan['factory_trial'],self.factory)
        client=openrouter.Client(plan['deployment']);self.client=client
        plan_sha=sha(self.directory/'plan.json')
        paid=WireBudget(InferenceBudget(self.directory/'inference.sqlite',VERSION,limit_seconds=None),
            self.ledger,plan_sha256=plan_sha,deployment=plan['deployment'],
            maximum_run_usd=plan.get('money_owner_limit_usd',plan['maximum_cost_usd']),paid_provider=client.generate,
            key_metadata=key_metadata,spend_scope_sha256=plan['spend_scope_sha256'])
        self.runner=CheckpointRunner(openrouter.Runner(self.directory,plan,paid,client),plan['generation_allocation'])

    def reservation(self,request):
        return str(self.runner.base.budget.maximum_charge(allocate(request,self.plan['generation_allocation'])))

    def status(self):
        try:cycle_guard(self.plan['cycle'],call_seconds=self.plan['limits']['call_seconds'])
        except TimeoutError:return 'cycle_deadline'
        if self.factory is not None:
            try:
                trial_budget.shared.guard(self.factory,call_seconds=self.plan['limits']['call_seconds'])
                trial_budget.check(self.plan['factory_trial'],self.factory,self.plan['cycle'],self.plan['cycle_file'],self.ledger)
            except TimeoutError:return 'cycle_deadline'
            except BudgetExhausted:return 'reconcile_required'
            if trial_budget.remaining(self.ledger,self.plan['factory_trial'],self.factory)<=0:return 'budget_exhausted'
        shared=self.ledger.summary()
        if shared['uncertain_calls']:return 'reconcile_required'
        if self.inflight:return 'busy'
        if shared['reserved_calls']:return 'reconcile_required'
        pending=[p for p in (self.directory/'checkpoints').glob('*.intent.json')
                 if not p.with_name(p.name.replace('.intent.json','.result.json')).exists()]
        if pending:return 'reconcile_required'
        own=self.ledger.summary(plan_sha256=self.plan['spend_scope_sha256'])
        if own['calls'] and Decimal(own['remaining_usd'])<=0:return 'budget_exhausted'
        return 'ready'

    def model(self,stage,request):
        with self.lock:
            validate(self.directory)
            status=self.status()
            if status!='ready':raise WebError(503,status)
            if not self.client.measure(request)['fits']:raise WebError(422,'context_capacity')
            before=self.runner.reused
            self.inflight=True
            try:result=self.runner.call('product-'+stage,request)
            except BudgetExhausted:
                raise WebError(503,'reconcile_required' if self.ledger.summary()['uncertain_calls'] else 'budget_exhausted') from None
            except PendingCallError:raise WebError(503,'reconcile_required') from None
            finally:self.inflight=False
            result=deepcopy(result)
            result['new_cost_usd']='0' if self.runner.reused>before else str((result.get('usage') or {}).get('cost',0))
            return result

    def legacy_provider(self,system,data,schema,*,max_tokens):
        result=self.model('legacy',{'system':system,'data':data,'schema':schema,'max_tokens':max_tokens})
        if result.get('errors'):raise ValueError('No completed runtime output')
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result['output'])}}]}


def build(directory):
    directory=Path(directory);plan=validate(directory)
    if not os.environ.get('OPENROUTER_API_KEY','').strip():raise ValueError('OPENROUTER_API_KEY required')
    provider_preflight(plan['deployment'])
    analysis=Analysis(plan['analysis']['bundle'],plan['analysis']['provenance'])
    if analysis.id!=plan['analysis']['analysis_id'] or analysis.revision!=plan['analysis']['bundle_revision']:
        raise ValueError('Registered product analysis changed')
    broker=Broker(directory,plan)
    product=ProductApp(directory/'app.sqlite',[analysis],broker.model,
        session_ttl_seconds=plan['session_ttl_seconds'],room_maximum_usd=plan['room_maximum_usd'],
        reservation=broker.reservation,revalidate=lambda:validate(directory),generation_status=broker.status)
    class Legacy(GroundedApp):
        def public(self,item):
            value=super().public(item);value['remote_status']=broker.status()
            if value['remote_status']!='ready':value['can_ask']=False
            return value
    legacy=Legacy(analysis.bundle,directory/'legacy-sessions',provider=broker.legacy_provider,
                  revalidate=lambda:validate(directory))
    return product,legacy,broker


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True)
    p=actions.add_parser('prepare');p.add_argument('directory',type=Path)
    p.add_argument('--factory-run',type=Path,required=True);p.add_argument('--cycle-file',type=Path,required=True)
    p.add_argument('--session-ttl-seconds',type=int,required=True);p.add_argument('--room-maximum-usd',required=True)
    p.add_argument('--factory-trial',type=Path)
    p=actions.add_parser('serve');p.add_argument('directory',type=Path)
    p.add_argument('--key-file',type=Path);p.add_argument('--port',type=int,default=8767)
    p.add_argument('--bind',choices=('127.0.0.1','0.0.0.0'),default='127.0.0.1')
    p.add_argument('--public-origin')
    p.add_argument('--experimental',action='store_true',required=True)
    args=parser.parse_args(argv)
    if args.action=='prepare':
        plan=prepare(args.directory,args.factory_run,args.cycle_file,
                     session_ttl_seconds=args.session_ttl_seconds,room_maximum_usd=args.room_maximum_usd,
                     factory_trial=args.factory_trial)
        print(json.dumps({'prepared':str(args.directory),'analysis_id':plan['analysis']['analysis_id'],
                          'quality_gate_passed':False,'inference_calls':0}));return
    if args.key_file is not None:os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip()
    with experiment_lock(args.directory):
        product,legacy,broker=build(args.directory);server=ProductServer(product,legacy,args.port,
            bind_host=args.bind,public_origin=args.public_origin)
        print(json.dumps({'origin':'http://127.0.0.1:'+str(server.server_address[1]),
                          'preview':'/mvp','quality_gate_passed':False}),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close();product.close()


if __name__=='__main__':main()
