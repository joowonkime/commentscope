from copy import deepcopy
from unittest import TestCase

from commentscope.factory import substantive_contribution as sc
from test_raw_membership import candidate


class SubstantiveContributionTests(TestCase):
    def setUp(self):
        self.source={'id':'a','text':'If funding is secured, I support free school meals.',
                     'parent':{'id':'p','text':'A parent claim is context, not this author evidence.'}}
        self.target=candidate(self.source,self.source['text'])

    def result(self,kind='issue_stance_or_effect',interpretation='clear'):
        return {'output':{'claim_relation':kind,'interpretation':interpretation}}

    def test_full_original_parent_and_candidate_are_preserved_without_prior_verdict(self):
        req=sc.request(self.target,self.source)
        self.assertEqual(req['data']['CANDIDATE']['text'],self.source['text'])
        self.assertEqual(req['data']['ORIGIN_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'],self.source['parent'])
        self.assertEqual(set(req['data']),{'CANDIDATE','ORIGIN_CONTEXT_ONLY'})
        self.assertEqual(sc.validate(sc.bind(self.target,self.source,self.result()))['origin'],self.source)

    def test_changed_original_or_proof_cannot_reuse_a_positive(self):
        wrong=deepcopy(self.source);wrong['parent']['text']='Changed context'
        with self.assertRaises(ValueError):sc.request(self.target,wrong)
        record=sc.bind(self.target,self.source,self.result());record['request_sha256']='changed'
        with self.assertRaises(ValueError):sc.validate(record)

    def test_failed_missing_or_unknown_output_cannot_become_a_positive(self):
        for result in ({'errors':['transport_error']},{'output':{}},self.result('unknown'),self.result(interpretation='unknown')):
            with self.subTest(result=result),self.assertRaises(ValueError):sc.bind(self.target,self.source,result)
        record=sc.bind(self.target,self.source,self.result(interpretation='uncertain'))
        self.assertFalse(record['passed']);self.assertFalse(record['semantic_approval']);self.assertFalse(record['factual_verification'])

    def test_content_version_preserves_context_and_rejects_cross_version_proofs(self):
        old=sc.request(self.target,self.source)
        current=sc.request(self.target,self.source,sc.CONTENT)
        self.assertEqual(old['data'],current['data'])
        self.assertNotEqual(old['system'],current['system'])
        result={'output':{'assertion_kind':'public_issue_claim','reference_target':'named_or_context_resolved'}}
        record=sc.bind(self.target,self.source,result,sc.CONTENT)
        self.assertEqual(sc.validate(record),record)
        with self.assertRaises(ValueError):sc.bind(self.target,self.source,self.result(),sc.CONTENT)
        with self.assertRaises(ValueError):sc.bind(self.target,self.source,result)
        for version in (sc.VERSION,'unknown'):
            changed=deepcopy(record);changed['artifact_kind']=version
            with self.subTest(version=version),self.assertRaises(ValueError):sc.validate(changed)
        for value in ('missing_or_ambiguous','unknown'):
            changed=deepcopy(result);changed['output']['reference_target']=value
            if value=='unknown':
                with self.assertRaises(ValueError):sc.bind(self.target,self.source,changed,sc.CONTENT)
            else:self.assertFalse(sc.bind(self.target,self.source,changed,sc.CONTENT)['passed'])
