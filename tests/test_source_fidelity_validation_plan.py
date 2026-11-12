"""Offline plan boundaries: no provider calls, reservations or semantic approval."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from tools import prepare_source_fidelity_validation as plan
from commentscope.factory import source_evidence_graph as g
from commentscope.providers import remote_verification as remote,openrouter
from commentscope.factory.automatic_contract import digest
from test_source_evidence_graph import observation_example


FIXTURE=Path(__file__).parent/'fixtures/source-fidelity-controls-v1.json'


class FidelityValidationPlanTests(TestCase):
    def test_fixed_pairs_have_valid_addresses_hidden_expectations_and_real_wire_bounds(self):
        fixture=json.loads(FIXTURE.read_text());pack=plan.controls(fixture,remote.SOL)
        self.assertEqual(len(pack['cases']),16)
        self.assertEqual({r['family'] for r in pack['cases']},{r['family'] for r in fixture['families']})
        self.assertEqual(plan.controls(fixture,remote.SOL),pack)
        for row in pack['cases']:
            self.assertNotIn('variant',row['request']['data']);self.assertNotIn('family',row['request']['data'])
            self.assertNotIn('expected',row['request']['data']);self.assertNotIn('CANDIDATES',row['request']['data'])
            self.assertEqual(row['request'],g.observation_request(row['proposal']))
            capacity=openrouter.Client(remote.SOL).measure(row['request'])
            self.assertEqual(row['capacity'],capacity);self.assertTrue(capacity['fits'])

    def test_proposal_mutations_reach_auditor_instead_of_failing_host_binding(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
        for row in pack['cases']:
            # A conforming all-pass audit is intentionally fallible. Each bad
            # proposal must challenge the auditor rather than a bad address.
            p=row['proposal'];o=observation_example(p)
            self.assertEqual(g.verify(p,g.bind_observation(p,{'output':o}))['status'],'complete')

    def test_whole_control_batch_rejects_five_dollars_without_trimming_or_zeroing_unknown_work(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
        for cap,ready in [('5',False),('6',True)]:
            result=plan.cost_review(pack,proposed_usd=cap,account_remaining_usd='24',key_remaining_usd='130')
            self.assertEqual(result['controls_fit'],ready)
            self.assertFalse(result['dispatch_enabled']);self.assertFalse(result['full_comparison_admitted'])
            self.assertIsNone(result['full_comparison_estimated_usd'])
            self.assertFalse(result['financial_authorization']);self.assertEqual(result['new_model_calls'],0)
        self.assertFalse(plan.cost_review(pack,proposed_usd='6',account_remaining_usd='5.7',key_remaining_usd='130')['controls_fit'])

    def test_changed_deployment_or_request_cannot_keep_stale_reservation(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
        for mutate in (lambda x:x['cases'][0]['request'].update(max_tokens=1),
                       lambda x:x['deployment'].update(reasoning_output_tokens=1),
                       lambda x:x.update(planner_sha256='0'*64),
                       lambda x:x['cases'][0].update(maximum_reservation_usd='0')):
            wrong=deepcopy(pack);mutate(wrong)
            with self.assertRaises(ValueError):plan.cost_review(wrong,proposed_usd='6',account_remaining_usd='24',key_remaining_usd='130')

    def test_reference_gaps_and_thread_leakage_remain_explicit(self):
        sources={str(i):{'source':{'id':str(i),'text':'Synthetic '+str(i),'parent':None}} for i in range(100)}
        review=dict(development=[dict(source=sources[str(i)]['source'],source_sha256=digest(sources[str(i)]['source']),expected_semantics=None) for i in range(48)],
            transfer=[dict(source_id=str(i),source_sha256=digest(sources[str(i)]['source'])) for i in range(48,96)])
        result=plan.split_review(review,sources)
        self.assertEqual(result['development_unannotated'],48);self.assertFalse(result['semantic_benchmark_ready'])
        self.assertFalse(result['independent_human_gold']);self.assertEqual(result['overlapping_threads'],[])
        sources['48']['source']['parent']={'id':'0','text':'Synthetic 0'}
        review['transfer'][0]['source_sha256']=digest(sources['48']['source'])
        with self.assertRaises(ValueError):plan.split_review(review,sources)

    def test_scoring_separates_unknown_block_from_detection_and_never_drops_missing_calls(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
        answers={}
        for row in pack['cases']:
            o=observation_example(row['proposal'])
            if row['variant']=='distorted':o['dependency_coverage']='unknown'
            answers[row['case_id']]={'output':o}
        result=plan.score_controls(pack,answers)
        self.assertEqual(result['distorted_blocked'],8);self.assertEqual(result['distorted_detected'],0)
        self.assertFalse(result['next_stage_ready']);self.assertFalse(result['semantic_adoption'])
        del answers[pack['cases'][0]['case_id']]
        result=plan.score_controls(pack,answers)
        self.assertEqual(result['planned_cases'],16);self.assertEqual(result['missing_cases'],1)
        self.assertFalse(result['next_stage_ready'])

    def test_unrelated_failure_is_a_block_without_credit_for_the_declared_problem(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
        row=next(r for r in pack['cases'] if r['family']=='negation' and r['variant']=='distorted')
        o=observation_example(row['proposal']);o['unit_observations'][0]['premises_complete']='fail'
        result=plan.score_controls(pack,{row['case_id']:{'output':o}})
        self.assertEqual(result['distorted_blocked'],1);self.assertEqual(result['distorted_detected'],0)

    def test_scripted_answers_cannot_admit_profiling_and_fixed_floor_is_enforced(self):
        pack=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL);answers={}
        for row in pack['cases']:
            o=observation_example(row['proposal'])
            if row['variant']=='distorted':
                unit,fields=next(iter(row['expected_detection']['unit_failures'].items()))
                next(u for u in o['unit_observations'] if u['unit_id']==unit)[fields[0]]='fail'
            answers[row['case_id']]={'output':o}
        self.assertFalse(plan.score_controls(pack,answers)['next_stage_ready'])
        with patch.object(remote,'parsed_receipt',return_value={}):
            self.assertTrue(plan.score_controls(pack,answers)['next_stage_ready'])
            faithful=[r for r in pack['cases'] if r['variant']=='faithful']
            for row in faithful[:3]:answers[row['case_id']]['output']['scope_coverage']='unknown'
            self.assertTrue(plan.score_controls(pack,answers)['next_stage_ready'])
            answers[faithful[3]['case_id']]['output']['scope_coverage']='unknown'
            self.assertFalse(plan.score_controls(pack,answers)['next_stage_ready'])

    def test_planning_can_run_with_network_disabled_and_refuses_changed_frozen_output(self):
        with tempfile.TemporaryDirectory() as temp,patch('urllib.request.urlopen',side_effect=AssertionError('offline')):
            dest=Path(temp)/'pack.json';value=plan.controls(json.loads(FIXTURE.read_text()),remote.SOL)
            plan.freeze(dest,value);plan.freeze(dest,value)
            plan.freeze(dest,dict(reversed(list(value.items()))))
            changed=deepcopy(value);changed['cases'].pop()
            with self.assertRaises(ValueError):plan.freeze(dest,changed)
            self.assertFalse((dest.parent/'authorization.json').exists())

    def test_build_preserves_closed_money_history_and_unannotated_split_without_dispatch(self):
        from commentscope.factory.claim_clusters import sha
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);artifacts=root/'artifacts';artifacts.mkdir();prior=root/'prior';(prior/'B').mkdir(parents=True)
            def save(path,value):path.write_text(json.dumps(value));return path
            registry={str(i):{'source':{'id':str(i),'text':'Synthetic '+str(i),'parent':None}} for i in range(100)}
            review=dict(development=[dict(source=registry[str(i)]['source'],source_sha256=digest(registry[str(i)]['source']),expected_semantics=None) for i in range(48)],
                transfer=[dict(source_id=str(i),source_sha256=digest(registry[str(i)]['source'])) for i in range(48,96)])
            review_file=save(root/'review.json',review)
            perspectives=[dict(id='a',minimum_support_met=True,supported_canonical_ids=['0','1','2']),dict(id='b',minimum_support_met=True,supported_canonical_ids=['3','4','5'])]
            for name,value in [('source-discourse',registry),('map',{'opinion_map':{'perspectives':perspectives}}),('candidates',[]),('memberships',[])]:save(artifacts/(name+'.json'),value)
            annotations=save(root/'annotations.json',dict(reviewer_kind='coding_agent_not_independent_human_gold',cases=[dict(candidate_id=p['id'],source_id=s) for p in perspectives for s in p['supported_canonical_ids']]))
            generation=deepcopy(remote.SOL);generation.update(model='openai/gpt-5.2',context=400000);generation.pop('billing_ceiling');generation['provider']['max_price']={'prompt':1.75,'completion':14,'request':0}
            old=dict(deployment=generation,inputs={str(annotations):sha(annotations)},baseline_artifacts=str(artifacts),annotations=str(annotations),spend_scope_sha256='a'*64,source_evidence_protocol='source-evidence-graph-20261111-v1')
            old_file=save(prior/'B/plan.json',old)
            close=dict(phase={'reserved_calls':0,'uncertain_calls':0},account={'charged_usd':'20'})
            close_file=save(prior/'financial-close.json',close);save(prior/'outcome.json',{'status':'budget_stopped_no_new_inference'})
            def endpoint(dep):return dict(tag='openai',context_length=dep['context'],supported_parameters=sorted(openrouter.required_parameters(dep)),pricing={k:str(v/(1 if k=='request' else 1_000_000)) for k,v in dep['provider']['max_price'].items()})
            observations=dict(new_model_calls=0,generation_endpoint=endpoint(generation),verification_endpoint=endpoint(remote.SOL),
                account={'charged_usd':'25','remaining_usd':'25','maximum_usd':'50','reserved_calls':0,'uncertain_calls':0},key_metadata={'limit':150,'limit_remaining':130})
            observed_file=save(root/'observations.json',observations)
            with patch('urllib.request.urlopen',side_effect=AssertionError('No inference or HTTP')):
                result=plan.build(old_file,review_file,FIXTURE,observed_file)
            self.assertEqual(result['source_inventory']['eligible_sources'],6)
            self.assertEqual(len(result['source_inventory']['representative_profiling']),3)
            self.assertEqual(result['split_review']['development_unannotated'],48)
            self.assertIsNone(result['authorization']);self.assertIsNone(result['new_money_owner']);self.assertFalse(result['dispatch_enabled'])
            self.assertIsNone(result['budget_policy']['small_subcap_usd'])
            self.assertTrue(result['budget_policy']['account_reconciliation_required'])
            observations['account']['charged_usd']='19';save(observed_file,observations)
            with self.assertRaisesRegex(ValueError,'regressed'):plan.build(old_file,review_file,FIXTURE,observed_file)
            observations['account']['charged_usd']='25';save(observed_file,observations)
            close['phase']['reserved_calls']=1;save(close_file,close)
            with self.assertRaisesRegex(ValueError,'closed'):plan.build(old_file,review_file,FIXTURE,observed_file)
