from copy import deepcopy
import unittest

from commentscope.factory import fixed_core
from experiments.fixed_core_review import summarize
from tests.test_fixed_core import fixture, supported


class FixedCoreReviewTests(unittest.TestCase):
    def inputs(self):
        units,vectors,groups,sources=fixture()
        selection=fixed_core.select_cores(units,vectors,groups,sources,1)
        membership=fixed_core.memberships(selection,sources,supported)
        cid=membership['cards'][0]['core']['id']
        ratings={'runtime_input':False,'independent_gold':False,'blinded':False,
                 'plan_sha256':'p','report_sha256':'r','cards':{cid:{'relations':[
                     {'source_id':s['source_id'],'verdict':'supported','reason':'Fixture only.'} for s in sources]}},
                 'controls':{'inflation_three_source_core_retained':True,
                             'contradicting_work_source_not_joined_to_no_work_claim':True,'reason':'Fixture only.'}}
        return {'expires_at':'2099-01-01T00:00:00Z'}, {'membership':membership,'summary':{'errors':0,'deferrals':0}},ratings,'p','r'

    def test_pass_is_reserve_only_not_agent(self):
        result=summarize(*self.inputs())
        self.assertTrue(result['summary']['eligible_for_reserved_trial'])
        self.assertFalse(result['summary']['quality_gate_passed'])
        self.assertEqual(result['summary']['agents'],[])

    def test_one_bad_binding_fails_no_repair(self):
        args=self.inputs();before=deepcopy(args[1])
        next(iter(args[2]['cards'].values()))['relations'][0]['verdict']='partial'
        result=summarize(*args)
        self.assertEqual(result['summary']['bad_model_supported'],1)
        self.assertEqual(result['summary']['faithful_ge3_cards'],0)
        self.assertEqual(result['summary']['decision'],'stop_same_family_iterations')
        self.assertEqual(args[1],before)

    def test_no_card_is_not_success(self):
        args=self.inputs();args[1]['membership']['cards']=[];args[2]['cards']={}
        self.assertFalse(summarize(*args)['summary']['eligible_for_reserved_trial'])

    def test_identity_coverage_and_metadata_fail(self):
        for kind in ['hash','coverage','source','runtime','reason']:
            with self.subTest(kind=kind):
                args=self.inputs();ratings=args[2];label=next(iter(ratings['cards'].values()))
                if kind=='hash':ratings['report_sha256']='changed'
                if kind=='coverage':label['relations'].pop()
                if kind=='source':label['relations'][0]['source_id']='someone else'
                if kind=='runtime':ratings['runtime_input']=True
                if kind=='reason':label['relations'][0]['reason']=' '
                with self.assertRaises(ValueError):summarize(*args)

    def test_controls_and_errors_block(self):
        args=self.inputs();args[2]['controls']['inflation_three_source_core_retained']=False
        self.assertFalse(summarize(*args)['summary']['eligible_for_reserved_trial'])
        args=self.inputs();args[1]['summary']['errors']=1
        self.assertFalse(summarize(*args)['summary']['eligible_for_reserved_trial'])


if __name__=='__main__':unittest.main()
