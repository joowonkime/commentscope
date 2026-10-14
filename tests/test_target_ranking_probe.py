from copy import deepcopy
import unittest

from experiments.target_ranking_probe import choose


class TargetRankingProbeTests(unittest.TestCase):
    def fixture(self):
        base={'id':'C1','claims':{'C':{'text':'Original position'}}}
        alt={'id':'C1-N1','parent_candidate_id':'C1','claims':{'C':{'text':'Existing alternative position'}}}
        def rows(cid):
            return [{'id':f'J{i}','source_id':f's{i}','candidate_id':cid,'request':{'target':cid}}
                    for i in range(3)]
        return [base],rows('C1'),[alt],rows('C1-N1')

    def test_higher_full_source_support_selects_existing_alternative(self):
        ps,bs,alts,ars=self.fixture();before=deepcopy((ps,bs,alts,ars))
        b={'J0':'supported','J1':'partial','J2':'unsupported'};a={r['id']:'supported' for r in ars}
        result=choose(ps,bs,b,alts,ars,a)
        self.assertEqual(result['proposals'][0]['claims'],alts[0]['claims'])
        self.assertEqual(result['proposals'][0]['id'],'C1')
        self.assertTrue(all(r['id'].startswith('A-') and r['candidate_id']=='C1' for r in result['rows']))
        self.assertEqual([r['request'] for r in result['rows']],[r['request'] for r in ars])
        self.assertEqual((ps,bs,alts,ars),before)
        self.assertEqual(result['qualified_agents'],0);self.assertTrue(result['typing_required'])

    def test_tie_keeps_baseline_and_preserves_record_origin(self):
        ps,bs,alts,ars=self.fixture();a={r['id']:'supported' for r in ars}
        result=choose(ps,bs,a,alts,ars,a)
        self.assertEqual(result['proposals'][0]['selected_variant'],'C1')
        self.assertTrue(all(r['id'].startswith('B-') for r in result['rows']))

    def test_nli_selection_alone_cannot_make_three_supporters(self):
        ps,bs,alts,ars=self.fixture();a={r['id']:'partial' for r in ars}
        result=choose(ps,bs,a,alts,ars,a)
        self.assertEqual(result['proposals'],[]);self.assertFalse(result['quality_gate_passed'])

    def test_duplicate_source_cannot_inflate_count(self):
        ps,bs,alts,ars=self.fixture();a={r['id']:'supported' for r in ars}
        ars[1]['source_id']=ars[0]['source_id']
        with self.assertRaises(ValueError):choose(ps,bs,a,alts,ars,a)

    def test_missing_decision_cannot_be_ignored(self):
        ps,bs,alts,ars=self.fixture();a={r['id']:'supported' for r in ars}
        with self.assertRaises(ValueError):choose(ps,bs,a,alts,ars,{'J0':'supported'})
