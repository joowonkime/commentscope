from copy import deepcopy
from unittest import TestCase

from commentscope.factory import substantive_target as target
from test_raw_membership import candidate


class SubstantiveTargetTests(TestCase):
    def setUp(self):
        self.origin={'id':'reply','text':'Sounds reasonable.',
                     'parent':{'id':'parent','text':'Free school meals should include every child.'}}
        self.candidate=candidate(self.origin,self.origin['text'])
        self.result={'output':{'target_address':'PARENT','target_content':'public_issue_claim','target_closed':'yes'}}

    def test_context_address_is_exact_and_never_endorsement_proof(self):
        req=target.request(self.candidate,self.origin)
        self.assertEqual(req['data']['ORIGINAL_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'],self.origin['parent'])
        record=target.bind(self.candidate,self.origin,self.result)
        self.assertEqual(target.validate(record)['selected_target']['span']['text'],self.origin['parent']['text'])
        self.assertTrue(record['context_is_not_endorsement'])
        self.assertFalse(record['semantic_approval']);self.assertFalse(record['factual_verification'])

    def test_changed_context_or_selected_span_cannot_reuse_proof(self):
        changed=deepcopy(self.origin);changed['parent']['text']='Different parent'
        with self.assertRaises(ValueError):target.request(self.candidate,changed)
        record=target.bind(self.candidate,self.origin,self.result)
        record['selected_target']['span']['text']='Invented policy'
        with self.assertRaises(ValueError):target.validate(record)

    def test_unavailable_address_and_incomplete_or_failed_results_hold(self):
        for key,value in (('target_address','VIDEO_TITLE'),('target_content','unknown'),('target_closed','unknown')):
            changed=deepcopy(self.result);changed['output'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):target.bind(self.candidate,self.origin,changed)
        for key,value in (('target_address','unresolved'),('target_content','unidentified'),('target_closed','no')):
            changed=deepcopy(self.result);changed['output'][key]=value
            self.assertFalse(target.bind(self.candidate,self.origin,changed)['passed'])
        with self.assertRaises(ValueError):target.bind(self.candidate,self.origin,{'errors':['transport_error']})

    def test_split_parent_domain_uses_complete_parent_without_reply_or_old_verdict(self):
        selected=target.bind_selection(self.candidate,self.origin,{'output':{'target_address':'PARENT'}})
        req=target.domain_request(selected)
        self.assertEqual(req['data']['CANDIDATE']['text'],self.origin['parent']['text'])
        self.assertEqual(req['data']['ORIGIN_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'],None)
        self.assertNotIn(self.origin['text'],str(req['data']))
        self.assertEqual(set(req['data']),{'CANDIDATE','ORIGIN_CONTEXT_ONLY'})
        domain=target.bind_domain(selected,{'output':{'assertion_kind':'public_issue_claim','reference_target':'named_or_context_resolved'}})
        self.assertEqual(target.validate_domain(domain,selected),domain)
        other=target.bind_selection(self.candidate,self.origin,{'output':{'target_address':'SELF'}})
        with self.assertRaises(ValueError):target.validate_domain(domain,other)

    def test_split_unresolved_or_changed_selection_cannot_acquire_domain_proof(self):
        unresolved=target.bind_selection(self.candidate,self.origin,{'output':{'target_address':'unresolved'}})
        with self.assertRaises(ValueError):target.domain_request(unresolved)
        selected=target.bind_selection(self.candidate,self.origin,{'output':{'target_address':'PARENT'}})
        selected['selected_target']['span']['text']='Invented target'
        with self.assertRaises(ValueError):target.domain_request(selected)
