"""Compact transport keeps the canonical source/claim validation boundaries."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc


def output(text='Adopt P.', *, evidence='S000', conditions='', author='asserted', status='covered'):
    return {'output': {'s': status, 'c': [
        {'t': text, 'e': evidence, 'k': conditions, 'a': author}]}}


class CompactClaimTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'child', 'text': 'Adopt P. Equity matters.',
                       'parent': {'id': 'parent', 'text': 'A different author reason.'}}

    def test_flat_transport_preserves_only_child_evidence_and_original_context(self):
        req = compact.request(self.source)
        packet = req['data']['ORIGINALS'][0]
        self.assertEqual(packet['PARENT_CONTEXT_ONLY'], self.source['parent'])
        self.assertEqual(''.join(x['text'] for x in packet['ORIGINAL_SEGMENTS']), self.source['text'])
        schema = req['schema']; self.assertEqual(set(schema['properties']), {'s', 'c'})
        claim = schema['properties']['c']['items']
        self.assertEqual(claim['properties']['e']['type'], 'string')
        self.assertEqual(claim['properties']['k']['type'], 'string')
        self.assertNotIn('anyOf', str(schema))
        self.assertEqual(req['max_tokens'], 3072)

    def test_normalized_contract_and_text_ids_match_legacy_without_claiming_its_request_was_sent(self):
        bound = compact.bind(self.source, output())
        legacy = mc.bind_extraction([self.source], {'output': {'sources': [{
            'source_id': 'child', 'status': 'covered', 'claims': [{
                'text': 'Adopt P.', 'authorship': 'asserted', 'evidence_segment_ids': ['S000'],
                'essential_condition_segment_ids': []}]}]}})[0]
        self.assertEqual(bound['canonical_record'], legacy)
        self.assertEqual(bound['claims'], legacy['claims'])
        self.assertNotEqual(bound['request_sha256'], legacy['request_sha256'])
        self.assertEqual(mc.validate(bound), bound)
        self.assertEqual(mc.candidates([bound])[0]['id'], mc.claim_id('Adopt P.'))
        self.assertEqual(mc.validate(legacy), legacy)

    def test_reported_or_uncertain_content_never_becomes_a_nomination(self):
        for author in ('reported', 'uncertain'):
            self.assertEqual(mc.candidates([compact.bind(self.source, output(author=author))]), [])

    def test_conditions_bind_to_exact_child_segments(self):
        source = {**self.source, 'text': 'Adopt P. Only if funded.'}
        record = compact.bind(source, output('Adopt P only if funded.', conditions='S001'))
        self.assertEqual(record['claims'][0]['essential_conditions'][0]['text'], 'Only if funded.')
        self.assertEqual(record['claims'][0]['evidence'][0]['id'], 'S000')

    def test_invalid_addresses_and_unknown_fields_cannot_be_repaired(self):
        variants = [output(evidence=''), output(evidence='parent'), output(evidence='S999'),
                    output(evidence='S000 S000'), output(conditions='S999'),
                    output(evidence='S000,S001'), output(evidence='S000  S001')]
        extra = output(); extra['output']['source_id'] = 'other'; variants.append(extra)
        extra = output(); extra['output']['c'][0]['reason'] = 'invented'; variants.append(extra)
        extra = output(); extra['output']['c'][0]['e'] = ['S000']; variants.append(extra)
        for result in variants:
            with self.subTest(result=result), self.assertRaises(ValueError):
                compact.bind(self.source, result)

    def test_original_capacity_authorship_and_status_rules_remain_enforced(self):
        variants = [output('x'*601), output(author='unknown'), output(status='unknown'),
                    output(status='non_substantive'), output(status='unresolved')]
        variants.append({'output': {'s': 'covered', 'c': []}})
        repeated = output(); repeated['output']['c'] *= 2; variants.append(repeated)
        too_many = output(); too_many['output']['c'] *= 17; variants.append(too_many)
        failed = output(); failed['errors'] = ['transport_error']; variants.append(failed)
        for result in variants:
            with self.subTest(result=result), self.assertRaises(ValueError):
                compact.bind(self.source, result)

    def test_wire_source_or_canonical_record_tampering_fails_replay(self):
        record = compact.bind(self.source, output())
        for mutate in (lambda r: r['source'].update(text='Different.'),
                       lambda r: r['source']['parent'].update(text='Changed parent.'),
                       lambda r: r.update(request_sha256='0'*64),
                       lambda r: r['response']['c'][0].update(t='Reject P.'),
                       lambda r: r['claims'][0].update(text='Reject P.'),
                       lambda r: r['canonical_record'].update(status='partial')):
            changed = deepcopy(record); mutate(changed)
            with self.assertRaises(ValueError): mc.validate(changed)

    def test_one_partial_supplement_preserves_old_claims_and_actual_wire_provenance(self):
        first = compact.bind(self.source, output(status='partial'))
        second = compact.bind(self.source, output('Equity matters.', evidence='S001'), previous=first)
        self.assertEqual([c['text'] for c in second['claims']], ['Adopt P.', 'Equity matters.'])
        self.assertEqual(second['additional_passes'], 1)
        self.assertEqual(mc.validate(second), second)
        self.assertTrue(compact.request(self.source, previous=first)['data']['PREVIOUS'])
        with self.assertRaises(ValueError): compact.request(self.source, previous=second)
        with self.assertRaises(ValueError): compact.bind(self.source, output(), previous=first)
        with self.assertRaises(ValueError): compact.request({**self.source, 'id': 'other'}, previous=first)
        with self.assertRaises(ValueError): compact.bind(self.source, {'output': {'s': 'non_substantive', 'c': []}}, previous=first)


class CompactPipelineTests(unittest.TestCase):
    def fixture(self):
        import test_minimal_pipeline as fixture
        helper = fixture.MinimalPipelineTests('test_complete_mock_path_two_distinct_agents_all_members_and_three_questions')
        helper.setUp(); self.addCleanup(helper.doCleanups)
        class Runner(fixture.ScriptedRunner):
            def call(self, stage, req):
                if req['system'].startswith(compact.PREFIX):
                    self.calls.append((stage, req))
                    source = req['data']['ORIGINALS'][0]
                    text = source['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.'
                    result = output(text)
                    if req['schema']['properties']['c']['items']['properties']['e']['type'] == 'object':
                        ids = [s['id'] for s in source['ORIGINAL_SEGMENTS']]
                        result['output']['c'][0].update(e={sid: sid == 'S000' for sid in ids},
                                                       k={sid: False for sid in ids})
                    elif 'pattern' in req['schema']['properties']['c']['items']['properties']['e']:
                        count = len(source['ORIGINAL_SEGMENTS'])
                        result['output']['c'][0].update(e='1'+'0'*(count-1), k='0'*count)
                    elif req['schema']['properties']['c']['items']['properties']['e']['type'] == 'array':
                        if 'v' in req['schema']['properties']: result['output']['v'] = []
                        else: result['output']['c'][0]['l'] = ''
                        result['output']['c'][0].update(e=['S000'], k=[])
                    if source['source_id'] == self.fail_source: result['output']['c'] = []
                    if 'm' in req['schema']['properties']:
                        result['output'] = {'c': result['output']['c'], 'm': False}
                    return result
                return super().call(stage, req)
        return helper, Runner

    def test_compact_discovery_reaches_owned_agents_and_assertion_only_equivalence(self):
        from commentscope.factory import candidate_consolidation as cc
        helper, Runner = self.fixture(); runner = Runner()
        result = helper.process(runner, extraction_protocol=compact.VERSION)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(all(r['artifact_kind'] == compact.VERSION for r in result['extractions']))
        self.assertTrue(all(r['protocol'] == cc.ASSERTION_ONLY for r in result['equivalences']))
        self.assertFalse(result['quality_gate_passed'])
        self.assertFalse(result['runtime_reference_labels'])

    def test_failed_source_is_preserved_without_discarding_other_originals_or_retrying(self):
        helper, Runner = self.fixture(); runner = Runner(fail_source='0')
        result = helper.process(runner, extraction_protocol=compact.VERSION)
        self.assertEqual(result['unextracted_source_ids'], ['0'])
        self.assertEqual(len(result['extractions']), 5)
        self.assertTrue(result['errors'])
        attempted = [r for _,r in runner.calls if r['system'].startswith(compact.PREFIX)
                     and r['data']['ORIGINALS'][0]['source_id'] == '0']
        self.assertEqual(len(attempted), 1)

    def test_masked_contract_reaches_agents_with_independent_assertion_only_checks(self):
        from commentscope.factory import candidate_consolidation as cc
        helper, Runner = self.fixture(); runner = Runner()
        result = helper.process(runner, extraction_protocol=compact.MASKED)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(all(r['artifact_kind'] == compact.MASKED for r in result['extractions']))
        self.assertTrue(all(r['protocol'] == cc.ASSERTION_ONLY for r in result['equivalences']))
        self.assertFalse(result['quality_gate_passed'])

    def test_indexed_contract_reaches_agents_without_changing_the_default(self):
        helper, Runner = self.fixture(); runner = Runner()
        result = helper.process(runner, extraction_protocol=compact.INDEXED)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(all(r['artifact_kind'] == compact.INDEXED for r in result['extractions']))
        self.assertFalse(result['quality_gate_passed'])

    def test_owner_refusal_remains_a_veto_in_the_indexed_pipeline(self):
        from commentscope.factory import owner_observations as owners, source_arguments as sa
        helper, Runner = self.fixture()
        class RefusingRunner(Runner):
            def call(self, stage, req):
                if req['system'].startswith(owners.SYSTEM) and req['data']['CANDIDATE']['text'] == 'Adopt P.':
                    self.calls.append((stage, req))
                    return {'output': {'relation': 'different', 'basis': 'different_scope',
                                       'owner_world': 'real_world', 'candidate_world': 'real_world'}}
                return super().call(stage, req)
        result = helper.process(RefusingRunner(), extraction_protocol=compact.INDEXED)
        self.assertFalse(result['errors'])
        profiles = result['agent_inputs']['compiled']['profiles']
        self.assertEqual(len(profiles), 1)
        self.assertTrue(all(a['protocol'] == sa.SPLIT_AUDIT for a in result['audits']))
        self.assertTrue(any(not c['passed'] for a in result['audits'] for c in a['owner_checks']))
        self.assertFalse(result['quality_gate_passed'])

    def test_segmented_pipeline_retains_owner_audits(self):
        from commentscope.factory import source_arguments as sa
        helper, Runner = self.fixture(); runner = Runner()
        result = helper.process(runner, extraction_protocol=compact.SEGMENTED)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(all(r['artifact_kind'] == compact.SEGMENTED for r in result['extractions']))
        self.assertTrue(all(a['protocol'] == sa.SPLIT_AUDIT for a in result['audits']))
        self.assertFalse(result['quality_gate_passed'])

    def test_unified_pipeline_retains_world_bilateral_and_owner_checks(self):
        self.assert_unified_pipeline(compact.UNIFIED)

    def test_proposal_pipeline_retains_world_bilateral_evidence_and_owner_checks(self):
        self.assert_unified_pipeline(compact.PROPOSALS)

    def assert_unified_pipeline(self, protocol):
        from commentscope.factory import source_arguments as sa, candidate_consolidation as cc
        from commentscope.factory import raw_membership as raw, raw_membership_verification as verification
        from commentscope.factory import statement_worlds as worlds, source_context_observations as contexts
        from test_raw_membership_source_context import observation
        helper, Runner = self.fixture()
        class RawRunner(Runner):
            def call(self, stage, req):
                system, data = req['system'], req['data']
                if system.startswith(contexts.SYSTEM):
                    value = {'source_use': 'substantive_assertion', 'reported_descriptors': []}
                elif system.startswith(worlds.SYSTEM): value = {'world': 'real_world', 'anchor': ''}
                elif system.startswith(raw.SYSTEM):
                    text = data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')
                    value = observation(); value.update(source_use='substantive_assertion',
                        relation='supported' if text == data['CANDIDATE']['text'].rstrip('.') else 'opposed')
                elif system.startswith(verification.FOCUS):
                    value = {'focus_token': 'T1', 'focus_domain': 'substantive_issue',
                             'role': 'subject_position', 'interpretation': 'clear'}
                elif system.startswith((verification.GROUNDED_EVIDENCE, verification.ALIGNED_EVIDENCE)):
                    value = {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                             'source_basis': 'own_assertion', 'verdict': 'fully_stated',
                             'basis': 'Authored synthetic own-evidence declaration.'}
                else: return super().call(stage, req)
                self.calls.append((stage, req))
                return {'output': value, 'raw': 'authored fixture only', 'errors': []}
        runner = RawRunner()
        result = helper.process(runner, extraction_protocol=protocol, membership_mode='raw',
                                verification_contract=verification.FULL_SCOPE)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(all(r['artifact_kind'] == protocol for r in result['extractions']))
        self.assertTrue(all(r['protocol'] == cc.BILATERAL for r in result['equivalences']))
        self.assertTrue(all(a['protocol'] == sa.SPLIT_AUDIT for a in result['audits']))
        self.assertTrue(all(a['raw']['artifact_kind'] == raw.WORLD_CONTEXT
                            for b in result['memberships'] for a in b['verified_assessments']))
        positive = [a for b in result['memberships'] for a in b['verified_assessments'] if a['passed']]
        self.assertTrue(positive)
        self.assertTrue(all(a['evidence_check']['protocol'] == verification.QUALIFIED for a in positive))
        self.assertFalse(result['quality_gate_passed'])

    def test_empty_proposal_preserves_source_without_retry_or_coverage_approval(self):
        helper, Runner = self.fixture(); runner = Runner(fail_source='0')
        result = helper.process(runner, extraction_protocol=compact.PROPOSALS)
        self.assertFalse(result['errors'])
        self.assertFalse(result['unextracted_source_ids'])
        self.assertEqual(len(result['extractions']), 6)
        empty = next(r for r in result['extractions'] if r['source']['id'] == '0')
        self.assertEqual(empty['status'], 'unresolved')
        self.assertEqual(empty['claims'], [])
        self.assertFalse(empty['semantic_approval'])
        calls = [req for _, req in runner.calls if req['system'].startswith(compact.PREFIX)
                 and req['data']['ORIGINALS'][0]['source_id'] == '0']
        self.assertEqual(len(calls), 1)

    def test_segmented_pipeline_vetoes_primary_equivalence_when_independent_check_finds_a_counterexample(self):
        from commentscope.factory import candidate_consolidation as cc, assertion_counterexamples as counter
        helper, Runner = self.fixture()
        class FalseMergeRunner(Runner):
            def call(self, stage, req):
                if req['system'].startswith(cc.SYSTEM):
                    self.calls.append((stage, req))
                    return {'output': {'decisions': [{'pair_id': p['pair_id'], 'relation': 'equivalent'}
                                                     for p in req['data']['PAIRS']]}}
                if req['system'].startswith(counter.SYSTEM):
                    self.calls.append((stage, req))
                    return {'output': {'a_scenario': 'Distinct asserted policy.', 'a_without_b': 'possible',
                                       'b_scenario': 'Different asserted policy.', 'b_without_a': 'possible'}}
                return super().call(stage, req)
        runner = FalseMergeRunner(); result = helper.process(runner, extraction_protocol=compact.SEGMENTED)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(any(req['system'].startswith(counter.SYSTEM) for _, req in runner.calls))
        for record in result['equivalences']:
            self.assertEqual(record['protocol'], cc.BILATERAL)
            self.assertTrue(record['assertion_checks'])
            self.assertTrue(all(r['model_relation'] == 'equivalent' and r['relation'] == 'uncertain'
                                for r in record['relations']))

    def test_independent_audits_close_one_original_without_changing_the_model_request(self):
        from commentscope.factory import source_arguments as sa
        from commentscope.factory.automatic_contract import digest
        helper, Runner = self.fixture()
        result = helper.process(Runner(), extraction_protocol=compact.INDEXED)
        arguments, cores = result['arguments'], result['cores']
        checks = {c['core_id']: c for a in result['audits'] for c in a['core_checks']}
        for audit in result['audits']:
            ids = {t['source_id'] for t in audit['tasks']}
            self.assertEqual(len(ids), 1)
            scoped = [r for r in arguments if r['source']['id'] in ids]
            self.assertEqual(audit['records_sha256'], digest(scoped))
            global_request = sa.audit_request(arguments, cores, audit['tasks'],
                protocol=sa.SPLIT_AUDIT, core_checks=list(checks.values()))
            self.assertEqual(audit['request_sha256'], digest(global_request))
            self.assertTrue(all(c['task']['source']['id'] in ids for c in audit['owner_checks']))
        from unittest.mock import patch
        with patch.object(sa, 'digest', wraps=digest) as hashing:
            sa.audit_verdicts(arguments, cores, result['audits'])
        self.assertEqual(sum(c.args[0] is arguments for c in hashing.call_args_list), 1)

    def test_protocol_is_explicit_and_cannot_change_a_literal_or_unknown_path(self):
        helper, Runner = self.fixture(); runner = Runner()
        for mode, protocol in [('literal', compact.VERSION), ('free', 'unknown')]:
            with self.assertRaises(ValueError):
                helper.process(runner, discovery_mode=mode, extraction_protocol=protocol)
        self.assertEqual(runner.calls, [])


if __name__ == '__main__': unittest.main()
