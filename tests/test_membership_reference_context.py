"""Source identity continuity does not promote context to author evidence."""
from copy import deepcopy
import unittest

from commentscope.factory import raw_membership as raw,raw_membership_verification as v
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate,decision

VIDEO={'artifact_kind':'snapshot-video-context-20261017-v1','video_id':'synthetic-policy',
       'title':'Policy P explained','primary_language':'en'}


class MembershipReferenceContextTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':'It may reduce fees.','parent':None,'video_context':deepcopy(VIDEO)}
        self.target=candidate(self.source,'Policy P may reduce fees.')
        self.proof=raw.bind(self.source,self.target,{'output':decision()})
        self.value={'reference_basis':'supplied_context','target_alignment':'aligned',
            'source_basis':'own_assertion','verdict':'fully_stated','basis':'Own prediction; context identifies the policy.'}

    def bind(self,proof=None,**changes):
        return v.bind_evidence(proof or self.proof,{'output':{**self.value,**changes}},
                               v.FULL_SCOPE,protocol=v.QUALIFIED_CONTEXT)

    def test_exact_video_identity_reaches_evidence_but_stays_out_of_selected_assertions(self):
        req=v.evidence_request(self.proof,v.FULL_SCOPE,protocol=v.QUALIFIED_CONTEXT)
        self.assertEqual(req['data']['VIDEO_CONTEXT_ONLY'],VIDEO)
        self.assertEqual(req['data']['OWN_CONTEXT'],self.source['text'])
        self.assertEqual(req['data']['OWN_EVIDENCE'],self.proof['evidence'])
        self.assertNotIn(VIDEO['title'],str(req['data']['OWN_EVIDENCE']))
        self.assertNotIn('passed',req['data']);self.assertNotIn('relation',req['data'])
        self.assertTrue(self.bind()['passed'])
        self.assertEqual(self.bind()['request_sha256'],digest(req))

    def test_previous_omission_contract_and_request_identity_remain_separate(self):
        old=v.evidence_request(self.proof,v.FULL_SCOPE,protocol=v.QUALIFIED)
        new=v.evidence_request(self.proof,v.FULL_SCOPE,protocol=v.QUALIFIED_CONTEXT)
        self.assertNotIn('VIDEO_CONTEXT_ONLY',old['data'])
        self.assertNotEqual(digest(old),digest(new))
        focus=next(iter(v.route_request(self.target,self.source,version=v.FULL_SCOPE)['data']['FOCUS_TOKENS']))
        route=v.bind_route(self.target,{'output':{'focus_token':focus,'focus_domain':'substantive_issue',
            'role':'subject_position','interpretation':'clear'}},self.source,version=v.FULL_SCOPE)
        old_evidence=v.bind_evidence(self.proof,{'output':self.value},v.FULL_SCOPE,protocol=v.QUALIFIED)
        record=v.assessment(self.proof,route,old_evidence,version=v.FULL_SCOPE)
        v.validate(record)
        record['evidence_check']['protocol']=v.QUALIFIED_CONTEXT
        with self.assertRaises(ValueError):v.validate(record)

    def test_missing_or_ambiguous_references_and_parent_only_assertions_remain_blocked(self):
        for change in ({'reference_basis':'missing_or_ambiguous'},{'target_alignment':'unresolved'},
                {'target_alignment':'different_target'},{'source_basis':'parent_only'},
                {'source_basis':'inferred_not_stated'},{'verdict':'extra_assertion'}):
            with self.subTest(change=change):self.assertFalse(self.bind(**change)['passed'])

    def test_title_does_not_supply_an_absent_payment_comparator(self):
        source={**self.source,'text':'They pay tenants more than that.'}
        proof=raw.bind(source,candidate(source,source['text']),{'output':decision()})
        record=self.bind(proof)
        self.assertFalse(record['passed'])
        self.assertIn('payment_comparator_without_supplied_quantity',record['guards'])

    def test_modality_and_approximation_vetoes_still_override_positive_model(self):
        for original,target,guard in (
                ('Policy P may reduce fees.','Policy P should be introduced.','forecast_or_possibility_is_not_a_demand'),
                ('Policy P should be introduced.','Policy P may reduce fees.','demand_does_not_state_a_forecast'),
                ('The program is nearly ready.','The program is ready.','selected_approximation_not_preserved')):
            source={**self.source,'text':original}
            proof=raw.bind(source,candidate(source,target),{'output':decision()})
            with self.subTest(original=original):
                record=self.bind(proof);self.assertFalse(record['passed']);self.assertIn(guard,record['guards'])

    def test_different_original_video_cannot_replace_bound_source_or_cache_identity(self):
        changed=deepcopy(self.proof);changed['source']['video_context']['video_id']='different'
        with self.assertRaises(ValueError):self.bind(changed)
        source={**self.source,'video_context':{**VIDEO,'title':'Policy Q explained'}}
        proof=raw.bind(source,candidate(source,self.target['text']),{'output':decision()})
        self.assertNotEqual(self.bind()['request_sha256'],self.bind(proof)['request_sha256'])

    def test_missing_video_is_explicit_and_old_contracts_do_not_accept_new_flag(self):
        source={k:v for k,v in self.source.items() if k!='video_context'}
        proof=raw.bind(source,candidate(source,self.target['text']),{'output':decision()})
        req=v.evidence_request(proof,v.FULL_SCOPE,protocol=v.QUALIFIED_CONTEXT)
        self.assertIsNone(req['data']['VIDEO_CONTEXT_ONLY'])
        with self.assertRaises(ValueError):v.evidence_request(proof,v.ALIGNED,protocol=v.QUALIFIED_CONTEXT)


if __name__=='__main__':unittest.main()
