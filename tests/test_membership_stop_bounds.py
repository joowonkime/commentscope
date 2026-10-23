from pathlib import Path
import tempfile
import unittest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments.membership_stop_bounds import analyze


class StopBoundTests(unittest.TestCase):
    def fixture(self,root,false_count):
        source=root/'source';nli=root/'nli'
        ids=[f'J{i:03}' for i in range(1,101)]
        write(source/'plan.json',{'rows':[{'id':i} for i in ids],'evaluation_ids':ids})
        labels={i:'supported' if n<21 else 'unsupported' for n,i in enumerate(ids)}
        write(source/'references.json',{'labels':labels})
        write(source/'reference-frozen.json',{'sha256':sha(source/'references.json')})
        for i in ids[21:21+false_count]:
            write(source/(i+'.json'),{'result':{'errors':[],'output':{'verdict':'supported','reason':'incorrect'}}})
        write(nli/'result.json',{'results':[{'id':i,'state':'supported' if n<13 else 'insufficient'} for n,i in enumerate(ids)]})
        return source,nli

    def test_bounds_preserve_unexecuted_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,nli=self.fixture(Path(tmp),3);analyze(source,nli)
            report=read_json(source/'early-stopped.json')
            self.assertEqual(report['planned_evaluation'],100)
            self.assertEqual(report['llm_observed_cases'],3)
            self.assertEqual(len(report['unexecuted']),97)
            self.assertEqual(report['llm_precision_best_possible'],21/24)
            self.assertEqual(report['intersection_retention_best_possible'],13/21)
            self.assertFalse(report['quality_gate_passed'])

    def test_one_still_possible_variant_prevents_early_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,nli=self.fixture(Path(tmp),1)
            with self.assertRaises(ValueError):analyze(source,nli)
            self.assertFalse((source/'early-stopped.json').exists())
