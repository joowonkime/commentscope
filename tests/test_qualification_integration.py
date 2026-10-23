"""Synthetic guard outcomes test counting safety, not model accuracy."""
from copy import deepcopy
import unittest
from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import proposition_requirements as pr, proposition_fidelity as pf
from commentscope.factory import candidate_consolidation as cc
from test_minimal_factory import extraction, membership


class QualificationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':'Adopt P.','parent':None}
        self.text='Adopt P because fairness matters.'
        self.candidates=mc.candidates(extraction([self.source],{'s':[self.text,'Adopt P.']}))
        self.candidate=next(c for c in self.candidates if c['text']==self.text)
        self.pairs=[{'source_id':'s','candidate_id':self.candidate['id']}]
        self.raw={'decisions':[{'pair_id':'P1','relation':'supported','authorship':'asserted_or_endorsed',
            'scope_preserved':'yes','evidence_segment_ids':['S000']}]}
        pid=next(p['id'] for p in pf.phrases(self.text) if p['text']=='because fairness matters.')
        self.shape=pr.bind_shape(self.text,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':pid}]}})

    def assessment(self,verdict='absent'):
        check=pr.bind_detail(self.source,self.shape,self.shape['details'][0],{'output':{
            'verdict':verdict,'source_segment_ids':['S000'] if verdict=='present' else []}})
        return pr.assessment(self.source,self.shape,[check])

    def test_unassessed_absent_uncertain_qualification_cannot_count(self):
        for assessment in (None,self.assessment(),self.assessment('uncertain')):
            quals=[] if assessment is None else [{**self.pairs[0],'assessment':assessment}]
            batch=mm.bind([self.source],self.candidates,self.pairs,{'output':self.raw},quals)
            self.assertEqual(mm.validate_batch(batch)[0]['relation'],'uncertain')
            self.assertEqual(batch['memberships'][0]['decision']['relation'],'supported')
            self.assertFalse(batch['memberships'][0]['semantic_approval'])

    def test_passed_does_not_override_opposition_or_authorship(self):
        for changes in ({'relation':'opposed'},{'authorship':'not_asserted'},{'scope_preserved':'no'}):
            raw=deepcopy(self.raw);raw['decisions'][0].update(changes)
            batch=mm.bind([self.source],self.candidates,self.pairs,{'output':raw},
                [{**self.pairs[0],'assessment':self.assessment('present')}])
            self.assertNotEqual(batch['memberships'][0]['relation'],'supported')

    def test_changed_source_shape_duplicate_or_forged_pass_rejected(self):
        a=self.assessment();a['passed']=True
        with self.assertRaises(ValueError):pr.validate_assessment(a)
        a=self.assessment();a['source']['text']='Different.'
        with self.assertRaises(ValueError):mm.bind([self.source],self.candidates,self.pairs,{'output':self.raw},[{**self.pairs[0],'assessment':a}])
        q={**self.pairs[0],'assessment':self.assessment()}
        with self.assertRaises(ValueError):mm.bind([self.source],self.candidates,self.pairs,{'output':self.raw},[q,q])

    def test_equivalence_needs_both_directions_and_primary_equivalence(self):
        self.candidates=mc.candidates(extraction([self.source],{'s':['Adopt P.','Approve P.']}))
        pairs=[{'source_id':'s','candidate_id':c['id']} for c in self.candidates]
        members=[membership([self.source],self.candidates,pairs)]
        a,b=sorted(c['id'] for c in self.candidates);pair=[{'a':a,'b':b}]
        cs={c['id']:c for c in self.candidates};quals=[]
        for left,right in ((a,b),(b,a)):
            shape=pr.bind_shape(cs[right]['text'],{'output':{'status':'complete','qualifications':[]}})
            quals.append({'from_candidate_id':left,'to_candidate_id':right,'assessment':pr.assessment(
                {'id':left,'text':cs[left]['text'],'parent':None},shape,[])})
        for used,relation,expected in (([], 'equivalent','uncertain'),(quals[:1],'equivalent','uncertain'),
                                       (quals,'equivalent','equivalent'),(quals,'different','different')):
            batch=cc.bind([self.source],self.candidates,members,pair,{'output':{'decisions':[{'pair_id':'P1','relation':relation}]}},used)
            self.assertEqual(batch['relations'][0]['relation'],expected)
            consolidated=cc.consolidate([self.source],self.candidates,members,[batch])
            self.assertEqual(len(consolidated['candidates']),1 if expected=='equivalent' else 2)
