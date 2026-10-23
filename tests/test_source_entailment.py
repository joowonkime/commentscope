from copy import deepcopy
import math
import unittest

from commentscope.factory import shared_admission, shared_claims, source_entailment as se
from commentscope.factory import minimal_membership as mm
from commentscope.factory.automatic_contract import digest
from commentscope.providers.local_nli import MODEL, REVISION, THRESHOLD, decide
from commentscope.providers import evidence_nli
from test_shared_admission import ScriptedAdmission


def nli_response(request,held=()):
    """Authored logits exercise proof validation, never test model accuracy."""
    metadata={'model':MODEL,'revision':REVISION,'threshold':THRESHOLD,'local_files_only':True,
        'id2label':{'0':'entailment','1':'neutral','2':'contradiction'}}
    results=[]
    for case in request['data']['cases']:
        raw=[0.,8.,0.] if case['id'] in held else [8.,0.,0.]
        values=[math.exp(x-max(raw)) for x in raw];total=sum(values)
        scores={metadata['id2label'][str(i)]:v/total for i,v in enumerate(values)}
        pairs=[{'id':case['evidence'][0]['id'],'errors':[],'raw':raw,'scores':scores,
            'relation':decide(scores,THRESHOLD),'input_tokens':8}]
        results.append({'id':case['id'],'pairs':pairs,**evidence_nli.aggregate(pairs)})
    return {'metadata':metadata,'results':results,'forward_pairs':len(results),'quality_gate_passed':False}


class SourceEntailmentTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':sid,'text':text,'parent':None} for sid,text in
            [('a','Adopt P.'),('b','Adopt P.'),('c','Reject P.'),('x','Adopt P.')]]
        self.sources[0]['parent']={'id':'parent','text':'Parent text must never become own evidence.'}
        record=shared_claims.bind(self.sources,{'output':{'candidates':[
            {'text':'Adopt P.','nominees':['A0','A1']}]}},version=shared_claims.COMMON)
        self.candidates=shared_claims.candidates([record])
        out=shared_admission.process(self.sources,self.candidates,
            {s['id']:[1.,0.] for s in self.sources},{c['id']:[1.,0.] for c in self.candidates},
            ScriptedAdmission(),lambda r:{'request_sha256':digest(r),'fits':True},on_shared=lambda *a:True)
        self.raw=out['memberships'];self.request=se.invocation(self.raw)
        self.response=nli_response(self.request)
    def build(self,response=None):
        return se.batch(self.sources,self.candidates,self.raw,self.response if response is None else response)

    def test_gate_never_promotes_negative_and_holds_nonentailed_positive(self):
        held={self.request['data']['cases'][0]['id']}
        bound=self.build(nli_response(self.request,held))
        rows=mm.collect(self.sources,self.candidates,[bound])
        self.assertEqual(sum(r['relation']=='supported' for r in rows),2)
        self.assertEqual(next(r for r in rows if r['source_id']=='c')['relation'],'opposed')
        self.assertIn('whole_original_entailment_unproved',rows[0]['guards'])
        self.assertFalse(bound['semantic_approval']);self.assertFalse(bound['factual_verification'])

    def test_request_contains_whole_own_originals_and_excludes_parent(self):
        self.assertEqual(len(self.request['data']['cases']),3)
        for case in self.request['data']['cases']:
            sid=case['evidence'][0]['id']
            source=next(s for s in self.sources if s['id']==sid)
            self.assertEqual(case['evidence'],[{'id':sid,'text':source['text']}])
            self.assertNotIn('Parent text',str(case))

    def test_missing_reordered_or_extra_comparisons_fail_closed(self):
        for mutate in [lambda r:r['results'].pop(),lambda r:r['results'].reverse(),
                       lambda r:r.update(forward_pairs=99)]:
            response=deepcopy(self.response);mutate(response)
            with self.assertRaises(ValueError):self.build(response)

    def test_changed_source_result_or_member_cannot_be_rebound(self):
        for mutate in [lambda b:b['sources'][0].update(text='Changed own comment.'),
                       lambda b:b['memberships'][0].update(relation='uncertain'),
                       lambda b:b['assessments'][0]['nli']['result']['pairs'][0]['scores'].update(entailment=.01)]:
            bound=self.build();mutate(bound)
            with self.assertRaises(ValueError):mm.collect(self.sources,self.candidates,[bound])

    def test_wrong_model_and_duplicated_votes_are_rejected(self):
        response=deepcopy(self.response);response['metadata']['revision']='other'
        with self.assertRaises(ValueError):self.build(response)
        with self.assertRaises(ValueError):se.invocation(self.raw+[self.raw[0]])

    def test_unprovided_positive_classifier_result_cannot_approve(self):
        with self.assertRaises(ValueError):se.batch(self.sources,self.candidates,self.raw,None)

    def test_source_projection_preserves_same_comparator_and_cannot_import_other_votes(self):
        full=self.build();cid=self.candidates[0]['id']
        selected=se.for_source(full,'a',{cid,'other-batch-core'})
        rows=mm.collect([self.sources[0]],self.candidates,[selected])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_id'],'a')
        self.assertEqual(selected['assessments'][0],full['assessments'][0])
        self.assertEqual(len(selected['sources']),1)
        response=deepcopy(self.response);response['results'][0]['pairs'][0]['input_tokens']=513
        with self.assertRaises(ValueError):self.build(response)

    def test_larger_actual_comparison_keeps_full_request_identity_and_exact_selected_case(self):
        request=deepcopy(self.request);extra=deepcopy(request['data']['cases'][0]);extra['id']='unused-comparison'
        request['data']['cases'].append(extra);response=nli_response(request)
        record=se.from_completed_comparisons(self.sources,self.candidates,self.raw,request,response)
        self.assertEqual(len(mm.collect(self.sources,self.candidates,[record])),4)
        self.assertEqual(record['assessments'][0]['nli']['batch_request_sha256'],digest(request))
        changed=deepcopy(request);changed['data']['cases'][0]['text']='Different core.'
        with self.assertRaises(ValueError):se.from_completed_comparisons(self.sources,self.candidates,self.raw,changed,response)

    def test_disjoint_actual_batches_keep_their_own_receipts_and_reject_duplicate_or_missing_cases(self):
        requests=[]
        for case in self.request['data']['cases']:
            request=deepcopy(self.request);request['data']['cases']=[case];requests.append(request)
        batches=[(r,nli_response(r)) for r in requests]
        record=se.from_completed_batches(self.sources,self.candidates,self.raw,batches)
        proofs=[p['nli'] for p in record['assessments'] if p['nli'] is not None]
        self.assertEqual({p['batch_request_sha256'] for p in proofs},{digest(r) for r in requests})
        self.assertEqual(sum(r['relation']=='supported' for r in mm.collect(self.sources,self.candidates,[record])),3)
        for invalid in [batches[:-1],batches+[batches[0]],[]]:
            with self.assertRaises(ValueError):se.from_completed_batches(self.sources,self.candidates,self.raw,invalid)

