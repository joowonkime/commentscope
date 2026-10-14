from copy import deepcopy
import unittest

from commentscope.factory import common_position as c


def seed(cid='S1'):
    return {'id':cid,'claims':{'C':{'text':'The review must begin immediately.'}},
            'sources':{'a':'Reviews should be required. Begin immediately.',
                       'b':'Reviews should be required.', 'c':'I support requiring reviews.',
                       'd':'I oppose requiring reviews.'}, 'candidate_unit_ids':['u1']}


def output():
    return {'errors':[],'output':{'status':'proposed','core':'Reviews should be required.',
            'scope':{'entity':'general','time':'','conditions':''},'witnesses':[
                {'source_id':'a','quote':'Reviews should be required.','qualifications':['Begin immediately.']},
                {'source_id':'b','quote':'Reviews should be required.','qualifications':[]},
                {'source_id':'c','quote':'I support requiring reviews.','qualifications':[]}]}}


class CommonPositionTests(unittest.TestCase):
    def test_original_context_and_opponent_retained_without_approval(self):
        s=seed(); before=deepcopy(s); req=c.invocation(s); p=c.bind(s,output())
        self.assertEqual(req['data']['ORIGINAL_SOURCES'],s['sources'])
        self.assertEqual(p['sources'],s['sources'])
        self.assertIn('d',p['sources']); self.assertEqual(len(p['source_witnesses']),3)
        self.assertFalse(p['semantic_approval']); self.assertTrue(p['typing_required'])
        self.assertEqual(s,before); self.assertEqual(p['id'],'CP-S1')
        self.assertEqual(p['source_witnesses'][0]['qualifications'],['Begin immediately.'])

    def test_foreign_duplicate_missing_witnesses_rejected(self):
        for change in ('foreign','duplicate','few'):
            r=output(); ws=r['output']['witnesses']
            if change=='foreign':ws[-1]['source_id']='unknown'
            elif change=='duplicate':ws[-1]=deepcopy(ws[0])
            else:ws.pop()
            with self.assertRaises(ValueError):c.bind(seed(),r)

    def test_quote_or_qualification_rewrite_rejected(self):
        for field in ('quote','qualifications'):
            r=output(); w=r['output']['witnesses'][0]
            w[field]='Invented evidence' if field=='quote' else ['Invented restriction']
            with self.assertRaises(ValueError):c.bind(seed(),r)

    def test_unexpected_approval_and_empty_core_rejected(self):
        for mutation in ({'approved':True},{'core':' '},{'scope':{'entity':'everyone'}}):
            r=output(); r['output'].update(mutation)
            with self.assertRaises(ValueError):c.bind(seed(),r)

    def test_model_deferral_and_errors_remain_unapproved(self):
        self.assertIsNone(c.bind(seed(),{'errors':[],'output':{'status':'defer','reason':'no_shared_position'}}))
        with self.assertRaises(ValueError):c.bind(seed(),{'errors':['timeout'],'output':output()['output']})

    def test_proposer_witness_is_not_a_semantic_approval(self):
        r=output(); r['output']['core']='This unsupported assertion passes only structural checks.'
        p=c.bind(seed(),r)
        self.assertFalse(p['semantic_approval'])
        self.assertNotIn('model_support_count',p)

    def test_exact_contract_dedup_preserves_all_sources_and_provenance(self):
        a=c.bind(seed(),output()); s=seed('S2'); s['sources']['extra']='An extra original.'
        b=c.bind(s,output()); queued=c.queue([a,b])
        self.assertEqual(len(queued),1); p=queued[0]
        self.assertEqual(p['seed_candidate_ids'],['S1','S2'])
        self.assertIn('extra',p['sources']); self.assertEqual(len(p['source_witnesses']),3)
        self.assertNotIn('extra',a['sources'])

    def test_scope_difference_not_merged_and_ties_keep_seed_order(self):
        a=c.bind(seed('S2'),output()); r=output();r['output']['scope']['conditions']='Only with safeguards'
        b=c.bind(seed('S1'),r); queued=c.queue([a,b])
        self.assertEqual([p['id'] for p in queued],['CP-S2','CP-S1'])

    def test_same_id_and_changed_source_identity_rejected(self):
        a=c.bind(seed(),output())
        with self.assertRaises(ValueError):c.queue([a,a])
        s=seed('S2');s['sources']['d']='Changed original';b=c.bind(s,output())
        with self.assertRaises(ValueError):c.queue([a,b])

    def test_request_size_budget_is_not_silent_truncation(self):
        s=seed();s['sources']['d']='x'*30000
        with self.assertRaises(ValueError):c.invocation(s)


if __name__=='__main__':unittest.main()
