"""Freeze privacy/split boundaries without accessing project originals."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from tools import prepare_source_evidence_review as review


class SourceEvidenceReviewTests(TestCase):
    def write_artifacts(self,path):
        sources={str(i):{'source':{'id':str(i),'text':'Synthetic position '+str(i),'parent':None}} for i in range(110)}
        values={'source-discourse':sources,'argument-extractions':[{'source':sources['0']['source'],'candidate_ids':['c'],
            'units':[{'local_id':'U1'}],'hold_reasons':['node_type_uncertain']}],
            'memberships':[{'memberships':[{'relation':'supported','source_id':'0','candidate_id':'c'}]}],
            'output':{'errors':[{'stage':'membership-jev','exception':'ValueError','message':'synthetic closed enum failure'}],
                      'capacity_holds':[{'stage':'owned-arguments','source_id':'0','reason':'synthetic capacity'}]}}
        for key,value in values.items():(path/(key+'.json')).write_text(json.dumps(value))

    def test_split_is_stable_disjoint_and_not_misreported_as_semantic_gold(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);self.write_artifacts(path);first=review.build(path);second=review.build(path)
            self.assertEqual(first,second)
            self.assertEqual(len(first['development']),48);self.assertEqual(len(first['transfer']),48)
            self.assertFalse({r['source']['id'] for r in first['development']}&{r['source_id'] for r in first['transfer']})
            self.assertFalse(first['semantic_benchmark_ready']);self.assertFalse(first['dispatch_enabled'])
            self.assertIsNone(first['development'][0]['expected_semantics'])
            self.assertFalse(first['failure_map'][0]['root_cause_proven'])

    def test_existing_frozen_review_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);self.write_artifacts(path);dest=path/'private.json';dest.write_text('existing frozen review')
            with patch('sys.argv',['prepare','--artifacts',str(path),'--output',str(dest)]),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):review.main()
            self.assertEqual(dest.read_text(),'existing frozen review')
