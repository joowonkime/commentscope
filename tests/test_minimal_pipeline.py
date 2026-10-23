from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import minimal_pipeline, minimal_claims as mc, minimal_membership as mm
from commentscope.factory import candidate_consolidation as cc, source_arguments as sa, proposition_requirements as pr
from commentscope.factory import owned_arguments as oa
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot
from commentscope.agents.grounded_runtime import SYSTEM as RUNTIME_SYSTEM
from experiments.grounding_contract_demo import MODEL
from experiments.framed_agent_probe import runtime_probe
from test_minimal_factory import proposition


class ScriptedRunner:
    """Authored toy decisions exercise orchestration, never measure semantics."""
    def __init__(self, fail_extraction=False, fail_source=None):
        self.calls = []; self.fail_extraction = fail_extraction; self.fail_source = fail_source
    def call(self, stage, req):
        self.calls.append((stage, req)); data = req['data']; system = req['system']
        if system.startswith(mc.SYSTEM):
            rows = [{'source_id': s['source_id'], 'status': 'covered',
                     'claims': [proposition(s['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.')]} for s in data['ORIGINALS']]
            if self.fail_extraction or any(r['source_id'] == self.fail_source for r in rows): rows.pop()
            value = {'sources': rows}
        elif system.startswith(mm.SYSTEM):
            value = {'decisions': [{'pair_id': p['pair_id'],
                'relation': 'supported' if p['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.' == p['CANDIDATE']['text'] else 'opposed',
                'authorship': 'asserted_or_endorsed', 'scope_preserved': 'yes', 'evidence_segment_ids': ['S000']} for p in data['PAIRS']]}
        elif system.startswith(pr.SHAPE):
            value={'status':'complete','qualifications':[]}
        elif system.startswith(cc.SYSTEM):
            value = {'decisions': [{'pair_id': p['pair_id'], 'relation': 'opposed'} for p in data['PAIRS']]}
        elif system.startswith(oa.CORE):
            value={'kind':'value','entity':'P','time_ids':[]}
        elif system.startswith(oa.META):
            value={'authorship':'asserted_or_endorsed','kind':'value','entity':'P','time_ids':[],'source_language':'en'}
        elif system.startswith(oa.ALIGN):
            value={'relation':'equivalent' if data['SOURCE_POSITION'].rstrip('.')==data['CANDIDATE'].rstrip('.') else 'different'}
        elif system.startswith(sa.CORE):
            value = {'kind': 'value', 'scope': {'entity': 'P', 'time': '', 'conditions': ''}}
        elif system.startswith(sa.SYSTEM):
            value = {'sources': [{'source_id': s['source_id'], 'source_language': 'en', 'status': 'complete', 'units': [
                {'local_id': 'U1', 'text': s['ORIGINAL_SEGMENTS'][1]['text'], 'kind': 'value',
                 'scope': {'entity': 'P', 'time': '', 'conditions': ''}, 'role': 'reason',
                 'candidate_ids': s['candidate_ids'], 'evidence_segment_ids': ['S001']}]}
                for s in data['ORIGINALS']]}
        elif system.startswith(sa.AUDIT):
            value = {'decisions': [{'task_id': t['task_id'], 'verdict': 'supported'} for t in data['TASKS']]}
        elif system.startswith(RUNTIME_SYSTEM):
            if 'exact annual' in data['QUESTION']:
                value = {'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}
            else:
                role = 'reason' if 'reasons' in data['QUESTION'] else 'core'
                selected = [c['claim_id'] for c in data['PERSPECTIVE']['allowed_entries'] if c['declared_role'] == role][:3]
                value = {'answerability': 'grounded', 'claim_ids': selected, 'limitation': 'none'}
        else: raise AssertionError(stage)
        return {'output': value, 'raw': 'scripted_test_only', 'errors': []}


class MinimalPipelineTests(unittest.TestCase):
    def setUp(self):
        original = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts = [f'Adopt P because Reason {i} matters.' for i in range(3)] + [f'Reject P because Other reason {i} matters.' for i in range(3)]
        self.snapshot = replace(original, usage=replace(original.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(original.comments[0], comment_id=str(i), text_original=t, parent_id=None) for i,t in enumerate(texts)))
        self.embeddings = []; self.saved = {}
    def embed(self, stage, texts):
        self.embeddings.append(stage)
        return {k: [1., 0.] for k in texts}
    def inspect(self, req): return {'request_sha256': digest(req), 'fits': True, 'input_tokens': 1}
    def facts(self, req): raise AssertionError('Values have no external fact verification')
    def save(self, name, value):
        if name in self.saved and self.saved[name] != value:
            raise ValueError('Same-plan artifact changed: '+name)
        self.saved[name] = value
    def process(self, runner, **kwargs):
        return minimal_pipeline.process(self.snapshot, runner, self.embed, self.inspect, self.facts,
                                        model=MODEL, save=self.save, **kwargs)

    def test_complete_mock_path_two_distinct_agents_all_members_and_three_questions(self):
        runner = ScriptedRunner(); output = self.process(runner)
        self.assertEqual(len(output['candidates']), 2)
        self.assertEqual(len(output['agent_inputs']['compiled']['profiles']), 2)
        self.assertEqual(len(output['arguments']), 6)
        self.assertEqual(self.embeddings, ['sources', 'candidates'])
        self.assertFalse(output['errors']); self.assertFalse(output['capacity_holds'])
        runtime = runtime_probe(output['agent_inputs']['bundle'], runner)
        self.assertEqual(len(runtime['turns']), 6)
        self.assertTrue(all(t['other_histories_unchanged'] for t in runtime['turns']))
        self.assertTrue(all(t['turn']['status'] == ('abstain' if t['question_id'] == 'missing' else 'answered') for t in runtime['turns']))
        self.assertFalse(output['quality_gate_passed'])
        self.assertFalse(output['runtime_reference_labels'])
        self.assertEqual(set(output['source_discourse']),set(output['processing_ids']))
        self.assertEqual(self.saved['source-discourse'],output['source_discourse'])
        self.assertTrue(all(g['model_calls']==0 and not g['semantic_approval'] for g in output['source_discourse'].values()))
        self.assertTrue(output['argument_ownership_enforced'])
        self.assertTrue(all(r['extraction_record']['artifact_kind']==oa.VERSION for r in output['arguments']))
        self.assertTrue(all('expected' not in str(req['data']) for _,req in runner.calls))

    def test_subset_does_not_shrink_map_denominator(self):
        output = self.process(ScriptedRunner(), scope_ids=['0','1','2'])
        mapped = output['agent_inputs']['map']['opinion_map']
        self.assertEqual(mapped['coverage']['canonical_nonempty_comments'], 6)
        self.assertEqual(mapped['perspectives'][0]['counts']['unassessed'], 3)
        self.assertEqual(output['processing_ids'], ['0','1','2'])

    def test_verified_raw_membership_runs_existing_argument_and_agent_path(self):
        from commentscope.factory import raw_membership as raw, raw_membership_verification as verification
        from commentscope.factory import shared_claims
        from commentscope.factory import shared_owned_positions
        from test_raw_membership import decision
        class RawRunner(ScriptedRunner):
            def call(self, stage, req):
                data = req['data']; system = req['system']
                if system.startswith((shared_claims.SYSTEM, shared_claims.COMMON_SYSTEM)):
                    grouped = {}
                    for original in data['ORIGINALS']:
                        text = original['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.'
                        grouped.setdefault(text, []).append(original['author_id'])
                    value = {'candidates': [{'text': text, 'nominees': ids} for text, ids in grouped.items()]}
                elif system.startswith(shared_owned_positions.SYSTEM):
                    value = {'relation': 'supports_core' if data['SOURCE_POSITION']['text'].rstrip('.') == data['COMMON_CORE'].rstrip('.') else 'different',
                             **{k: 'yes' for k in shared_owned_positions.CHECKS}, 'conditions': []}
                elif system.startswith(raw.SYSTEM):
                    text = data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.'
                    value = decision(relation='supported' if text == data['CANDIDATE']['text'] else 'opposed')
                elif system.startswith(verification.ROUTE): value = {'role': 'subject_position'}
                elif system.startswith((verification.OWN_ONLY,verification.EVIDENCE)): value = {'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                elif system.startswith(verification.FOCUS):
                    value = {'focus_token': 'T1', 'focus_domain': 'substantive_issue',
                             'role': 'subject_position', 'interpretation': 'clear'}
                elif system.startswith((verification.GROUNDED_EVIDENCE, verification.ALIGNED_EVIDENCE)):
                    value = {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                             'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                elif system.startswith(verification.SPEECH):
                    value = {'speech_use': 'literal_assertion', 'reference_basis': 'self_contained',
                             'target_alignment': 'aligned', 'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                else: return super().call(stage, req)
                self.calls.append((stage, req))
                return {'output': value, 'raw': 'authored fixture only', 'errors': []}
        configurations = [('free', c) for c in (verification.LEGACY, verification.FOCUSED, verification.GROUNDED, verification.ALIGNED)]
        configurations.append(('shared', verification.ALIGNED))
        for mode, contract in configurations:
            with self.subTest(mode=mode, contract=contract):
                self.saved = {}; self.embeddings = []
                runner = RawRunner(); result = self.process(runner, discovery_mode=mode, membership_mode='raw', verification_contract=contract)
                self.assertFalse(result['errors']); self.assertFalse(result['capacity_holds'])
                self.assertEqual(len(result['arguments']), 6)
                self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
                self.assertTrue(all(b['artifact_kind'] == contract+'-batch' for b in result['memberships']))
                runtime = runtime_probe(result['agent_inputs']['bundle'], runner)
                self.assertEqual(len(runtime['turns']), 6)
                self.assertTrue(all(t['other_histories_unchanged'] for t in runtime['turns']))
                self.assertFalse(result['quality_gate_passed'])
                if mode == 'shared':
                    self.assertEqual(len(result['shared_discovery']), 1)
                    self.assertFalse(result['extractions'])
                    self.assertFalse(result['equivalences'])
                    self.assertTrue(all(not r['semantic_approval'] for r in result['shared_discovery']))
                    self.assertFalse(any(req['system'].startswith(mc.SYSTEM) for _, req in runner.calls))
                    cached = result['shared_discovery']; expected_bundle = result['agent_inputs']['bundle']
                    self.saved = {}; self.embeddings = []
                    reused_runner = RawRunner()
                    reused = self.process(reused_runner, discovery_mode='shared', membership_mode='raw',
                        verification_contract=contract, shared_records=cached)
                    self.assertEqual(reused['agent_inputs']['bundle'], expected_bundle)
                    self.assertEqual(reused['shared_discovery'], cached)
                    self.assertFalse(any(req['system'].startswith((shared_claims.SYSTEM, shared_claims.COMMON_SYSTEM))
                        for _, req in reused_runner.calls))
                    self.saved = {}; self.embeddings = []
                    staged_runner = RawRunner()
                    staged = self.process(staged_runner, discovery_mode='shared', membership_mode='raw',
                        verification_contract=contract, shared_records=cached, shared_memberships=result['memberships'])
                    self.assertEqual(staged['agent_inputs']['bundle'], expected_bundle)
                    self.assertFalse(staged['nomination_batches'])
                    self.assertEqual(self.embeddings, ['sources'])
                    self.assertFalse(any(req['system'].startswith((shared_claims.COMMON_SYSTEM, raw.SYSTEM,
                        verification.FOCUS, verification.ALIGNED_EVIDENCE)) for _,req in staged_runner.calls))
                    from commentscope.factory import source_entailment
                    from test_source_entailment import nli_response
                    source_rows=list({s['id']:s for b in result['memberships'] for s in b['sources']}.values())
                    request=source_entailment.invocation(result['memberships'])
                    response=nli_response(request)
                    proof=source_entailment.batch(source_rows,result['candidates'],result['memberships'],response)
                    self.saved={};self.embeddings=[]
                    guarded=self.process(RawRunner(),discovery_mode='shared',membership_mode='raw',
                        verification_contract=contract,shared_records=cached,shared_memberships=[proof],
                        source_entailment_required=True)
                    self.assertEqual(len(guarded['agent_inputs']['compiled']['profiles']),2)
                    self.saved={};self.embeddings=[]
                    with self.assertRaises(ValueError):
                        self.process(RawRunner(),discovery_mode='shared',membership_mode='raw',
                            verification_contract=contract,shared_records=cached,
                            shared_memberships=result['memberships'],source_entailment_required=True)

    def test_malformed_extraction_batch_is_preserved_not_partial_success_or_retry(self):
        runner = ScriptedRunner(fail_extraction=True); output = self.process(runner)
        self.assertEqual(len(output['errors']), 6)
        self.assertEqual(len(output['unextracted_source_ids']), 6)
        self.assertEqual(len(runner.calls), 6)
        self.assertFalse(output['candidates'])
        self.assertFalse(output['agent_inputs']['compiled']['profiles'])

    def test_unavailable_prior_metadata_is_held_without_fabricating_response_or_retry(self):
        from commentscope.factory.shared_admission import PriorRequestUnavailable
        class MissingMetadata(ScriptedRunner):
            def call(self,stage,req):
                if req['system'].startswith(oa.META):raise PriorRequestUnavailable('known prior interruption')
                return super().call(stage,req)
        output=self.process(MissingMetadata())
        self.assertFalse(output['arguments']);self.assertFalse(output['agent_inputs']['compiled']['profiles'])
        self.assertTrue(any(h['reason']=='prior_request_unavailable_no_retry' for h in output['capacity_holds']))
        self.assertFalse(any(e['stage']=='argument-node-metadata' for e in output['errors']))

    def test_merged_candidate_keeps_both_bindings_of_identical_route_request(self):
        from commentscope.factory import raw_membership as raw, raw_membership_verification as verification
        from test_raw_membership import decision
        comments = list(self.snapshot.comments)
        comments[1] = replace(comments[1], text_original='Approve P because Reason 1 matters.')
        self.snapshot = replace(self.snapshot, comments=tuple(comments))
        def position(text): return text.replace('Approve P', 'Adopt P').split(' because ')[0].strip().rstrip('.')
        class MergeRunner(ScriptedRunner):
            def call(self, stage, req):
                data, system = req['data'], req['system']
                if system.startswith(raw.SYSTEM):
                    value = decision(relation='supported' if position(data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text']) == position(data['CANDIDATE']['text']) else 'opposed')
                elif system.startswith(verification.ROUTE): value = {'role': 'subject_position'}
                elif system.startswith(verification.EVIDENCE): value = {'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                elif system.startswith(cc.SYSTEM):
                    value = {'decisions': [{'pair_id': p['pair_id'], 'relation': 'equivalent' if position(p['A']['text']) == position(p['B']['text']) else 'opposed'} for p in data['PAIRS']]}
                elif system.startswith(oa.ALIGN):
                    value = {'relation': 'equivalent' if position(data['SOURCE_POSITION']) == position(data['CANDIDATE']) else 'different'}
                else: return super().call(stage, req)
                self.calls.append((stage, req))
                return {'output': value, 'raw': 'authored fixture only', 'errors': []}
        result = self.process(MergeRunner(), membership_mode='raw')
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        merged = next(c for c in result['candidates'] if len(c['aliases']) == 2)
        routes = [v for k, v in self.saved.items() if k.startswith('bound/raw-candidate-route-') and v['candidate']['id'] == merged['id']]
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0]['request_sha256'], routes[1]['request_sha256'])
        self.assertNotEqual(routes[0]['candidate'], routes[1]['candidate'])
        self.assertEqual(routes[-1]['candidate'], merged)
        for record in routes:
            self.assertEqual(record, verification.bind_route(record['candidate'], {'output': record['output']}))

    def test_one_bad_original_cannot_erase_other_sources_or_trigger_retry(self):
        runner = ScriptedRunner(fail_source='0'); output = self.process(runner)
        self.assertEqual(output['unextracted_source_ids'], ['0'])
        self.assertEqual({r['source']['id'] for r in output['extractions']}, {'1','2','3','4','5'})
        requests = [req for stage, req in runner.calls if stage.startswith('extract-')]
        self.assertEqual(len(requests), 6)
        self.assertTrue(all(len(req['data']['ORIGINALS']) == 1 for req in requests))
        self.assertTrue(all('VIDEO_CONTEXT_ONLY' in req['data']['ORIGINALS'][0] for req in requests))


if __name__ == '__main__': unittest.main()
