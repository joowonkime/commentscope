from copy import deepcopy
import unittest

from commentscope.factory import scope_reference_review as sr, literal_discovery as ld
from commentscope.factory import source_scope as ss, minimal_claims as mc
import test_scope_reference_review as fixture


class ReferenceKindGuardTests(unittest.TestCase):
    def setUp(self):
        self.graph, self.node, self.cert = fixture.setup(
            'Archive checks should be mandatory. This rule should start tomorrow.',
            'Archive checks')

    def result(self, reference='rule_or_policy', replacement='activity_or_process',
               relation='same_nominal_referent'):
        return {'output': {'R1': {'reference_kind': reference,
                                 'replacement_kind': replacement, 'relation': relation,
                                 'basis': 'The rule and the activity it regulates have different referents.'}}}

    def bind(self, result):
        return sr.bind(self.graph, self.node, self.cert, result, protocol=sr.TYPED)

    def test_kind_mismatch_vetoes_positive_identity_without_erasing_source_positions(self):
        review = self.bind(self.result())
        self.assertEqual(review['response']['R1']['relation'], 'same_nominal_referent')
        self.assertEqual(review['failed_reference_ids'], ['R1'])
        projection = sr.projection(self.graph, self.node, self.cert, review)
        self.assertIn('reference_fidelity:R1:referent_kind_mismatch', projection['holds'])
        record = fixture.assemble(self.graph, self.node, self.cert, review)
        self.assertEqual([c['text'] for c in record['claims']], ['Archive checks should be mandatory.'])
        self.assertEqual(record['source']['text'], self.graph['source']['text'])
        self.assertEqual(record['status'], 'partial')
        self.assertIn('Archive checks should start tomorrow.', str(record['holds']))
        mc.validate(record)

    def test_valid_typed_nominal_substitution_preserves_both_positions(self):
        graph, node, cert = fixture.setup('Archives need funding. They should also be accessible.', 'Archives')
        result = self.result('other_nominal', 'other_nominal')
        result['output']['R1']['basis'] = 'They refers to the Archives explicitly named in this original.'
        review = sr.bind(graph, node, cert, result, protocol=sr.TYPED)
        record = fixture.assemble(graph, node, cert, review)
        self.assertFalse(review['failed_reference_ids'])
        self.assertEqual(record['status'], 'covered')
        self.assertEqual(len(record['claims']), 2)
        self.assertEqual(record['claims'][1]['text'], 'Archives should also be accessible.')
        mc.validate(record)

    def test_uncertain_kind_or_adverse_relation_cannot_become_approval(self):
        for result in (self.result('uncertain', 'rule_or_policy'),
                       self.result('rule_or_policy', 'uncertain'),
                       self.result('rule_or_policy', 'rule_or_policy', 'different_referent'),
                       self.result('other_nominal', 'other_nominal', 'not_nominal')):
            review = self.bind(result)
            self.assertEqual(review['failed_reference_ids'], ['R1'])
            self.assertTrue(sr.projection(self.graph, self.node, self.cert, review)['holds'])

    def test_incomplete_unknown_or_unbounded_declarations_are_rejected(self):
        for change in (lambda r: r['output']['R1'].pop('replacement_kind'),
                       lambda r: r['output']['R1'].update(reference_kind='approved'),
                       lambda r: r['output']['R1'].update(basis=' '),
                       lambda r: r['output']['R1'].update(basis=' '*240+'x'),
                       lambda r: r['output']['R1'].update(basis=None)):
            result = self.result(); change(result)
            with self.assertRaises(ValueError):
                self.bind(result)
        with self.assertRaises(ValueError):
            sr.request(self.graph, self.node, self.cert, protocol='unknown')

    def test_review_binding_protects_kind_guards_explanation_and_protocol(self):
        review = self.bind(self.result())
        with self.assertRaises(ValueError):
            sr.projection(self.graph, self.node, self.cert, [])
        for change in (lambda r: r.update(failed_reference_ids=[]),
                       lambda r: r['guards']['R1'].clear(),
                       lambda r: r['response']['R1'].update(basis='Changed explanation.'),
                       lambda r: r.update(protocol='unknown')):
            changed = deepcopy(review); change(changed)
            with self.assertRaises(ValueError):
                sr.projection(self.graph, self.node, self.cert, changed)
        changed_graph, node, cert = fixture.setup(
            'Archive checks should be mandatory. This rule should start tomorrow.',
            'Archive checks', parent={'id': 'p', 'text': 'Another context.'})
        with self.assertRaises(ValueError):
            sr.projection(changed_graph, node, cert, review)

    def test_unresolved_resolver_requires_no_paid_review_and_keeps_its_hold(self):
        cert = ss.bind(self.graph, self.node, {'output': {'R1': 'unresolved'}})
        self.assertIsNone(sr.request(self.graph, self.node, cert, protocol=sr.TYPED))
        review = sr.bind(self.graph, self.node, cert, protocol=sr.TYPED)
        self.assertEqual(review['response'], {})
        self.assertIn('unresolved_reference:R1', sr.projection(self.graph, self.node, cert, review)['holds'])

    def test_discovery_uses_typed_review_and_holds_mismatch_even_when_model_says_same(self):
        calls = []
        def work(stage, tasks, request, bind, size):
            req = request(tasks); calls.append((stage, req))
            if stage == 'literal-select':
                value = {t['id']: {'role': 'topic_position', 'speaker': 'comment_author'}
                         for t in req['data']['TARGETS']}
            elif stage == 'scope-reference':
                choice = next(c[0] for c in req['data']['WITNESS_CHOICES'] if c[2] == 'Archive checks')
                value = {'R1': choice}
            elif stage == 'scope-reference-fidelity':
                self.assertIn('reference_kind', str(req['schema']))
                value = self.result()['output']
            else:
                raise AssertionError(stage)
            return [bind(tasks, {'output': value})]
        record = ld.discover([self.graph['source']], work)[0]
        self.assertEqual([c['text'] for c in record['claims']], ['Archive checks should be mandatory.'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(record['status'], 'partial')
        mc.validate(record)
