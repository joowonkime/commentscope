"""Retrieval/provenance fixtures; these do not measure model accuracy."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import named_candidate_census as census,shared_claims
from commentscope.factory import policy_target,explicit_discourse as ed,owned_arguments as oa
from commentscope.factory import source_closed_policy as closed,policy_attitude
from commentscope.factory.automatic_contract import digest
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_entailment import nli_response
from test_source_closed_policy import ClosingRunner


class NamedCensusTests(unittest.TestCase):
    def setUp(self):
        template=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        self.snapshot=replace(template,video=replace(template.video,title='Policy P Explained PP'),
            usage=replace(template.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0],comment_id=str(i),parent_id=None,
                text_original='PP could reduce stress. '+word+' matters.')
                for i,word in enumerate(['Equity','Freedom','Fairness','Care','Health'])))
        self.sources=list(registry(self.snapshot,include_video_context=True).values())
        proposal=shared_claims.bind(self.sources,{'output':{'candidates':[
            {'text':'PP could reduce stress.','nominees':['A0','A1']},
            {'text':'People could stop working.','nominees':['A2','A3']}]}},version=shared_claims.COMMON)
        self.proposals=shared_claims.candidates([proposal])
        self.ranked=census.ranking(self.sources,self.proposals,'Policy P','PP',limit=3)
        self.req=census.invocation(self.ranked);self.res=nli_response(self.req)
        self.record=census.bind(self.ranked,[(self.req,self.res)])

    def test_nominations_do_not_approve_and_unselected_sources_remain_visible(self):
        self.assertEqual(len(self.ranked['sources']),5)
        self.assertEqual(len(self.req['data']['cases']),3)
        cs=census.candidates(self.record);self.assertEqual(len(cs),1)
        self.assertEqual(len(cs[0]['nominees']),3);self.assertFalse(self.record['semantic_approval'])
        for row in self.ranked['rows']:self.assertEqual(row['unselected_pair_status'],'unassessed_not_rejected')
        unnamed=next(r for r in self.ranked['rows'] if not r['named_policy'])
        self.assertFalse(unnamed['selected_source_ids'])

    def test_parent_text_never_drives_ranking_or_premise(self):
        changed=deepcopy(self.sources)
        changed[-1]['parent']={'id':'parent','text':'PP could reduce stress. '*30}
        ranked=census.ranking(changed,self.proposals,'Policy P','PP',limit=3)
        self.assertEqual(ranked['rows'],self.ranked['rows'])
        self.assertEqual(census.invocation(ranked),self.req)

    def test_remaining_self_contained_hypotheses_need_no_invented_policy_name(self):
        ranked=census.ranking(self.sources,self.proposals,'Policy P','PP',limit=3,remaining_unnamed=True)
        request=census.invocation(ranked)
        self.assertEqual(len(request['data']['cases']),3)
        self.assertTrue(all(c['text']=='People could stop working.' for c in request['data']['cases']))
        record=census.bind(ranked,[(request,nli_response(request))]);census.validate(record)
        self.assertEqual(record['artifact_kind'],census.UNNAMED)
        self.assertFalse(record['semantic_approval'])

    def test_missing_changed_duplicate_or_extra_comparisons_rejected(self):
        for mutation in ('missing','changed','extra','duplicate'):
            req=deepcopy(self.req)
            if mutation=='missing':req['data']['cases'].pop()
            elif mutation=='changed':req['data']['cases'][0]['evidence'][0]['text']='Different.'
            elif mutation=='extra':req['data']['cases'].append({**req['data']['cases'][0],'id':'extra'})
            batches=[(req,nli_response(req))]
            if mutation=='duplicate':batches*=2
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):census.bind(self.ranked,batches)

    def test_ranking_tamper_rejected(self):
        record=deepcopy(self.ranked)
        next(r for r in record['rows'] if r['selected_source_ids'])['selected_source_ids'].reverse()
        with self.assertRaises(ValueError):census.invocation(record)

    def test_general_target_still_requires_literal_name_in_own_node(self):
        candidate=census.candidates(self.record)[0];graph=ed.parse(self.sources[0]);node=graph['nodes'][0]
        proof=policy_target.bind_general(graph,node,candidate,'Policy P','PP')
        self.assertTrue(proof['passed']);policy_target.validate(graph,node,candidate,proof)
        source={**self.sources[0],'text':'It could reduce stress.'}
        graph=ed.parse(source);proof=policy_target.bind_general(graph,graph['nodes'][0],candidate,'Policy P','PP')
        self.assertFalse(proof['passed'])

    def test_prediction_can_compile_without_unrelated_attitude_gate(self):
        runner=ClosingRunner(kind='prediction');runner.core_kind='prediction'
        out=closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']),1)
        self.assertFalse(any(req['system'].startswith(policy_attitude.SYSTEM) for _,req in runner.calls))
        self.assertTrue(all(e['kind']=='prediction' for e in out['agent_inputs']['compiled']['profiles'][0]['prompt_entries']))
        self.assertFalse(out['quality_gate_passed'])

    def test_fact_core_is_held_not_retyped_as_a_forecast(self):
        runner=ClosingRunner(kind='fact');runner.core_kind='fact'
        out=closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION})
        self.assertFalse(out['accepted']);self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        self.assertTrue(all(c['output']['kind']=='fact' for c in out['cores']))


if __name__=='__main__':unittest.main()
