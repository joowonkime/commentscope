from copy import deepcopy
from unittest import TestCase

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import raw_membership as raw, contextual_engine as ce
from commentscope.factory.automatic_contract import digest


def candidate(source, text):
    cid = mc.claim_id(text)
    return {'id': cid, 'text': text, 'aliases': [cid], 'nominees': {source['id']: digest(source)},
            'extraction_refs': ['synthetic-fixture'], 'equivalence_refs': []}


def decision(**updates):
    return {'relation': 'supported', 'authorship': 'asserted_or_endorsed',
            'candidate_interpretation': 'clear', 'scope_preserved': 'yes',
            'contribution': 'substantive', 'evidence_segment_ids': ['S000'], **updates}


class RawMembershipTests(TestCase):
    def setUp(self):
        self.source = {'id': 'reply', 'text': 'Deal with it',
                       'parent': {'id': 'parent', 'text': 'That situation is sad.'}}
        self.target = candidate(self.source, 'The author tells the parent to deal with the matter described.')

    def bind(self, **updates):
        return raw.bind(self.source, self.target, {'output': decision(**updates)})

    def test_raw_evidence_keeps_complete_parent_without_source_paraphrase(self):
        req = raw.request(self.source, self.target)
        self.assertEqual(req['data']['ORIGINAL']['PARENT_CONTEXT_ONLY'], self.source['parent'])
        self.assertEqual(req['data']['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'], 'Deal with it')
        self.assertEqual(set(req['data']), {'ORIGINAL', 'CANDIDATE'})

    def test_no_scope_or_extraction_record_needed_for_raw_comparison(self):
        calls = []
        class Runner:
            def call(_, stage, req):
                calls.append(req)
                if stage.startswith('raw-candidate-route'):
                    return {'output': {'role': 'contextual_attitude'}, 'raw': 'synthetic', 'errors': []}
                if stage.startswith('raw-own-evidence'):
                    return {'output': {'source_basis': 'own_assertion', 'verdict': 'fully_stated'}, 'raw': 'synthetic', 'errors': []}
                return {'output': decision(), 'raw': 'synthetic', 'errors': []}
        engine = ce.Engine([self.source], Runner(), lambda r: {'fits': True, 'request_sha256': digest(r)}, raw_membership=True)
        result = engine.support('reply', self.target)
        self.assertTrue(result['accepted'])
        self.assertFalse(engine.records); self.assertFalse(engine.scopes)
        self.assertEqual(mm.collect([self.source], [self.target], [result['batch']])[0]['relation'], 'supported')
        engine.support('reply', self.target)
        self.assertEqual(len(calls), 3)

    def test_each_uncertainty_still_withholds_positive(self):
        for update in [{'authorship': 'not_asserted'}, {'authorship': 'unclear'},
                       {'candidate_interpretation': 'uncertain'}, {'scope_preserved': 'no'},
                       {'scope_preserved': 'unclear'}, {'contribution': 'context_only'},
                       {'contribution': 'uncertain'}, {'evidence_segment_ids': []}]:
            with self.subTest(update=update):
                record = self.bind(**update)
                self.assertFalse(record['passed']); self.assertEqual(record['relation'], 'uncertain')

    def test_negative_and_conditional_relations_remain_separate(self):
        for relation in raw.RELATIONS[1:]:
            record = self.bind(relation=relation)
            self.assertFalse(record['passed']); self.assertEqual(record['relation'], relation)

    def test_parent_source_candidate_and_output_tampering_rejected(self):
        for field in ('parent', 'text', 'candidate', 'output'):
            record = self.bind()
            if field == 'parent': record['source']['parent']['text'] = 'An opposing parent.'
            elif field == 'text': record['source']['text'] = 'Not what I said.'
            elif field == 'candidate': record['candidate']['text'] = 'Different claim.'
            else: record['output']['scope_preserved'] = 'unclear'
            with self.subTest(field=field), self.assertRaises(ValueError): raw.validate(record)

    def test_parent_and_duplicate_segment_ids_cannot_be_own_evidence(self):
        for ids in (['parent'], ['S999'], ['S000', 'S000']):
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.bind(evidence_segment_ids=ids)

    def test_changed_current_source_or_double_vote_is_rejected(self):
        b = raw.batch([self.source], [self.target], [self.bind()])
        changed = deepcopy(self.source); changed['parent']['text'] = 'Changed parent'
        with self.assertRaises(ValueError): mm.collect([changed], [self.target], [b])
        with self.assertRaises(ValueError): mm.collect([self.source], [self.target], [b, b])

    def test_raw_positive_cannot_claim_fact_or_agent_approval(self):
        record = self.bind()
        self.assertFalse(record['semantic_approval']); self.assertFalse(record['factual_verification'])
