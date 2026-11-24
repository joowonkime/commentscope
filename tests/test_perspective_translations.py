from copy import deepcopy
from hashlib import sha256
import unittest

from tools.perspective_translations import publish, worksheet


class PerspectiveTranslationTests(unittest.TestCase):
    def setUp(self):
        self.view = {'analysis_id': 'A', 'perspectives': [
            {'id': 'P', 'display_name': 'Later start', 'core_claim_id': 'C', 'text': 'Start later.',
             'grounds': [{'claim_id': 'G', 'text': '등교 시간이 겹친다.'}]}]}
        self.issue = 'When should we start?'
        self.review = worksheet(self.view, self.issue, 'en')
        for key, value in {'issue': '언제 시작할까?', 'name:P': '늦게 시작하기', 'claim:C': '더 늦게 시작하자.',
                           'claim:G': 'It overlaps with the school commute.'}.items():
            self.review['fields'][key]['translation'] = value
        self.review['fields']['claim:G']['source_language'] = 'ko'

    def test_publish_checks_sources_and_keeps_only_hashes_and_translations(self):
        fields = publish(self.view, self.issue, self.review)['A']['fields']
        self.assertEqual(fields['name:P'], {'sha256': sha256(b'Later start').hexdigest(), 'ko': '늦게 시작하기'})
        self.assertEqual(fields['claim:G']['en'], 'It overlaps with the school commute.')
        self.assertEqual(fields['claim:G']['source_language'], 'ko')
        self.assertNotIn('original', fields['claim:G'])

    def test_changed_analysis_or_field_and_incomplete_review_cannot_publish(self):
        for key, value in [('original', 'Different wording'), ('translation', ' '), ('source_language', 'unknown')]:
            reviewed = deepcopy(self.review)
            reviewed['fields']['name:P'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                publish(self.view, self.issue, reviewed)
        with self.assertRaises(ValueError):
            publish({**self.view, 'analysis_id': 'B'}, self.issue, self.review)
        del self.review['fields']['claim:G']
        with self.assertRaises(ValueError):
            publish(self.view, self.issue, self.review)

    def test_optional_topics_publish_bilingual_labels_and_unique_registered_members(self):
        topic = {'en': 'School schedules', 'ko': '등교 시간', 'members': ['P']}
        self.review['topics'] = [topic]
        self.assertEqual(publish(self.view, self.issue, self.review)['A']['topics'], [topic])
        for invalid in ([topic, topic], [{**topic, 'ko': ' '}], [{**topic, 'members': ['unknown']}],
                        [{**topic, 'members': ['P', 'P']}], [{**topic, 'members': []}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                publish(self.view, self.issue, {**self.review, 'topics': invalid})
        self.assertNotIn('topics', publish(self.view, self.issue, {**self.review, 'topics': []})['A'])
