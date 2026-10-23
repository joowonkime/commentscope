from copy import deepcopy
from unittest import TestCase

from commentscope.factory import authored_reference as ar, raw_membership_verification as v
from commentscope.factory import minimal_claims as mc, substantive_target as st
from commentscope.factory.contextual_engine import Engine
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate, decision
from test_contextual_propositions import original, selected


class AuthoredReferenceTests(TestCase):
    def pair(self, text='Workers say they need rest.', parent=None):
        source = original(text); source['parent'] = parent
        return candidate(source, text), source

    def test_original_normalization_and_bounded_inventory(self):
        source = original('Cafe\u0301  access is free.'); target = mc.candidates([selected(source)])[0]
        data = ar.property_request('form', target, source)['data']
        self.assertEqual(data['SELECTED_ASSERTION']['text'], source['text'])
        self.assertEqual(data['ORIGINAL'], source)
        target, source = self.pair('He goes there. I think that 16% need help.')
        self.assertEqual([x['span']['text'] for x in ar.inventory(target, source)], ['He', 'there', 'that'])
        target, source = self.pair('People need rest. I need rest.')
        self.assertEqual(ar.inventory(target, source), [])

    def test_exact_addresses_and_reference_provenance(self):
        target, source = self.pair(); mention = ar.inventory(target, source)[0]
        choices = ar.contexts(source, mention['span'])
        self.assertFalse(any(c['origin']=='source' and c['span']['start']<mention['span']['end']
            and mention['span']['start']<c['span']['end'] for c in choices))
        chosen = next(c for c in choices if c['span']['text']=='Workers say')
        proposal = ar.bind_reference(target, source, mention, {'output': {'selection': chosen['id']}})
        checked = ar.bind_check(target, source, proposal, {'output': {'verdict': 'supported'}})
        self.assertTrue(checked['passed'])
        data = ar.check_request(target, source, proposal)['data']
        self.assertNotIn('passed', str(data)); self.assertEqual(data['SELECTED_CONTEXT']['span']['text'], 'Workers say')
        wrong = deepcopy(proposal); wrong['context']['span']['text'] = 'parents'
        with self.assertRaises(ValueError): ar.check_request(target, source, wrong)
        with self.assertRaises(ValueError): ar.bind_reference(target, source, mention, {'output': {'selection': 'unlisted'}})
        other = deepcopy(source); other['parent'] = {'id': 'p', 'text': 'Different context.'}
        with self.assertRaises(ValueError): ar.check_request(target, other, proposal)

    def test_nonreferential_requires_independent_check(self):
        target, source = self.pair('There are jobs.')
        mention = ar.inventory(target, source)[0]
        p = ar.bind_reference(target, source, mention, {'output': {'selection': 'nonreferential'}})
        self.assertIsNone(ar.check_request(target, source, p)['data']['SELECTED_CONTEXT'])
        self.assertFalse(ar.bind_check(target, source, p)['passed'])
        self.assertFalse(ar.bind_check(target, source, p, {'output': {'verdict': 'unsupported'}})['passed'])
        missing = ar.bind_reference(target, source, mention, {'output': {'selection': 'unresolved'}})
        with self.assertRaises(ValueError): ar.check_request(target, source, missing)

    def test_closure_and_all_reference_proofs_are_required(self):
        target, source = self.pair()
        form = ar.bind_property('form', target, source, {'output': {'form': 'complete'}})
        voice = ar.bind_property('voice', target, source, {'output': {'voice': 'asserted'}})
        closure = ar.bind_property('closure', target, source, {'output': {'closure': 'closed'}}, [])
        self.assertFalse(ar.assessment(target, source, form, voice, [], closure)['passed'])
        target, source = self.pair('Workers need rest.')
        calls = []
        def call(stage, req):
            calls.append(stage)
            task = next(iter(req['schema']['properties']))
            return {'output': {task: {'form': 'complete', 'voice': 'asserted', 'closure': 'closed'}[task]}}
        proof = ar.run(target, source, call)
        self.assertTrue(ar.validate(proof)['passed'])
        self.assertEqual(calls, ['authored-form', 'authored-voice', 'authored-closure'])
        wrong = deepcopy(proof); wrong['closure']['request_sha256'] = 'foreign'
        with self.assertRaises(ValueError): ar.validate(wrong)
        wrong = deepcopy(proof); wrong['closure'] = None
        with self.assertRaises(ValueError): ar.validate(wrong)

    def test_v10_binding_and_actual_engine(self):
        target, source = self.pair('Workers need rest.')
        class Runner:
            def __init__(self, fragment): self.fragment=fragment; self.calls=[]
            def call(self, stage, request):
                self.calls.append(stage)
                if stage.startswith('authored-form'): value={'form': 'fragment' if self.fragment else 'complete'}
                elif stage.startswith('authored-voice'): value={'voice': 'asserted'}
                elif stage.startswith('authored-closure'): value={'closure': 'closed'}
                elif stage.startswith('raw-candidate-route'): value={'assertion_kind':'public_issue_claim','reference_target':'named_or_context_resolved'}
                elif stage.startswith('raw-candidate-target'): value={'target_address':'SELF','target_content':'public_issue_claim','target_closed':'yes'}
                elif stage.startswith('raw-own-evidence'): value={'reference_basis':'self_contained','target_alignment':'aligned','source_basis':'own_assertion','verdict':'fully_stated'}
                else: value=decision()
                return {'output':value,'raw':'test fixture','errors':[]}
        for fragment in (False,True):
            runner=Runner(fragment);other={**source,'id':'another'}
            engine=Engine([source,other],runner,lambda req:{'fits':True,'request_sha256':digest(req)},
                          raw_membership=True,verification_contract=v.REFERENCED)
            for item in (source,other):
                result=engine.support(item['id'],target)
                self.assertEqual(result['accepted'],not fragment,engine.errors)
            self.assertFalse(engine.errors)
            self.assertEqual(sum(s.startswith('authored-form') for s in runner.calls),1)
            route=next(iter(engine._raw_routes.values()))
            proof=route['proposition_proof']; self.assertEqual(ar.validate(proof),proof)
            with self.assertRaises(ValueError):
                v.bind_route(target,{'output':route['output']},source,version=v.AUTHORED,
                    target_check=route['target_check'],proposition_proof=proof)
        self.assertEqual(v.route_request(target,source,version=v.REFERENCED),
                         v.route_request(target,source,version=v.TARGETED_NORMALIZED))
