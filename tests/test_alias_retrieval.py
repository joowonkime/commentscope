"""Retrieval must retain certified equivalent wording; similarity is not a vote."""
from copy import deepcopy
import unittest
from commentscope.factory import candidate_consolidation as cc,minimal_claims as mc
from test_minimal_factory import extraction


class AliasRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':'author','text':'Authored toy proposals.','parent':None},
                      {'id':'query','text':'Independent toy original.','parent':None}]
        raw=mc.candidates(extraction(self.sources[:1],{'author':['Policy '+str(i)+'.' for i in range(9)]}))
        self.rep=deepcopy(raw[0]);alias=raw[-1];self.rep['aliases']=sorted(self.rep['aliases']+alias['aliases'])
        self.candidates=[self.rep,*raw[1:-1]]
        self.alias_vectors={c['id']:[1.,.1] for c in raw}
        self.alias_vectors[self.rep['id']]=[0.,1.];self.alias_vectors[alias['id']]=[1.,0.]
        self.final_vectors={c['id']:self.alias_vectors[c['id']] for c in self.candidates}
        self.source_vectors={s['id']:[1.,0.] for s in self.sources}
        mapping={c['id']:c['id'] for c in raw};mapping[alias['id']]=self.rep['id']
        self.index={'vectors':self.alias_vectors,'alias_to_final':mapping}

    def pairs(self,index=None):
        return cc.membership_pairs(self.sources,self.candidates,self.source_vectors,self.final_vectors,retrieval_index=index)

    def test_equivalent_alias_prevents_representative_language_from_hiding_target(self):
        before=[r for r in self.pairs() if r['source_id']=='query']
        self.assertNotIn(self.rep['id'],[r['candidate_id'] for r in before])
        after=[r for r in self.pairs(self.index) if r['source_id']=='query']
        self.assertEqual(len(after),3)
        self.assertIn(self.rep['id'],[r['candidate_id'] for r in after])
        self.assertTrue(all(set(r)=={'source_id','candidate_id'} for r in after))

    def test_alias_order_cannot_change_ranking_or_duplicate_canonical_pairs(self):
        changed={k:dict(reversed(list(v.items()))) for k,v in self.index.items()}
        a=self.pairs(self.index);b=self.pairs(changed)
        self.assertEqual(a,b);self.assertEqual(len(a),len({(r['source_id'],r['candidate_id']) for r in a}))

    def test_foreign_mapping_or_incomplete_vector_inventory_is_rejected(self):
        for change in ('mapping','missing','representative','dimension','nan'):
            value=deepcopy(self.index);alias=next(k for k,v in value['alias_to_final'].items() if k!=v)
            if change=='mapping':value['alias_to_final'][alias]=self.candidates[1]['id']
            elif change=='missing':value['vectors'].pop(alias)
            elif change=='representative':value['vectors'][self.rep['id']]=[1.,0.]
            elif change=='dimension':value['vectors'][alias]=[1.]
            else:value['vectors'][alias]=[float('nan'),0.]
            with self.subTest(change=change),self.assertRaises(ValueError):self.pairs(value)


if __name__=='__main__':unittest.main()
