from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import contextual_runtime as cr, owned_arguments as oa
from commentscope.factory import minimal_pipeline as pipeline, raw_membership as raw
from commentscope.factory import raw_membership_verification as verification
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.ingestion import load_snapshot
from experiments.framed_agent_probe import runtime_probe
from experiments.grounding_contract_demo import MODEL
from test_contextual_dependencies import fixture,scope
from test_contextual_engine import PipelineRunner,capacity
from test_raw_membership import decision


class ContextualRuntimeTests(unittest.TestCase):
    def test_exact_binding_preserves_world_and_keeps_old_guard_without_proof(self):
        c,i=fixture('Garden access should be free because education matters.')
        proof=cr.bind(c,scope(c,i,world='fictional'))
        self.assertTrue(proof['ready']);self.assertFalse(proof['semantic_approval'])
        self.assertEqual(proof['text'],'Garden access should be free')
        result={'output':{'kind':'value','entity':'garden access','time_ids':[]}}
        old=oa.bind_core(c,result);oa.validate_core(old)
        self.assertIn('contextual_runtime_adapter_unassessed',old['hold_reasons'])
        record=oa.bind_core(c,result,proof);oa.validate_core(record)
        self.assertFalse(record['hold_reasons'])
        data=oa.core_request(c,proof)['data']['TARGET']
        self.assertEqual(data,{'text':c['text'],'interpretation_scope':{'world':'fictional'}})
        self.assertNotIn('education',str(data))
        mutated=deepcopy(proof);mutated['interpretation_scope']['world']='actual'
        with self.assertRaises(ValueError):cr.validate(mutated)
        other,_=fixture(c['text'],'other')
        with self.assertRaises(ValueError):cr.validate(proof,other)
        factual=oa.bind_core(c,{'output':{**result['output'],'kind':'fact'}},proof)
        self.assertIn('nonactual_factual_scope_unsupported',factual['hold_reasons'])

    def test_references_and_unclosed_scope_stay_held_and_conditions_cannot_be_removed(self):
        c,i=fixture('Garden access should be free. This rule should start tomorrow.',index=1)
        proof=cr.bind(c,scope(c,i,links={'R1':'C1'}))
        self.assertFalse(proof['ready']);self.assertIn('external_interpretation_dependency',proof['hold_reasons'])
        c,i=fixture('Garden access should be free.')
        self.assertFalse(cr.bind(c,scope(c,i,closure='unresolved'))['ready'])
        c,i=fixture('Garden access should be free only if residents fund the garden.')
        proof=cr.bind(c,scope(c,i))
        self.assertTrue(proof['ready'])
        core=oa.bind_core(c,{'output':{'kind':'value','entity':'garden access','time_ids':[]}},proof)
        self.assertEqual(core['output']['scope']['conditions'],'only if residents fund the garden.')
        mutated=deepcopy(proof);mutated['text']='Garden access should be free.'
        with self.assertRaises(ValueError):cr.validate(mutated)

    def test_contextual_raw_factory_two_agents_six_turns_scope_and_isolation(self):
        class Runner(PipelineRunner):
            def call(self,stage,req):
                data=req['data'];system=req['system']
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):
                    result=super().call(stage,req);result['output']['world']='fictional';return result
                if stage.startswith('scoped-position'):
                    value={'relation':'opposed','interpretation':'clear'}
                elif system.startswith(raw.SYSTEM):
                    own=data['ORIGINAL']['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].rstrip('.')
                    value=decision(relation='supported' if own==data['CANDIDATE']['text'].rstrip('.') else 'opposed')
                elif system.startswith(verification.ROUTE):value={'role':'subject_position'}
                elif system.startswith(verification.EVIDENCE):value={'source_basis':'own_assertion','verdict':'fully_stated'}
                else:return super().call(stage,req)
                self.calls.append((stage,req));return {'output':value,'errors':[],'raw':'authored fixture only'}
        base=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts=[f'Garden access should be free because Reason {i} matters.' for i in range(3)]
        texts += [f'Garden access should require payment because Other reason {i} matters.' for i in range(3)]
        snapshot=replace(base,usage=replace(base.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(base.comments[0],comment_id=str(i),text_original=t,parent_id=None) for i,t in enumerate(texts)))
        saved={}
        def save(name,value):
            if name in saved and saved[name]!=value:raise AssertionError('Immutable binding overwritten: '+name)
            saved[name]=deepcopy(value)
        def facts(req):raise AssertionError('Value-only fixture cannot request fact inference')
        runner=Runner()
        def embed(stage,texts):
            return {k:[-1. if 'require payment' in text else 1.,0.] for k,text in texts.items()}
        result=pipeline.process(snapshot,runner,embed,capacity,facts,
            model=MODEL,discovery_mode='contextual',membership_mode='raw',verification_contract=verification.CLAUSE_SCOPE,save=save)
        self.assertFalse(result['errors']);self.assertFalse(result['capacity_holds'])
        agent=result['agent_inputs'];self.assertEqual(len(agent['compiled']['profiles']),2)
        self.assertEqual(len(result['arguments']),6)
        self.assertTrue(all(r['status']=='complete' for r in result['arguments']))
        for profile in agent['compiled']['profiles']:
            self.assertEqual(profile['model_core_support_count'],3)
            self.assertEqual(profile['interpretation_scope'],{'world':'fictional'})
            self.assertTrue(all(e['interpretation_scope']=={'world':'fictional'} for e in profile['prompt_entries']))
            session=GroundedSession(agent['bundle'],profile['candidate_id'])
            invocation=session.invocation('What is your position?')
            self.assertEqual(invocation['data']['PERSPECTIVE']['interpretation_scope'],{'world':'fictional'})
            self.assertNotIn('dependency',str(invocation));self.assertNotIn('meaning_context',str(invocation))
        runtime=runtime_probe(agent['bundle'],runner)
        self.assertEqual(len(runtime['turns']),6)
        for row in runtime['turns']:
            self.assertTrue(row['other_histories_unchanged'])
            self.assertEqual(row['turn']['status'],'abstain' if row['question_id']=='missing' else 'answered')
            for point in row['turn']['points']:
                self.assertEqual(point['interpretation_scope'],{'world':'fictional'})
                self.assertTrue(point['citations']['comment_evidence'])
        mutated=deepcopy(agent['bundle']);key=next(iter(mutated['runtime_scopes']))
        mutated['runtime_scopes'][key]['interpretation_scope']['world']='actual'
        with self.assertRaises(ValueError):compile_inputs(mutated)
        mutated=deepcopy(agent['bundle']);del mutated['runtime_scopes']
        with self.assertRaisesRegex(ValueError,'requires its bound runtime scope'):compile_inputs(mutated)
        from commentscope.factory import fact_checks
        mutated=deepcopy(agent['bundle'])
        candidate=mutated['candidates'][0];argument_id=candidate['reason_claim_ids'][0]
        argument=next(c for c in mutated['claims'] if c['id']==argument_id)
        argument['kind']='fact';candidate['major_fact_ids']=[argument_id]
        for relation in mutated['relations']:
            if relation['claim_id']==argument_id:relation['claim_sha256']=fact_checks.claim_identity(argument)
        with self.assertRaisesRegex(ValueError,'Nonactual factual arguments'):compile_inputs(mutated)
