"""Shared original-position discovery and comparison for the actual Factory.

No evaluation labels or approved answers enter this interface. Completed exact
requests may be reused within this instance, but proofs always bind the complete
current candidate, including final representative provenance.
"""
from copy import deepcopy
import json

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import contextual_propositions as cp, contextual_dependencies as cd
from commentscope.factory import contextual_witness as cw, contextual_qualifications as cq
from commentscope.factory import scoped_comparison as sc, source_nominal_scope as ns
from commentscope.factory import candidate_consolidation as cc
from commentscope.factory import raw_membership as raw
from commentscope.factory import raw_membership_verification as verification
from commentscope.factory import selected_reference_verification as reference_verification
from commentscope.factory.automatic_contract import digest

VERSION='contextual-factory-engine-20261018-v13'


class Engine:
    def __init__(self,sources,runner,inspect,save=None,*,raw_membership=False,verification_contract=verification.LEGACY):
        if verification_contract not in verification.VERSIONS:raise ValueError('Unknown raw verification contract')
        self.sources=deepcopy(sources);self.registry=mc.source_index(self.sources)
        self.runner=runner;self.inspect=inspect;self.save=save or (lambda name,value:None)
        self.errors=[];self.holds=[];self.capacity=[];self.reused=[];self.call_stages=[]
        self._completed={};self._called=set();self._attempted=set();self._comparisons={};self._shapes={}
        self.records=[];self.candidates=[];self.scopes={};self.nominations=None
        self.raw_membership=raw_membership;self._raw_comparisons={};self._raw_routes={}
        self.verification_contract=verification_contract

    def call(self,stage,request):
        key=stage+'-'+digest(request)[:20]
        if key in self._completed:
            self.reused.append({'stage':stage,'request_sha256':digest(request),'completed_call_key':key})
            return deepcopy(self._completed[key])
        if key in self._called:raise ValueError('Prior request attempted; no retry')
        self._called.add(key);capacity=self.inspect(request)
        if capacity['request_sha256']!=digest(request):raise ValueError('Unbound contextual capacity measurement')
        self.capacity.append({'stage':stage,**capacity});self.save('capacity/'+key,capacity)
        if not capacity['fits']:
            self.holds.append({'stage':stage,'request_sha256':digest(request),'reason':'context_capacity'})
            raise ValueError('Complete contextual request exceeds capacity')
        result=self.runner.call(key,request);self.call_stages.append(stage)
        if result.get('raw') is None and result.get('errors'):
            raise RuntimeError('Incomplete transport; inspect the same process and ledger')
        if not result.get('errors'):self._completed[key]=deepcopy(result)
        return result

    def error(self,stage,task,exc):
        row={'stage':stage,'task':deepcopy(task),'exception':type(exc).__name__,'message':str(exc)}
        self.errors.append(row);self.save('errors/'+stage+'-'+digest([task,len(self.errors)])[:20],row)

    def work(self,stage,items,build,bind,size):
        if size!=1:raise ValueError('Contextual source-local binding required')
        results=[]
        for item in items:
            try:
                request=build([item]);bound=bind([item],self.call(stage,request))
                self.save('bound/'+stage+'-'+digest(bound)[:20],bound);results.append(bound)
            except (ValueError,KeyError,TypeError) as exc:self.error(stage,item,exc)
        return results

    def resolve_scope(self,candidate,interpretation):
        """Resolve and independently verify one original-bound proposal."""
        bundle=candidate['meaning_context']
        contract=cd.VERSION
        request=cd.request(bundle,interpretation,contract)
        measured=self.inspect(request)
        if measured['request_sha256'] != digest(request):
            raise ValueError('Unbound dependency capacity selection')
        if not measured['fits']:
            contract=cd.REGIONS
            request=cd.request(bundle,interpretation,contract)
            regions_measured=self.inspect(request)
            if regions_measured['request_sha256'] != digest(request):
                raise ValueError('Unbound whole-region capacity selection')
            if not regions_measured['fits']:
                contract=cd.COMPACT_REGIONS
                request=cd.request(bundle,interpretation,contract)
            self.save('dependency-capacity-selection/'+candidate['id'],{
                'artifact_kind':cd.CAPACITY_POLICY,'candidate_id':candidate['id'],
                'original_contract':cd.VERSION,'original_capacity':measured,
                'whole_region_capacity':regions_measured,
                'selected_contract':contract,'selected_request_sha256':digest(request),
                'inference_attempts_before_selection':0,'original_text_truncated':False})
        rows=self.work('dependency',[candidate],lambda group:request,
            lambda group,result:cd.bind(bundle,interpretation,result,contract),1)
        if rows and reference_verification.required(rows[0]):
            proposal=rows[0]
            self.save('dependency-proposals/'+candidate['id'],proposal)
            rows=self.work('dependency-link-verification',[candidate],
                lambda group:reference_verification.request(proposal),
                lambda group,result:reference_verification.bind(proposal,result),1)
        if rows:
            self.scopes[candidate['id']]=rows[0];self.save('dependencies/'+candidate['id'],rows[0])
        return self.scopes.get(candidate['id'])

    def discover(self):
        if self.records or self.nominations is not None:raise ValueError('Discovery already attempted')
        self.records=cp.discover(self.sources,self.work,save=self.save)
        self.candidates=mc.candidates(self.records)
        interpreted={(r['source']['id'],i['node_id']):i for r in self.records for i in r['interpretations']}
        for candidate in self.candidates:
            bundle=candidate['meaning_context'];key=(bundle['source']['id'],bundle['node_id'])
            self.resolve_scope(candidate,interpreted[key])
        proofs=[]
        if self.raw_membership:
            for candidate in self.candidates:
                for sid in sorted(candidate['nominees']):
                    try: proofs.append(self.raw_assessment(sid,candidate))
                    except (ValueError,KeyError,TypeError) as exc:self.error('raw-nomination',candidate['id'],exc)
            self.nominations=verification.batch(self.sources,self.candidates,proofs,version=self.verification_contract)
            self.save('nomination-batches',[self.nominations])
            self.save('extractions',self.records);self.save('initial-candidates',self.candidates)
            return self.discovery_output()
        for candidate in self.candidates:
            if candidate['id'] not in self.scopes:
                self.holds.append({'stage':'nomination','candidate_id':candidate['id'],'reason':'scope_unavailable'})
                continue
            scope=self.scope(candidate)
            witness=cw.scoped_identity(scope,candidate,scope)
            proof=cq.assessment(witness,scope['interpretation'],scope['interpretation'])
            proofs.append(proof)
        # Self text equality cannot bypass dependency or nominal-scope guards.
        self.nominations=mm.bind_contextual(self.sources,self.candidates,proofs)
        self.save('nomination-batches',[self.nominations])
        self.save('extractions',self.records);self.save('initial-candidates',self.candidates)
        return self.discovery_output()

    def discovery_output(self):
        proofs=self.nominations.get('contextual_assessments',[]) if self.nominations else []
        return {'extractions':deepcopy(self.records),'candidates':deepcopy(self.candidates),
            'errors':deepcopy(self.errors),'capacity_holds':deepcopy(self.holds),
            'unextracted_source_ids':sorted(set(self.registry)-{r['source']['id'] for r in self.records if r['interpretations']}),
            'position_witnesses':[deepcopy(a['witness']) for a in proofs],
            'contextual_assessments':deepcopy(proofs),'counted_contextual_supports':0,
            'quality_gate_passed':False,'semantic_review_required':True}

    def scope(self,candidate):
        mc.validate_candidate(candidate);scope=self.scopes[candidate['id']]
        if scope['bundle']!=candidate['meaning_context']:raise ValueError('Candidate interpretation context changed')
        return scope

    def embedding_text(self,candidate):
        mc.validate_candidate(candidate)
        if candidate['id'] not in self.scopes:return candidate['text']
        # These addresses aid retrieval only, never become additional assertions.
        return json.dumps({'assertion':candidate['text'],'referents':ns.packet(self.scope(candidate))},
                          ensure_ascii=False,sort_keys=True)

    def assessment(self,left,right,source_mode='source_contribution',*,semantic=True):
        key=digest([left,right,source_mode,semantic])
        if key in self._comparisons:return self._comparisons[key]
        if key in self._attempted:raise ValueError('Prior comparison failed; no retry')
        self._attempted.add(key);a,b=self.scope(left),self.scope(right)
        witness=cw.scoped_identity(a,right,b)
        if not semantic or witness['relation']=='supported' or not a['ready'] or not b['ready']:
            proof=cq.assessment(witness,a['interpretation'],b['interpretation'])
        else:
            witness=sc.bind(a,right,b,self.call('scoped-position',sc.request(a,right,b,source_mode=source_mode)),
                            source_mode=source_mode)
            alignment=None;shape=None;checks=[]
            if witness['relation']=='supported':
                alignment=sc.exact_alignment(witness)
                if alignment is None:
                    alignment=sc.bind_alignment(witness,self.call('scoped-referents',sc.alignment_request(witness)))
                shape_key=digest(right)
                if shape_key not in self._shapes:
                    self._shapes[shape_key]=None
                    self._shapes[shape_key]=sc.bind_shape(right,b,self.call('scoped-inventory',sc.shape_request(right,b)))
                shape=self._shapes[shape_key]
                if shape is None:raise ValueError('Prior candidate inventory failed')
                if shape['ready']:
                    for detail in shape['literal_inventory']['details']:
                        checks.append(sc.bind_detail(witness,shape,detail,
                            self.call('scoped-detail',sc.detail_request(witness,shape,detail))))
            proof=sc.assessment(witness,alignment,shape,checks)
        self._comparisons[key]=proof;self.save('comparisons/'+key,proof)
        return proof

    def support(self,sid,target,*,semantic=True):
        if sid not in self.registry:raise ValueError('Unknown original source')
        if self.raw_membership and semantic:
            try:
                proof=self.raw_assessment(sid,target)
                batch=verification.batch([self.registry[sid]],[target],[proof],version=self.verification_contract)
                self.save('memberships/'+digest([sid,target]),batch)
                return {'assessments':[proof],'batch':batch,'accepted':proof['passed'],
                        'semantic_relation':proof['relation']}
            except (ValueError,KeyError,TypeError) as exc:
                self.error('raw-membership',{'source_id':sid,'candidate_id':target['id']},exc)
                return {'assessments':[],'batch':None,'accepted':False,'semantic_relation':'unassessed'}
        attempts=[]
        if target['id'] in self.scopes:
            for source in self.candidates:
                if source['meaning_context']['source']['id']==sid and source['id'] in self.scopes:
                    try:attempts.append(self.assessment(source,target,semantic=semantic))
                    except (ValueError,KeyError,TypeError) as exc:
                        self.error('contextual-membership',{'source_id':sid,'candidate_id':target['id'],'position_id':source['id']},exc)
        passed=[a for a in attempts if a['passed']]
        # Retain uncertain attempts ahead of a different position's negative.
        def priority(a):
            relation=a['witness']['relation']
            if relation=='supported' and not a['passed']:relation='uncertain'
            return {'supported':0,'uncertain':1,'conditional':2,'opposed':3,'unrelated':4}[relation]
        selected=passed[0] if passed else min(attempts,key=priority) if attempts else None
        batch=mm.bind_contextual([self.registry[sid]],[target],[selected]) if selected else None
        if batch:self.save('memberships/'+digest([sid,target]),batch)
        else:self.holds.append({'stage':'membership','source_id':sid,'candidate_id':target['id'],'reason':'source_or_target_scope_unavailable'})
        return {'assessments':attempts,'batch':batch,'accepted':bool(passed),
                'semantic_relation':'supported' if passed else 'unassessed'}

    def raw_assessment(self,sid,target):
        source=self.registry[sid];key=digest([source,target])
        if key not in self._raw_comparisons:
            proposal=raw.bind(source,target,self.call('raw-membership',raw.request(source,target)))
            route=None;evidence=None
            if proposal['passed']:
                target_key=digest(target)
                if target_key not in self._raw_routes:
                    origin_id=min(target['nominees'])
                    if self.verification_contract in verification.INDEPENDENT and 'meaning_context' in target:
                        origin_id=target['meaning_context']['source']['id']
                    origin=self.registry[origin_id] if self.verification_contract in (verification.VERSION,*verification.INDEPENDENT) else None
                    route_version=self.verification_contract if self.verification_contract in verification.INDEPENDENT else None
                    route_result=self.call('raw-candidate-route',verification.route_request(target,origin,version=route_version))
                    target_check=None;proposition_proof=None
                    if route_version in verification.TARGETED_CONTRACTS:
                        from commentscope.factory import substantive_contribution, substantive_target
                        contribution=substantive_contribution.bind(target,origin,route_result,substantive_contribution.CONTENT)
                        if contribution['passed']:
                            target_version=(substantive_target.NORMALIZED if route_version in verification.NORMALIZED_TARGETS
                                            else substantive_target.VERSION)
                            target_check=substantive_target.bind(target,origin,
                                self.call('raw-candidate-target',substantive_target.request(target,origin,target_version)),target_version)
                            if route_version==verification.AUTHORED and target_check['passed']:
                                from commentscope.factory import authored_proposition as authored
                                authored_proposal=authored.bind_proposal(target,origin,
                                    self.call('authored-proposition',authored.proposal_request(target,origin)))
                                checked=(self.call('authored-proposition-check',authored.check_request(authored_proposal))
                                         if authored_proposal['ready_for_check'] else None)
                                proposition_proof=authored.assessment(authored_proposal,checked)
                            elif route_version in (verification.REFERENCED,verification.ACYCLIC) and target_check['passed']:
                                from commentscope.factory import authored_reference
                                proposition_proof=authored_reference.run(target,origin,self.call)
                                if route_version==verification.ACYCLIC:
                                    from commentscope.factory import reference_cycle_guard
                                    proposition_proof=reference_cycle_guard.bind(proposition_proof)
                    self._raw_routes[target_key]=verification.bind_route(target,route_result,origin,
                        version=route_version,target_check=target_check,proposition_proof=proposition_proof)
                route=self._raw_routes[target_key]
                if route['passed']:
                    candidate_scope=None
                    if self.verification_contract in verification.INDEPENDENT and target['id'] in self.scopes:
                        from commentscope.factory import contextual_runtime
                        candidate_scope=contextual_runtime.bind(target,self.scope(target))
                    request=verification.evidence_request(proposal,self.verification_contract,candidate_scope=candidate_scope)
                    evidence=verification.bind_evidence(proposal,self.call('raw-own-evidence',request),self.verification_contract,candidate_scope=candidate_scope)
            self._raw_comparisons[key]=verification.assessment(proposal,route,evidence,version=self.verification_contract)
            self.save('raw-comparisons/'+key,self._raw_comparisons[key])
        return self._raw_comparisons[key]

    def judge(self,pairs,targets):
        lookup={c['id']:c for c in targets};batches=[]
        for pair in pairs:
            result=self.support(pair['source_id'],lookup[pair['candidate_id']])
            if result['batch']:batches.append(result['batch'])
        return batches

    def equivalences(self,pairs,*,semantic=True):
        lookup={c['id']:c for c in self.candidates};records=[]
        for pair in pairs:
            try:
                left,right=lookup[pair['a']],lookup[pair['b']]
                directions=[{'from_candidate_id':a['id'],'to_candidate_id':b['id'],
                    'assessment':self.assessment(a,b,'candidate_assertion',semantic=semantic)}
                    for a,b in ((left,right),(right,left))]
                binder=cc.bind_scoped_equivalence if semantic else cc.bind_scoped_literal
                record=binder(self.sources,self.candidates,[self.nominations],[pair],directions)
                records.append(record);self.save('equivalences/'+digest(pair),record)
            except (ValueError,KeyError,TypeError) as exc:self.error('contextual-equivalence',pair,exc)
        return records

    def diagnostics(self):
        return {'artifact_kind':VERSION,'scopes':list(self.scopes.values()),
            'raw_membership_enabled':self.raw_membership,'raw_comparisons':list(self._raw_comparisons.values()),
            'raw_verification_contract':self.verification_contract,
            'comparisons':list(self._comparisons.values()),'shapes':[s for s in self._shapes.values() if s],
            'errors':deepcopy(self.errors),'holds':deepcopy(self.holds),'capacity_measurements':deepcopy(self.capacity),
            'completed_request_reuse':deepcopy(self.reused),'actual_calls_by_stage':deepcopy(self.call_stages),
            'quality_gate_passed':False}
