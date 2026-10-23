import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commentscope.factory import minimal_membership as mm
from commentscope.factory.automatic_contract import digest
from experiments.contextual_comparison_probe import component,scoped_component


class Runner:
    def __init__(self,failure=None):self.stages=[];self.failure=failure
    def call(self,stage,req):
        self.stages.append(stage)
        if stage.startswith('contextual-interpret'):
            value={'function':'stance','authorship':'author','topic_relation':'direct','scope':'complete','attribution_cue':'none'}
        elif stage.startswith('position'):
            if self.failure=='transport':return {'errors':['timeout'],'raw':None,'output':None}
            value=({'invalid':True} if self.failure=='format' else {'position':'P1','relation':'supported',
                'authorship':'asserted_or_endorsed','scope':'complete','topic':'relevant'})
        elif stage.startswith('qualification-inventory'):value={'status':'complete','qualifications':[]}
        elif stage.startswith('dependency-link-verification'):
            value={'links':{key:'supported' for key in req['schema']['properties']['links']['properties']},
                   'closure':'complete'}
        elif stage.startswith('dependency'):
            if self.failure=='transport':return {'errors':['timeout'],'raw':None,'output':None}
            value={'links':{},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
        elif stage.startswith('scoped-position'):
            if self.failure=='scoped_transport':return {'errors':['timeout'],'raw':None,'output':None}
            value={'invalid':True} if self.failure=='format' else {'relation':'supported','interpretation':'clear'}
        elif stage.startswith('scoped-referents'):value={'verdict':'compatible'}
        elif stage.startswith('scoped-inventory'):value={'status':'complete','qualifications':[]}
        elif stage.startswith('equivalence'):value={'decisions':[{'pair_id':'P1','relation':'equivalent'}]}
        else:raise AssertionError(stage)
        return {'output':value,'errors':[],'raw':json.dumps(value)}


CONTROLS={'sources':[{'id':'a','text':'Garden access should be free.','parent':None},
                    {'id':'b','text':'Garden access should be free.','parent':None}],
          'membership_pairs':[{'source_id':'a','target':['b',0]}],
          'equivalence_pairs':[{'a':['a',0],'b':['b',0]}]}


class ContextualComparisonProbeTests(unittest.TestCase):
    def test_completed_identical_request_is_reused_with_new_source_binding_not_resent(self):
        controls=deepcopy(CONTROLS);controls['sources'][1]['text']='Entry to the garden should cost nothing.'
        controls['sources'].append({'id':'c','text':controls['sources'][1]['text'],'parent':None})
        controls['membership_pairs'].append({'source_id':'a','target':['c',0]});controls['equivalence_pairs']=[]
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=scoped_component(Path(tmp),runner,controls,semantic=True,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertFalse(result['errors']);self.assertTrue(all(m['accepted'] for m in result['memberships']))
        self.assertEqual(result['comparison_model_calls'],3)
        self.assertEqual(len(result['completed_request_reuse']),3)
        self.assertEqual(len({a['witness']['candidate']['id'] for a in result['comparisons']}),2)

    def test_semantic_mode_reuses_bound_direction_and_checks_referents_separately(self):
        controls=deepcopy(CONTROLS);controls['sources'][1]['text']='Entry to the garden should cost nothing.'
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=scoped_component(Path(tmp),runner,controls,semantic=True,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertFalse(result['errors']);self.assertEqual(len(runner.stages),10)
        self.assertEqual(result['comparison_model_calls'],6)
        self.assertTrue(result['memberships'][0]['accepted'])
        self.assertEqual(result['equivalences'][0]['record']['relations'][0]['relation'],'equivalent')
        self.assertEqual(result['equivalences'][0]['record']['dedicated_equivalence_model_calls'],0)
        self.assertEqual(len(result['comparisons']),3)
        self.assertEqual({a['witness']['source_mode'] for a in result['comparisons']},
                         {'source_contribution','candidate_assertion'})

    def test_scoped_failed_comparison_is_not_retried_and_ambiguous_transport_stops(self):
        controls=deepcopy(CONTROLS);controls['sources'][1]['text']='Entry to the garden should cost nothing.'
        runner=Runner('format')
        with TemporaryDirectory() as tmp:
            result=scoped_component(Path(tmp),runner,controls,semantic=True,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertTrue(result['errors'])
        self.assertEqual(len([s for s in runner.stages if s.startswith('scoped-position')]),1)
        runner=Runner('scoped_transport')
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                scoped_component(Path(tmp),runner,controls,semantic=True,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertEqual(len(runner.stages),5)

    def test_scoped_component_interprets_scope_but_does_not_invent_comparison_votes(self):
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=scoped_component(Path(tmp),runner,CONTROLS,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertFalse(result['errors']);self.assertEqual(len(runner.stages),4)
        self.assertEqual(result['comparison_model_calls'],0)
        self.assertTrue(result['memberships'][0]['accepted'])
        self.assertEqual(result['equivalences'][0]['record']['relations'][0]['relation'],'equivalent')
        self.assertNotIn('output',result['equivalences'][0]['record'])

    def test_actual_interfaces_export_typed_identity_and_bidirectional_cross_proofs(self):
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=component(Path(tmp),runner,CONTROLS,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertFalse(result['errors']);self.assertFalse(result['holds'])
        self.assertEqual(len(runner.stages),7)
        self.assertFalse(any(s.startswith('contextual-position') for s in runner.stages))
        self.assertNotIn('output',result['nominations']);mm.validate_batch(result['nominations'])
        self.assertEqual(result['memberships'][0]['batch']['memberships'][0]['relation'],'supported')
        self.assertEqual(result['equivalences'][0]['record']['relations'][0]['relation'],'equivalent')
        self.assertEqual(result['counted_corpus_supports'],0);self.assertFalse(result['quality_gate_passed'])

    def test_failed_comparison_is_not_retried_by_equivalence(self):
        runner=Runner('format')
        with TemporaryDirectory() as tmp:
            result=component(Path(tmp),runner,CONTROLS,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertTrue(result['errors']);stages=[s for s in runner.stages if s.startswith('position')]
        self.assertEqual(len(stages),len(set(stages)))

    def test_ambiguous_transport_stops_without_followup_call(self):
        runner=Runner('transport')
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                component(Path(tmp),runner,CONTROLS,inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertEqual(len(runner.stages),3)


if __name__=='__main__':unittest.main()
