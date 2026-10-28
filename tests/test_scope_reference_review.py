from copy import deepcopy
import unittest

from commentscope.factory import explicit_discourse as ed, literal_discovery as ld
from commentscope.factory import minimal_claims as mc, source_scope as ss, scope_reference_review as sr


def setup(text='Repair bridges. The process should be transparent.', phrase='bridges', parent=None):
    graph = ed.parse({'id': 's', 'text': text, 'parent': parent})
    node = ld.roots(graph)[-1]
    choice = next(c['id'] for c in ss.witness_choices(graph, node) if c['text'] == phrase)
    return graph, node, ss.bind(graph, node, {'output': {'R1': choice}})


def assemble(graph, node, certificate, review, *, version=ld.VERSION):
    ids = [n['id'] for n in ld.roots(graph)]
    batch = ld.bind_selection(graph, ids, {'output': {
        f'N{i}': {'role': 'topic_position', 'speaker': 'comment_author'}
        for i in range(1, len(ids)+1)}}, version=version)
    scope = {'node_id': node['id'], 'certificate': certificate}
    if version == ld.VERSION:
        scope['review'] = review
    return ld.assemble(graph, [batch], [scope], version=version)


class ReferenceFidelityTests(unittest.TestCase):
    def test_exact_object_span_is_not_automatically_an_equivalent_event_reference(self):
        g, n, cert = setup()
        req = sr.request(g, n, cert)
        self.assertEqual(req['data']['TARGET'], 'The process should be transparent.')
        self.assertEqual(req['data']['PROPOSED_TARGET'], 'bridges should be transparent.')
        self.assertEqual(req['data']['SUBSTITUTIONS'][0]['resolution']['span']['text'], 'bridges')
        review = sr.bind(g, n, cert, {'output': {'R1': 'different_referent'}})
        record = assemble(g, n, cert, review)
        self.assertEqual([c['text'] for c in record['claims']], ['Repair bridges.'])
        self.assertEqual(record['status'], 'partial')
        self.assertEqual(record['source']['text'], g['source']['text'])
        self.assertIn('reference_fidelity:R1:different_referent', record['holds'][0]['scope_projection']['holds'])
        self.assertFalse(record['semantic_approval'])
        mc.validate(record)

    def test_imperative_as_nominal_is_held_without_repairing_the_output(self):
        g, n, cert = setup(phrase='Repair bridges')
        review = sr.bind(g, n, cert, {'output': {'R1': 'not_nominal'}})
        p = sr.projection(g, n, cert, review)
        self.assertEqual(p['text'], 'Repair bridges should be transparent.')
        self.assertIn('reference_fidelity:R1:not_nominal', p['holds'])
        self.assertEqual(assemble(g, n, cert, review)['claims'][0]['text'], 'Repair bridges.')

    def test_missing_or_uncertain_review_does_not_approve_substitution(self):
        g, n, cert = setup()
        p = sr.projection(g, n, cert)
        self.assertIn('unreviewed_reference:R1', p['holds'])
        self.assertEqual(assemble(g, n, cert, None)['status'], 'partial')
        review = sr.bind(g, n, cert, {'output': {'R1': 'uncertain'}})
        self.assertIn('reference_fidelity:R1:uncertain', sr.projection(g, n, cert, review)['holds'])

    def test_valid_nominal_reference_keeps_both_literal_positions_and_review(self):
        g, n, cert = setup('Archives need funding. They should also be accessible.', 'Archives')
        review = sr.bind(g, n, cert, {'output': {'R1': 'same_nominal_referent'}})
        record = assemble(g, n, cert, review)
        self.assertEqual(record['status'], 'covered')
        self.assertEqual([c['text'] for c in record['claims']],
                         ['Archives need funding.', 'Archives should also be accessible.'])
        projection = record['claims'][1]['source_selections'][0]['scope_projection']
        self.assertEqual(projection['reference_review'], review)
        self.assertFalse(projection['semantic_approval'])
        mc.validate(record)

    def test_resolver_unresolved_requires_no_fidelity_call_or_false_approval(self):
        g, n, _ = setup()
        cert = ss.bind(g, n, {'output': {'R1': 'unresolved'}})
        self.assertIsNone(sr.request(g, n, cert))
        review = sr.bind(g, n, cert)
        self.assertEqual(review['response'], {})
        self.assertIn('unresolved_reference:R1', sr.projection(g, n, cert, review)['holds'])
        with self.assertRaises(ValueError):
            sr.bind(g, n, cert, {'output': {}})

    def test_missing_extra_unknown_or_failed_model_decisions_are_rejected(self):
        g, n, cert = setup()
        for value in ({}, {'R1': 'same_nominal_referent', 'R2': 'uncertain'}, {'R1': 'approved'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sr.bind(g, n, cert, {'output': value})
        with self.assertRaises(ValueError):
            sr.bind(g, n, cert, {'output': {'R1': 'same_nominal_referent'}, 'errors': ['failure']})

    def test_review_cannot_be_reused_after_source_or_selected_witness_changes(self):
        g, n, cert = setup()
        review = sr.bind(g, n, cert, {'output': {'R1': 'same_nominal_referent'}})
        _, _, other = setup(phrase='Repair bridges')
        with self.assertRaises(ValueError):
            sr.projection(g, n, other, review)
        changed, other_node, other_cert = setup(parent={'id': 'p', 'text': 'Different topic.'})
        with self.assertRaises(ValueError):
            sr.projection(changed, other_node, other_cert, review)

    def test_clearing_holds_or_changing_review_provenance_is_rejected(self):
        g, n, cert = setup()
        review = sr.bind(g, n, cert, {'output': {'R1': 'different_referent'}})
        changed = deepcopy(review); changed['failed_reference_ids'] = []
        with self.assertRaises(ValueError):
            sr.projection(g, n, cert, changed)
        record = assemble(g, n, cert, review)
        changed = deepcopy(record); changed['holds'] = []
        with self.assertRaises(ValueError):
            mc.validate(changed)

    def test_parent_context_never_becomes_replacement_assertion(self):
        g, n, cert = setup('This is too expensive.', 'Rail pricing',
                           {'id': 'p', 'text': 'Rail pricing will raise 42 million dollars.'})
        req = sr.request(g, n, cert)
        self.assertEqual(req['data']['PROPOSED_TARGET'], 'Rail pricing is too expensive.')
        self.assertTrue(req['data']['SUBSTITUTIONS'][0]['resolution']['context_only'])
        self.assertEqual(req['data']['ORIGINAL']['PARENT_CONTEXT_ONLY'], g['source']['parent'])
        self.assertNotIn('42 million', req['data']['PROPOSED_TARGET'])

    def test_legacy_replay_is_preserved_but_cannot_be_relabeled_as_new_contract(self):
        g, n, cert = setup()
        old = assemble(g, n, cert, None, version=ld.LEGACY)
        self.assertEqual(old['status'], 'covered')
        mc.validate(old)
        changed = deepcopy(old); changed['artifact_kind'] = ld.VERSION
        with self.assertRaises(ValueError):
            mc.validate(changed)


if __name__ == '__main__':
    unittest.main()
