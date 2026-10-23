from copy import deepcopy
import unittest

from commentscope.factory import direct_arguments as d,candidate_completion as c,grounded_factory
from tests.test_candidate_completion import argument
from tests import test_fresh_grounded_pipeline as fresh


class DirectArgumentTests(unittest.TestCase):
    def data(self):
        p,sources,_=argument()
        p['claims']={'C':p['claims']['C']}
        inv=d.inventory(p['claims']['C'],sources)
        nid=next(k for k,v in inv['nodes'].items() if 'Safety matters' in v['text'])
        chosen={'status':'selected','node_ids':[nid],'essential_node_ids':[nid]}
        return p,sources,inv,chosen

    def test_context_is_complete_and_core_repeat_not_selectable(self):
        p,s,inv,_=self.data();req=d.select_request(p['claims']['C'],s)
        for sid,parts in req['data']['SOURCE_SEGMENTS'].items():
            self.assertEqual(''.join(n['text'] for n in parts),s[sid])
        for n in inv['nodes'].values():
            self.assertEqual(n['text'],s[n['source_id']][n['start']:n['end']])
            if n['text'].strip()==p['claims']['C']['text'].strip():self.assertFalse(n['eligible'])

    def test_long_span_preserved_as_context_not_shortened(self):
        p,s,_,_=self.data();s['s0']+=' '+'x'*501
        inv=d.inventory(p['claims']['C'],s)
        self.assertTrue(any(len(n['text'])>500 and not n['eligible'] for n in inv['nodes'].values()))
        self.assertEqual(''.join(n['text'] for n in inv['source_segments']['s0']),s['s0'])

    def test_restatement_foreign_duplicate_and_free_text_are_rejected(self):
        p,s,inv,chosen=self.data()
        core=next(k for k,v in inv['nodes'].items() if not v['eligible'])
        for mutation in ({'node_ids':[core],'essential_node_ids':[]},
                         {'node_ids':['unknown'],'essential_node_ids':[]},
                         {'node_ids':chosen['node_ids']*2}, {'quote':'Invented'}):
            with self.assertRaises(ValueError):d.selection({'output':{**chosen,**mutation}},inv)

    def test_direct_edge_binds_current_target_and_one_original_author(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        typed=d.assemble(p,s,'value',chosen,{nid:'value'})
        self.assertEqual(typed['direct_links'][0]['to_target_sha256'],d.target_identity(p['claims']['C']))
        self.assertFalse(typed['semantic_approval'])
        rows=d.origin_details(typed,s,fresh.FreshGroundedPipelineTests().policy())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_id'],'s0')
        self.assertEqual(rows[0]['text'],s['s0']);self.assertEqual(rows[0]['claim']['text'],inv['nodes'][nid]['text'])

    def test_changed_claim_scope_type_ownership_or_source_fails(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        typed=d.assemble(p,s,'value',chosen,{nid:'value'})
        mutations=[lambda t:t['claims']['C'].update(text='Changed'),
                   lambda t:t['claims']['C']['scope'].update(time='new'),
                   lambda t:t['claims']['R1'].update(text='Rewritten'),
                   lambda t:t['claims']['R1'].update(kind='fact'),
                   lambda t:t['direct_links'][0].update(source_id='s1')]
        for mutate in mutations:
            t=deepcopy(typed);mutate(t)
            with self.assertRaises(ValueError):d.bound_inventory(t,s)
        changed={**s,'s0':s['s0']+' New context.'}
        with self.assertRaises(ValueError):d.bound_inventory(typed,changed)

    def test_selected_fact_and_core_dependency_preserved(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        typed=d.assemble(p,s,'value',chosen,{nid:'fact'})
        self.assertEqual(typed['claims']['C']['requires'],['R1'])
        self.assertEqual(grounded_factory.global_claims(typed)['C']['requires'],[p['id']+':R1'])
        d.bound_inventory(typed,s)
        typed['claims']['C']['requires']=[]
        with self.assertRaises(ValueError):d.bound_inventory(typed,s)

    def test_prior_fact_dependency_cannot_be_replaced_by_new_selection(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        p['claims']['C']['requires']=['prior_fact']
        with self.assertRaises(ValueError):d.assemble(p,s,'value',chosen,{nid:'value'})

    def test_existing_audit_policy_and_major_premise_gate_remain(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        typed=d.assemble(p,s,'value',chosen,{nid:'value'});req=d.audit_request(typed,s)
        self.assertTrue(req['system'].startswith(c.AUDIT_SYSTEM));self.assertEqual(req['data']['MEMBER_SOURCES'],s)
        good={'core_fidelity':'faithful','core_kind_matches':True,'major_premises':'preserved',
              'grounds':[{'node_id':nid,'role':'reason_for_core','kind_matches':True}]}
        self.assertTrue(c.audit_passed(typed,{'output':good}))
        for key,value in [('major_premises','missing'),('core_fidelity','distorted')]:
            self.assertFalse(c.audit_passed(typed,{'output':{**good,key:value}}))

    def test_no_extraction_record_or_old_model_decision_is_required(self):
        p,s,inv,chosen=self.data();nid=chosen['node_ids'][0]
        p['historical_analysis']={'errors':['invalid_response']}
        req=d.select_request(p['claims']['C'],s)
        self.assertNotIn('historical_analysis',str(req));d.assemble(p,s,'value',chosen,{nid:'value'})


if __name__=='__main__':unittest.main()
