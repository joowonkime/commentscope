from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from commentscope.factory import candidate_completion as cc, argument_graph as graph, source_first
from commentscope.factory.target_ranking import target
from commentscope.factory.automatic_contract import digest
from tests.test_source_first import output
from tests import test_fresh_grounded_pipeline as fresh_tests


def argument(core='Reviews should be mandatory.', reason='Safety matters more than speed.'):
    sources = {f's{i}': core+' '+(reason if i == 0 else f' Context {i}.') for i in range(3)}
    units = []
    for sid, text in sources.items():
        value = output(core)
        if sid == 's0': value['claims'][0].update(reason=reason, reason_quote=reason)
        units.extend(source_first.bind(sid, text, {'errors': [], 'output': value})['units'])
    p = {'id': 'P', 'claims': {'C': target(units[0])}, 'sources': sources,
         'anchor_unit_id': units[0]['claim_id'], 'candidate_unit_ids': [u['claim_id'] for u in units]}
    inventory = graph.inventory(units, sources)
    nid = next(k for k, v in inventory['nodes'].items() if v['text'] == reason)
    typed = graph.assemble(p, sources, units, 'value',
        {'status': 'selected', 'node_ids': [nid], 'essential_node_ids': [nid]}, {nid: 'value'})
    return typed, sources, units


class CandidateCompletionTests(unittest.TestCase):
    def test_candidate_slot_reserved_before_start_and_failures_never_retry(self):
        now = [0.]
        runner = SimpleNamespace(clock=lambda: now[0], started=0., plan={'limits': {'analysis_seconds': 3600}}, budget=Mock())
        runner.budget.summary.return_value = {'remaining_seconds': 10000}
        allocation = cc.Allocation(runner)
        now[0] = 2900
        self.assertTrue(allocation.begin('A')); self.assertEqual(allocation.timeout(90), 90)
        with self.assertRaises(ValueError): allocation.begin('B')
        now[0] = 3438
        with self.assertRaises(TimeoutError): allocation.timeout(90)
        allocation.finish('failed')
        with self.assertRaises(ValueError): allocation.begin('A')
        self.assertFalse(allocation.begin('B'))
        self.assertEqual(allocation.attempts[0]['state'], 'failed')

    def test_cycle_allowance_and_attempt_cap_are_not_reset_by_fast_failures(self):
        runner = SimpleNamespace(clock=lambda: 0., started=0., plan={'limits': {'analysis_seconds': 3600}}, budget=Mock())
        runner.budget.summary.return_value = {'remaining_seconds': 599}
        allocation = cc.Allocation(runner); self.assertFalse(allocation.begin('A'))
        runner.budget.summary.return_value = {'remaining_seconds': 9000}
        for i in range(cc.MAX_ATTEMPTS):
            self.assertTrue(allocation.begin(str(i))); allocation.finish('failed')
        self.assertFalse(allocation.begin('next'))

    def test_reason_membership_is_original_author_only_with_full_source(self):
        typed, sources, units = argument(); policy = fresh_tests.FreshGroundedPipelineTests().policy()
        rows = cc.origin_details(typed, sources, units, policy)
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['source_id'], 's0')
        self.assertEqual(rows[0]['text'], sources['s0'])
        self.assertEqual(rows[0]['claim']['text'], 'Safety matters more than speed.')
        typed['claims']['R1']['text'] = 'Invented replacement'
        with self.assertRaises(ValueError): cc.origin_details(typed, sources, units, policy)

    def test_audit_rejects_reversed_role_changed_type_missing_premise_and_error(self):
        typed, sources, units = argument(); nid = typed['selected_nodes']['node_ids'][0]
        valid = {'core_fidelity': 'faithful', 'core_kind_matches': True,
                 'grounds': [{'node_id': nid, 'role': 'reason_for_core', 'kind_matches': True}], 'major_premises': 'preserved'}
        req = cc.audit_request(typed, sources, units)
        self.assertEqual(req['data']['MEMBER_SOURCES'], sources)
        self.assertTrue(cc.audit_passed(typed, {'output': valid, 'errors': []}))
        for mutate in (lambda v: v.update(core_fidelity='distorted'), lambda v: v.update(core_kind_matches=False),
                       lambda v: v.update(major_premises='missing'), lambda v: v['grounds'][0].update(role='response_or_consequence'),
                       lambda v: v['grounds'][0].update(kind_matches=False), lambda v: v['grounds'].clear(),
                       lambda v: v['grounds'][0].update(node_id='invented')):
            changed = deepcopy(valid); mutate(changed)
            self.assertFalse(cc.audit_passed(typed, {'output': changed, 'errors': []}))
        self.assertFalse(cc.audit_passed(typed, {'output': valid, 'errors': ['timeout']}))

    def test_one_source_can_nominate_but_not_approve_a_perspective(self):
        typed, sources, units = argument(); units = units[:1]
        self.assertEqual(source_first.candidates(units, [[1., 0.]], sources)['proposals'], [])
        result = source_first.candidates(units, [[1., 0.]], sources, minimum_sources=1)
        self.assertEqual(len(result['proposals']), 1)
        self.assertFalse(result['proposals'][0]['semantic_approval']); self.assertFalse(result['quality_gate_passed'])
        with self.assertRaises(ValueError): source_first.candidates(units, [[1., 0.]], sources, minimum_sources=2)

    def test_queue_merges_only_exact_targets_and_uses_no_membership_labels(self):
        typed, sources, units = argument()
        p = {'id': 'A', 'claims': {'C': target(units[0])}, 'sources': sources,
             'anchor_unit_id': units[0]['claim_id'], 'candidate_unit_ids': [u['claim_id'] for u in units]}
        q = {**deepcopy(p), 'id': 'B'}
        broad = {'rankings': [{'candidate_id': pid, 'rows': [{'source_id': 's0', 'ranking_score': .9}]} for pid in ['A', 'B']]}
        result = cc.queue([p, q], broad, {'proposals': [p, q]})
        self.assertEqual(len(result), 1); self.assertEqual(result[0]['retrieval_candidate_ids'], ['A', 'B'])
        self.assertFalse(result[0]['membership_approval'])
        q['claims']['C']['text'] = 'Reviews should be voluntary.'
        self.assertEqual(len(cc.queue([p, q], broad, {'proposals': [p, q]})), 2)
        with self.assertRaises(ValueError): cc.queue([p], broad, {'proposals': [p]})


if __name__ == '__main__': unittest.main()
