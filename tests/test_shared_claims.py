from copy import deepcopy
import unittest

from commentscope.factory import shared_claims as shared, minimal_membership as mm
from commentscope.factory.automatic_contract import digest


class SharedClaimsTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{'id': 'one', 'text': 'Adopt P because freedom matters.', 'parent': None},
                        {'id': 'two', 'text': 'Adopt P because safety matters.',
                         'parent': {'id': 'parent', 'text': 'An unrelated reason.'}}]
        self.output = {'candidates': [{'text': 'Adopt P.', 'nominees': ['A0', 'A1']}]}

    def test_originals_and_parent_roles_are_preserved_without_generated_evidence(self):
        req = shared.request(self.sources)
        for packet, source in zip(req['data']['ORIGINALS'], self.sources, strict=True):
            self.assertEqual(packet['source_sha256'], digest(source))
            self.assertEqual(packet['PARENT_CONTEXT_ONLY'], source['parent'])
            for span in packet['ORIGINAL_SEGMENTS']:
                self.assertEqual(source['text'][span['start']:span['end']], span['text'])
        self.assertNotIn('CANDIDATE', req['data'])

    def test_multiple_nominees_are_provenance_never_support_or_approval(self):
        record = shared.bind(self.sources, {'output': self.output})
        candidate, = shared.candidates([record])
        self.assertFalse(record['semantic_approval'])
        self.assertEqual(set(candidate['nominees']), {'one', 'two'})
        self.assertEqual(mm.collect(self.sources, [candidate], []), [])
        self.assertNotIn('meaning_context', candidate)
        self.assertNotIn('supported', candidate)

    def test_unknown_duplicate_nominees_and_duplicate_text_fail_closed(self):
        for rows in ([{'text': 'Adopt P.', 'nominees': ['parent']}],
                     [{'text': 'Adopt P.', 'nominees': ['A0', 'A0']}],
                     [self.output['candidates'][0], {'text': ' Adopt P. ', 'nominees': ['A1']}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                shared.bind(self.sources, {'output': {'candidates': rows}})

    def test_changed_source_or_parent_invalidates_request_provenance(self):
        record = shared.bind(self.sources, {'output': self.output})
        for field in ('text', 'parent'):
            changed = deepcopy(record)
            changed['sources'][1][field] = 'Changed.' if field == 'text' else None
            with self.subTest(field=field), self.assertRaises(ValueError):
                shared.candidates([changed])

    def test_exact_merge_retains_all_proposal_receipts_but_no_semantic_union(self):
        first = shared.bind(self.sources[:1], {'output': {'candidates': [
            {'text': 'Adopt P.', 'nominees': ['A0']}]}})
        second = shared.bind(self.sources[1:], {'output': {'candidates': [
            {'text': 'Adopt P.', 'nominees': ['A0']},
            {'text': 'Adopt P only if fees are waived.', 'nominees': ['A0']}]}})
        candidates = shared.candidates([first, second])
        self.assertEqual(len(candidates), 2)
        common = next(c for c in candidates if c['text'] == 'Adopt P.')
        self.assertEqual(set(common['extraction_refs']), {digest(first), digest(second)})
        self.assertEqual(set(common['nominees']), {'one', 'two'})
        self.assertEqual(common['equivalence_refs'], [])

    def test_96_sources_are_scheduled_once_without_labels_or_text_truncation(self):
        sources = [{'id': f'{i:03}', 'text': 'Complete original '+str(i), 'parent': None}
                   for i in range(96)]
        vectors = {s['id']: [1., 0.] for s in sources}
        groups = shared.batches(sources, vectors)
        self.assertEqual(len(groups), 8)
        self.assertEqual([s for g in groups for s in g], sources)
        self.assertTrue(all(len(g) <= shared.BATCH_SIZE for g in groups))
        self.assertEqual(groups, shared.batches(list(reversed(sources)), vectors))

    def test_common_contract_allows_empty_and_rejects_singleton_enumeration(self):
        record = shared.bind(self.sources, {'output': {'candidates': []}}, version=shared.COMMON)
        self.assertEqual(shared.candidates([record]), [])
        with self.assertRaises(ValueError):
            shared.bind(self.sources, {'output': {'candidates': [
                {'text': 'Adopt P.', 'nominees': ['A0']}]}}, version=shared.COMMON)
        record = shared.bind(self.sources, {'output': self.output}, version=shared.COMMON)
        self.assertEqual(record['artifact_kind'], shared.COMMON)
        self.assertEqual(len(shared.candidates([record])), 1)
        req = shared.request(self.sources, version=shared.COMMON)
        self.assertEqual(req['schema']['properties']['candidates']['maxItems'], 4)
        self.assertFalse(record['semantic_approval'])

    def test_common_capacity_does_not_build_or_call_singleton_requests(self):
        from commentscope.providers.context_capacity import partition
        inspected = []
        def inspect(req):
            inspected.append(req)
            return {'request_sha256': digest(req), 'fits': False}
        fitted, held = partition(self.sources,
            lambda rows: shared.request(rows, version=shared.COMMON), inspect, minimum=2)
        self.assertEqual(fitted, [])
        self.assertEqual(len(inspected), 1)
        self.assertEqual([r['item'] for r in held], self.sources)
        self.assertTrue(all(r['reason'] == 'context_capacity_minimum_group' for r in held))
        fitted, held = partition(self.sources[:1],
            lambda rows: shared.request(rows, version=shared.COMMON), inspect, minimum=2)
        self.assertFalse(fitted)
        self.assertEqual(held[0]['reason'], 'minimum_task_size')

    def test_reused_proposals_must_cover_exact_scope_including_unshared_authors(self):
        record = shared.bind(self.sources, {'output': {'candidates': []}}, version=shared.COMMON)
        self.assertEqual(shared.for_scope([record], self.sources), [record])
        for records, sources in (([record, record], self.sources),
                                 ([record], self.sources[:1]),
                                 ([record], [*self.sources, {'id': 'missing', 'text': 'Adopt P.', 'parent': None}])):
            with self.subTest(records=len(records), sources=len(sources)), self.assertRaises(ValueError):
                shared.for_scope(records, sources)


if __name__ == '__main__': unittest.main()
