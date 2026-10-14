from contextlib import nullcontext
from types import SimpleNamespace
import unittest

from commentscope.providers.raw_nli import score_full


class Values:
    def softmax(self, **kwargs): return self
    def tolist(self): return [.9,.05,.05]


class RawNLITests(unittest.TestCase):
    def model(self, tokens=50):
        seen=[]
        def tokenizer(a,b,**kwargs):
            seen.append((a,b,kwargs));return {'input_ids':SimpleNamespace(shape=[1,tokens])}
        class Model:
            config=SimpleNamespace(max_position_embeddings=512)
            def __call__(self,**kwargs):return SimpleNamespace(logits=[Values()])
        return SimpleNamespace(tokenizer=tokenizer,model=Model(),torch=SimpleNamespace(inference_mode=nullcontext),
                               labels={0:'entailment',1:'neutral',2:'contradiction'}),seen

    def test_over500_char_source_still_processed_without_truncation(self):
        model,seen=self.model();text='A'*900
        result=score_full(model,text,'Claim.')
        self.assertEqual(result['relation'],'supports')
        self.assertEqual(seen[0][0],text);self.assertFalse(seen[0][2]['truncation'])

    def test_token_budget_is_deferred_not_negative(self):
        model,_=self.model(513)
        result=score_full(model,'Source.','Claim.')
        self.assertEqual(result['deferred_reason'],'token_budget')
        self.assertIsNone(result['relation'])

    def test_invalid_source_or_target_cannot_be_silently_shortened(self):
        for a,b in [('','Claim.'),('a'*4001,'Claim.'),('Source.','t'*250)]:
            model,_=self.model();result=score_full(model,a,b)
            self.assertTrue(result['errors']);self.assertIsNone(result['relation'])
