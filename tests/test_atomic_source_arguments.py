"""Independent nomination/type/scope and lineage mechanics, not model gold."""
from copy import deepcopy
import unittest
from commentscope.factory import atomic_source_arguments as atomic,source_arguments as sa
from commentscope.factory import source_closed_policy as closed
from commentscope.factory.automatic_contract import digest
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_entailment import nli_response
from test_semantic_source_closure import SemanticSourceClosureTests,SemanticRunner


class AtomicRunner(SemanticRunner):
    def __init__(self,*,typing_kind='prediction',**kwargs):
        super().__init__(**kwargs);self.typing_kind=typing_kind
    def call(self,stage,req):
        if req['system'].startswith(atomic.NOMINATE):
            self.calls.append((stage,req));source=req['data']['ORIGINAL']
            return {'raw':'atomic nomination fixture','errors':[],'output':{
                'source_language':'en','status':'partial' if self.partial else 'complete','units':[{
                    'local_id':'U1','text':source['ORIGINAL_SEGMENTS'][0]['text'],'role':'reason','parent_local_id':'core',
                    'candidate_ids':[c['id'] for c in req['data']['CANDIDATES']],'evidence_segment_ids':['S000']}]}}
        if req['system'].startswith(atomic.TYPE):
            self.calls.append((stage,req));tokens=req['data']['SCOPE_TOKENS']
            start=next(t['id'] for t in tokens if t['text']=='if')
            return {'raw':'independent source-only typing fixture','errors':[],'output':{
                'kind':self.typing_kind,'entity':'PP','time_ids':[],
                'conditions':[{'first_token_id':start,'last_token_id':tokens[-1]['id']}],'scope_complete':'yes'}}
        return super().call(stage,req)


class AtomicSourceArgumentTests(unittest.TestCase):
    setUp=SemanticSourceClosureTests.setUp
    configure=SemanticSourceClosureTests.configure

    def process(self,runner):
        self.configure()
        return closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},
            interpret_unparsed=True,atomic_arguments=True)

    def test_independent_typing_compiles_and_preserves_condition_as_literal_scope(self):
        runner=AtomicRunner();out=self.process(runner)
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']),1)
        for a in out['accepted']:
            declaration=a['record']['extraction_record'];sa.validate_extraction(declaration)
            self.assertEqual(declaration['units'][0]['kind'],'prediction')
            self.assertEqual(declaration['units'][0]['scope']['time'],'')
            self.assertEqual(declaration['units'][0]['scope']['conditions'],'if it were introduced.')
        for _,req in runner.calls:
            if req['system'].startswith(atomic.NOMINATE):
                self.assertNotIn('kind',req['schema']['properties']['units']['items']['properties'])
                self.assertNotIn('scope',req['schema']['properties']['units']['items']['properties'])
            if req['system'].startswith(atomic.TYPE):
                self.assertEqual(set(req['data']),{'OWN_ORIGINAL','TARGET','TEMPORAL_ANCHORS','SCOPE_TOKENS'})
        self.assertFalse(out['quality_gate_passed'])

    def test_mixed_units_remain_unresolved_not_forced_into_values_or_predictions(self):
        out=self.process(AtomicRunner(typing_kind='mixed'))
        self.assertFalse(out['accepted']);self.assertFalse(out['agent_inputs']['compiled']['profiles'])
        self.assertTrue(all('unit_not_atomic_or_type_uncertain' in s['reasons'] for s in out['source_statuses']))

    def test_nomination_cannot_sneak_in_old_kind_scope_or_forged_time(self):
        out=self.process(AtomicRunner());declaration=out['accepted'][0]['record']['extraction_record'];nom=declaration['nomination']
        output=deepcopy(nom['output']);output['units'][0]['kind']='value'
        with self.assertRaises(ValueError):atomic.bind_nomination(nom['source'],nom['candidates'],nom['memberships'],{'output':output})
        output=deepcopy(declaration['typings'][0]['output']);output['time_ids']=['if it were introduced.']
        with self.assertRaises(ValueError):atomic.bind_typing(nom,'U1',{'output':output})
        output=deepcopy(declaration['typings'][0]['output']);output['conditions'][0]['last_token_id']='not-a-token'
        with self.assertRaises((ValueError,KeyError)):atomic.bind_typing(nom,'U1',{'output':output})

    def test_parent_cycles_or_changed_typed_condition_bindings_rejected(self):
        out=self.process(AtomicRunner());declaration=out['accepted'][0]['record']['extraction_record'];nom=declaration['nomination']
        output=deepcopy(nom['output']);output['units'][0]['parent_local_id']='U1'
        with self.assertRaises(ValueError):atomic.bind_nomination(nom['source'],nom['candidates'],nom['memberships'],{'output':output})
        changed=deepcopy(declaration);changed['typings'][0]['condition_spans'][0]['text']='invented condition'
        with self.assertRaises(ValueError):atomic.validate(changed)

    def test_all_audit_chunks_required_when_atomic_source_has_more_than_seven_units(self):
        class ManyUnits(AtomicRunner):
            def call(self,stage,req):
                result=super().call(stage,req)
                if req['system'].startswith(atomic.NOMINATE):
                    row=result['output']['units'][0]
                    # Controller fixture stresses complete task coverage only;
                    # duplicated text is not real semantic-quality evidence.
                    result['output']['units']=[{**deepcopy(row),'local_id':f'U{i}'} for i in range(1,9)]
                return result
        out=self.process(ManyUnits());self.assertFalse(out['errors'])
        self.assertEqual(len(out['accepted']),3)
        for accepted in out['accepted']:
            self.assertEqual([len(a['tasks']) for a in accepted['audits']],[8,1])
            tasks={t['task_id'] for a in accepted['audits'] for t in a['tasks']}
            self.assertEqual(len(tasks),9)

    def test_factual_role_cannot_accept_value_or_prediction_without_retyping_answers(self):
        out=self.process(AtomicRunner());record=out['accepted'][0]['record']['extraction_record'];nom=record['nomination']
        output=deepcopy(nom['output']);output['units'][0]['role']='factual_premise'
        nomination=atomic.bind_nomination(nom['source'],nom['candidates'],nom['memberships'],{'output':output})
        for kind in ('value','prediction'):
            raw={**record['typings'][0]['output'],'kind':kind}
            typing=atomic.bind_typing(nomination,'U1',{'output':raw});declared=atomic.declare(nomination,[typing])
            self.assertEqual(declared['status'],'unresolved')
            self.assertEqual(typing['output']['kind'],kind)
            self.assertIn('factual_premise_requires_fact_kind:U1',declared['hold_reasons'])

    def test_entire_claim_cannot_be_its_own_condition_but_legacy_record_stays_replayable(self):
        out=self.process(AtomicRunner());record=out['accepted'][0]['record']['extraction_record'];nom=record['nomination']
        raw=deepcopy(record['typings'][0]['output']);tokens=atomic.scope_tokens(nom['units'][0]['text'])
        raw['conditions']=[{'first_token_id':tokens[0]['id'],'last_token_id':tokens[-1]['id']}]
        typing=atomic.bind_typing(nom,'U1',{'output':raw});declared=atomic.declare(nom,[typing])
        self.assertEqual(declared['status'],'unresolved')
        self.assertIn('assertion_cannot_be_its_own_condition:U1',declared['hold_reasons'])
        legacy=atomic.declare(nom,[typing],check_compatibility=False)
        self.assertNotIn('compatibility_contract',legacy);atomic.validate(legacy)
        atomic.validate(declared)


if __name__=='__main__':unittest.main()
