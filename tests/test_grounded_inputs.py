from copy import deepcopy
import json
import unittest

from commentscope.agents.grounded_inputs import compile_inputs, prompt_input
from commentscope.agents.runtime import AgentSession
from commentscope.factory import fact_checks as f
from experiments.grounding_contract_demo import fixture, scenarios, source_relation, add_check, claim


class GroundedInputTests(unittest.TestCase):
    def test_supported_fact_only_and_separate_support_counts(self):
        b=fixture();before=deepcopy(b);out=compile_inputs(b);self.assertEqual(b,before)
        profile=out['profiles'][0]
        self.assertEqual(profile['model_core_support_count'],3)
        self.assertEqual({p['claim_id'] for p in profile['prompt_entries']},{'position','observed'})
        fact=next(p for p in profile['prompt_entries'] if p['claim_id']=='observed')
        self.assertEqual(fact['member_source_count'],1)
        self.assertEqual(profile['omitted'],[{'claim_id':'eliminated','reason':'fact_refuted'}])
        self.assertEqual(out['agents'],[]);self.assertFalse(out['quality_gate_passed'])

    def test_bad_raw_reason_is_not_in_model_input(self):
        b=fixture();out=compile_inputs(b);payload=prompt_input(out,'P1',bundle=b)
        self.assertNotIn('eliminated',json.dumps(payload))
        self.assertNotIn('verification_evidence',json.dumps(payload))
        self.assertNotIn('original_text',json.dumps(payload))
        # Original source provenance remains available separately for inspection.
        self.assertIn('eliminated',json.dumps(out['profiles'][0]['citations']))

    def test_all_main_facts_missing_or_refuted_defer(self):
        for name in ['all_facts_unassessed','all_major_facts_refuted']:
            b=scenarios()[name];out=compile_inputs(b)
            self.assertEqual(out['profiles'],[])
            self.assertEqual(out['deferred'][0]['reason'],'no_verified_major_fact')
            with self.assertRaises(ValueError):prompt_input(out,'P1',bundle=b)

    def test_required_bad_fact_blocks_core(self):
        out=compile_inputs(scenarios()['core_requires_refuted_fact'])
        self.assertEqual(out['profiles'],[])
        self.assertEqual(out['deferred'][0]['reason'],'required_premise_unavailable')

    def test_two_sources_do_not_make_agent_input(self):
        out=compile_inputs(scenarios()['two_core_sources'])
        self.assertEqual(out['profiles'],[])
        self.assertEqual(out['deferred'][0]['reason'],'fewer_than_three_core_sources')

    def test_changed_profile_or_source_blocks_prompt_export(self):
        b=fixture();out=compile_inputs(b)
        out['profiles'][0]['prompt_entries'][0]['text']='Injected false assertion'
        with self.assertRaises(ValueError):prompt_input(out,'P1',bundle=b)
        out=compile_inputs(b);b['sources'][0]['text']+=' Changed'
        with self.assertRaises(ValueError):prompt_input(out,'P1',bundle=b)

    def test_optional_outsider_fact_cannot_be_added(self):
        b=fixture();s={'id':'outsider','canonical_id':'outsider','text':'External commenter only.'}
        b['sources'].append(s)
        c=claim('outside','A separate external fact.');b['claims'].append(c)
        b['relations'].append(source_relation(c,s));add_check(b,'outside')
        b['candidates'][0]['reason_claim_ids'].append('outside')
        out=compile_inputs(b)
        self.assertNotIn('outside',{e['claim_id'] for e in out['profiles'][0]['prompt_entries']})
        self.assertIn({'claim_id':'outside','reason':'no_member_source_for_reason'},out['profiles'][0]['omitted'])

    def test_external_verification_without_comment_support_cannot_add_fact(self):
        b=fixture();b['relations']=[r for r in b['relations'] if r['claim_id']!='observed']
        out=compile_inputs(b);self.assertEqual(out['profiles'],[])
        self.assertEqual(out['claim_decisions']['observed']['reason'],'no_source_support')

    def test_cycles_and_nonfact_dependencies_rejected(self):
        for dep in ['position','observed','missing']:
            b=fixture();b['claims'][1]['requires']=[dep]
            with self.subTest(dep=dep),self.assertRaises(ValueError):compile_inputs(b)

    def test_duplicate_source_votes_and_aliases_rejected(self):
        b=fixture();b['relations'].append(deepcopy(b['relations'][0]))
        with self.assertRaises(ValueError):compile_inputs(b)
        b=fixture();b['sources'][2]['canonical_id']='c2'
        with self.assertRaises(ValueError):compile_inputs(b)

    def test_unclear_partial_and_error_never_support(self):
        for verdict in ['partial','unclear','error','unassessed','unsupported']:
            b=fixture();b['relations'][0]['verdict']=verdict
            with self.subTest(verdict=verdict):self.assertEqual(compile_inputs(b)['profiles'],[])

    def test_fact_kind_needs_check_even_when_core_has_three_sources(self):
        b=fixture();b['claims'][0]['kind']='fact'
        for r in b['relations']:
            if r['claim_id']=='position':r['claim_sha256']=f.claim_identity(b['claims'][0])
        out=compile_inputs(b);self.assertEqual(out['profiles'],[])
        self.assertEqual(out['deferred'][0]['reason'],'fact_unassessed')

    def test_value_only_not_falsely_marked_verified_fact(self):
        b=fixture();b['candidates'][0]['reason_claim_ids']=[];b['candidates'][0]['major_fact_ids']=[]
        out=compile_inputs(b)
        self.assertEqual(out['profiles'][0]['prompt_entries'][0]['epistemic_status'],'attributed_value_not_verified_fact')
        self.assertEqual(out['agents'],[])

    def test_cannot_hide_major_facts_by_empty_declaration(self):
        b=fixture();b['candidates'][0]['major_fact_ids']=[]
        with self.assertRaises(ValueError):compile_inputs(b)

    def test_changed_document_and_ambiguous_checks_rejected(self):
        b=fixture();b['documents'][0]['text']+=' New correction'
        with self.assertRaises(ValueError):compile_inputs(b)
        b=fixture();b['checks'].append(deepcopy(b['checks'][0]))
        with self.assertRaises(ValueError):compile_inputs(b)

    def test_expired_document_blocks_export(self):
        b=fixture();out=compile_inputs(b);b['documents'][0]['expires_at']='2000-01-01T00:00:00Z'
        with self.assertRaises(ValueError):prompt_input(out,'P1',bundle=b)

    def test_existing_agent_runtime_cannot_misread_new_status(self):
        profile=compile_inputs(fixture())['profiles'][0]
        with self.assertRaises(ValueError):AgentSession(profile)

    def test_fake_promotion_and_new_fields_rejected(self):
        b=fixture();b['checks'][0]['record']['quality_gate_passed']=True
        with self.assertRaises(ValueError):compile_inputs(b)
        b=fixture();b['candidates'][0]['invented_replacement_fact']='Replacement argument'
        with self.assertRaises(ValueError):compile_inputs(b)


if __name__=='__main__':unittest.main()
