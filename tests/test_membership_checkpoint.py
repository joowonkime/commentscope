import json
from pathlib import Path
import tempfile
import unittest
from experiments.membership_checkpoint import checkpoint
from experiments.audit_model_compare import command
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write


class MembershipCheckpointTests(unittest.TestCase):
    def setup_run(self, verdicts):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root=Path(tmp.name); source=root/'source'; run=root/'run'
        ids=[f'J{i:03}' for i in range(100)]
        req={'system':'judge','data':{},'schema':{},'max_tokens':180}
        refs={'labels':{rid:'supported' if i<21 else 'unsupported' for i,rid in enumerate(ids)},'runtime_input':False}
        write(source/'references.json',refs)
        write(source/'reference-frozen.json',{'sha256':sha(source/'references.json')})
        plan={'reference_source':str(source),'evaluation_ids':ids,
              'rows':[{'id':rid,'request':req,'request_sha256':digest(req)} for rid in ids]}
        write(run/'plan.json',plan); write(run/'started.json',{'plan_sha256':sha(run/'plan.json')})
        for i,state in verdicts.items():
            out={'verdict':state,'reason':'Recorded decision'}
            write(run/(ids[i]+'.json'),{'request_sha256':digest(req),'result':{
                'raw':json.dumps(out),'output':out,'errors':[]}})
        return run

    def test_partial_never_passes_or_counts_missing_as_negative(self):
        report=checkpoint(self.setup_run({0:'supported'}))
        self.assertEqual(report['observed_evaluation'],1)
        self.assertEqual(len(report['unexecuted_evaluation']),99)
        self.assertFalse(report['development_gate_passed'])
        self.assertFalse(report['cannot_pass'])

    def test_two_false_supports_prove_impossible(self):
        report=checkpoint(self.setup_run({21:'supported',22:'supported'}))
        self.assertAlmostEqual(report['precision_best_possible'],21/23)
        self.assertTrue(report['cannot_pass'])

    def test_five_lost_positives_prove_impossible(self):
        report=checkpoint(self.setup_run({i:'partial' for i in range(5)}))
        self.assertAlmostEqual(report['retention_best_possible'],16/21)
        self.assertTrue(report['cannot_pass'])

    def test_complete_gate_does_not_approve_agents(self):
        report=checkpoint(self.setup_run({i:'supported' if i<21 else 'unsupported' for i in range(100)}))
        self.assertTrue(report['development_gate_passed'])
        self.assertFalse(report['quality_gate_passed'])

    def test_recorded_request_must_match(self):
        run=self.setup_run({0:'supported'})
        # Tampering is deliberate test data, never a production repair.
        record=json.loads((run/'J000.json').read_text()); record['request_sha256']='0'*64
        (run/'J000.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'Recorded request'):checkpoint(run)

    def test_reasoning_command_is_explicitly_bounded(self):
        plan={'server':{'path':'server'},'models':{'baseline':{'path':'model'}},
              'runtime':{'context':4096,'gpu_layers':'all','threads':6,'template_kwargs':{},
                         'reasoning':'on','reasoning_budget':256}}
        args=command(plan,'baseline')
        self.assertEqual(args[args.index('--reasoning-budget')+1],'256')
        self.assertEqual(args[args.index('-ngl')+1],'all')
        for budget in [-1,True,2049]:
            plan['runtime']['reasoning_budget']=budget
            with self.assertRaises(ValueError):command(plan,'baseline')
