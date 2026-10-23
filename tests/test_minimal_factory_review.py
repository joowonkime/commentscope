"""Review gate tests use authored verdicts; no claim of semantic evaluation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review as review


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='runs', prefix='test-review-')
        self.root = Path(self.tmp.name); self.addCleanup(self.tmp.cleanup)
        tasks = []
        def add(kind, key, data):
            task = {'id': kind+':'+digest(key), 'kind': kind, 'key': key, 'data': data}
            tasks.append(task)
        for sid in 'ABCDEFGHIJKL': add('source',sid,{})
        for cid,label,sids in [('one','mandatory',['A','B','C','I','J']), ('two','voluntary',['E','G','L'])]:
            add('candidate',cid,{'supported_canonical_ids':sids,'label':label})
            add('agent',cid,{'model_core_support_count':len(sids),'label':label})
            for sid in sids: add('support',[cid,sid],{})
            for question in ('position','reasons','missing'): add('runtime',[cid,question],{})
        add('equivalence',['x','y'],{'decision':{'relation':'different'}})
        self.packet = {'artifact_kind':review.VERSION+'-packet','run':str(self.root),
                       'output_sha256':'output','runtime_sha256':'runtime','tasks':tasks,'fact_benchmark':{'passed':True}}
        self.rows = [{'id':t['id'],'verdict':'pass','reason':'Authored synthetic review only.', 'omissions':[],
                      'label':t['data'].get('label')} for t in tasks]
        self.loaded = ({'gate':'G1'}, {'binding_errors':0,'output_sha256':'output','runtime_sha256':'runtime'},
                       None, {'agent_inputs':{'map':{'opinion_map':{}}}}, {})

    def evaluate(self, *, rows=None, packet_hash=None):
        write(self.root/'packet.json', self.packet)
        write(self.root/'review.json', {'artifact_kind':review.VERSION+'-review',
            'packet_sha256':packet_hash or digest(self.packet),'evaluator':'synthetic fixture',
            'rows':self.rows if rows is None else rows})
        with patch.object(review,'load_run',return_value=self.loaded):
            return review.evaluate(self.root,self.root/'review.json',self.root/'result.json')

    def test_complete_authored_g1_contract_pass_is_not_factory_complete(self):
        result=self.evaluate()
        self.assertTrue(result['gate_passed']);self.assertFalse(result['factory_complete'])

    def test_one_wrong_support_cannot_be_offset_by_all_other_correct_rows(self):
        next(r for r in self.rows if r['id'].startswith('support:'))['verdict']='fail'
        result=self.evaluate()
        self.assertFalse(result['requirements']['all_counted_support_valid'])
        self.assertFalse(result['gate_passed'])

    def test_missing_runtime_review_is_not_success(self):
        rows=[r for r in self.rows if r is not next(x for x in self.rows if x['id'].startswith('runtime:'))]
        result=self.evaluate(rows=rows)
        self.assertFalse(result['requirements']['all_runtime_turns_valid'])
        self.assertFalse(result['gate_passed'])

    def test_duplicate_semantic_agent_labels_do_not_prove_distinctness(self):
        for r in self.rows:
            if r['id'].startswith('agent:'): r['label']='mandatory'
        self.assertFalse(self.evaluate()['requirements']['two_distinct_agents'])

    def test_nonmerging_taxonomy_error_is_reported_without_inventing_merge_failure(self):
        next(r for r in self.rows if r['id'].startswith('equivalence:'))['verdict']='fail'
        result=self.evaluate()
        self.assertTrue(result['gate_passed'])
        self.assertEqual(result['review_counts']['equivalence'],{'fail':1})

    def test_incorrect_equivalence_always_vetoes(self):
        self.packet['tasks'][-1]['data']['decision']['relation']='equivalent'
        self.rows[-1]['verdict']='fail'
        result=self.evaluate()
        self.assertFalse(result['requirements']['all_merging_equivalences_valid'])
        self.assertFalse(result['gate_passed'])

    def test_duplicate_review_is_rejected(self):
        with self.assertRaises(ValueError): self.evaluate(rows=self.rows+[deepcopy(self.rows[0])])

    def test_cross_packet_review_is_rejected(self):
        with self.assertRaises(ValueError): self.evaluate(packet_hash='changed')


if __name__=='__main__':unittest.main()
