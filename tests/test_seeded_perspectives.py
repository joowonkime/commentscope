from copy import deepcopy
from dataclasses import replace
import unittest

from commentscope.agents import seed_policy
from commentscope.agents.grounded_inputs import compile_inputs, SEEDED_VERSION
from commentscope.factory import minimal_agents, pipeline_stages
from experiments.grounding_contract_demo import fixture, source_relation, MODEL
import test_minimal_agents as agent_fixtures
from test_minimal_factory import membership
import test_minimal_pipeline as pipeline_fixture


def seeded_bundle():
    bundle=fixture();bundle['sources']=bundle['sources'][:1]
    bundle['claims']=bundle['claims'][:1]
    bundle['relations']=[source_relation(bundle['claims'][0],bundle['sources'][0])]
    bundle['candidates'][0].update(reason_claim_ids=[],major_fact_ids=[])
    bundle['checks']=[];bundle['admission_policy']=deepcopy(seed_policy.POLICY)
    doc=bundle['documents'][0]
    bundle['reference_selections']=[{'id':'prepared','document_id':doc['id'],
        'span':{'start':0,'end':len(doc['text']),'text':doc['text']}}]
    return bundle


class SeededPerspectiveTests(unittest.TestCase):
    def test_one_two_three_and_zero_sources_keep_observed_counts(self):
        for count in (0,1,2,3):
            bundle=seeded_bundle();original=fixture()
            bundle['sources']=original['sources'][:count]
            bundle['relations']=[source_relation(bundle['claims'][0],s) for s in bundle['sources']]
            compiled=compile_inputs(bundle)
            self.assertEqual(len(compiled['profiles']),int(count>0))
            if count:self.assertEqual(compiled['profiles'][0]['model_core_support_count'],count)
            self.assertEqual(compiled['artifact_kind'],SEEDED_VERSION)
            self.assertFalse(compiled['formal_factory_eligible'])

    def test_legacy_is_still_three_and_unknown_policies_cannot_override(self):
        bundle=seeded_bundle();bundle.pop('admission_policy');bundle.pop('reference_selections')
        self.assertFalse(compile_inputs(bundle)['profiles'])
        for policy in ({},dict(seed_policy.POLICY,minimum_core_sources=0),False):
            bundle['admission_policy']=policy
            with self.assertRaises(ValueError):compile_inputs(bundle)

    def test_source_mutation_duplicate_vote_and_unverified_fact_still_fail(self):
        bundle=seeded_bundle();bundle['sources'][0]['text']+='changed'
        with self.assertRaises(ValueError):compile_inputs(bundle)
        bundle=seeded_bundle();bundle['relations']*=2
        with self.assertRaises(ValueError):compile_inputs(bundle)
        bundle=seeded_bundle();bundle['claims'][0]['requires']=['observed']
        fact=fixture()['claims'][1];bundle['claims'].append(fact)
        bundle['relations']=[source_relation(c,bundle['sources'][0]) for c in bundle['claims']]
        bundle['candidates'][0]['major_fact_ids']=['observed']
        self.assertFalse(compile_inputs(bundle)['profiles'])

    def test_optional_unverified_fact_is_omitted_without_becoming_a_core_premise(self):
        bundle=seeded_bundle();fact=fixture()['claims'][1]
        bundle['claims'].append(fact);bundle['relations'].append(source_relation(fact,bundle['sources'][0]))
        bundle['candidates'][0]['reason_claim_ids']=['observed']
        compiled=compile_inputs(bundle)
        self.assertEqual(len(compiled['profiles']),1)
        self.assertEqual([e['claim_id'] for e in compiled['profiles'][0]['prompt_entries']],['position'])
        self.assertEqual(compiled['profiles'][0]['omitted'][0]['reason'],'fact_unassessed')
        bundle['claims'][0]['requires']=['observed']
        bundle['relations'][0]=source_relation(bundle['claims'][0],bundle['sources'][0])
        with self.assertRaises(ValueError):compile_inputs(bundle)
        bundle['candidates'][0]['major_fact_ids']=['observed']
        self.assertFalse(compile_inputs(bundle)['profiles'])

    def test_compiler_reuses_only_verified_sources_and_preserves_private_draft(self):
        h=agent_fixtures.MinimalAgentTests();h.setUp();records=h.records()[:1]
        members=[membership(h.sources,h.candidates,[{'source_id':'s0','candidate_id':h.cid}])]
        args=(h.snapshot,h.candidates,members,records,h.cores,h.audits(records))
        self.assertFalse(minimal_agents.prepare(*args,model=MODEL)['compiled']['profiles'])
        out=minimal_agents.prepare(*args,model=MODEL,admission_policy=seed_policy.POLICY)
        self.assertEqual(out['compiled']['profiles'][0]['model_core_support_count'],1)
        self.assertFalse(minimal_agents.prepare(*args,model=MODEL,_draft_single_source=True)['compiled']['profiles'])
        with self.assertRaises(ValueError):
            minimal_agents.prepare(*args,model=MODEL,_draft_single_source=True,admission_policy=seed_policy.POLICY)
        self.assertFalse(minimal_agents.prepare(*args[:-1],[],model=MODEL,
            admission_policy=seed_policy.POLICY)['compiled']['profiles'])

    def test_full_pipeline_routes_single_member_to_argument_and_compiler(self):
        h=pipeline_fixture.MinimalPipelineTests();h.setUp()
        h.snapshot=replace(h.snapshot,comments=h.snapshot.comments[:1])
        output=h.process(pipeline_fixture.ScriptedRunner(),admission_policy=seed_policy.POLICY)
        profiles=output['agent_inputs']['compiled']['profiles']
        self.assertEqual(len(profiles),1)
        self.assertEqual(profiles[0]['model_core_support_count'],1)
        self.assertEqual(output['agent_inputs']['bundle']['admission_policy'],seed_policy.POLICY)

    def test_factory_optional_fact_and_core_required_fact_follow_different_contracts(self):
        h=agent_fixtures.MinimalAgentTests();h.setUp()
        for source in h.value['sources']:source['units'][0]['kind']='fact'
        records=h.records();audits=h.audits(records)
        args=(h.snapshot,h.candidates,h.members,records,h.cores,audits)
        self.assertFalse(minimal_agents.prepare(*args,model=MODEL)['compiled']['profiles'])
        seeded=minimal_agents.prepare(*args,model=MODEL,admission_policy=seed_policy.POLICY)
        self.assertEqual(len(seeded['compiled']['profiles']),1)
        self.assertEqual(seeded['bundle']['candidates'][0]['major_fact_ids'],[])
        self.assertEqual(len(seeded['compiled']['profiles'][0]['prompt_entries']),1)
        for source in h.value['sources']:source['units'][0]['core_requires_for']=[h.cid]
        records=h.records()
        required=minimal_agents.prepare(h.snapshot,h.candidates,h.members,records,h.cores,
            h.audits(records),model=MODEL,admission_policy=seed_policy.POLICY)
        self.assertFalse(required['compiled']['profiles'])


if __name__=='__main__':unittest.main()
