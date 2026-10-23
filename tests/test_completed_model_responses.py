import json
import sqlite3
import unittest

from commentscope.factory.claim_clusters import read_json
from commentscope.factory.shared_admission import PriorRequestUnavailable
from experiments.completed_model_responses import CompletedResponses,CompletedResponseChain
from commentscope.factory.automatic_contract import digest
import test_completed_shared_proposals as fixture


class CompletedModelResponseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.CompletedSharedProposalTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_exact_completed_raw_response_is_reused_without_semantic_approval(self):
        f=self.fixture;cache=CompletedResponses(f.root,deployment=f.deployment)
        req=read_json(f.request_path)['request'];result=cache.get(req)
        self.assertEqual(result['output'],f.record['output'])
        self.assertEqual(cache.hits,1);self.assertFalse(cache.proof['semantic_approval'])
        self.assertEqual(cache.proof['receipts'][0]['ledger_call_id'],1)
        result['output']['candidates']=[]
        self.assertEqual(cache.get(req)['output'],f.record['output'])

    def test_interrupted_request_is_unavailable_and_never_a_new_request(self):
        f=self.fixture
        with sqlite3.connect(f.db) as db:db.execute("update calls set state='interrupted',response_json=NULL")
        f.request_path.with_name(f.request_path.name.replace('.request.json','.result.json')).unlink()
        for p in (f.root/'checkpoints').glob('*.result.json'):p.unlink()
        cache=CompletedResponses(f.root,deployment=f.deployment)
        self.assertEqual(len(cache.results),0)
        with self.assertRaises(PriorRequestUnavailable):cache.get(read_json(f.request_path)['request'])

    def test_matching_mutated_files_cannot_override_the_raw_ledger(self):
        f=self.fixture;path=f.request_path.with_name(f.request_path.name.replace('.request.json','.result.json'))
        result=read_json(path);result['raw']='{"candidates":[]}';result['output']={'candidates':[]}
        path.write_text(json.dumps(result))
        from commentscope.factory.automatic_contract import digest
        checkpoint=next((f.root/'checkpoints').glob('*.result.json'));done=read_json(checkpoint)
        done['result']=result;done['result_sha256']=digest(result);checkpoint.write_text(json.dumps(done))
        with self.assertRaises(ValueError):CompletedResponses(f.root,deployment=f.deployment)

    def child(self, reference):
        child=self.fixture.root/'followup';child.mkdir()
        plan=read_json(self.fixture.root/'plan.json')
        plan['completed_response_priors']=[reference]
        (child/'plan.json').write_text(json.dumps(plan))
        return child

    def test_chain_reuses_actual_ancestor_receipt_without_fabricating_child_calls(self):
        f=self.fixture;prior=CompletedResponseChain(f.root,deployment=f.deployment)
        child=self.child({'directory':str(f.root),'proof_sha256':digest(prior.proof)})
        cache=CompletedResponseChain(child,deployment=f.deployment)
        self.assertFalse(cache.current.results)
        self.assertEqual(cache.get(read_json(f.request_path)['request'])['output'],f.record['output'])
        self.assertEqual(cache.proof['priors'][0]['current']['receipts'][0]['ledger_call_id'],1)
        self.assertFalse((child/'calls').exists())

    def test_chain_rejects_changed_frozen_ancestor_proof(self):
        child=self.child({'directory':str(self.fixture.root),'proof_sha256':'0'*64})
        with self.assertRaisesRegex(ValueError,'provenance changed'):
            CompletedResponseChain(child,deployment=self.fixture.deployment)

    def test_chain_rejects_recursive_prior(self):
        child=self.fixture.root/'followup'
        self.child({'directory':str(child),'proof_sha256':'0'*64})
        with self.assertRaisesRegex(ValueError,'Cyclic'):
            CompletedResponseChain(child,deployment=self.fixture.deployment)


if __name__=='__main__':unittest.main()
