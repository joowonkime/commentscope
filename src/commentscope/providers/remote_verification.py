"""Explicit all-HTTP verification roles; no local inference or automatic fallback."""
from copy import deepcopy
from decimal import Decimal
import json
import math
import os
import re
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.factory.automatic_contract import digest
from commentscope.providers import openrouter
from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.openrouter_budget import PaidBudget, units
from commentscope.providers.budget import BudgetExhausted

VERSION = 'remote-verification-20261106-v1'
WIRE_BUDGET = 'wire-bound-input-0.1'
SOL = {'version':'openrouter-chat-completions-0.1', 'model':'openai/gpt-6.1-sol',
       'context':1050000, 'call_seconds':180, 'temperature':None,
       'reasoning':{'effort':'low'}, 'reasoning_output_tokens':1024,
       'schema_policy':'openai-strict-schema-20261104-v1',
       'provider':{'only':['openai'], 'max_price':{'prompt':2,'completion':10,'request':0}},
       'billing_ceiling':{'prompt':5,'completion':15,'request':0}}
EMBEDDING = {'version':'openrouter-embeddings-0.2', 'model':'openai/text-embedding-3-small',
             'response_models':['openai/text-embedding-3-small','text-embedding-3-small'],
             'context':8192,'dimensions':1536,'call_seconds':180,
             'provider':{'only':['openai'],'allow_fallbacks':False,
                         'max_price':{'prompt':0.02,'completion':0,'request':0}}}
GENERATION = ('extract','extract-additional','argument-node-metadata',
              'argument-position-alignment','argument-dependencies','source-evidence-proposal')
VERIFICATION = ('source-context','source-world','candidate-world','nomination-raw',
                'raw-candidate-route','raw-own-evidence','equivalence','qualification-inventory',
                'qualification-detail','qualification-ownership','assertion-counterexample',
                'membership-initial-raw','membership-expanded-raw','core','core-fidelity',
                'argument-owner','argument-audit','argument-dependency','facts',
                'source-evidence-observation','source-evidence-candidates')
ROLES = {**dict.fromkeys(GENERATION,'generation'), **dict.fromkeys(VERIFICATION,'verification'),
         'runtime':'interaction'}


def role(stage):
    family = re.sub(r'-[a-f0-9]{20}$','',stage)
    if family not in ROLES: raise ValueError('Unregistered remote decision stage: '+stage)
    return ROLES[family]


def receipt(response, deployment):
    """Called after durable money settlement, before accepting logical content."""
    model = response.get('model','')
    if (response.get('provider') != 'OpenAI' or not isinstance(model,str)
            or not (model == deployment['model'] or re.fullmatch(re.escape(deployment['model'])+r'-\d{8}',model))):
        raise ValueError('Remote response model/provider differs from frozen route')


def parsed_receipt(result,request,deployment):
    raw=result.get('transport',{}).get('provider_response')
    if result.get('errors') or raw is None or digest(raw)!=result['transport'].get('provider_response_sha256'):
        raise ValueError('Original remote provider receipt required')
    receipt(raw,deployment)
    logical=openrouter.Client(deployment).decode_response(request,raw)
    if (raw['choices'][0]['finish_reason']!='stop'
            or json.loads(logical['choices'][0]['message']['content'])!=result['output']
            or json.loads(result['raw'])!=result['output']):
        raise ValueError('Logical output differs from original remote receipt')
    return raw


class WireBudget(PaidBudget):
    """Bound the exact already-allocated two-message payload, not a fake context."""
    def maximum_charge(self, request):
        client = openrouter.Client(self.deployment)
        wire = client.payload(request['system'],request['data'],request['schema'],request['max_tokens'])
        bound = len(json.dumps(wire,ensure_ascii=False,allow_nan=False).encode()) + openrouter.PROVIDER_MARGIN
        if bound + request['max_tokens'] > self.deployment['context']:
            raise ValueError('Actual wire payload exceeds frozen context')
        p = {k:Decimal(str(v)) for k,v in self.prices.items()}
        return (bound*p['prompt']+request['max_tokens']*p['completion'])/1_000_000+p['request']


def chunks(text):
    if not isinstance(text,str) or not text: raise ValueError('Complete nonempty embedding text required')
    out=[]; start=0; size=0
    for i,c in enumerate(text):
        width=len(c.encode())
        if size+width>6000: out.append(text[start:i]); start=i; size=0
        size+=width
    out.append(text[start:])
    return out


def batches(texts):
    if not isinstance(texts,dict) or not texts: raise ValueError('ID to complete text mapping required')
    out=[]; batch=[]; size=0
    for sid,text in texts.items():
        if not isinstance(sid,str) or not sid:raise ValueError('Source identity required')
        for index,part in enumerate(chunks(text)):
            width=len(part.encode())
            if len(batch)==32 or size+width>64000:out.append(batch);batch=[];size=0
            batch.append({'id':sid,'chunk':index,'text':part});size+=width
    if batch:out.append(batch)
    return out


def embedding_vectors(response, count):
    if (response.get('model') not in EMBEDDING['response_models'] or len(response.get('data',[]))!=count
            or response.get('provider') not in (None,'OpenAI')):
        raise ValueError('Embedding model/count changed')
    found={}
    for row in response['data']:
        i=row.get('index');vector=row.get('embedding')
        if (type(i) is not int or not 0<=i<count or i in found or not isinstance(vector,list)
                or len(vector)!=EMBEDDING['dimensions']
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector)
                or not any(vector)):
            raise ValueError('Invalid embedding index, dimensions or numeric vector')
        found[i]=vector
    usage=response.get('usage',{});tokens=usage.get('prompt_tokens')
    if (type(tokens) is not int or not 0<tokens<=count*EMBEDDING['context']
            or type(usage.get('total_tokens')) is not int or usage['total_tokens']!=tokens):
        raise ValueError('Embedding token usage missing or exceeds reserved bound')
    return [found[i] for i in range(count)]


def combine(texts, observations):
    vectors={sid:[0.]*EMBEDDING['dimensions'] for sid in texts};seen={sid:[] for sid in texts}
    expected=batches(texts)
    if len(expected)!=len(observations):raise ValueError('Missing embedding batches')
    for batch,response in zip(expected,observations,strict=True):
        for part,vector in zip(batch,embedding_vectors(response,len(batch)),strict=True):
            sid=part['id'];weight=len(part['text'].encode());seen[sid].append(part['text'])
            vectors[sid]=[a+weight*b for a,b in zip(vectors[sid],vector,strict=True)]
    for sid,vector in vectors.items():
        if ''.join(seen[sid])!=texts[sid]:raise ValueError('Embedding chunks omitted source text')
        norm=math.sqrt(sum(v*v for v in vector))
        if not math.isfinite(norm) or norm==0:raise ValueError('Embedding aggregation cannot normalize')
        vectors[sid]=[v/norm for v in vector]
    return vectors


class EmbeddingClient:
    def __init__(self, deployment):
        if deployment!=EMBEDDING:raise ValueError('Pinned embedding deployment required')
        self.deployment=deepcopy(deployment)

    def generate(self,system,data,schema,max_tokens=1):
        if system!=VERSION or schema!={} or max_tokens!=1 or set(data)!={'input'}:
            raise ValueError('Typed embedding request required')
        inputs=data['input']
        if (not isinstance(inputs,list) or not 1<=len(inputs)<=32
                or any(not isinstance(s,str) or not 0<len(s.encode())<=6000 for s in inputs)
                or sum(len(s.encode()) for s in inputs)>64000):
            raise ValueError('Bounded complete embedding chunks required')
        key=os.environ.get('OPENROUTER_API_KEY','').strip()
        if not key:raise ValueError('OPENROUTER_API_KEY is not configured')
        payload={'model':self.deployment['model'],'input':inputs,'encoding_format':'float',
                 'dimensions':self.deployment['dimensions'],'provider':self.deployment['provider']}
        req=Request('https://openrouter.ai/api/v1/embeddings',data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=self.deployment['call_seconds']) as response:
            return json.load(response)


class EmbeddingBudget:
    def __init__(self,base,ledger,*,plan_sha256,spend_scope_sha256,maximum_run_usd,paid_provider,key_metadata):
        self.base=base;self.ledger=ledger;self.plan_sha=plan_sha256;self.scope=spend_scope_sha256
        self.limit=maximum_run_usd;self.provider=paid_provider;self.metadata=key_metadata

    def call(self,request,plan_sha,*,timeout_seconds,provider):
        if (plan_sha!=self.plan_sha or provider!=self.provider or request.get('system')!=VERSION
                or request.get('schema')!={} or request.get('max_tokens')!=1
                or set(request)!={'system','data','schema','max_tokens'} or set(request['data'])!={'input'}):
            raise ValueError('Unknown embedding route cannot bypass accounting')
        inputs=request['data']['input']
        # Validate before charging, using the same chunk limits as the client.
        if (not isinstance(inputs,list) or not 1<=len(inputs)<=32
                or any(not isinstance(s,str) or not 0<len(s.encode())<=6000 for s in inputs)
                or sum(len(s.encode()) for s in inputs)>64000):raise ValueError('Invalid embedding batch')
        maximum=Decimal(len(inputs)*8192)*Decimal('0.02')/1_000_000
        cid=self.ledger.reserve(self.scope,digest(request),maximum,run_limit_usd=self.limit,
                                key_remaining_usd=self.metadata()['limit_remaining'])
        try:response=self.base.call(request,plan_sha,timeout_seconds=timeout_seconds,provider=provider)
        except BaseException:
            self.ledger.finish(cid,None);raise
        cost=response.get('usage',{}).get('cost')
        if cost is not None:
            try:units(cost)
            except ValueError:
                self.ledger.finish(cid,None);raise BudgetExhausted('Invalid embedding cost') from None
            self.ledger.finish(cid,cost)
            embedding_vectors(response,len(inputs))
        else:
            self.ledger.finish(cid,None)
            embedding_vectors(response,len(inputs))  # Invalid receipts retain unknown hold.
            self.ledger.resolve_conservatively(cid,plan_sha256=self.scope,request_sha256=digest(request),
                evidence_sha256=digest({'request':request,'response':response,'deployment':EMBEDDING}),
                reason='Validated embedding receipt omits cost; retain entire context reservation, not an actual bill.')
        return response
