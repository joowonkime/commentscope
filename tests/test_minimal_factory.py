"""Synthetic contract tests; authored decisions do not measure model quality."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory import candidate_consolidation as cc, proposition_requirements as pr
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot


def proposition(text, *, authorship='asserted', conditions=None):
    return {'text': text, 'authorship': authorship, 'evidence_segment_ids': ['S000'],
            'essential_condition_segment_ids': conditions or []}


def extraction(sources, texts, statuses=None, previous=()):
    rows = [{'source_id': s['id'], 'status': (statuses or {}).get(s['id'], 'covered'),
             'claims': [proposition(t) for t in texts.get(s['id'], [])]} for s in sources]
    return mc.bind_extraction(sources, {'output': {'sources': rows}}, previous)


def membership(sources, candidates, pairs, decisions=None):
    req = mm.membership_request(sources, candidates, pairs)
    rows = [{'pair_id': p['pair_id'], 'relation': 'supported', 'authorship': 'asserted_or_endorsed',
             'scope_preserved': 'yes', 'evidence_segment_ids': ['S000'],
             **(decisions or {}).get(p['source_id'], {})} for p in req['data']['PAIRS']]
    # Authored empty inventories are mock evidence, never semantic gold.
    ss={s['id']:s for s in sources};cs={c['id']:c for c in candidates}
    quals=[{'source_id':p['source_id'],'candidate_id':p['candidate_id'],
        'assessment':pr.assessment(ss[p['source_id']],pr.bind_shape(cs[p['candidate_id']]['text'],
            {'output':{'status':'complete','qualifications':[]}}),[])} for p in pairs]
    return mm.bind(sources, candidates, pairs, {'output': {'decisions': rows}},quals)


class MinimalFactoryTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{'id': 'a', 'text': 'Adopt P. Equity matters.', 'parent': None},
                        {'id': 'b', 'text': 'Adopt P. Freedom matters.', 'parent': None},
                        {'id': 'c', 'text': 'Adopt P only if funded.', 'parent': None},
                        {'id': 'd', 'text': 'Do not adopt P.', 'parent': None}]
        self.records = extraction(self.sources, {'a': ['Adopt P.'], 'b': ['Adopt P.'],
                                                'c': ['Adopt P only if funded.'], 'd': ['Do not adopt P.']})
        self.candidates = mc.candidates(self.records)
        self.target = next(c for c in self.candidates if c['text'] == 'Adopt P.')
        self.pairs = [{'source_id': s['id'], 'candidate_id': self.target['id']} for s in self.sources]

    def test_normalization_keeps_negation_punctuation_and_condition(self):
        self.assertEqual(mc.claim_id(' Cafe\u0301\n P.  '), mc.claim_id('Café P.'))
        self.assertNotEqual(mc.claim_id('Adopt P.'), mc.claim_id('Do not adopt P.'))
        self.assertNotEqual(mc.claim_id('Adopt P.'), mc.claim_id('Adopt P only if funded.'))
        self.assertNotEqual(mc.claim_id('Adopt P.'), mc.claim_id('Adopt P?'))

    def test_one_candidate_multiple_nominees_not_support(self):
        self.assertEqual(set(self.target['nominees']), {'a', 'b'})
        self.assertNotIn('support_count', self.target)
        self.assertEqual(len(self.target['extraction_refs']), 2)
        self.assertNotIn('contract', self.target)  # No fabricated legacy frame.

    def test_parent_is_context_never_evidence_inventory(self):
        source = {**self.sources[0], 'parent': {'id': 'parent', 'text': 'Outside argument.'}}
        req = mc.extraction_request([source]); packet = req['data']['ORIGINALS'][0]
        self.assertEqual(''.join(p['text'] for p in packet['ORIGINAL_SEGMENTS']), source['text'])
        self.assertEqual(packet['PARENT_CONTEXT_ONLY'], source['parent'])
        self.assertEqual(req['max_tokens'], 3072)
        self.assertNotIn('expected', str(req))

    def test_reported_or_uncertain_does_not_nominate(self):
        for author in ('reported', 'uncertain'):
            value = deepcopy(self.records[0]['extraction'])
            value['sources'][0]['claims'][0]['authorship'] = author
            records = mc.bind_extraction(self.sources, {'output': value})
            target = next(c for c in mc.candidates(records) if c['id'] == self.target['id'])
            self.assertEqual(set(target['nominees']), {'b'})

    def test_segment_or_source_mutation_is_rejected(self):
        for mutate in (lambda r: r['source'].update(text='Different.'),
                       lambda r: r['claims'][0]['evidence'][0].update(text='Invented.'),
                       lambda r: r['claims'][0].update(text='Opposite.'),
                       lambda r: r.update(request_sha256='bad')):
            record = deepcopy(self.records[0]); mutate(record)
            with self.assertRaises(ValueError): mc.validate(record)

    def test_missing_unknown_duplicate_or_extra_source_fails_entire_batch(self):
        value = self.records[0]['extraction']
        for rows in (value['sources'][:-1], value['sources']+[value['sources'][0]],
                     [value['sources'][0]]*4,
                     [{**value['sources'][0], 'source_id': 'outside'}, *value['sources'][1:]]):
            with self.assertRaises(ValueError): mc.bind_extraction(self.sources, {'output': {'sources': rows}})
        with self.assertRaises(ValueError): mc.bind_extraction(self.sources, {'errors': ['timeout'], 'output': value})

    def test_conditions_bound_to_own_exact_evidence(self):
        value = deepcopy(self.records[0]['extraction'])
        value['sources'][2]['claims'][0]['essential_condition_segment_ids'] = ['S000']
        rows = mc.bind_extraction(self.sources, {'output': value})
        self.assertEqual(rows[2]['claims'][0]['essential_conditions'][0]['text'], self.sources[2]['text'])
        value['sources'][2]['claims'][0]['essential_condition_segment_ids'] = ['S001']
        with self.assertRaises(ValueError): mc.bind_extraction(self.sources, {'output': value})

    def test_condition_address_can_be_separate_from_stance_evidence(self):
        source = {'id': 'x', 'text': 'Adopt P. Only if funded.', 'parent': None}
        value = {'sources': [{'source_id': 'x', 'status': 'covered', 'claims': [
            proposition('Adopt P only if funded.', conditions=['S001'])]}]}
        row = mc.bind_extraction([source], {'output': value})[0]
        self.assertEqual(row['claims'][0]['evidence'][0]['id'], 'S000')
        self.assertEqual(row['claims'][0]['essential_conditions'][0]['id'], 'S001')
        self.assertIn('only if funded', row['claims'][0]['text'])

    def test_request_schema_binds_segments_per_source_and_uses_short_pair_aliases(self):
        req = mm.membership_request(self.sources, self.candidates, self.pairs)
        self.assertEqual([p['pair_id'] for p in req['data']['PAIRS']], ['P1','P2','P3','P4'])
        self.assertEqual(req['data']['PAIRS'][0]['CANDIDATE']['text'], self.target['text'])
        self.assertEqual(req['data']['PAIRS'][0]['ORIGINAL']['source_id'], 'a')
        branches = req['schema']['properties']['decisions']['items']['anyOf']
        third = branches[2]['properties']
        self.assertEqual(third['pair_id']['const'], 'P3')
        self.assertEqual(third['evidence_segment_ids']['items']['enum'], ['S000'])

    def test_single_additional_pass_preserves_old_claims(self):
        sources = self.sources[:1]
        first = extraction(sources, {'a': ['Adopt P.']}, {'a': 'partial'})
        final = extraction(sources, {'a': ['Equity matters.']}, previous=first)
        self.assertEqual(len(final[0]['claims']), 2)
        self.assertEqual(final[0]['claims'][0], first[0]['claims'][0])
        self.assertEqual(final[0]['additional_passes'], 1); mc.validate(final[0])
        with self.assertRaises(ValueError): mc.extraction_request(sources, final)
        with self.assertRaises(ValueError): extraction(sources, {'a': ['Adopt P.']}, previous=first)
        with self.assertRaises(ValueError): extraction(sources, {}, {'a': 'non_substantive'}, previous=first)

    def test_partial_can_stay_partial_and_capacity_is_not_truncated(self):
        first = extraction(self.sources[:1], {}, {'a': 'partial'})
        final = extraction(self.sources[:1], {}, {'a': 'partial'}, previous=first)
        self.assertEqual(final[0]['status'], 'partial')
        with self.assertRaises(ValueError): mc.extraction_request(self.sources[:1], final)
        with self.assertRaises(ValueError): extraction(self.sources[:1], {'a': ['x'*601]})
        with self.assertRaises(ValueError): extraction(self.sources[:1], {'a': [str(i) for i in range(17)]})

    def test_historical_extraction_replays_unchanged_and_cannot_mix_contracts(self):
        record = json.loads(Path('tests/fixtures/minimal-extraction-v3.json').read_text())
        self.assertEqual(record['artifact_kind'], mc.LEGACY)
        self.assertEqual(mc.validate(record), record)
        with self.assertRaises(ValueError):
            mc.extraction_request([record['source']], [record])

    def test_completed_supplement_can_add_nothing_without_repeating_previous(self):
        first = extraction(self.sources[:1], {'a': ['Adopt P.', 'Equity matters.']}, {'a': 'partial'})
        req = mc.extraction_request(self.sources[:1], first)
        self.assertTrue(req['system'].startswith(mc.SUPPLEMENT_SYSTEM))
        self.assertEqual(req['data']['PREVIOUS']['a'][0],
                         {'text': 'Adopt P.', 'evidence_segment_ids': ['S000']})
        final = extraction(self.sources[:1], {}, previous=first)[0]
        self.assertEqual(final['status'], 'covered')
        self.assertEqual(final['claims'], first[0]['claims'])
        self.assertEqual(final['additional_passes'], 1)
        mc.validate(final)
        with self.assertRaises(ValueError):
            extraction(self.sources[:1], {'a': ['Adopt P.']}, previous=first)

    def test_scope_and_authorship_guards_are_uncertain_not_negative(self):
        for guard in ({'scope_preserved': 'no'}, {'scope_preserved': 'unclear'},
                      {'authorship': 'not_asserted'}, {'authorship': 'unclear'}):
            batch = membership(self.sources, self.candidates, self.pairs, {'a': guard})
            self.assertEqual(batch['memberships'][0]['relation'], 'uncertain')
            self.assertFalse(batch['memberships'][0]['semantic_approval'])

    def test_membership_batch_is_atomic_and_own_segments_only(self):
        batch = membership(self.sources, self.candidates, self.pairs)
        for mutate in (lambda v: v['decisions'].pop(),
                       lambda v: v['decisions'].append(v['decisions'][0]),
                       lambda v: v['decisions'][0].update(pair_id=v['decisions'][1]['pair_id']),
                       lambda v: v['decisions'][2].update(evidence_segment_ids=['S001'])):
            value = deepcopy(batch['output']); mutate(value)
            with self.assertRaises(ValueError): mm.bind(self.sources, self.candidates, self.pairs, {'output': value})

    def test_changed_original_or_final_claim_cannot_reuse_membership(self):
        batch = membership(self.sources, self.candidates, self.pairs)
        changed = deepcopy(self.sources); changed[0]['parent'] = {'id': 'parent', 'text': 'New context.'}
        with self.assertRaises(ValueError): mm.collect(changed, self.candidates, [batch])
        with self.assertRaises(ValueError): mm.collect(self.sources, self.candidates, [batch, batch])
        changed_batch = deepcopy(batch); changed_batch['memberships'][0]['relation'] = 'uncertain'
        with self.assertRaises(ValueError): mm.validate_batch(changed_batch)

    def snapshot(self, *, duplicate=True):
        base = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        comments = [replace(base.comments[0], comment_id=s['id'], text_original=s['text'], parent_id=None) for s in self.sources]
        if duplicate: comments.append(replace(comments[0], comment_id='alias'))
        return replace(base, usage=replace(base.usage, expires_at='2099-01-01T00:00:00Z'), comments=tuple(comments))

    def test_map_adapter_counts_canonical_and_keeps_unassessed(self):
        batch = membership(self.sources, self.candidates, self.pairs[:3], {'c': {'relation': 'conditional'}})
        mapped = mm.assemble_map(self.snapshot(), self.candidates, [batch])['opinion_map']
        target = next(p for p in mapped['perspectives'] if p['id'] == self.target['id'])
        self.assertEqual(target['canonical_denominator'], 4)
        self.assertEqual(target['counts'], {'supported': 2, 'conditional': 1, 'not_supported': 0, 'uncertain': 0, 'unassessed': 1})
        self.assertFalse(target['minimum_support_met']); self.assertFalse(mapped['quality_gate_passed'])
        self.assertEqual(mapped['coverage']['duplicate_aliases'], 1)

    def test_alias_cannot_vote_in_new_adapter(self):
        alias = {**self.sources[0], 'id': 'alias'}
        batch = membership([alias], self.candidates, [{'source_id': 'alias', 'candidate_id': self.target['id']}])
        with self.assertRaises(ValueError): mm.assemble_map(self.snapshot(), self.candidates, [batch])

    def equivalences(self, relations):
        # These tests isolate graph closure, not semantic/conditional equivalence.
        self.sources=[{'id':str(i),'text':t,'parent':None} for i,t in enumerate(('Adopt P.','Approve P.','Implement P.'))]
        self.candidates=mc.candidates(extraction(self.sources,{s['id']:[s['text']] for s in self.sources}))
        pairs = [{'source_id': c['nominees'].__iter__().__next__(), 'candidate_id': c['id']} for c in self.candidates]
        members = [membership(self.sources, self.candidates, pairs)]
        ordered = sorted(self.candidates, key=lambda c: c['id'])
        pairs = [{'a': ordered[i]['id'], 'b': ordered[j]['id']} for i, j, _ in relations]
        req = cc.equivalence_request(self.sources, self.candidates, members, pairs)
        value = {'decisions': [{'pair_id': task['pair_id'], 'relation': relation}
                              for task, (_, _, relation) in zip(req['data']['PAIRS'], relations)]}
        cs={c['id']:c for c in self.candidates};quals=[]
        for pair in pairs:
            for a,b in ((pair['a'],pair['b']),(pair['b'],pair['a'])):
                shape=pr.bind_shape(cs[b]['text'],{'output':{'status':'complete','qualifications':[]}})
                quals.append({'from_candidate_id':a,'to_candidate_id':b,
                    'assessment':pr.assessment({'id':a,'text':cs[a]['text'],'parent':None},shape,[])})
        batch = cc.bind(self.sources, self.candidates, members, pairs, {'output': value},quals)
        return members, batch

    def test_chain_equivalence_never_implies_unassessed_edge(self):
        members, eq = self.equivalences([(0, 1, 'equivalent'), (1, 2, 'equivalent')])
        out = cc.consolidate(self.sources, self.candidates, members, [eq])
        self.assertEqual(len(out['candidates']), 2)
        self.assertEqual(out['unassessed_pairs'], 1)
        self.assertEqual(out['memberships'], [])
        self.assertTrue(out['final_wording_reassessment_required'])

    def test_complete_link_selects_existing_minimum_id_and_keeps_aliases(self):
        members, eq = self.equivalences([(0, 1, 'equivalent'), (0, 2, 'equivalent'), (1, 2, 'equivalent')])
        out = cc.consolidate(self.sources, self.candidates, members, [eq])
        self.assertEqual(len(out['candidates']), 1)
        final = out['candidates'][0]
        self.assertEqual(final['id'], min(c['id'] for c in self.candidates))
        self.assertEqual(final['aliases'], sorted(c['id'] for c in self.candidates))
        # Old judgments for non-final text cannot be copied to merged support.
        with self.assertRaises(ValueError): mm.collect(self.sources, [final], members)

    def test_conditional_opposed_and_uncertain_candidates_are_not_merged(self):
        for relation in cc.RELATIONS[1:]:
            members, eq = self.equivalences([(0, 1, relation)])
            out = cc.consolidate(self.sources, self.candidates, members, [eq])
            self.assertEqual(len(out['candidates']), 3)

    def test_unverified_candidates_cannot_provide_equivalence_context(self):
        a, b = sorted(c['id'] for c in self.candidates)[:2]
        with self.assertRaises(ValueError): cc.equivalence_request(self.sources, self.candidates, [], [{'a': a, 'b': b}])

    def test_retrieval_is_deterministic_without_similarity_filter(self):
        values = {str(i): [1., 0.] for i in range(12)}
        self.assertEqual(cc.neighborhoods(values), [sorted(values)[:8], sorted(values)[8:]])
        self.assertEqual(cc.neighborhoods(dict(reversed(list(values.items())))), cc.neighborhoods(values))
        self.assertEqual(cc.nearest_pairs({'c': [1., 0.], 'a': [1., 0.], 'b': [1., 0.]}, width=1),
                         [{'a': 'a', 'b': 'b'}, {'a': 'a', 'b': 'c'}])
        with self.assertRaises(ValueError): cc.neighborhoods({'a': [float('nan')]})

    def test_nominations_are_always_examined_and_expansion_is_bounded(self):
        # More candidates than retrieval width; nominated target stays present.
        texts = {'a': [f'Proposition {i}.' for i in range(7)]}
        candidates = mc.candidates(extraction(self.sources[:1], texts))
        sv = {'a': [1., 0.]}; cv = {c['id']: [1., 0.] for c in candidates}
        pairs = cc.membership_pairs(self.sources[:1], candidates, sv, cv)
        self.assertEqual(len(pairs), 7)
        batch = membership(self.sources[:1], candidates, pairs, {'a': {'relation': 'uncertain'}})
        self.assertEqual(cc.membership_pairs(self.sources[:1], candidates, sv, cv, previous=[batch], expand=True), [])

    def test_singleton_and_conditional_hits_expand_but_shared_support_stops(self):
        sources=self.sources[:2]
        candidates=mc.candidates(extraction(sources,{'a':[f'Policy {i}.' for i in range(7)],'b':['Policy 0.']}))
        sv={s['id']:[1.,0.] for s in sources};cv={c['id']:[1.,0.] for c in candidates}
        target=candidates[0]['id'];pairs=[{'source_id':'a','candidate_id':target}]
        for relation in ('supported','conditional'):
            batch=membership(sources,candidates,pairs,{'a':{'relation':relation}})
            extra=cc.membership_pairs(sources,candidates,sv,cv,previous=[batch],expand=True)
            selected=[p for p in extra if p['source_id']=='a']
            self.assertEqual(len(selected),3)
            self.assertNotIn(pairs[0],selected)
        both=membership(sources,candidates,[*pairs,{'source_id':'b','candidate_id':target}])
        self.assertEqual(cc.membership_pairs(sources,candidates,sv,cv,previous=[both],expand=True),[])


if __name__ == '__main__': unittest.main()
