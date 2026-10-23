from copy import deepcopy
import unittest
from commentscope.factory import source_clause_graph as cg


class ClauseGraphTests(unittest.TestCase):
    source={'id':'s','text':'Adopt P. Start now because fairness matters.','parent':None}
    def value(self):
        return {'source_language':'en','status':'complete','nodes':[
            {'local_id':'N1','first_word':'W1','last_word':'W2','role':'position','parent_id':'NONE','authorship':'asserted'},
            {'local_id':'N2','first_word':'W3','last_word':'W4','role':'position','parent_id':'NONE','authorship':'asserted'},
            {'local_id':'N3','first_word':'W5','last_word':'W7','role':'justification','parent_id':'N2','authorship':'asserted'}]}

    def test_model_has_no_free_text_or_quote_field(self):
        props=cg.request(self.source)['schema']['properties']['nodes']['items']['properties']
        self.assertNotIn('text',props);self.assertNotIn('quote',props)
        record=cg.bind(self.source,{'output':self.value()});cg.validate(record)
        self.assertEqual([n['text'] for n in record['nodes']],['Adopt P.','Start now','because fairness matters.'])
        self.assertEqual(record['nodes'][2]['parent_id'],'N2')
        self.assertFalse(record['semantic_approval'])
        for node in record['nodes']:
            self.assertEqual(node['text'],self.source['text'][node['span']['start']:node['span']['end']])

    def test_invalid_ranges_ids_and_ground_links_reject_entire_response(self):
        for changes in ({'last_word':'W999'},{'first_word':'W7','last_word':'W5'},
                        {'local_id':'N1'},{'parent_id':'N3'},{'parent_id':'external'},
                        {'first_word':'W3','last_word':'W4'}):
            value=self.value();value['nodes'][2].update(changes)
            with self.assertRaises(ValueError):cg.bind(self.source,{'output':value})
        value=self.value();value['nodes'][0]['parent_id']='N2'
        with self.assertRaises(ValueError):cg.bind(self.source,{'output':value})

    def test_single_supplement_can_reference_old_parent_but_not_rewrite_it(self):
        value=self.value();value['status']='partial';value['nodes']=value['nodes'][:2]
        prior=cg.bind(self.source,{'output':value})
        extra=self.value();extra['nodes']=extra['nodes'][2:]
        record=cg.bind(self.source,{'output':extra},prior);cg.validate(record)
        self.assertEqual(record['nodes'][:2],prior['nodes'])
        with self.assertRaises(ValueError):cg.request(self.source,record)
        with self.assertRaises(ValueError):cg.bind(self.source,{'output':self.value()},prior)

    def test_raw_text_source_or_parent_mutation_is_not_a_valid_binding(self):
        for change in (lambda r:r['nodes'][2].update(text='Invented motive.'),
                       lambda r:r['nodes'][2].update(parent_id='N1'),
                       lambda r:r['source'].update(parent={'id':'p','text':'New context.'}),
                       lambda r:r['output']['nodes'][2].update(parent_id='N1')):
            record=cg.bind(self.source,{'output':self.value()});change(record)
            with self.assertRaises(ValueError):cg.validate(record)
