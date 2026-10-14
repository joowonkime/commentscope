import unittest
from unittest.mock import patch
from pathlib import Path
from experiments.reasoning_report import render


class ReasoningReportCountsTests(unittest.TestCase):
    def test_counts_and_runtime_are_not_hardcoded_to_old_trial(self):
        status={'planned_evaluation':100,'reference_positive':19,'observed_evaluation':14,
                'accepted_observed':1,'true_accepted_observed':0,'false_accepted_observed':['J5'],
                'missed_positive_observed':['J14'],'errors_observed':['J14'],
                'precision_best_possible':18/19,'retention_best_possible':18/19,
                'cannot_pass':True,'development_gate_passed':False}
        plan={'reference_source':'unused','rows':[],'evaluation_ids':[],
              'runtime':{'reasoning':'off','reasoning_budget':0,'max_tokens':180,'context':4096,'gpu_layers':'all'}}
        with patch('experiments.reasoning_report.checkpoint',return_value=status), \
             patch('experiments.reasoning_report.read_json',side_effect=[plan,{'labels':{},'reasons':{}}]):
            page=render(Path('unused'))
        self.assertIn('정상 지지19건',page)
        self.assertNotIn('정상 지지21건',page)
        self.assertNotIn('256token 제한 추론',page)
        self.assertIn('180',page)
        self.assertIn('호출 오류 관측',page)
        self.assertIn('사용자 중단',page)
