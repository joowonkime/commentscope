from copy import deepcopy
from dataclasses import replace
import math
import unittest

from commentscope.ingestion import load_snapshot
from commentscope.factory import raw_candidates as r


class RawCandidatesTests(unittest.TestCase):
    def snapshot(self,texts):
        snapshot=load_snapshot('tests/fixtures/synthetic-snapshot.json').snapshot
        return replace(snapshot,comments=tuple(replace(snapshot.comments[0],comment_id=str(i),text_original=t,parent_id=None)
                                               for i,t in enumerate(texts)))

    def test_no_semantic_filter_or_length_topic_gate(self):
        texts=['I agree. I would still work with UBI.','It is proven otherwise.','긴 댓글 '*1000,'!!!','']
        s=self.snapshot(texts); index=r.registry(s)
        self.assertEqual([v['text'] for v in index['sources']],texts)
        self.assertEqual(len(index['sources']),5)
        self.assertEqual(sum(v['indexable'] for v in index['sources']),4)
        self.assertFalse(index['semantic_filter_applied'])

    def test_duplicate_alias_is_retained_but_not_a_second_source(self):
        index=r.registry(self.snapshot(['same text','same text','different']))
        self.assertEqual(index['aliases'],{'1':'0'})
        self.assertEqual(len(index['sources']),2)
        selected=r.registry(self.snapshot(['same text','same text']),['1'])
        self.assertEqual(selected['sources'][0]['source_id'],'0')

    def test_no_parent_text_is_appended_to_reply(self):
        snapshot=self.snapshot(['parent assertion','reply assertion'])
        snapshot=replace(snapshot,comments=(snapshot.comments[0],replace(snapshot.comments[1],parent_id='0')))
        index=r.registry(snapshot)
        bundle=r.build(index,[[1,0],[1,0]])
        packet=r.source_packet(index,bundle['queue']['pairs'][0])
        self.assertEqual([s['text'] for s in packet['sources']],['parent assertion','reply assertion'])
        self.assertNotIn('parent_id',packet['sources'][1])
        self.assertEqual(packet['sources'][1]['text'],'reply assertion')

    def test_unknown_duplicate_selection_and_changed_registry_rejected(self):
        snapshot=self.snapshot(['a','b'])
        for ids in [['missing'],['0','0']]:
            with self.assertRaises(ValueError):r.registry(snapshot,ids)
        index=r.registry(snapshot); index['sources'][0]['text']='changed'
        with self.assertRaises(ValueError):r.validate_registry(index,snapshot)
        with self.assertRaises(ValueError):r.build(index,[[1],[1]])

    def test_bad_vectors_fail_instead_of_dropping_sources(self):
        index=r.registry(self.snapshot(['a','b']))
        for rows in [[],[[1]],[[0],[1]],[[math.nan],[1]],[[True],[1]],[[1,0],[1]],[[math.inf],[1]]]:
            with self.assertRaises(ValueError):r.build(index,rows)

    def test_symmetric_pairs_are_once_and_budget_is_separate_from_preservation(self):
        index=r.registry(self.snapshot(['a','b','c','d']))
        b=r.build(index,[[1,0]]*4,budget=2)
        self.assertEqual(len(b['candidates']),4)
        self.assertEqual(b['queue']['available_unique_pairs'],6)
        self.assertEqual(len(b['queue']['pairs']),2)
        self.assertEqual(b['queue']['deferred_pairs'],4)
        self.assertIsNone(b['summary']['support_count'])
        self.assertEqual(b['queue']['agents'],[])

    def test_zero_budget_keeps_candidates_and_no_edges_are_support_votes(self):
        index=r.registry(self.snapshot(['a','b']))
        result=r.build(index,[[1,0],[0,1]],budget=0)
        self.assertEqual(len(result['candidates']['0']),1)
        self.assertEqual(result['queue']['pairs'],[])
        self.assertFalse(result['queue']['quality_gate_passed'])

    def test_queue_is_deterministic_without_reference_labels(self):
        index=r.registry(self.snapshot(['a','b','c']))
        links=r.search(index,[[1,0]]*3)
        self.assertEqual(r.queue(index,links),r.queue(index,dict(reversed(list(links.items())))))
        self.assertEqual(r.build(index,[[1,0]]*3),r.build(index,[[1,0]]*3))

    def test_pair_binding_rejects_source_or_pair_mutation(self):
        index=r.registry(self.snapshot(['a','b'])); b=r.build(index,[[1],[1]])
        pair=deepcopy(b['queue']['pairs'][0]);pair['pair_id']='fake'
        with self.assertRaises(ValueError):r.source_packet(index,pair)
        index['sources'][0]['text']='invented'
        with self.assertRaises(ValueError):r.source_packet(index,b['queue']['pairs'][0])

    def test_bad_queue_references_and_budget_rejected(self):
        index=r.registry(self.snapshot(['a','b']))
        for links in [{'0':[]},{'0':[{'source_id':'0'}],'1':[]},{'0':[{'source_id':'foreign'}],'1':[]}]:
            with self.assertRaises(ValueError):r.queue(index,links)
        for budget in [-1,True,1.5,10001]:
            with self.assertRaises(ValueError):r.queue(index,{'0':[],'1':[]},budget)

    def test_empty_and_single_source_are_preserved(self):
        for texts in [[],[''],['only source']]:
            index=r.registry(self.snapshot(texts))
            vectors=[[1] for s in index['sources'] if s['indexable']]
            result=r.build(index,vectors)
            self.assertEqual(len(result['candidates']),len(texts))
            self.assertEqual(result['queue']['pairs'],[])

    def test_1000_sources_supported_with_bounded_edges_not_llm_pairs(self):
        index=r.registry(self.snapshot([str(i) for i in range(1000)]))
        result=r.build(index,[[1] for _ in range(1000)])
        self.assertEqual(result['summary']['canonical_sources'],1000)
        self.assertLessEqual(result['summary']['directed_candidates'],12000)
        self.assertEqual(result['summary']['queued_pairs'],64)
        self.assertEqual(result['summary']['generative_calls'],0)


if __name__=='__main__':unittest.main()
