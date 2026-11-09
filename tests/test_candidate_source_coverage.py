"""A refused candidate cannot poison separately verified source content."""
from copy import deepcopy
import unittest

from commentscope.factory import minimal_agents as ma,source_arguments as sa,owned_arguments as oa
from commentscope.factory import owner_observations as owners,argument_observations as obs
from commentscope.factory import argument_dependencies as deps
from commentscope.factory.automatic_contract import digest
from experiments.grounding_contract_demo import MODEL
import test_typed_verification as fixture


class CandidateSourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.TypedOwnerIntegrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.h=self.f.h;self.good=self.h.candidates[0]['id'];self.bad=self.h.candidates[1]['id']
        rebuilt=[]
        for linked in self.h.records:
            e=linked['extraction_record'];alignments=[]
            for a in e['alignments']:
                c=next(c for c in self.h.candidates if digest(c)==a['candidate_sha256'])
                if c['id']==self.bad:
                    n=next(n for n in e['graph']['nodes'] if n['id']==a['node_id'])
                    a=oa.bind_alignment(e['graph'],n,c,{'output':{'relation':'different'}},a['qualifications'])
                alignments.append(a)
            rebuilt.append(sa.bind_links(oa.declare(e['graph'],e['batch_candidates'],e['support_batches'],
                e['metadata'],alignments,discourse=e.get('discourse'))))
        self.h.records=rebuilt
        self.f.tasks=sa.audit_tasks(rebuilt,self.h.cores)
        self.f.owners=owners.tasks(rebuilt,self.h.cores,self.f.tasks,protocol=owners.SOURCE_BOUND)
        self.audits=self.f.audits()

    def prepare(self,policy='candidate_verified_subset',audits=None):
        return ma.prepare(self.h.snapshot,self.h.candidates,self.h.memberships,self.h.records,self.h.cores,
            self.audits if audits is None else audits,model=MODEL,source_policy=policy)

    def changed_coverage(self):
        result=[]
        for a in self.audits:
            response=deepcopy(a['response'])
            if a['tasks'][0]['kind']=='coverage':response['observations'][0]['source_coverage']='incomplete'
            result.append(sa.bind_audit(self.h.records,self.h.cores,a['tasks'],{'output':response},
                protocol=a['protocol'],core_checks=a['core_checks'],owner_checks=a['owner_checks'],
                dependency_checks=a['dependency_checks']))
        return result

    def test_failed_other_candidate_does_not_erase_complete_owned_target(self):
        for policy in ('all_members','verified_subset'):
            self.assertFalse(self.prepare(policy)['compiled']['profiles'])
        out=self.prepare()
        self.assertEqual([p['candidate_id'] for p in out['compiled']['profiles']],[self.good])
        self.assertEqual(out['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertTrue(all(r['status']=='unresolved' for r in self.h.records))
        self.assertTrue(any(h['candidate_id']==self.bad for h in out['source_holds']))
        self.assertTrue(out['source_coverage_projections'])
        self.assertFalse(out['quality_gate_passed'])

    def test_actual_source_coverage_failure_is_never_rescued(self):
        self.assertFalse(self.prepare(audits=self.changed_coverage())['compiled']['profiles'])

    def test_modified_observation_is_rejected_before_projection(self):
        changed=deepcopy(self.audits)
        changed[0]['response']['observations'][0]['conditions_fidelity']='no'
        with self.assertRaises(ValueError):self.prepare(audits=changed)

    def test_batched_reordered_observations_use_the_exact_coverage_address(self):
        dependencies=[c for r in self.h.records for c in fixture.graph(r,self.h.cores)]
        owner_checks=[owners.bind(t,{'output':{'relation':'equivalent','basis':'same_assertion',
            'owner_world':'real_world','candidate_world':'real_world'}}) for t in self.f.owners]
        audits=[]
        for record in self.h.records:
            tasks=[t for t in self.f.tasks if t['source_id']==record['source']['id']]
            request=sa.audit_request(self.h.records,self.h.cores,tasks,protocol=obs.TYPED_CHAT,core_checks=self.h.checks)
            helper=deepcopy(request)
            for task in helper['data']['TASKS']:
                if task['kind']=='unit':task['LINK_TARGETS']=[]
            result=self.h.result(helper)
            for row in result['output']['observations']:
                row.pop('dependency_fidelity');row.pop('owner_relations',None)
                row['basis']='coverage_agrees' if 'source_coverage' in row else 'normative_assertion'
            result['output']['observations'].reverse()
            audits.append(sa.bind_audit(self.h.records,self.h.cores,tasks,result,protocol=obs.TYPED_CHAT,
                core_checks=self.h.checks,owner_checks=owner_checks,dependency_checks=dependencies))
        self.assertEqual([p['candidate_id'] for p in self.prepare(audits=audits)['compiled']['profiles']],[self.good])

    def test_existing_unit_condition_veto_still_blocks_the_target(self):
        self.assertFalse(self.prepare(audits=self.f.audits('conditions_fidelity'))['compiled']['profiles'])

    def test_owner_world_veto_is_not_replaced_by_positive_coverage(self):
        changed=[]
        for a in self.audits:
            checks=[owners.bind(c['task'],{'output':{**c['response'],'owner_world':'fictional_world'}})
                    for c in a['owner_checks']]
            changed.append(sa.bind_audit(self.h.records,self.h.cores,a['tasks'],{'output':a['response']},
                protocol=a['protocol'],core_checks=a['core_checks'],owner_checks=checks,
                dependency_checks=a['dependency_checks']))
        self.assertFalse(self.prepare(audits=changed)['compiled']['profiles'])

    def test_source_language_failure_remains_global(self):
        changed=[]
        for linked in self.h.records:
            e=linked['extraction_record'];metadata=[]
            for n,m in zip(e['graph']['nodes'],e['metadata'],strict=True):
                metadata.append(oa.bind_metadata(e['graph'],n,{'output':{**m['response'],'source_language':'uncertain'}}))
            changed.append(sa.bind_links(oa.declare(e['graph'],e['batch_candidates'],e['support_batches'],
                metadata,e['alignments'],discourse=e.get('discourse'))))
        self.h.records=changed
        self.f.tasks=sa.audit_tasks(changed,self.h.cores)
        self.f.owners=owners.tasks(changed,self.h.cores,self.f.tasks,protocol=owners.SOURCE_BOUND)
        self.assertFalse(self.prepare(audits=self.f.audits())['compiled']['profiles'])


class CandidateGraphCoverageTests(unittest.TestCase):
    def test_unrelated_core_conflict_does_not_become_the_selected_core_coverage(self):
        record,cores=fixture.case();record['candidate_ids'].append('other')
        cores.append({'candidate':{'id':'other','text':'Adopt another policy.'},'output':{'kind':'value'}})
        for unit in record['units']:unit['candidate_ids']=['core']
        checks=fixture.graph(record,cores,{'kind_C2':'fact'})
        self.assertIn('unresolved_type_conflict',deps.guards(record,cores,checks,typed=True)['coverage'])
        self.assertFalse(deps.guards(record,cores,checks,typed=True,candidate_id='core')['coverage'])
        self.assertIn('unresolved_type_conflict',deps.guards(record,cores,checks,typed=True,candidate_id='other')['coverage'])

    def test_own_missing_factual_premise_remains_held(self):
        record,cores=fixture.case('fact',declared_fact=False)
        for unit in record['units']:unit['candidate_ids']=['core']
        checks=fixture.graph(record,cores,{'relation_C1_U1':'restatement'})
        self.assertIn('missing_factual_prerequisite',deps.guards(record,cores,checks,typed=True,candidate_id='core')['coverage'])


class CandidatePipelineTests(unittest.TestCase):
    def test_policy_reaches_the_complete_pipeline_and_keeps_legacy_audits_conservative(self):
        import test_minimal_pipeline as pipeline_fixture
        helper=pipeline_fixture.MinimalPipelineTests();helper.setUp()
        output=helper.process(pipeline_fixture.ScriptedRunner(),agent_source_policy='candidate_verified_subset')
        self.assertEqual(len(output['agent_inputs']['compiled']['profiles']),2)
        self.assertEqual(output['agent_inputs']['source_policy'],'candidate_verified_subset')
        self.assertFalse(output['agent_inputs']['source_coverage_projections'])
        self.assertFalse(output['quality_gate_passed'])


if __name__=='__main__':unittest.main()
