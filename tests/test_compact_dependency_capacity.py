from copy import deepcopy
import unittest

from commentscope.factory import contextual_dependencies as cd, contextual_engine as ce
from commentscope.factory.automatic_contract import digest
from test_contextual_dependencies import fixture
from test_contextual_comparison_probe import Runner


class CompactDependencyCapacityTests(unittest.TestCase):
    def test_output_contract_is_visible_and_binding_remains_equal(self):
        candidate,interpretation=fixture('This rule should begin tomorrow.',parent={'id':'p','text':'Library entry should be free.'})
        bundle=candidate['meaning_context']
        old=cd.request(bundle,interpretation,cd.COMPACT_REGIONS)
        visible=cd.request(bundle,interpretation,cd.VISIBLE_REGIONS)
        self.assertNotIn('OUTPUT_SCHEMA',old['data'])
        self.assertEqual(visible['data']['OUTPUT_SCHEMA'],old['schema'])
        self.assertEqual(visible['schema'],old['schema'])
        self.assertEqual({k:v for k,v in visible['data'].items() if k!='OUTPUT_SCHEMA'},old['data'])
        for selection in ('C1','unresolved'):
            output={'links':{'R1':selection},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
            before=cd.bind(bundle,interpretation,{'output':output},cd.COMPACT_REGIONS)
            after=cd.bind(bundle,interpretation,{'output':output},cd.VISIBLE_REGIONS)
            self.assertEqual(cd.packet(before),cd.packet(after));self.assertEqual(before['guards'],after['guards'])
            cd.validate(after)

    def test_originals_schema_and_selected_meaning_are_preserved(self):
        examples = [
            fixture('This rule should begin tomorrow.', parent={'id':'p','text':'Library entry should be free.'}),
            fixture('Archive access should be free. This rule should begin tomorrow.','s',1),
            fixture('Some people say "Library cards should be mandatory." I disagree: cards should remain optional.','s',1),
            fixture('학교 급식은 무료여야 한다. This rule should begin tomorrow.','s',1),
        ]
        for candidate,interpretation in examples:
            bundle=candidate['meaning_context']
            old=cd.request(bundle,interpretation,cd.REGIONS)
            compact=cd.request(bundle,interpretation,cd.COMPACT_REGIONS)
            self.assertEqual(old['schema'],compact['schema'])
            self.assertEqual(old['max_tokens'],compact['max_tokens'])
            for key in ('ASSERTION','INDEPENDENT_INTERPRETATION','DISCOURSE_STRUCTURE'):
                self.assertEqual(old['data'][key],compact['data'][key])
            for a,b in zip(old['data']['CONTEXT_ADDRESSES'],compact['data']['CONTEXT_ADDRESSES'],strict=True):
                self.assertEqual([a['id'],a['origin'],a['span']['text']],b)
            for a,b in zip(old['data'].get('CONTEXT_REGIONS',[]),compact['data'].get('CONTEXT_REGIONS',[]),strict=True):
                self.assertEqual([a['id'],a['origin'],a['span']['text'],a['whole_reference']],b)
            output={'links':{r['id']:'C1' for r in cd.inventory(bundle,cd.REGIONS)['requirements']},
                    'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
            before=cd.bind(bundle,interpretation,{'output':output},cd.REGIONS)
            after=cd.bind(bundle,interpretation,{'output':output},cd.COMPACT_REGIONS)
            for key in before:
                if key not in ('artifact_kind','request_sha256'):
                    self.assertEqual(before[key],after[key],key)
            self.assertEqual(cd.packet(before),cd.packet(after))
            cd.validate(after)
            changed=deepcopy(after);changed['bundle']['source']['text']+=' forged'
            with self.assertRaises(ValueError):cd.validate(changed)

    def test_region_selection_cannot_bypass_binding_or_uncertainty(self):
        from commentscope.factory import source_context_addresses as addresses
        candidate,interpretation=fixture('This rule should begin tomorrow.',parent={'id':'p','text':'Library entry should be free.'})
        bundle=candidate['meaning_context'];regions=addresses.regions(bundle['source'])
        parent=next(r['id'] for r in regions if r['origin']=='parent')
        self_reference=next(r['id'] for r in regions if r['origin']=='source' and r['reference_span'])
        output={'links':{'R1':parent},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
        good=cd.bind(bundle,interpretation,{'output':output},cd.COMPACT_REGIONS)
        self.assertTrue(good['ready']);self.assertFalse(good['semantic_approval'])
        for selected in ('Z9999',self_reference):
            bad=deepcopy(output);bad['links']['R1']=selected
            with self.assertRaises(ValueError):cd.bind(bundle,interpretation,{'output':bad},cd.COMPACT_REGIONS)
        for change in ({'links':{'R1':'unresolved'}},{'speech':'nonliteral'},{'closure':'unresolved'}):
            bad={**output,**change}
            self.assertFalse(cd.bind(bundle,interpretation,{'output':bad},cd.COMPACT_REGIONS)['ready'])
        bad=deepcopy(good);bad['bundle']['source']['parent']['text']='Other policy.'
        with self.assertRaises(ValueError):cd.validate(bad)

    def test_compact_fallback_preserves_holds_and_capacity_failure(self):
        class Held(Runner):
            def call(self,stage,request):
                result=super().call(stage,request)
                if stage.startswith('dependency') and not stage.startswith('dependency-link-verification'):
                    result['output']['links']={key:'unresolved' for key in request['schema']['properties']['links']['properties']}
                return result
        sources=[{'id':'s','text':'It should be free.','parent':{'id':'p','text':'Garden access should be free.'}}]
        for fits in (True,False):
            saved={};runner=Held()
            def inspect(request):
                dependency='DEPENDENCIES' in request['data']
                accepted=not dependency or (fits and 'CONTEXT_REGIONS_FORMAT' in request['data'])
                return {'request_sha256':digest(request),'fits':accepted}
            engine=ce.Engine(sources,runner,inspect,save=lambda name,value:saved.update({name:value}))
            engine.discover()
            selection=next(v for k,v in saved.items() if k.startswith('dependency-capacity-selection/'))
            self.assertEqual(selection['selected_contract'],cd.COMPACT_REGIONS)
            self.assertFalse(selection['whole_region_capacity']['fits'])
            self.assertEqual(selection['inference_attempts_before_selection'],0)
            self.assertEqual(sum(s.startswith('dependency') for s in runner.stages),int(fits))
            if fits:
                self.assertFalse(engine.holds);self.assertFalse(engine.errors)
                scope=next(iter(engine.scopes.values()))
                self.assertEqual(scope['artifact_kind'],cd.COMPACT_REGIONS)
                self.assertFalse(scope['ready'])
            else:
                self.assertEqual([h['reason'] for h in engine.holds],['context_capacity','scope_unavailable'])
                self.assertEqual(len(engine.errors),1)
                self.assertFalse(engine.scopes)


if __name__=='__main__':unittest.main()
