"""Search cannot create votes, erase sources or spend beyond a frozen scope."""
from copy import deepcopy
from dataclasses import replace
import unittest

from commentscope.factory import perspective_mining as mining, shared_claims as shared
from commentscope.factory import framed_corpus, raw_membership_verification as verify, argument_observations as obs
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate
from test_jev_membership import JevRunner
import test_minimal_pipeline as fixture


def policy(**changes):
    return {'version': mining.VERSION, 'sources_per_candidate': 3, 'maximum_pairs': 6,
            'maximum_sources': 6, 'maximum_snapshot_comments': 3000, **changes}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.root = {'id': 'root', 'text': 'Buses should be free.', 'parent': None}
        self.reply = {'id': 'reply', 'text': 'I agree.', 'parent': {'id': 'root', 'text': self.root['text']}}
        self.other = {'id': 'other', 'text': 'I oppose free buses.', 'parent': None}
        self.sources = [self.root, self.reply, self.other]
        self.target = candidate(self.root, self.root['text'])
        self.sv = {'root': [1., 0.], 'reply': [0., 1.], 'other': [.8, .2]}
    def schedule(self, sources=None, candidates=None, sv=None, cv=None, configuration=None):
        return mining.schedule(sources or self.sources, candidates or [self.target], sv or self.sv,
            cv or {self.target['id']: [1., 0.]}, configuration=configuration or policy())
    def test_parent_retrieves_a_short_reply_without_transferring_support(self):
        result = self.schedule()
        row = next(r for r in result['pair_retrieval'] if r['source_id'] == 'reply')
        self.assertEqual(row['own_similarity'], 0)
        self.assertEqual(row['parent_similarity'], 1)
        self.assertFalse(row['semantic_approval'])
        self.assertNotIn('relation', row)
        self.assertFalse(result['semantic_approval']); self.assertFalse(result['full_corpus_coverage'])
    def test_another_thread_is_considered_before_a_second_same_thread_reply(self):
        result = self.schedule(configuration=policy(sources_per_candidate=2))
        self.assertEqual([p['source_id'] for p in result['pairs']], ['root', 'other'])
        self.assertEqual(result['unassessed_pair_count'], 1)
        self.assertEqual(next(r for r in result['source_states'] if r['source_id']=='reply')['state'], 'not_selected')
    def test_missing_parent_vector_is_not_fabricated(self):
        child = {**self.reply, 'parent': {'id': 'missing', 'text': 'A different original.'}}
        result = self.schedule(sources=[self.root, child, self.other])
        row = next(r for r in result['pair_retrieval'] if r['source_id']=='reply')
        self.assertIsNone(row['parent_similarity'])
    def test_global_limits_preserve_unassessed_nominees(self):
        c2 = candidate(self.other, 'Keep fares.'); cs = [self.target, c2]
        result = self.schedule(candidates=cs, cv={c['id']: [1.,0.] for c in cs},
                               configuration=policy(maximum_pairs=2, maximum_sources=1))
        self.assertLessEqual(len(result['pairs']), 2)
        self.assertLessEqual(len(result['selected_source_ids']), 1)
        self.assertEqual(result['unassessed_pair_count'], 6-len(result['pairs']))
        self.assertTrue(any(s['unassessed_source_count'] for s in result['candidate_states']))
        self.assertEqual(len(result['source_states']), 3)
    def test_many_candidates_do_not_spread_the_budget_below_every_agent_support_minimum(self):
        cs = [candidate(self.root,'Distinct policy option '+str(i)+'.') for i in range(20)]
        result = self.schedule(candidates=cs,cv={c['id']:[1.,0.] for c in cs},
                               configuration=policy(maximum_pairs=6,sources_per_candidate=3))
        funded = [s for s in result['candidate_states'] if s['selected_source_count']]
        self.assertEqual(len(funded),2)
        self.assertTrue(all(s['selected_source_count']==3 for s in funded))
        self.assertEqual(result['unassessed_pair_count'],54)
    def test_changed_original_invalidates_nomination_before_judging(self):
        bad = deepcopy(self.target); bad['nominees']['root'] = '0'*64
        with self.assertRaises(ValueError): self.schedule(candidates=[bad], cv={bad['id']: [1.,0.]})
        changed = [{**self.root,'text':'A changed statement.'}, self.reply, self.other]
        with self.assertRaises(ValueError): self.schedule(sources=changed)
    def test_policy_vector_and_scope_mismatches_are_rejected(self):
        for update in ({'maximum_pairs': True}, {'maximum_snapshot_comments': 3001},
                       {'maximum_pairs': 0}, {'extra': 1}, {'maximum_sources': 7,'maximum_snapshot_comments': 6}):
            with self.subTest(update=update), self.assertRaises(ValueError): mining.policy(policy(**update))
        with self.assertRaises(ValueError): self.schedule(sv={'root':[1.,0.]})
        with self.assertRaises(ValueError): self.schedule(cv={self.target['id']: [1.]})
        with self.assertRaises(ValueError): self.schedule(configuration=policy(maximum_sources=2,maximum_snapshot_comments=2))
    def test_empty_candidate_set_keeps_every_source_without_a_vote(self):
        r = mining.schedule(self.sources, [], self.sv, {}, configuration=policy())
        self.assertFalse(r['pairs']); self.assertEqual(len(r['source_states']), 3)
        self.assertTrue(all(x['state']=='not_selected' for x in r['source_states']))
    def test_two_and_three_thousand_sources_have_bounded_pairs_and_complete_inventory(self):
        for n in (2000,3000):
            sources = [{'id': str(i), 'text': 'Unique statement '+str(i)+'.', 'parent': None} for i in range(n)]
            cs = [candidate(sources[i], 'Policy option '+str(i)+'.') for i in range(4)]
            r = mining.schedule(sources, cs, {s['id']:[1.,0.] for s in sources},
                {c['id']:[1.,0.] for c in cs}, configuration=policy(sources_per_candidate=6,maximum_pairs=20,maximum_sources=12))
            self.assertEqual(len(r['source_states']), n); self.assertLessEqual(len(r['pairs']), 20)
            self.assertLessEqual(len(r['selected_source_ids']), 12)
            self.assertEqual(r['unassessed_pair_count'], n*4-len(r['pairs']))
            self.assertEqual(len({(p['source_id'],p['candidate_id']) for p in r['pairs']}),len(r['pairs']))


class DiscoveryTests(unittest.TestCase):
    def test_one_source_hypothesis_is_preserved_without_changing_legacy_common_rule(self):
        s = {'id':'single','text':'Buses should be free only if hospitals keep their funding.','parent':None}
        output = {'candidates':[{'text':s['text'],'nominees':['A0'],'assertion_kind':'value'}]}
        record = shared.bind([s], {'output':output}, version=shared.MINING)
        self.assertFalse(record['semantic_approval']); self.assertEqual(len(shared.candidates([record])),1)
        with self.assertRaises(ValueError): shared.request([s],version=shared.COMMON_TYPED)
        with self.assertRaises(ValueError):
            shared.bind([s], {'output':{'candidates':output['candidates']*5}},version=shared.MINING)
    def test_larger_registry_is_explicit_and_default_one_thousand_limit_remains(self):
        h = fixture.MinimalPipelineTests(); h.setUp()
        comments = tuple(replace(h.snapshot.comments[0],comment_id=str(i),text_original='Unique '+str(i)+'.') for i in range(3000))
        snapshot = replace(h.snapshot,comments=comments)
        with self.assertRaises(ValueError): framed_corpus.sources(snapshot)
        self.assertEqual(len(framed_corpus.sources(snapshot,maximum_comments=3000)),3000)
        with self.assertRaises(ValueError): framed_corpus.sources(snapshot,maximum_comments=True)


class MiningRunner(JevRunner):
    def call(self, stage, req):
        if req['system'].startswith(shared.MINING_SYSTEM):
            self.calls.append((stage,req)); groups = {}
            for s in req['data']['ORIGINALS']:
                text = s['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.'
                groups.setdefault(text,[]).append(s['author_id'])
            return {'output':{'candidates':[{'text':t,'nominees':ids,'assertion_kind':'value'} for t,ids in groups.items()]},
                    'errors':[], 'raw':'Authored synthetic mining fixture'}
        return super().call(stage,req)


class PipelineTests(unittest.TestCase):
    def setUp(self): self.h = fixture.MinimalPipelineTests(); self.h.setUp()
    def process(self, runner, **changes):
        from commentscope.factory import jev_membership
        args = {'discovery_mode':'shared','membership_mode':'raw','verification_contract':verify.FULL_SCOPE,
            'argument_audit_protocol':obs.SHARED_TYPED_CHAT,'agent_source_policy':'candidate_verified_subset',
            'membership_judge_protocol':jev_membership.VERSION,'membership_search_policy':policy()}
        args.update(changes); return self.h.process(runner,**args)
    def test_selected_pairs_reach_two_agents_and_keep_independent_m2(self):
        runner = MiningRunner(); r = self.process(runner)
        self.assertFalse(r['errors']); self.assertEqual(len(r['agent_inputs']['compiled']['profiles']),2)
        self.assertTrue(all(p['model_core_support_count']==3 for p in r['agent_inputs']['compiled']['profiles']))
        self.assertEqual(len(runner.typed_calls),6)
        self.assertTrue(any(stage.startswith('raw-own-evidence') for stage,_ in runner.calls))
        self.assertFalse(any(stage.startswith('nomination') for stage,_ in runner.calls))
        self.assertEqual(self.h.saved['membership-search']['selected_pair_count'],6)
        self.assertFalse(r['quality_gate_passed'])
    def test_only_selected_sources_pay_for_context_and_world_observations(self):
        runner = MiningRunner(); r = self.process(runner,membership_search_policy=policy(maximum_pairs=2,maximum_sources=2))
        for prefix in ('source-context','source-world'):
            self.assertLessEqual(sum(stage.startswith(prefix) for stage,_ in runner.calls),2)
        self.assertEqual(len(self.h.saved['membership-search']['source_states']),6)
        self.assertFalse(r['agent_inputs']['compiled']['profiles'])
    def test_m2_veto_and_failed_jev_keep_their_existing_holds(self):
        for runner in (MiningRunner(veto=True),MiningRunner(invalid=True)):
            self.h.saved={}; r=self.process(runner)
            self.assertFalse(r['agent_inputs']['compiled']['profiles'])
            self.assertEqual(len(runner.typed_calls),6)
    def test_incompatible_mode_is_rejected_before_any_model_call(self):
        runner=MiningRunner()
        with self.assertRaises(ValueError):self.process(runner,discovery_mode='free')
        self.assertFalse(runner.calls);self.assertFalse(runner.typed_calls)


class CostTests(unittest.TestCase):
    def test_selected_pair_and_source_bounds_replace_full_source_workload_only_when_selected(self):
        import test_factory_cost_plan as cost_fixture
        from commentscope.factory import cost_planning as cost
        h=cost_fixture.CostPlanningTests();h.setUp()
        h.plan['membership_search_policy']=policy(maximum_pairs=2,maximum_sources=2)
        for stage in ('source-context','source-world','membership-raw'):h.work['counts'][stage]=2
        result=h.estimate(goal='development')
        self.assertEqual(result['mining_bounds'],{'pair_upper_bound':2,'source_upper_bound':2})
        self.assertFalse(any(x.startswith('stage_cap_too_small:') for x in result['issues']))
        h.work['counts']['source-context']=1
        self.assertIn('stage_cap_too_small:source-context',h.estimate(goal='development')['issues'])
        del h.plan['membership_search_policy']
        self.assertIn('stage_cap_too_small:membership-raw',h.estimate(goal='development')['issues'])
    def test_mining_cannot_hide_an_unknown_typed_packet_count(self):
        import test_factory_cost_plan as cost_fixture
        from commentscope.factory import jev_membership
        from commentscope.providers import openrouter_decisions as decisions
        h=cost_fixture.CostPlanningTests();h.setUp()
        h.plan.update(membership_search_policy=policy(),membership_judge_protocol=jev_membership.VERSION,
                      membership_deployment=decisions.DEPLOYMENT)
        h.profile=cost_fixture.cost_profile(h.plan)
        h.work['counts']['membership-raw']=0;h.work['counts']['membership-jev']=None
        result=h.estimate(goal='development')
        self.assertIn('membership-jev',result['unknown_stages']);self.assertFalse(result['estimated_feasible'])
