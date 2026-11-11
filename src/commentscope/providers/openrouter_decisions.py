"""Pinned text-only Decisions adapter; no model selection, retry or admission."""
from copy import deepcopy
from decimal import Decimal
import json
import hashlib
import math
import os
import re
from urllib.request import Request,build_opener,ProxyHandler

from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.openrouter import endpoint_price_ceiling
from commentscope.providers.openrouter_budget import units,identity
from commentscope.providers.budget import BudgetExhausted
from commentscope.factory.automatic_contract import digest

VERSION='openrouter-decisions-20261105-v1'
ENDPOINT='https://openrouter.ai/api/alpha/decisions'
DEPLOYMENT={'version':VERSION,'model':'typesafe/jev-1.14','provider':'typesafe',
    'provider_name':'TypeSafe','context':262144,'call_seconds':30,'maximum_wire_bytes':28000,
    'max_questions':16,'prices':{'prompt':'0.042','completion':'0','request':'0'},
    'response_models':['typesafe/jev-1.14','typesafe/jev-1.14-20261014','jev-1.14.0']}


def validate(deployment):
    if deployment!=DEPLOYMENT:raise ValueError('Only the frozen first-trial Decisions deployment is supported')
    return deepcopy(deployment)


def routing(deployment):
    validate(deployment)
    return {'only':[deployment['provider']],'allow_fallbacks':False,
            'max_price':{k:float(v) for k,v in deployment['prices'].items()}}


def validate_choice_structure(payload,deployment):
    """Validate complete Choice structure; typed dispatch still needs validate_request."""
    validate(deployment)
    if (not isinstance(payload,dict) or set(payload)!={'model','state','questions','provider'}
            or payload['model']!=deployment['model'] or payload['provider']!=routing(deployment)
            or not isinstance(payload['state'],dict) or not payload['state']
            or not isinstance(payload['questions'],dict)
            or not 1<=len(payload['questions'])<=deployment['max_questions']):
        raise ValueError('Complete bounded typed Decisions request required')
    for alias,q in payload['questions'].items():
        if (not isinstance(alias,str) or re.fullmatch(r'[A-Za-z0-9_]{1,80}',alias) is None
                or not isinstance(q,dict) or set(q)!={'type','instructions','criteria'}
                or q['type']!='choice' or not isinstance(q['instructions'],str) or not q['instructions']
                or not isinstance(q['criteria'],dict) or not 2<=len(q['criteria'])<=8
                or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in q['criteria'].items())):
            raise ValueError('First trial supports only explicit bounded Choice questions')
    raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    return raw


def validate_request(payload,deployment):
    raw=validate_choice_structure(payload,deployment)
    if len(raw)>deployment['maximum_wire_bytes']:raise ValueError('Complete request exceeds short-state limit')
    return raw


def reservation(deployment):
    validate(deployment);p=deployment['prices']
    return Decimal(deployment['context'])*Decimal(p['prompt'])/1_000_000+Decimal(p['request'])


def wire_sha256(payload,deployment):
    return hashlib.sha256(validate_request(payload,deployment)).hexdigest()


def preflight(deployment,metadata=None):
    validate(deployment)
    if metadata is None:
        url='https://openrouter.ai/api/v1/models/'+deployment['model']+'/endpoints'
        with build_opener(ProxyHandler({}),NoRedirect()).open(url,timeout=20) as response:metadata=json.load(response)['data']
    endpoints=[e for e in metadata.get('endpoints',[]) if e.get('tag')==deployment['provider']]
    if metadata.get('id')!=deployment['model'] or len(endpoints)!=1:raise ValueError('Pinned provider endpoint required')
    e=endpoints[0];prices=endpoint_price_ceiling(e['pricing'])
    if (e.get('provider_name')!=deployment['provider_name'] or e.get('context_length')!=deployment['context']
            or e.get('status')!=0 or e.get('name','').split(' | ')[-1] not in deployment['response_models']
            or any(Decimal(str(prices[k]))>Decimal(v) for k,v in deployment['prices'].items())):
        raise ValueError('Provider, model limits or price ceiling changed')
    return {'model':deployment['model'],'endpoint':deepcopy(e),'reservation_usd':str(reservation(deployment))}


def answers(payload,response,deployment):
    validate_request(payload,deployment)
    if (not isinstance(response,dict) or response.get('provider')!=deployment['provider_name']
            or response.get('model') not in deployment['response_models']
            or not isinstance(response.get('id'),str) or not response['id']
            or not isinstance(response.get('answers'),dict) or set(response['answers'])!=set(payload['questions'])):
        raise ValueError('Bound model/provider and complete typed answers required')
    units(response.get('usage',{}).get('cost'));result={}
    for alias,question in payload['questions'].items():
        row=response['answers'][alias];probs=row.get('probabilities',{}) if isinstance(row,dict) else {}
        if (not isinstance(row,dict) or row.get('type')!='choice'
                or not isinstance(probs,dict) or set(probs)!=set(question['criteria'])
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in probs.values())
                or abs(sum(probs.values())-1)>0.00001 or row.get('choice') not in probs
                or probs[row['choice']]+1e-8<max(probs.values())
                or type(row.get('confidence')) not in (int,float) or not math.isfinite(row['confidence'])
                or not 0<=row['confidence']<=1):
            raise ValueError('Invalid Choice distribution or answer binding')
        result[alias]=deepcopy(row)
    return result


class Client:
    def __init__(self,deployment):self.deployment=validate(deployment)

    def generate(self,payload):
        raw=validate_request(payload,self.deployment)
        key=os.environ.get('OPENROUTER_API_KEY','').strip()
        if not key:raise ValueError('Missing API key')
        req=Request(ENDPOINT,data=raw,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=self.deployment['call_seconds']) as response:
            body=response.read(2_000_001)
        if len(body)>2_000_000:raise ValueError('Oversized Decisions receipt')
        return json.loads(body)


class DecisionsBudget:
    """Shared reservation/settlement for a caller's immutable money owner."""
    def __init__(self,base,ledger,*,plan_sha256,deployment,spend_scope_sha256,parent_limit_usd,
                 opening_scope_charge_usd,additional_limit_usd,paid_provider,key_metadata):
        identity(plan_sha256);identity(spend_scope_sha256)
        self.base=base;self.ledger=ledger;self.plan_sha=plan_sha256;self.deployment=validate(deployment)
        self.scope=spend_scope_sha256;self.parent_limit=parent_limit_usd
        self.opening=units(opening_scope_charge_usd);self.limit=units(additional_limit_usd)
        if not 0<self.limit<=units(parent_limit_usd) or self.opening>=units(parent_limit_usd):
            raise ValueError('Typed subcap must fit its existing monetary owner')
        self.paid_provider=paid_provider;self.metadata=key_metadata

    def call(self,payload,plan_sha,*,timeout_seconds,provider):
        if plan_sha!=self.plan_sha or provider!=self.paid_provider:raise ValueError('Unbound typed call')
        validate_request(payload,self.deployment)
        reserve=reservation(self.deployment);charged=units(self.ledger.summary(plan_sha256=self.scope)['charged_usd'])
        if charged<self.opening or charged-self.opening+units(reserve)>self.limit:
            raise BudgetExhausted('Original scope charge cannot fit the fixed typed subcap')
        metadata=self.metadata()
        call_id=self.ledger.reserve(self.scope,wire_sha256(payload,self.deployment),reserve,run_limit_usd=self.parent_limit,
                                   key_remaining_usd=metadata['limit_remaining'])
        try:response=self.base.call(payload,plan_sha,timeout_seconds=timeout_seconds,provider=provider,typed_request=True)
        except BaseException:
            self.ledger.finish(call_id,None);raise
        try:cost=response['usage']['cost'];units(cost)
        except (KeyError,TypeError,ValueError):
            self.ledger.finish(call_id,None)
            raise BudgetExhausted('Missing Decisions charge; reconcile before new requests') from None
        self.ledger.finish(call_id,cost)
        # Semantic/schema/model validation happens after durable raw accounting.
        return response


class PaidDecisions(DecisionsBudget):
    """The original first-trial entry point retains its strict $0.10 bound."""
    def __init__(self,base,ledger,*,trial_limit_usd,**kwargs):
        if not 0<units(trial_limit_usd)<=units('0.10'):
            raise ValueError('First-trial subcap exceeds authorization')
        super().__init__(base,ledger,additional_limit_usd=trial_limit_usd,**kwargs)
