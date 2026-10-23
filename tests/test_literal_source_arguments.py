"""Literal provenance/coverage and integration gates, not semantic model gold."""
from copy import deepcopy
import unittest
from commentscope.factory import literal_source_arguments as literal,source_closed_policy as closed
from commentscope.factory import source_arguments as sa
from commentscope.factory.automatic_contract import digest
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_entailment import nli_response
from test_semantic_source_closure import SemanticSourceClosureTests,SemanticRunner


class LiteralRunner(SemanticRunner):
    def call(self,stage,req):
        system=req['system'];data=req['data']
        if system.startswith(literal.GRAPH):
            self.calls.append((stage,req));ts=data['OWN_TOKENS']
            return {'raw':'literal graph fixture','errors':[],'output':{'source_language':'en',
                'status':'partial' if self.partial else 'complete','units':[{
                    'local_id':'U1','range':{'first':ts[0][0],'last':ts[-1][0]},
                    'relation':'position','parent':'root','voice':'own'}],'context':[]}}
        if system.startswith(literal.TYPE):
            self.calls.append((stage,req));ts=data['TARGET_TOKENS'];start=next(t[0] for t in ts if t[1]=='if')
            return {'raw':'literal type fixture','errors':[],'output':{'kind':self.unit_kind,
                'entity':'PP','time_ids':[],'qualifier':{'state':'present','ranges':[{'first':start,'last':ts[-1][0]}]},
                'scope_complete':'yes'}}
        if system.startswith(literal.LINK):
            self.calls.append((stage,req))
            return {'raw':'root link fixture','errors':[],'output':{'status':'complete','roots':[
                {'local_id':u['local_id'],'links':[{'candidate_id':c['id'],'role':'reason'} for c in data['CANDIDATES']]}
                for u in data['UNITS'] if u['parent']=='root']}}
        return super().call(stage,req)


class LiteralArgumentTests(unittest.TestCase):
    setUp=SemanticSourceClosureTests.setUp
    configure=SemanticSourceClosureTests.configure

    def process(self,runner=None,classify=nli_response):
        self.configure();runner=runner or LiteralRunner()
        return closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},classify,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},
            interpret_unparsed=True,literal_arguments=True)

    def test_literal_path_compiles_without_candidate_or_parent_in_graph_or_type(self):
        runner=LiteralRunner();out=self.process(runner)
        self.assertFalse(out['errors']);self.assertEqual(len(out['accepted']),3)
        self.assertEqual(len(out['agent_inputs']['compiled']['profiles']),1)
        for accepted in out['accepted']:
            record=accepted['record']['extraction_record'];sa.validate_extraction(record)
            self.assertEqual(record['units'][0]['text'],record['source']['text'])
            self.assertEqual(record['units'][0]['scope']['conditions'],'if it were introduced.')
        for _,req in runner.calls:
            if req['system'].startswith(literal.GRAPH):
                self.assertEqual(set(req['data']),{'OWN_ORIGINAL','OWN_TOKENS'})
                self.assertNotIn('text',req['schema']['properties']['units']['items']['properties'])
            if req['system'].startswith(literal.TYPE):
                self.assertEqual(set(req['data']),{'TARGET','TARGET_TOKENS','TEMPORAL_ANCHORS'})
        self.assertFalse(out['quality_gate_passed'])

    def test_parent_or_candidate_text_cannot_be_generated_as_a_unit(self):
        self.configure();source=self.sources[0];req=literal.graph_request(source)
        result=LiteralRunner().call('graph',req);result['output']['units'][0]['text']='foreign parent sentence'
        with self.assertRaises(ValueError):literal.bind_graph(source,result)
        result=LiteralRunner().call('graph',req);result['output']['units'][0]['range']['last']='PARENT1'
        with self.assertRaises((ValueError,KeyError)):literal.bind_graph(source,result)

    def test_type_scope_errors_and_changed_records_cannot_be_repaired_by_association(self):
        out=self.process();record=out['accepted'][0]['record']['extraction_record'];graph=record['graph']
        raw=deepcopy(record['typings'][0]['output']);ts=literal.tokens(graph['units'][0]['text'])
        raw['qualifier']={'state':'present','ranges':[{'first':ts[0]['id'],'last':ts[-1]['id']}]}
        typed=literal.bind_typing(graph,'U1',{'output':raw})
        self.assertIn('assertion_cannot_be_its_own_condition:U1',typed['hold_reasons'])
        declared=literal.declare(graph,[typed],record['batch_candidates'],record['support_batches'],
            {'output':record['association_output']})
        self.assertEqual(declared['status'],'unresolved')
        self.assertEqual(typed['output'],raw)
        changed=deepcopy(record);changed['units'][0]['text']='invented'
        with self.assertRaises(ValueError):literal.validate(changed)
        raw['time_ids']=['if it were introduced']
        with self.assertRaises(ValueError):literal.bind_typing(graph,'U1',{'output':raw})

    def test_factual_role_conflict_and_unendorsed_voice_stay_held(self):
        record=self.process()['accepted'][0]['record']['extraction_record']
        output=deepcopy(record['association_output']);output['roots'][0]['links'][0]['role']='factual_premise'
        declared=literal.declare(record['graph'],record['typings'],record['batch_candidates'],record['support_batches'],{'output':output})
        self.assertIn('factual_premise_requires_fact_kind:U1',declared['hold_reasons'])
        raw=deepcopy(record['graph']['output']);raw['units'][0]['voice']='reported'
        graph=literal.bind_graph(record['source'],{'output':raw})
        typed=literal.bind_typing(graph,'U1',{'output':record['typings'][0]['output']})
        declared=literal.declare(graph,[typed],record['batch_candidates'],record['support_batches'],{'output':record['association_output']})
        self.assertIn('unendorsed_root_or_argument:U1',declared['hold_reasons'])

    def test_independent_roots_do_not_share_candidate_links(self):
        record=self.process()['accepted'][0]['record']['extraction_record'];source=record['source']
        raw=deepcopy(record['graph']['output']);second=deepcopy(raw['units'][0])
        raw['units'][0]['range']['last']='T3';second.update(local_id='U2')
        second['range']['first']='T4';raw['units'].append(second)
        graph=literal.bind_graph(source,{'output':raw});typings=[]
        for unit in graph['units']:
            typings.append(literal.bind_typing(graph,unit['local_id'],{'output':{
                'kind':'prediction','entity':'PP','time_ids':[],'qualifier':{'state':'absent'},'scope_complete':'yes'}}))
        links=deepcopy(record['association_output']);links['roots'].append({'local_id':'U2','links':[]})
        declared=literal.declare(graph,typings,record['batch_candidates'],record['support_batches'],{'output':links})
        self.assertTrue(declared['units'][0]['candidate_ids'])
        self.assertFalse(declared['units'][1]['candidate_ids'])
        self.assertNotEqual(declared['units'][0]['ownership_family'],declared['units'][1]['ownership_family'])

    def test_rejects_partial_mixed_or_failed_audit_before_any_vote(self):
        for runner in (LiteralRunner(partial=True),LiteralRunner(kind='mixed'),LiteralRunner(audit_bad=True)):
            with self.subTest(partial=runner.partial,kind=runner.unit_kind,audit_bad=runner.audit_bad):
                self.assertFalse(self.process(runner)['accepted'])

    def test_unverified_actual_facts_and_failed_own_fidelity_never_count(self):
        from test_source_closed_policy import empty_fact_classifier
        self.assertFalse(self.process(LiteralRunner(kind='fact'),empty_fact_classifier)['accepted'])
        def reject_units(req):
            return nli_response(req,{c['id'] for c in req['data']['cases'] if c['id'].startswith('AF')})
        self.assertFalse(self.process(classify=reject_units)['accepted'])

    def test_word_omissions_hold_and_overlaps_or_cycles_are_rejected(self):
        self.configure();source=self.sources[0];req=literal.graph_request(source)
        result=LiteralRunner().call('graph',req);result['output']['units'][0]['range']['first']='T2'
        self.assertIn('own_source_words_uncovered',literal.bind_graph(source,result)['hold_reasons'])
        result=LiteralRunner().call('graph',req);result['output']['context']=[result['output']['units'][0]['range']]
        with self.assertRaises(ValueError):literal.bind_graph(source,result)
        result=LiteralRunner().call('graph',req);result['output']['units'][0]['parent']='U1'
        with self.assertRaises(ValueError):literal.bind_graph(source,result)

if __name__=='__main__':unittest.main()
