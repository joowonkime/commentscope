"""Prune only provably blocked review work; keep the existing publication rules."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from commentscope.factory import candidate_source_coverage as coverage
from commentscope.factory import owned_arguments as owned,source_arguments as sa
import test_candidate_source_coverage as candidate_fixture
import test_shared_typed_pipeline as shared_fixture


class PreflightCandidateTests(TestCase):
    def setUp(self):
        self.fixture=candidate_fixture.CandidateSourceCoverageTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_uncertain_other_candidate_keeps_the_source_for_its_owned_candidate(self):
        for record in self.fixture.h.records:
            self.assertEqual(coverage.potential_candidates(record),[self.fixture.good])
        self.assertEqual(len(self.fixture.prepare()['compiled']['profiles']),1)

    def test_non_scopable_source_failure_stays_blocked_even_with_positive_later_reviews(self):
        for linked in self.fixture.h.records:
            e=linked['extraction_record'];metadata=[owned.bind_metadata(e['graph'],node,
                {'output':{**row['response'],'source_language':'uncertain'}})
                for node,row in zip(e['graph']['nodes'],e['metadata'],strict=True)]
            record=sa.bind_links(owned.declare(e['graph'],e['batch_candidates'],e['support_batches'],metadata,
                e['alignments'],discourse=e.get('discourse')))
            self.assertEqual(coverage.potential_candidates(record),[])

    def test_provenance_is_checked_before_pruning(self):
        record=deepcopy(self.fixture.h.records[0]);record['source']['text']+=' changed'
        with self.assertRaises(ValueError):coverage.potential_candidates(record)


class UnresolvedLanguageRunner(shared_fixture.SharedRunner):
    def call(self,stage,request):
        result=super().call(stage,request)
        if request['system'].startswith(owned.META) and request['data']['ORIGINAL']['source_id']=='0':
            result['output']['source_language']='uncertain'
        return result


class PreflightPipelineTests(TestCase):
    def run_pipeline(self,runner,*,skip_preflight=False):
        helper=shared_fixture.SharedTypedPipelineTests();helper.setUp()
        if skip_preflight:
            with patch.object(coverage,'potential_candidates',side_effect=lambda record:list(record['candidate_ids'])):
                result=helper.run_pipeline(runner)
        else:result=helper.run_pipeline(runner)
        return result,helper.h.saved

    def test_irrecoverable_source_uses_fewer_calls_with_identical_agents_and_bundle(self):
        baseline_runner=UnresolvedLanguageRunner();old,_=self.run_pipeline(baseline_runner,skip_preflight=True)
        runner=UnresolvedLanguageRunner();new,saved=self.run_pipeline(runner)
        self.assertEqual(new['agent_inputs']['bundle'],old['agent_inputs']['bundle'])
        self.assertEqual(new['agent_inputs']['compiled'],old['agent_inputs']['compiled'])
        self.assertEqual(len(new['agent_inputs']['compiled']['profiles']),1)
        self.assertEqual(len(new['arguments']),6)
        self.assertTrue(any(r['source']['id']=='0' for r in new['arguments']))
        self.assertEqual(new['agent_inputs']['map'],old['agent_inputs']['map'])
        self.assertLess(len(runner.calls),len(baseline_runner.calls))
        self.assertTrue(any(h['stage']=='argument-review-preflight' and h['source_id']=='0' for h in new['capacity_holds']))
        self.assertIn('argument-review-preflight',saved)

    def test_complete_sources_keep_two_agents_and_the_same_requests(self):
        before=shared_fixture.SharedRunner();old,_=self.run_pipeline(before,skip_preflight=True)
        after=shared_fixture.SharedRunner();new,_=self.run_pipeline(after)
        self.assertEqual(new['agent_inputs']['compiled'],old['agent_inputs']['compiled'])
        self.assertEqual(new['agent_inputs']['bundle'],old['agent_inputs']['bundle'])
        self.assertEqual(len(new['agent_inputs']['compiled']['profiles']),2)
        self.assertEqual(after.calls,before.calls)
