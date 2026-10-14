from copy import deepcopy
import unittest

from commentscope.factory import semantic_neighborhood as retrieval, source_first
from commentscope.factory.automatic_contract import digest
from commentscope.factory.unit_reason_typing import UnitReasonTyping
from tests.test_source_first import output


class ProductPathTests(unittest.TestCase):
    def population(self, count=6):
        sources = {f's{i}': f'Reviews should be required. They would reduce errors in area {i}.' for i in range(count)}
        units = []
        for i, (sid, source) in enumerate(sources.items()):
            value = output(source)
            value['claims'][0].update(claim='Reviews should be required.', stance_target=f'review wording {i}',
                reason='They would reduce errors.', reason_quote=f'They would reduce errors in area {i}.')
            units.extend(source_first.bind(sid, source, {'errors': [], 'output': value})['units'])
        cache = {'unit_ids': [u['claim_id'] for u in units],
                 'embedding_texts': [source_first.embedding_text(u) for u in units], 'vectors': [[1., 0.]]*count}
        return units, cache, sources

    def result(self, scheduled, score=.9):
        return {'rows': [{'id': p['id'], 'pair_sha256': digest(p), 'errors': [],
                'scores': {'entailment': score, 'neutral': 1-score, 'contradiction': 0.}}
                for p in scheduled['pairs']]}

    def test_cross_frame_retrieval_is_not_membership_or_scope_rewrite(self):
        units, cache, sources = self.population()
        units[0]['scope'] = 'personal'; units[1]['stance'] = 'oppose'
        scheduled = retrieval.schedule(units, cache, sources)
        self.assertTrue(all(p['crosses_frame'] for p in scheduled['pairs']))
        ranked = retrieval.assemble(units, cache, sources, scheduled, self.result(scheduled))
        for proposal in ranked['proposals']:
            anchor = next(u for u in units if u['claim_id'] == proposal['anchor_unit_id'])
            self.assertEqual(proposal['claims']['C']['text'], anchor['claim'])
            self.assertEqual(proposal['claims']['C']['scope']['entity'], anchor['scope'])
            self.assertFalse(proposal['semantic_approval'])
            self.assertEqual(proposal['sources'], {sid: sources[sid] for sid in proposal['sources']})
        self.assertFalse(ranked['membership_approval']); self.assertFalse(ranked['quality_gate_passed'])

    def test_one_source_gets_one_neighbor_and_never_votes_for_itself(self):
        units, cache, sources = self.population(3)
        extra = {**units[1], 'claim_id': 'extra'}; units.append(extra)
        cache['unit_ids'].append('extra'); cache['embedding_texts'].append(source_first.embedding_text(extra))
        cache['vectors'].append([1., 0.])
        scheduled = retrieval.schedule(units, cache, sources)
        for row in scheduled['neighborhoods']:
            pairs = [p for p in scheduled['pairs'] if p['id'] in row['pair_ids']]
            anchor = next(u for u in units if u['claim_id'] == row['anchor_unit_id'])
            sids = [p['premise_source_id'] for p in pairs]
            self.assertEqual(len(sids), len(set(sids)))
            self.assertNotIn(anchor['source_comment_id'], sids)

    def test_corrupt_vectors_binding_and_quote_rejected(self):
        units, cache, sources = self.population()
        for mutate in (lambda c: c['unit_ids'].reverse(), lambda c: c['vectors'].__setitem__(0, [0., 0.]),
                       lambda c: c['vectors'].__setitem__(0, [float('nan'), 0.]),
                       lambda c: c['embedding_texts'].__setitem__(0, 'changed')):
            changed = deepcopy(cache); mutate(changed)
            with self.assertRaises(ValueError): retrieval.schedule(units, changed, sources)
        with self.assertRaises(ValueError): retrieval.schedule(units, cache, {})

    def test_missing_or_bad_ranking_is_not_support(self):
        units, cache, sources = self.population(); schedule = retrieval.schedule(units, cache, sources)
        failed = self.result(schedule)
        for r in failed['rows']: r.update(errors=['timeout'], scores=None)
        ranked = retrieval.assemble(units, cache, sources, schedule, failed)
        self.assertEqual(ranked['proposals'], []); self.assertEqual(len(ranked['pair_errors']), len(schedule['pairs']))
        bad = self.result(schedule); bad['rows'].pop()
        with self.assertRaises(ValueError): retrieval.assemble(units, cache, sources, schedule, bad)
        bad = self.result(schedule); bad['rows'][0]['pair_sha256'] = 'changed'
        with self.assertRaises(ValueError): retrieval.assemble(units, cache, sources, schedule, bad)

    def test_budget_diversity_is_recorded_not_declared_semantic_equivalence(self):
        units, cache, sources = self.population(); schedule = retrieval.schedule(units, cache, sources)
        ranked = retrieval.assemble(units, cache, sources, schedule, self.result(schedule))
        self.assertTrue(any(d['reason'] == 'retrieval_diversity_budget' for d in ranked['deferred']))
        self.assertLessEqual(len(ranked['proposals']), 6)
        self.assertLessEqual(len(schedule['pairs']), 4*len(units))

    def test_original_reason_menu_and_full_context_not_range_enumeration(self):
        units, _, sources = self.population(); typer = UnitReasonTyping(units)
        menu = typer.inventory(sources); request = typer.invocation({'text': 'Reviews should be required.'}, sources)
        self.assertEqual(request['data']['MEMBER_SOURCES'], sources)
        self.assertEqual({x['text'] for x in menu.values()}, {u['reason_quote'] for u in units})
        for row in menu.values():
            self.assertEqual(row['source_sha256'], digest(sources[row['source_id']]))
        self.assertNotIn('Reviews should be required.', {x['text'] for x in menu.values()})
        self.assertNotIn('reference', request['data'])

    def test_typing_preserves_text_dependency_and_declared_fact(self):
        units, _, sources = self.population(); typer = UnitReasonTyping(units); rid = next(iter(typer.inventory(sources)))
        proposal = {'id': 'P', 'claims': {'C': {'id': 'C', 'text': 'Reviews should be required.',
            'kind': 'fact', 'scope': {'entity': 'general', 'time': '', 'conditions': ''}, 'requires': []}}, 'sources': sources}
        value = {'status': 'classified', 'kind': 'normative_preference', 'details': [
            {'reason_id': rid, 'kind': 'empirical_description', 'required_fact': True}]}
        typed = typer.apply(proposal, value, sources)
        self.assertEqual(typed['claims']['C']['text'], proposal['claims']['C']['text'])
        self.assertEqual(typed['claims']['C']['requires'], ['R1'])
        self.assertEqual(typed['claims']['R1']['text'], typer.inventory(sources)[rid]['text'])
        self.assertEqual(typed['claims']['R1']['kind'], 'fact')  # host never relabels model mistakes
        value['details'][0]['kind'] = 'future_expectation'
        with self.assertRaises(ValueError): typer.apply(proposal, value, sources)
        self.assertIsNone(typer.apply(proposal, {'status': 'defer', 'reason': 'missing_essential_ground'}, sources))

    def test_unknown_or_nonmember_reason_fails(self):
        units, _, sources = self.population(); typer = UnitReasonTyping(units)
        altered = deepcopy(units); altered[0]['reason_quote'] = 'Invented reason'
        with self.assertRaises(ValueError): UnitReasonTyping(altered).inventory(sources)
        subset = {'s0': sources['s0']}
        self.assertEqual(len(typer.inventory(subset)), 1)
        self.assertEqual(typer.inventory({}), {})


if __name__ == '__main__': unittest.main()
