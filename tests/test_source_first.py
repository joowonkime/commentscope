from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope import claim_prompt
from commentscope.contracts.claim_generation import constrained_schema
from commentscope.factory import source_first as sf
from commentscope.factory.claim_clusters import read_json
from commentscope.providers import source_first_candidates as provider
from commentscope.storage import write_json_exclusive as write
from experiments.fresh_grounded_pipeline import proposals_from_sources


def output(text, *, stance='support', scope='general', modality='asserted'):
    return {'eligibility': 'argument_or_experience', 'claims': [{
        'issue': 'safety reviews', 'claim': text, 'quote': text, 'stance_target': 'safety reviews',
        'stance': stance, 'reason': None, 'reason_quote': None, 'condition': None,
        'condition_quote': None, 'scope': scope, 'modality': modality}]}


class SourceFirstTests(unittest.TestCase):
    def sources(self):
        return {f's{i}': 'Safety reviews should be required.' for i in range(3)}

    def units(self, sources):
        return [sf.bind(sid, text, {'output': output(text), 'errors': []})['units'][0] for sid, text in sources.items()]

    def test_frozen_prompt_and_source_only_request(self):
        req = sf.invocation('Source text')
        self.assertEqual(req['system'], claim_prompt.SYSTEM)
        self.assertEqual(req['schema'], constrained_schema())
        self.assertEqual(req['data'], {'TARGET': 'Source text', 'PARENT': None})
        self.assertNotIn('CORE', req['data']); self.assertNotIn('reference', req['data'])

    def test_source_queue_is_deterministic_and_never_reextracts_overlap(self):
        raw = {'sources': {s: {} for s in 'abcdef'}, 'clusters': [
            {'id': 'A', 'members': list('abcd')}, {'id': 'B', 'members': list('cdef')}]}
        order = sf.schedule(raw)
        self.assertEqual(set(order), set('abcdef')); self.assertEqual(len(order), 6)
        self.assertEqual(order, sf.schedule({**raw, 'clusters': list(reversed(raw['clusters']))}))

    def test_error_and_empty_claims_are_different_states(self):
        self.assertEqual(sf.bind('s', 'text', {'errors': ['timeout']})['status'], 'call_or_contract_error')
        record = sf.bind('s', 'text', {'errors': [], 'output': {'eligibility': 'question_or_request', 'claims': []}})
        self.assertEqual(record['status'], 'question_or_request'); self.assertEqual(record['errors'], [])
        value = output('Invented quote')
        self.assertEqual(sf.bind('s', 'Original text', {'errors': [], 'output': value})['status'], 'extraction_contract_error')

    def test_medoid_is_existing_unit_not_generated_consensus_or_support(self):
        sources = self.sources(); units = self.units(sources)
        result = sf.candidates(units, [[1., 0.]]*3, sources)
        self.assertEqual(len(result['proposals']), 1)
        proposal = result['proposals'][0]
        self.assertIn(proposal['claims']['C']['text'], [u['claim'] for u in units])
        self.assertEqual(len(proposal['sources']), 3)
        self.assertFalse(proposal['semantic_approval']); self.assertTrue(proposal['typing_required'])
        self.assertFalse(result['quality_gate_passed'])

    def test_many_units_from_one_comment_cannot_make_three_supporters(self):
        sources = {'s': 'Safety reviews should be required.'}; unit = self.units(sources)[0]
        units = [{**deepcopy(unit), 'claim_id': f'u{i}'} for i in range(6)]
        result = sf.candidates(units, [[1., 0.]]*6, sources)
        self.assertEqual(result['proposals'], [])
        self.assertEqual(result['deferred'][0]['reason'], 'fewer_than_three_sources')

    def test_opposite_stance_or_personal_scope_not_joined_by_identical_vectors(self):
        sources = self.sources(); units = self.units(sources)
        for field, value in (('stance', 'oppose'), ('scope', 'personal'), ('modality', 'possible')):
            changed = deepcopy(units); changed[0][field] = value
            with self.subTest(field=field):
                self.assertFalse(sf.candidates(changed, [[1., 0.]]*3, sources)['proposals'])

    def test_ambiguous_units_preserved_as_deferred(self):
        sources = self.sources(); units = self.units(sources); units[0]['scope'] = 'unclear'
        result = sf.candidates(units, [[1., 0.]]*3, sources)
        self.assertTrue(any(r.get('claim_id') == units[0]['claim_id'] for r in result['deferred']))

    def test_bad_vectors_ids_and_quotes_fail(self):
        sources = self.sources(); units = self.units(sources)
        for vectors in ([], [[0., 0.]]*3, [[float('nan'), 0.]]*3, [[1.], [1., 0.], [1.]]):
            with self.assertRaises(ValueError): sf.candidates(units, vectors, sources)
        with self.assertRaises(ValueError): sf.candidates([units[0]]*3, [[1., 0.]]*3, sources)
        with self.assertRaises(ValueError): sf.candidates(units, [[1., 0.]]*3, {})

    def test_empty_provider_does_not_load_a_model_or_approve_quality(self):
        with patch.object(provider, 'embed') as embed:
            result = provider.generate(provider.VERSION, {'units': [], 'sources': {}, 'threshold': .45}, {}, 1)
        embed.assert_not_called(); self.assertEqual(result['proposals'], [])
        self.assertFalse(result['quality_gate_passed'])

    def test_source_budget_keeps_unprocessed_separate_from_no_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sources = self.sources()
            raw = {'sources': {sid: {'text': text} for sid, text in sources.items()},
                   'clusters': [{'id': 'C', 'members': list(sources)}]}
            write(root/'fresh-groups.json', raw)
            runner = Mock(); runner.directory = root; runner.started = 0
            runner.plan = {'limits': {'groups': 20, 'source_analysis_seconds': 10, 'source_request_bytes': 27000}}
            runner.clock.side_effect = [0, 11, 11]
            runner.call.return_value = {'errors': [], 'output': output(next(iter(sources.values())))}
            units, _, coverage = proposals_from_sources(raw, runner)
            self.assertEqual(len(units), 1); self.assertEqual(len(coverage['unprocessed_budget']), 2)
            self.assertEqual(coverage['model_calls'], 1); self.assertEqual(coverage['failed_sources'], [])
            self.assertTrue((root/'source-analysis.json').exists())

    def test_coverage_separates_canonical_population_from_original_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); sources=self.sources()
            raw={'sources':{sid:{'text':text} for sid,text in sources.items()},
                 'clusters':[{'id':'C','members':list(sources)}, {'id':'rare','members':['rare']} ]}
            raw['sources']['rare']={'text':'A distinct rare position.'}
            raw['sources']['duplicate']={'text':next(iter(sources.values()))}
            write(root/'fresh-groups.json',raw)
            runner=Mock(); runner.directory=root; runner.started=0; runner.clock.return_value=0
            runner.plan={'limits':{'groups':20,'source_analysis_seconds':10,'source_request_bytes':27000}}
            runner.call.return_value={'errors':[],'output':output(next(iter(sources.values())))}
            _,_,coverage=proposals_from_sources(raw,runner)
            self.assertEqual(coverage['registry_source_count'],5)
            self.assertEqual(coverage['canonical_available'],4)
            self.assertEqual(coverage['scheduled'],3)
            self.assertEqual(coverage['not_scheduled'],['rare'])
            self.assertEqual(coverage['noncanonical_or_empty'],['duplicate'])
