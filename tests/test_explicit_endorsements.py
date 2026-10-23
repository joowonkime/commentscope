"""Exact reference/own-comparison adapter checks, never real Agent evidence."""
from copy import deepcopy
from dataclasses import replace
import unittest
from commentscope.factory import explicit_endorsements as endorse,minimal_membership as mm
from commentscope.factory import minimal_agents as ma,source_arguments as sa,owned_arguments as oa,explicit_discourse as ed
from commentscope.factory.framed_corpus import sources as registry
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_closed_policy import SourceClosedPolicyTests,ClosingRunner
from test_source_entailment import nli_response

class ExplicitEndorsementTests(unittest.TestCase):
    def setUp(self):
        fixture=SourceClosedPolicyTests();fixture.setUp()
        texts=['I think Policy P should cover basic needs, and work should fund additional wants.','Agreed','Totally agree','I agree but only with a different condition.']
        self.snapshot=replace(fixture.snapshot,comments=tuple(replace(c,text_original=t,parent_id=None if i==0 else '0')
            for i,(c,t) in enumerate(zip(fixture.snapshot.comments,texts,strict=True))))
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        self.group=endorse.inventory(self.sources,'Policy P','PP')['groups'][0]
        self.candidate=endorse.candidate(self.group);self.request=endorse.invocation(self.group);self.response=nli_response(self.request)
        self.core=oa.bind_core(self.candidate,{'output':{'kind':'value','entity':'Policy P','time_ids':[]}})
        graph=ed.parse(self.group['parent']);node=graph['nodes'][0]
        self.metadata=oa.bind_metadata(graph,node,{'output':{'kind':'value','entity':'Policy P','time_ids':[],
            'source_language':'en','authorship':'asserted_or_endorsed'}})

    def batches_records(self,response=None):
        batches=[];records=[];audits=[]
        for s in [self.group['parent'],*self.group['children']]:
            batch=endorse.bind_batch(self.group,self.request,response or self.response,[s['id']]);batches.append(batch)
            declared=endorse.declare(self.group,batch,self.core,self.metadata,s['id'])
            linked=sa.bind_links(declared);records.append(linked);tasks=sa.audit_tasks([linked],[self.core])
            req=sa.audit_request([linked],[self.core],tasks)
            audits.append(sa.bind_audit([linked],[self.core],tasks,ClosingRunner().call('audit',req)))
        return batches,records,audits

    def test_all_sources_scanned_partial_agreement_excluded_literal_parent_preserved(self):
        inventory=endorse.inventory(self.sources,'Policy P','PP')
        self.assertEqual(len(inventory['source_ids']),4);self.assertEqual(len(inventory['groups']),1)
        self.assertEqual(len(self.candidate['nominees']),3)
        self.assertEqual(self.candidate['text'],self.group['parent']['text'])
        self.assertNotIn('3',self.candidate['nominees'])

    def test_child_comparator_reads_only_own_speech_act_and_full_receipt_is_preserved(self):
        for source,case in zip([self.group['parent'],*self.group['children']],self.request['data']['cases'],strict=True):
            self.assertEqual(case['evidence'][0]['text'],source['text'])
            if source['parent'] is not None:self.assertEqual(case['text'],'I agree.')
        one=endorse.bind_batch(self.group,self.request,self.response,[self.group['children'][0]['id']])
        self.assertEqual(len(one['memberships']),1);self.assertEqual(len(one['completed_request']['data']['cases']),3)
        self.assertEqual(len(one['completed_response']['results']),3)
        self.assertEqual(len(mm.collect([self.group['children'][0]],[self.candidate],[one])),1)

    def test_reference_wrong_parent_changed_scope_or_non_agreement_cannot_count(self):
        for mutate in ('parent_id','parent_text','partial','candidate_scope'):
            group=deepcopy(self.group)
            if mutate=='parent_id':group['children'][0]['parent']['id']='elsewhere'
            elif mutate=='parent_text':group['children'][0]['parent']['text']='another proposal'
            elif mutate=='partial':group['children'][0]['text']='I agree but only partly.'
            else:group['parent']['text']=group['parent']['text'].replace('should','can')
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):endorse.validate_group(group)

    def test_public_compiler_uses_three_canonical_sources_without_donated_reasons(self):
        batches,records,audits=self.batches_records()
        out=ma.prepare(self.snapshot,[self.candidate],batches,records,[self.core],audits,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})
        self.assertEqual(len(out['compiled']['profiles']),1)
        self.assertEqual(out['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertEqual(len(out['bundle']['claims']),1)
        self.assertEqual(out['bundle']['candidates'][0]['reason_claim_ids'],[])
        self.assertEqual(len(out['bundle']['source_contexts']),2)
        self.assertFalse(out['quality_gate_passed'])

    def test_failed_own_comparison_blocks_public_agent(self):
        response=nli_response(self.request,{self.request['data']['cases'][1]['id']})
        batches,records,audits=self.batches_records(response)
        supported={r['source_id'] for b in batches for r in endorse.validate_batch(b) if r['relation']=='supported'}
        records=[r for r in records if r['source']['id'] in supported]
        audits=[a for a in audits if all(t['source_id'] in supported for t in a['tasks'])]
        out=ma.prepare(self.snapshot,[self.candidate],batches,records,[self.core],audits,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})
        self.assertFalse(out['compiled']['profiles'])

    def test_failed_complete_source_audit_cannot_be_overridden_by_explicit_agreement(self):
        batches,records,audits=self.batches_records();record=records[0];tasks=sa.audit_tasks([record],[self.core])
        req=sa.audit_request([record],[self.core],tasks)
        audits[0]=sa.bind_audit([record],[self.core],tasks,ClosingRunner(audit_bad=True).call('audit',req))
        out=ma.prepare(self.snapshot,[self.candidate],batches,records,[self.core],audits,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})
        self.assertFalse(out['compiled']['profiles'])

if __name__=='__main__':unittest.main()
