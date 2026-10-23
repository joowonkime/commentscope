from copy import deepcopy
from dataclasses import replace
import unittest

from commentscope.factory import batch_stances as b, batched_corpus as corpus
from commentscope.factory.automatic_contract import digest
from commentscope.factory.framed_corpus import sources
from experiments.framed_cluster_controls import synthetic_snapshot, TARGET


def proposal(packets, *, non_substantive=()):
    originals = b.discovery_request(packets)['data']['ORIGINALS']
    nominees = [key for key, p in originals.items() if p['id'] not in non_substantive]
    value = {'candidates': [{'contract': deepcopy(TARGET), 'nominees': nominees}] if nominees else [],
             'sources': [{'source_key': key, 'state': 'covered' if key in nominees else 'non_substantive'}
                         for key in originals]}
    return {'errors': [], 'output': value}


def judgments(packets, candidates, pairs):
    return {'errors': [], 'output': {'decisions': [
        {'pair_id': f'P{i}', 'relation': {'D': 'conditional', 'E': 'opposed', 'F': 'unrelated'}.get(p['source_id'], 'supported'),
         'authorship': 'asserted_or_endorsed', 'scope_preserved': 'yes', 'evidence_segment_ids': ['S000']}
        for i, p in enumerate(pairs)]}}


class BatchStanceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = synthetic_snapshot(); self.packets = list(sources(self.snapshot).values())
        self.discovery = b.bind_discovery(self.packets, proposal(self.packets))
        self.candidates = b.candidates_from(self.packets, [self.discovery])
        self.pairs = [{'source_id': p['id'], 'candidate_id': self.candidates[0]['id']} for p in self.packets]

    def admission(self, result=None):
        return b.bind_membership(self.packets, self.candidates, self.pairs,
                                 result or judgments(self.packets, self.candidates, self.pairs))

    def test_no_frames_and_no_votes_from_nominations(self):
        request = b.discovery_request(self.packets)
        self.assertEqual(set(request['data']), {'ORIGINALS'})
        self.assertEqual(request['data']['ORIGINALS']['S0']['text'], self.packets[0]['text'])
        mapped = b.assemble_map(self.snapshot, [self.discovery], self.candidates, [])
        p = mapped['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts']['supported'], 0)
        self.assertEqual(p['counts']['unassessed'], 6)
        self.assertNotIn('frame_sha256', self.candidates[0])

    def test_batch_request_not_fabricated_single_call_is_bound(self):
        bound = self.admission()
        request = b.membership_request(self.packets, self.candidates, self.pairs)
        self.assertEqual(bound['request_sha256'], digest(request))
        self.assertEqual(len(request['data']['ORIGINALS']), 6)
        self.assertEqual(len(request['data']['CANDIDATES']), 1)
        mapped = b.assemble_map(self.snapshot, [self.discovery], self.candidates, [bound])
        p = mapped['opinion_map']['perspectives'][0]
        self.assertEqual(p['supported_canonical_ids'], ['A', 'B', 'C'])
        self.assertEqual(p['counts'], {'supported': 3, 'conditional': 1, 'not_supported': 2, 'uncertain': 0, 'unassessed': 0})
        self.assertFalse(mapped['quality_gate_passed'])
        for m in mapped['memberships']:
            self.assertEqual(m['batch_sha256'], digest(bound))
            self.assertNotIn('request_sha256', m)

    def test_unknown_duplicate_and_missing_dispositions_rejected(self):
        for mutation in ('missing', 'duplicate', 'unknown', 'contradiction'):
            with self.subTest(mutation=mutation):
                result = proposal(self.packets); states = result['output']['sources']
                if mutation == 'missing': states.pop()
                elif mutation == 'duplicate': states[-1] = deepcopy(states[0])
                elif mutation == 'unknown': states[-1]['source_key'] = 'foreign'
                else: states[0]['state'] = 'non_substantive'
                with self.assertRaises(ValueError): b.bind_discovery(self.packets, result)

    def test_candidate_contract_and_nomination_capacity_checked(self):
        for mutation in ('unknown', 'duplicate', 'empty', 'duplicate_contract', 'overflow', 'contract'):
            with self.subTest(mutation=mutation):
                result = proposal(self.packets); c = result['output']['candidates'][0]
                if mutation == 'unknown': c['nominees'].append('foreign')
                elif mutation == 'duplicate': c['nominees'].append(c['nominees'][0])
                elif mutation == 'empty': c['nominees'] = []
                elif mutation == 'duplicate_contract': result['output']['candidates'].append(deepcopy(c))
                elif mutation == 'overflow': result['output']['candidates'] *= 17
                else: c['contract']['conditions'] = 'x'*400
                with self.assertRaises(ValueError): b.bind_discovery(self.packets, result)

    def test_exact_only_merge_and_minority_preservation(self):
        first = b.bind_discovery(self.packets[:3], proposal(self.packets[:3]))
        second = b.bind_discovery(self.packets[3:], proposal(self.packets[3:]))
        merged = b.candidates_from(self.packets, [first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['nominee_source_ids'], ['A', 'B', 'C', 'D', 'E', 'F'])
        self.assertEqual(len(merged[0]['discovery_refs']), 2)
        value = proposal(self.packets[3:]); value['output']['candidates'][0]['contract']['conditions'] = 'Only if fees are waived'
        different = b.bind_discovery(self.packets[3:], value)
        self.assertEqual(len(b.candidates_from(self.packets, [first, different])), 2)
        singleton = b.bind_discovery(self.packets[:1], proposal(self.packets[:1]))
        self.assertEqual(b.candidates_from(self.packets, [singleton])[0]['nominee_source_ids'], ['A'])

    def test_original_parent_and_discovery_provenance_are_replayed(self):
        for mutation in ('text', 'parent', 'request', 'candidate'):
            with self.subTest(mutation=mutation):
                packets = deepcopy(self.packets); record = deepcopy(self.discovery); candidates = deepcopy(self.candidates)
                if mutation == 'text': packets[0]['text'] += ' But only conditionally.'
                elif mutation == 'parent': packets[0]['parent'] = {'id': 'other', 'text': 'Context changed.'}
                elif mutation == 'request': record['request_sha256'] = '0'*64
                else: candidates[0]['discovery_refs'] = ['0'*64]
                with self.assertRaises(ValueError):
                    if mutation == 'candidate': b.assemble_map(self.snapshot, [record], candidates, [])
                    else: b.candidates_from(packets, [record])

    def test_authorship_and_scope_fail_closed(self):
        result = judgments(self.packets, self.candidates, self.pairs)
        result['output']['decisions'][0]['authorship'] = 'not_asserted'
        result['output']['decisions'][1]['scope_preserved'] = 'no'
        bound = self.admission(result)
        self.assertEqual([m['relation'] for m in bound['memberships'][:3]], ['uncertain', 'uncertain', 'supported'])
        self.assertEqual(bound['memberships'][0]['guards'], ['authorship_unresolved'])

    def test_missing_duplicate_unknown_and_foreign_evidence_reject_batch(self):
        for mutation in ('missing', 'duplicate', 'unknown', 'foreign_segment', 'no_evidence', 'bad_relation', 'extra_field'):
            with self.subTest(mutation=mutation):
                result = judgments(self.packets, self.candidates, self.pairs); rows = result['output']['decisions']
                if mutation == 'missing': rows.pop()
                elif mutation == 'duplicate': rows[-1] = deepcopy(rows[0])
                elif mutation == 'unknown': rows[0]['pair_id'] = 'P999'
                elif mutation == 'foreign_segment': rows[1]['evidence_segment_ids'] = ['S001']  # B has only one segment.
                elif mutation == 'no_evidence': rows[0]['evidence_segment_ids'] = []
                elif mutation == 'bad_relation': rows[0]['relation'] = 'yes'
                else: rows[0]['reason'] = 'not in contract'
                with self.assertRaises(ValueError): self.admission(result)

    def test_batch_tampering_rejected_and_pair_not_counted_twice(self):
        for mutation in ('request', 'membership', 'pair'):
            with self.subTest(mutation=mutation):
                bound = self.admission()
                if mutation == 'request': bound['request_sha256'] = '0'*64
                elif mutation == 'membership': bound['memberships'][0]['relation'] = 'unrelated'
                else: bound['pairs'][0]['source_id'] = 'foreign'
                with self.assertRaises(ValueError): b.assemble_map(self.snapshot, [self.discovery], self.candidates, [bound])
        bound = self.admission()
        with self.assertRaises(ValueError): b.assemble_map(self.snapshot, [self.discovery], self.candidates, [bound, bound])

    def test_duplicate_source_candidate_pair_and_failed_response_rejected(self):
        with self.assertRaises(ValueError): b.discovery_request([*self.packets, self.packets[0]])
        with self.assertRaises(ValueError): b.membership_request(self.packets, self.candidates*2, self.pairs)
        with self.assertRaises(ValueError): b.membership_request(self.packets, self.candidates, [self.pairs[0]]*2)
        failed = judgments(self.packets, self.candidates, self.pairs); failed['errors'] = ['truncated']
        with self.assertRaises(ValueError): self.admission(failed)
        failed = proposal(self.packets); failed['errors'] = ['truncated']
        with self.assertRaises(ValueError): b.bind_discovery(self.packets, failed)

    def test_parent_is_context_only_and_complete_originals_survive(self):
        changed = replace(self.snapshot, comments=tuple(replace(c, parent_id='A') if c.comment_id == 'B' else c
                                                       for c in self.snapshot.comments))
        packets = list(sources(changed).values())
        request = b.membership_request(packets, self.candidates, self.pairs)
        parent = request['data']['ORIGINALS']['S1']['PARENT_CONTEXT']
        self.assertEqual(parent['id'], 'A'); self.assertEqual(parent['text'], self.packets[0]['text'])
        self.assertNotIn('nominee_source_ids', str(request['data']))
        self.assertNotIn('reference', request['data'])

    def test_request_is_detached_and_input_objects_are_unchanged(self):
        before = deepcopy((self.packets, self.candidates, self.pairs, self.discovery))
        bound = self.admission()
        b.assemble_map(self.snapshot, [self.discovery], self.candidates, [bound])
        request = b.membership_request(self.packets, self.candidates, self.pairs)
        request['data']['CANDIDATES']['C0']['conditions'] = 'Changed by caller'
        request['data']['ORIGINALS']['S0']['ORIGINAL_SEGMENTS'][0]['text'] = 'Changed by caller'
        self.assertEqual((self.packets, self.candidates, self.pairs, self.discovery), before)


class FakeRunner:
    def __init__(self, *, fail_discovery=False, fail_admission=False, non_substantive=()):
        self.calls = []; self.fail_discovery = fail_discovery; self.fail_admission = fail_admission
        self.non_substantive = non_substantive

    def call(self, stage, request):
        self.calls.append((stage, deepcopy(request)))
        if stage.startswith('discovery-'):
            if self.fail_discovery: return {'errors': ['failed'], 'output': None}
            return proposal(list(request['data']['ORIGINALS'].values()), non_substantive=self.non_substantive)
        if self.fail_admission: return {'errors': ['failed'], 'output': None}
        rows = []
        originals = request['data']['ORIGINALS']
        for pair in request['data']['PAIRS']:
            text = ' '.join(p['text'] for p in originals[pair['source_key']]['ORIGINAL_SEGMENTS'])
            relation = ('conditional' if 'fee waivers' in text else 'opposed' if 'remain voluntary' in text
                        else 'unrelated' if 'blind residents' in text else 'supported')
            rows.append({'pair_id': pair['pair_id'], 'relation': relation, 'authorship': 'asserted_or_endorsed',
                         'scope_preserved': 'yes', 'evidence_segment_ids': ['S000']})
        return {'errors': [], 'output': {'decisions': rows}}


class BatchedCorpusTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = synthetic_snapshot(); self.embeddings = []; self.saved = {}

    def embed(self, stage, texts):
        self.embeddings.append((stage, deepcopy(texts)))
        return {sid: [1., 0.] for sid in texts}

    def execute(self, **kwargs):
        self.runner = FakeRunner(**kwargs)
        return corpus.process(self.snapshot, self.runner, self.embed,
                              save=lambda key, value: self.saved.update({key: deepcopy(value)}))

    def test_full_clustering_path_uses_two_calls_not_per_comment_frames(self):
        output = self.execute()
        self.assertEqual([stage for stage, _ in self.runner.calls], ['discovery-0000', 'initial-0000'])
        self.assertEqual(len(output['source_states']), 6)
        self.assertEqual(output['per_comment_frame_calls'], 0)
        self.assertEqual([stage for stage, _ in self.embeddings], ['sources', 'candidates'])
        self.assertEqual(output['map']['opinion_map']['perspectives'][0]['supported_canonical_ids'], ['A', 'B', 'C'])
        self.assertEqual(output['agent_generation_state'], 'requires_argument_adapter')
        self.assertFalse(output['quality_gate_passed']); self.assertIsNone(output['correct_comment_utilization'])
        self.assertIn('map', self.saved); self.assertIn('source-states', self.saved)

    def test_non_substantive_discovery_is_not_membership_filter(self):
        output = self.execute(non_substantive=('B',))
        bstate = next(s for s in output['source_states'] if s['source_id'] == 'B')
        self.assertEqual(bstate['discovery_state'], 'non_substantive')
        self.assertEqual(bstate['membership_state'], 'supported')
        self.assertEqual(output['membership_schedule']['canonical_sources'], 6)

    def test_failed_discovery_retains_population_without_empty_success(self):
        output = self.execute(fail_discovery=True)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(output['candidates'], [])
        self.assertEqual(len(output['source_states']), 6)
        self.assertEqual(output['map']['opinion_map']['coverage']['sources_without_supported_assignment'], 6)
        self.assertTrue(all(s['discovery_state'] == 'discovery_contract_error' for s in output['source_states']))

    def test_no_candidates_retains_all_sources_and_does_not_invent_agent(self):
        output = self.execute(non_substantive=tuple('ABCDEF'))
        self.assertEqual(output['candidates'], [])
        self.assertEqual(len(output['source_states']), 6)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertTrue(all(s['membership_state'] == 'unassessed' for s in output['source_states']))
        self.assertFalse(output['quality_gate_passed'])

    def test_failed_membership_is_unassessed_without_per_pair_retry(self):
        output = self.execute(fail_admission=True)
        self.assertEqual(len(self.runner.calls), 2)
        p = output['map']['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts']['unassessed'], 6); self.assertEqual(p['counts']['not_supported'], 0)
        self.assertEqual(len(output['errors']), 1)
        self.assertEqual(len(output['errors'][0]['pairs']), 6)

    def test_aliases_do_not_get_extra_votes(self):
        alias = replace(self.snapshot.comments[0], comment_id='alias')
        self.snapshot = replace(self.snapshot, comments=(*self.snapshot.comments, alias))
        output = self.execute(); coverage = output['map']['opinion_map']['coverage']
        self.assertEqual(coverage['raw_comments'], 7); self.assertEqual(coverage['canonical_nonempty_comments'], 6)
        self.assertEqual(coverage['duplicate_aliases'], 1)
        self.assertEqual(output['map']['opinion_map']['perspectives'][0]['counts']['supported'], 3)

    def test_long_original_is_never_cut_or_removed(self):
        long = replace(self.snapshot.comments[0], comment_id='long', text_original='Important condition. '*2000)
        self.snapshot = replace(self.snapshot, comments=(*self.snapshot.comments, long))
        output = self.execute()
        state = next(s for s in output['source_states'] if s['source_id'] == 'long')
        self.assertEqual(state['discovery_state'], 'capacity_deferred')
        self.assertEqual(state['membership_state'], 'unassessed')
        self.assertEqual(self.embeddings[0][1]['long'], long.text_original)
        self.assertEqual(output['map']['opinion_map']['coverage']['canonical_nonempty_comments'], 7)
        self.assertEqual(output['map']['opinion_map']['perspectives'][0]['counts']['unassessed'], 1)

    def test_deterministic_batches_cover_every_source_at_most_eight(self):
        original = next(iter(sources(self.snapshot).values()))
        packets = {f's{i:03}': {**deepcopy(original), 'id': f's{i:03}'} for i in range(25)}
        vectors = {sid: [1., 0.] for sid in packets}
        schedule = corpus.discovery_schedule(packets, vectors)
        self.assertEqual([len(ids) for ids in schedule['batches']], [8, 8, 8, 1])
        self.assertEqual(sorted(sid for ids in schedule['batches'] for sid in ids), sorted(packets))
        self.assertEqual(schedule, corpus.discovery_schedule(dict(reversed(list(packets.items()))), vectors))

    def test_membership_schedule_keeps_all_nominees_and_fallback_separate(self):
        packets = list(sources(self.snapshot).values()); result = proposal(packets)
        value = result['output']; base = value['candidates'][0]
        value['candidates'] = []
        for i in range(5):
            c = deepcopy(base); c['contract']['statement'] += f' Variant {i}.'; c['nominees'] = ['S0']
            value['candidates'].append(c)
        for row in value['sources']: row['state'] = 'covered' if row['source_key'] == 'S0' else 'non_substantive'
        record = b.bind_discovery(packets, result); candidates = b.candidates_from(packets, [record])
        registry = sources(self.snapshot)
        sv = {sid: [1., 0.] for sid in registry}; cv = {c['id']: [1., 0.] for c in candidates}
        schedule = corpus.membership_schedule(registry, candidates, sv, cv)
        a = next(r for r in schedule['rankings'] if r['source_id'] == 'A')
        other = next(r for r in schedule['rankings'] if r['source_id'] == 'B')
        self.assertEqual(len(a['initial_candidate_ids']), 5); self.assertEqual(a['fallback_candidate_ids'], [])
        self.assertEqual(len(other['initial_candidate_ids']), 2); self.assertEqual(len(other['fallback_candidate_ids']), 2)
        self.assertFalse(set(other['initial_candidate_ids']) & set(other['fallback_candidate_ids']))
        packed = corpus.admission_batches(registry, candidates, schedule['initial'])
        self.assertTrue(all(len(ps) <= 8 for ps in packed['batches']))
        self.assertEqual([p for ps in packed['batches'] for p in ps], schedule['initial'])

    def test_fallback_runs_only_for_unlinked_sources_and_never_repeats_pairs(self):
        class ManyCandidates(FakeRunner):
            def call(self, stage, request):
                result = super().call(stage, request)
                if stage.startswith('discovery-'):
                    value = result['output']; base = value['candidates'][0]; value['candidates'] = []
                    for i in range(5):
                        c = deepcopy(base); c['contract']['statement'] += f' Variant {i}.'; c['nominees'] = ['S0']
                        value['candidates'].append(c)
                    for row in value['sources']:
                        row['state'] = 'covered' if row['source_key'] == 'S0' else 'non_substantive'
                return result
        runner = ManyCandidates(); output = corpus.process(self.snapshot, runner, self.embed)
        fallback = output['admission_execution'][1]
        pairs = [p for chunk in fallback['batches'] for p in chunk]
        self.assertEqual({p['source_id'] for p in pairs}, {'D', 'E', 'F'})
        self.assertEqual(len(pairs), 6)
        all_pairs = [(p['source_id'], p['candidate_id']) for b in output['membership_batches'] for p in b['pairs']]
        self.assertEqual(len(all_pairs), len(set(all_pairs)))
        self.assertEqual(output['map']['opinion_map']['coverage']['canonical_nonempty_comments'], 6)

    def test_earlier_batches_survive_a_later_failed_batch(self):
        originals = list(self.snapshot.comments)
        originals.extend(replace(originals[0], comment_id=f'extra{i}', text_original=f'Distinct opinion {i}.') for i in range(4))
        self.snapshot = replace(self.snapshot, comments=tuple(originals))
        class LaterFailure(FakeRunner):
            def call(self, stage, request):
                result = super().call(stage, request)
                return {'errors': ['failed'], 'output': None} if stage == 'initial-0001' else result
        runner = LaterFailure(); output = corpus.process(self.snapshot, runner, self.embed)
        self.assertEqual(len(output['discoveries']), 2)
        self.assertEqual(len(output['candidates']), 1)  # Exact contracts only.
        self.assertEqual(len(output['membership_batches']), 1)
        p = output['map']['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts']['unassessed'], 2)
        self.assertEqual(len(output['source_states']), 10)
        self.assertEqual(len(runner.calls), 4)

    def test_embeddings_must_cover_entire_population_with_finite_vectors(self):
        originals = sources(self.snapshot)
        with self.assertRaises(ValueError): corpus.discovery_schedule(originals, {})
        with self.assertRaises(ValueError): corpus.discovery_schedule(originals, {sid: [float('nan')] for sid in originals})

    def test_pilot_keeps_external_parent_context_and_full_denominator(self):
        self.snapshot = replace(self.snapshot, comments=tuple(replace(c, parent_id='A') if c.comment_id == 'B' else c
                                                             for c in self.snapshot.comments))
        runner = FakeRunner(); output = corpus.process(self.snapshot, runner, self.embed, source_ids=['B', 'C'])
        self.assertEqual(set(self.embeddings[0][1]), {'B', 'C'})
        first = runner.calls[0][1]['data']['ORIGINALS']['S0']
        self.assertEqual(first['parent']['id'], 'A')
        self.assertEqual(output['map']['opinion_map']['coverage']['canonical_nonempty_comments'], 6)
        self.assertEqual(len(output['source_states']), 6)
        self.assertFalse(output['processing_scope']['whole_corpus_scheduled'])
        self.assertEqual(next(r for r in output['source_states'] if r['source_id'] == 'A')['discovery_state'], 'not_scheduled')
        for ids in ([], ['A', 'A'], ['foreign']):
            with self.assertRaises(ValueError): corpus.process(self.snapshot, runner, self.embed, source_ids=ids)


if __name__ == '__main__':
    unittest.main()
