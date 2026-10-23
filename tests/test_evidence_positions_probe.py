import unittest
from experiments.evidence_positions_probe import summarize, retrieval_summary, render


class PositionProbeTests(unittest.TestCase):
    def test_errors_are_not_successful_negative_classification(self):
        result = {'selection': {'errors':['transport_error']}, 'candidates':[], 'position_units':[], 'units':[]}
        summary = summarize([{'split':'fixed_development','expected':False,'result':result}])['fixed_development']
        self.assertEqual(summary['sources_with_errors'],1)
        self.assertEqual(summary['units_quality']['negative_blocked'],0)

    def test_missing_source_stays_in_recall_denominator(self):
        units = [{'claim_id':'u1','source_comment_id':'a','mode':'source_literal'}]
        pair = {'id':'pair','anchor':{'source_comment_id':'a'},'member':{'source_comment_id':'b'}}
        result = retrieval_summary(units, {'u1':[]}, [pair])
        self.assertEqual(result['known_pairs'],1)
        self.assertEqual(result['both_sources_retained'],0)
        self.assertEqual(result['source_exposed'],0)

    def test_source_exposure_is_distinct_from_unit_or_claim_identity(self):
        units = [{'claim_id':'u1','source_comment_id':'a','mode':'source_literal'},
                 {'claim_id':'u2','source_comment_id':'b','mode':'source_literal'}]
        pair = {'id':'pair','anchor':{'source_comment_id':'a'},'member':{'source_comment_id':'b'}}
        result = retrieval_summary(units, {'u1':[{'claim_id':'u2'}],'u2':[]}, [pair])
        self.assertEqual(result['source_exposed'],1)
        self.assertEqual(result['pairs'][0]['hits'][0]['rank'],1)
        self.assertNotIn('semantic_approved',result)

    def test_html_is_escaped(self):
        page = render({'summary':{'value':'<script>bad</script>'}})
        self.assertNotIn('<script>',page)


if __name__ == '__main__': unittest.main()
