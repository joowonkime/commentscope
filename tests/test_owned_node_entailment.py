from copy import deepcopy
import unittest
from commentscope.factory import owned_node_entailment as node_nli,owned_arguments as oa,explicit_discourse as ed
from commentscope.factory import minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from test_source_entailment import nli_response
from test_minimal_factory import membership


class OwnedNodeEntailmentTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'a','text':'Policy P is always a bad idea because unfairness is wrong.',
            'parent':{'id':'parent','text':'Parent text must not become this author\'s reason.'}}
        self.graph=ed.parse(self.source);self.root=next(n for n in self.graph['nodes'] if n['kind']=='statement')
        text='Policy P can be undesirable.';cid=mc.claim_id(text)
        self.candidate={'id':cid,'text':text,'aliases':[cid],'nominees':{'a':self.graph['source_sha256']},
            'extraction_refs':[digest(['authored test fixture',self.source])],'equivalence_refs':[]}
        self.metadata=[self.meta(self.graph,n) for n in self.graph['nodes']]
        self.job={'graph':self.graph,'node':self.root,'candidate':self.candidate,'metadata':self.metadata[0]}
    def meta(self,graph,node,**changes):
        return oa.bind_metadata(graph,node,{'output':{'authorship':'asserted_or_endorsed','kind':'value',
            'entity':'Policy P','time_ids':[],'source_language':'en',**changes}})
    def proof(self):
        request=node_nli.invocation([self.job]);return node_nli.records([self.job],nli_response(request))[0]

    def test_directional_entailment_closes_owned_root_and_preserves_exact_own_reason(self):
        proof=self.proof();self.assertEqual(proof['relation'],'supports_core')
        members=[membership([self.source],[self.candidate],[{'source_id':'a','candidate_id':self.candidate['id']}])]
        declared=oa.declare(self.graph,[self.candidate],members,self.metadata,[proof])
        oa.validate(declared);self.assertEqual(declared['status'],'complete')
        reason=next(u for u in declared['units'] if u['role']=='reason')
        self.assertEqual(reason['text'],'because unfairness is wrong.')
        self.assertEqual(reason['candidate_ids'],[self.candidate['id']])
        self.assertNotIn('Parent text',str(node_nli.invocation([self.job])))
        self.assertFalse(proof['factual_verification'])

    def test_nonneutral_result_is_not_required_for_unrelated_nodes_to_count_as_nonproof(self):
        request=node_nli.invocation([self.job]);response=nli_response(request,{request['data']['cases'][0]['id']})
        proof=node_nli.records([self.job],response)[0]
        self.assertEqual(proof['relation'],'not_proved');self.assertIn('own_node_entailment_unproved',proof['guards'])

    def test_essential_condition_cannot_be_erased_into_unqualified_core(self):
        graph=ed.parse({'id':'c','text':'Adopt P only if the rate is low.','parent':None})
        root=next(n for n in graph['nodes'] if n['kind']=='statement')
        job={'graph':graph,'node':root,'candidate':self.candidate,'metadata':self.meta(graph,root)}
        self.assertFalse(node_nli.invocation([job])['data']['cases'])
        proof=node_nli.records([job],None)[0]
        self.assertEqual(proof['relation'],'not_proved')
        self.assertIn('essential_condition_needs_separate_scope_proof',proof['guards'])

    def test_other_voice_unresolved_type_and_tampered_selected_text_are_rejected(self):
        for changes in [{'authorship':'not_asserted'},{'kind':'uncertain'}]:
            job={**self.job,'metadata':self.meta(self.graph,self.root,**changes)}
            self.assertFalse(node_nli.invocation([job])['data']['cases'])
            self.assertEqual(node_nli.records([job],None)[0]['relation'],'not_proved')
        proof=deepcopy(self.proof());proof['comparison']['case']['evidence'][0]['text']='Parent text.'
        with self.assertRaises(ValueError):node_nli.validate(self.graph,self.root,self.candidate,proof)
