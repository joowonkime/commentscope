"""Broader searches must never become inferred votes or paid retry loops."""
from copy import deepcopy
import inspect
import unittest

from commentscope.factory import candidate_consolidation as cc, candidate_hierarchy as ch
from commentscope.factory import minimal_claims as mc, minimal_membership as mm, minimal_pipeline
from test_minimal_factory import extraction, membership


class CandidateHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':sid,'text':text,'parent':None} for sid,text in (
            ('parent_author','Broad proposal.'),('author','Narrow proposal.'),
            ('condition_author','Contingent proposal.'),('extra1','Parent one.'),('extra2','Parent two.'),('peer','Narrow proposal.'),
            ('conditional','Consider the contingent proposal only if funded.'))]
        self.initial=mc.candidates(extraction(self.sources[:5],{s['id']:[s['text']] for s in self.sources[:5]}))
        self.bytext={c['text']:c['id'] for c in self.initial}
        self.parent=self.bytext['Broad proposal.'];self.child=self.bytext['Narrow proposal.']
        self.condition=self.bytext['Contingent proposal.']
        self.nominations=[membership(self.sources,self.initial,[{'source_id':next(iter(c['nominees'])),'candidate_id':c['id']} for c in self.initial])]
        self.equivalences=self.relations([(self.child,self.parent),(self.condition,self.parent)])
        self.consolidation=cc.consolidate(self.sources,self.initial,self.nominations,self.equivalences)
        self.candidates=self.consolidation['candidates']
        self.current=[membership(self.sources,self.candidates,[
            {'source_id':'author','candidate_id':self.child},{'source_id':'peer','candidate_id':self.child},
            {'source_id':'conditional','candidate_id':self.condition}])]

    def relations(self,edges):
        pairs=[];decisions=[]
        for i,(child,parent) in enumerate(edges):
            a,b=sorted((child,parent));pairs.append({'a':a,'b':b});decisions.append({
                'pair_id':'P'+str(i+1),'relation':'a_narrower' if a==child else 'b_narrower'})
        return [cc.bind(self.sources,self.initial,self.nominations,pairs,{'output':{'decisions':decisions}})]

    def plan(self,**changes):
        args={'sources':self.sources,'initial_candidates':self.initial,'nominations':self.nominations,
              'consolidation':self.consolidation,'equivalences':self.equivalences,'memberships':self.current}
        args.update(changes);return ch.expansion(**args)

    def test_shared_subgroup_still_searches_parent_without_transferring_votes(self):
        result=self.plan()
        self.assertIn({'source_id':'peer','candidate_id':self.parent},result['pairs'])
        self.assertEqual(result['memberships'],[]);self.assertFalse(result['semantic_approval'])
        collected=mm.collect(self.sources,self.candidates,self.current)
        self.assertFalse(any(r['candidate_id']==self.parent and r['relation']=='supported' for r in collected))

    def test_conditionally_worded_child_does_not_make_parent_unconditional(self):
        pair={'source_id':'conditional','candidate_id':self.parent}
        self.assertIn(pair,self.plan()['pairs'])
        judged=membership(self.sources,self.candidates,[pair],{'conditional':{'relation':'conditional'}})
        rows=mm.collect(self.sources,self.candidates,[*self.current,judged])
        row=next(r for r in rows if r['source_id']=='conditional' and r['candidate_id']==self.parent)
        self.assertEqual(row['relation'],'conditional')

    def test_non_support_and_unobserved_relations_do_not_expand(self):
        for relation in ('conditional','opposed','uncertain','unrelated'):
            current=[membership(self.sources,self.candidates,[{'source_id':'peer','candidate_id':self.child}],
                                {'peer':{'relation':relation}})]
            with self.subTest(relation=relation):self.assertEqual(self.plan(memberships=current)['pairs'],[])
        empty=cc.consolidate(self.sources,self.initial,self.nominations,[])
        self.assertEqual(self.plan(equivalences=[],consolidation=empty)['pairs'],[])

    def test_already_attempted_failed_or_assessed_pair_is_not_retried(self):
        pair={'source_id':'peer','candidate_id':self.parent}
        self.assertNotIn(pair,self.plan(attempted=[pair])['pairs'])
        rejected=membership(self.sources,self.candidates,[pair],{'peer':{'relation':'unrelated'}})
        self.assertNotIn(pair,self.plan(memberships=[*self.current,rejected])['pairs'])

    def test_graph_or_alias_tampering_is_rejected_before_search(self):
        for field in ('equivalences_sha256','alias_to_final'):
            value=deepcopy(self.consolidation)
            if field=='equivalences_sha256':value[field]='0'*64
            else:value[field][self.child]=self.parent
            with self.subTest(field=field),self.assertRaises(ValueError):self.plan(consolidation=value)
        with self.assertRaises(ValueError):self.plan(attempted=[{'source_id':'foreign','candidate_id':self.parent}])

    def test_only_one_hop_is_followed(self):
        relations=self.relations([(self.child,self.condition),(self.condition,self.parent)])
        merged=cc.consolidate(self.sources,self.initial,self.nominations,relations)
        current=[membership(self.sources,self.candidates,[{'source_id':'peer','candidate_id':self.child}])]
        pairs=self.plan(equivalences=relations,consolidation=merged,memberships=current)['pairs']
        self.assertEqual(pairs,[{'source_id':'peer','candidate_id':self.condition}])

    def test_new_policy_is_explicit_and_legacy_remains_the_default(self):
        parameter=inspect.signature(minimal_pipeline.process).parameters['membership_retrieval_policy']
        self.assertEqual(parameter.default,cc.ALIAS_RETRIEVAL)

    def test_extra_parent_searches_are_bounded_and_overflow_is_visible(self):
        parents=[self.parent,self.condition,self.bytext['Parent one.'],self.bytext['Parent two.']]
        relations=self.relations([(self.child,parent) for parent in parents])
        merged=cc.consolidate(self.sources,self.initial,self.nominations,relations)
        plan=self.plan(equivalences=relations,consolidation=merged)
        chosen=[p for p in plan['pairs'] if p['source_id']=='peer']
        held=[p for p in plan['held_pairs'] if p['source_id']=='peer']
        self.assertEqual(len(chosen),3);self.assertEqual(len(held),1)
        self.assertEqual({p['candidate_id'] for p in [*chosen,*held]},set(parents))


if __name__=='__main__':unittest.main()
