from copy import deepcopy
import unittest

from commentscope.factory import argument_graph as graph, argument_paths as paths, candidate_completion as cc
from commentscope.factory.automatic_contract import digest
from tests.test_candidate_completion import argument


class ArgumentPathTests(unittest.TestCase):
    def test_reason_menu_excludes_positions_but_keeps_full_context(self):
        typed, sources, units = argument(); inventory = graph.inventory(units, sources)
        req = paths.select_request(typed['claims']['C'], sources, inventory)
        ids = req['data']['ELIGIBLE_REASON_IDS']
        self.assertEqual(ids, typed['selected_nodes']['node_ids'])
        self.assertEqual(req['data']['SOURCE_GRAPH'], inventory)
        self.assertEqual(req['data']['MEMBER_SOURCES'], sources)
        self.assertEqual(req['schema']['anyOf'][0]['properties']['node_ids']['items']['enum'], ids)
        position = next(k for k in inventory['nodes'] if k not in ids)
        with self.assertRaises(ValueError): paths.selection({'errors': [], 'output': {
            'status': 'selected', 'node_ids': [position], 'essential_node_ids': []}}, inventory)

    def test_self_loops_cannot_nominate_a_reason(self):
        typed, sources, units = argument()
        for unit in units: unit['reason_quote'] = unit['quote']
        inventory = graph.inventory(units, sources)
        self.assertEqual(paths.eligible(inventory), [])
        req = paths.select_request(typed['claims']['C'], sources, inventory)
        self.assertEqual(req['schema']['anyOf'][0]['properties']['node_ids']['maxItems'], 0)
        self.assertEqual(len(req['data']['SOURCE_GRAPH']['nodes']), 3)
        deferred = {'errors': [], 'output': {'status': 'defer', 'reason': 'missing_major_ground'}}
        self.assertEqual(paths.selection(deferred, inventory), deferred['output'])

    def test_position_may_be_reason_only_when_an_actual_nonself_link_exists(self):
        _, sources, units = argument(); copied = deepcopy(units[0])
        copied.update(claim_id='other-unit', quote=units[0]['reason_quote'], reason_quote=units[0]['quote'])
        inventory = graph.inventory(units+[copied], sources)
        self.assertEqual(len(paths.eligible(inventory)), 2)

    def test_contract_checked_again_at_audit_and_original_author_boundary(self):
        typed, sources, units = argument(); typed['ground_selection_contract'] = paths.VERSION
        self.assertEqual(cc.selected_graph(typed, sources, units), graph.inventory(units, sources))
        inventory = graph.inventory(units, sources)
        position = next(k for k in inventory['nodes'] if k not in paths.eligible(inventory))
        typed['selected_nodes'].update(node_ids=[position], essential_node_ids=[position])
        typed['claims']['R1']['text'] = inventory['nodes'][position]['text']
        typed['independent_node_kinds'] = {position: 'value'}
        with self.assertRaises(ValueError): cc.selected_graph(typed, sources, units)

    def test_no_text_rewrite_or_semantic_approval_is_added(self):
        typed, sources, units = argument(); before = digest([typed, sources, units])
        inventory = graph.inventory(units, sources)
        paths.select_request(typed['claims']['C'], sources, inventory)
        paths.selection({'errors': [], 'output': typed['selected_nodes']}, inventory)
        self.assertEqual(digest([typed, sources, units]), before)


if __name__ == '__main__': unittest.main()
