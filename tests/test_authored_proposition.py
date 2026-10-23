from copy import deepcopy
from unittest import TestCase

from commentscope.factory import authored_proposition as ap
from commentscope.factory import raw_membership_verification as v, raw_membership as raw
from commentscope.factory import substantive_target as st, minimal_claims as mc
from commentscope.factory.contextual_engine import Engine
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate, decision
from test_contextual_propositions import selected, original


def output(predicate, **updates):
    return {'form': 'complete', 'voice': 'asserted', 'predicate_quote': predicate,
            'references': [], **updates}


class AuthoredPropositionTests(TestCase):
    def setUp(self):
        self.source = original('Buses should receive funding.')
        self.target = candidate(self.source, self.source['text'])

    def proposal(self, value=None):
        return ap.bind_proposal(self.target, self.source, {'output': value or output('should receive funding')})

    def proof(self):
        return ap.assessment(self.proposal(), {'output': dict.fromkeys(ap.CHECKS, 'yes')})

    def test_literal_original_and_independent_verifier_boundary(self):
        self.source = original('Cafe\u0301  access should be free.')
        self.target = mc.candidates([selected(self.source)])[0]
        p = self.proposal(output('should be free'))
        self.assertEqual(p['selected_assertion']['text'], self.source['text'])
        self.assertNotEqual(self.target['text'], p['selected_assertion']['text'])
        data = ap.check_request(p)['data']
        self.assertEqual(set(data), {'SELECTED_ASSERTION', 'ORIGINAL', 'PREDICATE_WITNESS', 'REFERENCE_WITNESSES'})
        self.assertEqual(data['ORIGINAL'], self.source)
        self.assertEqual(ap.validate_proposal(p), p)
        changed = deepcopy(p); changed['selected_assertion']['text'] = self.target['text']
        with self.assertRaises(ValueError): ap.validate_proposal(changed)

    def test_fragment_missing_predicate_and_parent_cannot_supply_predicate(self):
        self.source = {**self.source, 'text': 'Seventy per week.', 'parent': {'id': 'p', 'text': 'I support a grant.'}}
        self.target = candidate(self.source, self.source['text'])
        for value in [output('', form='fragment'), output('support a grant')]:
            p = self.proposal(value)
            self.assertFalse(p['ready_for_check'])
            self.assertFalse(ap.assessment(p)['passed'])
            with self.assertRaises(ValueError): ap.check_request(p)

    def test_internal_and_parent_reference_quotes_are_exact(self):
        self.source = {**self.source, 'text': 'Workers say they need rest.', 'parent': {'id': 'p', 'text': 'A work-time proposal is under discussion.'}}
        self.target = candidate(self.source, self.source['text'])
        ref = {'mention_quote': 'they', 'antecedent_origin': 'source', 'antecedent_quote': 'Workers'}
        p = self.proposal(output('need rest', references=[ref]))
        self.assertTrue(p['ready_for_check'])
        self.assertEqual(p['references'][0]['antecedent']['text'], 'Workers')
        for updated in [dict(ref, antecedent_quote='they'), dict(ref, antecedent_origin='missing', antecedent_quote=''),
                        dict(ref, mention_quote='absent'), dict(ref, antecedent_origin='parent', antecedent_quote='Workers')]:
            self.assertFalse(self.proposal(output('need rest', references=[updated]))['ready_for_check'])
        self.source['text'] = 'I endorse that.'; self.target = candidate(self.source, self.source['text'])
        p = self.proposal(output('endorse', voice='endorsed', references=[{
            'mention_quote': 'that', 'antecedent_origin': 'parent', 'antecedent_quote': self.source['parent']['text']}]))
        self.assertTrue(p['ready_for_check'])
        check = dict.fromkeys(ap.CHECKS, 'yes'); check['references_grounded'] = 'uncertain'
        self.assertFalse(ap.assessment(p, {'output': check})['passed'])

    def test_duplicate_or_ambiguous_quotes_and_uncertain_voice_hold(self):
        self.source['text'] = 'It moves and it stops.'; self.target = candidate(self.source, self.source['text'])
        ref = {'mention_quote': 'it', 'antecedent_origin': 'missing', 'antecedent_quote': ''}
        p = self.proposal(output('moves', references=[ref, ref]))
        self.assertTrue(any('duplicate_mention' in g for g in p['guards']))
        self.assertFalse(self.proposal(output('moves', voice='unclear'))['ready_for_check'])
        self.source['text'] = 'it moves and it stops.'; self.target = candidate(self.source, self.source['text'])
        self.assertTrue(any('mention_unbound' in g for g in self.proposal(output('moves', references=[ref]))['guards']))

    def test_missing_or_negative_independent_check_cannot_pass(self):
        p = self.proposal(); self.assertFalse(ap.assessment(p)['passed'])
        for field in ap.CHECKS:
            check = dict.fromkeys(ap.CHECKS, 'yes'); check[field] = 'no'
            self.assertFalse(ap.assessment(p, {'output': check})['passed'])
        proof = self.proof(); self.assertTrue(ap.validate(proof)['passed'])
        self.assertFalse(proof['semantic_approval']); self.assertFalse(proof['factual_verification'])
        changed = deepcopy(proof); changed['check']['request_sha256'] = 'wrong'
        with self.assertRaises(ValueError): ap.validate(changed)

    def test_long_source_and_condition_remain_complete_inputs(self):
        self.source['text'] = 'Buses should receive funding only if access remains public. '+'Background. '*150
        self.target = candidate(self.source, 'Buses should receive funding only if access remains public.')
        req = ap.proposal_request(self.target, self.source)
        self.assertEqual(req['data']['ORIGINAL']['text'], self.source['text'])
        self.assertIn('only if', req['data']['SELECTED_ASSERTION']['text'])

    def test_v9_exact_binding_and_old_contract_requests_preserved(self):
        content = {'output': {'assertion_kind': 'public_issue_claim', 'reference_target': 'named_or_context_resolved'}}
        target = st.bind(self.target, self.source, {'output': {'target_address': 'SELF',
            'target_content': 'public_issue_claim', 'target_closed': 'yes'}}, st.NORMALIZED)
        self.assertEqual(v.route_request(self.target, self.source, version=v.AUTHORED),
                         v.route_request(self.target, self.source, version=v.TARGETED_NORMALIZED))
        raw_proof = raw.bind(self.source, self.target, {'output': decision()})
        self.assertEqual(v.evidence_request(raw_proof, v.AUTHORED), v.evidence_request(raw_proof, v.ALIGNED))
        missing = v.bind_route(self.target, content, self.source, version=v.AUTHORED, target_check=target)
        self.assertFalse(missing['passed'])
        good = v.bind_route(self.target, content, self.source, version=v.AUTHORED, target_check=target, proposition_proof=self.proof())
        self.assertTrue(good['passed'])
        for version, proof in [(v.TARGETED_NORMALIZED, self.proof()), (v.AUTHORED, deepcopy(self.proof()))]:
            if version == v.AUTHORED: proof['proposal']['origin']['id'] = 'foreign'
            with self.assertRaises(ValueError):
                v.bind_route(self.target, content, self.source, version=version, target_check=target, proposition_proof=proof)

    def test_actual_engine_requires_checked_proposition_and_caches_it(self):
        owner = self
        class Runner:
            def __init__(self, fragment=False): self.calls = []; self.fragment = fragment
            def call(self, stage, request):
                self.calls.append(stage)
                if stage.startswith('authored-proposition-check'):
                    value = dict.fromkeys(ap.CHECKS, 'yes')
                elif stage.startswith('authored-proposition'):
                    value = output('should receive funding', form='fragment' if self.fragment else 'complete')
                elif stage.startswith('raw-candidate-route'):
                    value = {'assertion_kind': 'public_issue_claim', 'reference_target': 'named_or_context_resolved'}
                elif stage.startswith('raw-candidate-target'):
                    value = {'target_address': 'SELF', 'target_content': 'public_issue_claim', 'target_closed': 'yes'}
                elif stage.startswith('raw-own-evidence'):
                    value = {'reference_basis': 'self_contained', 'target_alignment': 'aligned', 'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                else: value = decision()
                return {'output': value, 'raw': 'test fixture', 'errors': []}
        for fragment in (False, True):
            runner = Runner(fragment); other = {**self.source, 'id': 'other'}
            engine = Engine([self.source, other], runner, lambda req: {'fits': True, 'request_sha256': digest(req)},
                            raw_membership=True, verification_contract=v.AUTHORED)
            for source in (self.source, other):
                result = engine.support(source['id'], self.target)
                self.assertEqual(result['accepted'], not fragment, {'result': result, 'errors': engine.errors})
            self.assertFalse(engine.errors)
            self.assertEqual(sum(x.startswith('authored-proposition-') and not x.startswith('authored-proposition-check') for x in runner.calls), 1)
            self.assertEqual(sum(x.startswith('authored-proposition-check') for x in runner.calls), 0 if fragment else 1)
