from copy import deepcopy
import unittest

from commentscope.factory import contextual_dependencies as cd, contextual_engine as ce
from commentscope.factory import selected_reference_verification as verifier
from commentscope.factory.automatic_contract import digest
from test_contextual_dependencies import fixture, scope
from test_contextual_comparison_probe import Runner


def selected(text='This rule should begin tomorrow.',parent=None,index=0):
    candidate,interpretation=fixture(text,index=index,parent=parent or {
        'id':'p','text':'Library entry should be free.'})
    bundle=candidate['meaning_context']
    return cd.bind(bundle,interpretation,{'output':{
        'links':{r['id']:'C1' for r in cd.inventory(bundle)['requirements']},
        'scope':'complete','speech':'literal','world':'actual','closure':'complete'}})


def decision(proposal,verdict='supported',closure='complete'):
    return {'output':{'links':{link['requirement']['id']:verdict for link in proposal['links']
                              if link['context'] is not None},'closure':closure}}


class SelectedReferenceVerificationTests(unittest.TestCase):
    def test_verified_scope_preserves_original_and_does_not_approve_support(self):
        proposal=selected();request=verifier.request(proposal)
        self.assertEqual(request['data']['ORIGINAL'],proposal['bundle']['source'])
        self.assertEqual(request['data']['ASSERTION'],proposal['bundle']['assertion'])
        self.assertNotIn('allowed',request['data']['PROPOSED_LINKS'][0]['requirement'])
        audited=verifier.bind(proposal,decision(proposal))
        self.assertTrue(audited['ready']);self.assertEqual(cd.validate(audited),audited)
        self.assertEqual(cd.packet(audited),cd.packet(proposal))
        self.assertEqual(audited['bundle'],proposal['bundle'])
        self.assertFalse(audited['semantic_approval'])
        self.assertFalse(audited['link_verification']['factual_verification'])
        self.assertNotIn('proposal',audited['link_verification'])

    def test_unapproved_or_unclosed_record_is_held_without_individual_link_credit(self):
        proposal=selected('They should adopt it.')
        self.assertGreater(len(proposal['links']),1)
        for verdict,closure in [('unsupported','complete'),('unresolved','complete'),('supported','unresolved')]:
            result=decision(proposal)
            first=next(iter(result['output']['links']))
            result['output']['links'][first]=verdict;result['output']['closure']=closure
            audited=verifier.bind(proposal,result)
            self.assertFalse(audited['ready']);self.assertFalse(audited['link_verification']['passed'])
            self.assertFalse(cd.packet(audited)['closed_literal_interpretation'])
            self.assertFalse(cd.literal_equivalence(audited,audited)['equivalent'])
            cd.validate(audited)

    def test_held_or_empty_proposal_cannot_be_promoted_or_recursively_audited(self):
        empty=scope(*fixture('Library entry should be free.'))
        proposal=selected();held=cd.bind(proposal['bundle'],proposal['interpretation'],{
            'output':{**proposal['output'],'closure':'unresolved'}})
        audited=verifier.bind(proposal,decision(proposal))
        for invalid in (empty,held,audited):
            with self.assertRaises(ValueError):verifier.request(invalid)
            with self.assertRaises(ValueError):verifier.bind(invalid,decision(proposal))

    def test_errors_missing_extra_and_unknown_verdicts_reject(self):
        proposal=selected()
        for result in ({'errors':['timeout'],'output':None},{'output':None},{'output':{}},
                       {'output':{'links':{},'closure':'complete'}},decision(proposal,'yes'),
                       decision(proposal,closure='unknown'),
                       {'output':{'links':{'R1':'supported','foreign':'supported'},'closure':'complete'}}):
            with self.assertRaises(ValueError):verifier.bind(proposal,result)

    def test_proof_source_selection_and_ready_cannot_be_mutated(self):
        proposal=selected();audited=verifier.bind(proposal,decision(proposal))
        mutations=[
            lambda r:r['bundle']['source']['parent'].update(text='A different policy.'),
            lambda r:r['links'][0]['context']['span'].update(text='forged'),
            lambda r:r['link_verification'].update(request_sha256='0'*64),
            lambda r:r['link_verification'].update(proposal_sha256='0'*64),
            lambda r:r['link_verification']['output']['links'].update(R1='unsupported'),
            lambda r:r.update(guards=['invented']),
            lambda r:r.update(ready=False),
            lambda r:r.update(proposal_contract=cd.AUDITED),
        ]
        for mutate in mutations:
            changed=deepcopy(audited);mutate(changed)
            with self.assertRaises(ValueError):cd.validate(changed)
        held=verifier.bind(proposal,decision(proposal,'unsupported'))
        held['ready']=True;held['guards']=[]
        with self.assertRaises(ValueError):cd.validate(held)

    def test_discourse_and_answer_packets_retain_context_and_modality(self):
        cases=[('Some people say "Library cards should be mandatory." I disagree: cards should remain optional.','DISCOURSE','actual'),
               ('Do you want cleaner air? If yes, adopt road pricing.','ANSWER','hypothetical')]
        for text,key,world in cases:
            c,i=fixture(text,index=1)
            proposal=scope(c,i,links={key:'C1'},world=world)
            audited=verifier.bind(proposal,decision(proposal))
            self.assertEqual(cd.packet(audited),cd.packet(proposal));cd.validate(audited)
            self.assertEqual(audited['output']['world'],world)

    def test_engine_never_uses_proposal_when_verification_fails(self):
        class Linked(Runner):
            def __init__(self,result):super().__init__();self.result=result
            def call(self,stage,request):
                result=super().call(stage,request)
                if stage.startswith('dependency-link-verification'):
                    return deepcopy(self.result)
                if stage.startswith('dependency'):
                    result['output']['links']={key:'C1' for key in request['schema']['properties']['links']['properties']}
                return result
        sources=[{'id':'s','text':'It should begin tomorrow.','parent':{
            'id':'p','text':'Free school meals should be introduced.'}}]
        for contract in (cd.VERSION,cd.REGIONS,cd.COMPACT_REGIONS):
            for verdict in ('supported','unsupported','unresolved','malformed','too_large'):
                with self.subTest(contract=contract,verdict=verdict):
                    result={'output':{'links':{'R1':verdict},'closure':'complete'},'errors':[],'raw':'fixture'}
                    if verdict=='malformed':result['output']={}
                    def inspect(request):
                        data=request['data'];fits=True
                        if 'DEPENDENCIES' in data:
                            if contract!=cd.VERSION and 'CONTEXT_TOKEN_REGIONS' in data:fits=False
                            if contract==cd.COMPACT_REGIONS and 'CONTEXT_REGIONS_FORMAT' not in data:fits=False
                        elif 'PROPOSED_LINKS' in data and verdict=='too_large':fits=False
                        return {'request_sha256':digest(request),'fits':fits}
                    saved={};runner=Linked(result)
                    engine=ce.Engine(sources,runner,inspect,save=saved.__setitem__)
                    engine.discover()
                    proposal=next(v for k,v in saved.items() if k.startswith('dependency-proposals/'))
                    self.assertEqual(proposal['artifact_kind'],contract)
                    self.assertEqual(sum(s.startswith('dependency-link-verification') for s in runner.stages),int(verdict!='too_large'))
                    if verdict in ('malformed','too_large'):
                        self.assertFalse(engine.scopes);self.assertEqual(len(engine.errors),1)
                    else:
                        self.assertFalse(engine.errors)
                        record=next(iter(engine.scopes.values()))
                        self.assertEqual(record['artifact_kind'],cd.AUDITED)
                        self.assertEqual(record['ready'],verdict=='supported');cd.validate(record)
                    if verdict!='supported':
                        self.assertTrue(all(row['relation']=='uncertain' for row in engine.nominations['memberships']))


if __name__=='__main__':unittest.main()
