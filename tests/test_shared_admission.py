import unittest

from commentscope.factory import shared_admission, shared_claims, minimal_membership as mm
from commentscope.factory import raw_membership as raw, raw_membership_verification as verification
from commentscope.factory import owned_arguments as oa
from commentscope.factory.automatic_contract import digest


class ScriptedAdmission:
    def __init__(self, *, core_kind='value', extra_evidence=False, unrelated=False, fail=False):
        self.calls=[]; self.core_kind=core_kind; self.extra_evidence=extra_evidence
        self.unrelated=unrelated; self.fail=fail
    def call(self, stage, req):
        self.calls.append((stage,req)); system=req['system']; data=req['data']
        if self.fail: return {'raw':None,'output':None,'errors':['transport_error']}
        if system.startswith(verification.FOCUS):
            value={'focus_token':'T1','focus_domain':'substantive_issue','role':'subject_position','interpretation':'clear'}
        elif system.startswith(oa.CORE):
            value={'kind':self.core_kind,'entity':'P','time_ids':[]}
        elif system.startswith(raw.SYSTEM):
            original=data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text']
            relation='unrelated' if self.unrelated else 'supported' if original.split(' because ')[0].rstrip('.')+'.'==data['CANDIDATE']['text'] else 'opposed'
            value={'relation':relation,'authorship':'asserted_or_endorsed','candidate_interpretation':'clear',
                   'scope_preserved':'yes','contribution':'substantive','evidence_segment_ids':['S000']}
        elif system.startswith(verification.ALIGNED_EVIDENCE):
            value={'reference_basis':'self_contained','target_alignment':'aligned',
                   'source_basis':'own_assertion','verdict':'extra_assertion' if self.extra_evidence else 'fully_stated'}
        else: raise AssertionError('Unexpected inference stage')
        return {'raw':'toy scripted response only','output':value,'errors':[]}


class SharedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':str(i),'text':('Adopt P.' if i<3 else 'Reject P.'),'parent':None} for i in range(6)]
        proposal=shared_claims.bind(self.sources,{'output':{'candidates':[
            {'text':'Adopt P.','nominees':['A0','A1','A2']},
            {'text':'Reject P.','nominees':['A3','A4','A5']}]}},version=shared_claims.COMMON)
        self.candidates=shared_claims.candidates([proposal])
        self.sv={s['id']:[1.,0.] for s in self.sources}
        self.cv={c['id']:[1.,0.] for c in self.candidates}
        self.saved={}
    def inspect(self,req): return {'request_sha256':digest(req),'fits':True}
    def process(self,runner,on_shared,**kwargs):
        return shared_admission.process(self.sources,self.candidates,self.sv,self.cv,runner,
            kwargs.get('inspect',self.inspect),on_shared=on_shared,
            save=lambda name,value:self.saved.update({name:value}))

    def test_callback_requires_three_independent_sources_and_keeps_votes_unique(self):
        calls=[]
        def callback(batches,outcomes):
            rows=mm.collect(self.sources,self.candidates,batches)
            calls.append(rows)
            self.assertTrue(any(len(o['supported_sources'])==3 for o in outcomes))
            return len(calls)==2
        runner=ScriptedAdmission(); out=self.process(runner,callback)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(len(o['supported_sources'])==3 for o in out['outcomes']))
        self.assertEqual(len(out['memberships']),6)
        self.assertEqual(out['stop_reason'],'downstream_compiled_distinct_agents_ready')
        self.assertFalse(out['semantic_approval']);self.assertFalse(out['quality_gate_passed'])
        self.assertEqual(out['processing_ids'],[str(i) for i in range(6)])

    def test_positive_raw_proposals_never_count_without_independent_own_evidence(self):
        callback=[];out=self.process(ScriptedAdmission(extra_evidence=True),lambda *args:callback.append(args))
        self.assertFalse(callback)
        self.assertTrue(all(not o['supported_sources'] for o in out['outcomes']))
        rows=mm.collect(self.sources,self.candidates,out['memberships'])
        self.assertFalse(any(r['relation']=='supported' for r in rows))

    def test_fact_or_uncertain_cores_remain_unassessed_not_retyped(self):
        for kind in ('fact','uncertain'):
            runner=ScriptedAdmission(core_kind=kind);calls=[]
            out=self.process(runner,lambda *args:calls.append(args))
            with self.subTest(kind=kind):
                self.assertFalse(out['memberships']);self.assertFalse(calls)
                self.assertTrue(all(c['output']['kind']==kind for c in out['cores']))
                self.assertFalse(any(req['system'].startswith(raw.SYSTEM) for _,req in runner.calls))

    def test_zero_support_stops_initial_retrieval_and_leaves_other_sources_unassessed(self):
        extra=[{'id':f'x{i}','text':'An unrelated statement.','parent':None} for i in range(24)]
        self.sources.extend(extra);self.sv.update({s['id']:[1.,0.] for s in extra})
        out=self.process(ScriptedAdmission(unrelated=True),lambda *args:False)
        self.assertTrue(all(len(o['assessed_sources'])==9 for o in out['outcomes']))
        self.assertTrue(all(not o['supported_sources'] for o in out['outcomes']))
        self.assertEqual(len(out['processing_ids']),30)

    def test_capacity_hold_and_ambiguous_transport_never_retry(self):
        runner=ScriptedAdmission();out=self.process(runner,lambda *a:False,
            inspect=lambda req:{'request_sha256':digest(req),'fits':False})
        self.assertFalse(runner.calls);self.assertTrue(out['capacity_holds'])
        runner=ScriptedAdmission(fail=True)
        with self.assertRaises(RuntimeError):self.process(runner,lambda *a:False)
        self.assertEqual(len(runner.calls),1)

    def test_initial_screening_of_all_candidates_precedes_deep_single_source_expansion(self):
        extra=[{'id':f'x{i}','text':'Another issue.','parent':None} for i in range(24)]
        self.sources.extend(extra);self.sv.update({s['id']:[1.,0.] for s in extra})
        class OneSupport(ScriptedAdmission):
            def call(self,stage,req):
                result=super().call(stage,req)
                if req['system'].startswith(raw.SYSTEM):
                    wanted='0' if req['data']['CANDIDATE']['text']=='Adopt P.' else '3'
                    result['output']['relation']='supported' if req['data']['ORIGINAL']['source_id']==wanted else 'unrelated'
                return result
        runner=OneSupport();out=self.process(runner,lambda *args:False)
        originals=[req for _,req in runner.calls if req['system'].startswith(raw.SYSTEM)]
        first=originals[0]['data']['CANDIDATE']['text']
        self.assertTrue(all(r['data']['CANDIDATE']['text']==first for r in originals[:9]))
        self.assertNotEqual(originals[9]['data']['CANDIDATE']['text'],first)
        self.assertEqual(len(originals),48)
        self.assertEqual(len({(r['data']['CANDIDATE']['text'],r['data']['ORIGINAL']['source_id']) for r in originals}),48)
        self.assertTrue(all(len(o['supported_sources'])==1 for o in out['outcomes']))

    def test_previous_interruption_remains_unassessed_instead_of_retried_or_counted(self):
        class Unavailable(ScriptedAdmission):
            def call(self,stage,req):
                if req['system'].startswith(raw.SYSTEM) and req['data']['ORIGINAL']['source_id']=='0':
                    self.calls.append((stage,req));raise shared_admission.PriorRequestUnavailable('old exact request')
                return super().call(stage,req)
        out=self.process(Unavailable(),lambda *args:False)
        self.assertTrue(any(h['reason']=='prior_request_unavailable_no_retry' for h in out['capacity_holds']))
        for o in out['outcomes']:
            if '0' in o['attempted_sources']:self.assertNotIn('0',o['assessed_sources'])


if __name__=='__main__':unittest.main()
