from copy import deepcopy
import unittest

from commentscope.factory import shared_owned_positions as ownership, shared_claims
from commentscope.factory import owned_arguments as oa, explicit_discourse as ed
from test_minimal_factory import membership


class SharedOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'teacher', 'text': 'I would keep working as a teacher under UBI because helping students matters.', 'parent': None}
        other = {'id': 'other', 'text': 'I would keep working under UBI.', 'parent': None}
        proposal = shared_claims.bind([self.source, other], {'output': {'candidates': [
            {'text': 'Some people would keep working under UBI.', 'nominees': ['A0', 'A1']}]}}, version=shared_claims.COMMON)
        self.candidate, = shared_claims.candidates([proposal])
        self.graph = ed.parse(self.source)
        self.root = next(n for n in self.graph['nodes'] if n['kind'] == 'statement')

    def decision(self, graph=None, node=None, **changes):
        graph = graph or self.graph; node = node or self.root
        return {'relation': 'supports_core', **{k: 'yes' for k in ownership.CHECKS},
                'conditions': [{'node_id': c['node_id'], 'status': 'preserved'}
                               for c in ownership.condition_inventory(graph, node)], **changes}

    def metadata(self):
        result = []
        for node in self.graph['nodes']:
            props = oa.metadata_request(self.graph, node)['schema']['properties']
            values = {'authorship': 'asserted_or_endorsed', 'kind': 'prediction',
                      'entity': 'the author', 'time_ids': [], 'source_language': 'en'}
            result.append(oa.bind_metadata(self.graph, node, {'output': {k: values[k] for k in props}}))
        return result

    def test_directional_proof_keeps_personal_position_and_own_reason_without_equivalence(self):
        proof = ownership.bind(self.graph, self.root, self.candidate, {'output': self.decision()})
        self.assertEqual(proof['relation'], 'supports_core')
        self.assertFalse(proof['semantic_approval'])
        members = [membership([self.source], [self.candidate], [
            {'source_id': self.source['id'], 'candidate_id': self.candidate['id']}])]
        record = oa.declare(self.graph, [self.candidate], members, self.metadata(), [proof])
        oa.validate(record)
        self.assertEqual(record['status'], 'complete')
        self.assertEqual(record['units'][0]['text'], self.root['span']['text'])
        reason = next(u for u in record['units'] if u['role'] == 'reason')
        self.assertEqual(reason['text'], 'because helping students matters.')
        self.assertEqual(reason['candidate_ids'], [self.candidate['id']])
        self.assertEqual(record['ownership_proofs'][0]['position']['span'], self.root['span'])

    def test_scope_commitment_and_modality_failures_hold_positive_declarations(self):
        for check in ownership.CHECKS:
            proof = ownership.bind(self.graph, self.root, self.candidate,
                {'output': self.decision(**{check: 'no'})})
            with self.subTest(check=check):
                self.assertEqual(proof['relation'], 'uncertain')
                self.assertIn(check+'_unapproved', proof['guards'])

    def test_essential_condition_checks_are_complete_and_cannot_be_erased(self):
        graph = ed.parse({'id': 'conditional', 'text': 'Adopt P only if fees are waived.', 'parent': None})
        root = next(n for n in graph['nodes'] if n['kind'] == 'statement')
        output = self.decision(graph, root)
        self.assertTrue(output['conditions'])
        output['conditions'][0]['status'] = 'missing_or_changed'
        proof = ownership.bind(graph, root, self.candidate, {'output': output})
        self.assertEqual(proof['relation'], 'uncertain')
        output['conditions'] = []
        with self.assertRaises(ValueError): ownership.bind(graph, root, self.candidate, {'output': output})

    def test_other_node_source_and_candidate_cannot_reuse_proof(self):
        proof = ownership.bind(self.graph, self.root, self.candidate, {'output': self.decision()})
        for key in ('graph_sha256', 'node_id', 'candidate_sha256'):
            changed = deepcopy(proof); changed[key] = 'different'
            with self.subTest(key=key), self.assertRaises(ValueError):
                ownership.validate(self.graph, self.root, self.candidate, changed)
        reason = next(n for n in self.graph['nodes'] if n['id'] != self.root['id'])
        with self.assertRaises(ValueError): ownership.request(self.graph, reason, self.candidate)


if __name__ == '__main__': unittest.main()
