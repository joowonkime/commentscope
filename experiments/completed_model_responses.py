"""Read-only reuse of exact completed calls from a terminal partial experiment.

Checkpoint, call artifacts, provider boundary and raw ledger response must all
agree. Interrupted/unresolved requests remain unavailable and are never retried.
No evaluations or corrected outputs enter the response cache.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.providers.generation_limits import allocate
from commentscope.providers import framed_embedding

LLM = 'local_llama'
EMBED = 'commentscope.providers.framed_embedding:generate'
NLI = 'commentscope.providers.evidence_nli:generate'
BOUNDARIES = {
    LLM: ('src/commentscope/providers/local_llama.py','src/commentscope/providers/generation_limits.py'),
    EMBED: ('src/commentscope/providers/framed_embedding.py','src/commentscope/factory/claim_clusters.py','src/commentscope/cluster_baseline.py'),
    NLI: ('src/commentscope/providers/evidence_nli.py','src/commentscope/providers/local_nli.py')}


class CompletedResponses:
    def __init__(self, directory, *, deployment):
        directory=Path(directory)
        if not directory.resolve().is_relative_to(Path('runs').resolve()):
            raise ValueError('Private response-cache source required')
        plan=read_json(directory/'plan.json');plan_hash=sha(directory/'plan.json')
        if plan['deployment']!=deployment:raise ValueError('Exact previous deployment required')
        started_paths=list((directory/'attempts').glob('*.started.json'))
        if (directory/'started.json').exists():started_paths.append(directory/'started.json')
        for path in started_paths:
            pid=read_json(path).get('pid')
            if type(pid) is int:
                process=Path(f'/proc/{pid}/cmdline')
                if process.exists() and str(directory).encode() in process.read_bytes().split(b'\0'):
                    raise RuntimeError('Previous owned experiment is still live')
        self.runtime=deepcopy(deployment['runtime']);self.results={};self.capacities={}
        self.unavailable=set();self.embedding_entries=[];self.hits=0;self.used=set()
        files={str(directory/'plan.json'):plan_hash};receipts=[]
        def pinned(path):
            value=read_json(path);files[str(path)]=sha(path);return value
        intents={}
        for path in sorted((directory/'checkpoints').glob('*.intent.json')):
            identity=pinned(path)
            if (identity['artifact_kind']!=CHECKPOINT_VERSION or identity['plan_sha256']!=plan_hash
                    or path.stem.removesuffix('.intent')!=digest(identity)):
                raise ValueError('Previous checkpoint identity changed')
            key=identity['request_sha256']
            if key in intents:raise ValueError('Duplicate previous logical request')
            intents[key]=(path,identity)
        ledger=Path(plan['budget']['ledger']).resolve()
        with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
            rows=db.execute('SELECT id,request_sha,request_json,state,response_json FROM calls WHERE plan_sha=?',(plan_hash,)).fetchall()
        by_request={}
        for row in rows:by_request.setdefault(row[1],[]).append(row)
        if any(row[3]=='reserved' for row in rows):
            raise RuntimeError('Source experiment still has a reserved/live request')
        checked_providers=set();seen=set()
        for path in sorted((directory/'calls').glob('*.request.json')):
            packet=pinned(path);request=packet['request'];key=digest(request)
            if packet['request_sha256']!=key or packet['plan_sha256']!=plan_hash or key in seen:
                raise ValueError('Previous request identity changed or repeated')
            seen.add(key)
            matches=by_request.get(key,[])
            if len(matches)!=1 or json.loads(matches[0][2])!=request:
                raise ValueError('Unique exact previous ledger request required')
            row=matches[0]
            capacity_path=directory/'artifacts/admission-capacity'/(key+'.json')
            if capacity_path.exists():
                capacity=pinned(capacity_path)
                if (capacity['request_sha256']!=key or capacity['context']!=self.runtime['context']
                        or capacity['output_reservation']!=request['max_tokens']):
                    raise ValueError('Previous measured capacity changed')
                self.capacities[key]=capacity
            if row[3]!='ok':self.unavailable.add(key);continue
            if key not in intents:raise ValueError('Completed previous call lacks checkpoint intent')
            intent_path,identity=intents[key];provider=identity['provider']
            if provider not in BOUNDARIES:raise ValueError('Unknown previous provider')
            if provider not in checked_providers:
                for boundary in BOUNDARIES[provider]:
                    if sha(boundary)!=plan['code_sha256'][boundary]:
                        raise ValueError('Previous provider boundary changed: '+boundary)
                checked_providers.add(provider)
            result_path=path.with_name(path.name.replace('.request.json','.result.json'))
            done_path=intent_path.with_name(intent_path.name.replace('.intent.json','.result.json'))
            if not result_path.exists() or not done_path.exists():
                self.unavailable.add(key);continue
            result=pinned(result_path);done=pinned(done_path)
            if done!={'identity':identity,'result':result,'result_sha256':digest(result)}:
                raise ValueError('Previous completed checkpoint/result changed')
            response=json.loads(row[4])
            if provider==LLM:
                choice=response['choices'][0]
                if (result['raw']!=choice['message']['content'] or result['usage']!=response['usage']):
                    raise ValueError('Previous raw LLM response differs from ledger')
                if result['errors'] or choice['finish_reason']!='stop':
                    self.unavailable.add(key);continue
                if json.loads(result['raw'])!=result['output']:
                    raise ValueError('Previous parsed LLM output changed')
                if key in self.capacities:
                    c=self.capacities[key]
                    if not c['fits'] or result['usage']['prompt_tokens']>c['input_tokens']+c['safety_margin']:
                        raise ValueError('Previous prompt exceeded measured allocation')
            elif result!=response:raise ValueError('Previous auxiliary response differs from ledger')
            if provider==EMBED:
                artifact_path=Path(result['output']);artifact=pinned(artifact_path)
                if (result['sha256']!=sha(artifact_path) or request['data']['output']!=str(artifact_path)
                        or artifact['texts_sha256']!=digest(request['data']['texts'])
                        or artifact['model']!=framed_embedding.MODEL or artifact['revision']!=framed_embedding.REVISION
                        or artifact['local_files_only'] is not True):
                    raise ValueError('Previous embedding provenance changed')
                self.embedding_entries.append((deepcopy(request),deepcopy(result)))
            self.results[provider,key]=deepcopy(result)
            receipts.append({'request_sha256':key,'provider':provider,'ledger_call_id':row[0],
                             'result_sha256':digest(result)})
        if seen!=set(by_request):raise ValueError('Previous ledger/artifact inventory differs')
        self.proof={'source_directory':str(directory),'source_plan_sha256':plan_hash,
                    'files_sha256':files,'receipts':receipts,'unavailable_requests':sorted(self.unavailable),
                    'ledger':str(ledger),'new_model_calls':0,'semantic_approval':False}

    def get(self, request, *, provider=LLM):
        actual=allocate(request,self.runtime) if provider==LLM else request
        key=digest(actual)
        if key in self.unavailable:raise PriorRequestUnavailable(key)
        result=self.results.get((provider,key))
        if result is not None:self.hits+=1;self.used.add((provider,key))
        return deepcopy(result)

    def capacity(self, request):
        return deepcopy(self.capacities.get(digest(allocate(request,self.runtime))))

    def embedding(self, texts):
        matches=[(req,result) for req,result in self.embedding_entries if req['data']['texts']==texts]
        if len(matches)!=1:raise ValueError('Exactly one unchanged embedding response required')
        req,_=matches[0]
        return self.get(req,provider=EMBED)


class CompletedResponseChain:
    """Exact ledger-backed reuse through explicitly frozen prior-run proofs.

    No call/result is copied into a later run's call inventory. Each result
    remains bound to the actual run and ledger entry which generated it.
    """
    def __init__(self, directory, *, deployment, _ancestors=()):
        directory = Path(directory)
        identity = str(directory.resolve())
        if identity in _ancestors:
            raise ValueError('Cyclic completed-response provenance')
        self.current = CompletedResponses(directory, deployment=deployment)
        self.priors = []
        for reference in read_json(directory/'plan.json').get('completed_response_priors', []):
            if set(reference) != {'directory', 'proof_sha256'}:
                raise ValueError('Exact prior response-chain proof required')
            prior = CompletedResponseChain(Path(reference['directory']), deployment=deployment,
                                           _ancestors=(*_ancestors, identity))
            if digest(prior.proof) != reference['proof_sha256']:
                raise ValueError('Frozen prior completed-response provenance changed')
            self.priors.append(prior)
        self.proof = {'artifact_kind':'exact-completed-response-chain-20261023-v1',
                      'current':self.current.proof, 'priors':[p.proof for p in self.priors]}
        self.used = set()

    def get(self, request, *, provider=LLM):
        for cache in [self.current, *self.priors]:
            result = cache.get(request, provider=provider)
            if result is not None:
                self.used.add((provider, digest(request)))
                return result
        return None
