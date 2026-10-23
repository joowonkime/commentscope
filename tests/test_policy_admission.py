import unittest
from commentscope.factory import policy_stance_hypotheses as stance,policy_attitude as attitude,policy_admission
from commentscope.factory import minimal_membership as mm
from commentscope.factory.automatic_contract import digest
from test_source_entailment import nli_response
from test_shared_admission import ScriptedAdmission


class PolicyRunner(ScriptedAdmission):
    def __init__(self,empty=False):super().__init__();self.empty=empty
    def call(self,stage,request):
        if request['system'].startswith(attitude.SYSTEM):
            self.calls.append((stage,request));text=request['data']['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text']
            polarity='unfavorable' if 'an undesirable' in text else 'favorable'
            value={'evaluation':'not_stated' if self.empty else polarity,'target':'topic_policy','authorship':'own_evaluation'}
            for direction in ['favorable','unfavorable']:
                active=not self.empty and direction==polarity
                value[direction+'_segment_ids']=['S000'] if active else []
                value[direction+'_force']='possible_or_conditional' if active else 'not_stated'
            return {'raw':'authored controller fixture only','output':value,'errors':[]}
        return super().call(stage,request)


class PolicyAdmissionTests(unittest.TestCase):
    def setUp(self):
        video={'artifact_kind':'snapshot-video-context-20261017-v1','video_id':'v','title':'Policy P Explained PP','primary_language':'en'}
        self.sources=[{'id':str(i),'text':'Policy P (PP) '+list(stance.POLARITIES.values())[i//3],
            'parent':None,'video_context':video} for i in range(6)]
        self.request=stance.invocation(self.sources,'Policy P','PP');self.response=nli_response(self.request)
        self.record=stance.bind(self.sources,'Policy P','PP',self.response)
    def process(self,runner):
        return policy_admission.process(self.sources,self.record,self.request,self.response,runner,
            lambda request:{'request_sha256':digest(request),'fits':True})

    def test_only_qualified_originals_form_two_three_source_cores(self):
        runner=PolicyRunner();out=self.process(runner)
        self.assertEqual(len(out['ready_candidate_ids']),2)
        self.assertEqual([len(o['qualified_sources']) for o in out['outcomes']],[3,3])
        self.assertFalse(out['errors']);self.assertFalse(out['holds']);self.assertFalse(out['semantic_approval'])
        rows=mm.collect(self.sources,out['candidates'],out['qualified_memberships'])
        self.assertEqual(len(rows),6);self.assertTrue(all(r['relation']=='supported' for r in rows))
        self.assertEqual(sum(r['system'].startswith(attitude.SYSTEM) for _,r in runner.calls),6)

    def test_classifier_nominations_alone_never_count_and_no_policy_evaluation_means_no_raw_calls(self):
        runner=PolicyRunner(empty=True);out=self.process(runner)
        self.assertFalse(out['ready_candidate_ids']);self.assertFalse(out['raw_memberships'])
        self.assertTrue(all(not o['qualified_sources'] for o in out['outcomes']))
        self.assertEqual(len(runner.calls),6)

    def test_prior_unavailable_requests_are_explicit_holds_without_fabricated_output(self):
        from commentscope.factory.shared_admission import PriorRequestUnavailable
        class Unavailable(PolicyRunner):
            def call(self,*args):raise PriorRequestUnavailable('prior interrupted request')
        out=self.process(Unavailable());self.assertFalse(out['ready_candidate_ids'])
        self.assertEqual(len(out['holds']),6);self.assertFalse(out['errors'])
