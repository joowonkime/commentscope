"""Literal target/provenance mechanics, not classifier quality evidence."""
from copy import deepcopy
import unittest
from commentscope.factory import policy_target as target,policy_stance_hypotheses as stance
from commentscope.factory import explicit_discourse as ed,owned_arguments as oa,owned_node_entailment as own
from commentscope.factory.automatic_contract import digest
from test_source_entailment import nli_response


class PolicyTargetTests(unittest.TestCase):
    def source(self,text,parent=None):
        return {'id':'a','text':text,'parent':parent,'video_context':{
            'artifact_kind':'snapshot-video-context-20261017-v1','video_id':'v',
            'title':'Universal Basic Income Explained UBI','primary_language':'en'}}
    def job(self,text,index=0,parent=None):
        source=self.source(text,parent);graph=ed.parse(source);node=graph['nodes'][index]
        request=stance.invocation([source],'Universal Basic Income','UBI')
        record=stance.bind([source],'Universal Basic Income','UBI',nli_response(request))
        candidate=next(c for c in stance.candidates(record) if 'a desirable' in c['text'])
        metadata=oa.bind_metadata(graph,node,{'output':{'authorship':'asserted_or_endorsed','kind':'value',
            'entity':'UBI','time_ids':[],'source_language':'en'}})
        return {'graph':graph,'node':node,'candidate':candidate,'metadata':metadata,
            'named_target':target.bind(graph,node,candidate,'Universal Basic Income','UBI')}

    def test_literal_name_or_acronym_is_necessary_but_not_semantic_approval(self):
        for text in ['UBI sounds good.','ubi sounds good.','Universal Basic Income seems good.']:
            job=self.job(text);self.assertTrue(job['named_target']['passed'])
            request=own.invocation([job]);proof=own.records([job],nli_response(request))[0]
            own.validate(job['graph'],job['node'],job['candidate'],proof)
            self.assertEqual(proof['relation'],'supports_core');self.assertFalse(proof['semantic_approval'])
    def test_generic_variant_parent_or_video_cannot_supply_missing_own_target(self):
        for text in ['Basic income for self-declared need seems good.','PUBI sounds good.','UBIs sound good.']:
            job=self.job(text,parent={'id':'p','text':'Universal Basic Income is the topic.'})
            self.assertFalse(job['named_target']['passed']);self.assertFalse(own.invocation([job])['data']['cases'])
            proof=own.records([job],None)[0]
            self.assertEqual(proof['relation'],'not_proved')
            self.assertIn('own_named_policy_reference_unbound',proof['guards'])
    def test_another_sentence_cannot_supply_own_node_missing_reference(self):
        job=self.job('UBI is the topic. A voluntary local donation scheme is good.',1)
        self.assertTrue(target.anchors(job['graph']['source'],'Universal Basic Income','UBI'))
        self.assertFalse(job['named_target']['passed']);self.assertFalse(own.invocation([job])['data']['cases'])
    def test_target_offsets_metadata_and_candidate_are_bound(self):
        job=self.job('UBI sounds good.');changed=deepcopy(job['named_target']);changed['anchors'][0]['text']='basic income'
        with self.assertRaises(ValueError):target.validate(job['graph'],job['node'],job['candidate'],changed)
        changed=deepcopy(job['named_target']);changed['topic']='Another Policy'
        with self.assertRaises(ValueError):target.validate(job['graph'],job['node'],job['candidate'],changed)
        candidate={**job['candidate'],'text':'A different proposal sounds good.'}
        with self.assertRaises(ValueError):target.bind(job['graph'],job['node'],candidate,'Universal Basic Income','UBI')
