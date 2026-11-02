"""Source kind, owner equivalence and core kind each retain their own veto."""
from copy import deepcopy
import unittest

from commentscope.factory import source_arguments as sa, argument_observations as obs
from commentscope.factory import owner_observations as owners
import test_argument_observations as fixture


class OwnerObservationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ArgumentObservationTests()
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.tasks = sa.audit_tasks(self.h.records, self.h.cores)
        self.owners = owners.tasks(self.h.records, self.h.cores, self.tasks)

    def checks(self, bad=None):
        return [owners.bind(t, {'output': {
            'owner_world': 'real_world', 'candidate_world': 'real_world',
            'relation': 'different' if t['candidate']['id'] == bad else 'equivalent',
            'basis': 'different_scope' if t['candidate']['id'] == bad else 'same_assertion'}})
            for t in self.owners]

    def audits(self, checks=None, bad_kind=False, core_checks=None):
        checks = self.checks() if checks is None else checks
        core_checks = self.h.checks if core_checks is None else core_checks
        result = []
        for t in self.tasks:
            req = sa.audit_request(self.h.records, self.h.cores, [t], protocol=sa.SPLIT_AUDIT,
                                   core_checks=core_checks)
            helper = deepcopy(req)
            for task in helper['data']['TASKS']:
                if task['kind'] == 'unit': task['LINK_TARGETS'] = []
            response = self.h.result(helper, bad_kind=bad_kind)
            for row in response['output']['observations']:
                row.pop('owner_relations', None)
                row['basis'] = 'coverage_agrees' if t['kind'] == 'coverage' else 'normative_assertion'
            result.append(sa.bind_audit(self.h.records, self.h.cores, [t], response,
                protocol=sa.SPLIT_AUDIT, core_checks=core_checks, owner_checks=checks))
        return result

    def test_source_observations_do_not_compare_the_ground_with_candidates(self):
        ground = next(t for t in self.tasks if t['kind'] == 'unit' and
                      next(u for r in self.h.records for u in r['units'] if u['id'] == t['task_id'])['role'] == 'reason')
        req = sa.audit_request(self.h.records, self.h.cores, [ground], protocol=sa.SPLIT_AUDIT,
                               core_checks=self.h.checks)
        self.assertNotIn('LINK_TARGETS', req['data']['TASKS'][0])
        self.assertNotIn('owner_relations', str(req['schema']))
        for task in self.owners:
            pair = owners.request(task)
            self.assertNotIn('SOURCE_TARGET', pair['data'])
            self.assertNotIn('because', pair['data']['OWNER_POSITION']['text'])
            self.assertIn('Adopt P', pair['data']['OWNER_POSITION']['text'])
        self.assertEqual(len(self.owners), 6)  # Same owner is audited once per source/core, not per ground.

    def test_separate_valid_checks_reach_agents_without_semantic_approval(self):
        out = self.h.prepare(self.audits())
        self.assertEqual(len(out['compiled']['profiles']), 2)
        self.assertFalse(out['quality_gate_passed'])

    def test_refused_or_missing_owner_never_becomes_approval_or_blocks_another_core(self):
        bad = self.h.candidates[1]['id']; good = self.h.candidates[0]['id']
        for checks in (self.checks(bad), [c for c in self.checks() if c['task']['candidate']['id'] != bad]):
            out = self.h.prepare(self.audits(checks))
            self.assertEqual([p['candidate_id'] for p in out['compiled']['profiles']], [good])
            self.assertEqual([h['candidate_id'] for h in out['argument_holds']], [bad])

    def test_positive_owner_cannot_override_wrong_source_or_core_kind(self):
        self.assertEqual(self.h.prepare(self.audits(bad_kind=True))['compiled']['profiles'], [])
        checks = deepcopy(self.h.checks)
        checks[1] = obs.bind_core(self.h.cores[1], self.h.core_result('fact'))
        out = self.h.prepare(self.audits(core_checks=checks))
        self.assertEqual(len(out['compiled']['profiles']), 1)

    def test_modified_owner_source_candidate_or_decision_fails_replay(self):
        audits = self.audits()
        for modify in (lambda a: a['owner_checks'][0]['response'].update(relation='different'),
                       lambda a: a['owner_checks'][0]['task']['source'].update(text='Foreign.'),
                       lambda a: a['owner_checks'][0]['task']['owner_position'].update(text='Foreign.'),
                       lambda a: a['owner_checks'][0]['task']['candidate'].update(text='Foreign.')):
            changed = deepcopy(audits); target = next(a for a in changed if a['owner_checks'])
            modify(target)
            with self.assertRaises(ValueError): self.h.prepare(changed)

    def test_duplicate_foreign_or_inconsistent_owner_observations_never_verify_a_link(self):
        task = self.owners[0]
        for value in ({'relation': 'uncertain', 'basis': 'uncertain'},
                      {'relation': 'equivalent', 'basis': 'different_condition'},
                      {'relation': 'different', 'basis': 'same_assertion'}):
            self.assertFalse(owners.bind(task, {'output': {'owner_world': 'real_world',
                'candidate_world': 'real_world', **value}})['passed'])
        with self.assertRaises(ValueError):
            owners.bind(task, {'output': {'relation': 'equivalent', 'basis': 'approval',
                'owner_world': 'real_world', 'candidate_world': 'real_world'}})
        checks = self.checks()
        with self.assertRaises(ValueError): self.audits(checks + [deepcopy(checks[0])])
        changed = deepcopy(task); changed['owner_position']['text'] = 'A different assertion.'
        with self.assertRaises(ValueError): owners.request(changed)

    def test_world_mismatch_or_uncertainty_vetoes_even_a_positive_equivalence(self):
        task = self.owners[0]
        for left, right in [('fictional_world', 'real_world'), ('real_world', 'hypothetical_world'),
                            ('uncertain', 'uncertain')]:
            check = owners.bind(task, {'output': {'relation': 'equivalent', 'basis': 'same_assertion',
                                'owner_world': left, 'candidate_world': right}})
            self.assertFalse(check['passed'])
            self.assertEqual(check['response']['relation'], 'equivalent')
        with self.assertRaises(ValueError):
            owners.bind(task, {'output': {'relation': 'equivalent', 'basis': 'same_assertion',
                'owner_world': 'invented', 'candidate_world': 'invented'}})

    def test_closed_basis_categories_keep_the_old_bound_and_do_not_shorten_failed_prose(self):
        core = self.h.cores[0]
        req = obs.core_request(core, protocol=obs.CORE_CODED)
        schema = req['schema']['properties']['observations']['items']['properties']['basis']
        self.assertLessEqual(max(map(len, schema['enum'])), 240)
        result = self.h.core_result(); result['output']['observations'][0]['basis'] = 'normative_assertion'
        bound = obs.bind_core(core, result, protocol=obs.CORE_CODED)
        self.assertTrue(bound['passed']); self.assertFalse(bound['semantic_approval'])
        for text in ('A valid-length but unselected explanation.', 'x'*241):
            failed = deepcopy(result); failed['output']['observations'][0]['basis'] = text
            with self.assertRaises(ValueError): obs.bind_core(core, failed, protocol=obs.CORE_CODED)
        self.assertIn('maxLength', str(obs.core_request(core)))  # Historical request unchanged.


if __name__ == '__main__': unittest.main()
