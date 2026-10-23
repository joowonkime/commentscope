from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import contextual_engine as ce, candidate_consolidation as cc
from commentscope.factory import contextual_runtime as cr
from commentscope.factory import contextual_dependencies as cd
from commentscope.factory import minimal_claims as mc, minimal_membership as mm, minimal_pipeline as pipeline, owned_arguments as oa
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot
from experiments.grounding_contract_demo import MODEL
from test_contextual_comparison_probe import Runner,CONTROLS
from test_minimal_pipeline import ScriptedRunner


def capacity(request):return {'request_sha256':digest(request),'fits':True}


class PipelineRunner(ScriptedRunner):
    def call(self,stage,request):
        if stage.startswith(('contextual-interpret','dependency','scoped-')):
            self.calls.append((stage,request));return Runner().call(stage,request)
        if request['system'].startswith(oa.META):
            self.calls.append((stage,request))
            full={'authorship':'asserted_or_endorsed','kind':'value','entity':'Garden access',
                  'time_ids':[],'source_language':'en'}
            return {'output':{k:full[k] for k in request['schema']['properties']},'errors':[],'raw':'test'}
        if request['system'].startswith(oa.ALIGN):
            self.calls.append((stage,request));return {'output':{'relation':'equivalent'},'errors':[],'raw':'test'}
        return super().call(stage,request)


class ContextualEngineTests(unittest.TestCase):
    def test_capacity_selects_regions_before_inference_and_preserves_fitted_requests(self):
        class Held(Runner):
            def __init__(self):super().__init__();self.requests=[]
            def call(self,stage,request):
                self.requests.append(request)
                result=super().call(stage,request)
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):
                    result['output']['links']={key:'unresolved' for key in request['schema']['properties']['links']['properties']}
                return result
        sources=[{'id':'a','text':'Garden access should be free.','parent':None},
                 {'id':'b','text':'It should be free.','parent':{'id':'p','text':'Garden access should be free.'}}]
        runner=Held();saved={}
        def inspect(request):
            return {'request_sha256':digest(request),'fits':'CONTEXT_TOKEN_REGIONS' not in request['data']}
        engine=ce.Engine(sources,runner,inspect,save=lambda name,value:saved.update({name:value}))
        engine.discover();self.assertFalse(engine.errors);self.assertFalse(engine.holds)
        self.assertFalse(any('CONTEXT_TOKEN_REGIONS' in req['data'] for req in runner.requests))
        scopes={s['bundle']['source']['id']:s for s in engine.scopes.values()}
        self.assertEqual(scopes['a']['artifact_kind'],cd.VERSION)
        self.assertEqual(scopes['b']['artifact_kind'],cd.REGIONS)
        self.assertFalse(scopes['b']['ready'])
        selections=[v for k,v in saved.items() if k.startswith('dependency-capacity-selection/')]
        self.assertEqual(len(selections),1)
        self.assertEqual(selections[0]['inference_attempts_before_selection'],0)
        self.assertFalse(selections[0]['original_text_truncated'])
        self.assertEqual(len([s for s in runner.stages if s.startswith('dependency')]),2)

    def representative_fixture(self):
        class Linked(Runner):
            def call(self,stage,request):
                result=super().call(stage,request)
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):
                    result['output']['links']={key:'C1' for key in request['schema']['properties']['links']['properties']}
                return result
        sources=[{'id':'a','text':'Garden access should be free.','parent':None},
                 {'id':'b','text':'It should be free.','parent':{'id':'parent','text':'Garden access should be free.'}}]
        engine=ce.Engine(sources,Linked(),capacity);engine.discover()
        scopes={c['id']:cr.bind(c,engine.scope(c)) for c in engine.candidates}
        return engine,scopes

    def test_closed_literal_representative_precedes_lower_id_referential_alias(self):
        engine,scopes=self.representative_fixture()
        a,b=engine.candidates;self.assertEqual(a['text'],'It should be free.')
        equivalences=engine.equivalences([{'a':a['id'],'b':b['id']}])
        args=(engine.sources,engine.candidates,[engine.nominations],equivalences)
        legacy=cc.consolidate(*args)
        self.assertEqual(legacy['candidates'][0]['id'],a['id'])
        self.assertNotIn('representative_selection',legacy)
        merged=cc.consolidate(*args,runtime_scopes=scopes);target=merged['candidates'][0]
        self.assertEqual(target['id'],b['id']);self.assertEqual(target['text'],b['text'])
        self.assertEqual(target['meaning_context'],b['meaning_context'])
        self.assertEqual(target['aliases'],[a['id'],b['id']])
        self.assertEqual(set(target['nominees']),{'a','b'})
        self.assertEqual(set(target['extraction_refs']),set(a['extraction_refs']+b['extraction_refs']))
        self.assertEqual(target['equivalence_refs'],[digest(equivalences[0])])
        self.assertEqual(merged['representative_selection']['runtime_scopes'],scopes)
        changed=deepcopy(target);del changed['representative_choice']
        with self.assertRaises(ValueError):mc.validate_candidate(changed)
        changed=deepcopy(target);changed['representative_choice']['selected_id']=a['id']
        with self.assertRaises(ValueError):mc.validate_candidate(changed)
        changed=deepcopy(target);del changed['nominees'][target['meaning_context']['source']['id']]
        with self.assertRaises(ValueError):mc.validate_candidate(changed)
        self.assertEqual(merged['memberships'],[]);self.assertTrue(merged['final_wording_reassessment_required'])
        with self.assertRaises(ValueError):mm.collect(engine.sources,[target],[engine.nominations])
        batches=engine.judge([{'source_id':s['id'],'candidate_id':target['id']} for s in engine.sources],[target])
        rows=mm.collect(engine.sources,[target],batches)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['relation']=='supported' for r in rows))

    def test_preference_never_approves_an_unassessed_merge_or_missing_scope(self):
        engine,scopes=self.representative_fixture()
        separate=cc.consolidate(engine.sources,engine.candidates,[engine.nominations],[],runtime_scopes=scopes)
        self.assertEqual(len(separate['candidates']),2)
        a,b=engine.candidates;eq=engine.equivalences([{'a':a['id'],'b':b['id']}])
        no_scope=cc.consolidate(engine.sources,engine.candidates,[engine.nominations],eq,runtime_scopes={})
        self.assertEqual(no_scope['candidates'][0]['id'],a['id'])
        self.assertFalse(scopes[a['id']]['ready']);self.assertTrue(scopes[b['id']]['ready'])

    def test_representative_scope_cannot_be_mutated_or_borrowed(self):
        engine,scopes=self.representative_fixture();a,b=engine.candidates
        for changed in (deepcopy(scopes),{a['id']:scopes[b['id']]},{'foreign':scopes[b['id']]}):
            if len(changed)==2:changed[a['id']]['ready']=True
            with self.assertRaises(ValueError):
                cc.consolidate(engine.sources,engine.candidates,[engine.nominations],[],runtime_scopes=changed)

    def test_self_nomination_requires_closed_scope_despite_equal_text(self):
        class Unclosed(Runner):
            def call(self,stage,request):
                result=super().call(stage,request)
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):result['output']['closure']='unresolved'
                return result
        engine=ce.Engine(CONTROLS['sources'],Unclosed(),capacity);engine.discover()
        self.assertEqual(len(engine.nominations['memberships']),2)
        self.assertTrue(all(r['relation']=='uncertain' for r in engine.nominations['memberships']))
        self.assertFalse(any(s.startswith('scoped-') for s in engine.call_stages))

    def test_merged_representative_rebinds_every_final_source_proof(self):
        engine=ce.Engine(CONTROLS['sources'],Runner(),capacity);engine.discover()
        a,b=engine.candidates;pair={'a':a['id'],'b':b['id']}
        equivalences=engine.equivalences([pair])
        merged=cc.consolidate(engine.sources,engine.candidates,[engine.nominations],equivalences)
        target=merged['candidates'][0]
        self.assertEqual(len(target['aliases']),2)
        batches=engine.judge([{'source_id':s['id'],'candidate_id':target['id']} for s in engine.sources],[target])
        rows=mm.collect(engine.sources,[target],batches)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['relation']=='supported' for r in rows))
        self.assertTrue(all(b['contextual_assessments'][0]['witness']['candidate']==target for b in batches))
        self.assertFalse(any(s.startswith('scoped-') for s in engine.call_stages))

    def test_reference_context_changes_retrieval_text_without_assertion_rewrite(self):
        class Linked(Runner):
            def call(self,stage,request):
                result=super().call(stage,request)
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):
                    links=request['schema']['properties']['links']['properties']
                    result['output']['links']={key:'C1' for key in links}
                return result
        sources=[{'id':sid,'text':subject+' should be free. This rule should start tomorrow.','parent':None}
                 for sid,subject in [('a','Garden access'),('b','Road tolls')]]
        engine=ce.Engine(sources,Linked(),capacity);engine.discover()
        targets=[c for c in engine.candidates if c['text'].startswith('This rule')]
        self.assertEqual(len(targets),2);self.assertEqual(targets[0]['text'],targets[1]['text'])
        self.assertNotEqual(engine.embedding_text(targets[0]),engine.embedding_text(targets[1]))
        self.assertIn('Garden access',engine.embedding_text(next(c for c in targets if c['meaning_context']['source']['id']=='a')))

    def test_real_factory_dispatch_adapts_closed_literal_core_and_keeps_population(self):
        base=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts=['Garden access should be free because education matters.',
               'Garden access should be free because inclusion matters.',
               'Garden access should be free because opportunity matters.']
        snapshot=replace(base,usage=replace(base.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(base.comments[0],comment_id=str(i),text_original=t,parent_id=None) for i,t in enumerate(texts)))
        saved={};embedded={};runner=PipelineRunner()
        def embed(stage,texts):
            embedded[stage]=deepcopy(texts);return {k:[1.,0.] for k in texts}
        def facts(request):raise AssertionError('Value claims do not require fact inference')
        result=pipeline.process(snapshot,runner,embed,capacity,facts,model=MODEL,
                                discovery_mode='contextual',save=saved.__setitem__)
        self.assertFalse(result['errors']);self.assertFalse(result['capacity_holds'])
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(len(mm.collect([r['source'] for r in result['extractions']],result['candidates'],result['memberships'])),3)
        self.assertEqual(result['canonical_population'],3)
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),1)
        self.assertFalse(result['agent_inputs']['argument_holds'])
        self.assertEqual(result['consolidation']['representative_selection']['artifact_kind'],cc.REPRESENTATIVE_POLICY)
        self.assertEqual(len(saved['contextual-runtime-scopes']),1)
        self.assertTrue(all(r['runtime_scope']['ready'] for r in result['cores']))
        self.assertEqual(len(saved['contextual-engine']['scopes']),3)
        self.assertTrue(all('referents' in text for text in embedded['candidates'].values()))
        self.assertFalse(any(stage.startswith('extract-') for stage,_ in runner.calls))


if __name__=='__main__':unittest.main()
