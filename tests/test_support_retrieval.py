from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.factory import source_first, source_index, support_retrieval as retrieval
from commentscope.factory.automatic_contract import digest
from commentscope.factory.target_ranking import target
from commentscope.ingestion.normalize import NormalizedComment
from tests.test_source_first import output


class SupportRetrievalTests(unittest.TestCase):
    def population(self, count=12):
        sources = {f's{i:02}': 'Safety reviews should be required.' + f' Source {i}.' for i in range(count)}
        rows = [NormalizedComment(comment_id=sid, text_analysis=s, normalization_version='test',
                                  duplicate_of=None) for sid, s in sources.items()]
        vectors = [[1., i/100] for i in range(count)]
        index = source_index.build(rows, vectors, 'a'*64, MODEL, REVISION, sources=sources)
        unit = source_first.bind('s00', sources['s00'], {'output': output('Safety reviews should be required.'), 'errors': []})['units'][0]
        cache = {'unit_ids': [unit['claim_id']], 'embedding_texts': [source_first.embedding_text(unit)], 'vectors': [[1., 0.]]}
        proposal = {'id': 'P1', 'claims': {'C': target(unit)}, 'anchor_unit_id': unit['claim_id'],
                    'candidate_unit_ids': [unit['claim_id']], 'sources': {'s00': sources['s00']}}
        return [proposal], [unit], cache, index, sources, rows

    def result(self, scheduled, high='s06'):
        return {'rows': [{'id': p['id'], 'pair_sha256': digest(p), 'errors': [],
                         'scores': {'entailment': .98 if p['premise_source_id'] == high else .01,
                                    'neutral': .01, 'contradiction': .01 if p['premise_source_id'] == high else .98}}
                        for p in scheduled['pairs']]}

    def test_searches_unextracted_sources_and_reranks_beyond_old_top_four(self):
        *args, rows = self.population()
        scheduled = retrieval.schedule(*args)
        self.assertEqual(len(scheduled['candidates'][0]['recall']), 11)
        assembled = retrieval.assemble(*args, scheduled, self.result(scheduled))
        selected = assembled['rankings'][0]['selected_source_ids']
        self.assertEqual(selected[:2], ['s00', 's06'])
        self.assertEqual(len(selected), 8)
        self.assertEqual(assembled['canonical_search_count'], 12)
        self.assertFalse(assembled['membership_approval'])
        self.assertFalse(assembled['proposals'][0]['semantic_approval'])
        self.assertNotIn('support_count', assembled)
        self.assertEqual(assembled['proposals'][0]['claims'], args[0][0]['claims'])

    def test_windows_cover_original_and_membership_gets_whole_source(self):
        *args, rows = self.population()
        sources = args[4]; sources['s06'] = 'a'*1200 + ' NOT unconditional.'
        rows[6] = replace(rows[6], text_analysis=sources['s06'])
        args[3] = source_index.build(rows, args[3]['vectors'], 'a'*64, MODEL, REVISION, sources=sources)
        scheduled = retrieval.schedule(*args)
        ps = [p for p in scheduled['pairs'] if p['premise_source_id'] == 's06']
        covered = set()
        for p in ps:
            self.assertEqual(p['premise'], sources['s06'][p['start']:p['end']])
            self.assertLessEqual(len(p['premise']), 500); covered.update(range(p['start'], p['end']))
        self.assertEqual(covered, set(range(len(sources['s06']))))
        result = retrieval.assemble(*args, scheduled, self.result(scheduled))
        self.assertEqual(result['proposals'][0]['sources']['s06'], sources['s06'])

    def test_pair_budget_and_errors_remain_unknown_not_negative(self):
        *args, rows = self.population()
        with patch.dict(retrieval.LIMITS, pairs=1):
            scheduled = retrieval.schedule(*args)
            self.assertEqual(len(scheduled['pairs']), 1)
            result = self.result(scheduled); result['rows'][0].update(errors=['timeout'], scores=None)
            assembled = retrieval.assemble(*args, scheduled, result)
            ranked = assembled['rankings'][0]
            self.assertTrue(all(r['ranking_score'] is None for r in ranked['rows']))
            self.assertEqual(ranked['selected_source_ids'], [f's{i:02}' for i in range(8)])
            self.assertEqual(len(assembled['pair_errors']), 1)

    def test_one_incomplete_window_makes_whole_source_ranking_unknown(self):
        *args, rows = self.population()
        args[4]['s01'] *= 30; rows[1] = replace(rows[1], text_analysis=args[4]['s01'])
        args[3] = source_index.build(rows, args[3]['vectors'], 'a'*64, MODEL, REVISION, sources=args[4])
        scheduled = retrieval.schedule(*args); result = self.result(scheduled)
        result['rows'][0].update(errors=['too_long'], scores=None)
        assembled = retrieval.assemble(*args, scheduled, result)
        self.assertIsNone(assembled['rankings'][0]['rows'][0]['ranking_score'])

    def test_index_binds_complete_canonical_population_text_and_model(self):
        *args, rows = self.population()
        source_index.validate(args[3], rows, 'a'*64, MODEL, REVISION, sources=args[4])
        for field, value in [('snapshot_sha256', 'b'*64), ('model_revision', 'changed'),
                             ('source_ids', ['s00']), ('embedding_texts', ['changed'])]:
            changed = deepcopy(args[3]); changed[field] = value
            with self.assertRaises(ValueError): source_index.validate(changed, rows, 'a'*64, MODEL, REVISION, sources=args[4])
        rows[0] = replace(rows[0], duplicate_of='other')
        with self.assertRaises(ValueError): source_index.validate(args[3], rows, 'a'*64, MODEL, REVISION, sources=args[4])

    def test_normalized_text_and_original_provenance_are_separate(self):
        *args, rows = self.population()
        original = args[4].copy(); original['s00'] = '  Safety reviews\nshould be required. '
        index = source_index.build(rows, args[3]['vectors'], 'a'*64, MODEL, REVISION, sources=original)
        self.assertEqual(index['source_sha256'][0], digest(original['s00']))
        self.assertEqual(index['embedding_texts'][0], rows[0].text_analysis)
        source_index.validate(index, rows, 'a'*64, MODEL, REVISION, sources=original)
        with self.assertRaises(ValueError):
            source_index.validate(index, rows, 'a'*64, MODEL, REVISION, sources=args[4])

    def test_bad_vectors_and_changed_query_source_target_fail(self):
        *args, rows = self.population()
        for value in ([float('nan'), 0], [0., 0.], [True, 0.], [1.]):
            altered = deepcopy(args); altered[3]['vectors'][0] = value
            with self.assertRaises(ValueError): retrieval.schedule(*altered)
        for mutate in (lambda a: a[2]['embedding_texts'].__setitem__(0, 'changed'),
                       lambda a: a[4].__setitem__('s00', 'changed'),
                       lambda a: a[0][0]['claims']['C'].__setitem__('text', 'Stronger assertion')):
            altered = deepcopy(args); mutate(altered)
            with self.assertRaises(ValueError): retrieval.schedule(*altered)

    def test_result_and_schedule_tampering_fail(self):
        *args, rows = self.population(); scheduled = retrieval.schedule(*args)
        result = self.result(scheduled); result['rows'].pop()
        with self.assertRaises(ValueError): retrieval.assemble(*args, scheduled, result)
        result = self.result(scheduled); result['rows'][0]['pair_sha256'] = 'bad'
        with self.assertRaises(ValueError): retrieval.assemble(*args, scheduled, result)
        changed = deepcopy(scheduled); changed['candidates'][0]['recall'].pop()
        with self.assertRaises(ValueError): retrieval.assemble(*args, changed, self.result(scheduled))

    def test_deterministic_order_and_no_duplicate_canonical_votes(self):
        *args, rows = self.population()
        other = deepcopy(args[0][0]); other['id'] = 'P2'; args[0].append(other)
        scheduled = retrieval.schedule(*args)
        args[0].reverse()
        self.assertEqual(scheduled, retrieval.schedule(*args))
        assembled = retrieval.assemble(*args, scheduled, self.result(scheduled))
        for p in assembled['proposals']:
            self.assertEqual(len(p['sources']), 8)
        args[3]['source_ids'][1] = 's00'
        with self.assertRaises(ValueError): retrieval.schedule(*args)

    def test_reserves_cosine_recall_even_when_nli_is_overconfident(self):
        *args, rows = self.population(); scheduled = retrieval.schedule(*args)
        assembled = retrieval.assemble(*args, scheduled, self.result(scheduled, high='s11'))
        self.assertEqual(len(assembled['rankings'][0]['cosine_reserve_source_ids']), 2)
        self.assertIn('s11', assembled['rankings'][0]['selected_source_ids'])
        self.assertFalse(assembled['quality_gate_passed'])

    def test_union_preserves_all_prior_nominations_without_reading_verdicts(self):
        *args, rows = self.population()
        args[0][0]['sources']['s11'] = args[4]['s11']
        scheduled = retrieval.schedule(*args)
        assembled = retrieval.assemble(*args, scheduled, self.result(scheduled))
        self.assertNotIn('s11', assembled['proposals'][0]['sources'])
        union = retrieval.union_nominations(args[0], assembled)
        self.assertEqual(set(union['proposals'][0]['sources']),
                         set(args[0][0]['sources']) | set(assembled['proposals'][0]['sources']))
        self.assertIn('s11', union['proposals'][0]['sources'])
        self.assertFalse(union['membership_approval']); self.assertFalse(union['quality_gate_passed'])

    def test_union_rejects_omitted_candidates_changed_sources_and_targets(self):
        *args, rows = self.population(); scheduled = retrieval.schedule(*args)
        assembled = retrieval.assemble(*args, scheduled, self.result(scheduled))
        for mutate in (lambda r: r['proposals'].clear(),
                       lambda r: r['proposals'][0]['sources'].__setitem__('s00', 'changed'),
                       lambda r: r['proposals'][0]['claims']['C'].__setitem__('text', 'changed'),
                       lambda r: r.__setitem__('membership_approval', True)):
            changed = deepcopy(assembled); mutate(changed)
            with self.assertRaises(ValueError): retrieval.union_nominations(args[0], changed)


if __name__ == '__main__': unittest.main()
