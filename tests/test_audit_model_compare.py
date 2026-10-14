import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from experiments import audit_model_compare as m
from experiments import audit_repeatability_probe as prior
from commentscope.factory.automatic_contract import digest


class AuditModelComparisonTests(unittest.TestCase):
    def test_exact_prompt_schema_and_source_contract(self):
        req=m.audit_request('조건이 중요하다. Another statement.','조건이 중요하다.')
        self.assertEqual(prior.source(req),'조건이 중요하다. Another statement.')
        self.assertEqual(req['data']['TARGET'],'조건이 중요하다.')
        self.assertNotIn('expected',req['data'])

    def test_duplicate_requests_keep_distinct_evaluation_memberships(self):
        req=m.audit_request('Source.','Source.')
        old={'cases':[{'id':'x','request':req,'expected':'support'}]}
        fidelity={'cases':[{'id':'f','source':'Source.','target':'Source.','expected':True}]}
        eligibility={'cases':[{'id':'e','source':'Source.','expected':True}]}
        rows,requests=m.make_cases(old,fidelity,eligibility)
        self.assertEqual(len(rows),3); self.assertEqual(len(requests),1)
        self.assertEqual({r['request_id'] for r in rows},{digest(req)})

    def test_eligibility_uses_complete_original_as_target(self):
        text='The bus is late. It should arrive on time.'
        rows,requests=m.make_cases({'cases':[]},{'cases':[]},{'cases':[{'id':'e','source':text,'expected':True}]})
        self.assertEqual(requests[0]['request']['data']['TARGET'],text)
        self.assertEqual(prior.source(requests[0]['request']),text)

    def test_label_changes_never_change_model_request(self):
        cases={'cases':[{'id':'f','source':'A.','target':'B.','expected':True}]}
        a=m.make_cases({'cases':[]},cases,{'cases':[]})
        cases['cases'][0]['expected']=False
        b=m.make_cases({'cases':[]},cases,{'cases':[]})
        self.assertNotEqual(a[0],b[0]); self.assertEqual(a[1],b[1])

    def test_commands_change_model_only(self):
        plan={'server':{'path':'server'},'models':{'baseline':{'path':'4b'},'candidate':{'path':'8b'}},'runtime':m.RUNTIME}
        a=m.command(plan,'baseline'); b=m.command(plan,'candidate')
        self.assertEqual([(x,y) for x,y in zip(a,b) if x!=y],[('4b','8b')])
        self.assertIn('--no-cache-prompt',a)
        self.assertIn('{"enable_thinking": false}',a)

    def comparison(self):
        rows=[{'id':str(i),'cohort':'repeatability_controls','request_id':str(i),'expected':i<10} for i in range(12)]
        plan={'model_order':['baseline','candidate'],'rows':rows,'requests':[{}]*12}
        def row(state):return {'decision':{'state':state,'errors':[]},'result':{'seconds':1}}
        baseline={str(i):row('support' if i<6 else 'uncertain') for i in range(12)}
        candidate={str(i):row('support' if i<10 else 'not_supported') for i in range(12)}
        return plan,{'baseline':baseline,'candidate':candidate}

    def test_success_only_qualifies_for_trial_not_production(self):
        plan,records=self.comparison(); report=m.summarize(plan,records)
        self.assertTrue(report['candidate_eligible_for_full_pipeline_trial'])
        self.assertFalse(report['quality_gate_passed']); self.assertEqual(report['agents'],[])

    def test_false_accept_disqualifies_even_with_perfect_positive_retention(self):
        plan,records=self.comparison(); records['candidate']['10']['decision']['state']='support'
        report=m.summarize(plan,records)
        self.assertFalse(report['candidate_eligible_for_full_pipeline_trial'])
        self.assertEqual(report['models']['candidate']['cohorts']['repeatability_controls']['negative_false_support'],1)

    def test_error_is_not_correct_negative(self):
        plan,records=self.comparison()
        records['candidate']['10']['decision']={'state':'error','errors':['transport_error']}
        report=m.summarize(plan,records)
        self.assertFalse(report['candidate_eligible_for_full_pipeline_trial'])
        c=report['models']['candidate']['cohorts']['repeatability_controls']
        self.assertEqual(c['errors'],1); self.assertEqual(c['negative_rejected'],1)

    def test_positive_loss_or_low_recall_disqualifies(self):
        plan,records=self.comparison()
        for i in range(5,10): records['candidate'][str(i)]['decision']['state']='uncertain'
        report=m.summarize(plan,records)
        self.assertFalse(report['candidate_trial_checks']['positive_kept_at_least_baseline_in_every_cohort'])
        self.assertFalse(report['candidate_trial_checks']['repeatability_positive_kept_at_least_9'])

    def test_busy_port_never_starts_or_stops_external_process(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m.socket,'socket') as sock,patch.object(m.subprocess,'Popen') as proc:
                sock.return_value.__enter__.return_value.bind.side_effect=OSError('busy')
                with self.assertRaises(OSError):
                    with m.owned_server({},'candidate',Path(temp)/'run'): pass
                proc.assert_not_called()

    def test_owned_server_startup_failure_is_cleaned_up(self):
        plan={'server':{'path':'server','libraries':'libs'},'models':{'candidate':{'path':'model'}},'runtime':m.RUNTIME}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m.socket,'socket'),patch.object(m.subprocess,'Popen') as factory:
                proc=factory.return_value; proc.poll.return_value=1; proc.pid=123; proc.returncode=1
                with self.assertRaises(RuntimeError):
                    with m.owned_server(plan,'candidate',Path(temp)/'run'): pass
                self.assertTrue((Path(temp)/'run/stopped.json').exists())
                proc.send_signal.assert_not_called()


if __name__=='__main__': unittest.main()
