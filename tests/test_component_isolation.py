import unittest
from copy import deepcopy
from experiments import component_isolation_probe as c
from experiments.raw_support_probe import source
from tests.test_positional_support import value
from tests.test_raw_support import score


class ComponentIsolationTests(unittest.TestCase):
    def case(self):
        sources = [source('a','First. Second.'), source('b','First. Third.')]
        spans = c.bind_reference(sources, [[{'first':'S000','last':'S000'}]]*2)
        return {'id':'test','sources':sources,'reference_spans':spans,'model_spans':spans,
                'reference_core':'SECRET ANSWER','reference_rationale':'SECRET LABEL'}

    def test_reference_binding_exact_and_rejects_missing_ids(self):
        case = self.case()
        self.assertEqual(case['reference_spans'][0]['text'],'First. ')
        with self.assertRaises(ValueError):
            c.bind_reference(case['sources'],[[{'first':'S999','last':'S999'}]]*2)
        with self.assertRaises(ValueError):
            c.bind_reference(case['sources'],[[],[]])
        with self.assertRaises(ValueError):
            c.bind_reference(case['sources'],[[{'first':'S000','last':'S000'}]])

    def test_proposal_never_sees_reference_answer_or_label(self):
        case = self.case()
        for arm, texts in c.proposal_inputs(case).items():
            def calls(system,data,schema):
                self.assertEqual(set(data),{'LEFT','RIGHT'})
                self.assertNotIn('SECRET',str(data)+system)
                return {'output':{'core':'Shared.'},'errors':[]}
            self.assertEqual(c.propose(texts,calls)['output']['core'],'Shared.')

    def test_missing_alignment_does_not_fallback_to_full_source(self):
        case = self.case(); case['model_spans'] = [None,None]
        texts = c.proposal_inputs(case)['model_span']
        self.assertIsNone(texts)
        def forbidden(*args): self.fail('No model call allowed')
        self.assertEqual(c.propose(texts,forbidden)['status'],'no_alignment')

    def test_generated_checks_always_use_full_originals(self):
        case = self.case(); before = deepcopy(case); observed = []
        def calls(system,data,schema):
            if system == c.raw_support.PROPOSE:
                return {'output':{'core':'Generated.'},'errors':[]}
            observed.append((data['TARGET'],''.join(s['text'] for s in data['SOURCE'])))
            return {'output':value(),'errors':[]}
        c.evaluate(case,calls,score)
        self.assertEqual(case,before)
        self.assertEqual([s for target,s in observed if target=='Generated.'],
                         [s['text'] for s in case['sources']]*3)
        self.assertEqual([s for target,s in observed if target=='SECRET ANSWER'],
                         [s['text'] for s in case['sources']]+['First. ']*2)

    def test_empty_and_partial_pair_are_not_success(self):
        self.assertFalse(c.pair_pass([]))
        self.assertFalse(c.pair_pass([{'state':'support'}]))
        self.assertFalse(c.pair_pass([{'state':'support'},{'state':'uncertain'}]))
        self.assertTrue(c.pair_pass([{'state':'support'}]*2))

    def test_nli_only_false_accept_is_visible_not_promoted(self):
        rows = [{'id':'negative','expected':False,'split':'test',
                 'decision':{'nli':score('a','b'),'state':'not_supported','reason':'host_projection'}}]
        report = c.stored_ablation(rows)['test']
        self.assertEqual(report['nli_only_counterfactual']['false_accepts'],['negative'])
        self.assertEqual(report['full_pipeline']['false_accepts'],[])

    def test_html_escapes_untrusted_source_and_core(self):
        case = self.case(); case['sources'][0]['text'] = '<script>bad</script>'
        row = {'id':'test','generated':{},'fixed_reference':{}}
        page = c.render({'cases':[case]},{'records':[row],'summary':{}})
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)


if __name__ == '__main__': unittest.main()

