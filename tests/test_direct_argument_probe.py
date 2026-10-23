from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

from experiments import direct_argument_probe as p
from tests import test_candidate_completion_pipeline as existing
from commentscope.storage import write_json_exclusive as write
from commentscope.providers.local_nli import MODEL,REVISION


class DirectRunner(existing.SyntheticRunner):
    def call(self,stage,req,**kwargs):
        if stage=='direct-ground-selection':
            self.seq+=1
            return {'errors':[],'output':{'status':'selected','node_ids':[],'essential_node_ids':[]}}
        return super().call(stage,req,**kwargs)


class FactRunner(DirectRunner):
    def call(self,stage,req,**kwargs):
        if stage=='direct-ground-selection':
            self.seq+=1
            nid=next(n['node_id'] for parts in req['data']['SOURCE_SEGMENTS'].values() for n in parts if n['eligible'])
            return {'errors':[],'output':{'status':'selected','node_ids':[nid],'essential_node_ids':[nid]}}
        if stage=='ground-kind':
            self.seq+=1;return {'errors':[],'output':{'kind':'fact'}}
        if stage=='argument-audit':
            self.seq+=1
            return {'errors':[],'output':{'core_fidelity':'faithful','core_kind_matches':True,'major_premises':'preserved',
                'grounds':[{'node_id':g['node_id'],'role':'reason_for_core','kind_matches':True} for g in req['data']['SELECTED_GROUNDS']]}}
        if stage.startswith('detail-'):
            self.seq+=1;return {'errors':[],'output':{'verdict':'supported','reason':'Synthetic source support, not truth.'}}
        if stage.startswith('facts-'):
            self.seq+=1
            return {'metadata':{'model':MODEL,'revision':REVISION,'threshold':.8,'local_files_only':True,
                                'id2label':{'0':'entailment','1':'neutral','2':'contradiction'}},
                    'results':[{'id':c['id'],'pairs':[],'state':'unassessed','supporting_ids':[],'refuting_ids':[]}
                               for c in req['data']['cases']]}
        return super().call(stage,req,**kwargs)


class DirectArgumentProbeTests(unittest.TestCase):
    def run_component(self,tmp,fail=False,extra=False,facts=False):
        root=Path(tmp);source=root/'source';directory=root/'direct'
        existing.CandidateCompletionPipelineTests().run_synthetic(source,False)
        plan=p.read_json(source/'plan.json');plan['limits']['analysis_seconds']=p.SECONDS
        if facts:plan['classifier']={'name':MODEL,'revision':REVISION,'weights_sha256':'a'*64,'runtime_sha256':'b'*64}
        plan['tasks']=[t['proposal'] for t in p.read_json(source/'candidate-queue.json')]
        plan['cached_membership']={}
        for q in plan['tasks']:
            plan['cached_membership'][q['id']]=p.read_json(source/'candidates'/q['id']/'membership.json')
        if extra:
            unknown=deepcopy(plan['tasks'][0]);unknown['id']='unknown';plan['tasks'].append(unknown)
            negative=deepcopy(plan['tasks'][0]);negative['id']='negative';plan['tasks'].append(negative)
            m=deepcopy(plan['cached_membership'][plan['tasks'][0]['id']]);m['actual']={k:'unsupported' for k in m['actual']}
            plan['cached_membership']['negative']=m
        write(directory/'plan.json',plan)
        budget=Mock();budget.summary.return_value={'remaining_seconds':9000,'charged_seconds':0}
        runner=(FactRunner if facts else DirectRunner)(directory,plan,budget)
        with patch.object(p.downstream,'owned_server'),patch.object(DirectRunner,'audit_fails',fail):
            outcomes,compiled=p.run_tasks(directory,plan,runner)
        return outcomes,compiled,directory

    def test_same_post_membership_path_builds_all_profiles_without_source_extraction(self):
        with TemporaryDirectory() as tmp:
            outcomes,compiled,d=self.run_component(tmp,extra=True)
            self.assertEqual(len(compiled['profiles']),2)
            self.assertEqual([o['state'] for o in outcomes],['screened_input','screened_input',
                'upstream_membership_unprocessed','cached_insufficient_core_support'])
            self.assertFalse((d/'member-source-results').exists())
            self.assertEqual(len(list((d/'candidates').glob('*/direct-inventory.json'))),2)

    def test_failed_audit_cannot_be_bypassed(self):
        with TemporaryDirectory() as tmp:
            outcomes,compiled,d=self.run_component(tmp,fail=True)
            self.assertEqual(compiled['profiles'],[])
            self.assertTrue(all(o['state']=='argument_audit_failed' for o in outcomes))

    def test_unverified_major_facts_defer_without_dropping_selected_grounds(self):
        with TemporaryDirectory() as tmp:
            outcomes,compiled,d=self.run_component(tmp,facts=True)
            self.assertEqual(compiled['profiles'],[])
            self.assertTrue(all(o['state']=='fact_or_compilation_deferred' for o in outcomes))
            for f in (d/'candidates').glob('*/bundle.json'):
                b=p.read_json(f);core=next(c for c in b['claims'] if c['id'].endswith(':C'))
                self.assertEqual(len(core['requires']),1)
                self.assertEqual(len(b['checks']),1);self.assertEqual(b['checks'][0]['record']['state'],'unassessed')

    def test_followup_reserve_and_diagnostic_ceiling_limit_calls(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);plan={'limits':{'analysis_seconds':p.SECONDS}}
            write(root/'plan.json',plan);budget=Mock()
            budget.summary.return_value={'charged_seconds':100,'remaining_seconds':3663}
            runner=p.Runner(root,plan,budget)
            self.assertLessEqual(runner.timeout(900),597)
            budget.summary.return_value={'charged_seconds':690,'remaining_seconds':3073}
            self.assertEqual(runner.timeout(90),7)
            budget.summary.return_value={'charged_seconds':700,'remaining_seconds':3063}
            with self.assertRaises(TimeoutError):runner.timeout(90)
            budget.summary.return_value={'charged_seconds':200,'remaining_seconds':3003}
            with self.assertRaises(TimeoutError):runner.timeout(90)


if __name__=='__main__':unittest.main()
