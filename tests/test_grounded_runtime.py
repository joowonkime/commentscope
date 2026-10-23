from copy import deepcopy
import json
import unittest

from commentscope.agents.grounded_runtime import GroundedSession, errors
from commentscope.factory import fact_checks as facts
from experiments.grounding_contract_demo import fixture, response


def selection(ids=None, kind='grounded', limitation='none'):
    return {'answerability': kind, 'claim_ids': ['position'] if ids is None else ids, 'limitation': limitation}


class GroundedRuntimeTests(unittest.TestCase):
    def session(self, output=None, bundle=None):
        bundle = bundle or fixture()
        # Legacy behavior tests choose fixture claims by identity; the mock model
        # returns the corresponding local address actually supplied in its input.
        texts = {c['id']:c['text'] for c in bundle['claims']}
        def provider(system,data,schema,**kwargs):
            aliases = {e['text']:e['claim_id'] for e in data['PERSPECTIVE']['allowed_entries']}
            value = deepcopy(output or selection())
            value['claim_ids'] = [aliases.get(texts.get(cid),cid) for cid in value['claim_ids']]
            return response(value)
        return GroundedSession(bundle, 'P1', provider=provider)

    def test_exact_entry_and_citations_not_model_prose(self):
        session = self.session()
        turn = session.ask('What is this perspective?')
        self.assertEqual(turn['points'][0]['text'], 'Safety reviews should be required.')
        self.assertEqual(turn['points'][0]['member_source_count'], 3)
        self.assertEqual(turn['points'][0]['epistemic_status'], 'attributed_value_not_verified_fact')
        self.assertEqual(len(turn['points'][0]['citations']['comment_evidence']), 3)
        self.assertFalse(turn['quality_gate_passed']); self.assertFalse(turn['semantic_guarantee'])

    def test_individual_reason_not_presented_as_group_consensus(self):
        turn = self.session(selection(['observed'])).ask('What observation is available?')
        self.assertEqual(turn['points'][0]['member_source_count'], 1)
        self.assertTrue(turn['points'][0]['citations']['verification_evidence'])

    def test_mutable_export_cache_cannot_change_published_entries(self):
        session = self.session()
        for entry in session.allowed['allowed_entries']:
            entry['text'] = 'Unbound invented text'
            entry['member_source_count'] = 99999
        turn = session.ask('What is the position?')
        self.assertEqual(turn['points'][0]['text'], 'Safety reviews should be required.')
        self.assertEqual(turn['points'][0]['member_source_count'], 3)

    def test_host_verifier_rejects_limits_outside_the_schema(self):
        for limit in ['ambiguous_question', 'out_of_scope']:
            self.assertTrue(errors(selection([], 'not_in_evidence', limit), {'position'}))

    def test_rejected_facts_and_raw_comments_excluded_from_request(self):
        session = self.session()
        request = session.invocation('What is the position?')
        encoded = json.dumps(request)
        self.assertNotIn('eliminated all accidents', encoded)
        self.assertNotIn('original_text', encoded)
        self.assertEqual(request['max_tokens'], 180)

    def test_roles_explicit_and_schema_cannot_mix_abstention_with_no_limit(self):
        request = self.session().invocation('What reason is provided?')
        roles = {entry['claim_id']: entry['declared_role'] for entry in request['data']['PERSPECTIVE']['allowed_entries']}
        self.assertEqual(roles, {'E1': 'reason'})
        for branch in request['schema']['anyOf']:
            properties = branch['properties']
            if properties['answerability']['const'] == 'not_in_evidence':
                self.assertEqual(properties['claim_ids']['maxItems'], 0)
                self.assertEqual(properties['limitation']['const'], 'missing_evidence')
            else:
                self.assertEqual(properties['claim_ids']['minItems'], 1)
        self.assertIn('Required JSON schema:', request['system'])

    def test_reason_question_cannot_select_core_even_if_provider_ignores_schema(self):
        session = self.session()
        session.provider = lambda *a, **k: response(selection(['E2']))
        turn = session.ask('What reasons and conditions are actually available?')
        self.assertEqual(turn['status'], 'error')
        self.assertEqual(turn['points'], [])

    def test_core_only_reason_question_requires_abstention_and_keeps_history_addresses(self):
        bundle = fixture()
        bundle['candidates'][0]['reason_claim_ids'] = []
        bundle['candidates'][0]['major_fact_ids'] = []
        session = self.session(bundle=bundle)
        session.ask('What is the position?')
        invocation = session.invocation('이 입장을 지지하는 이유는 무엇인가요?')
        self.assertEqual(invocation['data']['PERSPECTIVE']['allowed_entries'], [])
        self.assertEqual(invocation['data']['HISTORY'][0]['selected_claim_ids'], ['E1'])
        self.assertEqual(len(invocation['schema']['anyOf']), 1)
        self.assertNotIn('enum', invocation['schema']['anyOf'][0]['properties']['claim_ids']['items'])
        self.assertEqual(invocation['schema']['anyOf'][0]['properties']['claim_ids']['maxItems'], 0)
        session.provider = lambda *a, **k: response(selection([], 'not_in_evidence', 'missing_evidence'))
        self.assertEqual(session.ask('Why support this?')['status'], 'abstain')

    def test_concession_and_additional_position_cannot_substitute_for_reason(self):
        for role in ('concession', 'additional_position', 'core_restatement'):
            bundle = fixture()
            bundle['candidates'][0]['argument_roles'] = {cid:role for cid in bundle['candidates'][0]['reason_claim_ids']}
            invocation = self.session(bundle=bundle).invocation('What reason is available?')
            self.assertEqual(invocation['data']['PERSPECTIVE']['allowed_entries'], [])

    def test_cannot_add_new_claim_or_citation_text(self):
        session = self.session({**selection(), 'answer': 'Invented fact'})
        result = session.ask('What is the position?')
        self.assertEqual(result['status'], 'error'); self.assertEqual(result['points'], [])

    def test_foreign_or_rejected_ids_fail_closed(self):
        for cid in ['eliminated', 'other-agent', 'missing']:
            turn = self.session(selection([cid])).ask('Tell me more')
            self.assertEqual(turn['status'], 'error'); self.assertEqual(turn['points'], [])

    def test_abstention_has_no_claims(self):
        turn = self.session(selection([], 'not_in_evidence', 'missing_evidence')).ask('How much did it cost?')
        self.assertEqual(turn['status'], 'abstain'); self.assertEqual(turn['points'], [])

    def test_partial_has_explicit_limit(self):
        turn = self.session(selection(['observed'], 'partial', 'missing_evidence')).ask('What failed and what was the cost?')
        self.assertEqual(turn['status'], 'answered'); self.assertEqual(turn['answerability'], 'partial')

    def test_invalid_combinations_blocked(self):
        for value in [selection([], 'grounded'), selection(['position'], 'not_in_evidence', 'missing_evidence'),
                      selection(['position'], 'partial'), selection(['position', 'position']),
                      selection(['position'], 'partial', 'out_of_scope'), selection([{}])]:
            self.assertTrue(errors(value, {'position'}))

    def test_required_fact_premise_cannot_disappear_from_answer(self):
        bundle = fixture(); bundle['claims'][0]['requires'] = ['observed']
        for relation in bundle['relations']:
            if relation['claim_id'] == 'position': relation['claim_sha256'] = facts.claim_identity(bundle['claims'][0])
        turn = self.session(bundle=bundle).ask('What position is represented?')
        self.assertEqual([p['claim_id'] for p in turn['required_premises']], ['observed'])

    def test_deferred_candidate_cannot_run(self):
        bundle = fixture(); bundle['checks'] = []
        with self.assertRaises(ValueError): self.session(bundle=bundle)

    def test_source_mutation_during_call_blocks_publication(self):
        session = self.session()
        def mutate(*a, **k):
            session.bundle['sources'][0]['text'] += ' changed'
            return response(selection())
        session.provider = mutate
        with self.assertRaises(ValueError): session.ask('What is the position?')
        self.assertEqual(session.history, [])

    def test_input_copy_and_question_validation(self):
        bundle = fixture(); session = self.session(bundle=bundle)
        bundle['sources'][0]['text'] = 'external mutation'
        self.assertEqual(session.ask('What position?')['status'], 'answered')
        for question in ['', ' ', None, 'x'*1001]:
            with self.assertRaises(ValueError): session.ask(question)

    def test_followup_has_bounded_own_selection_history(self):
        session = self.session()
        for i in range(3): session.ask('Question '+str(i))
        history = session.invocation('And then?')['data']['HISTORY']
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]['selected_claim_ids'], ['E2'])
        self.assertEqual(session.history[-1]['selected_claim_ids'], ['position'])
        self.assertNotIn('result', json.dumps(history))
        for i in range(3): session.ask('More '+str(i))
        with self.assertRaises(ValueError): session.ask('Seventh')

    def test_transport_error_not_a_successful_abstention(self):
        session = self.session()
        def fail(*a, **k): raise OSError('unavailable')
        session.provider = fail
        self.assertEqual(session.ask('Question')['status'], 'error')

    def test_model_cannot_return_canonical_or_unknown_local_id(self):
        for cid in ('position','E999'):
            session=self.session()
            session.provider=lambda *a,**kw:response(selection([cid]))
            turn=session.ask('Position?')
            self.assertEqual(turn['status'],'error')
            self.assertEqual(turn['points'],[])

    def test_aliases_bind_core_dependencies_and_exact_published_citations(self):
        bundle=fixture();bundle['claims'][0]['requires']=['observed']
        for r in bundle['relations']:
            if r['claim_id']=='position':r['claim_sha256']=facts.claim_identity(bundle['claims'][0])
        session=self.session(bundle=bundle);request=session.invocation('Position?')
        entries=request['data']['PERSPECTIVE']['allowed_entries']
        core=next(e for e in entries if e['declared_role']=='core')
        self.assertEqual(core['claim_id'],'E2');self.assertEqual(core['requires'],['E1'])
        turn=session.ask('Position?')
        self.assertEqual(turn['selection_id_map'],{'E1':'observed','E2':'position'})
        self.assertEqual(turn['result']['output']['claim_ids'],['E2'])
        self.assertEqual(turn['points'][0]['claim_id'],'position')
        self.assertEqual(turn['required_premises'][0]['claim_id'],'observed')
        self.assertEqual(len(turn['points'][0]['citations']['comment_evidence']),3)


if __name__ == '__main__': unittest.main()
