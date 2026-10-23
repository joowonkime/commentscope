from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha,read_json
from commentscope.storage import write_json_exclusive as write
from experiments.reasoning_membership_probe import execute


class ReasoningExecutionTests(unittest.TestCase):
    def test_mathematical_failure_stops_calls_and_closes_owned_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';run=root/'run'
            ids=[f'J{i:03}' for i in range(100)]
            labels={rid:'supported' if i>=79 else 'unsupported' for i,rid in enumerate(ids)}
            write(source/'references.json',{'labels':labels,'runtime_input':False})
            write(source/'reference-frozen.json',{'sha256':sha(source/'references.json')})
            rows=[]
            for rid in ids:
                req={'system':'judge','data':{'SOURCE':rid},'schema':{},'max_tokens':512}
                rows.append({'id':rid,'request':req,'request_sha256':digest(req)})
            plan={'reference_source':str(source),'rows':rows,'evaluation_ids':ids,
                  'plumbing_only':False,'stop_on_impossible':True}
            write(run/'plan.json',plan)
            budget=Mock();budget.summary.return_value={'charged_seconds':2}
            budget.call.return_value={'choices':[{'finish_reason':'stop','message':{
                'content':json.dumps({'verdict':'supported','reason':'Synthetic wrong approval'}),
                'reasoning_content':'Synthetic fixture, not model inference'}}]}
            closed=[]
            @contextmanager
            def server(*args):
                try:yield
                finally:closed.append(True)
            with patch('experiments.reasoning_membership_probe.validate'), \
                 patch('experiments.reasoning_membership_probe.InferenceBudget',return_value=budget), \
                 patch('experiments.reasoning_membership_probe.owned_server',server):
                execute(run)
            self.assertEqual(budget.call.call_count,2)
            self.assertEqual(closed,[True])
            result=read_json(run/'early-stopped.json')
            self.assertEqual(result['planned_evaluation'],100)
            self.assertEqual(result['observed_evaluation'],2)
            self.assertEqual(len(result['unexecuted_evaluation']),98)
            self.assertFalse(result['development_gate_passed'])
            self.assertFalse((run/'completed.json').exists())
            for call in budget.call.call_args_list:
                self.assertEqual(set(call.args[0]['data']),{'SOURCE'})
