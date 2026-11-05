"""Dependency semantics are explicit; all source/owner vetoes remain intact."""
from copy import deepcopy
import unittest

from commentscope.factory import source_arguments as sa, argument_observations as obs
import test_owner_observations as fixtures


class ArgumentDependencyContractTests(unittest.TestCase):
    def setUp(self):
        self.owner=fixtures.OwnerObservationTests();self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.h=self.owner.h;self.tasks=self.owner.tasks

    def request(self,task,protocol):
        return sa.audit_request(self.h.records,self.h.cores,[task],protocol=protocol,core_checks=self.h.checks)

    def audits(self,protocol,*,bad_dependency=False):
        checks=self.owner.checks();audits=[]
        for t in self.tasks:
            req=self.request(t,protocol);helper=deepcopy(req)
            for task in helper['data']['TASKS']:
                if task['kind']=='unit':task['LINK_TARGETS']=[]
            response=self.h.result(helper)
            for row in response['output']['observations']:
                row.pop('owner_relations',None)
                row['basis']='coverage_agrees' if t['kind']=='coverage' else 'normative_assertion'
                if bad_dependency and t['kind']=='unit':row['dependency_fidelity']='no'
            audits.append(sa.bind_audit(self.h.records,self.h.cores,[t],response,
                protocol=protocol,core_checks=self.h.checks,owner_checks=checks))
        return audits

    def test_new_request_names_factual_graph_without_leaking_previous_classifications(self):
        t=next(t for t in self.tasks if t['kind']=='unit')
        old=self.request(t,obs.LEGACY_SPLIT);new=self.request(t,obs.DEPENDENCY_SCOPED)
        self.assertNotIn('DEPENDENCY_CONTRACT',old['data'])
        self.assertEqual(new['data']['DEPENDENCY_CONTRACT']['scope'],'factual_prerequisites_only')
        self.assertFalse(new['data']['DEPENDENCY_CONTRACT']['discourse_ownership_is_a_factual_dependency'])
        self.assertEqual(new['data']['SOURCES'],old['data']['SOURCES'])
        self.assertEqual(new['data']['TASKS'],old['data']['TASKS'])
        self.assertEqual(new['schema'],old['schema'])
        self.assertTrue(new['system'].startswith(old['system']))
        self.assertTrue(all('kind' not in u for s in new['data']['SOURCES'] for u in s['UNIT_INVENTORY']))

    def test_legacy_split_and_new_split_both_replay_their_own_receipts(self):
        for protocol in (obs.LEGACY_SPLIT,obs.DEPENDENCY_SCOPED):
            with self.subTest(protocol=protocol):
                out=self.h.prepare(self.audits(protocol))
                self.assertEqual(len(out['compiled']['profiles']),2)

    def test_no_is_still_a_veto_even_when_factual_link_lists_are_empty(self):
        out=self.h.prepare(self.audits(obs.DEPENDENCY_SCOPED,bad_dependency=True))
        self.assertFalse(out['compiled']['profiles'])
        self.assertTrue(all('argument_not_verified' in h['reasons'] for h in out['argument_holds']))

    def test_a_legacy_receipt_cannot_be_relabelled_as_the_new_observation(self):
        audits=self.audits(obs.LEGACY_SPLIT);audits[0]['protocol']=obs.DEPENDENCY_SCOPED
        with self.assertRaises(ValueError):self.h.prepare(audits)

    def test_unqualified_dependency_candidate_is_not_the_factory_default(self):
        self.assertEqual(sa.SPLIT_AUDIT,obs.LEGACY_SPLIT)
        self.assertNotEqual(sa.SPLIT_AUDIT,obs.DEPENDENCY_SCOPED)
