from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive as write
from experiments import factory_evaluation_kit as kit


def source(sid,text='Text.',parent=None):
    return {'source_id':sid,'text':text,'parent_id':parent,'indexable':bool(text), 'source_digest':digest(text)}


class FactoryEvaluationKitTests(unittest.TestCase):
    def test_threads_including_missing_parent_share_component(self):
        rows=[source('a',parent='missing'),source('b',parent='missing'),source('c','Different.',parent='a')]
        groups=kit.components(rows)
        self.assertEqual(len(set(groups.values())),1)

    def test_text_duplicates_across_threads_group_but_ids_preserved(self):
        rows=[source('a','Same  text.'),source('b','Same\ntext.'),source('c','Other.',parent='b')]
        groups=kit.components(rows)
        self.assertEqual(set(groups),{'a','b','c'});self.assertEqual(len(set(groups.values())),1)

    def test_empty_text_does_not_merge_unrelated_threads(self):
        self.assertNotEqual(*kit.components([source('a',' '),source('b','\t')]).values())

    def test_grouping_is_deterministic_and_order_independent(self):
        rows=[source('a','One.'),source('b','Two.',parent='a'),source('c','Three.')]
        self.assertEqual(kit.components(rows),kit.components(rows[::-1]))
        with self.assertRaises(ValueError):kit.components([rows[0],rows[0]])

    def test_no_thread_or_identical_text_cross_split(self):
        rows=[source('a','One.'),source('b','Two.',parent='a'),source('c','Two.'),source('d','Four.'),source('e','Five.',parent='d')]
        groups=kit.components(rows);split=kit.split_sources(rows,groups,['a'],1)
        self.assertTrue(set(split['reserve_ids'])<={'d','e'})
        self.assertEqual(split['partition_by_source']['b'],'development')
        self.assertEqual(split['partition_by_source']['c'],'development')
        self.assertEqual(split['partition_by_source']['d'],'reserve')
        self.assertEqual(split['partition_by_source']['e'],'reserve')
        self.assertFalse(split['reserve_is_unseen'])

    def test_split_never_silently_shrinks_and_rejects_invalid_ids(self):
        rows=[source('a')];groups=kit.components(rows)
        for ids,count in [(['a'],1),(['missing'],0),(['a','a'],0),(['a'],-1),(['a'],True)]:
            with self.assertRaises(ValueError):kit.split_sources(rows,groups,ids,count)

    def test_source_order_does_not_change_split(self):
        rows=[source(str(i),str(i)) for i in range(10)];groups=kit.components(rows)
        self.assertEqual(kit.split_sources(rows,groups,['0'],3),kit.split_sources(rows[::-1],groups,['0'],3))

    def test_calibration_stratifies_length_reply_without_labels(self):
        rows=[source(str(i),str(i)+'x'*length,parent='p' if reply else None)
              for i,(length,reply) in enumerate([(20,False),(100,False),(500,False),(20,True),(100,True),(500,True)])]
        selected=kit.calibration_ids(rows,6)
        self.assertEqual(set(selected),{str(i) for i in range(6)})
        self.assertEqual(selected,kit.calibration_ids(rows[::-1],6))

    def test_baseline_preserves_partition_and_unindexed_source(self):
        rows=[source('a','A.'),source('b','B.'),source('c','C.'),source('d','')]
        report=kit.baseline({'sources':rows},[[1,0],[1,0],[1,0]])
        self.assertEqual(report['candidate_groups_ge3'],1)
        self.assertEqual(report['source_coverage_in_ge3_candidates'],3)
        self.assertEqual(report['unindexed_ids'],['d'])
        self.assertEqual(report['clusters'][0]['representative_quote'],'A.')
        self.assertIsNone(report['clusters'][0]['support_count'])
        self.assertIsNone(report['semantic_precision']);self.assertIsNone(report['valid_perspective_coverage'])
        self.assertFalse(report['quality_gate_passed']);self.assertEqual(report['agents'],[])

    def test_baseline_rejects_wrong_vector_count(self):
        with self.assertRaises(ValueError):kit.baseline({'sources':[source('a')]},[])

    def fixture(self,root):
        path=Path('tests/fixtures/synthetic-snapshot.json')
        prior=kit.prior.make_plan(str(path),3)
        contract=kit.prior.vector_contract(prior)
        vectors=[[1.,0.] for _ in contract['texts']]
        write(root/'old.json',prior)
        write(root/'vectors.json',{'input':contract,'vectors':vectors,'vectors_sha256':digest(vectors)})
        return path,root/'old.json',root/'vectors.json'

    def test_prepare_is_model_free_and_does_not_claim_finished_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp))
            with patch.object(kit.prior,'embed',side_effect=AssertionError('No inference')):
                plan,report,packet=kit.prepare(*args,reserve_count=0)
            self.assertFalse(plan['comparison_ready'])
            self.assertEqual(report['new_generative_calls'],0)
            self.assertFalse(packet['runtime_input'])
            self.assertTrue(all(c['assessment'] is None and c['user_feedback'] is None for c in packet['items']))
            self.assertEqual((plan,report,packet),kit.prepare(*args,reserve_count=0))

    def test_cache_changes_fail_before_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));stored=kit.read_json(args[2]);stored['vectors'][0]=[0,1]
            original=kit.read_json
            with patch.object(kit,'read_json',side_effect=lambda p:stored if Path(p)==args[2] else original(p)):
                with self.assertRaises(ValueError):kit.prepare(*args,reserve_count=0)

    def test_html_escapes_untrusted_original(self):
        with tempfile.TemporaryDirectory() as temp:
            plan,report,packet=kit.prepare(*self.fixture(Path(temp)),reserve_count=0)
            packet['items'][0]['text']='<script>untrusted</script>'
            page=kit.render(plan,report,packet)
            self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)

    def test_prepare_verify_round_trip_no_inference_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);snapshot,old,vectors=self.fixture(root);out=root/'result'
            args=['kit','--snapshot',str(snapshot),'--development-plan',str(old),'--vectors',str(vectors),
                  '--reserve-count','0','--run-dir',str(out),'--phase','prepare']
            with patch('sys.argv',args):kit.main()
            args[-1]='verify'
            with patch('sys.argv',args):kit.main()
            original=kit.read_json
            report=deepcopy(original(out/'baseline.json'));report['agents']=['fake']
            with patch('sys.argv',args),patch.object(kit,'read_json',side_effect=lambda p:report if Path(p)==out/'baseline.json' else original(p)):
                with self.assertRaisesRegex(ValueError,'replay changed'):kit.main()
