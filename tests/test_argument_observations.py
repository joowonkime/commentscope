from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import argument_observations as obs
from commentscope.factory import minimal_claims as mc, minimal_agents as ma
from commentscope.factory import source_arguments as sa, owned_arguments as oa
from commentscope.factory import explicit_discourse as ed
from commentscope.ingestion import load_snapshot
from experiments.grounding_contract_demo import MODEL
from test_minimal_factory import extraction, membership
import test_owned_arguments as fixture
import test_minimal_agents as legacy_fixture


class ArgumentObservationTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{'id': f's{i}', 'text': f'Adopt P because {reason} matters.', 'parent': None}
                        for i, reason in enumerate(('fairness', 'privacy', 'access'))]
        self.candidates = mc.candidates(extraction(self.sources, {
            s['id']: ['Adopt P.', 'Support adopting P.'] for s in self.sources}))
        self.memberships = []; self.records = []
        for source in self.sources:
            h = fixture.OwnedArgumentTests(); h.setUp()
            h.source = source; h.graph = ed.parse(source); h.candidates = self.candidates
            h.members = [membership([source], self.candidates, [
                {'source_id': source['id'], 'candidate_id': c['id']} for c in self.candidates])]
            self.memberships.extend(h.members)
            metadata = h.metadata()
            for i, node in enumerate(h.graph['nodes']):
                values = deepcopy(metadata[i]['response'])
                values['entity'] = 'P' if node['kind'] == 'statement' else node['span']['text'].split()[1]
                metadata[i] = oa.bind_metadata(h.graph, node, {'output': values})
            alignments = []
            for node in h.graph['nodes']:
                if node['kind'] != 'statement': continue
                for c in self.candidates:
                    h.candidate = c; h.cid = c['id']
                    alignments.append(h.alignment(node, 'equivalent'))
            self.records.append(sa.bind_links(oa.declare(h.graph, self.candidates, h.members, metadata, alignments)))
        self.cores = [oa.bind_core(c, {'output': {'kind': 'value', 'entity': 'P', 'time_ids': []}})
                      for c in self.candidates]
        self.checks = [obs.bind_core(c, self.core_result()) for c in self.cores]
        base = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        self.snapshot = replace(base, usage=replace(base.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(base.comments[0], comment_id=s['id'], text_original=s['text'], parent_id=None)
                           for s in self.sources))

    def core_result(self, kind='value'):
        return {'output': {'observations': [{'actual_kind': kind, 'time_ids': [],
            'entity_fidelity': 'yes', 'conditions_fidelity': 'yes', 'basis': 'Synthetic normative position.'}]}}

    def request(self, tasks, checks=None):
        return sa.audit_request(self.records, self.cores, tasks, protocol=sa.OBSERVED_AUDIT,
                                core_checks=self.checks if checks is None else checks)

    def result(self, req, *, bad_alias=None, bad_kind=False):
        rows = []
        for task in req['data']['TASKS']:
            row = {'task_id': task['task_id'], 'dependency_fidelity': 'yes', 'basis': 'Authored synthetic source observation.'}
            if task['kind'] == 'coverage':
                row.update(actual_source_language='en', source_coverage='complete')
            else:
                target = task['SOURCE_TARGET']
                row.update(actual_kind='fact' if bad_kind else 'value', time_ids=[],
                    entity_fidelity='yes', conditions_fidelity='yes', actual_authorship='asserted_or_endorsed',
                    actual_function='reason' if target['text'].startswith('because ') else 'position',
                    owner_relations=[{'candidate_id': c['id'],
                        'relation': 'different' if c['id'] == bad_alias else 'equivalent'} for c in task['LINK_TARGETS']])
            rows.append(row)
        return {'output': {'observations': rows}}

    def audits(self, *, bad_cid=None, bad_kind=False, checks=None):
        checks = self.checks if checks is None else checks
        bad_alias = None if bad_cid is None else 'C'+str(sorted(c['id'] for c in self.candidates).index(bad_cid)+1)
        result = []
        for task in sa.audit_tasks(self.records, self.cores):
            req = self.request([task], checks)
            response = self.result(req, bad_alias=bad_alias, bad_kind=bad_kind)
            result.append(sa.bind_audit(self.records, self.cores, [task], response,
                                       protocol=sa.OBSERVED_AUDIT, core_checks=checks))
        return result

    def prepare(self, audits):
        return ma.prepare(self.snapshot, self.candidates, self.memberships, self.records,
                          self.cores, audits, model=MODEL)

    def test_source_classification_hides_previous_kind_and_time_and_keeps_original(self):
        task = sa.audit_tasks(self.records, self.cores)[0]
        req = self.request([task]); target = req['data']['TASKS'][0]['SOURCE_TARGET']
        self.assertNotIn('kind', target); self.assertNotIn('time_ids', target)
        for source in req['data']['SOURCES']:
            self.assertNotIn('source_language', source)
            self.assertTrue(all('kind' not in u and 'scope' not in u for u in source['UNIT_INVENTORY']))
        coverage = next(t for t in sa.audit_tasks(self.records, self.cores) if t['kind'] == 'coverage')
        self.assertNotIn('Support adopting P.', str(self.request([coverage])['data']))
        self.assertNotIn('ORIGINAL', str(obs.core_request(self.cores[0])['data']))

    def test_all_source_and_candidate_checks_can_compile_both_toy_candidates(self):
        out = self.prepare(self.audits())
        self.assertFalse(out['argument_holds'])
        self.assertEqual(len(out['compiled']['profiles']), 2)
        self.assertFalse(out['quality_gate_passed'])

    def test_one_bad_candidate_link_does_not_approve_it_or_block_the_other_candidate(self):
        bad = self.candidates[1]['id']; good = self.candidates[0]['id']
        audits = self.audits(bad_cid=bad); out = self.prepare(audits)
        self.assertEqual([p['candidate_id'] for p in out['compiled']['profiles']], [good])
        self.assertEqual([h['candidate_id'] for h in out['argument_holds']], [bad])
        self.assertTrue(all(len(p['supported_canonical_ids']) == 3 for p in out['map']['opinion_map']['perspectives']))
        self.assertTrue(any(r['verdict'] != 'supported' for a in audits for r in a['output']['decisions']))

    def test_source_kind_failure_still_blocks_every_candidate_using_that_unit(self):
        out = self.prepare(self.audits(bad_kind=True))
        self.assertFalse(out['compiled']['profiles'])
        self.assertEqual(len(out['argument_holds']), 2)
        self.assertTrue(all(len(p['supported_canonical_ids']) == 3 for p in out['map']['opinion_map']['perspectives']))

    def test_core_kind_failure_is_isolated_and_never_rewrites_declared_kind(self):
        checks = deepcopy(self.checks)
        checks[1] = obs.bind_core(self.cores[1], self.core_result('fact'))
        self.assertFalse(checks[1]['passed'])
        self.assertEqual(self.cores[1]['output']['kind'], 'value')
        out = self.prepare(self.audits(checks=checks))
        self.assertEqual([p['candidate_id'] for p in out['compiled']['profiles']], [self.candidates[0]['id']])
        self.assertIn('core_fidelity_not_verified', out['argument_holds'][0]['reasons'])

    def test_missing_or_changed_core_checks_cannot_be_used_as_source_approval(self):
        tasks = sa.audit_tasks(self.records, self.cores)[:1]
        for checks in ([], self.checks[:1]):
            with self.assertRaises(ValueError): self.request(tasks, checks)
        changed = deepcopy(self.checks); changed[0]['response']['observations'][0]['actual_kind'] = 'fact'
        with self.assertRaises(ValueError): self.request(tasks, changed)

    def test_changed_source_observations_or_candidate_verdicts_fail_replay(self):
        audits = self.audits(); changed = deepcopy(audits)
        changed[0]['response']['observations'][0]['actual_kind'] = 'fact'
        with self.assertRaises(ValueError): self.prepare(changed)
        changed = deepcopy(audits)
        row = next(r for a in changed for r in a['output']['decisions'] if r.get('candidate_verdicts'))
        row['candidate_verdicts'][self.candidates[0]['id']] = 'unsupported'
        with self.assertRaises(ValueError): self.prepare(changed)

    def test_unknown_fields_ids_duplicate_links_and_invalid_observations_are_rejected(self):
        tasks = sa.audit_tasks(self.records, self.cores)[:1]; req = self.request(tasks)
        for change in (lambda r: r['output']['observations'][0].update(task_id='foreign'),
                       lambda r: r['output']['observations'][0].update(actual_kind='approved'),
                       lambda r: r['output']['observations'][0].update(time_ids=['missing']),
                       lambda r: r['output']['observations'][0].update(basis=' '*240+'x'),
                       lambda r: r['output']['observations'][0]['owner_relations'].__setitem__(1,
                           deepcopy(r['output']['observations'][0]['owner_relations'][0]))):
            response = self.result(req); change(response)
            with self.assertRaises(ValueError):
                sa.bind_audit(self.records, self.cores, tasks, response,
                              protocol=sa.OBSERVED_AUDIT, core_checks=self.checks)
        core_response = self.core_result(); core_response['output']['observations'][0]['task_id'] = 'foreign'
        with self.assertRaises(ValueError): obs.bind_core(self.cores[0], core_response)

    def test_empirical_fact_cannot_be_relabelled_as_value_to_skip_fact_screening(self):
        source = {'id': 'fact', 'text': 'The archive charges seven dollars per visit.', 'parent': None}
        candidate = mc.candidates(extraction([source], {'fact': [source['text']]}))[0]
        wrong = oa.bind_core(candidate, {'output': {'kind': 'value', 'entity': 'The archive', 'time_ids': []}})
        correct = oa.bind_core(candidate, {'output': {'kind': 'fact', 'entity': 'The archive', 'time_ids': []}})
        self.assertFalse(obs.bind_core(wrong, self.core_result('fact'))['passed'])
        self.assertTrue(obs.bind_core(correct, self.core_result('fact'))['passed'])
        self.assertEqual(wrong['output']['kind'], 'value')

    def test_conflicting_owner_and_core_kinds_cannot_pass_as_equivalent_assertions(self):
        bad = self.candidates[1]
        self.cores[1] = oa.bind_core(bad, {'output': {'kind': 'fact', 'entity': 'P', 'time_ids': []}})
        self.checks[1] = obs.bind_core(self.cores[1], self.core_result('fact'))
        self.assertTrue(self.checks[1]['passed'])
        out = self.prepare(self.audits())
        self.assertEqual([c['id'] for c in out['bundle']['candidates']], [self.candidates[0]['id']])
        self.assertIn('argument_not_verified', out['argument_holds'][0]['reasons'])

    def test_time_omission_in_a_validly_bound_declaration_is_not_silently_repaired(self):
        h = fixture.OwnedArgumentTests(); h.setUp(); original = h.record()
        metadata = deepcopy(original['metadata']); graph = h.graph
        node = next(n for n in graph['nodes'] if n['span']['text'] == 'Start immediately')
        index = next(i for i, m in enumerate(metadata) if m['node_id'] == node['id'])
        response = {**metadata[index]['response'], 'time_ids': []}
        metadata[index] = oa.bind_metadata(graph, node, {'output': response})
        record = sa.bind_links(oa.declare(graph, h.candidates, h.members, metadata, original['alignments']))
        core = oa.bind_core(h.candidate, {'output': {'kind': 'value', 'entity': 'P', 'time_ids': []}})
        checks = [obs.bind_core(core, self.core_result())]
        task = next(t for t in sa.audit_tasks([record], [core])
                    if t['task_id'] == next(u['id'] for u in record['units'] if u['source_node_id'] == node['id']))
        req = sa.audit_request([record], [core], [task], protocol=sa.OBSERVED_AUDIT, core_checks=checks)
        result = self.result(req); result['output']['observations'][0]['time_ids'] = ['T1']
        audit = sa.bind_audit([record], [core], [task], result, protocol=sa.OBSERVED_AUDIT, core_checks=checks)
        self.assertEqual(audit['output']['decisions'][0]['source_verdict'], 'unsupported')
        self.assertIn('declared_time_mismatch', audit['output']['decisions'][0]['guards'])
        self.assertEqual(record['units'][1]['scope']['time'], '')

    def test_generated_legacy_arguments_cannot_claim_fixed_source_parent_proofs(self):
        legacy = legacy_fixture.MinimalAgentTests(); legacy.setUp()
        records = legacy.records(); cores = legacy.cores
        checks = [obs.bind_core(c, self.core_result()) for c in cores]
        with self.assertRaisesRegex(ValueError, 'source-owned'):
            sa.audit_request(records, cores, sa.audit_tasks(records, cores)[:1],
                             protocol=sa.OBSERVED_AUDIT, core_checks=checks)
