"""Batch transport keeps independent vetoes; fixtures do not measure model quality."""
from copy import deepcopy
import unittest

from commentscope.factory import source_membership_batch as batch, raw_membership as raw
from commentscope.factory import source_context_observations as contexts, statement_worlds as worlds
from commentscope.factory import argument_observations as obs, raw_membership_verification as verify
from commentscope.factory.pipeline_work import PipelineWork
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate
from test_raw_membership_source_context import observation
from test_shared_typed_pipeline import SharedRunner
import test_minimal_pipeline as fixture


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'author','text':'Adopt P only if wages remain unchanged.','parent':None}
        self.targets=[candidate(self.source,t) for t in ('Adopt P only if wages remain unchanged.','Adopt P.')]
        self.context=contexts.bind(self.source,{'output':{'source_use':'substantive_assertion','reported_descriptors':[]}})
        self.world=lambda text:worlds.bind(text,{'output':{'world':'real_world','anchor':''}})
        self.kw={'source_context':self.context,'source_world':self.world(self.source['text']),
                 'candidate_worlds':{c['id']:self.world(c['text']) for c in self.targets}}
        self.output={'decisions':[{'id':'C1',**observation()},
                                   {'id':'C2',**observation(scope_preserved='no')}]}

    def bind(self,value=None):
        return batch.bind(self.source,self.targets,{'output':value or self.output},**self.kw)

    def test_one_author_packet_and_independent_rows_keep_scalar_host_vetoes(self):
        req=batch.request(self.source,self.targets,**self.kw)
        self.assertEqual(set(req['data']),{'ORIGINAL','SOURCE_CONTEXT_OBSERVATION','SOURCE_WORLD_OBSERVATION','CANDIDATE_TARGETS'})
        self.assertEqual(len(req['data']['CANDIDATE_TARGETS']),2)
        a,b=self.bind();self.assertTrue(a['passed']);self.assertFalse(b['passed'])
        self.assertIn('scope_preserved_unapproved',b['guards'])
        for row in (a,b):
            self.assertEqual(raw.validate(row),row)
            self.assertEqual(row['request_sha256'],digest(req))
            self.assertNotEqual(row['logical_request_sha256'],row['request_sha256'])
            self.assertFalse(row['semantic_approval'])

    def test_all_unrelated_and_reordered_rows_are_valid_without_forcing_support(self):
        value=deepcopy(self.output)
        for row in value['decisions']:row['relation']='unrelated'
        expected=self.bind(value);value['decisions'].reverse()
        actual=self.bind(value)
        self.assertEqual([r['output'] for r in actual],[r['output'] for r in expected])
        self.assertFalse(any(r['passed'] for r in actual))

    def test_missing_duplicate_foreign_extra_and_malformed_rows_hold_whole_packet(self):
        for rows in ([],self.output['decisions'][:1],self.output['decisions']*2,
                     [self.output['decisions'][0]]*2,
                     [self.output['decisions'][0],{**self.output['decisions'][1],'id':'foreign'}],
                     [self.output['decisions'][0],{**self.output['decisions'][1],'relation':'invented'}]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.bind({'decisions':rows})
        with self.assertRaises(ValueError):self.bind({'decisions':self.output['decisions'],'extra':True})

    def test_exact_source_world_and_candidate_provenance_cannot_change(self):
        row=self.bind()[0]
        for change in ('source','candidate','request_sha256','logical_request_sha256','output','witness'):
            bad=deepcopy(row)
            if change in ('source','candidate'):bad[change]['text']+=' changed'
            elif change=='output':bad['output']['relation']='unrelated'
            elif change=='witness':bad['batch_witness']['request_sha256']='bad'
            else:bad[change]='bad'
            with self.subTest(change=change),self.assertRaises(ValueError):raw.validate(bad)
        bad=deepcopy(self.kw);bad['source_context']['source']['id']='another author'
        with self.assertRaises(ValueError):batch.request(self.source,self.targets,**bad)
        with self.assertRaises(ValueError):batch.request(self.source,self.targets*4,**self.kw)

    def test_world_and_reported_descriptor_vetoes_are_not_removed_by_batching(self):
        bad=deepcopy(self.kw)
        bad['candidate_worlds'][self.targets[0]['id']]=worlds.bind(self.targets[0]['text'],
            {'output':{'world':'fictional_world','anchor':'P'}})
        rows=batch.bind(self.source,self.targets,{'output':self.output},**bad)
        self.assertFalse(rows[0]['passed']);self.assertIn('independent_world_scope_unapproved',rows[0]['guards'])
        bad=deepcopy(self.output);bad['decisions'][0]['authorship']='not_asserted'
        self.assertFalse(self.bind(bad)[0]['passed'])

    def test_remote_transport_cannot_be_relabelled_as_a_synthetic_or_scalar_receipt(self):
        with self.assertRaises(ValueError):batch.bind(self.source,self.targets,
            {'output':self.output,'transport':{}},**self.kw)

    def test_whole_provider_receipt_is_bound_once_and_tampering_any_row_fails(self):
        from test_remote_verification import parsed
        from commentscope.providers import remote_verification as remote
        result=parsed(self.output)
        rows=batch.bind(self.source,self.targets,result,**self.kw,deployment=remote.SOL)
        self.assertTrue(all(raw.validate(row)==row for row in rows))
        bad=deepcopy(rows[0]);bad['batch_witness']['result']['output']['decisions'][1]['relation']='opposed'
        with self.assertRaises(ValueError):raw.validate(bad)
        bad=deepcopy(result);bad['transport']['provider_response']['provider']='other'
        bad['transport']['provider_response_sha256']=digest(bad['transport']['provider_response'])
        with self.assertRaises(ValueError):batch.bind(self.source,self.targets,bad,**self.kw,deployment=remote.SOL)

    def test_reported_descriptor_cannot_be_adopted_by_a_positive_batch_row(self):
        source={'id':'report','text':'They call residents idle. I disagree.','parent':None}
        target=candidate(source,'Idle residents should receive help.')
        context=contexts.bind(source,{'output':{'source_use':'substantive_assertion',
            'reported_descriptors':[{'segment_id':'S000','text':'idle'}]}})
        value={'decisions':[{'id':'C1',**{**observation(),'reported_descriptor_uses':[{'id':'R000','use':'adopted_report'}]}}]}
        rows=batch.bind(source,[target],{'output':value},source_context=context,
            source_world=self.world(source['text']),candidate_worlds={target['id']:self.world(target['text'])})
        self.assertFalse(rows[0]['passed'])
        self.assertIn('independent_descriptor_attribution_unapproved',rows[0]['guards'])


class BatchRunner(SharedRunner):
    def __init__(self,*,malformed=False,veto_evidence=False,**kw):
        super().__init__(**kw);self.malformed=malformed;self.veto_evidence=veto_evidence

    def call(self,stage,req):
        data=req['data']
        if 'CANDIDATE_TARGETS' in data:
            self.calls.append((stage,req));own=data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')
            rows=[{'id':t['id'],**observation(relation=('unrelated' if self.no_support else
                'supported' if own==t['CANDIDATE']['text'].rstrip('.') else 'opposed'))} for t in data['CANDIDATE_TARGETS']]
            return {'output':{'decisions':rows[:0] if self.malformed else rows},'raw':'authored synthetic batch fixture','errors':[]}
        result=super().call(stage,req)
        if self.veto_evidence and stage.startswith('raw-own-evidence'):
            result['output']['verdict']='extra_assertion'
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.MinimalPipelineTests();self.h.setUp()

    def run_pipeline(self,runner,**kw):
        return self.h.process(runner,discovery_mode='shared',membership_mode='raw',
            verification_contract=verify.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT,
            agent_source_policy='candidate_verified_subset',membership_batch_protocol=batch.VERSION,**kw)

    def test_two_agents_with_three_supports_still_pass_all_independent_host_paths(self):
        scalar_runner=SharedRunner();scalar=self.h.process(scalar_runner,discovery_mode='shared',membership_mode='raw',
            verification_contract=verify.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT,
            agent_source_policy='candidate_verified_subset')
        self.h.saved.clear()
        runner=BatchRunner();result=self.run_pipeline(runner)
        self.assertFalse(result['errors']);self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),2)
        self.assertTrue(all(p['model_core_support_count']==3 for p in result['agent_inputs']['compiled']['profiles']))
        self.assertFalse(result['quality_gate_passed'])
        relations=lambda result:{(r['source_id'],r['candidate_id']):r['relation']
                                 for b in result['memberships'] for r in b['memberships']}
        self.assertEqual(relations(result),relations(scalar))
        self.assertTrue(any('CANDIDATE_TARGETS' in req['data'] for _,req in runner.calls))
        self.assertFalse(any('CANDIDATE' in req['data'] and stage.startswith(('nomination','membership-initial','membership-expanded'))
                             for stage,req in runner.calls))

    def test_bad_packet_cannot_fallback_to_scalar_or_repay_in_a_later_phase(self):
        runner=BatchRunner(malformed=True);result=self.run_pipeline(runner)
        self.assertFalse(result['agent_inputs']['compiled']['profiles']);self.assertTrue(result['errors'])
        self.assertFalse(any('CANDIDATE' in req['data'] and stage.startswith('membership') for stage,req in runner.calls))

    def test_batch_positive_does_not_bypass_independent_evidence_veto(self):
        runner=BatchRunner(veto_evidence=True);result=self.run_pipeline(runner)
        self.assertFalse(result['agent_inputs']['compiled']['profiles'])
        self.assertTrue(any(stage.startswith('raw-own-evidence') for stage,_ in runner.calls))

    def test_protocol_cannot_activate_on_legacy_or_prejudged_memberships(self):
        runner=BatchRunner()
        with self.assertRaises(ValueError):self.h.process(runner,membership_batch_protocol=batch.VERSION)
        self.assertEqual(runner.calls,[])

    def test_exact_pair_reuse_and_failed_pair_hold_across_regrouping(self):
        h=PacketTests();h.setUp();s=h.source;targets=h.targets
        class Runner:
            calls=[]
            def call(_,stage,req):
                _.calls.append((stage,req));return {'output':{'decisions':[
                    {'id':t['id'],**observation(relation='unrelated')} for t in req['data']['CANDIDATE_TARGETS']]}}
        runner=Runner();work=PipelineWork(runner,lambda req:{'fits':True,'request_sha256':digest(req)},lambda *a:None,
            registry={s['id']:s},membership_mode='raw',verification_contract=verify.FULL_SCOPE,schedule={})
        work.membership_batch_protocol=batch.VERSION;work.source_contexts[digest(s)]=h.context
        work.observe_world=lambda text,parent,stage:h.world(text)
        pairs=[{'source_id':s['id'],'candidate_id':c['id']} for c in targets]
        initial=work.judge('nomination',pairs,targets)
        again=work.judge('membership-initial',pairs[::-1],targets)
        self.assertEqual(len(runner.calls),1);self.assertEqual(len(initial),len(again))
        changed=deepcopy(targets);changed[0]['extraction_refs']=sorted([*changed[0]['extraction_refs'],'new provenance'])
        work.judge('membership-expanded',pairs,changed);self.assertEqual(len(runner.calls),2)
        work.source_batch_cache.clear()
        work.judge('membership-expanded',pairs,changed);self.assertEqual(len(runner.calls),2)
        self.assertTrue(any(h['reason']=='prior_source_packet_unavailable_no_retry' for h in work.holds))

    def test_failed_packet_is_not_retried_after_candidate_metadata_changes(self):
        h=PacketTests();h.setUp();s=h.source;targets=h.targets
        class Runner:
            def __init__(self):self.calls=[]
            def call(self,stage,req):
                self.calls.append(req);return {'output':{'decisions':[]},'raw':'malformed fixture'}
        runner=Runner();work=PipelineWork(runner,lambda req:{'fits':True,'request_sha256':digest(req)},lambda *a:None,
            registry={s['id']:s},membership_mode='raw',verification_contract=verify.FULL_SCOPE,schedule={})
        work.membership_batch_protocol=batch.VERSION;work.source_contexts[digest(s)]=h.context
        work.observe_world=lambda text,parent,stage:h.world(text)
        pairs=[{'source_id':s['id'],'candidate_id':c['id']} for c in targets]
        self.assertEqual(work.judge('nomination',pairs[:1],targets),[])
        changed=deepcopy(targets);changed[0]['extraction_refs']=sorted([*changed[0]['extraction_refs'],'new provenance'])
        self.assertEqual(work.judge('membership-initial',pairs[:1],changed),[])
        self.assertEqual(len(runner.calls),1)
        work.judge('membership-expanded',pairs,changed)
        self.assertEqual(len(runner.calls),2)
        self.assertEqual(len(runner.calls[-1]['data']['CANDIDATE_TARGETS']),1)
        self.assertEqual(runner.calls[-1]['data']['CANDIDATE_TARGETS'][0]['CANDIDATE']['text'],targets[1]['text'])

    def test_batch_development_aliases_cannot_change_money_scope_or_role(self):
        from test_shared_factory_trial import SharedTrialTests
        from tools import shared_factory_trial as trial
        h=SharedTrialTests();h.setUp();self.addCleanup(h.doCleanups)
        plan=deepcopy(h.plan);plan.update(membership_batch_protocol=batch.VERSION,stage_aliases=deepcopy(trial.BATCH_ALIASES))
        trial.guard(plan)
        self.assertEqual(plan['spend_scope_sha256'],h.plan['spend_scope_sha256'])
        self.assertEqual(plan['subcap_usd'],'1.50')
        self.assertEqual(trial.mapped_stage('membership-source-batch-'+'a'*20),'membership-initial-raw-'+'a'*20)
        plan['stage_aliases']['membership-source-batch']='runtime'
        with self.assertRaises(ValueError):trial.guard(plan)


class CostAndComparisonTests(unittest.TestCase):
    def test_batch_cannot_borrow_scalar_prices_or_undersized_batch_samples(self):
        from test_factory_cost_plan import CostPlanningTests
        from commentscope.factory import cost_planning as cost
        h=CostPlanningTests();h.setUp();h.plan['membership_batch_protocol']=batch.VERSION
        h.work['counts']['membership-raw']=0
        h.profile['stages'].pop('membership-source-batch')
        self.assertIn('membership-source-batch',h.estimate()['unknown_stages'])
        h.profile['stages']['membership-source-batch']={**h.profile['stages']['membership-raw'],'maximum_batch_targets':1}
        self.assertIn('membership-source-batch',h.estimate()['unknown_stages'])
        h.profile['stages']['membership-source-batch']['maximum_batch_targets']=2
        self.assertNotIn('membership-source-batch',h.estimate()['unknown_stages'])
        req={'data':{'CANDIDATE_TARGETS':[{},{}]}}
        self.assertEqual(cost.canonical('verification-membership-initial-raw',req),'membership-source-batch')

    def test_physical_budget_counts_one_batch_and_refuses_next_distinct_packet(self):
        from commentscope.factory import cost_planning as cost
        caps=dict.fromkeys(cost.STAGES,0);caps['membership-source-batch']=1
        limits=cost.CallLimits(caps)
        req={'data':{'CANDIDATE_TARGETS':[{},{}]}}
        limits.admit('verification-membership-initial-raw',req)
        limits.admit('verification-membership-initial-raw',deepcopy(req))
        with self.assertRaises(cost.CostPlanError):limits.admit('verification-membership-initial-raw',{'data':{'CANDIDATE_TARGETS':[{}]}})
        self.assertEqual(limits.used['membership-source-batch'],1)

    def test_comparison_never_combines_different_phases_or_ambiguous_role_aliases(self):
        from tools.compare_membership_transport import compare_requests
        from commentscope.providers import remote_verification as remote,openrouter
        from commentscope.providers.generation_limits import allocate
        h=PacketTests();h.setUp()
        logical=batch.logical_requests(h.source,h.targets,h.kw['source_context'],h.kw['source_world'],h.kw['candidate_worlds'])
        allocated=[allocate(r,openrouter.generation_allocation(remote.SOL)) for r in logical]
        rows=[('verification-membership-initial-raw',req,{'fixture':True}) for req in allocated]
        joined=compare_requests(rows,remote.SOL)
        self.assertEqual(joined['scalar_requests'],2);self.assertEqual(joined['batched_requests'],1)
        self.assertTrue(joined['all_archived_pairs_preserved']);self.assertEqual(joined['new_model_calls'],0)
        split=compare_requests(rows,remote.SOL,phases={digest(allocated[0]):'nomination',digest(allocated[1]):'initial'})
        self.assertEqual(split['batched_requests'],2)
        unknown=compare_requests(rows,remote.SOL,phases={})
        self.assertEqual(unknown['batched_requests'],2)
        self.assertIsNone(unknown['actual_batch_cost_usd'])
