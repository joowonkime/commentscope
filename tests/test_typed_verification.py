"""Type/relation consistency and source-world boundaries; synthetic, no API."""
from copy import deepcopy
import unittest

from commentscope.factory import argument_dependencies as deps, argument_observations as obs
from commentscope.factory import owner_observations as owners,source_arguments as sa
from commentscope.providers import remote_verification as remote
from test_remote_verification import parsed
import test_owner_observations as owner_fixture


def case(kind='value', *, declared_fact=False):
    texts=['Adopt this policy.','Fairness matters.'] if kind=='value' else ['The trial paid 20 units.','The trial enrolled 10 people.']
    original=' '.join(texts);units=[]
    for i,text in enumerate(texts,1):
        start=original.index(text)
        units.append({'id':'u'+str(i),'local_id':'U'+str(i),'text':text,'kind':kind,
            'authorship':'asserted_or_endorsed','requires':[],
            'core_requires_for':['core'] if declared_fact and i==1 else [],
            'evidence':[{'start':start,'end':start+len(text),'text':text}]})
    record={'source':{'id':'synthetic','text':original,'parent':None},'units':units,'candidate_ids':['core']}
    cores=[{'candidate':{'id':'core','text':texts[0]},'output':{'kind':kind}}]
    return record,cores


def graph(record,cores,overrides=None):
    out=[]
    for task in deps.tasks(record,cores,typed=True):
        labels={}
        for i,u in enumerate(record['units'],1):labels['kind_U'+str(i)]=u['kind']
        for i,c in enumerate(cores,1):labels['kind_C'+str(i)]=c['output']['kind']
        labels.update(overrides or {})
        results=[]
        for req in deps.chat_requests(task):
            answer={k:labels.get(k,'asserted' if k.startswith('authorship_') else 'complete' if k.startswith('coverage_') else 'none') for k in req['schema']['properties']}
            results.append(parsed(answer))
        out.append(deps.bind_chat(task,results,remote.SOL))
    return out


class TypedGraphTests(unittest.TestCase):
    def checked(self,kind='value',*,declared_fact=False,overrides=None):
        r,c=case(kind,declared_fact=declared_fact)
        return deps.guards(r,c,graph(r,c,overrides),typed=True)

    def test_normative_restatement_and_personal_value_reason_need_no_empirical_premise(self):
        guards=self.checked(overrides={'relation_C1_U1':'restatement','relation_U1_U2':'personal_ground'})
        self.assertTrue(all(not v for v in guards.values()))

    def test_factual_restatement_remains_a_required_fact_and_never_approves_truth(self):
        self.assertTrue(all(not v for v in self.checked('fact',declared_fact=True,overrides={'relation_C1_U1':'restatement'}).values()))
        guards=self.checked('fact',overrides={'relation_C1_U1':'restatement'})
        self.assertIn('missing_factual_prerequisite',guards['coverage'])
        r,c=case('fact',declared_fact=True);self.assertFalse(graph(r,c)[0]['semantic_approval'])

    def test_local_factual_inference_and_direct_core_restatements_remain_separate(self):
        from commentscope.factory.claim_clusters import read_json
        item=read_json('tests/fixtures/jev-transfer-controls.json')['sources'][4]
        r,c=deepcopy(item['record']),deepcopy(item['cores'])
        for u in r['units']:u['kind']='fact'
        for core in c:core['output']={'kind':'fact'}
        checks=graph(r,c,{'relation_U3_U1':'necessary_fact','relation_C1_U1':'restatement','relation_C1_U3':'restatement'})
        self.assertTrue(all(not v for v in deps.guards(r,c,checks,typed=True).values()))
        r['units'][2]['requires']=[]
        self.assertIn('missing_factual_prerequisite',deps.guards(r,c,checks,typed=True)['U3'])

    def test_normative_unit_mislabeled_as_necessary_fact_is_an_explicit_conflict(self):
        guards=self.checked(overrides={'relation_C1_U1':'necessary_fact'})
        self.assertIn('unresolved_type_conflict',guards['coverage'])
        self.assertIn('premise_type_or_authorship_unverified',guards['U1'])

    def test_core_kind_conflict_and_cross_kind_restatement_remain_held(self):
        for labels in ({'kind_C1':'fact'},{'relation_C1_U1':'restatement','kind_U1':'prediction'}):
            with self.subTest(labels=labels):self.assertIn('unresolved_type_conflict',self.checked(overrides=labels)['coverage'])

    def test_missing_wrong_and_unasserted_fact_bases_remain_rejected(self):
        for labels,expected in [({'relation_C1_U1':'none'},'wrong_factual_prerequisite'),
                ({'relation_C1_U2':'necessary_fact'},'missing_factual_prerequisite'),
                ({'relation_C1_U1':'restatement','authorship_U1':'not_asserted'},'unresolved_type_conflict')]:
            with self.subTest(labels=labels):
                self.assertIn(expected,self.checked('fact',declared_fact=True,overrides=labels)['coverage'])

    def test_incomplete_parent_only_or_uncertain_premises_are_not_repaired(self):
        for labels,expected in [({'coverage_C1':'omitted'},'premise_coverage_unverified'),
                               ({'relation_C1_U2':'uncertain'},'premise_relation_uncertain')]:
            with self.subTest(labels=labels):self.assertIn(expected,self.checked(overrides=labels)['coverage'])

    def test_predictions_conditions_reported_context_do_not_become_verified_facts(self):
        for relation in ('personal_ground','condition','reported_context'):
            guards=self.checked(overrides={'relation_C1_U2':relation})
            self.assertTrue(all(not v for v in guards.values()))
        r,c=case();r['units'][0]['kind']='prediction';c[0]['output']['kind']='prediction'
        self.assertTrue(all(not v for v in deps.guards(r,c,graph(r,c,{'relation_C1_U1':'restatement'}),typed=True).values()))

    def test_combined_request_is_blind_and_keeps_every_original_unit(self):
        r,c=case();tasks=deps.tasks(r,c,typed=True)
        self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['kind'],'combined')
        req=deps.chat_requests(tasks[0])[0]
        self.assertEqual(req['data']['state']['ORIGINAL'],r['source']['text'])
        self.assertTrue(all(set(u)=={'id','text','evidence'} for u in req['data']['state']['UNITS'].values()))
        self.assertNotIn('requires',req['data']['state']);self.assertNotIn('output',req['data']['state'])
        self.assertIn('kind_C1',req['schema']['properties'])

    def test_missing_literal_inventory_is_rejected_before_any_graph_request(self):
        r,c=case();r['units']=r['units'][1:]
        with self.assertRaisesRegex(ValueError,'Complete literal original inventory'):
            deps.tasks(r,c,typed=True)

    def test_legacy_task_or_receipt_cannot_be_relabelled_as_typed(self):
        r,c=case();checks=graph(r,c)
        with self.assertRaises(ValueError):deps.select([r],c,[{'source_id':'synthetic'}],checks)
        changed=deepcopy(checks);changed[0]['task']['original']='A foreign original.'
        with self.assertRaises(ValueError):deps.select([r],c,[{'source_id':'synthetic'}],changed,typed=True)


class TypedOwnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f=owner_fixture.OwnerObservationTests();self.f.setUp();self.addCleanup(self.f.doCleanups);self.h=self.f.h
        self.tasks=sa.audit_tasks(self.h.records,self.h.cores)
        self.owners=owners.tasks(self.h.records,self.h.cores,self.tasks,protocol=owners.SOURCE_BOUND)

    def test_new_world_policy_is_explicit_and_legacy_requests_are_unchanged(self):
        self.assertNotEqual(self.owners[0]['id'],self.f.owners[0]['id'])
        self.assertIn('VIDEO_CONTEXT is topic metadata',owners.request(self.owners[0])['system'])
        self.assertNotIn('WORLD_CONTEXT_POLICY',owners.request(self.f.owners[0])['data'])
        for left,right in [('fictional_world','real_world'),('uncertain','uncertain')]:
            self.assertFalse(owners.bind(self.owners[0],{'output':{'relation':'equivalent','basis':'same_assertion','owner_world':left,'candidate_world':right}})['passed'])
        with self.assertRaises(ValueError):owners.select(self.h.records,self.h.cores,self.tasks,self.f.checks(),protocol=owners.SOURCE_BOUND)

    def audits(self,bad_field=None):
        dependencies=[g for r in self.h.records for g in graph(r,[c for c in self.h.cores if c['candidate']['id'] in r['candidate_ids']])]
        owner_checks=[owners.bind(t,{'output':{'relation':'equivalent','basis':'same_assertion','owner_world':'real_world','candidate_world':'real_world'}}) for t in self.owners]
        out=[]
        for task in self.tasks:
            req=sa.audit_request(self.h.records,self.h.cores,[task],protocol=obs.TYPED_CHAT,core_checks=self.h.checks)
            helper=deepcopy(req)
            for row in helper['data']['TASKS']:
                if row['kind']=='unit':row['LINK_TARGETS']=[]
            result=self.h.result(helper)
            for row in result['output']['observations']:
                row.pop('dependency_fidelity');row.pop('owner_relations',None)
                row['basis']='coverage_agrees' if task['kind']=='coverage' else 'normative_assertion'
                if bad_field and task['kind']=='unit':row[bad_field]='no'
            out.append(sa.bind_audit(self.h.records,self.h.cores,[task],result,protocol=obs.TYPED_CHAT,
                core_checks=self.h.checks,owner_checks=owner_checks,dependency_checks=dependencies))
        return out

    def test_new_observations_compile_two_agents_without_weakening_conditions(self):
        self.assertEqual(len(self.h.prepare(self.audits())['compiled']['profiles']),2)
        self.assertEqual(self.h.prepare(self.audits('conditions_fidelity'))['compiled']['profiles'],[])


if __name__=='__main__':unittest.main()
