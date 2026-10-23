from copy import deepcopy
import unittest

from commentscope.factory import explicit_discourse as ed, speech_forms as sf, owned_arguments as oa
from commentscope.factory import source_discourse as sd


class SpeechFormTests(unittest.TestCase):
    def consequence(self,body,parent='I hope P is adopted.'):
        graph=self.graph(parent+' '+body);node=graph['nodes'][1]
        record=sd.bind(graph,{'output':{'decisions':[{'pair_id':'L1','relation':'reason',
            'position_node_id':'N1','ground_node_id':'N2'}]}})
        return graph,node,sd.metadata_context(graph,node,record)

    def test_bound_dynamic_modal_is_prediction_without_observed_truth(self):
        for body in ['Would make alot of stressed, unhappy people alot more relaxed.',
                     'Would reduce anxiety.','Would not increase pressure.','Would allow visitors access.']:
            graph,node,context=self.consequence(body)
            self.assertIsNone(sf.interpret(graph,node)['binding'])
            proof=sf.interpret(graph,node,context)
            self.assertEqual(proof['binding']['rule'],'source_bound_dynamic_modal_consequence')
            req=oa.metadata_request(graph,node,context);self.assertNotIn('kind',req['schema']['properties'])
            values={'entity':'people','time_ids':[],'source_language':'en','authorship':'asserted_or_endorsed'}
            values={k:values[k] for k in req['schema']['properties']}
            record=oa.bind_metadata(graph,node,{'output':values},context);oa.validate_metadata(graph,node,record)
            self.assertEqual(record['output']['kind'],'prediction');self.assertNotIn('kind',record['response'])
            self.assertEqual(record['output']['authorship'],'linked_to_parent')
            self.assertNotIn('authorship',record['response'])
            self.assertEqual(node['span']['text'],body);self.assertFalse(proof['semantic_truth_verified'])
            with self.assertRaises(ValueError):oa.bind_metadata(graph,node,{'output':{**values,'kind':'value'}},context)
            with self.assertRaises(ValueError):oa.bind_metadata(graph,node,{'output':{**values,'authorship':'not_asserted'}},context)

    def test_evaluative_observed_compound_numeric_effects_are_not_forced(self):
        for body in ['Made people more relaxed.','This reduces anxiety.','Would like P.',
                     'Would make a great policy.','Would make no sense.',
                     'Would increase anxiety and costs.','Would reduce costs by $500.',
                     'Would reduce anxiety, we paid the fees.']:
            graph,node,context=self.consequence(body)
            self.assertIsNone(sf.interpret(graph,node,context)['binding'],body)
            self.assertIn('kind',oa.metadata_request(graph,node,context)['schema']['properties'])

    def test_reported_consequence_does_not_get_source_form_typing(self):
        graph,node,context=self.consequence('Would reduce anxiety.',parent='They say P should be adopted.')
        self.assertIsNone(sf.interpret(graph,node,context)['binding'])

    def graph(self,text):return ed.parse({'id':'source','text':text,'parent':None})
    def bindings(self,text):
        g=self.graph(text);return [(n,sf.interpret(g,n)['binding']) for n in g['nodes']]
    def meta(self,g,n,**changes):
        values={'kind':'value','authorship':'asserted_or_endorsed','entity':'topic','time_ids':[],'source_language':'en',**changes}
        req=oa.metadata_request(g,n)
        return oa.bind_metadata(g,n,{'output':{k:values[k] for k in req['schema']['properties']}})

    def test_modal_topics_and_negation_retain_prediction_without_factual_approval(self):
        for topic in ('Park entry','School meals','The process','Transit service','The proposal','Film ratings'):
            for modal in ('may','might','could','would'):
                for neg in ('','not '):
                    text=f'{topic} {modal} {neg}be expensive.';g=self.graph(text);n=g['nodes'][0]
                    binding=sf.interpret(g,n)['binding']
                    self.assertEqual(binding['kind'],'prediction')
                    self.assertEqual(binding['authorship'],'asserted_or_endorsed')
                    self.assertEqual(n['span']['text'],text)
                    record=self.meta(g,n,kind='fact')
                    self.assertEqual(record['output']['kind'],'prediction')
                    self.assertNotIn('kind',record['response'])
                    self.assertFalse(record['semantic_approval'])

    def test_modal_concession_inherits_only_its_fixed_parent(self):
        g=self.graph('I support P even though it may be expensive.')
        child=next(n for n in g['nodes'] if n['kind']=='ground')
        binding=sf.interpret(g,child)['binding']
        self.assertEqual(binding['authorship'],'linked_to_parent')
        self.assertEqual(binding['parent_id'],g['edges'][0]['parent_id'])
        self.assertEqual(self.meta(g,child)['output']['kind'],'prediction')

    def test_past_or_present_facts_never_reclassified_as_modal_predictions(self):
        for text in ('School meals were expensive.','The trial is expensive.','The estimate was wrong.','Safety checks cost 1000 dollars.'):
            g=self.graph(text);n=g['nodes'][0]
            self.assertIsNone(sf.interpret(g,n)['binding'])
            self.assertEqual(self.meta(g,n,kind='fact')['output']['kind'],'fact')

    def test_report_question_quote_and_compound_never_get_direct_approval(self):
        for text in ('They say meals may be expensive.','Meals may be expensive?','"Meals may be expensive."',
                     'Meals may be expensive and schools might close.',
                     '그는 공원을 개방해야 한다고 말합니다.','공원을 개방해야 합니다?',
                     '"공원을 개방해야 합니다."'):
            self.assertTrue(all(b is None for _,b in self.bindings(text)),text)

    def test_direct_korean_form_attribution_does_not_assign_content_type(self):
        for topic in ('공원','학교 급식','대중교통','영화 등급','세금','안전성 검토'):
            for text in (f'{topic}은 자율에 맡겨야 합니다.',f'{topic}에 찬성합니다.',f'{topic}에 반대합니다.'):
                g=self.graph(text);n=g['nodes'][0];binding=sf.interpret(g,n)['binding']
                self.assertEqual(binding['authorship'],'asserted_or_endorsed')
                self.assertIsNone(binding['kind'])
                meta=self.meta(g,n,kind='uncertain',authorship='unclear',source_language='other')
                self.assertEqual(meta['output']['kind'],'uncertain')
                self.assertEqual(meta['output']['authorship'],'asserted_or_endorsed')

    def test_antecedent_is_not_assertion_that_condition_holds(self):
        for text in ('Adopt P only if funding is available.','재원이 있을 때만 제안에 찬성합니다.'):
            g=self.graph(text);n=next(n for n in g['nodes'] if n['kind']=='ground')
            meta=self.meta(g,n)
            self.assertEqual(meta['assertion_mode'],'conditional_antecedent')
            self.assertEqual(meta['output']['kind'],'uncertain')
            self.assertEqual(meta['output']['authorship'],'not_asserted')
            self.assertNotIn('kind',meta['response'])
            self.assertNotIn('authorship',meta['response'])
            changed=deepcopy(meta);changed['output']['kind']='fact'
            with self.assertRaises(ValueError):oa.validate_metadata(g,n,changed)
