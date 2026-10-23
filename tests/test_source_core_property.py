from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_core_property as prop, claim_frame as cf
from test_raw_membership import candidate


class FocusedPropertyTests(TestCase):
    def setUp(self):
        self.source = {'id':'source','text':'It should cover everyone. The policy helps concentration.',
            'parent':{'id':'parent','text':'The city is considering free school meals.'}}
        self.candidate = candidate(self.source,'It should cover everyone.')

    def test_existing_commitment_and_scope_definitions_are_reused(self):
        for task in ('commitment','scope'):
            self.assertEqual(prop.SYSTEMS[task],cf.TASK_SYSTEMS[task])
            self.assertEqual(prop.SCHEMAS[task],cf.TASK_SCHEMAS[task])
        self.assertEqual(prop.core_request('commitment','Cash might help.')['data'],{'TEXT':['Cash might help.']})

    def test_each_request_contains_only_its_property_and_original_context_boundary(self):
        for task in prop.SYSTEMS:
            req=prop.source_request(task,self.candidate,self.source)
            self.assertEqual(req['data']['TEXT'],[self.candidate['text']])
            self.assertEqual(req['data']['ORIGINAL_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'],self.source['parent'])
            self.assertEqual(set(req['schema']['properties']), {'scope','status'} if task=='scope' else {task})
        with self.assertRaises(ValueError):prop.core_request('invented','Cash might help.')

    def test_reason_cannot_escape_selected_literal_even_with_full_original_present(self):
        for quote in ['The policy helps concentration.','free school meals']:
            with self.assertRaises(ValueError):
                prop.bind_source('reason_quotes',self.candidate,self.source,{'output':{'reason_quotes':[quote]}})
        record=prop.bind_source('reason_quotes',self.candidate,self.source,{'output':{'reason_quotes':[]}})
        self.assertEqual(prop.validate(record),record)

    def test_cross_task_context_or_text_tampering_and_unknown_values_are_rejected(self):
        record=prop.bind_core('scope','People could benefit.',{'output':{'status':'atomic','scope':'population'}})
        self.assertEqual(prop.validate(record),record);self.assertFalse(record['membership_vote'])
        for key,value in [('core','A specific person could benefit.'),('property','voice'),('original_context_visible',True)]:
            altered=deepcopy(record);altered[key]=value
            with self.assertRaises((ValueError,KeyError)):prop.validate(altered)
        with self.assertRaises(ValueError):prop.bind_core('commitment','Cash might help.',{'output':{'commitment':'certain'}})
        with self.assertRaises(ValueError):prop.bind_core('target','A plan.',{'output':{'target':'identified'},'errors':['transport']})
