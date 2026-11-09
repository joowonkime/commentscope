"""Common positions keep individual grounds and independent typed vetoes."""
from copy import deepcopy
import unittest

from commentscope.factory import argument_observations as obs, owner_observations as owners
from commentscope.factory import source_arguments as sa, shared_owned_positions as shared_owner
from commentscope.factory import shared_claims, raw_membership as raw, raw_membership_verification as verify
from commentscope.factory import source_context_observations as contexts, statement_worlds as worlds
from commentscope.factory import argument_dependencies as deps
from commentscope.factory import explicit_discourse as ed
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate
from test_remote_verification import parsed
from test_raw_membership_source_context import observation
import test_typed_verification as typed_fixture
import test_minimal_pipeline as pipeline_fixture


class DirectionalOwnerTests(unittest.TestCase):
    def setUp(self):
        self.f=typed_fixture.TypedOwnerIntegrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        h=self.f.h
        self.tasks=owners.tasks(h.records,h.cores,sa.audit_tasks(h.records,h.cores),protocol=owners.DIRECTIONAL_SOURCE_BOUND)

    def answer(self,task,**changes):
        return {'relation':'supports_core','basis':'direct_support','owner_world':'real_world',
            'candidate_world':'real_world','source_conditions':[
                {'node_id':c['node_id'],'status':'preserved'} for c in owners.request(task)['data']['FIXED_SOURCE_CONDITIONS']],**changes}

    def test_directional_observation_is_bound_separately_from_equivalence(self):
        task=self.tasks[0];check=owners.bind(task,{'output':self.answer(task)})
        self.assertTrue(check['passed']);self.assertFalse(check['semantic_approval'])
        self.assertNotEqual(task['id'],self.f.owners[0]['id'])
        self.assertIn('directional',owners.request(task)['system'])
        with self.assertRaises(ValueError):owners.bind(task,{'output':self.answer(task,relation='equivalent')})
        h=self.f.h
        with self.assertRaises(ValueError):owners.select(h.records,h.cores,sa.audit_tasks(h.records,h.cores),
            [check],protocol=owners.SOURCE_BOUND)

    def test_world_uncertainty_and_negative_scope_do_not_become_approval(self):
        t=self.tasks[0]
        for changes in ({'owner_world':'fictional_world'},{'candidate_world':'uncertain'},
                {'relation':'uncertain'},{'basis':'different_condition'}):
            with self.subTest(changes=changes):self.assertFalse(owners.bind(t,{'output':self.answer(t,**changes)})['passed'])

    def test_every_essential_source_condition_must_have_a_preserved_observation(self):
        source={'id':'condition','text':'Adopt P only if wages remain unchanged.','parent':None}
        graph=ed.parse(source);node=next(n for n in graph['nodes'] if n['kind']=='statement')
        value={'source':source,'owner_position':{'id':node['id'],'text':node['span']['text']},
            'candidate':candidate(source,'Adopt P only if wages remain unchanged.'),
            'world_context_policy':owners.WORLD_CONTEXT_POLICY,'comparison_policy':owners.DIRECTIONAL_POLICY}
        task={'id':'OP'+digest([owners.DIRECTIONAL_SOURCE_BOUND,value]),**value}
        answer=self.answer(task);self.assertTrue(answer['source_conditions'])
        self.assertTrue(owners.bind(task,{'output':answer})['passed'])
        for status in ('missing_or_changed','unclear'):
            changed=deepcopy(answer);changed['source_conditions'][0]['status']=status
            self.assertFalse(owners.bind(task,{'output':changed})['passed'])
        for rows in ([],answer['source_conditions']*2,[{'node_id':'foreign','status':'preserved'}]):
            with self.assertRaises(ValueError):owners.bind(task,{'output':{**answer,'source_conditions':rows}})


class SharedRunner(pipeline_fixture.ScriptedRunner):
    def __init__(self,*,bad_condition=False,empty=False,no_support=False):
        super().__init__();self.bad_condition=bad_condition;self.empty=empty;self.no_support=no_support

    def call(self,stage,req):
        system,data=req['system'],req['data']
        if system.startswith(shared_claims.COMMON_SYSTEM):
            grouped={}
            for s in data['ORIGINALS']:
                core=s['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')+'.'
                grouped.setdefault(core,[]).append(s['author_id'])
            value={'candidates':[] if self.empty else [{'text':t,'nominees':ids,
                **({'assertion_kind':'value'} if 'assertion_kind' in req['schema']['properties']['candidates']['items']['properties'] else {})}
                for t,ids in grouped.items() if len(ids)>=2]}
        elif system.startswith(contexts.SYSTEM):value={'source_use':'substantive_assertion','reported_descriptors':[]}
        elif system.startswith(worlds.SYSTEM):value={'world':'real_world','anchor':''}
        elif system.startswith(raw.SYSTEM):
            value=observation();own=data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].strip().rstrip('.')
            value['relation']='supported' if own==data['CANDIDATE']['text'].rstrip('.') else 'opposed'
            if self.no_support:value['relation']='unrelated'
        elif system.startswith(verify.FOCUS):
            value={'focus_token':'T1','focus_domain':'substantive_issue','role':'subject_position','interpretation':'clear'}
        elif system.startswith(verify.FULL_SCOPE_EVIDENCE):
            value={'reference_basis':'self_contained','target_alignment':'aligned','source_basis':'own_assertion',
                   'verdict':'fully_stated','basis':'Original author states the stance.'}
        elif system.startswith(shared_owner.SYSTEM):
            value={'relation':'supports_core' if data['SOURCE_POSITION']['text'].rstrip('.')==data['COMMON_CORE'].rstrip('.') else 'different',
                **{k:'yes' for k in shared_owner.CHECKS},'conditions':[]}
        elif system.startswith(owners.DIRECTIONAL_SYSTEM):
            value={'relation':'supports_core','basis':'direct_support','owner_world':'real_world',
                'candidate_world':'real_world','source_conditions':[]}
        elif stage.startswith('argument-dependency-'):
            labels={k:'value' if k.startswith('kind_') else 'asserted' if k.startswith('authorship_')
                else 'complete' if k.startswith('coverage_') else 'none' for k in req['schema']['properties']}
            self.calls.append((stage,req));return parsed(labels)
        else:
            result=super().call(stage,req)
            if system.startswith(obs.SOURCE_SYSTEM):
                for row in result['output']['observations']:row.pop('dependency_fidelity',None)
            if self.bad_condition and system.startswith(obs.SOURCE_SYSTEM):
                for row in result['output']['observations']:
                    if 'conditions_fidelity' in row:row['conditions_fidelity']='no'
            return result
        self.calls.append((stage,req));return {'output':value,'raw':'authored synthetic fixture','errors':[]}


class SharedTypedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.h=pipeline_fixture.MinimalPipelineTests();self.h.setUp()

    def run_pipeline(self,runner):
        return self.h.process(runner,discovery_mode='shared',membership_mode='raw',
            verification_contract=verify.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT,
            agent_source_policy='candidate_verified_subset')

    def test_full_originals_form_two_cores_with_separate_reasons_and_typed_audits(self):
        result=self.run_pipeline(SharedRunner())
        self.assertFalse(result['errors']);self.assertFalse(result['unextracted_source_ids'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),2)
        self.assertTrue(all(p['model_core_support_count']==3 for p in result['agent_inputs']['compiled']['profiles']))
        self.assertTrue(all(a['protocol']==obs.SHARED_TYPED_CHAT for a in result['audits']))
        self.assertFalse(result['quality_gate_passed'])
        reasons=[c for c in result['agent_inputs']['bundle']['claims'] if 'because' in c['text']]
        self.assertEqual(len(reasons),6)

    def test_source_condition_failure_still_holds_every_affected_agent(self):
        result=self.run_pipeline(SharedRunner(bad_condition=True))
        self.assertFalse(result['agent_inputs']['compiled']['profiles'])

    def test_empty_intersections_retain_all_processed_originals_without_fabricated_agents(self):
        result=self.run_pipeline(SharedRunner(empty=True))
        self.assertEqual(result['candidates'],[]);self.assertFalse(result['unextracted_source_ids'])
        self.assertFalse(result['agent_inputs']['compiled']['profiles'])
        self.assertEqual(sum(len(r['sources']) for r in result['shared_discovery']),6)

    def test_nominees_never_count_as_support_without_original_verification(self):
        result=self.run_pipeline(SharedRunner(no_support=True))
        self.assertEqual(len(result['candidates']),2)
        self.assertTrue(all(len(c['nominees'])==3 for c in result['candidates']))
        self.assertFalse(result['agent_inputs']['compiled']['profiles'])
        self.assertTrue(all(not p['supported_canonical_ids'] for p in result['agent_inputs']['map']['opinion_map']['perspectives']))

    def test_directional_audits_cannot_be_silently_applied_to_free_claims(self):
        with self.assertRaises(ValueError):self.h.process(SharedRunner(),discovery_mode='free',membership_mode='raw',
            verification_contract=verify.FULL_SCOPE,argument_audit_protocol=obs.SHARED_TYPED_CHAT)

    def test_new_proposals_require_one_kind_and_cannot_relabel_legacy_records(self):
        sources=[{'id':'a','text':'Adopt P.','parent':None},{'id':'b','text':'Adopt P.','parent':None}]
        row={'text':'Adopt P.','nominees':['A0','A1']}
        old=shared_claims.bind(sources,{'output':{'candidates':[row]}},version=shared_claims.COMMON)
        with self.assertRaises(ValueError):shared_claims.for_scope([old],sources,version=shared_claims.COMMON_TYPED)
        for kind in (None,'value_or_prediction'):
            proposal={**row,**({'assertion_kind':kind} if kind else {})}
            with self.assertRaises(ValueError):shared_claims.bind(sources,{'output':{'candidates':[proposal]}},version=shared_claims.COMMON_TYPED)
        typed=shared_claims.bind(sources,{'output':{'candidates':[{**row,'assertion_kind':'value'}]}},version=shared_claims.COMMON_TYPED)
        self.assertFalse(typed['semantic_approval'])
        self.assertEqual(len(shared_claims.for_scope([typed],sources,version=shared_claims.COMMON_TYPED)),1)


if __name__=='__main__':unittest.main()
