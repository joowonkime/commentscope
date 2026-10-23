import unittest
from experiments.directed_membership_probe import directed,OLD,NEW,FIXTURE
from commentscope.factory.claim_clusters import read_json
from commentscope.factory.scoped_discovery import judge_request


class DirectedMembershipTests(unittest.TestCase):
    def test_only_system_direction_changes(self):
        claim={'id':'C','text':'I would work.','kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}
        req=judge_request('I would work as a nurse.',claim);changed=directed(req)
        self.assertIn(OLD,req['system']);self.assertNotIn(OLD,changed['system'])
        self.assertIn(NEW,changed['system'])
        for key in ['data','schema','max_tokens']:self.assertEqual(req[key],changed[key])
        self.assertEqual(changed['system'].replace(NEW,OLD),req['system'])

    def test_cannot_silently_change_another_prompt_or_repeat_patch(self):
        with self.assertRaises(ValueError):directed({'system':'Other prompt'})
        with self.assertRaises(ValueError):directed({'system':NEW})

    def test_balanced_frozen_controls_not_replacement_100(self):
        fixture=read_json(FIXTURE)
        self.assertFalse(fixture['runtime_input_labels'])
        self.assertEqual(len(fixture['cases']),8)
        self.assertEqual(sum(c['expected']=='supported' for c in fixture['cases']),4)
        self.assertEqual(len({c['id'] for c in fixture['cases']}),8)
