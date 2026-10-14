from copy import deepcopy
import unittest
from experiments import matched_factory_review as r


def fixture():
    c={'id':'C1','candidate_source_count':2,'source_ids':['a','b'],
       'common':{'text':'Claim','evidence':[{'source_comment_id':s} for s in ['a','a','b']]},'details':[]}
    report={'V0':{'cards':[]},'V1':{'cards':[c]},'V2':{'cards':[c],'records':[{
        'card_id':'C1','retained':True,'pairs':[{'statement_index':0,'source_id':s,'verdict':'supported','errors':[]} for s in ['a','a','b']]}]}}
    ratings={'C1':{'common':['supported','supported','unsupported'],'details':[],'note':'Test'}}
    return report,ratings


class MatchedReviewTests(unittest.TestCase):
    def test_deduplicates_metrics_not_claim_count(self):
        report,ratings=fixture();out=r.evaluate(report,ratings)
        self.assertEqual(out['variants']['V1']['common_bindings']['count'],2)
        self.assertEqual(out['audit']['assistant_supported_bindings'],1)
        self.assertEqual(out['audit']['model_kept_supported_bindings'],1)
        self.assertEqual(out['audit']['assistant_non_supported_or_unclear_bindings'],1)
        self.assertEqual(out['audit']['model_false_supported_bindings'],1)
        self.assertEqual(out['audit']['nonfaithful_cards_kept'],1)
        self.assertIsNone(out['variants']['V0']['common_bindings']['supported_fraction'])
        self.assertEqual(out['agents'],[]);self.assertFalse(out['quality_gate_passed'])

    def test_missing_extra_or_short_ratings_rejected(self):
        report,ratings=fixture()
        for replacement in [{},{**ratings,'C2':ratings['C1']},{'C1':{**ratings['C1'],'common':['supported']}}]:
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):r.evaluate(report,replacement)

    def test_conflicting_duplicate_source_verdict_rejected(self):
        report,ratings=fixture();ratings['C1']['common'][1]='partial'
        with self.assertRaises(ValueError):r.evaluate(report,ratings)

    def test_unknown_label_and_detail_coverage_rejected(self):
        report,ratings=fixture()
        bad=deepcopy(ratings);bad['C1']['common'][0]='gold'
        with self.assertRaises(ValueError):r.evaluate(report,bad)
        bad=deepcopy(ratings);bad['C1']['details']=[['supported']]
        with self.assertRaises(ValueError):r.evaluate(report,bad)

    def test_audit_must_match_every_review_binding(self):
        report,ratings=fixture();report['V2']['records'][0]['pairs']=[]
        with self.assertRaises(ValueError):r.evaluate(report,ratings)

    def test_review_does_not_mutate_inference_artifacts(self):
        report,ratings=fixture();before=deepcopy(report)
        r.evaluate(report,ratings);self.assertEqual(report,before)


if __name__=='__main__':unittest.main()
