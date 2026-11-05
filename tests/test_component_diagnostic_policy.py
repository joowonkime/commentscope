"""Diagnostic warnings may allow spending on a fresh run, never approve outputs."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
import unittest

from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory import argument_dependencies as deps
from commentscope.providers import scoped_authorization as auth,openrouter_decisions as od
from commentscope.storage import write_json_exclusive as write
from experiments import jev_transfer_controls as transfer,openrouter_factory_pipeline as executor
from test_jev_audit_integration import receipt
import test_openrouter_factory_pipeline as fixtures


class DiagnosticPolicyTests(unittest.TestCase):
    setUp=fixtures.OpenRouterExecutorTests.setUp

    def diagnostic(self):
        directory=self.root/'diagnostic';scope=self.root/'scope.json';now=datetime.now(timezone.utc)
        self.policy['maximum_usd']='50';write(self.root/'policy.json',self.policy)
        write(scope,{'version':auth.VERSION,'tasks':['TASK-005','TASK-006'],'gates':['G1','G2','G3'],
            'started_at':now.isoformat(),'deadline':(now+timedelta(hours=1)).isoformat(),'maximum_additional_usd':'8',
            'shared_policy_file':str(self.root/'policy.json'),'chat_deployment':self.deployment,
            'decisions_deployment':od.DEPLOYMENT,'transfer_directory':str(directory.resolve())})
        patch.object(od,'preflight',return_value={}).start()
        manifest={p:sha(p) for p in transfer.SEMANTIC_FILES}
        patch.object(transfer,'source_code_hashes',return_value=manifest).start()
        transfer.prepare(directory,scope);plan=read_json(directory/'plan.json');checks=[];rows=[]
        for case in plan['fixture']['sources']:
            selected=[]
            for task in deps.tasks(case['record'],case['cores']):
                raw=[]
                for payload in deps.requests(task):
                    labels={**{'kind_'+k:v for k,v in case['expected_kinds'].items()},
                            **{'authorship_'+k:v for k,v in case['expected_authorship'].items()}}
                    for target,values in (case['expected_local'] if task['kind']=='local' else case['expected_core']).items():
                        labels.update({'relation_'+target+'_'+a:'necessary_fact' for a in values})
                    if case['id']=='T6' and task['kind']=='core':labels['relation_C1_U3']='none'
                    raw.append(receipt(payload,{k:v for k,v in labels.items() if k in payload['questions']}))
                selected.append(deps.bind(task,raw))
            checks.extend(selected);rows.append(transfer.assess(case,selected))
        write(directory/'checks.json',checks)
        write(directory/'report.json',{'plan_sha256':sha(directory/'plan.json'),'cases':rows,'all_passed':False,
            'quality_gate_passed':False,'production_admission':False})
        return directory,plan['authorization']

    def test_progress_keeps_failure_and_guards_but_allows_fresh_run(self):
        directory,binding=self.diagnostic()
        with self.assertRaises(ValueError):executor.transfer_admission(binding)
        before=sha(directory/'report.json')
        inputs=executor.transfer_admission(binding,allow_component_warnings=True)
        self.assertIn(str((directory/'report.json').resolve()),inputs)
        self.assertFalse(read_json(directory/'report.json')['all_passed'])
        self.assertEqual(sha(directory/'report.json'),before)
        self.time_budget.call.assert_not_called()

    def test_nonsemantic_code_changes_do_not_require_paid_diagnostic_repetition(self):
        directory,binding=self.diagnostic()
        manifest={p:sha(p) for p in transfer.SEMANTIC_FILES}
        with patch.object(transfer,'source_code_hashes',return_value={**manifest,'experiments/new-executor.py':'a'*64}):
            with self.assertRaises(ValueError):transfer.replay_report(directory)
            self.assertFalse(transfer.replay_report(directory,historical_diagnostic=True)['all_passed'])

    def test_forged_pass_or_changed_receipt_is_not_a_diagnostic(self):
        directory,binding=self.diagnostic();p=directory/'report.json';report=read_json(p);report['all_passed']=True
        p.write_text(json.dumps(report))
        with self.assertRaises(ValueError):executor.transfer_admission(binding,allow_component_warnings=True)

    def test_another_money_owner_cannot_borrow_the_diagnostic(self):
        directory,binding=self.diagnostic();changed=deepcopy(binding);changed['sha256']='a'*64
        with self.assertRaises(ValueError):executor.transfer_admission(changed,allow_component_warnings=True)

    def test_warning_policy_requires_explicit_scoped_jev_and_is_part_of_plan(self):
        directory,binding=self.diagnostic()
        plan=executor.prepare(self.run_dir,self.deployment,self.materials,self.policy,8,discovery_mode='free',
            scope_file=binding['file'],argument_audit_protocol=executor.argument_observations.JEV_SPLIT,
            allow_component_warnings=True,agent_source_policy='verified_subset')
        self.assertEqual(plan['component_diagnostic_policy'],'record_and_continue')
        self.assertEqual(plan['agent_source_policy'],'verified_subset')
        executor.validate(self.run_dir,plan)
        self.assertEqual(plan['scope_ids'],list('ABCDEFGHIJKL'))
        self.assertFalse(plan['cross_run_response_reuse']);self.assertFalse(plan['quality_gate_passed'])
        self.time_budget.call.assert_not_called()
        with self.assertRaises(ValueError):executor.prepare(self.root/'bad',self.deployment,self.materials,self.policy,8,
            allow_component_warnings=True)


if __name__=='__main__':unittest.main()
