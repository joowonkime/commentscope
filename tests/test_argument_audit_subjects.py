from copy import deepcopy
import unittest

from commentscope.factory import source_arguments as sa, owned_arguments as oa
from commentscope.factory import explicit_discourse as ed, minimal_claims as mc
import test_owned_arguments as fixture
from test_minimal_factory import extraction, membership


class ArgumentAuditSubjectTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixture.OwnedArgumentTests(); self.helper.setUp()
        self.records = [sa.bind_links(self.helper.record())]
        self.cores = [oa.bind_core(self.helper.candidate, {'output': {
            'kind': 'value', 'entity': 'P', 'time_ids': []}})]
        self.tasks = sa.audit_tasks(self.records, self.cores)

    def request(self, tasks):
        return sa.audit_request(self.records, self.cores, tasks, protocol=sa.SUBJECT_AUDIT)

    def test_unlinked_reason_is_audited_against_its_actual_owner_not_another_core(self):
        req = self.request([self.tasks[2]])
        task = req['data']['TASKS'][0]
        self.assertEqual(task['TARGET']['text'], 'because fairness matters.')
        self.assertEqual(task['TARGET']['role'], 'reason')
        self.assertEqual(task['OWNER_POSITION']['text'], 'Start immediately')
        self.assertFalse(task['LINKED_CANDIDATES'])
        self.assertNotIn('CANDIDATES', req['data']['SOURCES'][0])
        self.assertEqual([u['text'] for u in req['data']['SOURCES'][0]['UNITS']],
                         [u['text'] for u in self.records[0]['units']])
        self.assertIn('Adopt P.', str(req['data']['SOURCES'][0]['ORIGINAL']))

    def test_additional_unlinked_position_is_not_presented_as_a_candidate_restatement(self):
        req = self.request([self.tasks[1]])
        task = req['data']['TASKS'][0]
        self.assertEqual(task['TARGET']['text'], 'Start immediately')
        self.assertFalse(task['TARGET']['candidate_ids'])
        self.assertEqual(task['OWNER_POSITION'], task['TARGET'])
        self.assertFalse(task['LINKED_CANDIDATES'])
        self.assertEqual(task['audit_subject'], 'unlinked_original_position')

    def test_concession_keeps_its_owner_and_link_role_instead_of_requiring_text_equality(self):
        h = self.helper
        h.source = {'id': 's', 'text': 'Adopt P even though costs may rise.', 'parent': None}
        h.graph = ed.parse(h.source)
        h.candidates = mc.candidates(extraction([h.source], {'s': ['Adopt P']}))
        h.candidate = h.candidates[0]; h.cid = h.candidate['id']
        h.members = [membership([h.source], h.candidates, [{'source_id': 's', 'candidate_id': h.cid}])]
        record = h.record(); metadata = h.metadata()
        for i, node in enumerate(h.graph['nodes']):
            if node['kind'] != 'statement':
                values = {**metadata[i]['response'], 'kind': 'prediction'}
                properties = oa.metadata_request(h.graph, node)['schema']['properties']
                metadata[i] = oa.bind_metadata(h.graph, node, {'output': {k: values[k] for k in properties}})
        self.records = [sa.bind_links(oa.declare(h.graph, h.candidates, h.members, metadata, record['alignments']))]
        self.cores = [oa.bind_core(h.candidate, {'output': {'kind': 'value', 'entity': 'P', 'time_ids': []}})]
        tasks = sa.audit_tasks(self.records, self.cores)
        req = self.request([tasks[1]])
        task = req['data']['TASKS'][0]
        self.assertEqual(task['TARGET']['text'], 'even though costs may rise.')
        self.assertEqual(task['TARGET']['kind'], 'prediction')
        self.assertEqual(task['OWNER_POSITION']['text'], 'Adopt P')
        self.assertEqual(task['LINKED_CANDIDATES'][0]['link_role'], 'concession')
        self.assertEqual(task['LINKED_CANDIDATES'][0]['text'], 'Adopt P')

    def test_coverage_still_sees_every_unit_and_core_declaration(self):
        req = self.request([self.tasks[-1]])
        task = req['data']['TASKS'][0]
        self.assertEqual(task['TARGET'], 'all_source_units_and_candidate_links')
        self.assertEqual(len(task['CANDIDATES']), 1)
        self.assertEqual(task['CANDIDATES'][0]['text'], 'Adopt P.')
        self.assertEqual(len(req['data']['SOURCES'][0]['UNITS']), 3)
        self.assertEqual(req['data']['SOURCES'][0]['extraction_status'], 'complete')
        self.assertEqual(req['data']['SOURCES'][0]['dependency_status'], 'complete')

    def test_negative_verdicts_still_bind_to_exact_tasks_and_keep_history(self):
        before = deepcopy((self.records, self.cores, self.tasks))
        req = self.request(self.tasks)
        result = {'output': {'decisions': [
            {'task_id': t['task_id'], 'verdict': 'unsupported', 'basis': 'A declaration differs from the source.'}
            for t in req['data']['TASKS']]}}
        audit = sa.bind_audit(self.records, self.cores, self.tasks, result, protocol=sa.SUBJECT_AUDIT)
        self.assertEqual(sa.audit_verdicts(self.records, self.cores, [audit]),
                         {t['task_id']: 'unsupported' for t in self.tasks})
        self.assertEqual(before, (self.records, self.cores, self.tasks))
        audit['output']['decisions'][0]['basis'] = 'Rewritten after binding.'
        with self.assertRaises(ValueError):
            sa.audit_verdicts(self.records, self.cores, [audit])
