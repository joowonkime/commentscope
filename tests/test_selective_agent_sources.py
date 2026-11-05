"""Hold a whole failed source, without discarding valid peers or core facts."""
from copy import deepcopy
from dataclasses import replace
import unittest

from commentscope.factory import minimal_agents as ma,source_arguments as sa
from test_minimal_factory import membership
from experiments.grounding_contract_demo import MODEL
import test_minimal_agents as fixture


class SelectiveAgentSourcesTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.MinimalAgentTests();self.h.setUp()
        source={'id':'s3','text':'Adopt P. Dignity matters.','parent':None};self.h.sources.append(source)
        self.h.value['sources'].append({**deepcopy(self.h.value['sources'][0]),'source_id':'s3'})
        self.h.value['sources'][-1]['units'][0]['text']='Dignity matters.'
        self.h.members=[membership(self.h.sources,self.h.candidates,[{'source_id':s['id'],'candidate_id':self.h.cid} for s in self.h.sources])]
        self.h.snapshot=replace(self.h.snapshot,comments=tuple(replace(self.h.snapshot.comments[0],
            comment_id=s['id'],text_original=s['text']) for s in self.h.sources))

    def prepare(self,bad=('s3',),*,policy='verified_subset',records=None):
        records=self.h.records() if records is None else records;tasks=sa.audit_tasks(records,self.h.cores)
        audits=[sa.bind_audit(records,self.h.cores,tasks,{'output':{'decisions':[
            {'task_id':t['task_id'],'verdict':'uncertain' if t['source_id'] in bad and t['kind']=='unit' else 'supported'} for t in tasks]}})]
        return ma.prepare(self.h.snapshot,self.h.candidates,self.h.members,records,self.h.cores,audits,
                          model=MODEL,source_policy=policy)

    def test_three_verified_sources_compile_while_failed_source_stays_held(self):
        self.assertFalse(self.prepare(policy='all_members')['compiled']['profiles'])
        out=self.prepare();self.assertEqual(len(out['compiled']['profiles']),1)
        self.assertEqual(out['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertEqual({s['id'] for s in out['bundle']['sources']},{'s0','s1','s2'})
        self.assertEqual(out['map']['opinion_map']['perspectives'][0]['counts']['supported'],4)
        self.assertEqual(out['source_holds'][0]['source_id'],'s3')
        self.assertFalse(any('Dignity' in c['text'] for c in out['bundle']['claims']))

    def test_two_remaining_sources_cannot_be_padded_or_exposed(self):
        out=self.prepare(bad=('s2','s3'))
        self.assertFalse(out['compiled']['profiles'])
        self.assertIn('fewer_than_three_verified_core_sources',out['argument_holds'][0]['reasons'])

    def test_all_verified_sources_keep_the_same_grounded_bundle(self):
        old=self.prepare(bad=(),policy='all_members');selective=self.prepare(bad=())
        self.assertEqual(old['bundle'],selective['bundle'])
        self.assertEqual(old['compiled'],selective['compiled'])
        self.assertEqual(selective['source_holds'],[])

    def test_unassessed_source_is_kept_in_map_but_not_used_as_agent_evidence(self):
        out=self.prepare(bad=(),records=self.h.records()[:3])
        self.assertEqual(out['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertEqual(out['source_holds'][0]['reasons'],['member_arguments_unassessed'])
        self.assertEqual(out['map']['opinion_map']['perspectives'][0]['counts']['supported'],4)

    def test_failed_common_factual_prerequisite_cannot_be_removed_to_rescue_agent(self):
        source=self.h.sources[-1];source['text']='Adopt P. The program costs ten dollars.'
        self.h.snapshot=replace(self.h.snapshot,comments=tuple(replace(c,text_original=source['text']) if c.comment_id=='s3' else c for c in self.h.snapshot.comments))
        unit=self.h.value['sources'][-1]['units'][0]
        unit.update(text='The program costs ten dollars.',kind='fact',core_requires_for=[self.h.cid])
        self.h.members=[membership(self.h.sources,self.h.candidates,[{'source_id':s['id'],'candidate_id':self.h.cid} for s in self.h.sources])]
        out=self.prepare()
        self.assertFalse(out['compiled']['profiles'])
        self.assertIn('core_required_source_held',out['argument_holds'][0]['reasons'])


if __name__=='__main__':unittest.main()
