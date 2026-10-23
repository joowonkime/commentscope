"""Discovery inventory and own-text grouping invariants, not stance approval."""
from copy import deepcopy
import unittest
from commentscope.factory import lexical_source_groups as lexical
from test_source_closed_policy import SourceClosedPolicyTests

class LexicalGroupTests(unittest.TestCase):
    def sources(self,count):
        fixture=SourceClosedPolicyTests();fixture.setUp();base=fixture.sources[0]
        return [{**deepcopy(base),'id':f'own-{i:03}',
                 'text':f'UBI might change topic {i}. I would retain an amount of {1000+i} dollars.'}
                for i in range(count)]

    def test_complete_unique_inventory_and_no_hidden_singletons(self):
        for count in (2,12,13,25,27):
            with self.subTest(count=count):
                sources=self.sources(count);groups=lexical.groups(sources)
                self.assertEqual(sorted(s['id'] for g in groups for s in g),sorted(s['id'] for s in sources))
                self.assertTrue(all(2<=len(g)<=12 for g in groups))

    def test_grouping_is_stable_without_parent_video_or_input_order(self):
        sources=self.sources(25);expected=[[s['id'] for s in g] for g in lexical.groups(sources)]
        changed=deepcopy(list(reversed(sources)))
        for s in changed:
            s['parent']={'id':'foreign-parent','text':'unrelated entirely different claim'}
            if 'video_context' in s:s['video_context']=deepcopy(sources[0]['video_context'])
        self.assertEqual(expected,[[s['id'] for s in g] for g in lexical.groups(changed)])

    def test_quantities_survive_grouping_features_and_duplicates_are_rejected(self):
        self.assertIn('1000',lexical.features('I would work for 1000 dollars'))
        self.assertIn('12000',lexical.features('I would work for 12000 dollars'))
        sources=self.sources(3)
        with self.assertRaises(ValueError):lexical.groups([*sources,sources[0]])

    def test_one_word_reactions_do_not_outrank_richer_shared_statements(self):
        sources=self.sources(15)
        for i,s in enumerate(sources):
            s['text']='lol' if i<3 else 'I would retain my job if a universal payment covered basic necessities and reduced financial stress.'
        first=lexical.groups(sources)[0]
        self.assertNotEqual(first[0]['text'],'lol')

if __name__=='__main__':unittest.main()
