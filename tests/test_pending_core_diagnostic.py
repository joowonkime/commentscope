from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock

from commentscope.storage import write_json_exclusive as write
from experiments import pending_core_diagnostic as p
from tests import test_fresh_grounded_pipeline as fixtures


class PendingCoreTests(TestCase):
    def tasks(self):
        return [{'proposal':{'id':f'P{i}', 'claims':{'C':{'id':'C','text':'A position.',
            'kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}},
            'sources':{f's{j}':f'Original {j}.' for j in range(5)}}} for i in range(5)]

    def measure(self, root, verdict, exhausted=False):
        plan = {'tasks':self.tasks(), 'membership_policy':fixtures.FreshGroundedPipelineTests().policy(),
                'limits':{'call_seconds':90}}
        runner = Mock(); runner.seq = 0
        if exhausted: runner.timeout.side_effect = TimeoutError
        def call(stage, req):
            runner.seq += 1
            return {'errors':[], 'output':{'verdict':verdict,'reason':'Synthetic fixture'}}
        runner.call.side_effect = call
        original = deepcopy(plan)
        result = p.measure(root, plan, runner)
        self.assertEqual(plan, original)
        return result, runner

    def test_whole_population_and_support_are_not_agent_approval(self):
        with TemporaryDirectory() as tmp:
            result, runner = self.measure(Path(tmp), 'supported')
            self.assertEqual([r['id'] for r in result], [f'P{i}' for i in range(5)])
            self.assertTrue(all(r['state']=='core_ready_not_agent' and r['model_support_count']==5 for r in result))
            # Same requests across these synthetic candidates reuse within-run responses only.
            self.assertEqual(runner.call.call_count, 5)

    def test_negative_bound_does_not_turn_unknown_into_negative(self):
        with TemporaryDirectory() as tmp:
            result, _ = self.measure(Path(tmp), 'unsupported')
            self.assertTrue(all(r['state']=='insufficient_core_support' for r in result))
            m = p.read_json(Path(tmp)/'candidates/P0/membership.json')
            self.assertEqual(list(m['actual'].values()).count('unassessed'), 2)

    def test_exhaustion_retains_all_candidates_and_unknown_relations(self):
        with TemporaryDirectory() as tmp:
            result, runner = self.measure(Path(tmp), 'supported', exhausted=True)
            self.assertTrue(all(r['state']=='unprocessed_core_budget' and r['support_upper_bound']==5 for r in result))
            runner.call.assert_not_called()

    def test_call_cap_and_followup_reserve(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); plan={'limits':{'analysis_seconds':1200}}; write(root/'plan.json', plan)
            budget=Mock(); budget.summary.return_value={'charged_seconds':0,'remaining_seconds':653}
            runner=p.Runner(root, plan, budget)
            self.assertEqual(runner.timeout(90), 50)
            budget.summary.return_value={'charged_seconds':600,'remaining_seconds':1200}
            with self.assertRaises(TimeoutError): runner.timeout(90)

    def test_minimum_support_does_not_disguise_incomplete_count(self):
        with TemporaryDirectory() as tmp:
            plan={'tasks':self.tasks(), 'membership_policy':fixtures.FreshGroundedPipelineTests().policy(),
                  'limits':{'call_seconds':90}}
            runner=Mock(); runner.seq=0; runner.timeout.side_effect=[90,90,90,TimeoutError()]
            def call(stage, req):
                runner.seq+=1
                return {'errors':[], 'output':{'verdict':'supported','reason':'Synthetic fixture'}}
            runner.call.side_effect=call
            outcomes=p.measure(Path(tmp),plan,runner)
            self.assertEqual(outcomes[0]['state'],'minimum_met_incomplete_not_agent')
            self.assertEqual(outcomes[0]['model_support_count'],3)
            self.assertEqual(outcomes[0]['support_upper_bound'],5)
            self.assertEqual(len(outcomes),5)


if __name__=='__main__': main()
