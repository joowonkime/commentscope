from copy import deepcopy
import unittest

from commentscope.factory import shared_core as c, temporal_guard as t, claim_frame
from experiments.claim_frame_probe import unit


def score(a,b):
    return {'errors':[],'relation':'supports','scores':{'entailment':.9,'neutral':.05,'contradiction':.05}}


class SharedCoreTests(unittest.TestCase):
    def calls(self,system,data,schema):
        if system==c.SYSTEM: return {'output':{'core':'Shared core.'},'errors':[]}
        text=' '.join(data['TEXT'])
        field='time' if system==claim_frame.TASK_SYSTEMS['time'] else 'commitment'
        values={'time':'future' if 'will ' in text else 'present',
                'commitment':'prediction' if 'will ' in text else 'assertion'}
        return {'output':{field:values[field]},'errors':[]}

    def test_temporal_mismatch_blocks_before_proposal(self):
        a,b=unit('a','Jobs are disappearing.','Jobs are disappearing.'),unit('b','Jobs will disappear.','Jobs will disappear.')
        def calls(system,data,schema):
            self.assertNotEqual(system,c.SYSTEM)
            return self.calls(system,data,schema)
        result=c.discover(a,b,calls,score)
        self.assertIsNone(result['selected_core'])
        self.assertIn('pair:time_mismatch',result['blocked_reasons'])

    def test_one_proposal_fixed_candidates_and_shortest_supported(self):
        a,b=unit('a','Original A','Long statement A'),unit('b','Original B','Long statement B')
        proposals=[]
        def calls(system,data,schema):
            if system==c.SYSTEM:
                proposals.append(data)
                self.assertEqual(set(data),{'LEFT','RIGHT'})
            return self.calls(system,data,schema)
        result=c.discover(a,b,calls,score)
        self.assertEqual(len(proposals),1)
        self.assertEqual(len(result['candidates']),3)
        self.assertEqual(result['selected_core'],'Shared core.')

    def test_generated_core_is_not_evidence_or_auto_approval(self):
        a,b=unit('a','Original A','Long statement A'),unit('b','Original B','Long statement B')
        def nli(p,h):
            if h=='Shared core.':
                return {'errors':[],'relation':'not_established','scores':{'entailment':.05,'neutral':.9,'contradiction':.05}}
            return score(p,h)
        result=c.discover(a,b,self.calls,nli)
        self.assertNotEqual(result['selected_core'],'Shared core.')
        self.assertFalse(result['candidates'][-1]['allowed'])

    def test_failed_source_cannot_be_rescued(self):
        a,b=unit('a','A','A'),unit('b','B','B')
        def nli(*args): return {**score(*args),'errors':['RuntimeError']}
        result=c.discover(a,b,self.calls,nli)
        self.assertIsNone(result['proposal'])
        self.assertIsNone(result['selected_core'])

    def test_temporal_trace_binding_and_component_reassembly(self):
        result=t.classify(self.calls,['A'])
        t.validate(['A'],result)
        with self.assertRaises(ValueError): t.validate(['B'],result)
        bad=deepcopy(result);bad['output']['time']='future'
        with self.assertRaises(ValueError): t.validate(['A'],bad)

    def test_explicit_condition_cannot_be_removed_or_changed(self):
        self.assertFalse(c.condition_compatibility('If jobs disappear, help is needed.','Help is needed.',score)['allowed'])
        self.assertTrue(c.condition_compatibility('If rent rises, help is needed.','If rents go up, help is needed.',score)['allowed'])
        def uncertain(a,b): return {**score(a,b),'errors':['RuntimeError']}
        self.assertFalse(c.condition_compatibility('If rent rises, help.','If wages fall, help.',uncertain)['allowed'])
        self.assertFalse(c.condition_compatibility('If A, if B, help.','If A, if B, help.',score)['allowed'])

    def test_proposal_length_and_type(self):
        for value in [None,{}, {'core':4},{'core':'x'*250},{'core':' '}]:
            self.assertTrue(c.validate_proposal(value))
        self.assertFalse(c.validate_proposal({'core':''}))


if __name__=='__main__': unittest.main()
