from copy import deepcopy
import json
import unittest

from commentscope.factory import fact_checks as f
from experiments.grounding_contract_demo import fixture, response, verdict, MODEL, EXPIRY


class FactCheckTests(unittest.TestCase):
    def inputs(self):
        b=fixture();c=b['claims'][1];selection=b['checks'][0]['selections']
        return b,c,selection,f.packet(c,b['documents'],selection,b['expires_at'])

    def test_scoped_packet_contains_original_document_binding(self):
        b,c,s,p=self.inputs()
        self.assertEqual(p['claim_sha256'],f.claim_identity(c))
        self.assertEqual(p['evidence'][0]['text'],b['documents'][0]['text'])
        self.assertEqual(p['retrieval_scope'],'supplied_passages_only_not_exhaustive')
        self.assertEqual(p['evidence'][0]['document_sha256'],f.digest(b['documents'][0]))

    def test_supported_record_replays_without_inference(self):
        b,c,s,p=self.inputs();record=b['checks'][0]['record']
        self.assertTrue(f.validate_record(record,p,MODEL))
        self.assertFalse(record['quality_gate_passed']);self.assertFalse(record['human_approved'])

    def test_each_non_support_state_stays_non_support(self):
        b,c,s,p=self.inputs()
        for state in ['refuted','insufficient']:
            with self.subTest(state=state):
                record=f.check(p,MODEL,lambda *a,**k:response(verdict(state)))
                self.assertEqual(record['state'],state)
                self.assertFalse(f.validate_record(record,p,MODEL))

    def test_conflict_requires_two_directions(self):
        b,c,s,p=self.inputs()
        s.append({**deepcopy(s[0]),'id':'E2'})
        p=f.packet(c,b['documents'],s,EXPIRY)
        record=f.check(p,MODEL,lambda *a,**k:response(verdict('conflicting',['E1'],['E2'])))
        self.assertEqual(record['state'],'conflicting');self.assertFalse(f.validate_record(record,p,MODEL))
        self.assertTrue(f.errors(verdict('conflicting',['E1'],[]),{'E1'}))

    def test_no_citation_or_foreign_citation_not_accepted(self):
        for result in [verdict('supported',[]),verdict('supported',['foreign']),verdict('supported',['E1','E1']),
                       verdict('supported',['E1'],['E1']),verdict('refuted',[],[])]:
            with self.subTest(result=result):self.assertTrue(f.errors(result,{'E1'}))

    def test_schema_failure_finish_length_and_transport_block(self):
        b,c,s,p=self.inputs()
        for provider in [lambda *a,**k:response({}),lambda *a,**k:response(verdict(),'length')]:
            r=f.check(p,MODEL,provider);self.assertEqual(r['state'],'error')
            self.assertFalse(f.validate_record(r,p,MODEL))
        def unavailable(*a,**k):raise OSError('offline fixture')
        r=f.check(p,MODEL,unavailable);self.assertEqual(r['result']['errors'],['transport_error'])

    def test_empty_evidence_does_not_call_model(self):
        b,c,s,p=self.inputs();p=f.packet(c,b['documents'],[],EXPIRY)
        r=f.check(p,MODEL,lambda *a,**k:self.fail('must not infer from memory'))
        self.assertEqual(r['state'],'unassessed');self.assertFalse(f.validate_record(r,p,MODEL))

    def test_size_budget_does_not_truncate_or_call(self):
        b,c,s,p=self.inputs();b['documents'][0]['text']='x'*40000
        s[0]['span']={'start':0,'end':40000,'text':'x'*40000}
        p=f.packet(c,b['documents'],s,EXPIRY)
        r=f.check(p,MODEL,lambda *a,**k:self.fail('over budget'))
        self.assertEqual(r['result']['errors'],['request_size_budget'])
        self.assertEqual(len(p['evidence'][0]['text']),40000)
        self.assertFalse(f.validate_record(r,p,MODEL))

    def test_changed_document_invalidates_record_even_outside_passage(self):
        b,c,s,p=self.inputs();record=b['checks'][0]['record']
        b['documents'][0]['text']+=' Additional material.'
        changed=f.packet(c,b['documents'],s,EXPIRY)
        with self.assertRaises(ValueError):f.validate_record(record,changed,MODEL)

    def test_changed_scope_or_model_invalidates_record(self):
        b,c,s,p=self.inputs();record=b['checks'][0]['record']
        c['scope']['time']='2026';changed=f.packet(c,b['documents'],s,EXPIRY)
        with self.assertRaises(ValueError):f.validate_record(record,changed,MODEL)
        changed_model={**MODEL,'runtime_sha256':'a'*64}
        with self.assertRaises(ValueError):f.validate_record(record,p,changed_model)

    def test_changed_raw_or_state_cannot_promote_result(self):
        b,c,s,p=self.inputs();r=deepcopy(b['checks'][0]['record']);r['result']['raw']='{}'
        with self.assertRaises(ValueError):f.validate_record(r,p,MODEL)
        r=f.check(p,MODEL,lambda *a,**k:response(verdict('refuted')));r['state']='supported'
        with self.assertRaises(ValueError):f.validate_record(r,p,MODEL)

    def test_expiry_and_timezone_validation(self):
        for expiry in ['2000-01-01T00:00:00Z','2099-01-01T00:00:00',None]:
            with self.subTest(expiry=expiry),self.assertRaises(ValueError):f.live(expiry)
        b,c,s,p=self.inputs();b['documents'][0]['expires_at']='2000-01-01T00:00:00Z'
        with self.assertRaises(ValueError):f.packet(c,b['documents'],s,EXPIRY)

    def test_expiry_uses_earliest_document(self):
        b,c,s,p=self.inputs();b['documents'][0]['expires_at']='2090-01-01T00:00:00Z'
        self.assertEqual(f.packet(c,b['documents'],s,EXPIRY)['expires_at'],'2090-01-01T00:00:00+00:00')

    def test_value_prediction_and_bad_span_rejected(self):
        b,c,s,p=self.inputs()
        for kind in ['value','prediction']:
            c['kind']=kind
            with self.assertRaises(ValueError):f.packet(c,b['documents'],s,EXPIRY)
        c['kind']='fact';s[0]['span']['start']=True
        with self.assertRaises(ValueError):f.packet(c,b['documents'],s,EXPIRY)

    def test_duplicate_ids_and_unsafe_urls_rejected(self):
        b,c,s,p=self.inputs()
        with self.assertRaises(ValueError):f.packet(c,b['documents']*2,s,EXPIRY)
        with self.assertRaises(ValueError):f.packet(c,b['documents'],s*2,EXPIRY)
        for url in ['javascript:alert(1)','file:///secrets','https://user:secret@example.com/']:
            b['documents'][0]['url']=url
            with self.assertRaises(ValueError):f.packet(c,b['documents'],s,EXPIRY)

    def test_request_is_bounded_evidence_not_other_comments(self):
        b,c,s,p=self.inputs();seen=[]
        def provider(system,data,schema,**kw):
            seen.append((system,data,schema,kw));return response(verdict())
        f.check(p,MODEL,provider)
        self.assertEqual(len(seen),1);self.assertEqual(set(seen[0][1]),{'CLAIM','EVIDENCE'})
        self.assertEqual(seen[0][3],{'max_tokens':500})
        self.assertNotIn('eliminated all accidents',json.dumps(seen[0][1]))


if __name__=='__main__':unittest.main()
