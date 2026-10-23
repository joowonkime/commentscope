from copy import deepcopy
import unittest

from commentscope.factory import typed_interpretation as ti


def source(text, sid='A', parent=None):
    return {'id': sid, 'text': text, 'parent': parent}


def claim(quote, sid='S1', **changes):
    return {'id': sid, 'quote': quote, 'occurrence': 1, 'meaning': quote,
            'voice': 'author', 'force': 'assertion', 'world': 'actual', **changes}


def link(quote, target='S1', kind='reason', origin='comment', **changes):
    return {'statement_id': target, 'kind': kind, 'origin': origin,
            'quote': quote, 'occurrence': 1, **changes}


def output(claims, links=(), sid='A'):
    return {'id': sid, 'relevance': 'substantive', 'coverage': 'complete',
            'statements': claims, 'attachments': list(links), 'unresolved': []}


class TypedInterpretationTests(unittest.TestCase):
    def test_different_reasons_do_not_change_shared_claim_or_get_pooled(self):
        records = [ti.bind(source('Open earlier because ' + reason + '.', sid),
            output([claim('Open earlier')], [link('because ' + reason + '.')], sid))
            for sid, reason in [('A', 'commuters arrive early'), ('B', 'it reduces queues')]]
        views = [ti.comparison_view(r, 'S1') for r in records]
        self.assertEqual(views[0]['statement']['quote'], views[1]['statement']['quote'])
        self.assertTrue(all(not v['scope'] for v in views))
        self.assertNotEqual(ti.owned_reasons(records[0], 'S1'), ti.owned_reasons(records[1], 'S1'))
        self.assertTrue(all(ti.owned_reasons(r, 'S1')[0]['surface_edge_id'] for r in records))
        self.assertTrue(all(not v['membership_approved'] for v in views))

    def test_claim_and_fragments_cannot_be_self_reasons(self):
        s = source('The service is good.')
        for quote in ('The service is good.', 'service is good', 'good'):
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, 'own reason'):
                ti.bind(s, output([claim(s['text'])], [link(quote)]))

    def test_setting_is_not_returned_as_reason_even_for_fictional_claims(self):
        s = source('In the novel. Everyone can fly.')
        r = ti.bind(s, output([claim('Everyone can fly.', world='fictional')],
            [link('In the novel.', kind='setting')]))
        self.assertEqual(ti.owned_reasons(r, 'S1'), [])
        self.assertEqual(ti.comparison_view(r, 'S1')['scope'][0]['kind'], 'setting')

    def test_mislabelled_setting_is_held_not_semantically_approved(self):
        s = source('In the novel. Everyone can fly.')
        r = ti.bind(s, output([claim('Everyone can fly.', world='fictional')],
            [link('In the novel.')]))
        a = ti.owned_reasons(r, 'S1')[0]
        self.assertEqual(a['verification'], 'pending_semantic_review')
        self.assertFalse(a['semantic_approval'])
        self.assertFalse(r['quality_gate_passed'])

    def test_parent_can_resolve_context_but_cannot_donate_reasons(self):
        s = source('Deal with it', parent={'id': 'P', 'text': 'The delays are sad.'})
        for kind in ('reason', 'condition', 'concession'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ti.bind(s, output([claim(s['text'])], [link('delays', kind=kind, origin='parent')]))
        r = ti.bind(s, output([claim(s['text'])], [link('delays', kind='referent', origin='parent')]))
        self.assertEqual(ti.comparison_view(r, 'S1')['scope'][0]['origin'], 'parent')

    def test_complete_condition_must_stay_with_proposition(self):
        s = source('I agree only if all shifts are covered.')
        a = link('only if all shifts are covered.', kind='condition')
        r = ti.bind(s, output([claim(s['text'], world='conditional')], [a]))
        self.assertEqual(ti.comparison_view(r, 'S1')['statement']['quote'], s['text'])
        with self.assertRaisesRegex(ValueError, 'complete proposition'):
            ti.bind(s, output([claim('I agree')], [a]))

    def test_explicit_reason_cannot_move_to_different_claim(self):
        s = source('Preserve the archive. Open on Sunday because weekdays are busy.')
        claims = [claim('Preserve the archive.'), claim('Open on Sunday', 'S2')]
        ti.bind(s, output(claims, [link('because weekdays are busy.', 'S2')]))
        for quote in ('because weekdays are busy.', 'weekdays are busy'):
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, 'ownership'):
                ti.bind(s, output(claims, [link(quote)]))

    def test_repeated_text_has_explicit_occurrence(self):
        s = source('Yes. Yes.')
        r = ti.bind(s, output([claim('Yes.', occurrence=2)]))
        self.assertEqual(r['statements'][0]['span']['start'], 5)
        for occurrence in (0, 3, True, 1.0):
            with self.subTest(occurrence=occurrence), self.assertRaises(ValueError):
                ti.bind(s, output([claim('Yes.', occurrence=occurrence)]))

    def test_fabricated_quote_and_cross_source_target_rejected(self):
        s = source('Use trains. Buses are crowded.')
        with self.assertRaises(ValueError):
            ti.bind(s, output([claim('Use buses.')]))
        with self.assertRaises(ValueError):
            ti.bind(s, output([claim('Use trains.')], [link('Buses are crowded.', target='B.S1')]))

    def test_mutated_source_or_reason_owner_or_approval_fails_replay(self):
        s = source('Use buses because air quality matters.')
        r = ti.bind(s, output([claim('Use buses')], [link('because air quality matters.')]))
        for mutate in (lambda x: x['source'].update(text='Changed.'),
                       lambda x: x['attachments'][0].update(statement_id='S2'),
                       lambda x: x.update(semantic_approval=True),
                       lambda x: x['statements'][0].update(world='fictional')):
            changed = deepcopy(r); mutate(changed)
            with self.assertRaises(ValueError):
                ti.validate(changed)

    def test_source_failure_isolation_and_missing_duplicate_identity_holds(self):
        sources = [source('A.', 'A'), source('B.', 'B')]
        a = output([claim('A.')]); b = output([claim('B.')], sid='B')
        bad = deepcopy(a); bad['statements'][0]['quote'] = 'invented'
        for cases in ([bad, b], [a, a, b], [b]):
            r = ti.bind_batch(sources, {'cases': cases})
            self.assertEqual([x['source']['id'] for x in r['records']], ['B'])
            self.assertEqual([x['id'] for x in r['errors']], ['A'])
            self.assertEqual(r['counted_supports'], 0)

    def test_generic_contract_has_no_policy_field_and_never_claims_coverage_proof(self):
        for topic in ('garden', 'station', 'museum'):
            s = source('If it is free, I will visit the ' + topic + '.')
            r = ti.bind(s, output([claim(s['text'], world='conditional', force='hypothetical')]))
            self.assertFalse(r['coverage_verified']); self.assertFalse(r['factual_verification'])
            self.assertNotIn('ubi_adoption_position', ti.request([s])['prompt'])

    def test_whole_because_quote_is_split_by_code_without_losing_fiction_or_original(self):
        s = source('In the novel. People study because they want to.')
        raw = output([claim('People study because they want to.', world='fictional')],
                     [link('In the novel.', kind='setting')])
        r = ti.bind(s, raw)
        view = ti.comparison_view(r, 'S1'); reasons = ti.owned_reasons(r, 'S1')
        self.assertEqual(view['position_span']['text'], 'People study')
        self.assertEqual(view['statement']['quote'], raw['statements'][0]['quote'])
        self.assertEqual(view['statement']['world'], 'fictional')
        self.assertEqual(view['scope'][0]['kind'], 'setting')
        self.assertEqual([g['quote'] for g in reasons], ['because they want to.'])
        self.assertFalse(reasons[0]['semantic_approval']); self.assertEqual(r['output'], raw)

    def test_whole_quotes_with_different_reasons_have_same_surface_position(self):
        records = [ti.bind(source('Use trains because ' + reason + '.'),
            output([claim('Use trains because ' + reason + '.')]))
            for reason in ('parking is scarce', 'roads are crowded')]
        self.assertEqual([ti.comparison_view(r, 'S1')['position_span']['text'] for r in records],
                         ['Use trains', 'Use trains'])
        self.assertNotEqual(ti.owned_reasons(records[0], 'S1'), ti.owned_reasons(records[1], 'S1'))

    def test_unknown_or_ambiguous_syntax_is_not_projected_and_reasons_not_duplicated(self):
        for text in ('Use trains since parking is scarce.',
                     'Use trains not because parking is scarce but because roads are crowded.',
                     'Use trains because parking is scarce only if there is an event.'):
            r = ti.bind(source(text), output([claim(text)]))
            self.assertEqual(ti.comparison_view(r, 'S1')['position_span']['text'], text)
            self.assertEqual(ti.owned_reasons(r, 'S1'), [])
        r = ti.bind(source('Use trains because parking is scarce.'),
                    output([claim('Use trains')], [link('because parking is scarce.')]))
        self.assertEqual(len(ti.owned_reasons(r, 'S1')), 1)


if __name__ == '__main__':
    unittest.main()
