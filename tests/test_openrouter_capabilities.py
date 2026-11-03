"""Preflight checks the actual deployment, including omitted sampling controls."""
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from commentscope.providers import openrouter
from experiments import openrouter_factory_pipeline as executor


class ProviderCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {'version':openrouter.VERSION,'model':'example/model','context':8192,
            'call_seconds':30,'provider':{'only':['chosen'],'max_price':{'prompt':2,'completion':10,'request':0}}}
        self.endpoint = {'tag':'chosen','provider_name':'Chosen','status':0,'context_length':8192,
            'pricing':{'prompt':'0.000002','completion':'0.00001','request':'0'},
            'supported_parameters':['structured_outputs','response_format','max_tokens','temperature','reasoning']}

    def check(self, deployment=None, endpoint=None):
        data = json.dumps({'data':{'endpoints':[endpoint or self.endpoint]}}).encode()
        with patch.object(executor,'build_opener') as opener:
            opener.return_value.open.return_value=BytesIO(data)
            return executor.provider_preflight(deployment or self.deployment)

    def test_default_sampling_and_both_reasoning_forms_match_transmitted_fields(self):
        self.assertEqual(openrouter.required_parameters(self.deployment),
                         {'structured_outputs','response_format','max_tokens','temperature'})
        for reasoning in [{'enabled':False},{'effort':'low'}]:
            deployment={**self.deployment,'temperature':None,'reasoning':reasoning}
            self.assertNotIn('temperature',openrouter.Client(deployment).payload('s',{}, {},32))
            self.assertEqual(openrouter.required_parameters(deployment),
                             {'structured_outputs','response_format','max_tokens','reasoning'})

    def test_omitted_temperature_is_accepted_only_when_not_transmitted(self):
        endpoint=deepcopy(self.endpoint);endpoint['supported_parameters'].remove('temperature')
        deployment={**self.deployment,'temperature':None,'reasoning':{'effort':'low'}}
        self.assertEqual(self.check(deployment,endpoint)['tag'],'chosen')
        with self.assertRaises(ValueError):self.check(self.deployment,endpoint)

    def test_all_actual_capabilities_and_price_context_checks_remain_mandatory(self):
        deployment={**self.deployment,'temperature':None,'reasoning':{'effort':'low'}}
        for missing in ['reasoning','max_tokens','response_format','structured_outputs']:
            endpoint=deepcopy(self.endpoint);endpoint['supported_parameters'].remove(missing)
            with self.subTest(missing=missing),self.assertRaises(ValueError):self.check(deployment,endpoint)
        for mutation in [lambda e:e.update(status=1),lambda e:e.update(context_length=8191),
                         lambda e:e['pricing'].update(prompt='0.000003')]:
            endpoint=deepcopy(self.endpoint);mutation(endpoint)
            with self.assertRaises(ValueError):self.check(deployment,endpoint)


if __name__=='__main__':unittest.main()
