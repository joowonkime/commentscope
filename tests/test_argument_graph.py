from copy import deepcopy
import unittest
from unittest.mock import Mock

from commentscope.factory import argument_graph as graph, source_first, membership_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.scoped_discovery import judge_request
from experiments.argument_graph_probe import union_selections, members, profile, profile_capacity, allocate
from experiments.fresh_grounded_pipeline import source_rows
from tests.test_source_first import output


class ArgumentGraphTests(unittest.TestCase):
    def fixture(self):
        sources = {f's{i}': 'Reviews should be required. They could reduce errors.' for i in range(3)}
        units = []
        for sid, source in sources.items():
            value = output(source)
            value['claims'][0].update(claim='Reviews should be required.', quote='Reviews should be required.',
                reason='They could reduce errors.', reason_quote='They could reduce errors.')
            units.extend(source_first.bind(sid, source, {'errors': [], 'output': value})['units'])
        claim = {'id': 'C', 'text': 'Reviews should be required.', 'kind': 'fact',
                 'scope': {'entity': 'general', 'time': '', 'conditions': ''}, 'requires': []}
        proposal = {'id': 'P', 'claims': {'C': claim}, 'sources': sources}
        req = judge_request(sources['s0'], claim)
        policy = membership_policy.from_rows([{'text': sources['s0'], 'claim': claim, 'request': req, 'request_sha256': digest(req)}])
        rows = source_rows([proposal], policy)
        return units, proposal, policy, {'proposals': [proposal], 'rows': rows, 'actual': {r['id']: 'supported' for r in rows}}

    def selected(self, evidence, *, essential=True):
        nid = next(i for i, n in evidence['nodes'].items() if n['text'] == 'They could reduce errors.')
        return {'status': 'selected', 'node_ids': [nid], 'essential_node_ids': [nid] if essential else []}

    def result(self, value): return {'errors': [], 'output': value}

    def test_graph_keeps_position_nodes_and_original_direction_without_truth_approval(self):
        units, p, _, _ = self.fixture(); evidence = graph.inventory(units, p['sources'])
        self.assertEqual(len(evidence['nodes']), 6)
        for link in evidence['links']:
            self.assertEqual(evidence['nodes'][link['position_node_id']]['text'], 'Reviews should be required.')
            self.assertEqual(evidence['nodes'][link['reason_node_id']]['text'], 'They could reduce errors.')
            self.assertFalse(link['extraction_is_semantic_approval'])
        with self.assertRaises(ValueError): graph.inventory(units+[units[0]], p['sources'])
        changed = deepcopy(units); changed[0]['quote'] = 'Invented position'
        with self.assertRaises(ValueError): graph.inventory(changed, p['sources'])

    def test_selection_has_graph_and_full_context_but_no_type_or_prior_fact_outcome(self):
        units, p, _, _ = self.fixture(); evidence = graph.inventory(units, p['sources'])
        req = graph.select_request(p['claims']['C'], p['sources'], evidence)
        self.assertEqual(req['data']['SOURCE_GRAPH'], evidence)
        self.assertEqual(req['data']['MEMBER_SOURCES'], p['sources'])
        self.assertEqual(set(graph.type_request('Text', {'s': 'Context'})['data']), {'TARGET', 'SOURCES'})
        self.assertNotIn('expected', req['data']); self.assertNotIn('checks', req['data'])

    def test_type_is_a_single_enum_and_errors_are_not_repaired(self):
        for kind in graph.KINDS: self.assertEqual(graph.kind(self.result({'kind': kind})), kind)
        for result in ({'errors': ['timeout'], 'output': {'kind': 'prediction'}}, self.result({'kind': 'made_up'}),
                       self.result({'kind': 'value', 'text': 'rewritten'})):
            with self.assertRaises(ValueError): graph.kind(result)

    def test_unknown_duplicate_and_omitted_essential_nodes_rejected(self):
        units, p, _, _ = self.fixture(); evidence = graph.inventory(units, p['sources']); good = self.selected(evidence)
        self.assertEqual(graph.selection(self.result(good), evidence), good)
        for changed in ({**good, 'node_ids': []}, {**good, 'node_ids': good['node_ids']*2},
                        {**good, 'essential_node_ids': ['unknown']}):
            with self.assertRaises(ValueError): graph.selection(self.result(changed), evidence)

    def test_assembly_copies_quote_and_keeps_required_fact_without_new_truth(self):
        units, p, _, _ = self.fixture(); evidence = graph.inventory(units, p['sources']); selected = self.selected(evidence)
        nid = selected['node_ids'][0]
        for kind in ('fact', 'prediction'):
            typed = graph.assemble(p, p['sources'], units, 'value', selected, {nid: kind})
            self.assertEqual(typed['claims']['R1']['text'], evidence['nodes'][nid]['text'])
            self.assertEqual(typed['claims']['R1']['kind'], kind)
            self.assertEqual(typed['claims']['C']['requires'], ['R1'] if kind == 'fact' else [])
            self.assertEqual(typed['selected_nodes']['essential_node_ids'], [nid])
            self.assertNotIn('typing_request_sha256', typed)
        for kinds in ({}, {nid: 'mixed_or_unclear'}):
            with self.assertRaises(ValueError): graph.assemble(p, p['sources'], units, 'value', selected, kinds)

    def test_essential_nonfactual_ground_cannot_be_silently_omitted(self):
        units, p, _, _ = self.fixture(); evidence = graph.inventory(units, p['sources']); selected = self.selected(evidence)
        typed = graph.assemble(p, p['sources'], units, 'value', selected, {selected['node_ids'][0]: 'prediction'})
        rows = [{'id': 'D1', 'claim': {'id': 'P:R1'}}]
        kept, deferred = graph.admit([typed], rows, {'D1': 'unsupported'})
        self.assertEqual(kept, []); self.assertEqual(deferred[0]['id'], 'P')
        self.assertEqual(graph.admit([typed], rows, {'D1': 'supported'})[0], [typed])
        with self.assertRaises(ValueError): graph.admit([typed], rows, {})

    def test_full_profile_uses_separate_calls_and_keeps_core_members_unchanged(self):
        units, p, policy, selection = self.fixture(); evidence = graph.inventory(units, p['sources']); selected = self.selected(evidence)
        runner = Mock(); runner.call.side_effect = [self.result({'kind': 'value'}), self.result(selected), self.result({'kind': 'prediction'})]
        typed, deferred = profile(p, selection, units, policy, runner)
        self.assertIsNone(deferred); self.assertEqual(typed['claims']['C']['text'], p['claims']['C']['text'])
        self.assertEqual(typed['claims']['R1']['kind'], 'prediction')
        self.assertEqual([c.args[0] for c in runner.call.call_args_list], ['core-kind', 'argument-selection', 'ground-kind'])
        self.assertEqual(members(p, selection, policy), p['sources'])
        changed = deepcopy(selection); changed['rows'][0]['text'] = 'changed'
        with self.assertRaises(ValueError): members(p, changed, policy)

    def test_union_keeps_all_candidates_and_outcomes_not_review_selected_winners(self):
        _, _, _, left = self.fixture(); right = deepcopy(left)
        right['proposals'][0]['id'] = 'Q'
        for row in right['rows']: row['candidate_id'] = 'Q'
        union = union_selections(left, right)
        self.assertEqual([p['id'] for p in union['proposals']], ['P', 'Q'])
        self.assertEqual(len(union['rows']), 6); self.assertEqual(len(union['actual']), 6)
        with self.assertRaises(ValueError): union_selections(left, left)

    def test_capacity_changes_limits_not_semantic_inputs_or_membership_deployment(self):
        deployment = {'runtime': {'context': 4096, 'reasoning_budget': 256, 'gpu_layers': 32, 'seed': 407}, 'models': {'baseline': 'fixed'}}
        before = deepcopy(deployment); expanded, extra = profile_capacity(deployment, 'expanded')
        self.assertEqual(deployment, before)
        self.assertEqual(expanded['runtime'], {**before['runtime'], 'context': 8192, 'reasoning_budget': 1024})
        self.assertEqual(extra, 768)
        req = graph.type_request('A claim.', {'s': 'Original source.'}); changed = allocate(req, extra)
        self.assertEqual(changed['max_tokens'], 1152)
        for key in ('system', 'data', 'schema'): self.assertEqual(req[key], changed[key])
        self.assertEqual(allocate(req, 0), req)
        for invalid in (-1, 1, True, 100000):
            with self.assertRaises(ValueError): allocate(req, invalid)

    def test_expanded_profile_records_actual_request_hashes(self):
        units, p, policy, selection = self.fixture(); evidence = graph.inventory(units, p['sources']); selected = self.selected(evidence)
        runner = Mock(); runner.call.side_effect = [self.result({'kind': 'value'}), self.result(selected), self.result({'kind': 'prediction'})]
        typed, _ = profile(p, selection, units, policy, runner, extra_tokens=768)
        calls = runner.call.call_args_list
        self.assertEqual([c.args[1]['max_tokens'] for c in calls], [1152, 1280, 1152])
        self.assertEqual(typed['decision_request_hashes']['core_type'], digest(calls[0].args[1]))
        self.assertEqual(typed['decision_request_hashes']['argument_selection'], digest(calls[1].args[1]))


if __name__ == '__main__': unittest.main()
