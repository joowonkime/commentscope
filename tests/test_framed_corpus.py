from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import framed_corpus as c, position_frames as f, framed_clusters as clusters
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.providers import framed_embedding
from tests import test_stance_agents as agent_fixtures
from tests.test_stance_agents import Runner as ArgumentRunner
from experiments.grounding_contract_demo import MODEL


class PipelineRunner(ArgumentRunner):
    def __init__(self, snapshot, *, fail_frame=None, fail_member=None, **kwargs):
        super().__init__(**kwargs); self.snapshot = snapshot
        self.fail_frame = fail_frame; self.fail_member = fail_member; self.recorded = []

    def call(self, stage, req):
        self.recorded.append((stage, req)); data = req['data']
        if stage.startswith('frame-'):
            sid = data['SOURCE_ID']
            if sid == self.fail_frame: return {'output': None, 'errors': ['transport_error']}
            value = {'status': 'positions', 'positions': [{'target': 'policy P', 'statement': 'Adopt policy P.',
                     'mode': 'normative', 'entity': 'policy P', 'time': '', 'segment_ids': ['S000'],
                     'qualifications': [], 'reasons': []}]}
        elif stage.startswith('proposal-'):
            value = {'candidates': [{'contract': {'target': 'policy P', 'statement': 'Adopt policy P.',
                     'entity': 'policy P', 'time': '', 'conditions': ''},
                     'nominees': [v['id'] for v in data['POSITION_VIEWS']]}]}
        elif stage.startswith('membership-'):
            sid = data['SOURCE_ID']
            if sid == self.fail_member: return {'output': None, 'errors': ['transport_error']}
            relation = {'s3': 'conditional', 's4': 'opposed'}.get(sid, 'supported')
            value = {'relation': relation, 'authorship': 'asserted_or_endorsed',
                     'scope_preserved': 'no' if relation == 'conditional' else 'yes', 'evidence_segment_ids': ['S000']}
        else: return super().call(stage[stage.index('argument-'):], req)
        return {'output': value, 'errors': []}


class FramedCorpusTests(unittest.TestCase):
    def setUp(self):
        base = agent_fixtures.StanceAgentTests(); base.setUp()
        self.snapshot, self.records, self.candidate = base.snapshot, base.frames, base.candidate

    def embed(self, stage, texts):
        self.embedding_requests.append((stage, deepcopy(texts)))
        return {sid: [1., 0.] for sid in texts}

    def execute(self, **kwargs):
        self.embedding_requests = []; self.saved = {}
        self.runner = PipelineRunner(self.snapshot, **kwargs)
        self.fact_check = Mock(side_effect=ValueError('unavailable fact provider'))
        out = c.process(self.snapshot, self.runner, self.embed, self.fact_check, model=MODEL,
                        save=lambda name, value: self.saved.update({name: deepcopy(value)}))
        return out

    def test_all_sources_to_map_arguments_and_compiler_without_evaluation_labels(self):
        out = self.execute()
        self.assertEqual(len(out['source_states']), 5)
        self.assertEqual(len(out['memberships']), 5)
        self.assertEqual(out['agent_inputs']['map']['opinion_map']['coverage']['canonical_nonempty_comments'], 5)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']), 1)
        self.fact_check.assert_not_called()
        self.assertIsNone(out['correct_comment_utilization']); self.assertFalse(out['quality_gate_passed'])
        for _, req in self.runner.recorded:
            self.assertNotIn('eligibility', str(req['data'])); self.assertNotIn('expected', str(req['data']))
        self.assertIn('agent-inputs', self.saved); self.assertIn('membership-schedule', self.saved)

    def test_frame_failure_does_not_remove_original_from_search_or_denominator(self):
        out = self.execute(fail_frame='s1')
        self.assertEqual(len(out['source_states']), 5)
        failed = next(r for r in out['source_states'] if r['source_id'] == 's1')
        self.assertEqual(failed['state'], 'frame_contract_error')
        self.assertEqual(out['membership_schedule']['canonical_sources'], 5)
        self.assertEqual(len(out['memberships']), 5)
        # A fresh original-only judgment may recover support; no frame repair.
        self.assertEqual(out['agent_inputs']['compiled']['profiles'][0]['model_core_support_count'], 3)

    def test_failed_membership_is_unassessed_not_negative(self):
        out = self.execute(fail_member='s1')
        p = out['agent_inputs']['map']['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts']['unassessed'], 1); self.assertEqual(p['counts']['supported'], 2)
        self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        requests = [req for stage, req in self.runner.recorded if stage.startswith('membership-')]
        self.assertEqual(len(requests), 5)

    def test_essential_facts_are_sent_to_provider_and_never_deleted_on_failure(self):
        out = self.execute(ground_kind='fact', essential=True)
        self.fact_check.assert_called_once()
        request = self.fact_check.call_args.args[0]
        self.assertEqual(len(request['data']['cases']), 3)
        self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        target = next(claim for claim in out['agent_inputs']['bundle']['claims'] if claim['id'].endswith(':C'))
        self.assertEqual(len(target['requires']), 3)
        self.assertIn({'stage': 'facts', 'reason': 'fact_contract_failed', 'batch_offset': 0}, out['errors'])

    def test_only_canonical_sources_vote_and_full_raw_population_remains_reported(self):
        alias = replace(self.snapshot.comments[0], comment_id='alias')
        self.snapshot = replace(self.snapshot, comments=(*self.snapshot.comments, alias))
        out = self.execute()
        self.assertEqual(len(out['source_states']), 5)
        coverage = out['agent_inputs']['map']['opinion_map']['coverage']
        self.assertEqual(coverage['raw_comments'], 6); self.assertEqual(coverage['duplicate_aliases'], 1)

    def test_empty_discovery_remains_empty_without_invented_candidate(self):
        class Empty:
            def call(self, stage, req): return {'output': {'status': 'non_substantive', 'positions': []}, 'errors': []}
        embed = Mock(); facts = Mock()
        out = c.process(self.snapshot, Empty(), embed, facts, model=MODEL)
        embed.assert_not_called(); facts.assert_not_called()
        self.assertEqual(len(out['source_states']), 5); self.assertEqual(out['candidates'], [])
        self.assertEqual(out['agent_inputs']['map']['opinion_map']['coverage']['sources_without_supported_assignment'], 5)

    def test_discovery_batches_cover_all_positions_without_24_overflow(self):
        records = []
        for i in range(61):
            source = {'id': f'id{i:03}', 'text': 'A substantive statement.', 'parent': None}
            extraction = deepcopy(self.records[0]['extraction'])
            record = f.bind(source, {'output': extraction}); records.append(record)
        out = c.discovery_batches(records, {r['source']['id']: [1., 0.] for r in records})
        self.assertEqual([len(b) for b in out['batches']], [24, 24, 13])
        flattened = [sid for b in out['batches'] for sid in b]
        self.assertEqual(len(flattened), len(set(flattened))); self.assertEqual(len(flattened), 61)

    def test_batching_counts_positions_not_just_comment_count(self):
        records = []
        for i in range(7):
            source = {'id': f'id{i}', 'text': 'A substantive statement.', 'parent': None}
            p = self.records[0]['extraction']['positions'][0]
            positions = [{**p, 'statement': f'Position {j}.'} for j in range(8)]
            records.append(f.bind(source, {'output': {'status': 'positions', 'positions': positions}}))
        out = c.discovery_batches(records, {r['source']['id']: [1., 0.] for r in records})
        self.assertEqual([len(b) for b in out['batches']], [3, 3, 1])

    def test_exact_merge_retains_all_nominees_but_distinct_conditions_survive(self):
        first = deepcopy(self.candidate); second = deepcopy(first)
        second['nominees'] = [self.records[3]['positions'][0]['id']]
        second['frame_sha256'] = {'s3': digest(self.records[3])}
        conditional = clusters.proposals(self.records, {'output': {'candidates': [{
            'contract': {**first['contract'], 'conditions': 'only with funding'}, 'nominees': second['nominees']}]}})[0]
        merged = c.merge_exact([first, second, conditional])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(next(p for p in merged if p['id'] == first['id'])['nominees']), 4)

    def test_source_and_candidate_vectors_must_be_complete_and_finite(self):
        for vectors in ({}, {'s0': []}, {'s0': [0, 0]}, {'s0': [float('nan'), 0]}, {'s0': [True, 0]}):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError): c.normalized(vectors, ['s0'])
        with self.assertRaises(ValueError): c.similarity([1], [1, 2])

    def test_nominees_included_even_outside_top_two_and_no_repeat_fallback(self):
        candidates = []
        for i in range(6):
            contract = {**self.candidate['contract'], 'target': f'target{i}'}
            candidates.extend(clusters.proposals(self.records, {'output': {'candidates': [{
                'contract': contract, 'nominees': [self.records[0]['positions'][0]['id']]}]}}))
        out = c.membership_schedule([f's{i}' for i in range(5)], self.records, candidates,
                {f's{i}': [1, 0] for i in range(5)}, {p['id']: [1, 0] for p in candidates})
        row = next(r for r in out['rankings'] if r['source_id'] == 's0')
        self.assertEqual(len(row['initial_candidate_ids']), 6)
        other = next(r for r in out['rankings'] if r['source_id'] == 's1')
        self.assertEqual(len(other['initial_candidate_ids']), 2); self.assertEqual(len(other['fallback_candidate_ids']), 2)
        keys = [(p['candidate_id'], p['source_id']) for p in out['initial'] + out['fallback_if_unlinked']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(out['membership_approval'])

    def test_embedding_artifact_uses_offline_pinned_model_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(framed_embedding, 'embed', return_value=[[1., 0.], [0., 1.]]) as embed:
            output = Path(tmp)/'vectors.json'; data = {'texts': {'b': 'Second.', 'a': 'First.'}, 'output': str(output)}
            with patch.dict('os.environ'):
                result = framed_embedding.generate(framed_embedding.VERSION, data, {}, 1)
            embed.assert_called_once_with(['First.', 'Second.'])
            self.assertEqual(read_json(output)['vectors'], {'a': [1., 0.], 'b': [0., 1.]})
            self.assertEqual(result['count'], 2); self.assertTrue(result['local_files_only'])
            with self.assertRaises(ValueError): framed_embedding.generate(framed_embedding.VERSION, data, {}, 1)


if __name__ == '__main__': unittest.main()
