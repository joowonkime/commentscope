"""Per-run model work, provenance binding and membership verification.

This layer owns request identities, capacity/error records and per-run caches.
It receives providers; it never starts a server or approves semantic quality.
"""
from copy import deepcopy

from commentscope.factory import minimal_membership as mm
from commentscope.factory import proposition_requirements as pr
from commentscope.factory import qualification_ownership as qo
from commentscope.factory.automatic_contract import digest
from commentscope.providers.context_capacity import partition


class PipelineWork:
    """Keep all mutable model-work state scoped to one Factory invocation."""

    def __init__(self, runner, inspect, save, *, registry, membership_mode,
                 verification_contract, schedule):
        self.runner = runner
        self.inspect = inspect
        self.save = save
        self.registry = registry
        self.membership_mode = membership_mode
        self.verification_contract = verification_contract
        self.schedule = schedule
        self.engine = None
        self.errors = []
        self.holds = []
        self.capacity = []
        self.shape_cache = {}
        self.assessment_cache = {}
        self.raw_routes = {}

    def work(self, stage, items, build, bind, size, *, minimum=1):
        results = []
        for offset in range(0, len(items), size):
            fitted, deferred = partition(items[offset:offset+size], build, self.inspect,minimum=minimum)
            self.holds.extend({'stage': stage, **d} for d in deferred)
            for task in fitted:
                req = task['request']; key = stage+'-'+digest(req)[:20]
                # Identical requests may bind different final candidate
                # provenance after consolidation. Keep the call checkpoint
                # identity, but never overwrite either bound input record.
                binding_key = key+'-'+digest(task['items'])[:20]
                self.capacity.append({'stage': stage, **task['capacity']}); self.save('capacity/'+key, task['capacity'])
                # Pending/transport ambiguity escapes: never turn it into permission
                # for a duplicate request. A returned malformed batch is preserved.
                from commentscope.factory.shared_admission import PriorRequestUnavailable
                try:result = self.runner.call(key, req)
                except PriorRequestUnavailable:
                    self.holds.append({'stage':stage,'task_sha256':digest(task['items']),
                        'request_sha256':digest(req),'reason':'prior_request_unavailable_no_retry'})
                    continue
                try:
                    bound = bind(task['items'], result)
                except (ValueError, KeyError, TypeError) as exc:
                    error = {'stage': stage, 'task_sha256': digest(task['items']),
                             'request_sha256': digest(req), 'exception': type(exc).__name__,
                             'message': str(exc), 'result': deepcopy(result), 'items': deepcopy(task['items'])}
                    self.errors.append(error); self.save('errors/'+binding_key, error)
                    if result.get('raw') is None and result.get('errors'):
                        raise RuntimeError('No completed model response; inspect process and ledger')
                    continue
                results.append(bound); self.save('bound/'+binding_key, bound)
        return results


    def qualify(self, source,candidate):
        text=candidate['text']
        if text not in self.shape_cache:
            rows=self.work('qualification-inventory',[text],lambda group:pr.shape_request(group[0]),
                      lambda group,result:pr.bind_shape(group[0],result),1)
            self.shape_cache[text]=rows[0] if rows else None
        shape=self.shape_cache[text]
        if shape is None:return None
        key=digest([source,shape])
        if key not in self.assessment_cache:
            checks=[]
            if shape['status']=='complete':
                checks=self.work('qualification-detail',shape['details'],
                    lambda group:pr.detail_request(source,shape,group[0]),
                    lambda group,result:pr.bind_detail(source,shape,group[0],result),1)
            ownership=self.work('qualification-ownership',qo.pairs(source,text),
                lambda group:qo.pair_request(source,text,group[0]),
                lambda group,result:qo.bind_pair(source,text,group[0],result),1)
            self.assessment_cache[key]=pr.assessment(source,shape,checks,qo.assessment(source,text,ownership))
        return self.assessment_cache[key]


    def judge(self, stage, pairs, targets):
        if self.engine is not None:return self.engine.judge(pairs,targets)
        target_lookup = {c['id']: c for c in targets}
        if self.membership_mode=='raw':
            from commentscope.factory import raw_membership as raw
            from commentscope.factory import raw_membership_verification as verification
            results=[]
            for pair in pairs:
                source,target=self.registry[pair['source_id']],target_lookup[pair['candidate_id']]
                proofs=self.work(stage+'-raw',[pair],lambda group:raw.request(source,target),
                            lambda group,result:raw.bind(source,target,result),1)
                for proof in proofs:
                    route=None;evidence=None
                    if proof['passed']:
                        target_key=digest(target)
                        if target_key not in self.raw_routes:
                            origin_id=min(target['nominees'])
                            if self.verification_contract in verification.INDEPENDENT and 'meaning_context' in target:
                                origin_id=target['meaning_context']['source']['id']
                            origin=self.registry[origin_id] if self.verification_contract in (verification.VERSION,*verification.INDEPENDENT) else None
                            route_version=self.verification_contract if self.verification_contract in verification.INDEPENDENT else None
                            rows=self.work('raw-candidate-route',[target],lambda group:verification.route_request(group[0],origin,version=route_version),
                                lambda group,result:verification.bind_route(group[0],result,origin,version=route_version),1)
                            self.raw_routes[target_key]=rows[0] if rows else None
                        route=self.raw_routes[target_key]
                        if route and route['passed']:
                            rows=self.work('raw-own-evidence',[proof],lambda group:verification.evidence_request(group[0],self.verification_contract),
                                lambda group,result:verification.bind_evidence(group[0],result,self.verification_contract),1)
                            evidence=rows[0] if rows else None
                    verified=verification.assessment(proof,route,evidence,version=self.verification_contract)
                    results.append(verification.batch([source],[target],[verified],version=self.verification_contract))
            return results
        def args(group):
            return ([self.registry[sid] for sid in sorted({p['source_id'] for p in group})],
                    [target_lookup[cid] for cid in sorted({p['candidate_id'] for p in group})], group)
        preliminary=self.work(stage,pairs,lambda group:mm.membership_request(*args(group)),
                         lambda group,result:mm.bind(*args(group),result),self.schedule['membership_pairs'])
        results=[]
        for batch in preliminary:
            qualifications=[]
            for row in batch['memberships']:
                decision=row['decision']
                if (decision['relation']=='supported' and decision['authorship']=='asserted_or_endorsed'
                        and decision['scope_preserved']=='yes'):
                    assessment=self.qualify(self.registry[row['source_id']],target_lookup[row['candidate_id']])
                    if assessment is not None:qualifications.append({'source_id':row['source_id'],
                        'candidate_id':row['candidate_id'],'assessment':assessment})
            bound=mm.bind(batch['sources'],batch['candidates'],batch['pairs'],{'output':batch['output']},qualifications)
            results.append(bound);self.save('bound/'+stage+'-qualified-'+digest(bound)[:20],bound)
        return results

