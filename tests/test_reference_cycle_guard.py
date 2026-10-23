from copy import deepcopy
from unittest import TestCase

from commentscope.factory import authored_reference as ar, reference_cycle_guard as cg
from commentscope.factory import raw_membership_verification as v
from commentscope.factory.contextual_engine import Engine
from commentscope.factory.automatic_contract import digest
from test_contextual_propositions import original
from test_raw_membership import candidate, decision


class ReferenceCycleTests(TestCase):
    def proof(self, text, selections, parent=None, closure='closed'):
        source=original(text);source['parent']=parent;target=candidate(source,text)
        links=[]
        for mention, selection in zip(ar.inventory(target,source),selections,strict=True):
            if selection=='nonreferential': choice=selection
            else:
                origin, quote=selection
                choice=next(c['id'] for c in ar.contexts(source,mention['span'])
                            if c['origin']==origin and c['span']['text']==quote)
            p=ar.bind_reference(target,source,mention,{'output':{'selection':choice}})
            links.append(ar.bind_check(target,source,p,{'output':{'verdict':'supported'}}))
        form=ar.bind_property('form',target,source,{'output':{'form':'complete'}})
        voice=ar.bind_property('voice',target,source,{'output':{'voice':'asserted'}})
        closed=ar.bind_property('closure',target,source,{'output':{'closure':closure}},links)
        return ar.assessment(target,source,form,voice,links,closed)

    def test_functional_graph_cycles_and_acyclic_paths(self):
        self.assertEqual(cg._cycles({'A':'B','B':'A','C':'A'}),[['A','B']])
        self.assertEqual(cg._cycles({'A':'B','B':'C','C':'A'}),[['A','B','C']])
        self.assertEqual(cg._cycles({'A':'B','B':'C'}),[])
        self.assertEqual(cg._cycles({'A':'A','B':'C','C':'B'}),[['A'],['B','C']])

    def test_bound_two_reference_cycle_held_despite_all_positive_labels(self):
        proof=self.proof('He says he works.',[('source','he'),('source','He')])
        self.assertTrue(proof['passed'])
        result=cg.bind(proof)
        self.assertEqual(result['edges'],{'R1':'R2','R2':'R1'})
        self.assertEqual(result['cycles'],[['R1','R2']]);self.assertFalse(result['passed'])
        self.assertEqual(result['proof'],proof);self.assertEqual(cg.validate(result),result)
        changed=deepcopy(result);changed['cycles']=[]
        with self.assertRaises(ValueError):cg.validate(changed)
        changed=deepcopy(result);changed['proof']['origin']['id']='foreign'
        with self.assertRaises(ValueError):cg.validate(changed)

    def test_exact_occurrence_and_origin_not_word_equality(self):
        # Same character offsets/text in a parent are not the source occurrence.
        # This structural result does not approve that semantic interpretation.
        proof=self.proof('It works.',[('parent','It')],{'id':'p','text':'It costs money.'})
        result=cg.bind(proof)
        self.assertEqual(result['edges'],{});self.assertFalse(result['semantic_approval'])
        proof=self.proof('Alex says he works.',[('source','Alex says')])
        self.assertTrue(cg.bind(proof)['passed'])

    def test_upstream_hold_cannot_be_cleared_by_no_cycle(self):
        proof=self.proof('Workers need rest.',[],closure='unresolved')
        self.assertFalse(cg.bind(proof)['passed'])
        self.assertIn('upstream_proposition_unapproved',cg.bind(proof)['guards'])

    def test_actual_engine_applies_guard_and_preserves_requests(self):
        source=original('He says he works.');target=candidate(source,source['text'])
        class Runner:
            def __init__(self):self.requests=[]
            def call(self,stage,request):
                self.requests.append(request)
                if stage.startswith('authored-reference-check'): value={'verdict':'supported'}
                elif stage.startswith('authored-reference'):
                    expression=request['data']['EXPRESSION']; other='he' if expression['text']=='He' else 'He'
                    value={'selection':next(c[0] for c in request['data']['CONTEXT'] if c[1]=='source' and c[2]==other)}
                elif stage.startswith('authored-form'):value={'form':'complete'}
                elif stage.startswith('authored-voice'):value={'voice':'asserted'}
                elif stage.startswith('authored-closure'):value={'closure':'closed'}
                elif stage.startswith('raw-candidate-route'):value={'assertion_kind':'public_issue_claim','reference_target':'named_or_context_resolved'}
                elif stage.startswith('raw-candidate-target'):value={'target_address':'SELF','target_content':'public_issue_claim','target_closed':'yes'}
                elif stage.startswith('raw-own-evidence'):value={'reference_basis':'self_contained','target_alignment':'aligned','source_basis':'own_assertion','verdict':'fully_stated'}
                else:value=decision()
                return {'output':value,'raw':'test fixture','errors':[]}
        runners=[]
        for version,expected in [(v.REFERENCED,True),(v.ACYCLIC,False)]:
            runner=Runner();runners.append(runner)
            engine=Engine([source],runner,lambda req:{'fits':True,'request_sha256':digest(req)},
                          raw_membership=True,verification_contract=version)
            result=engine.raw_assessment(source['id'],target)
            self.assertEqual(result['passed'],expected);self.assertFalse(engine.errors)
            self.assertEqual(v.validate(result),result)
        self.assertEqual(runners[1].requests,runners[0].requests[:-1])
