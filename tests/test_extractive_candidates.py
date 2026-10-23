import unittest
from copy import deepcopy
from commentscope.factory import extractive_candidates as e, positional_support as p
from experiments.extractive_candidates_probe import rank_case
from experiments.raw_support_probe import source
from tests.test_raw_support import score
from tests.test_positional_support import value


class ExtractiveCandidateTests(unittest.TestCase):
    def pair(self):
        return [source('a','First claim. Second claim. Third claim.'),
                source('b','Related claim. Other claim. Final claim.')]

    def rank(self,sources):
        inv=e.inventory(sources)
        vm={c['candidate_id']:[1.,0.] for c in inv if c['eligible']}
        return e.rank(sources,inv,vm)

    def test_unicode_literal_offsets_and_repeated_sentences(self):
        original='조건이 필요하다. 조건이 필요하다.'
        rows=e.inventory([source('a',original)])
        self.assertEqual(len({r['candidate_id'] for r in rows}),2)
        for row in rows:self.assertEqual(row['text'],original[row['start']:row['end']])
        self.assertEqual(''.join(r['text'] for r in rows),original)

    def test_long_sentences_preserved_and_explicitly_deferred(self):
        text='x'*250
        row=e.inventory([source('a',text)])[0]
        self.assertEqual(row['text'],text)
        self.assertEqual(row['deferred_reason'],'core_character_budget')
        self.assertFalse(row['eligible'])

    def test_empty_and_source_budget_are_not_semantic_rejections(self):
        self.assertEqual(e.inventory([source('a','   ')])[0]['deferred_reason'],'empty')
        self.assertTrue(all(r['deferred_reason']=='source_budget' for r in e.inventory([source('a','Hi. '*81)])))

    def test_tampered_source_and_duplicate_ids_rejected(self):
        s=source('a','One.');s['text']='Changed.'
        with self.assertRaises(ValueError):e.inventory([s])
        with self.assertRaises(ValueError):e.inventory([source('a','One.')]*2)

    def test_selection_has_side_quota_and_keeps_unselected(self):
        sources=self.pair();before=deepcopy(sources);r=self.rank(sources)
        self.assertEqual(sources,before)
        self.assertEqual(len(r['selected']),4)
        self.assertEqual(sum(x['status']=='deferred_budget' for x in r['inventory']),2)
        self.assertEqual(r['support_count'],None)
        self.assertEqual(r['agents'],[])
        self.assertFalse(r['quality_gate_passed'])

    def test_identical_targets_merge_origins_not_votes(self):
        r=self.rank([source('a','Same.'),source('b','Same.')])
        self.assertEqual(len(r['selected']),1)
        self.assertEqual(len(r['selected'][0]['origins']),2)
        self.assertIsNone(r['support_count'])

    def test_similarity_does_not_filter_opposite_polarities(self):
        r=self.rank([source('a','I agree.'),source('b','I disagree.')])
        self.assertEqual(len(r['selected']),2)
        self.assertTrue(all('model_pair_passed' not in c for c in r['selected']))

    def test_no_other_candidate_has_explicit_status(self):
        r=self.rank([source('a','Claim.'),source('b','x'*250)])
        self.assertEqual(r['selected'],[])
        self.assertEqual(r['inventory'][0]['status'],'no_other_candidate')

    def test_forged_candidate_or_missing_vector_rejected(self):
        sources=self.pair();inv=e.inventory(sources)
        vm={c['candidate_id']:[1.] for c in inv}
        inv[0]['text']='Invented.'
        with self.assertRaises(ValueError):e.rank(sources,inv,vm)
        with self.assertRaises(ValueError):e.rank(sources,e.inventory(sources),{})

    def test_invalid_vectors_rejected(self):
        sources=self.pair();inv=e.inventory(sources)
        for row in [[float('nan')],[0.]]:
            with self.assertRaises(ValueError):e.rank(sources,inv,{c['candidate_id']:row for c in inv})

    def test_assessment_uses_both_full_sources_without_proposal(self):
        sources=self.pair();r=self.rank(sources);seen=[]
        def calls(system,data,schema):
            self.assertEqual(system,p.AUDIT)
            seen.append(''.join(s['text'] for s in data['SOURCE']))
            return {'errors':[],'output':value()}
        result=e.assess(sources,r['selected'][0],calls,score)
        self.assertEqual(seen,[s['text'] for s in sources])
        self.assertEqual(len(result['checks']),2)
        self.assertFalse(result['quality_gate_passed'])

    def test_origin_is_not_automatically_supported(self):
        sources=self.pair();r=self.rank(sources)
        def calls(*args):return {'errors':[],'output':value(eligibility='non_substantive')}
        result=e.assess(sources,r['selected'][0],calls,score)
        self.assertFalse(result['model_pair_passed'])
        self.assertTrue(all(d['state']=='not_supported' for d in result['checks']))

    def test_target_rewriting_or_single_source_assessment_rejected(self):
        sources=self.pair();r=self.rank(sources);c=deepcopy(r['selected'][0]);c['core']='Changed.'
        with self.assertRaises(ValueError):e.assess(sources,c,None,None)
        with self.assertRaises(ValueError):e.assess(sources[:1],r['selected'][0],None,None)

    def test_rank_is_reproducible_and_has_no_evaluation_argument(self):
        sources=self.pair();inv=e.inventory(sources);vm={c['candidate_id']:[1.] for c in inv}
        self.assertEqual(rank_case(sources,vm),rank_case(sources,vm))


if __name__=='__main__':unittest.main()

