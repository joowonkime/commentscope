import tempfile
import unittest
from pathlib import Path

from commentscope.cluster_baseline import review_html, run, token_chunks, validate_audit


class BaselineReviewTests(unittest.TestCase):
    def test_audit_cannot_cite_another_cluster(self):
        report=self.report()
        report['snapshot_sha256']='digest'
        audit={'snapshot_sha256':'digest','findings':[{'cluster':'C001','evidence_ids':['b']}]}
        with self.assertRaises(ValueError):
            validate_audit(report,audit)

    def test_audit_cannot_use_another_snapshot(self):
        report=self.report()
        report['snapshot_sha256']='digest'
        with self.assertRaises(ValueError):
            validate_audit(report,{'snapshot_sha256':'other','findings':[]})

    def test_chunk_roundtrip_expansion_preserves_all_tokens(self):
        class Tokenizer:
            def encode(self,text,add_special_tokens=False,truncation=False):
                return list(text) + (['special']*2 if add_special_tokens else [])
            def decode(self,tokens,skip_special_tokens=True):
                return ''.join(tokens)*2
            def num_special_tokens_to_add(self,pair=False):
                return 2
        parts=list(token_chunks(Tokenizer(),'abcdefghi',8))
        self.assertEqual(sum(size for _,size in parts),9)
        self.assertTrue(all(len(text)+2<=8 for text,_ in parts))

    def report(self):
        return {'summary':{'accepted_perspectives':0},'sources':{
            'a':{'text':'<script>alert(1)</script> & "quote"','parent_id':'b'},
            'b':{'text':'parent context','parent_id':None}},
            'clusters':[{'id':'C001','members':['a'],'representatives':['a'],
                         'status':'rare_unreviewed','mean_pair_cosine':None,'nearest_cluster':None}]}

    def test_html_escapes_comment_text(self):
        rendered=review_html(self.report())
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('parent context',rendered)

    def test_missing_parent_is_explicit(self):
        report=self.report()
        del report['sources']['b']
        self.assertIn('[parent unavailable]',review_html(report))

    def test_invalid_threshold_before_model_load(self):
        for value in [0,1,-1,float('nan')]:
            with self.assertRaises(ValueError):
                run('nonexistent','unused',value)

    def test_no_overwrite_before_model_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            path.touch()
            with self.assertRaises(FileExistsError):
                run('nonexistent',path)

    def test_no_html_overwrite_before_model_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            Path(str(path)+'.html').touch()
            with self.assertRaises(FileExistsError):
                run('nonexistent',path)
