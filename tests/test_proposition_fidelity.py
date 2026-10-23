from copy import deepcopy
import unittest

from commentscope.factory import proposition_fidelity as pf


class PropositionFidelityTests(unittest.TestCase):
    source = {'id': 'a', 'text': 'Adopt P because fairness matters.', 'parent': None}
    text = 'Adopt P because fairness matters.'

    def value(self):
        return {'details': [{'candidate_phrase_id': 'P002', 'source_segment_ids': ['S000']}], 'verdict': 'faithful'}

    def test_exact_inventory_and_source_request_binding(self):
        record = pf.bind(self.source, self.text, {'output': self.value()})
        self.assertEqual(pf.validate(record)['verdict'], 'faithful')
        changed = deepcopy(record); changed['source']['text'] = 'Different.'
        with self.assertRaises(ValueError): pf.validate(changed)

    def test_missing_detail_evidence_cannot_count_despite_faithful_label(self):
        value = self.value(); value['details'][0]['source_segment_ids'] = []
        record = pf.bind(self.source, self.text, {'output': value})
        self.assertEqual(record['verdict'], 'uncertain')
        self.assertIn('candidate_detail_without_source_evidence', record['guards'])

    def test_generated_or_other_candidate_quotes_rejected(self):
        for key in ('candidate_phrase_id', 'source_segment_ids'):
            value = self.value(); value['details'][0][key] = 'P999' if key=='candidate_phrase_id' else ['S999']
            with self.assertRaises(ValueError): pf.bind(self.source, self.text, {'output': value})

    def test_parent_reason_is_not_own_evidence(self):
        source = {**self.source, 'text': 'Adopt P.', 'parent': {'id': 'p', 'text': self.source['text']}}
        value = self.value(); value['details'][0]['source_segment_ids'] = ['S001']
        with self.assertRaises(ValueError): pf.bind(source, self.text, {'output': value})

    def test_plain_position_can_have_no_qualification_but_is_not_semantic_approval(self):
        record=pf.bind(self.source,'Adopt P.',{'output':{'details':[],'verdict':'faithful'}})
        self.assertFalse(record['semantic_approval'])

    def test_candidate_phrase_inventory_is_exact_and_source_independent(self):
        for phrase in pf.phrases(self.text):
            self.assertEqual(self.text[phrase['start']:phrase['end']],phrase['text'])
        self.assertIn('because fairness matters.',[p['text'] for p in pf.phrases(self.text)])

    def test_duplicate_inventory_and_changed_verdict_rejected(self):
        value = self.value(); value['details'] *= 2
        with self.assertRaises(ValueError): pf.bind(self.source, self.text, {'output': value})
        record = pf.bind(self.source, self.text, {'output': self.value()}); record['verdict'] = 'uncertain'
        with self.assertRaises(ValueError): pf.validate(record)


if __name__ == '__main__': unittest.main()
