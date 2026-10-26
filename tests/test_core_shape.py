from unittest import TestCase
from commentscope.factory import raw_membership_verification as verification
from test_raw_membership import candidate


class CoreShapeTests(TestCase):
    def route(self,text,version):
        source={'id':'source','text':text,'parent':None}
        target=candidate(source,text)
        request=verification.route_request(target,source,version=version)
        positive={key:value['enum'][0] for key,value in request['schema']['properties'].items()}
        positive['focus_token']=next(token for token in request['schema']['properties']['focus_token']['enum'] if token!='unresolved')
        return verification.bind_route(target,{'output':positive},source,version=version)

    def test_full_scope_rejects_compound_core_despite_positive_model_routing(self):
        for text in ['Lower bus fares because commuters pay too much.',
                     'I favor bus service even though it may be expensive.']:
            result=self.route(text,verification.FULL_SCOPE)
            self.assertFalse(result['passed'])
            self.assertIn('compound_core_requires_separate_interpretation',result['guards'])

    def test_required_condition_is_preserved_and_not_rejected_as_a_reason(self):
        result=self.route('Lower bus fares only if operating grants rise.',verification.FULL_SCOPE)
        self.assertTrue(result['passed'])
        self.assertFalse(result['guards'])

    def test_frozen_aligned_route_contract_remains_replayable(self):
        result=self.route('Lower bus fares because commuters pay too much.',verification.ALIGNED)
        self.assertTrue(result['passed'])
