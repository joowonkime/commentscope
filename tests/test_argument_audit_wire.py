from copy import deepcopy
import json
import unittest

from commentscope.factory import owned_arguments as oa, source_arguments as sa
from commentscope.factory import argument_audit_wire as wire
import test_owned_arguments as fixture


class ArgumentAuditWireTests(unittest.TestCase):
    def setUp(self):
        helper = fixture.OwnedArgumentTests()
        helper.setUp()
        self.record = sa.bind_links(helper.record())
        self.records = [self.record]
        self.core = oa.bind_core(helper.candidate, {'output': {
            'kind': 'value', 'entity': 'P', 'time_ids': []}})
        self.cores = [self.core]
        self.tasks = sa.audit_tasks(self.records, self.cores)

    def request(self, tasks=None):
        return sa.audit_request(self.records, self.cores,
                                self.tasks if tasks is None else tasks,
                                protocol=sa.ADDRESSED_AUDIT)

    def result(self, tasks=None, verdict='supported'):
        return {'output': {'decisions': [
            {'task_id': t['task_id'], 'verdict': verdict,
             'basis': 'The supplied source retains this declaration.'}
            for t in self.request(tasks)['data']['TASKS']]}}

    def bind(self, result, tasks=None):
        return sa.bind_audit(self.records, self.cores,
                             self.tasks if tasks is None else tasks, result,
                             protocol=sa.ADDRESSED_AUDIT)

    def test_addresses_preserve_all_units_and_ownership_without_mutating_records(self):
        before = deepcopy((self.records, self.cores, self.tasks))
        old = sa.audit_request(self.records, self.cores, self.tasks)
        new = self.request()
        source = new['data']['SOURCES'][0]
        units = source['UNITS']
        self.assertEqual([u['text'] for u in units],
                         [u['text'] for u in self.record['units']])
        self.assertEqual(source['ORIGINAL']['ORIGINAL_SEGMENTS'],
                         old['data']['SOURCES'][0]['ORIGINAL']['ORIGINAL_SEGMENTS'])
        self.assertEqual(units[0]['candidate_roles'], {'C1': 'core_restatement'})
        self.assertEqual([u['candidate_ids'] for u in units[1:]], [[], []])
        self.assertEqual(units[1]['ownership_family'], units[2]['ownership_family'])
        self.assertNotEqual(units[0]['ownership_family'], units[2]['ownership_family'])
        self.assertEqual(source['CANDIDATES'][0]['id'], 'C1')
        self.assertEqual([t['TARGET'] for t in new['data']['TASKS'][:-1]],
                         [u['id'] for u in units])
        self.assertEqual(before, (self.records, self.cores, self.tasks))
        self.assertLess(len(json.dumps(new['data'])), len(json.dumps(old['data'])))

    def test_single_unit_task_keeps_other_positions_and_their_reasons_visible(self):
        req = self.request(self.tasks[:1])
        self.assertEqual(len(req['data']['SOURCES'][0]['UNITS']), 3)
        self.assertEqual(len(req['data']['TASKS']), 1)
        self.assertIn('Start immediately', str(req['data']))
        self.assertIn('because fairness matters.', str(req['data']))

    def test_addresses_do_not_replace_prose_or_cross_source_local_dependencies(self):
        old = sa.audit_request(self.records, self.cores, self.tasks)['data']['SOURCES']
        payload = deepcopy(old)
        # Exercise the pure view with repeated local IDs in different sources.
        second = deepcopy(payload[0])
        second['ORIGINAL']['source_id'] = 'other'
        second['UNITS'][0]['id'] = 'other-unit'
        payload.append(second)
        literal_id = self.core['candidate']['id']
        payload[0]['UNITS'][0]['text'] = literal_id
        payload[0]['UNITS'][1]['requires'] = ['U3']
        payload[0]['UNITS'][0]['core_requires_for'] = [literal_id]
        tasks = [self.tasks[0], {'task_id': 'other-unit', 'source_id': 'other', 'kind': 'unit'}]
        sources, tasks = wire.project(payload, tasks)
        self.assertEqual(sources[0]['UNITS'][0]['text'], literal_id)
        self.assertEqual(sources[0]['UNITS'][1]['requires'], ['U3'])
        self.assertEqual(sources[0]['UNITS'][0]['core_requires_for'], ['C1'])
        self.assertEqual([(t['source_id'], t['TARGET']) for t in tasks],
                         [('s', 'U1'), ('other', 'U1')])

    def test_negative_verdict_and_its_basis_bind_to_original_task(self):
        audit = self.bind(self.result(verdict='unsupported'))
        verdicts = sa.audit_verdicts(self.records, self.cores, [audit])
        self.assertEqual(verdicts, {t['task_id']: 'unsupported' for t in self.tasks})
        self.assertEqual(audit['protocol'], sa.ADDRESSED_AUDIT)
        self.assertTrue(all(r['basis'] for r in audit['output']['decisions']))
        audit['response']['decisions'][0]['basis'] = 'Changed after binding.'
        with self.assertRaises(ValueError):
            sa.audit_verdicts(self.records, self.cores, [audit])

    def test_missing_basis_unknown_address_and_protocol_are_rejected(self):
        for change in (lambda r: r['output']['decisions'][0].pop('basis'),
                       lambda r: r['output']['decisions'][0].update(basis=' '),
                       lambda r: r['output']['decisions'][0].update(basis=' '*240+'x'),
                       lambda r: r['output']['decisions'][0].update(basis=None),
                       lambda r: r['output']['decisions'][0].update(task_id='foreign')):
            result = self.result()
            change(result)
            with self.assertRaises(ValueError):
                self.bind(result)
        with self.assertRaises(ValueError):
            sa.audit_request(self.records, self.cores, self.tasks, protocol='unknown')

    def test_legacy_audits_remain_verifiable_with_original_request_and_response(self):
        req = sa.audit_request(self.records, self.cores, self.tasks)
        result = {'output': {'decisions': [
            {'task_id': t['task_id'], 'verdict': 'supported'}
            for t in req['data']['TASKS']]}}
        audit = sa.bind_audit(self.records, self.cores, self.tasks, result)
        self.assertNotIn('protocol', audit)
        self.assertEqual(sa.audit_verdicts(self.records, self.cores, [audit]),
                         {t['task_id']: 'supported' for t in self.tasks})
