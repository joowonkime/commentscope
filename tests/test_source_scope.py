from copy import deepcopy
import unittest

from commentscope.factory import source_scope as ss, explicit_discourse as ed, literal_discovery as ld


def graph(text,parent=None):
    return ed.parse({'id':'s','text':text,'parent':parent})


def witness(g,phrase,origin='source',occurrence=0):
    return next(c['id'] for c in ss.witness_choices(g,ld.roots(g)[0]) if c['origin']==origin and c['text']==phrase)


class SourceScopeTests(unittest.TestCase):
    def test_generic_topics_bind_references_without_importing_prior_assertions(self):
        for topic in ('School meals','Park access','Road pricing','Film ratings','Lab reviews'):
            g=graph(f'{topic} should be optional. It should also be transparent.')
            node=ld.roots(g)[1];value={'R1':witness(g,topic)}
            cert=ss.bind(g,node,{'output':value});p=ss.projection(g,node,cert)
            self.assertFalse(p['holds']);self.assertEqual(p['text'],f'{topic} should also be transparent.')
            self.assertNotIn('optional',p['text']);self.assertFalse(p['semantic_approval'])
            self.assertFalse(ss.projection(g,node)['substitutions'])
            self.assertTrue(ss.projection(g,node)['holds'])

    def test_missing_or_unresolved_each_reference_is_held(self):
        g=graph('Workers are tired. They choose their shifts.');node=ld.roots(g)[1]
        self.assertEqual(len(ss.inventory(g,node)['references']),2)
        with self.assertRaises(ValueError):ss.bind(g,node,{'output':{'R1':witness(g,'Workers')}})
        cert=ss.bind(g,node,{'output':{'R1':witness(g,'Workers'),'R2':'unresolved'}})
        self.assertEqual(ss.projection(g,node,cert)['holds'],['unresolved_reference:R2'])
        cert=ss.bind(g,node,{'output':{k:witness(g,'Workers') for k in ('R1','R2')}})
        self.assertEqual(ss.projection(g,node,cert)['text'],"Workers choose Workers' shifts.")

    def test_parent_can_name_reply_target_but_never_replace_reply_with_assertion(self):
        g=graph('This is too expensive.',{'id':'p','text':'Rail pricing will raise 42 million dollars.'})
        node=ld.roots(g)[0]
        cert=ss.bind(g,node,{'output':{'R1':witness(g,'Rail pricing','parent')}})
        p=ss.projection(g,node,cert)
        self.assertEqual(p['text'],'Rail pricing is too expensive.')
        self.assertTrue(p['substitutions'][0]['resolution']['context_only'])
        for phrase in ('Rail pricing will raise','42 million dollars'):
            self.assertFalse(any(c['text']==phrase for c in ss.witness_choices(g,node)))
            with self.assertRaises(ValueError):ss.bind(g,node,{'output':{'R1':phrase}})

    def test_reference_cannot_resolve_to_itself_or_cross_origins(self):
        g=graph('This fails.',{'id':'p','text':'Rail pricing.'});node=ld.roots(g)[0]
        self.assertFalse(any(c['text']=='This' for c in ss.witness_choices(g,node)))
        with self.assertRaises(ValueError):ss.bind(g,node,{'output':{'R1':'This'}})
        with self.assertRaises(ValueError):ss.bind(g,node,{'output':{'R1':{'first_token':2,'last_token':4}}})

    def test_schema_contains_only_bound_choices_and_unresolved(self):
        g=graph('They failed.');node=ld.roots(g)[0];req=ss.request(g,node)
        choices=ss.witness_choices(g,node)
        self.assertEqual(req['schema']['properties']['R1']['enum'],['unresolved']+[c['id'] for c in choices])
        self.assertFalse(any('They' in c['text'] for c in choices))
        cert=ss.bind(g,node,{'output':{'R1':'unresolved'}})
        self.assertTrue(ss.projection(g,node,cert)['holds'])

    def test_bounded_grammar_does_not_remove_demonstrative_in_same_position(self):
        cases=[('I think that we should wait.',[]),('I think that is wrong.',['that']),
               ('It is important to wait.',[]),('It is broken.',['It']),
               ('People that hate queues complain.',[]),('All of that is broken.',['that']),
               ('Those who need help should apply.',[]),('Those failed.',['Those']),
               ('This Rail Plan failed.',[]),('This failed.',['This'])]
        for text,expected in cases:
            with self.subTest(text=text):
                g=graph(text);self.assertEqual([r['span']['text'] for r in ss.inventory(g,ld.roots(g)[0])['references']],expected)

    def test_quoted_reference_never_rewritten_as_authors_statement(self):
        g=graph('Some people say "They should resign."');node=ld.roots(g)[0]
        inv=ss.inventory(g,node);self.assertFalse(inv['references'])
        self.assertEqual(inv['syntax'][0]['kind'],'quoted_reference_not_rewritten')

    def test_if_answer_remains_condition_and_no_intervening_claim_becomes_core(self):
        g=graph('Do you want clean air? Fees should fall. If yes, adopt road pricing.')
        node=ld.roots(g)[2];p=ss.projection(g,node)
        self.assertEqual(p['inventory']['answer_condition']['question']['text'],'Do you want clean air?')
        self.assertIn('answer_condition_requires_structured_scope',p['holds'])
        self.assertEqual(p['text'],'If yes, adopt road pricing.');self.assertNotIn('Fees',p['text'])

    def test_possible_heading_requires_bound_role_and_no_intervening_assertion(self):
        for title in ('Moon Colony!','In an imaginary valley.'):
            g=graph(title+' Everyone has food. Taxes are low.');node=ld.roots(g)[2]
            self.assertEqual(ss.projection(g,node)['text'],'Taxes are low.')
            self.assertEqual(ss.projection(g,node,framing=True)['text'],title+' Taxes are low.')
        g=graph('Taxes are low. Everyone has food.')
        with self.assertRaises(ValueError):ss.projection(g,ld.roots(g)[1],framing=True)

    def test_certificate_and_selected_source_mutation_rejected(self):
        g=graph('Reviews are optional. They cost money.');node=ld.roots(g)[1]
        cert=ss.bind(g,node,{'output':{'R1':witness(g,'Reviews')}})
        changed=deepcopy(cert);changed['bindings'][0]['resolution']['span']['text']='Laws'
        with self.assertRaises(ValueError):ss.projection(g,node,changed)
        h=graph('Reviews are required. They cost money.')
        with self.assertRaises(ValueError):ss.projection(h,ld.roots(h)[1],cert)


if __name__=='__main__':unittest.main()
