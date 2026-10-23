import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import positional_support as p
from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive as write
from commentscope.factory.claim_clusters import sha
from experiments import audit_repeatability_probe as r
from tests.test_positional_support import value


class AuditRepeatabilityTests(unittest.TestCase):
    def case(self):
        text = 'Electric buses reduce local air pollution.'
        schema = p.audit_schema(text)
        req = {'system':p.AUDIT+'\n\nRequired JSON output schema:\n'+json.dumps(schema,ensure_ascii=False,sort_keys=True,separators=(',',':')),
               'data':{'SOURCE':p.parts(text),'TARGET':text},'schema':schema}
        return {'id':digest(req),'request':req,'expected':'support','historical':[]}

    def provider(self,*args):
        return {'choices':[{'message':{'content':json.dumps(value())},'finish_reason':'stop'}],
                'usage':{'prompt_tokens_details':{'cached_tokens':0}}}

    def test_schedules_same_multiset_different_history(self):
        cases = [{'id':'a'},{'id':'b'}]
        a = r.schedule(cases,'blocked'); b = r.schedule(cases,'interleaved')
        self.assertEqual(a,[('a',0),('a',1),('a',2),('b',0),('b',1),('b',2)])
        self.assertEqual(b,[('a',0),('b',0),('a',1),('b',1),('a',2),('b',2)])
        self.assertEqual(sorted(a),sorted(b))
        with self.assertRaises(ValueError): r.schedule(cases,'unknown')

    def test_identical_requests_always_call_provider(self):
        seen = []
        def provider(*args): seen.append(args); return self.provider(*args)
        case = self.case()
        outputs = [r.fresh(case,provider) for _ in range(3)]
        self.assertEqual(len(seen),3)
        self.assertEqual(seen[0],seen[2])
        self.assertEqual(outputs[0]['response'],self.provider())
        self.assertTrue(all(o['decision']['state']=='support' for o in outputs))

    def test_prompt_and_positions_and_schema_tampering_rejected(self):
        case = self.case()
        for part in ['system','data','schema']:
            req = deepcopy(case['request'])
            if part == 'system': req['system'] += 'repair'
            elif part == 'data': req['data']['SOURCE'][0]['start'] = 5
            else: req['schema'] = {}
            with self.assertRaises(ValueError): r.source(req)

    def test_incomplete_or_malformed_is_error_not_support(self):
        def incomplete(*args):
            raw = self.provider(); raw['choices'][0]['finish_reason']='length'; return raw
        self.assertEqual(r.fresh(self.case(),incomplete)['decision']['state'],'error')
        def bad(*args): return {'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
        self.assertEqual(r.fresh(self.case(),bad)['decision']['state'],'error')

    def test_transport_failure_not_retried(self):
        calls = []
        def fail(*args): calls.append(1); raise OSError('offline')
        output = r.fresh(self.case(),fail)
        self.assertEqual(len(calls),1)
        self.assertIsNone(output['response'])
        self.assertEqual(output['decision']['state'],'error')

    def test_projection_change_and_stable_false_accept_separate(self):
        case = self.case(); case['expected']='not_supported'
        plan = {'arms':[r.ARMS[0]],'cases':[case]}
        attempts = [{'arm':r.ARMS[0]['id'],'case':case['id'],**r.fresh(case,self.provider)} for _ in range(3)]
        arm = r.summarize(plan,attempts)['arms'][0]
        self.assertEqual(arm['state_varying_cases'],0)
        self.assertEqual(arm['negative_support_calls'],3)
        attempts[1]['result']['output']['conditions']='unclear'
        attempts[1]['decision']=r.decision(case['request'],attempts[1]['result'])
        arm = r.summarize(plan,attempts)['arms'][0]
        self.assertEqual(arm['state_varying_cases'],1)
        self.assertEqual(arm['cases'][0]['changed_fields'],['conditions'])

    def test_server_commands_differ_only_cache_flag(self):
        plan = {'runtime':{'server':'server','model':'model'}}
        on = r.command(plan,r.ARMS[0]); off = r.command(plan,r.ARMS[2])
        self.assertEqual(on[:-1],off[:-1])
        self.assertEqual(on[-1],'--cache-prompt'); self.assertEqual(off[-1],'--no-cache-prompt')

    def test_replay_no_inference_and_tamper_rejected(self):
        case = self.case(); plan = {'cases':[case],'arms':[r.ARMS[0]],'repeats':3}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); write(root/'plan.json',plan)
            write(root/'started.json',{'plan_sha256':sha(root/'plan.json')})
            ad = root/r.ARMS[0]['id']; write(ad/'stopped.json',{'returncode':0})
            for seq in range(3):
                body = {'arm':r.ARMS[0]['id'],'sequence':seq,'case':case['id'],'repeat':seq,**r.fresh(case,self.provider)}
                write(ad/f'attempt-{seq:03}.json',{'attempt':body,'attempt_sha256':digest(body)})
            with patch.object(r,'local_provider',side_effect=AssertionError('No inference')):
                self.assertEqual(len(r.load_attempts(plan,root)),3)
            path = ad/'attempt-000.json'; row=json.loads(path.read_text()); row['attempt']['repeat']=7
            path.write_text(json.dumps(row))
            with self.assertRaises(ValueError): r.load_attempts(plan,root)


if __name__ == '__main__': unittest.main()
