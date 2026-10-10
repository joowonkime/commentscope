import copy
import json
from pathlib import Path
import tempfile
import unittest

from commentscope.factory.claim_clusters import average_linkage, build, prepare, render, sha, validate_review
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/synthetic-snapshot.json'


def claim(cid, source):
    return {'claim_id': cid, 'source_comment_id': source, 'issue': 'work', 'claim': 'I might work.',
            'quote': 'I might work.', 'reason': None, 'reason_quote': None, 'condition': None,
            'condition_quote': None, 'scope': 'personal', 'modality': 'possible', 'stance': 'neutral', 'stance_target': None}


class ClaimClusterTests(unittest.TestCase):
    def prepared(self, same_source=False):
        units = [claim(str(i), 'a' if same_source else str(i)) for i in range(3)]
        return {'claims': units, 'source_count': 3, 'selected_count': 3, 'source_records': [],
                'sources': {c['source_comment_id']: {'text': '<script>bad()</script>', 'parent_id': None} for c in units}}

    def report(self, same_source=False):
        return build(self.prepared(same_source), [[1, 0]]*3)

    def review(self):
        return {'candidate_report_sha256': 'hash', 'reviewer': 'assistant', 'human_approved': False,
                'findings': [{'cluster_id': 'CC001', 'status': 'propose_for_user_review',
                              'evidence_claim_ids': ['0', '1', '2'], 'common_claim': 'Work remains possible.'}]}

    def test_average_linkage_partition_and_determinism(self):
        groups, _ = average_linkage([[1, 0], [0.99, 0.01], [-1, 0]], .45)
        self.assertEqual(groups, [[0, 1], [2]])
        self.assertEqual(groups, average_linkage([[1, 0], [0.99, 0.01], [-1, 0]], .45)[0])

    def test_invalid_vectors_and_thresholds(self):
        for vectors in [[[0, 0]], [[float('nan'), 1]], [[1], [1, 2]], [[True, 1]]]:
            with self.assertRaises(ValueError):
                average_linkage(vectors, .45)
        for threshold in [0, 1, float('nan')]:
            with self.assertRaises(ValueError):
                average_linkage([[1]], threshold)

    def test_zero_claims_are_explicit(self):
        prepared = self.prepared(); prepared['claims'] = []
        self.assertEqual(build(prepared, [])['summary']['groups'], 0)

    def test_vector_count_must_match(self):
        with self.assertRaises(ValueError):
            build(self.prepared(), [[1]])

    def test_same_source_claims_do_not_inflate_support(self):
        report = self.report(True)
        self.assertEqual(report['clusters'][0]['unique_source_count'], 1)
        self.assertEqual(report['clusters'][0]['status'], 'rare_unreviewed')
        self.assertEqual(report['summary']['accepted_perspectives'], 0)

    def test_all_claims_assigned_once(self):
        report = self.report()
        ids = [cid for c in report['clusters'] for cid in c['claim_ids']]
        self.assertEqual(sorted(ids), ['0', '1', '2'])

    def test_review_cannot_accept_or_use_foreign_evidence(self):
        for key, value in [('status', 'accepted'), ('evidence_claim_ids', ['other']), ('evidence_claim_ids', ['0'])]:
            review = self.review(); review['findings'][0][key] = value
            with self.assertRaises(ValueError):
                validate_review(self.report(), review, 'hash')

    def test_review_hash_and_distinct_sources(self):
        with self.assertRaises(ValueError):
            validate_review(self.report(), self.review(), 'different')
        with self.assertRaises(ValueError):
            validate_review(self.report(True), self.review(), 'hash')

    def test_split_cannot_drop_duplicate_or_approve_claims(self):
        review = self.review()
        item = review['findings'][0]
        item['status'] = 'split_needed'
        item['proposed_groups'] = [
            {'id': 'a', 'common_claim': 'One', 'status': 'rare', 'evidence_claim_ids': ['0']},
            {'id': 'b', 'common_claim': 'Two', 'status': 'rare', 'evidence_claim_ids': ['1', '2']}]
        validate_review(self.report(), review, 'hash')
        for members in [['1'], ['0', '1', '2'], ['outside']]:
            bad = copy.deepcopy(review)
            bad['findings'][0]['proposed_groups'][1]['evidence_claim_ids'] = members
            with self.assertRaises(ValueError): validate_review(self.report(), bad, 'hash')
        bad = copy.deepcopy(review)
        bad['findings'][0]['proposed_groups'][0]['status'] = 'accepted'
        with self.assertRaises(ValueError): validate_review(self.report(), bad, 'hash')

    def test_html_is_escaped_and_ai_proposal_is_not_approval(self):
        page = render(self.report(), self.review(), 'hash')
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('사용자 승인 대기', page)

    def extraction(self):
        loaded = load_snapshot(FIXTURE)
        sources = {c.comment_id: c for c in loaded.snapshot.comments}
        source = next(c for c in loaded.snapshot.comments if c.parent_id is None)
        unit = claim('ignored', source.comment_id)
        unit.pop('claim_id'); unit.pop('source_comment_id')
        unit['quote'] = source.text_original
        return {'snapshot_sha256': loaded.sha256, 'schema_version': 'claims-0.2', 'results': [{
            'comment_id': source.comment_id, 'source': source.text_original, 'parent_context': None,
            'finish_reason': 'stop', 'output': {'eligibility': 'argument_or_experience', 'claims': [unit]},
            'contract_errors': [], 'bound_claims': {'fake': 'must be ignored'}}]}

    def test_prepare_revalidates_raw_output_and_ignores_cached_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'extraction.json'
            data = self.extraction()
            data['results'][0]['output']['claims'][0]['quote'] = 'not a source quote'
            write_json_exclusive(path, data)
            report = prepare(FIXTURE, path)
            self.assertEqual(report['claims'], [])
            self.assertEqual(report['source_records'][0]['status'], 'blocked')

    def test_prepare_rejects_source_tampering_and_duplicate_ids(self):
        for mode in ['text', 'hash', 'duplicate']:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'extraction.json'
                data = self.extraction()
                if mode == 'text': data['results'][0]['source'] = 'changed'
                if mode == 'hash': data['snapshot_sha256'] = 'different'
                if mode == 'duplicate': data['results'].append(copy.deepcopy(data['results'][0]))
                write_json_exclusive(path, data)
                with self.assertRaises(ValueError): prepare(FIXTURE, path)

    def test_prepare_preserves_valid_claim_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'extraction.json'
            data = self.extraction(); write_json_exclusive(path, data)
            result = prepare(FIXTURE, path)
            self.assertEqual(result['extraction_sha256'], sha(path))
            self.assertEqual(result['claims'][0]['source_comment_id'], data['results'][0]['comment_id'])
            self.assertEqual(result['semantic_review_status'], 'pending')
